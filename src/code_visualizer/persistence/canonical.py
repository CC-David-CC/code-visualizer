"""Versioned semantic JSON bytes for local hashes, independent of wire encoding."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass

from code_visualizer.domain.common import JsonValue


@dataclass(frozen=True, slots=True)
class JsonObject:
    """Transient codec field inventory; never canonical project state."""

    fields: Mapping[str, EncodedJsonValue]


@dataclass(frozen=True, slots=True)
class JsonArray:
    """Single-use record stream owned by one serialization operation."""

    items: Iterable[EncodedJsonValue]


type EncodedJsonValue = JsonValue | JsonObject | JsonArray


def json_stream_data(value: EncodedJsonValue) -> JsonValue:
    if isinstance(value, JsonObject):
        return {key: json_stream_data(item) for key, item in value.fields.items()}
    if isinstance(value, JsonArray):
        return [json_stream_data(item) for item in value.items]
    return value


def json_object_data(value: JsonObject) -> dict[str, JsonValue]:
    return {key: json_stream_data(item) for key, item in value.fields.items()}


def _json_stream_tokens(value: EncodedJsonValue) -> Iterator[bytes]:
    """Encode inventories and records without retaining an entire JSON tree.

    The leaf encoder preserves the existing sorted/ASCII/finite-number contract.
    Array records are encoded and released one at a time, including nested arrays.
    """
    if isinstance(value, (JsonObject, dict)):
        fields = value.fields if isinstance(value, JsonObject) else value
        yield b"{"
        for index, key in enumerate(sorted(fields)):
            if index:
                yield b","
            yield canonical_data_bytes(key)
            yield b":"
            yield from _json_stream_tokens(fields[key])
        yield b"}"
    elif isinstance(value, (JsonArray, list)):
        items = value.items if isinstance(value, JsonArray) else value
        yield b"["
        for index, item in enumerate(items):
            if index:
                yield b","
            yield from _json_stream_tokens(item)
        yield b"]"
    else:
        # Scalars cannot traverse a large container. The native encoder avoids
        # constructing one cyclic iterencode closure graph per small leaf.
        yield canonical_data_bytes(value)


def json_stream_chunks(value: EncodedJsonValue) -> Iterator[bytes]:
    """Bound output chunks as well as the lifetime of temporary record data."""
    buffer = bytearray()
    bound = 64 * 1024
    for token in _json_stream_tokens(value):
        buffer.extend(token)
        while len(buffer) >= bound:
            yield bytes(buffer[:bound])
            del buffer[:bound]
    if buffer:
        yield bytes(buffer)


def canonical_data_bytes(value: JsonValue) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")
    ).encode("ascii")


def canonical_data_chunks(value: JsonValue) -> Iterator[bytes]:
    """The identical hash contract, traversed incrementally by host adapters.

    The C encoder used by dumps holds the GIL across a complete container.
    iterencode lets Python schedule the UI while an orchestration thread walks a
    large snapshot, and bounded byte chunks can feed a hash or resource stream.
    """
    encoder = json.JSONEncoder(
        sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")
    )
    parts: list[str] = []
    size, bound = 0, 64 * 1024
    for token in encoder.iterencode(value):
        length = len(token)
        if size + length < bound:
            parts.append(token)
            size += length
            continue
        offset = 0
        while offset < length:
            count = min(bound - size, length - offset)
            parts.append(token[offset : offset + count])
            offset += count
            size += count
            if size == bound:
                yield "".join(parts).encode("ascii")
                parts.clear()
                size = 0
    if parts:
        yield "".join(parts).encode("ascii")
