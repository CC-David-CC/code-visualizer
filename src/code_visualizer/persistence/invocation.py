"""Strict codecs for literal invocation values and explicit unresolved settings."""

from collections.abc import Mapping

from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.invocation import InvocationSpec
from code_visualizer.domain.invocation_arguments import (
    ArgumentDictionary,
    ArgumentEntry,
    ArgumentList,
    ArgumentTuple,
    ArgumentValue,
    ConfiguredArguments,
    InvocationArguments,
    InvocationKeyword,
    UnresolvedInvocationArguments,
    configured_arguments_from_text,
)
from code_visualizer.domain.program_kinds import CallableKind, MethodKind


def _value_data(value: ArgumentValue) -> JsonValue:
    if isinstance(value, (ArgumentList, ArgumentTuple)):
        return {
            "type": "list" if isinstance(value, ArgumentList) else "tuple",
            "items": [_value_data(item) for item in value.items],
        }
    if isinstance(value, ArgumentDictionary):
        return {
            "type": "dictionary",
            "entries": [
                {"key": item.key, "value": _value_data(item.value)} for item in value.entries
            ],
        }
    return value


def invocation_arguments_to_data(value: ConfiguredArguments) -> dict[str, JsonValue]:
    if isinstance(value, UnresolvedInvocationArguments):
        if not isinstance(value.text, str) or len(value.text) > 100_000:
            raise ValueError("Unresolved invocation notation must be bounded text")
        return {"kind": "unresolved", "text": value.text}
    if not isinstance(value, InvocationArguments):
        raise ValueError("Configured arguments must be typed literal or unresolved values")
    return {
        "kind": "literal",
        "positional": [_value_data(item) for item in value.positional],
        "keywords": [
            {"name": item.name, "value": _value_data(item.value)} for item in value.keywords
        ],
    }


def _array(value: object) -> list[object]:
    if not isinstance(value, list) or len(value) > 10_000:
        raise ValueError("Invocation collection must be a bounded array")
    return value


def _record(value: object, names: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != names:
        raise ValueError("Invocation record has missing or unknown fields")
    return value


def _value(value: object, depth: int, budget: list[int]) -> ArgumentValue:
    budget[0] -= 1
    if depth > 32 or budget[0] < 0:
        raise ValueError("Invocation literal exceeds structural limits")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if not isinstance(value, dict):
        raise ValueError("Expected a typed invocation literal")
    if value.get("type") in {"list", "tuple"}:
        record = _record(value, {"type", "items"})
        items = tuple(_value(item, depth + 1, budget) for item in _array(record["items"]))
        return ArgumentList(items) if record["type"] == "list" else ArgumentTuple(items)
    record = _record(value, {"type", "entries"})
    if record["type"] != "dictionary":
        raise ValueError("Unknown invocation literal kind")
    entries = []
    for raw in _array(record["entries"]):
        entry = _record(raw, {"key", "value"})
        if not isinstance(entry["key"], str):
            raise ValueError("Invocation dictionary keys must be strings")
        entries.append(ArgumentEntry(entry["key"], _value(entry["value"], depth + 1, budget)))
    return ArgumentDictionary(tuple(entries))


def invocation_arguments_from_data(value: object) -> ConfiguredArguments:
    if isinstance(value, dict) and value.get("kind") == "unresolved":
        record = _record(value, {"kind", "text"})
        if not isinstance(record["text"], str) or len(record["text"]) > 100_000:
            raise ValueError("Unresolved invocation notation must be bounded text")
        return UnresolvedInvocationArguments(record["text"])
    record = _record(value, {"kind", "positional", "keywords"})
    if record["kind"] != "literal":
        raise ValueError("Unknown invocation argument kind")
    budget = [10_000]
    positional = tuple(_value(item, 0, budget) for item in _array(record["positional"]))
    keywords = []
    for raw in _array(record["keywords"]):
        item = _record(raw, {"name", "value"})
        if not isinstance(item["name"], str):
            raise ValueError("Invocation keyword name must be text")
        keywords.append(InvocationKeyword(item["name"], _value(item["value"], 0, budget)))
    return InvocationArguments(positional, tuple(keywords))


def migrate_legacy_invocation_operation(
    command_type: object, payload: dict[str, JsonValue], depth: int = 0
) -> dict[str, JsonValue]:
    """One-time format <=7 history cutover; live command decoding remains strict."""
    if depth > 32:
        raise ValueError("Legacy history operation exceeds nesting limits")
    if command_type == "python.replace_module_setup":
        text = payload.get("entrypoint_arguments", "")
        if isinstance(text, str):
            return {
                **payload,
                "entrypoint_arguments": invocation_arguments_to_data(
                    configured_arguments_from_text(text)
                ),
            }
    if command_type == "transaction":
        operations = payload.get("operations")
        if isinstance(operations, list):
            updated: list[JsonValue] = []
            for item in operations:
                if isinstance(item, dict) and isinstance(item.get("payload"), dict):
                    inner = item["payload"]
                    assert isinstance(inner, dict)
                    updated.append(
                        {
                            **item,
                            "payload": migrate_legacy_invocation_operation(
                                item.get("command_type"), inner, depth + 1
                            ),
                        }
                    )
                else:
                    updated.append(item)
            return {**payload, "operations": updated}
    return payload


def invocation_to_data(invocation: InvocationSpec) -> dict[str, JsonValue]:
    """Ephemeral transport representation; this is not canonical project persistence."""

    return {
        "identifier": invocation.identifier,
        "kind": invocation.kind.value,
        "owning_class": invocation.owning_class,
        "method_kind": invocation.method_kind.value if invocation.method_kind is not None else None,
        "arguments": invocation_arguments_to_data(invocation.arguments),
        "callable_id": invocation.callable_id,
    }


def invocation_from_data(value: object) -> InvocationSpec:
    """Decode one complete invocation and reject ambiguous or mistyped transport fields."""

    if isinstance(value, InvocationSpec):
        return value
    if not isinstance(value, Mapping):
        raise ValueError("An invocation must be a structured object")
    allowed = {"identifier", "kind", "owning_class", "method_kind", "arguments", "callable_id"}
    if set(value) - allowed:
        raise ValueError("Unknown invocation fields")

    def text(name: str, default: str | None = None) -> str:
        raw = value.get(name, default)
        if not isinstance(raw, str):
            raise ValueError(f"Invocation {name!r} must be text")
        return raw

    def optional_text(name: str) -> str | None:
        raw = value.get(name)
        if raw is not None and not isinstance(raw, str):
            raise ValueError(f"Invocation {name!r} must be text or null")
        return raw

    arguments = invocation_arguments_from_data(
        value.get("arguments", invocation_arguments_to_data(InvocationArguments()))
    )
    if not isinstance(arguments, InvocationArguments):
        raise ValueError("Unresolved argument notation cannot be executed")
    method = optional_text("method_kind")
    return InvocationSpec(
        text("identifier"),
        CallableKind(text("kind", CallableKind.SYNC.value)),
        optional_text("owning_class"),
        MethodKind(method) if method is not None else None,
        arguments,
        optional_text("callable_id"),
    )
