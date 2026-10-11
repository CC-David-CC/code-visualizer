"""Typed asynchronous Python SDK for the authenticated automation endpoint."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from code_visualizer.application.commands import TypedCommand, new_operation_id
from code_visualizer.application.messages import CommandAccepted, CommandResult, EventEnvelope
from code_visualizer.automation.protocol import (
    JSONRPC_VERSION,
    RpcError,
    checked_json,
    event_from_data,
    object_params,
    result_from_data,
)
from code_visualizer.automation.service import AccessMode
from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.project import Project
from code_visualizer.domain.projection import ProjectionDefinition
from code_visualizer.domain.semantic import ProjectionKind
from code_visualizer.persistence.decoding import project_from_data
from code_visualizer.persistence.serialization import projection_definition_to_data


@dataclass(frozen=True, slots=True)
class RemoteRpcError(RuntimeError):
    code: int
    message: str
    data: dict[str, JsonValue]

    def __str__(self) -> str:
        return f"{self.message} ({self.code})"


class AsyncRemoteClient:
    def __init__(
        self,
        endpoint: str,
        token: str,
        *,
        actor_id: str,
        mode: AccessMode = AccessMode.COMMIT,
    ) -> None:
        self.endpoint = endpoint
        self.token = token
        self.actor_id = actor_id
        self.mode = mode
        self._connection: ClientConnection | None = None
        self._receiver: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[JsonValue]] = {}
        self._next_id = 0
        self._send_lock = asyncio.Lock()
        self._events: list[EventEnvelope] = []
        self._subscribers: list[Callable[[EventEnvelope], None]] = []
        self._observed_revision = 0
        self._project_id = ""
        self._capabilities: dict[str, JsonValue] = {}

    @property
    def observed_revision(self) -> int:
        return self._observed_revision

    @property
    def project_id(self) -> str:
        return self._project_id

    @property
    def events(self) -> tuple[EventEnvelope, ...]:
        return tuple(self._events)

    @property
    def capabilities(self) -> dict[str, JsonValue]:
        return dict(self._capabilities)

    async def connect(self) -> AsyncRemoteClient:
        if self._connection is not None:
            return self
        self._connection = await connect(
            self.endpoint,
            additional_headers={"Authorization": f"Bearer {self.token}"},
            max_size=2 * 1024 * 1024,
            compression=None,
        )
        self._receiver = asyncio.create_task(self._receive_loop())
        try:
            initialized = await self.call(
                "service.initialize",
                {"actor_id": self.actor_id, "mode": self.mode.value},
            )
        except Exception:
            await self.close()
            raise
        if not isinstance(initialized, dict):
            raise RemoteRpcError(-32603, "Initialization returned invalid data", {})
        self._capabilities = initialized
        revision = initialized.get("revision")
        project_id = initialized.get("project_id")
        if isinstance(revision, int) and not isinstance(revision, bool):
            self._observed_revision = revision
        if isinstance(project_id, str):
            self._project_id = project_id
        return self

    async def __aenter__(self) -> AsyncRemoteClient:
        return await self.connect()

    async def __aexit__(self, *_args: object) -> None:
        await self.close()

    async def close(self) -> None:
        connection = self._connection
        self._connection = None
        if connection is not None:
            await connection.close()
        receiver = self._receiver
        self._receiver = None
        if receiver is not None:
            receiver.cancel()
            with contextlib.suppress(asyncio.CancelledError, ConnectionClosed):
                await receiver
        for future in self._pending.values():
            if not future.done():
                future.set_exception(RemoteRpcError(-32000, "Connection closed", {}))
        self._pending.clear()

    def subscribe_events(self, callback: Callable[[EventEnvelope], None]) -> Callable[[], None]:
        self._subscribers.append(callback)

        def unsubscribe() -> None:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

        return unsubscribe

    async def call(self, method: str, params: dict[str, JsonValue] | None = None) -> JsonValue:
        connection = self._connection
        if connection is None:
            raise RemoteRpcError(-32000, "Client is not connected", {})
        async with self._send_lock:
            self._next_id += 1
            request_id = self._next_id
            future: asyncio.Future[JsonValue] = asyncio.get_running_loop().create_future()
            self._pending[request_id] = future
            request = {
                "id": request_id,
                "jsonrpc": JSONRPC_VERSION,
                "method": method,
                "params": params or {},
            }
            try:
                await connection.send(
                    json.dumps(
                        request,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                )
            except Exception:
                self._pending.pop(request_id, None)
                raise
        return await future

    async def _receive_loop(self) -> None:
        connection = self._connection
        if connection is None:
            return
        close_error = RemoteRpcError(-32000, "Connection closed", {})
        try:
            async for raw in connection:
                if not isinstance(raw, str):
                    continue
                try:
                    message = object_params(json.loads(raw))
                    method = message.get("method")
                    if method == "service.event":
                        self._observe_event(event_from_data(message.get("params")))
                        continue
                    request_id = message.get("id")
                    if isinstance(request_id, bool) or not isinstance(request_id, int):
                        continue
                    future = self._pending.pop(request_id, None)
                    if future is None or future.done():
                        continue
                    raw_error = message.get("error")
                    if isinstance(raw_error, dict):
                        code = raw_error.get("code")
                        text = raw_error.get("message")
                        data = raw_error.get("data", {})
                        future.set_exception(
                            RemoteRpcError(
                                code if isinstance(code, int) else -32603,
                                text if isinstance(text, str) else "Remote error",
                                data if isinstance(data, dict) else {},
                            )
                        )
                    else:
                        future.set_result(checked_json(message.get("result")))
                except (json.JSONDecodeError, RpcError):
                    continue
        except ConnectionClosed:
            close_error = RemoteRpcError(
                -32001,
                f"Connection closed: {connection.close_reason or 'no reason'}",
                {"close_code": connection.close_code},
            )
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(close_error)

    def _observe_event(self, event: EventEnvelope) -> None:
        self._events.append(event)
        self._observed_revision = max(self._observed_revision, event.revision)
        for callback in tuple(self._subscribers):
            try:
                callback(event)
            except Exception:
                continue

    async def subscribe(self, *, since_revision: int | None = None) -> Project | None:
        result = await self.call(
            "service.subscribe",
            {
                "since_revision": (
                    self._observed_revision if since_revision is None else since_revision
                )
            },
        )
        data = object_params(result)
        raw_events = data.get("events", [])
        if isinstance(raw_events, list):
            for raw_event in raw_events:
                self._observe_event(event_from_data(raw_event))
        revision = data.get("revision")
        if isinstance(revision, int) and not isinstance(revision, bool):
            self._observed_revision = max(self._observed_revision, revision)
        if data.get("resync_required") is True:
            project = project_from_data(data.get("snapshot"))
            self._observed_revision = project.revision
            self._project_id = project.id
            return project
        return None

    async def snapshot(self) -> Project:
        project = project_from_data(await self.call("project.snapshot"))
        self._observed_revision = project.revision
        self._project_id = project.id
        return project

    async def submit(
        self,
        command: TypedCommand,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
        intent: str = "",
    ) -> CommandResult:
        operation = command.to_operation()
        result = result_from_data(
            await self.call(
                "command.execute",
                {
                    "command_type": operation.command_type,
                    "expected_revision": (
                        self._observed_revision if expected_revision is None else expected_revision
                    ),
                    "intent": intent,
                    "operation_id": operation_id or new_operation_id(),
                    "payload": operation.payload,
                },
            )
        )
        self._observe_result(result)
        return result

    async def transaction(
        self,
        commands: Sequence[TypedCommand],
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
        intent: str = "",
    ) -> CommandResult:
        revision = self._observed_revision if expected_revision is None else expected_revision
        payload_commands: list[JsonValue] = []
        for command in commands:
            operation = command.to_operation()
            payload_commands.append(
                {
                    "command_type": operation.command_type,
                    "expected_revision": revision,
                    "operation_id": new_operation_id(),
                    "payload": operation.payload,
                }
            )
        result = result_from_data(
            await self.call(
                "command.transaction",
                {
                    "commands": payload_commands,
                    "expected_revision": revision,
                    "intent": intent,
                    "operation_id": operation_id or new_operation_id(),
                },
            )
        )
        self._observe_result(result)
        return result

    async def propose(
        self,
        command: TypedCommand,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
        intent: str = "",
    ) -> dict[str, JsonValue]:
        operation = command.to_operation()
        result = await self.call(
            "proposal.create",
            {
                "command": {
                    "command_type": operation.command_type,
                    "expected_revision": (
                        self._observed_revision if expected_revision is None else expected_revision
                    ),
                    "intent": intent,
                    "operation_id": operation_id or new_operation_id(),
                    "payload": operation.payload,
                }
            },
        )
        return object_params(result)

    async def accept_proposal(
        self,
        proposal_id: str,
        *,
        operation_id: str | None = None,
    ) -> CommandResult:
        result = result_from_data(
            await self.call(
                "proposal.accept",
                {
                    "operation_id": operation_id or new_operation_id(),
                    "proposal_id": proposal_id,
                },
            )
        )
        self._observe_result(result)
        return result

    async def reject_proposal(self, proposal_id: str) -> dict[str, JsonValue]:
        return object_params(
            await self.call(
                "proposal.reject",
                {"proposal_id": proposal_id},
            )
        )

    async def list_proposals(self) -> tuple[dict[str, JsonValue], ...]:
        result = await self.call("proposal.list")
        if not isinstance(result, list):
            raise RemoteRpcError(-32603, "Proposal list returned invalid data", {})
        return tuple(object_params(item) for item in result)

    async def update_presence(
        self,
        *,
        selection: tuple[str, ...] = (),
        preview: str = "",
    ) -> EventEnvelope:
        return event_from_data(
            await self.call(
                "service.presence",
                {"preview": preview, "selection": list(selection)},
            )
        )

    async def undo(self, *, operation_id: str | None = None) -> CommandResult:
        result = result_from_data(
            await self.call(
                "history.undo",
                {
                    "expected_revision": self._observed_revision,
                    "operation_id": operation_id or new_operation_id(),
                },
            )
        )
        self._observe_result(result)
        return result

    async def preview_undo(self) -> dict[str, JsonValue]:
        return object_params(await self.call("history.preview_undo"))

    async def redo(self, *, operation_id: str | None = None) -> CommandResult:
        result = result_from_data(
            await self.call(
                "history.redo",
                {
                    "expected_revision": self._observed_revision,
                    "operation_id": operation_id or new_operation_id(),
                },
            )
        )
        self._observe_result(result)
        return result

    async def preview_redo(self) -> dict[str, JsonValue]:
        return object_params(await self.call("history.preview_redo"))

    async def validate(self, *, diagram_id: str | None = None) -> JsonValue:
        if diagram_id is None:
            return await self.call("validate.project")
        return await self.call("validate.diagram", {"diagram_id": diagram_id})

    async def generate_preview(self) -> dict[str, JsonValue]:
        return object_params(await self.call("generate.preview"))

    async def search(self, query: str) -> JsonValue:
        return await self.call("search.query", {"query": query})

    async def list_operations(self) -> tuple[dict[str, JsonValue], ...]:
        result = await self.call("service.operations")
        if not isinstance(result, list):
            raise RemoteRpcError(-32603, "Operation discovery returned invalid data", {})
        return tuple(object_params(item) for item in result)

    async def invoke_capability(
        self,
        capability_id: str,
        inputs: dict[str, JsonValue] | None = None,
    ) -> JsonValue:
        """Invoke one operation discovered through :meth:`list_operations`."""

        if not capability_id:
            raise ValueError("capability_id must not be empty")
        return await self.call(
            "capability.invoke",
            {"capability_id": capability_id, "inputs": inputs or {}},
        )

    async def semantic_object(self, object_id: str) -> dict[str, JsonValue] | None:
        result = await self.call("query.semantic_object", {"object_id": object_id})
        return None if result is None else object_params(result)

    async def semantic_children(self, namespace_id: str) -> tuple[dict[str, JsonValue], ...]:
        result = await self.call("query.children", {"namespace_id": namespace_id})
        if not isinstance(result, list):
            raise RemoteRpcError(-32603, "Semantic children returned invalid data", {})
        return tuple(object_params(item) for item in result)

    async def semantic_relations(
        self,
        query: str,
        object_id: str,
    ) -> tuple[dict[str, JsonValue], ...]:
        parameters = {
            "callers": "function_id",
            "references": "symbol_id",
            "control_flow": "function_id",
            "data_dependencies": "operation_id",
        }
        key = parameters.get(query)
        if key is None:
            raise ValueError(f"Unknown semantic relation query {query!r}")
        result = await self.call(f"query.{query}", {key: object_id})
        if not isinstance(result, list):
            raise RemoteRpcError(-32603, "Semantic relations returned invalid data", {})
        return tuple(object_params(item) for item in result)

    async def projection(
        self,
        kind: ProjectionKind | str,
        *,
        root_id: str | None = None,
    ) -> dict[str, JsonValue]:
        resolved = kind.value if isinstance(kind, ProjectionKind) else kind
        return object_params(
            await self.call(
                "query.projection",
                {"kind": resolved, "root_id": root_id},
            )
        )

    async def projection_definitions(self) -> tuple[dict[str, JsonValue], ...]:
        result = await self.call("query.projection_definitions")
        if not isinstance(result, list):
            raise RemoteRpcError(-32603, "Projection definitions returned invalid data", {})
        return tuple(object_params(item) for item in result)

    async def compose_projection(
        self,
        definition: ProjectionDefinition,
    ) -> dict[str, JsonValue]:
        return object_params(
            await self.call(
                "query.compose_projection",
                {"definition": projection_definition_to_data(definition)},
            )
        )

    async def runtime_active(self) -> dict[str, JsonValue] | None:
        result = await self.call("runtime.active")
        return None if result is None else object_params(result)

    async def runtime_sessions(self) -> tuple[dict[str, JsonValue], ...]:
        result = await self.call("runtime.sessions")
        if not isinstance(result, list):
            raise RemoteRpcError(-32603, "Runtime session list returned invalid data", {})
        return tuple(object_params(item) for item in result)

    async def runtime_history(
        self,
        execution_session_id: str | None = None,
    ) -> tuple[dict[str, JsonValue], ...]:
        result = await self.call(
            "runtime.history",
            {"execution_session_id": execution_session_id},
        )
        if not isinstance(result, list):
            raise RemoteRpcError(-32603, "Runtime history returned invalid data", {})
        return tuple(object_params(item) for item in result)

    async def reveal(self, diagram_id: str, object_id: str | None = None) -> None:
        await self.call(
            "navigation.reveal",
            {"diagram_id": diagram_id, "object_id": object_id},
        )

    def _observe_result(self, result: CommandResult) -> None:
        revision = (
            result.revision if isinstance(result, CommandAccepted) else result.current_revision
        )
        self._observed_revision = max(self._observed_revision, revision)
