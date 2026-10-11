"""MCP tool adapter that delegates exclusively to the semantic remote API."""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from typing import cast

from code_visualizer.application.commands import new_operation_id
from code_visualizer.application.git_service import GIT_READ_METHODS, GIT_WRITE_METHODS
from code_visualizer.automation.protocol import JSONRPC_VERSION, object_params
from code_visualizer.domain.common import JsonValue
from code_visualizer.sdk.remote import AsyncRemoteClient, RemoteRpcError

MCP_PROTOCOL_VERSION = "2025-06-18"
MAX_MCP_LINE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class McpToolDefinition:
    name: str
    description: str
    input_schema: dict[str, JsonValue]

    def to_data(self) -> dict[str, JsonValue]:
        return {
            "description": self.description,
            "inputSchema": self.input_schema,
            "name": self.name,
        }


def _object_schema(
    properties: dict[str, JsonValue],
    *,
    required: tuple[str, ...] = (),
) -> dict[str, JsonValue]:
    schema: dict[str, JsonValue] = {
        "additionalProperties": False,
        "properties": properties,
        "type": "object",
    }
    if required:
        schema["required"] = list(required)
    return schema


MCP_TOOLS: tuple[McpToolDefinition, ...] = (
    McpToolDefinition(
        "git_operation",
        "Inspect or explicitly operate on the current project's real Git repository. "
        "Writes require commit mode and granted permissions; worktree reloads retire the endpoint.",
        _object_schema(
            {
                "operation": {
                    "type": "string",
                    "enum": [
                        cast(JsonValue, item)
                        for item in sorted(GIT_READ_METHODS | GIT_WRITE_METHODS)
                    ],
                },
                "params": {"type": "object"},
            },
            required=("operation",),
        ),
    ),
    McpToolDefinition(
        "project_snapshot",
        "Read the canonical typed project snapshot and current revision.",
        _object_schema({}),
    ),
    McpToolDefinition(
        "list_diagrams",
        "List document IDs, titles, and the three semantic document modes.",
        _object_schema({}),
    ),
    McpToolDefinition(
        "list_drakon_insertions",
        "List semantic insertion references on real horizontal and vertical DRAKON routes.",
        _object_schema(
            {"diagram_id": {"type": "string"}},
            required=("diagram_id",),
        ),
    ),
    McpToolDefinition(
        "semantic_object",
        "Resolve one stable semantic object without inspecting persistence dataclasses.",
        _object_schema(
            {"object_id": {"type": "string"}},
            required=("object_id",),
        ),
    ),
    McpToolDefinition(
        "semantic_projection",
        "Read an architecture, call, control-flow, data-flow, or concept projection.",
        _object_schema(
            {
                "kind": {
                    "enum": ["architecture", "calls", "control", "data", "concepts"],
                    "type": "string",
                },
                "root_id": {"type": ["string", "null"]},
            },
            required=("kind",),
        ),
    ),
    McpToolDefinition(
        "list_projection_definitions",
        "List author-created visual lenses stored with the project.",
        _object_schema({}),
    ),
    McpToolDefinition(
        "compose_semantic_projection",
        "Preview a no-code projection definition without changing the project.",
        _object_schema(
            {"definition": {"type": "object"}},
            required=("definition",),
        ),
    ),
    McpToolDefinition(
        "discover_operations",
        "List registered analysis, generation, execution, layout, export, and view capabilities.",
        _object_schema({}),
    ),
    McpToolDefinition(
        "active_runtime",
        "Inspect the active revision-pinned debugger value graph, if one exists.",
        _object_schema({}),
    ),
    McpToolDefinition(
        "runtime_history",
        "Inspect the bounded execution timeline for the active or named debugger session.",
        _object_schema({"execution_session_id": {"type": ["string", "null"]}}),
    ),
    McpToolDefinition(
        "semantic_command",
        "Commit one typed semantic command with an operation ID and optimistic revision.",
        _object_schema(
            {
                "command_type": {"type": "string"},
                "expected_revision": {"type": "integer"},
                "intent": {"type": "string"},
                "operation_id": {"type": "string"},
                "payload": {"type": "object"},
            },
            required=("command_type", "payload"),
        ),
    ),
    McpToolDefinition(
        "propose_semantic_command",
        "Preview a typed semantic command as a human-reviewable diff without committing it.",
        _object_schema(
            {
                "command_type": {"type": "string"},
                "expected_revision": {"type": "integer"},
                "intent": {"type": "string"},
                "operation_id": {"type": "string"},
                "payload": {"type": "object"},
            },
            required=("command_type", "payload"),
        ),
    ),
    McpToolDefinition(
        "validate_project",
        "Return structured diagnostics without executing project Python.",
        _object_schema({}),
    ),
    McpToolDefinition(
        "generate_preview",
        "Return deterministic in-memory generated Python and source mappings.",
        _object_schema({}),
    ),
    McpToolDefinition(
        "search_project",
        "Search semantic text and return object IDs and normalized model paths.",
        _object_schema({"query": {"type": "string"}}, required=("query",)),
    ),
    McpToolDefinition(
        "update_presence",
        "Publish the agent's selection and bounded preview so the human can see its focus.",
        _object_schema(
            {
                "preview": {"type": "string"},
                "selection": {"items": {"type": "string"}, "type": "array"},
            }
        ),
    ),
    McpToolDefinition(
        "undo_my_last_command",
        "Undo the latest compatible command by this actor; conflicts are never overwritten.",
        _object_schema({"operation_id": {"type": "string"}}),
    ),
)


class McpServerAdapter:
    def __init__(self, client: AsyncRemoteClient) -> None:
        self.client = client

    async def call_tool(self, name: str, raw_arguments: object) -> dict[str, JsonValue]:
        arguments = object_params(raw_arguments)
        try:
            result = await self._dispatch_tool(name, arguments)
            text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
            rejected = isinstance(result, dict) and result.get("status") == "rejected"
            return {"content": [{"text": text, "type": "text"}], "isError": rejected}
        except (RemoteRpcError, ValueError) as exc:
            error = (
                {
                    "code": exc.code,
                    "data": exc.data,
                    "message": exc.message,
                }
                if isinstance(exc, RemoteRpcError)
                else {"code": "INVALID_TOOL_ARGUMENT", "message": str(exc)}
            )
            return {
                "content": [
                    {
                        "text": json.dumps(error, ensure_ascii=False, sort_keys=True),
                        "type": "text",
                    }
                ],
                "isError": True,
            }

    async def _dispatch_tool(
        self,
        name: str,
        arguments: dict[str, JsonValue],
    ) -> JsonValue:
        if name == "git_operation":
            operation = arguments.get("operation")
            if (
                not isinstance(operation, str)
                or operation not in GIT_READ_METHODS | GIT_WRITE_METHODS
            ):
                raise ValueError("Choose a supported Git operation")
            return await self.client.call(
                f"git.{operation}", object_params(arguments.get("params", {}))
            )
        if name == "project_snapshot":
            return await self.client.call("project.snapshot")
        if name == "list_diagrams":
            return await self.client.call("project.list_diagrams")
        if name == "list_drakon_insertions":
            return await self.client.call("drakon.list_insertions", arguments)
        if name == "semantic_object":
            return await self.client.call("query.semantic_object", arguments)
        if name == "semantic_projection":
            return await self.client.call("query.projection", arguments)
        if name == "list_projection_definitions":
            return await self.client.call("query.projection_definitions")
        if name == "compose_semantic_projection":
            return await self.client.call("query.compose_projection", arguments)
        if name == "discover_operations":
            return await self.client.call("service.operations")
        if name == "active_runtime":
            return await self.client.call("runtime.active")
        if name == "runtime_history":
            return await self.client.call("runtime.history", arguments)
        if name in {"semantic_command", "propose_semantic_command"}:
            command = dict(arguments)
            command.setdefault("expected_revision", self.client.observed_revision)
            command.setdefault("operation_id", new_operation_id())
            command.setdefault("intent", "MCP semantic edit")
            if name == "semantic_command":
                return await self.client.call("command.execute", command)
            return await self.client.call("proposal.create", {"command": command})
        if name == "validate_project":
            return await self.client.call("validate.project")
        if name == "generate_preview":
            return await self.client.call("generate.preview")
        if name == "search_project":
            return await self.client.call("search.query", arguments)
        if name == "update_presence":
            return await self.client.call("service.presence", arguments)
        if name == "undo_my_last_command":
            params = {
                "expected_revision": self.client.observed_revision,
                "operation_id": arguments.get("operation_id", new_operation_id()),
            }
            return await self.client.call("history.undo", params)
        raise ValueError(f"Unknown MCP tool {name!r}")

    async def handle_jsonrpc(self, raw_request: object) -> dict[str, JsonValue] | None:
        request = object_params(raw_request)
        request_id = request.get("id")
        method = request.get("method")
        if method == "notifications/initialized":
            return None
        if method == "initialize":
            result: JsonValue = {
                "capabilities": {"tools": {"listChanged": False}},
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "serverInfo": {"name": "code-visualizer", "version": "0.1.0"},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": [tool.to_data() for tool in MCP_TOOLS]}
        elif method == "tools/call":
            params = object_params(request.get("params", {}))
            name = params.get("name")
            if not isinstance(name, str):
                return self._error(request_id, -32602, "tools/call requires a tool name")
            result = await self.call_tool(name, params.get("arguments", {}))
        else:
            return self._error(request_id, -32601, f"Unknown MCP method {method!r}")
        if request_id is None:
            return None
        return {"id": request_id, "jsonrpc": JSONRPC_VERSION, "result": result}

    @staticmethod
    def _error(request_id: JsonValue, code: int, message: str) -> dict[str, JsonValue]:
        return {
            "error": {"code": code, "message": message},
            "id": request_id,
            "jsonrpc": JSONRPC_VERSION,
        }


async def run_mcp_stdio(adapter: McpServerAdapter) -> None:
    """Run bounded newline-delimited MCP stdio until the host closes stdin."""

    while True:
        line = await asyncio.to_thread(sys.stdin.buffer.readline, MAX_MCP_LINE_BYTES + 1)
        if not line:
            return
        if len(line) > MAX_MCP_LINE_BYTES:
            response: dict[str, JsonValue] = McpServerAdapter._error(
                None,
                -32700,
                "MCP message exceeds the safety limit",
            )
        else:
            try:
                decoded: object = json.loads(line)
                handled = await adapter.handle_jsonrpc(decoded)
                if handled is None:
                    continue
                response = handled
            except (json.JSONDecodeError, ValueError):
                response = McpServerAdapter._error(None, -32700, "Parse error")
        sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
        sys.stdout.flush()
