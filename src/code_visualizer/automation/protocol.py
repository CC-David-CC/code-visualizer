"""JSON-RPC 2.0 DTO validation and authority-envelope serialization."""

from __future__ import annotations

from dataclasses import dataclass

from code_visualizer.application.messages import (
    CommandAccepted,
    CommandDeferred,
    CommandEnvelope,
    CommandRejected,
    CommandResult,
    EventEnvelope,
)
from code_visualizer.domain.common import JsonValue

JSONRPC_VERSION = "2.0"
PROTOCOL_VERSION = 1
MAX_COLLECTION_ITEMS = 20_000
MAX_JSON_DEPTH = 40


@dataclass(frozen=True, slots=True)
class RpcError(Exception):
    code: int
    message: str
    data: dict[str, JsonValue] | None = None

    def __str__(self) -> str:
        return self.message


def checked_json(value: object, *, depth: int = 0) -> JsonValue:
    if depth > MAX_JSON_DEPTH:
        raise RpcError(-32602, "JSON value exceeds the nesting limit")
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, list):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise RpcError(-32602, "JSON array exceeds the item limit")
        return [checked_json(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) > MAX_COLLECTION_ITEMS or not all(isinstance(key, str) for key in value):
            raise RpcError(-32602, "JSON object has invalid or excessive keys")
        return {str(key): checked_json(item, depth=depth + 1) for key, item in value.items()}
    raise RpcError(-32602, f"Unsupported JSON value {type(value).__name__}")


def object_params(value: object) -> dict[str, JsonValue]:
    checked = checked_json(value)
    if not isinstance(checked, dict):
        raise RpcError(-32602, "Method params must be an object")
    return checked


def event_to_data(event: EventEnvelope) -> dict[str, JsonValue]:
    return {
        "actor_id": event.actor_id,
        "affected_ids": list(event.affected_ids),
        "event_type": event.event_type,
        "occurred_at": event.occurred_at,
        "operation_id": event.operation_id,
        "payload": event.payload,
        "project_id": event.project_id,
        "revision": event.revision,
        "schema_version": event.schema_version,
    }


def event_from_data(value: object) -> EventEnvelope:
    data = object_params(value)

    def text(key: str) -> str:
        item = data.get(key)
        if not isinstance(item, str):
            raise RpcError(-32602, f"Event {key} must be text")
        return item

    revision = data.get("revision")
    schema = data.get("schema_version", 1)
    payload = data.get("payload")
    affected = data.get("affected_ids", [])
    if (
        isinstance(revision, bool)
        or not isinstance(revision, int)
        or isinstance(schema, bool)
        or not isinstance(schema, int)
        or not isinstance(payload, dict)
        or not isinstance(affected, list)
        or not all(isinstance(item, str) for item in affected)
    ):
        raise RpcError(-32602, "Event numeric, payload, or affected fields are invalid")
    if schema != 1:
        raise RpcError(-32602, "Unsupported event envelope schema version")
    return EventEnvelope(
        event_type=text("event_type"),
        actor_id=text("actor_id"),
        operation_id=text("operation_id"),
        project_id=text("project_id"),
        revision=revision,
        payload=payload,
        schema_version=schema,
        occurred_at=text("occurred_at"),
        affected_ids=tuple(item for item in affected if isinstance(item, str)),
    )


def result_to_data(result: CommandResult) -> dict[str, JsonValue]:
    if isinstance(result, CommandAccepted):
        return {
            "affected_ids": list(result.affected_ids),
            "events": [event_to_data(event) for event in result.events],
            "revision": result.revision,
            "status": "accepted",
            "undo_group_id": result.undo_group_id,
        }
    return {
        "code": result.code,
        "current_revision": result.current_revision,
        "details": result.details,
        "message": result.message,
        "status": "deferred" if isinstance(result, CommandDeferred) else "rejected",
    }


def result_from_data(value: object) -> CommandResult:
    data = object_params(value)
    status = data.get("status")
    if status == "accepted":
        revision = data.get("revision")
        affected = data.get("affected_ids", [])
        events = data.get("events", [])
        undo_group = data.get("undo_group_id")
        if (
            isinstance(revision, bool)
            or not isinstance(revision, int)
            or not isinstance(affected, list)
            or not all(isinstance(item, str) for item in affected)
            or not isinstance(events, list)
            or not isinstance(undo_group, str)
        ):
            raise RpcError(-32602, "Accepted command result is invalid")
        return CommandAccepted(
            revision,
            tuple(item for item in affected if isinstance(item, str)),
            tuple(event_from_data(item) for item in events),
            undo_group,
        )
    if status in {"rejected", "deferred"}:
        code = data.get("code")
        message = data.get("message")
        revision = data.get("current_revision")
        details = data.get("details", {})
        if (
            not isinstance(code, str)
            or not isinstance(message, str)
            or isinstance(revision, bool)
            or not isinstance(revision, int)
            or not isinstance(details, dict)
        ):
            raise RpcError(-32602, "Rejected command result is invalid")
        result_type = CommandDeferred if status == "deferred" else CommandRejected
        return result_type(code, message, revision, details)
    raise RpcError(-32602, "Command result status is invalid")


def command_from_params(
    params: dict[str, JsonValue],
    *,
    actor_id: str,
    project_id: str,
    command_type: str | None = None,
) -> CommandEnvelope:
    resolved_type = command_type or params.get("command_type")
    operation_id = params.get("operation_id")
    expected_revision = params.get("expected_revision")
    payload = params.get("payload", {})
    intent = params.get("intent", "")
    schema_version = params.get("schema_version", 1)
    transaction_id = params.get("transaction_id")
    if type(schema_version) is not int or schema_version != 1:
        raise RpcError(-32602, "Unsupported command envelope schema version")
    if transaction_id is not None and not isinstance(transaction_id, str):
        raise RpcError(-32602, "transaction_id must be text or null")
    if not isinstance(resolved_type, str) or not resolved_type:
        raise RpcError(-32602, "command_type must be non-empty text")
    if not isinstance(operation_id, str) or not operation_id:
        raise RpcError(-32602, "operation_id must be non-empty text")
    if expected_revision is not None and (
        isinstance(expected_revision, bool) or not isinstance(expected_revision, int)
    ):
        raise RpcError(-32602, "expected_revision must be an integer or null")
    if not isinstance(payload, dict):
        raise RpcError(-32602, "payload must be an object")
    if not isinstance(intent, str):
        raise RpcError(-32602, "intent must be text")
    return CommandEnvelope(
        command_type=resolved_type,
        actor_id=actor_id,
        operation_id=operation_id,
        project_id=project_id,
        expected_revision=expected_revision,
        payload=payload,
        intent=intent,
        schema_version=schema_version,
        transaction_id=transaction_id,
    )


def success_response(request_id: JsonValue, result: JsonValue) -> dict[str, JsonValue]:
    return {"id": request_id, "jsonrpc": JSONRPC_VERSION, "result": result}


def error_response(request_id: JsonValue, error: RpcError) -> dict[str, JsonValue]:
    detail: dict[str, JsonValue] = {"code": error.code, "message": error.message}
    if error.data:
        detail["data"] = error.data
    return {"error": detail, "id": request_id, "jsonrpc": JSONRPC_VERSION}
