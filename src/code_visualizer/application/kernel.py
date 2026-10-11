"""Shared project kernel: authority, read models, semantic events, and services."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from threading import RLock
from typing import TYPE_CHECKING

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.capabilities import (
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityRegistry,
)
from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.domain_workbench import (
    WorkbenchSnapshot,
    available_notations,
    decorate_semantic_projection,
    project_notation,
    workbench_snapshot,
)
from code_visualizer.application.messages import EventEnvelope
from code_visualizer.application.notations import NotationProjection
from code_visualizer.application.queries import (
    ProjectQueries,
    projection_to_data,
    semantic_object_to_data,
)
from code_visualizer.application.runtime_overlay import (
    RuntimeOverlayContext,
    overlay_runtime_context,
)
from code_visualizer.application.runtime_projection import compile_runtime_projection
from code_visualizer.application.runtime_sessions import (
    RuntimeSessionState,
    runtime_session_to_data,
)
from code_visualizer.application.selection import SelectionService
from code_visualizer.application.semantic_index import update_semantic_program
from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.notation import NotationDefinition
from code_visualizer.domain.projection import ProjectionDefinition
from code_visualizer.domain.semantic import (
    ProjectionKind,
    SemanticDelta,
    SemanticProjection,
    diff_semantic_program,
)
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.languages import resolve_domain_languages
from code_visualizer.extensions.registry import DomainExtensionRegistry
from code_visualizer.persistence.decoding import projection_definition_from_data

if TYPE_CHECKING:
    from code_visualizer.persistence.evidence_store import EvidenceStore
    from code_visualizer.persistence.resource_store import ResourceStore


class KernelEventKind(StrEnum):
    SEMANTIC_OBJECT_CHANGED = "semantic_object_changed"
    FUNCTION_MOVED = "function_moved"
    EXPRESSION_CHANGED = "expression_changed"
    SYMBOL_RENAMED = "symbol_renamed"
    VIEW_LAYOUT_CHANGED = "view_layout_changed"
    PROJECT_REVISION_CHANGED = "project_revision_changed"


@dataclass(frozen=True, slots=True)
class KernelEvent:
    kind: KernelEventKind
    project_id: str
    revision: int
    affected_semantic_ids: tuple[str, ...]
    source_event_type: str
    actor_id: str
    operation_id: str
    payload: dict[str, JsonValue]
    semantic_delta: SemanticDelta | None = None


KernelListener = Callable[[KernelEvent], None]


class ProjectKernel:
    """Revision-consistent application facade consumed by all feature slices."""

    def __init__(
        self,
        authority: ProjectAuthority,
        *,
        extensions: DomainExtensionRegistry | None = None,
        resource_store: ResourceStore | None = None,
        evidence_store: EvidenceStore | None = None,
        computations: ComputationService | None = None,
    ) -> None:
        self.authority = authority
        self.resource_store = resource_store
        self.evidence_store = evidence_store
        self._host_extensions = extensions if extensions is not None else builtin_registry()
        snapshot = authority.snapshot()
        self.selection = SelectionService(snapshot.id, snapshot.revision)
        self.computations = computations if computations is not None else ComputationService()
        self._owns_computations = computations is None
        self.computation_attachment = self.computations.attach(snapshot.id)
        self.computation_attachment.revision = snapshot.revision
        self.computation_attachment.selection = self.selection
        self.runtime = self.computation_attachment.runtime
        self.capabilities = CapabilityRegistry()
        self._queries: ProjectQueries | None = ProjectQueries.from_project(
            snapshot, self.extensions
        )
        self._indexed_project = snapshot
        self._query_revision = snapshot.revision
        self._last_semantic_delta: SemanticDelta | None = None
        self._listeners: list[KernelListener] = []
        self._lock = RLock()
        self._unsubscribe_authority = authority.subscribe(self._on_authority_event)
        self._register_query_capabilities()

    @property
    def extensions(self) -> DomainExtensionRegistry:
        return resolve_domain_languages(self.authority.snapshot(), self._host_extensions)

    @property
    def host_extensions(self) -> DomainExtensionRegistry:
        """Trusted inert composition handle; resolving authored languages is preparation."""
        return self._host_extensions

    @property
    def revision(self) -> int:
        return self.authority.revision

    @property
    def queries(self) -> ProjectQueries:
        revision = self.authority.revision
        with self._lock:
            if self._queries is None or self._query_revision != revision:
                snapshot = self.authority.snapshot()
                self._queries = ProjectQueries.from_project(snapshot, self.extensions)
                self._indexed_project = snapshot
                self._query_revision = snapshot.revision
            return self._queries

    def subscribe(self, listener: KernelListener) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe

    def close(self) -> None:
        self._unsubscribe_authority()
        self.computations.detach(self.computation_attachment.id)
        if self._owns_computations:
            self.computations.close()
        with self._lock:
            self._listeners.clear()

    def transfer_computation_ownership(self) -> ComputationService | None:
        """Move a standalone session's existing host to its longer-lived workbench."""
        if not self._owns_computations:
            return None
        self._owns_computations = False
        return self.computations

    def project_projection(
        self,
        kind: ProjectionKind | str,
        root: str | None = None,
        *,
        runtime_context: RuntimeOverlayContext | None = None,
    ) -> SemanticProjection:
        """Build any lens with the same optional runtime overlay context."""

        resolved = kind if isinstance(kind, ProjectionKind) else ProjectionKind(kind)
        context = runtime_context or self._active_runtime_context()
        if resolved is ProjectionKind.RUNTIME:
            # The runtime lens can inspect history; automatic author-source
            # overlays below only use the current attachment/revision.
            state = context.state if context is not None else self.runtime.active
            adapter = context.adapter if context is not None else None
            binding_name = context.binding_name if context is not None else None
            return compile_runtime_projection(
                self.authority.snapshot().id,
                state,
                **({"adapter": adapter} if adapter is not None else {}),
                binding_name=binding_name,
            )
        projected = overlay_runtime_context(
            self.queries.projection(resolved, root, focus_ids=self._projection_focus()),
            context,
        )
        return self._runtime_presentations(projected, context)

    def compose_projection(
        self,
        definition: ProjectionDefinition,
        *,
        kind: ProjectionKind = ProjectionKind.COMPOSED,
        runtime_context: RuntimeOverlayContext | None = None,
    ) -> SemanticProjection:
        context = runtime_context or self._active_runtime_context()
        projected = overlay_runtime_context(
            self.queries.compose_projection(
                replace(
                    definition,
                    focus_ids=tuple(
                        dict.fromkeys((*definition.focus_ids, *self._projection_focus()))
                    ),
                ),
                kind=kind,
            ),
            context,
        )
        return self._runtime_presentations(projected, context)

    def _runtime_presentations(
        self,
        projection: SemanticProjection,
        context: RuntimeOverlayContext | None,
    ) -> SemanticProjection:
        if (
            context is None
            or context.state is None
            or context.state.project_revision != self.revision
        ):
            return projection
        return decorate_semantic_projection(
            projection,
            self.extensions.runtime_decorations(context.state.active_ids),
        )

    def _projection_focus(self) -> tuple[str, ...]:
        runtime = self.current_runtime_state()
        return tuple(
            dict.fromkeys(
                (
                    *self.selection.state.semantic_ids,
                    *(runtime.active_ids if runtime is not None else ()),
                )
            )
        )

    def _active_runtime_context(self) -> RuntimeOverlayContext | None:
        state = self.current_runtime_state()
        if state is None:
            return None
        history = self.runtime.history(state.execution_session_id)
        previous = history[-2] if len(history) > 1 else None
        return RuntimeOverlayContext(state, previous)

    def current_runtime_state(self) -> RuntimeSessionState | None:
        """Only this attachment's current revision may decorate authored contents."""
        state = self.runtime.active
        return state if state is not None and state.project_revision == self.revision else None

    def current_runtime_ids(self) -> tuple[str, ...]:
        state = self.current_runtime_state()
        return state.active_ids if state is not None else ()

    def workbench(self) -> WorkbenchSnapshot:
        return workbench_snapshot(self.authority.snapshot(), self.extensions)

    def notations(self, model_id: str) -> tuple[NotationDefinition, ...]:
        return available_notations(self.authority.snapshot(), model_id, self.extensions)

    def notation(self, model_id: str, notation_id: str) -> NotationProjection:
        runtime = self.runtime.active
        return project_notation(
            self.authority.snapshot(),
            model_id,
            notation_id,
            self.extensions,
            active_node_ids=self.current_runtime_ids(),
            runtime_revision=runtime.project_revision if runtime is not None else None,
            semantic_relations=self.queries.program.relations,
        )

    def _on_authority_event(self, event: EventEnvelope) -> None:
        snapshot = self.authority.snapshot()
        self.computation_attachment.revision = snapshot.revision
        with self._lock:
            previous = self._queries
            already_indexed = self._query_revision == snapshot.revision
            cached_delta = self._last_semantic_delta
        if already_indexed and previous is not None:
            query = previous
            delta = cached_delta
        else:
            if previous is None:
                query = ProjectQueries.from_project(snapshot, self.extensions)
            else:
                update = update_semantic_program(
                    self._indexed_project,
                    previous.program,
                    snapshot,
                    extensions=self.extensions,
                )
                query = ProjectQueries(
                    update.program,
                    snapshot.projection_definitions,
                    snapshot.documents,
                )
            delta = (
                diff_semantic_program(previous.program, query.program)
                if previous is not None
                else None
            )
            with self._lock:
                self._queries = query
                self._indexed_project = snapshot
                self._query_revision = snapshot.revision
                self._last_semantic_delta = delta
        available_ids = (item.id for item in query.program.objects)
        self.selection.rebase(event.revision, available_ids)
        primary = KernelEvent(
            self._classify(event),
            event.project_id,
            event.revision,
            event.affected_ids,
            event.event_type,
            event.actor_id,
            event.operation_id,
            event.payload,
            delta,
        )
        revision_event = KernelEvent(
            KernelEventKind.PROJECT_REVISION_CHANGED,
            event.project_id,
            event.revision,
            event.affected_ids,
            event.event_type,
            event.actor_id,
            event.operation_id,
            {"source_event_type": event.event_type},
            delta,
        )
        with self._lock:
            listeners = tuple(self._listeners)
        for emitted in (primary, revision_event):
            for listener in listeners:
                listener(emitted)

    @staticmethod
    def _classify(event: EventEnvelope) -> KernelEventKind:
        event_type = event.event_type
        if event_type == "diagram.moved" or event_type == "program.function_owner_changed":
            return KernelEventKind.FUNCTION_MOVED
        if (
            event_type.startswith("freeform.")
            or event_type.startswith("mindmap.layout")
            or event_type.startswith("view.")
        ):
            return KernelEventKind.VIEW_LAYOUT_CHANGED
        if event_type in {"drakon.text_changed", "drakon.replaced"}:
            return KernelEventKind.EXPRESSION_CHANGED
        if "rename" in event_type:
            return KernelEventKind.SYMBOL_RENAMED
        return KernelEventKind.SEMANTIC_OBJECT_CHANGED

    def _register_query_capabilities(self) -> None:
        empty_contract: dict[str, JsonValue] = {"type": "object"}
        for identity, title, handler in (
            (
                "analysis.computation_attempts",
                "Inspect host computation attempts",
                self._computation_attempts_capability,
            ),
            (
                "analysis.computation_publications",
                "Inspect sealed computation publications",
                self._publications_capability,
            ),
        ):
            self.capabilities.register(
                CapabilityDescriptor(
                    identity,
                    title,
                    CapabilityKind.ANALYSIS,
                    "Read source-pinned host history without changing authored state.",
                    empty_contract,
                    empty_contract,
                ),
                handler,
            )
        self.capabilities.register(
            CapabilityDescriptor(
                "analysis.computation_backends",
                "Available computation backends",
                CapabilityKind.ANALYSIS,
                "Discover versioned terminal representation contracts.",
                empty_contract,
                empty_contract,
            ),
            self._computation_backends_capability,
        )
        self.capabilities.register(
            CapabilityDescriptor(
                "execution.computation",
                "Execute computation",
                CapabilityKind.EXECUTION,
                "Execute a pinned backend request and return immutable evidence.",
                empty_contract,
                empty_contract,
            ),
            self._computation_capability,
        )
        for name, title, handler in (
            ("start", "Start computation", self._computation_start_capability),
            ("advance", "Advance computation", self._computation_advance_capability),
            ("cancel", "Cancel computation", self._computation_cancel_capability),
        ):
            self.capabilities.register(
                CapabilityDescriptor(
                    f"execution.computation_{name}",
                    title,
                    CapabilityKind.EXECUTION,
                    "Control one revision-pinned backend lifecycle through the runtime plane.",
                    empty_contract,
                    empty_contract,
                ),
                handler,
            )
        self.capabilities.register(
            CapabilityDescriptor(
                "analysis.evidence",
                "Inspect computation evidence",
                CapabilityKind.ANALYSIS,
                "Read typed observations and their pinned origin provenance.",
                empty_contract,
                empty_contract,
            ),
            self._evidence_capability,
        )
        self.capabilities.register(
            CapabilityDescriptor(
                "generation.computation_plan",
                "Export portable computation plan",
                CapabilityKind.GENERATOR,
                "Publish a verified terminal resource for a worker without editor state.",
                empty_contract,
                empty_contract,
            ),
            self._computation_plan_capability,
        )
        self.capabilities.register(
            CapabilityDescriptor(
                "analysis.computation_sessions",
                "Inspect computation sessions",
                CapabilityKind.ANALYSIS,
                "Read pinned evidence sessions and supported cancellation capabilities.",
                empty_contract,
                empty_contract,
            ),
            self._computation_sessions_capability,
        )
        self.capabilities.register(
            CapabilityDescriptor(
                "analysis.workbench",
                "Inspect domain workbench",
                CapabilityKind.ANALYSIS,
                "Discover schemas, canonical domains, bundles, generators, "
                "and transformation diagnostics.",
                empty_contract,
                empty_contract,
            ),
            lambda _inputs: self.workbench(),
        )
        self.capabilities.register(
            CapabilityDescriptor(
                "view.notation",
                "Compile editable domain notation",
                CapabilityKind.VIEW,
                "Project canonical identities and explicit typed edit bindings "
                "with runtime origins.",
                {"type": "object", "required": ["model_id", "notation_id"]},
                empty_contract,
            ),
            self._notation_capability,
        )
        self.capabilities.register(
            CapabilityDescriptor(
                "execution.workbench.trace",
                "Trace domain program",
                CapabilityKind.EXECUTION,
                "Execute the derived program with the existing trace worker and runtime origins.",
                empty_contract,
                empty_contract,
            ),
            self._workbench_trace_capability,
        )
        self.capabilities.register(
            CapabilityDescriptor(
                "analysis.semantic",
                "Inspect semantic object",
                CapabilityKind.ANALYSIS,
                "Resolve one stable semantic identity in the current project revision.",
                {"required": ["object_id"], "type": "object"},
                empty_contract,
            ),
            self._semantic_capability,
        )
        for projection in ProjectionKind:
            if projection is ProjectionKind.COMPOSED:
                continue
            capability_id = f"view.{projection.value}"
            self.capabilities.register(
                CapabilityDescriptor(
                    capability_id,
                    f"{projection.value.replace('_', ' ').title()} projection",
                    CapabilityKind.VIEW,
                    "Build a disposable graph projection from the semantic program.",
                    {"type": "object"},
                    empty_contract,
                ),
                (
                    self._runtime_capability
                    if projection is ProjectionKind.RUNTIME
                    else self._projection_capability(projection)
                ),
            )
        self.capabilities.register(
            CapabilityDescriptor(
                "view.compose",
                "Compose semantic projection",
                CapabilityKind.VIEW,
                "Apply scope, relation, filtering, grouping, decoration, label, and layout rules.",
                {"required": ["definition"], "type": "object"},
                empty_contract,
            ),
            self._compose_capability,
        )
        self.capabilities.register(
            CapabilityDescriptor(
                "analysis.runtime_history",
                "Inspect runtime history",
                CapabilityKind.ANALYSIS,
                "Read the bounded, revision-pinned execution timeline for a debugger session.",
                {"type": "object"},
                empty_contract,
            ),
            self._runtime_history_capability,
        )
        self.capabilities.register(
            CapabilityDescriptor(
                "analysis.dataflow",
                "Analyze data flow",
                CapabilityKind.ANALYSIS,
                "Build the symbol/expression dependency projection for a semantic root.",
                {"type": "object"},
                empty_contract,
            ),
            self._projection_capability(ProjectionKind.DATA),
        )

    def _semantic_capability(self, inputs: Mapping[str, object]) -> object:
        object_id = inputs.get("object_id")
        if not isinstance(object_id, str) or not object_id:
            raise ValueError("analysis.semantic requires object_id")
        value = self.queries.semantic_object(object_id)
        return None if value is None else semantic_object_to_data(value)

    def _computation_backends_capability(self, _inputs: Mapping[str, object]) -> object:
        from code_visualizer.application.computation import available_backends

        return available_backends(self)

    def _computation_capability(self, inputs: Mapping[str, object]) -> object:
        from code_visualizer.application.computation import execute_computation
        from code_visualizer.domain.computation import ComputationRequest
        from code_visualizer.persistence.computation import computation_request_from_data
        from code_visualizer.persistence.evidence import evidence_to_data

        raw = inputs.get("request")
        request = raw if isinstance(raw, ComputationRequest) else computation_request_from_data(raw)
        return evidence_to_data(execute_computation(self, request))

    def _computation_start_capability(self, inputs: Mapping[str, object]) -> object:
        from code_visualizer.application.computation import start_computation
        from code_visualizer.domain.computation import ComputationRequest
        from code_visualizer.persistence.computation import computation_request_from_data

        raw = inputs.get("request")
        request = raw if isinstance(raw, ComputationRequest) else computation_request_from_data(raw)
        return start_computation(self, request)

    def _computation_advance_capability(self, inputs: Mapping[str, object]) -> object:
        from code_visualizer.application.computation import advance_computation
        from code_visualizer.domain.evidence import ComputationEvidence
        from code_visualizer.persistence.evidence import evidence_to_data

        identity = inputs.get("session_id")
        if not isinstance(identity, str) or not identity:
            raise ValueError("Computation advance requires a session_id")
        update = advance_computation(self, identity)
        return evidence_to_data(update) if isinstance(update, ComputationEvidence) else update

    def _computation_cancel_capability(self, inputs: Mapping[str, object]) -> object:
        from code_visualizer.application.computation import cancel_computation
        from code_visualizer.domain.computation import CancelRequest

        identity, reason = inputs.get("session_id"), inputs.get("reason", "")
        if not isinstance(identity, str) or not isinstance(reason, str):
            raise ValueError("Computation cancellation requires text session_id and reason")
        return cancel_computation(self, CancelRequest(identity, reason))

    def _evidence_capability(self, inputs: Mapping[str, object]) -> object:
        from code_visualizer.application.computation import get_evidence
        from code_visualizer.persistence.evidence import evidence_to_data

        evidence_id = inputs.get("evidence_id")
        if evidence_id is None:
            return [evidence_to_data(item) for item in self.runtime.evidence_records()]
        if not isinstance(evidence_id, str):
            raise ValueError("evidence_id must be text")
        evidence = get_evidence(self, evidence_id)
        return evidence_to_data(evidence) if evidence is not None else None

    def _publications_capability(self, inputs: Mapping[str, object]) -> object:
        from code_visualizer.persistence.publications import publication_to_data

        identity = inputs.get("publication_id")
        if identity is None:
            retained = {
                identity
                for attempt in self.computations.attempts()
                for identity in attempt.publications
            }
            if self.evidence_store is not None:
                retained.update(self.evidence_store.publication_identities())
            return tuple(sorted(retained))
        if not isinstance(identity, str):
            raise ValueError("publication_id must be text")
        publication = self.computations.publication(identity)
        if publication is None and self.evidence_store is not None:
            publication = self.evidence_store.get_publication(identity)
        return publication_to_data(publication) if publication is not None else None

    def _computation_plan_capability(self, inputs: Mapping[str, object]) -> object:
        from code_visualizer.application.computation import export_computation_plan
        from code_visualizer.domain.computation import ComputationRequest
        from code_visualizer.persistence.computation import (
            computation_plan_to_data,
            computation_request_from_data,
        )

        raw = inputs.get("request")
        request = raw if isinstance(raw, ComputationRequest) else computation_request_from_data(raw)
        return computation_plan_to_data(export_computation_plan(self, request))

    def _computation_sessions_capability(self, _inputs: Mapping[str, object]) -> object:
        from code_visualizer.application.computation import computation_sessions

        return computation_sessions(self)

    def _computation_attempts_capability(self, _inputs: Mapping[str, object]) -> object:
        return self.computations.attempts()

    def _notation_capability(self, inputs: Mapping[str, object]) -> object:
        model_id, notation_id = inputs.get("model_id"), inputs.get("notation_id")
        if not isinstance(model_id, str) or not isinstance(notation_id, str):
            raise ValueError("view.notation requires model_id and notation_id")
        return self.notation(model_id, notation_id)

    def _workbench_trace_capability(self, inputs: Mapping[str, object]) -> object:
        from code_visualizer.application.domain_execution import trace_project

        model_id = inputs.get("model_id")
        if model_id is not None and not isinstance(model_id, str):
            raise ValueError("model_id must be text or absent")
        result = trace_project(self, model_id=model_id)
        active = self.runtime.active
        return {
            "return_code": result.run.return_code,
            "stdout": result.run.stdout,
            "stderr": result.run.stderr,
            "event_count": len(result.runtime_events),
            "execution_session_id": active.execution_session_id if active is not None else None,
            "revision": active.project_revision if active is not None else self.revision,
        }

    def _projection_capability(
        self,
        kind: ProjectionKind,
    ) -> Callable[[Mapping[str, object]], object]:
        def build(inputs: Mapping[str, object]) -> object:
            raw_root = inputs.get("root_id")
            root = raw_root if isinstance(raw_root, str) and raw_root else None
            return projection_to_data(self.project_projection(kind, root))

        return build

    def _runtime_capability(self, _inputs: Mapping[str, object]) -> object:
        active = self.runtime.active
        return None if active is None else runtime_session_to_data(active)

    def _runtime_history_capability(self, inputs: Mapping[str, object]) -> object:
        raw_session_id = inputs.get("execution_session_id")
        session_id = raw_session_id if isinstance(raw_session_id, str) else None
        return [runtime_session_to_data(item) for item in self.runtime.history(session_id)]

    def _compose_capability(self, inputs: Mapping[str, object]) -> object:
        definition = projection_definition_from_data(
            inputs.get("definition"),
            "$.capability.definition",
        )
        return projection_to_data(self.compose_projection(definition))
