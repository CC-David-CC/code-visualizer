"""Closed, type-checked codecs for inert authored language definitions.

The record allowlist is application code. A project cannot request a Python import,
class lookup outside this list, callback, or expression evaluation during decoding.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import MISSING, fields, is_dataclass
from enum import StrEnum
from functools import cache
from types import UnionType
from typing import TypeAliasType, cast, get_args, get_origin, get_type_hints

from code_visualizer.domain import language as language_types
from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.language import (
    AuthoredDomainLanguage,
    AuthoredTransformation,
    ValidatorDefinition,
)
from code_visualizer.domain.notation import (
    NotationColumn,
    NotationDefinition,
    NotationEdgeRule,
    NotationField,
    NotationNodeRule,
)
from code_visualizer.domain.notation_syntax import NOTATION_SYNTAX_RECORDS
from code_visualizer.domain.transformation import Representation, TransformationDefinition


class LanguageDecodeError(ValueError):
    pass


# Only these statically imported records belong to this persistence language.
_RECORD_TYPES = (
    AuthoredDomainLanguage,
    AuthoredTransformation,
    ValidatorDefinition,
    language_types.QueryLiteral,
    language_types.QueryVariable,
    language_types.QueryNodes,
    language_types.QueryRole,
    language_types.QueryProperty,
    language_types.QueryIdentity,
    language_types.QueryUnary,
    language_types.QueryBinary,
    language_types.QueryTuple,
    language_types.QueryMap,
    language_types.QueryFilter,
    language_types.QueryAll,
    language_types.QueryUnique,
    language_types.QueryHole,
    language_types.RuntimeLiteral,
    language_types.RuntimeVariable,
    language_types.RuntimeBinary,
    language_types.RuntimeCall,
    language_types.RuntimeHole,
    language_types.TemplateSymbol,
    language_types.TemplateParameter,
    language_types.TemplateExpand,
    language_types.TemplateWhen,
    language_types.TemplateLet,
    language_types.TemplateAssignment,
    language_types.TemplateOutput,
    language_types.TemplateIf,
    language_types.TemplateFor,
    language_types.TemplateTransfer,
    language_types.TemplateHole,
    language_types.FunctionTemplate,
    language_types.DomainPropertyTemplate,
    language_types.DomainRoleTemplate,
    language_types.DomainNodeTemplate,
    language_types.DomainTemplate,
    NotationDefinition,
    NotationColumn,
    NotationEdgeRule,
    NotationField,
    NotationNodeRule,
    Representation,
    TransformationDefinition,
    *NOTATION_SYNTAX_RECORDS,
)
_RECORD_BY_TAG = {record.__name__: record for record in _RECORD_TYPES}
_MAX_DEPTH = 128
_MAX_VALUES = 100_000
_MAX_TEXT_CHARACTERS = 1_000_000


@cache
def _field_types(record: type[object]) -> dict[str, object]:
    # These are annotations from the fixed host record list, never project strings.
    return cast(dict[str, object], get_type_hints(record))


def _charge(value: object, depth: int, remaining: list[int]) -> None:
    remaining[0] -= 1
    if isinstance(value, str):
        remaining[1] -= len(value)
    if depth > _MAX_DEPTH or min(remaining) < 0:
        raise LanguageDecodeError("Language definition exceeds structural or text limits")


def _encode(value: object, depth: int, remaining: list[int]) -> JsonValue:
    _charge(value, depth, remaining)
    if isinstance(value, StrEnum):
        return value.value
    if value is None or type(value) in (str, bool, int):
        return cast(JsonValue, value)
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, tuple):
        return [_encode(item, depth + 1, remaining) for item in value]
    if type(value) in _RECORD_TYPES and is_dataclass(value) and not isinstance(value, type):
        return {
            "type": type(value).__name__,
            **{
                field.name: _encode(getattr(value, field.name), depth + 1, remaining)
                for field in fields(value)
            },
        }
    raise LanguageDecodeError(f"Value {type(value).__name__} is not authored language data")


def _decode(
    value: object,
    expected: object,
    path: str,
    depth: int,
    remaining: list[int],
) -> object:
    _charge(value, depth, remaining)
    if isinstance(expected, TypeAliasType):
        return _decode(value, expected.__value__, path, depth, remaining)
    origin = get_origin(expected)
    if origin is UnionType:
        choices = get_args(expected)
        if isinstance(value, dict) and isinstance(value.get("type"), str):
            record = _RECORD_BY_TAG.get(value["type"])
            if record in choices:
                return _decode(value, record, path, depth, remaining)
        for choice in choices:
            try:
                return _decode(value, choice, path, depth, remaining)
            except LanguageDecodeError:
                pass
        raise LanguageDecodeError(f"{path}: value does not match its declared slot type")
    if origin is tuple:
        if not isinstance(value, list):
            raise LanguageDecodeError(f"{path}: expected an array")
        arguments = get_args(expected)
        if len(arguments) != 2 or arguments[1] is not Ellipsis:
            raise LanguageDecodeError(f"{path}: unsupported fixed tuple slot")
        return tuple(
            _decode(item, arguments[0], f"{path}[{index}]", depth + 1, remaining)
            for index, item in enumerate(value)
        )
    if expected is type(None) and value is None:
        return None
    if expected in (str, bool, int) and type(value) is expected:
        return value
    if expected is float and type(value) in (int, float) and math.isfinite(cast(float, value)):
        return float(cast(float, value))
    if isinstance(expected, type) and issubclass(expected, StrEnum):
        if not isinstance(value, str):
            raise LanguageDecodeError(f"{path}: expected an enumerated value")
        try:
            return expected(value)
        except ValueError as exc:
            raise LanguageDecodeError(f"{path}: unknown {expected.__name__} value") from exc
    if isinstance(expected, type) and expected in _RECORD_TYPES:
        if not isinstance(value, dict) or value.get("type") != expected.__name__:
            raise LanguageDecodeError(f"{path}: expected {expected.__name__}")
        definitions = fields(expected)
        names = {field.name for field in definitions}
        if set(value) - names - {"type"}:
            raise LanguageDecodeError(f"{path}: unknown record fields")
        annotations = _field_types(expected)
        arguments_by_name = {}
        for field in definitions:
            if field.name not in value:
                if field.default is not MISSING or field.default_factory is not MISSING:
                    continue
                raise LanguageDecodeError(f"{path}.{field.name}: required field is missing")
            arguments_by_name[field.name] = _decode(
                value[field.name],
                annotations[field.name],
                f"{path}.{field.name}",
                depth + 1,
                remaining,
            )
        try:
            constructor = cast(Callable[..., object], expected)
            return constructor(**arguments_by_name)
        except (TypeError, ValueError) as exc:
            raise LanguageDecodeError(f"{path}: {exc}") from exc
    raise LanguageDecodeError(f"{path}: value does not match its declared scalar type")


def language_record_to_data(value: object) -> dict[str, JsonValue]:
    encoded = _encode(value, 0, [_MAX_VALUES, _MAX_TEXT_CHARACTERS])
    if not isinstance(encoded, dict):
        raise LanguageDecodeError("Expected an authored language record")
    # Validate typed constructor inputs too; a dataclass annotation alone is not a check.
    _decode(encoded, type(value), "$", 0, [_MAX_VALUES, _MAX_TEXT_CHARACTERS])
    return encoded


def language_record_from_data[T](value: object, expected: type[T]) -> T:
    return cast(T, _decode(value, expected, "$", 0, [_MAX_VALUES, _MAX_TEXT_CHARACTERS]))


def authored_language_to_data(value: AuthoredDomainLanguage) -> dict[str, JsonValue]:
    return language_record_to_data(value)


def authored_language_from_data(value: object) -> AuthoredDomainLanguage:
    if isinstance(value, dict) and "syntax_version" not in value:
        value = {**value, "syntax_version": 1}
    return language_record_from_data(value, AuthoredDomainLanguage)
