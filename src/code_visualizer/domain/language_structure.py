"""Bounded traversal of authored rule ownership, independent from interpretation."""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import fields, is_dataclass
from enum import StrEnum
from functools import cache
from types import UnionType
from typing import TypeAliasType, cast, get_args, get_origin, get_type_hints

from code_visualizer.domain import language as language_types
from code_visualizer.domain import notation_syntax
from code_visualizer.domain.language import AuthoredDomainLanguage, AuthoredTransformation
from code_visualizer.domain.notation import (
    NotationColumn,
    NotationDefinition,
    NotationEdgeRule,
    NotationField,
    NotationNodeRule,
)
from code_visualizer.domain.transformation import Representation, TransformationDefinition

_RECORDS = (
    *(
        record
        for record in vars(language_types).values()
        if isinstance(record, type)
        and is_dataclass(record)
        and record.__module__ == language_types.__name__
    ),
    NotationColumn,
    NotationDefinition,
    NotationEdgeRule,
    NotationField,
    NotationNodeRule,
    Representation,
    TransformationDefinition,
    *notation_syntax.NOTATION_SYNTAX_RECORDS,
)


@cache
def _slot_types(record_name: str) -> dict[str, object]:
    # These annotations belong to fixed host dataclasses, never project text.
    record = next(record for record in _RECORDS if record.__name__ == record_name)
    return cast(dict[str, object], get_type_hints(record))


def _choices(expected: object) -> tuple[object, ...]:
    if isinstance(expected, TypeAliasType):
        return _choices(expected.__value__)
    if get_origin(expected) is UnionType:
        return tuple(choice for member in get_args(expected) for choice in _choices(member))
    return (expected,)


def validate_language_slots(language: AuthoredDomainLanguage) -> None:
    """Reject invalid direct Python DTO construction before it enters an authority.

    This validates inert shapes only. A hole or a well-typed but unfinished rule is
    accepted; schema/type semantics are reported separately by the language checker.
    """

    pending: list[tuple[object, object, str, int]] = [(language, AuthoredDomainLanguage, "$", 0)]
    remaining_values, remaining_text = 100_000, 1_000_000
    while pending:
        value, expected, path, depth = pending.pop()
        remaining_values -= 1
        if isinstance(value, str):
            remaining_text -= len(value)
        if remaining_values < 0 or remaining_text < 0 or depth > 128:
            raise ValueError(f"{path}: authored language exceeds structural or text limits")
        choices = _choices(expected)
        if value is None and type(None) in choices:
            continue
        if type(value) in (str, bool, int, float) and type(value) in choices:
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"{path}: language numbers must be finite")
            continue
        if isinstance(value, StrEnum) and type(value) in choices:
            continue
        tuple_type = next((choice for choice in choices if get_origin(choice) is tuple), None)
        if isinstance(value, tuple) and tuple_type is not None:
            arguments = get_args(tuple_type)
            if len(arguments) != 2 or arguments[1] is not Ellipsis:
                raise ValueError(f"{path}: unsupported tuple slot")
            if len(value) + len(pending) > remaining_values:
                raise ValueError(f"{path}: authored language exceeds structural limits")
            pending.extend(
                (item, arguments[0], f"{path}[{index}]", depth + 1)
                for index, item in enumerate(value)
            )
            continue
        record = type(value)
        if record in _RECORDS and record in choices and is_dataclass(value):
            annotations = _slot_types(record.__name__)
            pending.extend(
                (
                    getattr(value, field.name),
                    annotations[field.name],
                    f"{path}.{field.name}",
                    depth + 1,
                )
                for field in fields(value)
            )
            continue
        raise ValueError(
            f"{path}: {type(value).__name__} does not match its declared language slot"
        )


def language_records(language: AuthoredDomainLanguage) -> Iterator[tuple[str, object, str | None]]:
    """Yield globally owned IDs; column IDs and representation IDs are local/references."""
    pending: list[tuple[object, str | None, int]] = [(language, None, 0)]
    count = 0
    while pending:
        value, parent_id, depth = pending.pop()
        count += 1
        if count > 100_000 or depth > 128:
            raise ValueError("Authored language exceeds structural limits")
        if isinstance(value, tuple):
            pending.extend((item, parent_id, depth + 1) for item in reversed(value))
        elif isinstance(value, AuthoredTransformation):
            yield value.definition.id, value.definition, parent_id
            pending.append((value.domain, value.definition.id, depth + 1))
            pending.append((value.functions, value.definition.id, depth + 1))
        elif is_dataclass(value) and not isinstance(value, type):
            identity = getattr(value, "id", None)
            owned = type(value).__module__ in {
                language_types.__name__,
                notation_syntax.__name__,
            } or isinstance(value, (NotationDefinition, TransformationDefinition))
            if owned and isinstance(identity, str):
                yield identity, value, parent_id
                parent_id = identity
            pending.extend(
                (getattr(value, field.name), parent_id, depth + 1)
                for field in reversed(fields(value))
                if field.name != "id"
            )


def language_owned_ids(language: AuthoredDomainLanguage) -> tuple[str, ...]:
    return tuple(identity for identity, _value, _parent in language_records(language))
