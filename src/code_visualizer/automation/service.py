"""Versioned semantic automation surface over one project authority."""

from __future__ import annotations

import difflib
import json
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, fields, is_dataclass, replace
from enum import Enum, StrEnum
from pathlib import Path
from threading import RLock
from typing import cast

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.capabilities import CapabilityKind
from code_visualizer.application.commands import Operation, new_operation_id
from code_visualizer.application.git import GitError
from code_visualizer.application.git_service import (
    GIT_READ_METHODS,
    GIT_WRITE_METHODS,
    GitProjectController,
)
from code_visualizer.application.invocations import invocation_for_document
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.messages import CommandAccepted, CommandEnvelope, EventEnvelope
from code_visualizer.application.queries import (
    projection_to_data,
    relation_to_data,
    semantic_object_to_data,
)
from code_visualizer.application.runtime_sessions import runtime_session_to_data
from code_visualizer.application.search import search_project
from code_visualizer.automation.protocol import (
    PROTOCOL_VERSION,
    RpcError,
    command_from_params,
    event_to_data,
    object_params,
    result_to_data,
)
from code_visualizer.domain.common import JsonValue, new_id
from code_visualizer.domain.drakon import DrakonDiagram, If, find_atom_location
from code_visualizer.domain.semantic import ProjectionKind
from code_visualizer.domain.values import (
    ComplexValue,
    QuantityValue,
    ResourceReference,
    TensorValue,
)
from code_visualizer.execution import RunResult, RunSession, TraceResult
from code_visualizer.generation import (
    BuildBlockedError,
    generate_python_project,
    generate_to_disk,
    load_generation_manifest,
)
from code_visualizer.persistence.decoding import projection_definition_from_data
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.serialization import (
    drakon_atom_to_data,
    normalized_project_json,
    project_to_data,
    projection_definition_to_data,
)
from code_visualizer.persistence.values import canonical_value_to_data
from code_visualizer.rendering import layout_drakon
from code_visualizer.validation import Diagnostic, Severity, assess_project


class AccessMode(StrEnum):
    PROPOSAL = "proposal"
    COMMIT = "commit"


class AutomationCapability(StrEnum):
    READ = "read"
    EDIT = "edit"
    PROPOSE = "propose"
    SAVE = "save"
    GENERATE = "generate"
    EXECUTE = "execute"
    DESTRUCTIVE = "destructive"
    ADMIN = "admin"


DEFAULT_CAPABILITIES = frozenset(
    {
        AutomationCapability.READ,
        AutomationCapability.EDIT,
        AutomationCapability.PROPOSE,
    }
)


def _capability_json_default(value: object) -> object:
    if isinstance(value, (ComplexValue, QuantityValue, TensorValue, ResourceReference)):
        return canonical_value_to_data(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: getattr(value, field.name) for field in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (set, frozenset)):
        return sorted(value, key=str)
    raise TypeError(f"Capability result {type(value).__name__} is not JSON serializable")


def _capability_json_value(value: object) -> JsonValue:
    encoded = json.dumps(value, default=_capability_json_default, ensure_ascii=False)
    return cast(JsonValue, json.loads(encoded))


@dataclass(frozen=True, slots=True)
class AutomationContext:
    actor_id: str
    connection_id: str
    mode: AccessMode
    capabilities: frozenset[AutomationCapability]


@dataclass(frozen=True, slots=True)
class Proposal:
    id: str
    actor_id: str
    base_revision: int
    command: CommandEnvelope
    created_order: int
    summary: str
    diff: str
    affected_ids: tuple[str, ...]


@dataclass(slots=True)
class ExecutionJob:
    id: str
    actor_id: str
    connection_id: str
    context: AutomationContext
    kind: str
    diagram_id: str | None
    session: RunSession
    status: str = "running"
    result: dict[str, JsonValue] | None = None


EventSink = Callable[[EventEnvelope], None]
RootProvider = Callable[[], Path | None]
SaveAsHandler = Callable[[Path], Path]


_DIRECT_COMMAND_METHODS = frozenset(
    {
        "diagram.create",
        "diagram.rename",
        "diagram.move",
        "diagram.duplicate",
        "diagram.delete",
        "drakon.insert",
        "drakon.replace",
        "drakon.remove",
        "drakon.move_block",
        "drakon.wrap",
        "drakon.unwrap",
        "mindmap.add_topic",
        "mindmap.update_topic",
        "mindmap.move_topic",
        "mindmap.remove_topic",
        "mindmap.add_cross_link",
        "mindmap.set_layout",
        "view.set_anchor",
        "semantic.concept.put",
        "semantic.concept.delete",
        "semantic.relation.put",
        "semantic.relation.delete",
        "projection.put",
        "projection.delete",
        "projection.materialize",
        "freeform.create",
        "freeform.transform",
        "freeform.remove",
        "freeform.connect",
        "freeform.set_properties",
        "freeform.arrange",
        "freeform.layer.add",
        "freeform.layer.update",
        "freeform.layer.remove",
        "freeform.guide.add",
        "freeform.guide.remove",
        "freeform.canvas.configure",
        "program.function.set_owner",
        "program.function.replace_signature",
        "program.configure",
        "program.declaration.set_text",
        "program.module.put",
        "program.module.delete",
        "program.class.put",
        "program.class.delete",
        "program.entrypoint.configure",
        "function.replace_spec",
        "program.function.create",
        "program.function.delete",
        "program.statement.insert",
        "program.statement.delete",
        "program.statement.move",
        "program.expression.replace",
        "program.symbol.rename",
        "python.configure_runtime",
        "domain.schema.put",
        "domain.language.put",
        "domain.language.delete",
        "domain.language.notation.put",
        "domain.language.notation.delete",
        "domain.language.validator.put",
        "domain.language.validator.delete",
        "domain.language.transformation.put",
        "domain.language.transformation.delete",
        "domain.schema.delete",
        "domain.schema.concept.put",
        "domain.schema.concept.delete",
        "domain.schema.property.put",
        "domain.schema.role.put",
        "domain.model.put",
        "domain.model.delete",
        "domain.node.create",
        "domain.node.delete",
        "domain.node.set_property",
        "domain.node.insert_child",
        "domain.node.move_child",
        "domain.node.remove_child",
        "domain.node.set_reference",
        "domain.node.remove_reference",
        "domain.bundle.put",
        "domain.bundle.delete",
    }
)


class AutomationService:
    """Application service used identically by WebSocket, CLI, and MCP adapters."""

    def __init__(
        self,
        authority: ProjectAuthority,
        *,
        project_root: RootProvider | None = None,
        save_as: SaveAsHandler | None = None,
        event_sink: EventSink | None = None,
        proposal_limit: int = 200,
        kernel: ProjectKernel | None = None,
        git: GitProjectController | None = None,
    ) -> None:
        if proposal_limit < 1:
            raise ValueError("proposal_limit must be positive")
        self.authority = authority
        if kernel is not None and kernel.authority is not authority:
            raise ValueError("kernel and authority must describe the same project")
        self._project_root = project_root or (lambda: None)
        root = self._project_root()
        self.kernel = kernel or ProjectKernel(
            authority,
            resource_store=None if root is None else ResourceStore(root),
            evidence_store=None if root is None else EvidenceStore(root),
        )
        self._owns_kernel = kernel is None
        self._save_as = save_as
        if git is not None and git.session.authority is not authority:
            raise ValueError("Git controller and authority must own the same project session")
        self._git = git
        self._event_sink = event_sink or (lambda _event: None)
        self._proposals: OrderedDict[str, Proposal] = OrderedDict()
        self._proposal_limit = proposal_limit
        self._proposal_order = 0
        self._execution_jobs: OrderedDict[str, ExecutionJob] = OrderedDict()
        self._execution_limit = 100
        self._lock = RLock()
        self._authority_sink: EventSink | None = None
        self._authority_unsubscribe: Callable[[], None] | None = None

    def subscribe_authority(self, sink: EventSink) -> Callable[[], None]:
        """Keep the endpoint's existing authority subscription attached on handoff."""
        with self._lock:
            self._unsubscribe_authority()
            self._authority_sink = sink
            self._authority_unsubscribe = self.authority.subscribe(sink)
        return self._unsubscribe_authority

    def _unsubscribe_authority(self) -> None:
        with self._lock:
            if self._authority_unsubscribe is not None:
                self._authority_unsubscribe()
            self._authority_unsubscribe = None
            self._authority_sink = None

    def _follow_git_session(self) -> None:
        if self._git is None or self.authority is self._git.session.authority:
            return
        self.stop_executions()
        if self._owns_kernel:
            self.kernel.close()
        sink = self._authority_sink
        self._unsubscribe_authority()
        self.authority = self._git.session.authority
        self.kernel = self._git.session.kernel
        self._owns_kernel = False
        self._project_root = lambda: self._git.session.root if self._git is not None else None
        # Revision numbers are local to a definition; proposals from another
        # branch cannot become valid merely because its revision is equal.
        self._proposals.clear()
        if sink is not None:
            self.subscribe_authority(sink)
        self._event_sink(
            EventEnvelope.now(
                event_type="session.replaced",
                actor_id="host",
                operation_id=new_operation_id(),
                project_id=self.authority.snapshot().id,
                revision=self.authority.revision,
                payload={"resync_required": True, "root": str(self._git.session.root)},
            )
        )

    def set_event_sink(self, sink: EventSink) -> None:
        self._event_sink = sink

    def close(self) -> None:
        self._unsubscribe_authority()
        self.stop_executions()
        if self._owns_kernel:
            self.kernel.close()

    def stop_executions(self) -> int:
        with self._lock:
            sessions = tuple(
                job.session for job in self._execution_jobs.values() if job.status == "running"
            )
        return sum(session.stop() for session in sessions)

    def dispatch(
        self,
        method: str,
        raw_params: object,
        context: AutomationContext,
    ) -> JsonValue:
        with self._lock:
            self._follow_git_session()
            return self._dispatch(method, raw_params, context)

    def _dispatch(
        self,
        method: str,
        raw_params: object,
        context: AutomationContext,
    ) -> JsonValue:
        params = object_params(raw_params)
        self._require_for_method(method, params, context)
        if method.startswith("git."):
            if self._git is None:
                raise RpcError(
                    -32010,
                    "The host has not attached a Git session controller",
                    {"code": "GIT_HOST_REQUIRED"},
                )
            try:
                result = _capability_json_value(self._git.execute(method, params))
                self._follow_git_session()
                return result
            except (GitError, OSError, RuntimeError) as exc:
                raise RpcError(
                    -32010, str(exc), {"code": getattr(exc, "code", "GIT_FAILED")}
                ) from exc
        if method == "service.capabilities":
            return self._capabilities(context)
        if method == "service.operations":
            return self._operation_capabilities()
        if method == "capability.invoke":
            return self._invoke_capability(params, context)
        if method == "service.subscribe":
            return self._subscribe(params, context)
        if method == "service.presence":
            return self._presence(params, context)
        if method == "project.snapshot":
            return project_to_data(self.authority.snapshot())
        if method == "project.list_diagrams":
            return self._list_diagrams()
        if method == "project.list_recent":
            return []
        if method == "project.save_as":
            return self._save_project_as(params, context)
        if method.startswith("query."):
            return self._query(method, params)
        if method == "runtime.active":
            active = self.kernel.runtime.active
            return None if active is None else runtime_session_to_data(active)
        if method == "runtime.sessions":
            return [runtime_session_to_data(item) for item in self.kernel.runtime.sessions()]
        if method == "runtime.history":
            raw_session_id = params.get("execution_session_id")
            if raw_session_id is not None and not isinstance(raw_session_id, str):
                raise RpcError(
                    -32602,
                    "execution_session_id must be a string or null",
                    {"code": "INVALID_PARAMS"},
                )
            return [
                runtime_session_to_data(item)
                for item in self.kernel.runtime.history(raw_session_id)
            ]
        if method in {"project.create", "project.open"}:
            raise RpcError(
                -32010,
                "This endpoint already owns one project; "
                "start another endpoint for another project",
                {"code": "PROJECT_ALREADY_OPEN"},
            )
        if method == "project.close":
            raise RpcError(
                -32010,
                "Only the authority host can close the active project",
                {"code": "PROJECT_HOST_OWNS_CLOSE"},
            )
        if method == "command.execute":
            return self._execute_command(params, context)
        if method == "command.transaction":
            return self._execute_transaction(params, context)
        if method in _DIRECT_COMMAND_METHODS or method in {
            "mindmap.reparent",
            "mindmap.reorder",
            "freeform.group",
            "object.set_text",
            "object.set_property",
            "object.set_layout_intent",
            "drakon.set_route_preference",
        }:
            return self._execute_semantic_method(method, params, context)
        if method == "drakon.list_insertions":
            return self._list_insertions(params)
        if method in {"history.preview_undo", "history.preview_redo"}:
            return self.authority.preview_history(
                actor_id=context.actor_id,
                redo=method.endswith("redo"),
            )
        if method == "history.undo":
            return self._history(params, context, redo=False)
        if method == "history.redo":
            return self._history(params, context, redo=True)
        if method == "proposal.create":
            return self._create_proposal(params, context)
        if method == "proposal.list":
            return [self._proposal_data(item) for item in self._proposals.values()]
        if method == "proposal.accept":
            return self._accept_proposal(params, context)
        if method == "proposal.reject":
            return self._reject_proposal(params, context)
        if method in {"validate.project", "validate.diagram"}:
            return self._validate(
                params,
                context,
                diagram_only=method.endswith("diagram"),
            )
        if method == "generate.preview":
            return self._generate_preview(context)
        if method == "generate.to_disk":
            return self._generate_to_disk(context)
        if method in {"test.run_diagram", "test.trace_diagram"}:
            return self._test_diagram(
                params,
                context,
                trace=method.endswith("trace_diagram"),
            )
        if method in {"test.stop", "run.stop"}:
            return self._stop_execution(params, context)
        if method in {"test.status", "run.status"}:
            return self._execution_status(params, context)
        if method == "run.project":
            return self._run_project(context)
        if method == "search.query":
            return self._search(params)
        if method == "navigation.reveal":
            return self._navigation(params, context)
        raise RpcError(-32601, f"Unknown method {method!r}")

    def _require(
        self,
        context: AutomationContext,
        capability: AutomationCapability,
    ) -> None:
        if (
            capability not in context.capabilities
            and AutomationCapability.ADMIN not in context.capabilities
        ):
            raise RpcError(
                -32003,
                f"Actor {context.actor_id!r} lacks {capability.value!r} capability",
                {"capability": capability.value, "code": "PERMISSION_DENIED"},
            )

    def _require_for_method(
        self,
        method: str,
        params: dict[str, JsonValue],
        context: AutomationContext,
    ) -> None:
        if method in {"service.capabilities"}:
            return
        self._require(context, AutomationCapability.READ)
        if method.startswith("git."):
            operation = method.removeprefix("git.")
            if operation in GIT_READ_METHODS:
                return
            if operation in GIT_WRITE_METHODS:
                self._require_command_commit(context, method)
                self._require(context, AutomationCapability.SAVE)
                if operation == "freeze_run":
                    self._require(context, AutomationCapability.EXECUTE)
                if operation not in {"stage", "unstage", "commit"}:
                    self._require(context, AutomationCapability.ADMIN)
                return
        if method == "proposal.create":
            self._require(context, AutomationCapability.PROPOSE)
            return
        if method in {"proposal.accept", "proposal.reject"}:
            self._require(context, AutomationCapability.EDIT)
            return
        if method == "project.save_as":
            self._require(context, AutomationCapability.SAVE)
            return
        if method == "generate.to_disk":
            self._require(context, AutomationCapability.GENERATE)
            return
        if method.startswith("test.") or method.startswith("run."):
            self._require(context, AutomationCapability.EXECUTE)
            return
        mutating = (
            method == "command.execute"
            or method == "command.transaction"
            or method in _DIRECT_COMMAND_METHODS
            or method in {"history.undo", "history.redo"}
            or method
            in {
                "mindmap.reparent",
                "mindmap.reorder",
                "freeform.group",
                "object.set_text",
                "object.set_property",
                "drakon.set_route_preference",
                "object.set_layout_intent",
            }
        )
        if mutating:
            command_type = (
                params.get("command_type", method) if method == "command.execute" else method
            )
            self._require_command_commit(
                context, command_type if isinstance(command_type, str) else method
            )

    def _require_command_commit(self, context: AutomationContext, command_type: str) -> None:
        """A command retains its grants inside transactions and accepted proposals."""

        if context.mode is AccessMode.PROPOSAL:
            raise RpcError(
                -32003,
                "Proposal-mode actors cannot commit; use proposal.create",
                {"code": "PERMISSION_PROPOSAL_ONLY"},
            )
        self._require(context, AutomationCapability.EDIT)
        if command_type.endswith((".delete", ".remove")):
            self._require(context, AutomationCapability.DESTRUCTIVE)

    def _capabilities(self, context: AutomationContext) -> dict[str, JsonValue]:
        capability_values = [
            cast(JsonValue, item) for item in sorted(value.value for value in context.capabilities)
        ]
        method_values = [
            cast(JsonValue, item)
            for item in sorted(
                {
                    *_DIRECT_COMMAND_METHODS,
                    *(f"git.{item}" for item in GIT_READ_METHODS | GIT_WRITE_METHODS),
                    "command.execute",
                    "command.transaction",
                    "diagram.delete",
                    "drakon.list_insertions",
                    "drakon.set_route_preference",
                    "freeform.group",
                    "generate.preview",
                    "generate.to_disk",
                    "history.redo",
                    "history.undo",
                    "history.preview_redo",
                    "history.preview_undo",
                    "mindmap.reorder",
                    "mindmap.reparent",
                    "navigation.reveal",
                    "object.set_layout_intent",
                    "object.set_property",
                    "object.set_text",
                    "project.close",
                    "project.create",
                    "project.list_diagrams",
                    "project.list_recent",
                    "project.open",
                    "project.save_as",
                    "project.snapshot",
                    "proposal.accept",
                    "proposal.create",
                    "proposal.list",
                    "proposal.reject",
                    "run.project",
                    "run.stop",
                    "run.status",
                    "runtime.active",
                    "runtime.history",
                    "runtime.sessions",
                    "search.query",
                    "service.capabilities",
                    "capability.invoke",
                    "service.operations",
                    "service.presence",
                    "service.subscribe",
                    "test.run_diagram",
                    "test.stop",
                    "test.status",
                    "test.trace_diagram",
                    "validate.diagram",
                    "validate.project",
                    "query.callers",
                    "query.children",
                    "query.control_flow",
                    "query.data_dependencies",
                    "query.projection",
                    "query.compose_projection",
                    "query.projection_definitions",
                    "query.references",
                    "query.semantic_object",
                    "query.views_for",
                    "query.workbench",
                    "query.notations",
                    "query.notation",
                }
            )
        ]
        return {
            "actor_id": context.actor_id,
            "capabilities": capability_values,
            "methods": method_values,
            "mode": context.mode.value,
            "project_id": self.authority.snapshot().id,
            "protocol_version": PROTOCOL_VERSION,
            "revision": self.authority.revision,
        }

    def _operation_capabilities(self) -> list[JsonValue]:
        return [
            {
                "description": item.description,
                "id": item.id,
                "input_contract": item.input_contract,
                "kind": item.kind.value,
                "label": item.label,
                "output_contract": item.output_contract,
            }
            for item in self.kernel.capabilities.descriptors()
        ]

    def _invoke_capability(
        self,
        params: dict[str, JsonValue],
        context: AutomationContext,
    ) -> JsonValue:
        capability_id = params.get("capability_id")
        raw_inputs = params.get("inputs", {})
        if not isinstance(capability_id, str) or not capability_id:
            raise RpcError(-32602, "capability.invoke requires capability_id")
        if not isinstance(raw_inputs, dict) or not all(isinstance(key, str) for key in raw_inputs):
            raise RpcError(-32602, "capability inputs must be an object")
        try:
            capability = self.kernel.capabilities.get(capability_id)
        except KeyError as exc:
            raise RpcError(-32602, str(exc), {"code": "UNKNOWN_CAPABILITY"}) from exc
        required = {
            CapabilityKind.GENERATOR: AutomationCapability.GENERATE,
            CapabilityKind.EXECUTION: AutomationCapability.EXECUTE,
            CapabilityKind.EXPORT: AutomationCapability.SAVE,
        }.get(capability.descriptor.kind, AutomationCapability.READ)
        self._require(context, required)
        try:
            result = capability.invoke(raw_inputs)
        except ValueError as exc:
            raise RpcError(-32602, str(exc), {"code": "INVALID_CAPABILITY_INPUT"}) from exc
        try:
            return _capability_json_value(result)
        except (TypeError, ValueError) as exc:
            raise RpcError(
                -32603,
                str(exc),
                {"code": "CAPABILITY_RESULT_NOT_SERIALIZABLE"},
            ) from exc

    def _query(
        self,
        method: str,
        params: dict[str, JsonValue],
    ) -> JsonValue:
        if method == "query.workbench":
            return _capability_json_value(self.kernel.workbench())
        if method in {"query.notations", "query.notation"}:
            model_id = params.get("model_id")
            if not isinstance(model_id, str) or not model_id:
                raise RpcError(-32602, f"{method} requires model_id")
            try:
                if method == "query.notations":
                    return _capability_json_value(self.kernel.notations(model_id))
                notation_id = params.get("notation_id")
                if not isinstance(notation_id, str) or not notation_id:
                    raise RpcError(-32602, "query.notation requires notation_id")
                return _capability_json_value(self.kernel.notation(model_id, notation_id))
            except ValueError as exc:
                raise RpcError(-32602, str(exc)) from exc
        queries = self.kernel.queries
        key_by_method = {
            "query.semantic_object": "object_id",
            "query.children": "namespace_id",
            "query.callers": "function_id",
            "query.references": "symbol_id",
            "query.control_flow": "function_id",
            "query.data_dependencies": "operation_id",
            "query.views_for": "semantic_id",
        }
        if method == "query.projection":
            raw_kind = params.get("kind")
            root = params.get("root_id")
            if not isinstance(raw_kind, str):
                raise RpcError(-32602, "query.projection requires kind")
            if root is not None and not isinstance(root, str):
                raise RpcError(-32602, "root_id must be text or null")
            try:
                kind = ProjectionKind(raw_kind)
            except ValueError as exc:
                raise RpcError(-32602, f"Unknown projection kind {raw_kind!r}") from exc
            return projection_to_data(self.kernel.project_projection(kind, root))
        if method == "query.projection_definitions":
            return [
                projection_definition_to_data(item) for item in queries.projection_definitions()
            ]
        if method == "query.compose_projection":
            raw_definition = params.get("definition")
            try:
                definition = projection_definition_from_data(
                    raw_definition,
                    "$.params.definition",
                )
            except ValueError as exc:
                raise RpcError(-32602, str(exc)) from exc
            return projection_to_data(self.kernel.compose_projection(definition))
        parameter = key_by_method.get(method)
        if parameter is None:
            raise RpcError(-32601, f"Unknown query {method!r}")
        object_id = params.get(parameter)
        if not isinstance(object_id, str) or not object_id:
            raise RpcError(-32602, f"{method} requires {parameter}")
        if method == "query.semantic_object":
            value = queries.semantic_object(object_id)
            return None if value is None else semantic_object_to_data(value)
        if method == "query.children":
            return [semantic_object_to_data(item) for item in queries.children(object_id)]
        if method == "query.callers":
            result = queries.callers(object_id)
        elif method == "query.references":
            result = queries.references(object_id)
        elif method == "query.control_flow":
            result = queries.control_flow(object_id)
        elif method == "query.data_dependencies":
            result = queries.data_dependencies(object_id)
        else:
            return [semantic_object_to_data(item) for item in queries.views_for(object_id)]
        return [relation_to_data(item) for item in result]

    def _subscribe(
        self,
        params: dict[str, JsonValue],
        context: AutomationContext,
    ) -> dict[str, JsonValue]:
        raw_revision = params.get("since_revision", self.authority.revision)
        if isinstance(raw_revision, bool) or not isinstance(raw_revision, int):
            raise RpcError(-32602, "since_revision must be an integer")
        events = self.authority.events_since(raw_revision)
        if events is None:
            self._emit_collaboration_event(
                "resynchronization.required",
                context,
                new_operation_id(),
                (),
                {"requested_revision": raw_revision},
            )
            return {
                "events": [],
                "resync_required": True,
                "revision": self.authority.revision,
                "snapshot": project_to_data(self.authority.snapshot()),
            }
        return {
            "events": [event_to_data(event) for event in events],
            "resync_required": False,
            "revision": self.authority.revision,
        }

    def _presence(
        self,
        params: dict[str, JsonValue],
        context: AutomationContext,
    ) -> dict[str, JsonValue]:
        raw_selection = params.get("selection", [])
        if not isinstance(raw_selection, list) or not all(
            isinstance(item, str) for item in raw_selection
        ):
            raise RpcError(-32602, "selection must be an array of object IDs")
        preview = params.get("preview", "")
        if not isinstance(preview, str) or len(preview) > 2_000:
            raise RpcError(-32602, "preview must be bounded text")
        event = EventEnvelope.now(
            event_type="presence.changed",
            actor_id=context.actor_id,
            operation_id=new_operation_id(),
            project_id=self.authority.snapshot().id,
            revision=self.authority.revision,
            payload={
                "connection_id": context.connection_id,
                "mode": context.mode.value,
                "preview": preview,
                "selection": raw_selection,
            },
            affected_ids=tuple(item for item in raw_selection if isinstance(item, str)),
        )
        self.kernel.selection.select(
            (item for item in raw_selection if isinstance(item, str)),
            revision=self.authority.revision,
            source=f"automation:{context.connection_id}",
        )
        self._event_sink(event)
        return event_to_data(event)

    def _list_diagrams(self) -> list[JsonValue]:
        return [
            {
                "id": document.id,
                "kind": document.kind.value,
                "title": document.title,
            }
            for document in self.authority.snapshot().documents
        ]

    def _save_project_as(
        self,
        params: dict[str, JsonValue],
        context: AutomationContext,
    ) -> dict[str, JsonValue]:
        value = params.get("path")
        if not isinstance(value, str) or not value:
            raise RpcError(-32602, "path must be non-empty text")
        if self._save_as is None:
            raise RpcError(
                -32010,
                "The host does not permit remote Save As",
                {"code": "SAVE_AS_HOST_ONLY"},
            )
        self._emit_collaboration_event(
            "save.running", context, new_operation_id(), (), {"path": value}
        )
        root = self._save_as(Path(value))
        self.kernel.resource_store = ResourceStore(root)
        self.kernel.evidence_store = EvidenceStore(root)
        self._emit_collaboration_event(
            "save.completed", context, new_operation_id(), (), {"path": str(root)}
        )
        return {"path": str(root), "revision": self.authority.revision, "status": "saved"}

    @staticmethod
    def _command_metadata(params: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return {
            "expected_revision": params.get("expected_revision"),
            "intent": params.get("intent", ""),
            "operation_id": params.get("operation_id", new_operation_id()),
        }

    def _execute_command(
        self,
        params: dict[str, JsonValue],
        context: AutomationContext,
    ) -> dict[str, JsonValue]:
        expected_revision = params.get("expected_revision")
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise RpcError(
                -32602,
                "Mutating commands require an integer expected_revision",
                {"code": "EXPECTED_REVISION_REQUIRED"},
            )
        command = command_from_params(
            params,
            actor_id=context.actor_id,
            project_id=self.authority.snapshot().id,
        )
        return result_to_data(self.authority.execute(command))

    def _execute_transaction(
        self,
        params: dict[str, JsonValue],
        context: AutomationContext,
    ) -> dict[str, JsonValue]:
        raw_commands = params.get("commands")
        expected = params.get("expected_revision")
        operation_id = params.get("operation_id", new_operation_id())
        intent = params.get("intent", "")
        if (
            not isinstance(raw_commands, list)
            or not raw_commands
            or isinstance(expected, bool)
            or not isinstance(expected, int)
            or not isinstance(operation_id, str)
            or not isinstance(intent, str)
        ):
            raise RpcError(-32602, "Transaction fields are invalid")
        project_id = self.authority.snapshot().id
        commands = tuple(
            command_from_params(
                object_params(item),
                actor_id=context.actor_id,
                project_id=project_id,
            )
            for item in raw_commands
        )
        for command in commands:
            self._require_command_commit(context, command.command_type)
        return result_to_data(
            self.authority.execute_transaction(
                commands,
                actor_id=context.actor_id,
                operation_id=operation_id,
                expected_revision=expected,
                intent=intent,
            )
        )

    def _operation_for_method(
        self,
        method: str,
        params: dict[str, JsonValue],
    ) -> Operation:
        metadata = {"expected_revision", "operation_id", "intent"}
        payload = {key: value for key, value in params.items() if key not in metadata}
        if method == "object.set_layout_intent":
            layout_kind = payload.pop("layout_kind", None)
            if layout_kind == "drakon.route_preference":
                method = "drakon.set_route_preference"
            elif layout_kind == "freeform.transform":
                method = "freeform.transform"
            else:
                raise RpcError(
                    -32602,
                    "layout_kind must be 'drakon.route_preference' or 'freeform.transform'",
                )
        command_type = method
        if method in {"mindmap.reparent", "mindmap.reorder"}:
            command_type = "mindmap.move_topic"
        elif method == "freeform.group":
            command_type = "freeform.set_properties"
        elif method == "object.set_text":
            command_type = "drakon.set_text"
        elif method == "object.set_property":
            command_type = (
                "freeform.set_properties" if "object_ids" in payload else "drakon.set_text"
            )
        elif method == "drakon.set_route_preference":
            diagram_id = payload.get("diagram_id")
            atom_id = payload.get("atom_id")
            preferred = payload.get("preferred_truth")
            if (
                not isinstance(diagram_id, str)
                or not isinstance(atom_id, str)
                or not isinstance(preferred, bool)
            ):
                raise RpcError(
                    -32602,
                    "Route preference requires diagram_id, atom_id, and Boolean preferred_truth",
                )
            diagram = next(
                (
                    item
                    for item in self.authority.snapshot().documents
                    if isinstance(item, DrakonDiagram) and item.id == diagram_id
                ),
                None,
            )
            location = find_atom_location(diagram.body, atom_id) if diagram is not None else None
            atom = location[0].atoms[location[1]] if location is not None else None
            if not isinstance(atom, If):
                raise RpcError(-32602, "Route preference target must be an If")
            command_type = "drakon.replace"
            payload = {
                "atom": drakon_atom_to_data(replace(atom, preferred_truth=preferred)),
                "atom_id": atom_id,
                "diagram_id": diagram_id,
            }
        elif method == "program.function.create":
            payload.setdefault("function_id", new_id("function"))
            payload.setdefault("symbol_id", new_id("symbol"))
            payload.setdefault("body_sequence_id", new_id("sequence"))
        elif method == "program.statement.insert":
            payload.setdefault("statement_id", new_id("statement"))
            payload.setdefault("operator", "=")
            payload.setdefault("arguments", "")
            payload.setdefault("awaited", False)
            payload.setdefault("preferred_truth", True)
            payload.setdefault("true_sequence_id", new_id("sequence"))
            payload.setdefault("false_sequence_id", new_id("sequence"))
        if command_type == "diagram.duplicate" and "document_id" not in payload:
            payload["document_id"] = new_id("diagram")
        return Operation(command_type, payload)

    def _execute_semantic_method(
        self,
        method: str,
        params: dict[str, JsonValue],
        context: AutomationContext,
    ) -> dict[str, JsonValue]:
        operation = self._operation_for_method(method, params)
        metadata = self._command_metadata(params)
        envelope_params = {
            **metadata,
            "command_type": operation.command_type,
            "payload": operation.payload,
        }
        return self._execute_command(envelope_params, context)

    def _list_insertions(self, params: dict[str, JsonValue]) -> list[JsonValue]:
        diagram_id = params.get("diagram_id")
        diagram = next(
            (
                item
                for item in self.authority.snapshot().documents
                if isinstance(item, DrakonDiagram) and item.id == diagram_id
            ),
            None,
        )
        if diagram is None:
            raise RpcError(-32602, "diagram_id must identify a DRAKON diagram")
        scene = layout_drakon(diagram)
        result: list[JsonValue] = []
        for route in scene.routes:
            boundary = route.boundary
            orientation = (
                "vertical"
                if abs(route.segment.start.x - route.segment.end.x) < 0.001
                else "horizontal"
            )
            result.append(
                {
                    "eligible": route.legal_insertion,
                    "index": boundary.index if boundary is not None else None,
                    "orientation": orientation,
                    "reason": route.tooltip,
                    "sequence_id": boundary.sequence_id if boundary is not None else None,
                    "target_id": route.id,
                }
            )
        return result

    def _history(
        self,
        params: dict[str, JsonValue],
        context: AutomationContext,
        *,
        redo: bool,
    ) -> dict[str, JsonValue]:
        revision = params.get("expected_revision")
        operation_id = params.get("operation_id", new_operation_id())
        if (
            isinstance(revision, bool)
            or not isinstance(revision, int)
            or not isinstance(operation_id, str)
        ):
            raise RpcError(-32602, "History command requires expected_revision")
        action = self.authority.redo if redo else self.authority.undo
        return result_to_data(
            action(
                actor_id=context.actor_id,
                operation_id=operation_id,
                expected_revision=revision,
            )
        )

    def _create_proposal(
        self,
        params: dict[str, JsonValue],
        context: AutomationContext,
    ) -> dict[str, JsonValue]:
        raw_command = params.get("command")
        command_params = object_params(raw_command)
        base = self.authority.snapshot()
        command = command_from_params(
            command_params,
            actor_id=context.actor_id,
            project_id=base.id,
        )
        if command.expected_revision != base.revision:
            return result_to_data(
                self.authority.execute(
                    replace(command, operation_id=f"proposal-conflict-{new_operation_id()}")
                )
            )
        preview_authority = ProjectAuthority(base)
        preview_command = replace(command, operation_id=f"preview-{command.operation_id}")
        result = preview_authority.execute(preview_command)
        if not isinstance(result, CommandAccepted):
            return result_to_data(result)
        before = normalized_project_json(base).splitlines()
        after = normalized_project_json(preview_authority.snapshot()).splitlines()
        diff = "\n".join(
            difflib.unified_diff(before, after, fromfile="current", tofile="proposal", lineterm="")
        )
        if len(diff) > 200_000:
            diff = diff[:200_000] + "\n… diff truncated …"
        proposal_id = new_id("proposal")
        self._proposal_order += 1
        proposal = Proposal(
            proposal_id,
            context.actor_id,
            base.revision,
            command,
            self._proposal_order,
            command.intent or command.command_type,
            diff,
            result.affected_ids,
        )
        self._proposals[proposal_id] = proposal
        while len(self._proposals) > self._proposal_limit:
            self._proposals.popitem(last=False)
        self._emit_collaboration_event(
            "proposal.created",
            context,
            proposal_id,
            proposal.affected_ids,
            {"base_revision": base.revision, "summary": proposal.summary},
        )
        return self._proposal_data(proposal)

    @staticmethod
    def _proposal_data(proposal: Proposal) -> dict[str, JsonValue]:
        return {
            "actor_id": proposal.actor_id,
            "affected_ids": list(proposal.affected_ids),
            "base_revision": proposal.base_revision,
            "diff": proposal.diff,
            "proposal_id": proposal.id,
            "summary": proposal.summary,
        }

    def _proposal(self, params: dict[str, JsonValue]) -> Proposal:
        proposal_id = params.get("proposal_id")
        if not isinstance(proposal_id, str) or proposal_id not in self._proposals:
            raise RpcError(-32004, "Proposal does not exist", {"code": "PROPOSAL_NOT_FOUND"})
        return self._proposals[proposal_id]

    def _accept_proposal(
        self,
        params: dict[str, JsonValue],
        context: AutomationContext,
    ) -> dict[str, JsonValue]:
        proposal = self._proposal(params)
        self._require_command_commit(context, proposal.command.command_type)
        operation_id = params.get("operation_id", new_operation_id())
        if not isinstance(operation_id, str):
            raise RpcError(-32602, "operation_id must be text")
        committed = replace(
            proposal.command,
            actor_id=context.actor_id,
            operation_id=operation_id,
            expected_revision=proposal.base_revision,
            intent=f"Accept proposal by {proposal.actor_id}: {proposal.summary}",
        )
        result = self.authority.execute(committed)
        if isinstance(result, CommandAccepted):
            del self._proposals[proposal.id]
            self._emit_collaboration_event(
                "proposal.accepted",
                context,
                proposal.id,
                result.affected_ids,
                {"proposed_by": proposal.actor_id, "revision": result.revision},
            )
        return result_to_data(result)

    def _reject_proposal(
        self,
        params: dict[str, JsonValue],
        context: AutomationContext,
    ) -> dict[str, JsonValue]:
        proposal = self._proposal(params)
        del self._proposals[proposal.id]
        self._emit_collaboration_event(
            "proposal.rejected",
            context,
            proposal.id,
            proposal.affected_ids,
            {"proposed_by": proposal.actor_id},
        )
        return {"proposal_id": proposal.id, "status": "rejected"}

    def _emit_collaboration_event(
        self,
        event_type: str,
        context: AutomationContext,
        operation_id: str,
        affected_ids: tuple[str, ...],
        payload: dict[str, JsonValue],
    ) -> None:
        self._event_sink(
            EventEnvelope.now(
                event_type=event_type,
                actor_id=context.actor_id,
                operation_id=operation_id,
                project_id=self.authority.snapshot().id,
                revision=self.authority.revision,
                payload=payload,
                affected_ids=affected_ids,
            )
        )

    @staticmethod
    def _diagnostic_data(diagnostic: Diagnostic) -> dict[str, JsonValue]:
        return {
            "category": diagnostic.category.value,
            "code": diagnostic.code,
            "diagram_id": diagnostic.diagram_id,
            "field": diagnostic.field,
            "message": diagnostic.message,
            "object_id": diagnostic.object_id,
            "severity": diagnostic.severity.value,
            "suggested_repair": diagnostic.suggested_repair,
        }

    def _build_blocked_rpc_error(self, error: BuildBlockedError) -> RpcError:
        return RpcError(
            -32020,
            str(error),
            {
                "buildability": "blocked",
                "diagnostics": [
                    self._diagnostic_data(item) for item in error.assessment.blocking_diagnostics
                ],
            },
        )

    def _validate(
        self,
        params: dict[str, JsonValue],
        context: AutomationContext,
        *,
        diagram_only: bool,
    ) -> dict[str, JsonValue]:
        diagram_id = params.get("diagram_id")
        affected = (diagram_id,) if isinstance(diagram_id, str) else ()
        operation_id = new_operation_id()
        self._emit_collaboration_event("validation.started", context, operation_id, affected, {})
        assessment = assess_project(self.authority.snapshot(), extensions=self.kernel.extensions)
        diagnostics = assessment.diagnostics
        if diagram_only:
            if not isinstance(diagram_id, str):
                raise RpcError(-32602, "validate.diagram requires diagram_id")
            diagnostics = tuple(item for item in diagnostics if item.diagram_id == diagram_id)
        buildable = not any(item.severity is Severity.ERROR for item in diagnostics)
        diagnostic_data: list[JsonValue] = [self._diagnostic_data(item) for item in diagnostics]
        self._emit_collaboration_event(
            "validation.completed",
            context,
            operation_id,
            affected,
            {
                "buildability": "buildable" if buildable else "blocked",
                "diagnostic_count": len(diagnostic_data),
            },
        )
        return {
            "buildability": "buildable" if buildable else "blocked",
            "diagnostics": diagnostic_data,
        }

    def _generate_preview(self, context: AutomationContext) -> dict[str, JsonValue]:
        operation_id = new_operation_id()
        self._emit_collaboration_event(
            "generation.running", context, operation_id, (), {"target": "preview"}
        )
        try:
            generated = generate_python_project(
                self.authority.snapshot(),
                extensions=self.kernel.extensions,
            )
        except BuildBlockedError as exc:
            raise self._build_blocked_rpc_error(exc) from exc
        total = sum(len(item.source.encode("utf-8")) for item in generated.files)
        if total > 4_000_000:
            raise RpcError(-32020, "Generated preview exceeds the transport limit")
        result: dict[str, JsonValue] = {
            "entrypoint": generated.entrypoint,
            "files": [{"path": item.path, "source": item.source} for item in generated.files],
            "revision": self.authority.revision,
            "spans": [
                {
                    "end_column": span.end_column,
                    "end_line": span.end_line,
                    "field": span.field,
                    "file_path": span.file_path,
                    "map_id": span.map_id,
                    "presentation_id": span.presentation_id,
                    "semantic_id": span.semantic_id,
                    "start_column": span.start_column,
                    "start_line": span.start_line,
                }
                for span in generated.spans
            ],
        }
        self._emit_collaboration_event(
            "generation.completed",
            context,
            operation_id,
            (),
            {"file_count": len(generated.files), "target": "preview"},
        )
        return result

    def _generate_to_disk(self, context: AutomationContext) -> dict[str, JsonValue]:
        root = self._project_root()
        if root is None:
            raise RpcError(
                -32010, "Save the project before generation", {"code": "PROJECT_UNSAVED"}
            )
        operation_id = new_operation_id()
        self._emit_collaboration_event(
            "generation.running", context, operation_id, (), {"target": "disk"}
        )
        if self._git is not None:
            result = self._git.session.generate(revision_provider=lambda: self.authority.revision)
        else:
            result = generate_to_disk(
                self.authority.snapshot(),
                root,
                current_revision=lambda: self.authority.revision,
                extensions=self.kernel.extensions,
            )
        response: dict[str, JsonValue] = {
            "files": [path.relative_to(result.root).as_posix() for path in result.files],
            "revision": result.revision,
            "root": str(result.root),
            "status": "complete",
        }
        self._emit_collaboration_event(
            "generation.completed",
            context,
            operation_id,
            (),
            {"file_count": len(result.files), "target": "disk"},
        )
        return response

    def _test_diagram(
        self,
        params: dict[str, JsonValue],
        context: AutomationContext,
        *,
        trace: bool,
    ) -> dict[str, JsonValue]:
        diagram_id = params.get("diagram_id")
        arguments = params.get("arguments", "")
        if not isinstance(diagram_id, str) or not isinstance(arguments, str):
            raise RpcError(-32602, "Test requires diagram_id and text arguments")
        project = self.authority.snapshot()
        document = next(
            (
                item
                for item in project.documents
                if isinstance(item, DrakonDiagram) and item.id == diagram_id
            ),
            None,
        )
        if document is None:
            raise RpcError(-32602, "diagram_id must identify a DRAKON diagram")
        try:
            invocation = invocation_for_document(project, diagram_id, arguments)
        except ValueError as exc:
            raise RpcError(-32602, str(exc)) from exc
        try:
            generated = generate_python_project(
                project,
                focus_diagram_id=diagram_id,
                invocation=invocation,
                extensions=self.kernel.extensions,
            )
        except BuildBlockedError as exc:
            raise self._build_blocked_rpc_error(exc) from exc
        operation_id = new_id("execution")
        session = RunSession()
        job = ExecutionJob(
            operation_id,
            context.actor_id,
            context.connection_id,
            context,
            "trace" if trace else "test",
            diagram_id,
            session,
        )
        self._register_execution(job)
        self._emit_collaboration_event(
            "execution.started",
            context,
            operation_id,
            (diagram_id,),
            {"kind": "trace" if trace else "test"},
        )
        if trace:
            session.start_project_trace(
                generated,
                project_revision=project.revision,
                artifact_revision=project.revision,
                completed=lambda result: self._complete_trace(operation_id, result),
            )
        else:
            session.start_project(
                generated,
                completed=lambda result: self._complete_run(operation_id, result),
            )
        return {"job_id": operation_id, "status": "running"}

    def _run_project(self, context: AutomationContext) -> dict[str, JsonValue]:
        root = self._project_root()
        if root is None:
            raise RpcError(-32010, "Save and generate the project before running")
        assessment = assess_project(self.authority.snapshot(), extensions=self.kernel.extensions)
        if not assessment.buildable:
            first = assessment.blocking_diagnostics[0]
            raise RpcError(
                -32020,
                f"Project is not buildable: {first.message}",
                {
                    "code": first.code,
                    "diagnostic": self._diagnostic_data(first),
                },
            )
        manifest = load_generation_manifest(root)
        if manifest is None or manifest.get("revision") != self.authority.revision:
            raise RpcError(-32020, "Generated artifacts are not current")
        launcher = root / "generated" / "run_project.py"
        if not launcher.is_file():
            raise RpcError(-32020, "Generate the current Python project launcher first")
        operation_id = new_id("execution")
        session = RunSession()
        job = ExecutionJob(
            operation_id,
            context.actor_id,
            context.connection_id,
            context,
            "project",
            None,
            session,
        )
        self._register_execution(job)
        self._emit_collaboration_event(
            "execution.started", context, operation_id, (), {"kind": "project"}
        )
        session.start_generated(
            launcher,
            working_directory=root,
            completed=lambda result: self._complete_run(operation_id, result),
        )
        return {"job_id": operation_id, "status": "running"}

    def _register_execution(self, job: ExecutionJob) -> None:
        self._execution_jobs[job.id] = job
        while len(self._execution_jobs) > self._execution_limit:
            removable = next(
                (
                    job_id
                    for job_id, item in self._execution_jobs.items()
                    if item.status != "running"
                ),
                None,
            )
            if removable is None:
                break
            del self._execution_jobs[removable]

    def _complete_run(self, job_id: str, result: RunResult) -> None:
        with self._lock:
            job = self._execution_jobs.get(job_id)
            if job is None:
                return
            job.status = result.termination_reason
            job.result = {
                "return_code": result.return_code,
                "stderr": result.stderr,
                "stdout": result.stdout,
                "timed_out": result.timed_out,
                "termination_reason": result.termination_reason,
            }
        self._emit_execution_complete(
            job.context,
            job.id,
            job.diagram_id,
            result.return_code,
            result.stdout,
            result.stderr,
            result.termination_reason,
        )

    def _complete_trace(self, job_id: str, traced: TraceResult) -> None:
        with self._lock:
            job = self._execution_jobs.get(job_id)
            if job is None:
                return
            job.status = traced.run.termination_reason
            job.result = {
                "events": [
                    {
                        "detail": event.detail,
                        "event": event.event,
                        "function": event.function,
                        "index": event.index,
                        "file_path": event.file_path,
                        "line": event.line,
                        "locals": dict(event.locals),
                    }
                    for event in traced.events
                ],
                "return_code": traced.run.return_code,
                "stderr": traced.run.stderr,
                "stdout": traced.run.stdout,
                "termination_reason": traced.run.termination_reason,
                "truncated": traced.events_truncated,
            }
        self._emit_execution_complete(
            job.context,
            job.id,
            job.diagram_id,
            traced.run.return_code,
            traced.run.stdout,
            traced.run.stderr,
            traced.run.termination_reason,
        )

    def _stop_execution(
        self,
        params: dict[str, JsonValue],
        context: AutomationContext,
    ) -> dict[str, JsonValue]:
        raw_job_id = params.get("job_id")
        if raw_job_id is not None and not isinstance(raw_job_id, str):
            raise RpcError(-32602, "job_id must be text or null")
        jobs = tuple(
            job
            for job in self._execution_jobs.values()
            if job.status == "running"
            and (raw_job_id is None or job.id == raw_job_id)
            and (
                job.actor_id == context.actor_id
                or AutomationCapability.ADMIN in context.capabilities
            )
        )
        if raw_job_id is not None and not jobs:
            raise RpcError(-32004, "Active execution job does not exist or is not owned by actor")
        stopped = sum(job.session.stop() for job in jobs)
        return {"status": "stopping" if stopped else "idle", "stopped": stopped}

    def _execution_status(
        self,
        params: dict[str, JsonValue],
        context: AutomationContext,
    ) -> dict[str, JsonValue]:
        job_id = params.get("job_id")
        if not isinstance(job_id, str):
            raise RpcError(-32602, "job_id must be text")
        job = self._execution_jobs.get(job_id)
        if job is None or (
            job.actor_id != context.actor_id
            and AutomationCapability.ADMIN not in context.capabilities
        ):
            raise RpcError(-32004, "Execution job does not exist or is not visible to actor")
        return {
            "job_id": job.id,
            "kind": job.kind,
            "result": job.result,
            "status": job.status,
        }

    def _emit_execution_complete(
        self,
        context: AutomationContext,
        operation_id: str,
        diagram_id: str | None,
        return_code: int,
        stdout: str,
        stderr: str,
        termination_reason: str,
    ) -> None:
        affected = (diagram_id,) if diagram_id is not None else ()
        output = (stdout + stderr)[:20_000]
        if output:
            self._emit_collaboration_event(
                "execution.output",
                context,
                operation_id,
                affected,
                {"text": output, "truncated": len(stdout) + len(stderr) > len(output)},
            )
        self._emit_collaboration_event(
            "execution.completed",
            context,
            operation_id,
            affected,
            {"return_code": return_code, "termination_reason": termination_reason},
        )

    def _search(self, params: dict[str, JsonValue]) -> list[JsonValue]:
        query = params.get("query")
        if not isinstance(query, str) or not query.strip():
            raise RpcError(-32602, "query must be non-empty text")
        return [
            {
                "diagram_id": match.diagram_id,
                "field": match.field,
                "kind": match.kind,
                "object_id": match.object_id,
                "path": match.path,
                "replace_supported": match.replace_supported,
                "text": match.text[:500],
            }
            for match in search_project(self.authority.snapshot(), query, limit=200)
        ]

    def _navigation(
        self,
        params: dict[str, JsonValue],
        context: AutomationContext,
    ) -> dict[str, JsonValue]:
        object_id = params.get("object_id")
        diagram_id = params.get("diagram_id")
        if object_id is not None and not isinstance(object_id, str):
            raise RpcError(-32602, "object_id must be text or null")
        if diagram_id is not None and not isinstance(diagram_id, str):
            raise RpcError(-32602, "diagram_id must be text or null")
        affected = tuple(item for item in (diagram_id, object_id) if isinstance(item, str))
        self._emit_collaboration_event(
            "navigation.requested",
            context,
            new_operation_id(),
            affected,
            {"diagram_id": diagram_id, "object_id": object_id},
        )
        return {"diagram_id": diagram_id, "object_id": object_id, "status": "requested"}
