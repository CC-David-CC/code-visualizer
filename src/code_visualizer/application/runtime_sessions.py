"""Kernel-owned execution sessions linked back to stable semantic identities."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from threading import RLock

from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.computation import ComputationSession, ProgressEvent
from code_visualizer.domain.evidence import (
    ComputationEvidence,
    ComputationOutcome,
    EvidenceObservation,
    ObservationEvent,
    PublicationEvent,
)
from code_visualizer.domain.preview import PreviewEvent
from code_visualizer.domain.transformation import OriginMap
from code_visualizer.execution import (
    DebugEvent,
    RuntimeGraph,
    RuntimeGraphDelta,
    RuntimeTraceStore,
    SourceLocation,
)
from code_visualizer.execution.lifecycle import BackendExecution


class RuntimeSessionStatus(StrEnum):
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    FINISHED = "finished"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class RuntimeSessionState:
    execution_session_id: str
    project_revision: int
    artifact_revision: int
    status: RuntimeSessionStatus
    event_sequence: int = 0
    semantic_id: str | None = None
    graph: RuntimeGraph | None = None
    result: str = ""
    detail: str = ""
    graph_history_index: int | None = None
    origin_ids: tuple[str, ...] = ()
    evidence_id: str | None = None
    observation: EvidenceObservation | None = None
    progress: ProgressEvent | None = None
    location: SourceLocation | None = None
    publication_id: str | None = None
    preview: PreviewEvent | None = None

    @property
    def active_ids(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (
                    *((self.semantic_id,) if self.semantic_id else ()),
                    *self.origin_ids,
                    *(self.observation.semantic_ids if self.observation is not None else ()),
                )
            )
        )


RuntimeSessionListener = Callable[[RuntimeSessionState], None]


class RuntimeSessionRegistry:
    """Bounded-lifetime execution state; no runtime data enters project persistence."""

    def __init__(self, *, history_limit: int = 500, project_id: str | None = None) -> None:
        if history_limit < 1:
            raise ValueError("history_limit must be positive")
        self.history_limit = history_limit
        self.project_id = project_id
        self._sessions: dict[str, RuntimeSessionState] = {}
        self._history: dict[str, deque[RuntimeSessionState]] = {}
        self._traces: dict[str, RuntimeTraceStore] = {}
        self._origins: dict[str, OriginMap] = {}
        self._evidence: dict[str, ComputationEvidence] = {}
        self._computations: dict[str, BackendExecution] = {}
        self._scientific_ids: set[str] = set()
        self._active_id: str | None = None
        self._listeners: list[RuntimeSessionListener] = []
        self._lock = RLock()

    @property
    def active(self) -> RuntimeSessionState | None:
        with self._lock:
            return self._sessions.get(self._active_id or "")

    def sessions(self) -> tuple[RuntimeSessionState, ...]:
        with self._lock:
            return tuple(
                sorted(self._sessions.values(), key=lambda item: item.execution_session_id)
            )

    def session_state(self, session_id: str) -> RuntimeSessionState | None:
        with self._lock:
            return self._sessions.get(session_id)

    def history(
        self,
        execution_session_id: str | None = None,
    ) -> tuple[RuntimeSessionState, ...]:
        """Return a bounded immutable execution timeline for one session.

        Omitting the identity follows the active session, which keeps GUI and
        automation consumers synchronized without introducing another selection
        authority into the persisted project.
        """

        with self._lock:
            session_id = execution_session_id or self._active_id
            if session_id is None:
                return ()
            trace = self._traces.get(session_id)
            return tuple(
                replace(
                    item,
                    graph=(
                        trace.graph_at(item.graph_history_index)
                        if trace is not None and item.graph_history_index is not None
                        else None
                    ),
                )
                for item in self._history.get(session_id, ())
            )

    def subscribe(
        self,
        listener: RuntimeSessionListener,
        *,
        replay: bool = True,
    ) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(listener)
            active = self._sessions.get(self._active_id or "")
        if replay and active is not None:
            listener(active)

        def unsubscribe() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe

    def record(self, event: DebugEvent, semantic_id: str | None = None) -> RuntimeSessionState:
        session_id = event.execution_session_id
        if not session_id:
            raise ValueError("Runtime events require an execution_session_id")
        graph = event.runtime_graph
        if graph is not None and (
            graph.execution_session_id != session_id
            or graph.project_revision != event.project_revision
            or graph.artifact_revision != event.artifact_revision
            or graph.sequence != event.sequence
        ):
            raise ValueError("Runtime graph identity and revisions must match its debug event")
        status = {
            "started": RuntimeSessionStatus.RUNNING,
            "paused": RuntimeSessionStatus.PAUSED,
            "finished": RuntimeSessionStatus.FINISHED,
            "failed": RuntimeSessionStatus.FAILED,
            "stopped": RuntimeSessionStatus.STOPPED,
        }.get(event.event, RuntimeSessionStatus.RUNNING)
        with self._lock:
            existing = self._sessions.get(session_id)
            origins = self._origins.get(session_id)
            if origins is not None and (
                origins.revision != event.project_revision
                or origins.revision != event.artifact_revision
            ):
                raise ValueError("Runtime origins must match the event's pinned revisions")
            if existing is not None and (
                existing.project_revision != event.project_revision
                or existing.artifact_revision != event.artifact_revision
            ):
                raise ValueError("A runtime session cannot change its pinned revisions")
            trace = self._traces.setdefault(
                session_id,
                RuntimeTraceStore(history_limit=self.history_limit),
            )
            update = event.runtime_delta
            if update is None and event.runtime_graph is not None:
                graph = event.runtime_graph
                update = RuntimeGraphDelta(
                    graph.execution_session_id,
                    graph.project_revision,
                    graph.artifact_revision,
                    graph.sequence,
                    graph.frame_id,
                    graph.bindings,
                    graph.values,
                    (),
                    graph.history_index,
                    True,
                    graph.truncated,
                )
            if update is not None:
                trace.append(update)
            history_index = (
                update.history_index
                if update is not None
                else (existing.graph_history_index if existing is not None else None)
            )
            current_graph = trace.graph_at(history_index) if history_index is not None else None
            state = RuntimeSessionState(
                session_id,
                event.project_revision,
                event.artifact_revision,
                status,
                event.sequence,
                semantic_id
                if semantic_id is not None
                else (existing.semantic_id if existing is not None else None),
                current_graph
                if current_graph is not None
                else (existing.graph if existing else None),
                event.result,
                event.detail,
                history_index,
                (
                    origins.sources(semantic_id)
                    if origins is not None and semantic_id is not None
                    else existing.origin_ids
                    if existing is not None and semantic_id is None
                    else ()
                ),
                location=(
                    event.location
                    if event.file_path and event.line > 0
                    else existing.location
                    if existing is not None
                    else None
                ),
            )
            self._sessions[session_id] = state
            self._active_id = session_id
            self._append_history(state)
            listeners = tuple(self._listeners)
        for listener in listeners:
            listener(state)
        return state

    def register_origins(self, execution_session_id: str, origins: OriginMap) -> None:
        """Bind a derived artifact's immutable origins to one execution session."""

        if not execution_session_id:
            raise ValueError("Runtime origins require an execution session identity")
        if self.project_id is not None and self.project_id != origins.project_id:
            raise ValueError("Runtime origins belong to another project")
        with self._lock:
            state = self._sessions.get(execution_session_id)
            if state is not None and (
                state.project_revision != origins.revision
                or state.artifact_revision != origins.revision
            ):
                raise ValueError("Runtime origins must match the session's pinned revisions")
            previous = self._origins.get(execution_session_id)
            if previous is not None and previous != origins:
                raise ValueError("A runtime session cannot replace its pinned origins")
            self._origins[execution_session_id] = origins

    def evidence(self, evidence_id: str) -> ComputationEvidence | None:
        with self._lock:
            return self._evidence.get(evidence_id)

    def evidence_records(self) -> tuple[ComputationEvidence, ...]:
        with self._lock:
            return tuple(self._evidence[key] for key in sorted(self._evidence))

    def record_evidence(
        self, execution_session_id: str, evidence: ComputationEvidence, *, replay: bool = True
    ) -> RuntimeSessionState:
        """Publish backend-neutral observations on the existing runtime timeline."""
        from code_visualizer.persistence.evidence import evidence_content_hash

        if evidence.id != "evidence:" + evidence_content_hash(evidence):
            raise ValueError("Runtime evidence identity does not match its content")
        provenance = evidence.provenance
        if self.project_id is not None and self.project_id != provenance.project_id:
            raise ValueError("Computation evidence belongs to another project")
        mapped = {item.generated_id for item in provenance.origins.links}
        ids = [item.semantic_ids for item in evidence.observations] + [
            item.semantic_ids for item in evidence.artifacts
        ]
        if any(set(identities) - mapped for identities in ids):
            raise ValueError("Computation evidence contains unmapped semantic identities")
        with self._lock:
            previous = self._evidence.get(evidence.id)
            if previous is not None and previous != evidence:
                raise ValueError("An evidence identity cannot replace different observations")
        self.register_origins(execution_session_id, provenance.origins)
        if replay:
            state = self.mark_starting(
                execution_session_id, provenance.revision, provenance.revision
            )
        else:
            with self._lock:
                state = self._sessions[execution_session_id]
        with self._lock:
            self._evidence[evidence.id] = evidence
            while len(self._evidence) > self.history_limit:
                del self._evidence[next(iter(self._evidence))]
        for observation in evidence.observations if replay else ():
            origin_ids = tuple(
                dict.fromkeys(
                    origin
                    for identity in observation.semantic_ids
                    for origin in provenance.origins.sources(identity)
                )
            )
            state = replace(
                state,
                status=RuntimeSessionStatus.RUNNING,
                event_sequence=observation.sequence + 1,
                semantic_id=observation.semantic_ids[0] if observation.semantic_ids else None,
                origin_ids=origin_ids,
                evidence_id=evidence.id,
                observation=observation,
                result=observation.label,
            )
            self._publish_evidence_state(state)
        state = replace(
            state,
            status={
                ComputationOutcome.SUCCEEDED: RuntimeSessionStatus.FINISHED,
                ComputationOutcome.FAILED: RuntimeSessionStatus.FAILED,
                ComputationOutcome.CANCELLED: RuntimeSessionStatus.STOPPED,
            }[evidence.outcome],
            event_sequence=state.event_sequence + 1,
            evidence_id=evidence.id,
            detail="\n".join(item.message for item in evidence.diagnostics),
        )
        self._publish_evidence_state(state)
        return state

    def bind_computation(self, execution: BackendExecution) -> None:
        """The existing runtime plane owns ephemeral backend controls as well as traces."""
        session = execution.session
        with self._lock:
            if session.id in self._computations or session.id in self._sessions:
                raise ValueError("A computation session identity is already owned")
            self.register_origins(session.id, execution.snapshot.origins)
            self._computations[session.id] = execution
            self._scientific_ids.add(session.id)
        self.mark_starting(session.id, session.revision, session.revision)

    def mark_computation_starting(self, session: ComputationSession) -> None:
        with self._lock:
            self._scientific_ids.add(session.id)
        self.mark_starting(session.id, session.revision, session.revision)

    def fail_computation(self, session_id: str, detail: str, *, cancelled: bool = False) -> None:
        with self._lock:
            state = self._sessions.get(session_id)
        if state is not None:
            self._publish_evidence_state(
                replace(
                    state,
                    status=RuntimeSessionStatus.STOPPED
                    if cancelled
                    else RuntimeSessionStatus.FAILED,
                    detail=detail,
                )
            )

    def computation(self, session_id: str) -> BackendExecution | None:
        with self._lock:
            return self._computations.get(session_id)

    def computations(self) -> tuple[BackendExecution, ...]:
        with self._lock:
            return tuple(self._computations[key] for key in sorted(self._computations))

    def release_computation(self, session_id: str) -> None:
        with self._lock:
            execution = self._computations.pop(session_id, None)
        if execution is not None:
            execution.close()

    def abandon_computation(self, session_id: str) -> None:
        """An inadmissible result cannot leave a valid-looking runtime session."""
        self.release_computation(session_id)
        with self._lock:
            self._sessions.pop(session_id, None)
            self._history.pop(session_id, None)
            self._traces.pop(session_id, None)
            self._origins.pop(session_id, None)
            self._scientific_ids.discard(session_id)
            if self._active_id == session_id:
                self._active_id = next(reversed(self._sessions), None)

    def record_computation_update(
        self, update: ProgressEvent | ObservationEvent | PublicationEvent | PreviewEvent
    ) -> RuntimeSessionState:
        """Publish an admitted lifecycle update through the shared selection timeline."""
        with self._lock:
            state = self._sessions[update.session_id]
            origins = self._origins[update.session_id]
        if isinstance(update, PreviewEvent):
            state = replace(state, preview=update, event_sequence=update.sequence + 1)
            # No history accumulation and no accepted selection/cursor changes.
            with self._lock:
                self._sessions[update.session_id] = state
            return state
        if isinstance(update, ProgressEvent):
            state = replace(
                state,
                status=RuntimeSessionStatus.RUNNING,
                event_sequence=update.sequence + 1,
                detail=update.message,
                progress=update,
            )
        elif isinstance(update, PublicationEvent):
            artifact = update.publication.artifact
            state = replace(
                state,
                status=RuntimeSessionStatus.RUNNING,
                event_sequence=update.sequence + 1,
                semantic_id=artifact.semantic_ids[0] if artifact.semantic_ids else None,
                origin_ids=tuple(
                    dict.fromkeys(
                        origin
                        for identity in artifact.semantic_ids
                        for origin in origins.sources(identity)
                    )
                ),
                publication_id=update.publication.id,
                result=artifact.label,
            )
        else:
            observation = update.observation
            state = replace(
                state,
                status=RuntimeSessionStatus.RUNNING,
                event_sequence=observation.sequence + 1,
                semantic_id=observation.semantic_ids[0] if observation.semantic_ids else None,
                origin_ids=tuple(
                    dict.fromkeys(
                        origin
                        for identity in observation.semantic_ids
                        for origin in origins.sources(identity)
                    )
                ),
                observation=observation,
                result=observation.label,
            )
        self._publish_evidence_state(state)
        return state

    def _publish_evidence_state(self, state: RuntimeSessionState) -> None:
        with self._lock:
            self._sessions[state.execution_session_id] = state
            self._active_id = state.execution_session_id
            self._append_history(replace(state, preview=None))
            listeners = tuple(self._listeners)
        for listener in listeners:
            listener(state)

    def mark_starting(
        self,
        execution_session_id: str,
        project_revision: int,
        artifact_revision: int,
    ) -> RuntimeSessionState:
        if not execution_session_id:
            raise ValueError("Runtime sessions require an execution session identity")
        if project_revision < 0 or artifact_revision < 0:
            raise ValueError("Runtime revisions must not be negative")
        state = RuntimeSessionState(
            execution_session_id,
            project_revision,
            artifact_revision,
            RuntimeSessionStatus.STARTING,
        )
        with self._lock:
            previous = self._sessions.get(execution_session_id)
            if previous is not None and (
                previous.project_revision != project_revision
                or previous.artifact_revision != artifact_revision
            ):
                raise ValueError("A runtime session cannot change its pinned revisions")
            origins = self._origins.get(execution_session_id)
            if origins is not None and (
                origins.revision != project_revision or origins.revision != artifact_revision
            ):
                raise ValueError("Runtime origins must match the session's pinned revisions")
            self._history.pop(execution_session_id, None)
            self._traces[execution_session_id] = RuntimeTraceStore(history_limit=self.history_limit)
            self._sessions[execution_session_id] = state
            self._active_id = execution_session_id
            self._append_history(state)
            listeners = tuple(self._listeners)
        for listener in listeners:
            listener(state)
        return state

    def clear(self) -> None:
        with self._lock:
            for execution in self._computations.values():
                execution.close()
            self._computations.clear()
            self._scientific_ids.clear()
            self._sessions.clear()
            self._history.clear()
            self._traces.clear()
            self._origins.clear()
            self._evidence.clear()
            self._active_id = None
            self._listeners.clear()

    def clear_interactive(self) -> None:
        """Detach an editor without destroying retained scientific attempts."""
        with self._lock:
            retained = self._scientific_ids | {
                identity
                for identity, state in self._sessions.items()
                if state.evidence_id is not None or state.publication_id is not None
            }
            for identity in tuple(self._sessions):
                if identity not in retained:
                    self._sessions.pop(identity, None)
                    self._history.pop(identity, None)
                    self._traces.pop(identity, None)
                    self._origins.pop(identity, None)
            if self._active_id not in retained:
                self._active_id = next(reversed(self._sessions), None)
            self._listeners.clear()

    def _append_history(self, state: RuntimeSessionState) -> None:
        history = self._history.setdefault(
            state.execution_session_id,
            deque(maxlen=self.history_limit),
        )
        history.append(replace(state, graph=None))


def runtime_session_to_data(state: RuntimeSessionState) -> dict[str, JsonValue]:
    from code_visualizer.persistence.values import canonical_value_to_data

    graph = state.graph
    graph_data: dict[str, JsonValue] | None = None
    if graph is not None:
        graph_data = {
            "artifact_revision": graph.artifact_revision,
            "bindings": [
                {
                    "changed": item.changed,
                    "frame_id": item.frame_id,
                    "name": item.name,
                    "semantic_symbol_id": item.semantic_symbol_id,
                    "value_id": item.value_id,
                }
                for item in graph.bindings
            ],
            "checkpoint": graph.checkpoint,
            "execution_session_id": graph.execution_session_id,
            "frame_id": graph.frame_id,
            "history_index": graph.history_index,
            "project_revision": graph.project_revision,
            "sequence": graph.sequence,
            "truncated": graph.truncated,
            "values": [
                {
                    "children": [
                        {
                            "key_id": child.key_id,
                            "label": child.label,
                            "value_id": child.value_id,
                        }
                        for child in item.children
                    ],
                    "kind": item.kind.value,
                    "preview": item.preview,
                    "scalar_value": item.scalar_value,
                    "truncated": item.truncated,
                    "type_id": item.type_id,
                    "value_id": item.value_id,
                }
                for item in graph.values
            ],
        }
    return {
        "artifact_revision": state.artifact_revision,
        "detail": state.detail,
        "event_sequence": state.event_sequence,
        "execution_session_id": state.execution_session_id,
        "graph": graph_data,
        "graph_history_index": state.graph_history_index,
        "project_revision": state.project_revision,
        "result": state.result,
        "semantic_id": state.semantic_id,
        "origin_ids": list(state.origin_ids),
        "status": state.status.value,
        "location": {
            "file_path": state.location.file_path,
            "line": state.location.line,
            "column": state.location.column,
        }
        if state.location is not None
        else None,
        "evidence_id": state.evidence_id,
        "progress": {
            "completed": state.progress.completed,
            "total": state.progress.total,
            "message": state.progress.message,
            "sequence": state.progress.sequence,
        }
        if state.progress is not None
        else None,
        "observation": {
            "id": state.observation.id,
            "semantic_ids": list(state.observation.semantic_ids),
            "value": canonical_value_to_data(state.observation.value),
            "label": state.observation.label,
            "sequence": state.observation.sequence,
        }
        if state.observation is not None
        else None,
    }
