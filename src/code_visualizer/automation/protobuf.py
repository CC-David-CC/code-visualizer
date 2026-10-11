"""Binary command adapter over the same authenticated AutomationService dispatch."""

from __future__ import annotations

from code_visualizer.application.messages import CommandAccepted, CommandDeferred
from code_visualizer.automation.protocol import RpcError, result_from_data
from code_visualizer.automation.service import AutomationContext, AutomationService
from code_visualizer.domain.common import JsonValue
from code_visualizer.protocol.commands import command_from_proto
from code_visualizer.protocol.v1 import command_pb2 as wire
from code_visualizer.protocol.validation import ProtocolBoundaryError, parse_message

PROTOBUF_PROTOCOL = "protobuf.v1"


def dispatch_protobuf(
    service: AutomationService, payload: bytes, context: AutomationContext
) -> bytes:
    """Decode known commands, authenticate claimed identities, and reuse normal grants/history."""
    response = wire.CommandResponse(schema_version=1)
    try:
        encoded = parse_message(payload, wire.CommandEnvelope)
        response.operation_id = encoded.operation_id
        command = command_from_proto(encoded)
        if command.actor_id != context.actor_id:
            raise RpcError(-32003, "Protobuf actor does not match the authenticated session")
        if command.project_id != service.authority.snapshot().id:
            raise RpcError(-32602, "Protobuf command targets a different project")
        params: dict[str, JsonValue] = {
            "schema_version": command.schema_version,
            "command_type": command.command_type,
            "operation_id": command.operation_id,
            "expected_revision": command.expected_revision,
            "transaction_id": command.transaction_id,
            "intent": command.intent,
            "payload": command.payload,
        }
        method = (
            command.command_type
            if command.command_type in {"history.undo", "history.redo"}
            else "command.execute"
        )
        result = result_from_data(service.dispatch(method, params, context))
        if isinstance(result, CommandAccepted):
            response.accepted.CopyFrom(
                wire.CommandAccepted(
                    revision=result.revision,
                    affected_ids=result.affected_ids,
                    undo_group_id=result.undo_group_id,
                    events=[
                        wire.EventReceipt(
                            schema_version=e.schema_version,
                            event_type=e.event_type,
                            actor_id=e.actor_id,
                            operation_id=e.operation_id,
                            project_id=e.project_id,
                            revision=e.revision,
                            affected_ids=e.affected_ids,
                            occurred_at=e.occurred_at,
                        )
                        for e in result.events
                    ],
                )
            )
        elif isinstance(result, CommandDeferred):
            response.deferred.CopyFrom(
                wire.CommandDeferred(
                    code=result.code,
                    message=result.message,
                    current_revision=result.current_revision,
                    host_operation_id=str(result.details["operation_id"]),
                )
            )
        else:
            response.rejected.CopyFrom(
                wire.CommandRejected(
                    code=result.code,
                    message=result.message,
                    current_revision=result.current_revision,
                )
            )
    except RpcError as exc:
        response.error.CopyFrom(wire.ProtocolError(code=exc.code, message=exc.message))
    except (ProtocolBoundaryError, ValueError, OverflowError) as exc:
        response.error.CopyFrom(wire.ProtocolError(code=-32602, message=str(exc)))
    return response.SerializeToString(deterministic=True)
