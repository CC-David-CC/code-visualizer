"""Bounded inert record encoding shared by separately closed resource contracts."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, fields, is_dataclass
from typing import cast

from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.values import QuantityValue, ResourceReference, UnitReference
from code_visualizer.extensions.foundations.unit_algebra import QuantityKind
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.values import (
    canonical_value_from_data,
    canonical_value_to_data,
    unit_from_data,
    unit_to_data,
)


@dataclass(frozen=True, slots=True)
class RecordCodec:
    """Only composition-supplied constructors can interpret these version-1 bytes."""

    record_types: tuple[type, ...]
    byte_limit: int = 64 * 1024

    def __post_init__(self) -> None:
        if (
            not self.record_types
            or len({item.__name__ for item in self.record_types}) != len(self.record_types)
            or not all(is_dataclass(item) for item in self.record_types)
            or not 1 <= self.byte_limit <= 2 * 1024 * 1024
        ):
            raise ValueError("Closed records require distinct trusted types and a bounded envelope")

    def _encode(self, value: object) -> JsonValue:
        if isinstance(value, QuantityKind):
            return {"quantity_kind": value.value}
        if type(value) in (str, int, float, bool) or value is None:
            return cast(JsonValue, value)
        if isinstance(value, UnitReference):
            return {"unit": unit_to_data(value)}
        if isinstance(value, QuantityValue | ResourceReference):
            return canonical_value_to_data(value)
        if isinstance(value, tuple):
            return [self._encode(item) for item in value]
        if type(value) in self.record_types and is_dataclass(value) and not isinstance(value, type):
            return {
                "record": type(value).__name__,
                "fields": {
                    item.name: self._encode(getattr(value, item.name)) for item in fields(value)
                },
            }
        raise ValueError("Unknown closed metadata value")

    def _decode(self, value: object, depth: int = 0) -> object:
        if depth > 8:
            raise ValueError("Metadata exceeds its nesting bound")
        if type(value) in (str, int, float, bool) or value is None:
            return value
        if isinstance(value, list):
            if len(value) > 256:
                raise ValueError("Metadata exceeds its page bound")
            return tuple(self._decode(item, depth + 1) for item in value)
        if not isinstance(value, dict):
            raise ValueError("Unknown metadata value")
        if set(value) == {"quantity_kind"}:
            return QuantityKind(value["quantity_kind"])
        if set(value) == {"unit"}:
            return unit_from_data(value["unit"])
        if "$value" in value:
            return canonical_value_from_data(value)
        if set(value) != {"record", "fields"}:
            raise ValueError("Unknown fields in metadata")
        kind = next((item for item in self.record_types if item.__name__ == value["record"]), None)
        data = value["fields"]
        if (
            kind is None
            or not isinstance(data, dict)
            or set(data) != {item.name for item in fields(kind)}
        ):
            raise ValueError("Unknown record or missing/extra fields")
        constructor = cast(Callable[..., object], kind)
        return constructor(**{key: self._decode(item, depth + 1) for key, item in data.items()})

    def encode(self, value: object) -> bytes:
        payload = canonical_data_bytes({"version": 1, "value": self._encode(value)})
        if len(payload) > self.byte_limit:
            raise ValueError("Metadata exceeds its byte bound; publish another bounded page")
        return payload

    def decode[T](self, payload: bytes, expected: type[T]) -> T:
        if type(payload) is not bytes or len(payload) > self.byte_limit:
            raise ValueError("Metadata exceeds its byte bound")
        try:
            data = json.loads(payload)
            if not isinstance(data, dict) or set(data) != {"version", "value"}:
                raise ValueError("Unknown metadata envelope")
            if type(data["version"]) is not int or data["version"] != 1:
                raise ValueError("Unsupported metadata envelope version")
            value = self._decode(data["value"])
            if not isinstance(value, expected) or self.encode(value) != payload:
                raise ValueError("Metadata must have its exact type and canonical encoding")
            return value
        except (TypeError, KeyError, AttributeError, RecursionError) as exc:
            raise ValueError("Malformed closed metadata") from exc
