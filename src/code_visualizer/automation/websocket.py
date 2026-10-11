"""Authenticated JSON-RPC 2.0 over a loopback WebSocket endpoint."""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass

from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from code_visualizer.application.messages import EventEnvelope
from code_visualizer.automation.protobuf import PROTOBUF_PROTOCOL, dispatch_protobuf
from code_visualizer.automation.protocol import (
    JSONRPC_VERSION,
    RpcError,
    checked_json,
    error_response,
    event_to_data,
    object_params,
    success_response,
)
from code_visualizer.automation.service import (
    AccessMode,
    AutomationCapability,
    AutomationContext,
    AutomationService,
)
from code_visualizer.domain.boundaries import MAX_PORTABLE_ENVELOPE_BYTES
from code_visualizer.domain.common import JsonValue

MAX_RPC_MESSAGE_BYTES = MAX_PORTABLE_ENVELOPE_BYTES


def new_bearer_token() -> str:
    """Return a strong token that is also safe as a command-line argument."""

    return f"cvi_{secrets.token_urlsafe(32)}"


@dataclass(frozen=True, slots=True)
class AccessGrant:
    token: str
    capabilities: frozenset[AutomationCapability]


@dataclass(slots=True)
class _ConnectionState:
    connection: ServerConnection
    grant: AccessGrant
    context: AutomationContext | None = None
    subscribed: bool = False
    binary_protocol: str | None = None


class AutomationWebSocketServer:
    def __init__(
        self,
        service: AutomationService,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        grants: tuple[AccessGrant, ...] | None = None,
        allow_remote: bool = False,
        event_listener: Callable[[EventEnvelope], None] | None = None,
    ) -> None:
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise ValueError("Automation host must be a literal IP address") from exc
        if not address.is_loopback and not allow_remote:
            raise ValueError("Remote automation binding requires explicit allow_remote=True")
        if not 0 <= port <= 65_535:
            raise ValueError("port must be between 0 and 65535")
        default_grant = AccessGrant(
            new_bearer_token(),
            frozenset(AutomationCapability),
        )
        configured = grants or (default_grant,)
        if not configured or any(not grant.token for grant in configured):
            raise ValueError("At least one non-empty bearer grant is required")
        self.service = service
        self.host = host
        self.requested_port = port
        self.allow_remote = allow_remote
        self.grants = configured
        self._event_listener = event_listener
        self._server: Server | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._connections: dict[int, _ConnectionState] = {}
        self._authority_unsubscribe: Callable[[], None] | None = None
        self._broadcast_tasks: set[asyncio.Task[None]] = set()
        self.service.set_event_sink(self.publish_ephemeral)

    @property
    def token(self) -> str:
        return self.grants[0].token

    @property
    def port(self) -> int:
        server = self._server
        if server is None or not server.sockets:
            return self.requested_port
        return int(server.sockets[0].getsockname()[1])

    @property
    def endpoint(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"ws://{host}:{self.port}"

    @property
    def security_warning(self) -> str:
        return (
            "Remote binding enabled: protect the bearer token and network boundary."
            if self.allow_remote and not ipaddress.ip_address(self.host).is_loopback
            else "Loopback-only authenticated endpoint."
        )

    async def start(self) -> AutomationWebSocketServer:
        if self._server is not None:
            return self
        self._loop = asyncio.get_running_loop()
        self._server = await serve(
            self._handle,
            self.host,
            self.requested_port,
            max_size=MAX_RPC_MESSAGE_BYTES,
            compression=None,
            close_timeout=1,
            ping_interval=20,
            ping_timeout=20,
        )
        self._authority_unsubscribe = self.service.subscribe_authority(self.publish_authority)
        return self

    async def stop(self) -> None:
        await asyncio.to_thread(self.service.stop_executions)
        if self._authority_unsubscribe is not None:
            self._authority_unsubscribe()
            self._authority_unsubscribe = None
        connections = tuple(state.connection for state in self._connections.values())
        for connection in connections:
            await connection.close(code=1001, reason="Authority endpoint stopping")
        self._connections.clear()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        tasks = tuple(self._broadcast_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._broadcast_tasks.clear()
        self._loop = None

    def publish_authority(self, event: EventEnvelope) -> None:
        # The desktop already subscribes directly to canonical authority events.
        # Only ephemeral collaboration events need the optional UI listener.
        self._publish_from_any_thread(event, external=False)

    def publish_ephemeral(self, event: EventEnvelope) -> None:
        self._publish_from_any_thread(event, external=True)

    def _publish_from_any_thread(self, event: EventEnvelope, *, external: bool) -> None:
        if external and self._event_listener is not None:
            with contextlib.suppress(Exception):
                self._event_listener(event)
        loop = self._loop
        if loop is None or loop.is_closed():
            return

        def schedule() -> None:
            task = asyncio.create_task(self._broadcast_event(event))
            self._broadcast_tasks.add(task)
            task.add_done_callback(self._broadcast_tasks.discard)

        loop.call_soon_threadsafe(schedule)

    async def _broadcast_event(self, event: EventEnvelope) -> None:
        message = json.dumps(
            {
                "jsonrpc": JSONRPC_VERSION,
                "method": "service.event",
                "params": event_to_data(event),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        recipients = tuple(
            state.connection
            for state in self._connections.values()
            if state.subscribed and state.context is not None
        )
        if recipients:
            await asyncio.gather(
                *(self._safe_send(connection, message) for connection in recipients)
            )

    @staticmethod
    async def _safe_send(connection: ServerConnection, message: str) -> None:
        try:
            await connection.send(message)
        except ConnectionClosed:
            return

    def _grant_for(self, connection: ServerConnection) -> AccessGrant | None:
        request = connection.request
        authorization = request.headers.get("Authorization", "") if request is not None else ""
        prefix = "Bearer "
        if not authorization.startswith(prefix):
            return None
        provided = authorization[len(prefix) :]
        return next(
            (grant for grant in self.grants if secrets.compare_digest(grant.token, provided)),
            None,
        )

    async def _handle(self, connection: ServerConnection) -> None:
        grant = self._grant_for(connection)
        if grant is None:
            await connection.close(code=4401, reason="Bearer authentication required")
            return
        state = _ConnectionState(connection, grant)
        self._connections[id(connection)] = state
        try:
            async for raw in connection:
                if not isinstance(raw, str):
                    if state.context is None or state.binary_protocol != PROTOBUF_PROTOCOL:
                        await connection.close(
                            code=1003, reason="Initialize protobuf.v1 before binary commands"
                        )
                        return
                    binary_response = await asyncio.to_thread(
                        dispatch_protobuf, self.service, raw, state.context
                    )
                    await connection.send(binary_response)
                    continue
                response = await self._request(state, raw)
                if response is not None:
                    await connection.send(
                        json.dumps(
                            response,
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        )
                    )
        except ConnectionClosed:
            pass
        finally:
            removed = self._connections.pop(id(connection), None)
            if removed is not None and removed.context is not None:
                self._connection_presence(removed.context, connected=False)

    async def _request(
        self,
        state: _ConnectionState,
        raw: str,
    ) -> dict[str, JsonValue] | None:
        request_id: JsonValue = None
        try:
            try:
                decoded: object = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise RpcError(-32700, "Parse error") from exc
            request = object_params(decoded)
            if request.get("jsonrpc") != JSONRPC_VERSION:
                raise RpcError(-32600, "jsonrpc must be '2.0'")
            raw_id = request.get("id")
            if raw_id is not None and (
                isinstance(raw_id, bool) or not isinstance(raw_id, (str, int))
            ):
                raise RpcError(-32600, "Request id must be text, integer, or null")
            request_id = raw_id
            method = request.get("method")
            if not isinstance(method, str) or not method:
                raise RpcError(-32600, "Method must be non-empty text")
            params = request.get("params", {})
            result: JsonValue
            if method == "service.initialize":
                result = self._initialize(state, params)
            else:
                if state.context is None:
                    raise RpcError(-32002, "Call service.initialize first")
                result = await asyncio.to_thread(
                    self.service.dispatch,
                    method,
                    params,
                    state.context,
                )
                if method == "service.subscribe":
                    state.subscribed = True
                if isinstance(result, dict) and result.get("status") == "rejected":
                    code = result.get("code")
                    if code in {"REVISION_CONFLICT", "UNDO_CONFLICT"}:
                        self._conflict_presence(state.context, result)
            if request_id is None:
                return None
            return success_response(request_id, checked_json(result))
        except RpcError as exc:
            if state.context is not None and exc.code == -32003:
                self._permission_presence(state.context, exc)
            return error_response(request_id, exc)
        except Exception:
            return error_response(request_id, RpcError(-32603, "Internal error"))

    def _initialize(self, state: _ConnectionState, raw_params: object) -> dict[str, JsonValue]:
        if state.context is not None:
            raise RpcError(-32002, "Connection is already initialized")
        params = object_params(raw_params)
        actor_id = params.get("actor_id")
        raw_mode = params.get("mode", AccessMode.COMMIT.value)
        binary_protocol = params.get("binary_protocol")
        if binary_protocol is not None and binary_protocol != PROTOBUF_PROTOCOL:
            raise RpcError(-32602, "Unsupported binary protocol; supported: protobuf.v1")
        if (
            not isinstance(actor_id, str)
            or not actor_id.strip()
            or len(actor_id) > 100
            or not all(character.isalnum() or character in " ._@-" for character in actor_id)
        ):
            raise RpcError(-32602, "actor_id contains unsupported characters")
        try:
            mode = AccessMode(str(raw_mode))
        except ValueError as exc:
            raise RpcError(-32602, "mode must be proposal or commit") from exc
        context = AutomationContext(
            actor_id.strip(),
            f"connection_{secrets.token_hex(8)}",
            mode,
            state.grant.capabilities,
        )
        state.context = context
        state.binary_protocol = PROTOBUF_PROTOCOL if binary_protocol is not None else None
        self._connection_presence(context, connected=True)
        capabilities = self.service.dispatch("service.capabilities", {}, context)
        assert isinstance(capabilities, dict)
        return {
            **capabilities,
            "connection_id": context.connection_id,
            "binary_protocols": [PROTOBUF_PROTOCOL],
            "binary_protocol": state.binary_protocol,
        }

    def _connection_presence(self, context: AutomationContext, *, connected: bool) -> None:
        event = EventEnvelope.now(
            event_type="presence.connected" if connected else "presence.disconnected",
            actor_id=context.actor_id,
            operation_id=f"presence_{secrets.token_hex(8)}",
            project_id=self.service.authority.snapshot().id,
            revision=self.service.authority.revision,
            payload={
                "connection_id": context.connection_id,
                "mode": context.mode.value,
            },
        )
        self.publish_ephemeral(event)

    def _permission_presence(self, context: AutomationContext, error: RpcError) -> None:
        event = EventEnvelope.now(
            event_type="permission.rejected",
            actor_id=context.actor_id,
            operation_id=f"permission_{secrets.token_hex(8)}",
            project_id=self.service.authority.snapshot().id,
            revision=self.service.authority.revision,
            payload=error.data or {"message": error.message},
        )
        self.publish_ephemeral(event)

    def _conflict_presence(
        self,
        context: AutomationContext,
        result: dict[str, JsonValue],
    ) -> None:
        event = EventEnvelope.now(
            event_type="conflict.detected",
            actor_id=context.actor_id,
            operation_id=f"conflict_{secrets.token_hex(8)}",
            project_id=self.service.authority.snapshot().id,
            revision=self.service.authority.revision,
            payload=result,
        )
        self.publish_ephemeral(event)
