"""Host-owned scientific attempts; editors attach to the existing runtime plane."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from tempfile import TemporaryDirectory
from threading import Condition, Event, RLock
from typing import TYPE_CHECKING, TypedDict, Unpack

from code_visualizer.application.computation_publications import PublicationBudget
from code_visualizer.application.runtime_sessions import RuntimeSessionRegistry, RuntimeSessionState
from code_visualizer.domain.common import new_id
from code_visualizer.domain.computation import (
    CancelRequest,
    ComputationPlan,
    ComputationRequest,
    ComputationSession,
    ComputationStatus,
    ProgressEvent,
)
from code_visualizer.domain.evidence import (
    ComputationEvidence,
    ComputationOutcome,
    EvidencePublication,
    ObservationEvent,
    PublicationEvent,
)
from code_visualizer.domain.preview import PreviewEvent
from code_visualizer.domain.project import Project
from code_visualizer.execution.computation_driver import InProcessDriver
from code_visualizer.generation.transformation import TransformationError

if TYPE_CHECKING:
    from code_visualizer.application.retained_computation import RetainedComputation
    from code_visualizer.application.selection import SelectionService
    from code_visualizer.execution.backends import PreparedComputation
    from code_visualizer.execution.computation_driver import ManagedPythonDriver
    from code_visualizer.execution.lifecycle import BackendExecution
    from code_visualizer.execution.worker_process import WorkerProcess, WorkerProfile
    from code_visualizer.extensions.registry import DomainExtensionRegistry
    from code_visualizer.persistence.evidence_store import EvidenceStore
    from code_visualizer.persistence.resource_store import ResourceStore


ComputationUpdate = (
    ComputationEvidence | ProgressEvent | ObservationEvent | PublicationEvent | PreviewEvent
)


class AttemptChanges(TypedDict, total=False):
    session: ComputationSession
    phase: str
    source_digest: str | None
    input_digest: str | None
    progress: ProgressEvent | None
    preview: PreviewEvent | None
    publications: tuple[str, ...]
    diagnostic: str
    worker_pid: int | None
    forced_termination: bool


@dataclass(slots=True)
class ComputationAttachment:
    id: str
    runtime: RuntimeSessionRegistry
    revision: int = 0
    attached: bool = True
    selection: SelectionService | None = None
    pending_selection: RuntimeSessionState | None = None


@dataclass(frozen=True, slots=True)
class ComputationAttempt:
    session: ComputationSession
    attachment_id: str
    phase: str = "queued"
    source_digest: str | None = None
    input_digest: str | None = None
    progress: ProgressEvent | None = None
    publications: tuple[str, ...] = ()
    diagnostic: str = ""
    update_index: int = 0
    worker_pid: int | None = None
    forced_termination: bool = False
    preview: PreviewEvent | None = None


@dataclass(slots=True)
class ComputationJob:
    """One attempt's controls and frozen inputs; never an editor/authority reference."""

    attachment: ComputationAttachment
    project: Project
    request: ComputationRequest
    registry: DomainExtensionRegistry
    resource_store: ResourceStore | None
    evidence_store: EvidenceStore | None
    view: ComputationAttempt
    retention: RetainedComputation | None = None
    snapshot: PreparedComputation | None = None
    plan: ComputationPlan | None = None
    execution: BackendExecution | None = None
    worker: WorkerProcess | None = None
    managed: ManagedPythonDriver | None = None
    last_progress_time: float = 0.0
    temporary_store: TemporaryDirectory[str] | None = None
    evidence: ComputationEvidence | None = None
    publications: dict[str, EvidencePublication] = field(default_factory=dict)
    publication_budget: PublicationBudget = field(default_factory=PublicationBudget)
    error: Exception | None = None
    update: ComputationUpdate | None = None
    delivered_index: int = -1
    done: Event = field(default_factory=Event)
    cancelled: Event = field(default_factory=Event)
    condition: Condition = field(default_factory=Condition)


class ComputationService:
    """One bounded lifecycle for GUI submit and headless wait.

    Production strategies supervise processes. The explicit in-process strategy
    permits trusted embedding and deterministic unit-test stepping; it is never
    inferred from an unavailable worker or a callback's Python implementation.
    """

    def __init__(
        self,
        *,
        in_process: InProcessDriver | None = None,
        profiles: tuple[WorkerProfile, ...] | None = None,
        max_workers: int = 4,
        max_attempts: int = 256,
    ) -> None:
        if max_workers < 1 or max_attempts < max_workers:
            raise ValueError("Computation limits must be positive and internally consistent")
        self.in_process = in_process
        self.profiles = profiles
        self.max_attempts = max_attempts
        self._attachments: dict[str, ComputationAttachment] = {}
        self._jobs: dict[str, ComputationJob] = {}
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="computation")
        self._lock = RLock()
        self._closed = False

    def attach(self, project_id: str) -> ComputationAttachment:
        with self._lock:
            if self._closed:
                raise RuntimeError("The computation host is closed")
            attachment = ComputationAttachment(
                new_id("computation-attachment"), RuntimeSessionRegistry(project_id=project_id)
            )
            self._attachments[attachment.id] = attachment
            return attachment

    def detach(self, attachment_id: str) -> None:
        with self._lock:
            attachment = self._attachments.get(attachment_id)
            if attachment is not None:
                attachment.attached = False
                attachment.selection = None
                attachment.pending_selection = None
                attachment.runtime.clear_interactive()

    def submit(
        self,
        attachment: ComputationAttachment,
        project: Project,
        request: ComputationRequest,
        host_registry: DomainExtensionRegistry,
        resource_store: ResourceStore | None,
        evidence_store: EvidenceStore | None,
        *,
        retention: RetainedComputation | None = None,
    ) -> ComputationSession:
        if (project.id, project.revision) != (request.project_id, request.revision):
            raise TransformationError("COMPUTATION_REVISION", "Request does not match its snapshot")
        if evidence_store is not None and resource_store is None:
            raise TransformationError(
                "COMPUTATION_RESOURCE_STORE",
                "Durable evidence requires a resource store for its reproducible terminal input",
            )
        if retention is not None:
            from hashlib import sha256

            from code_visualizer.persistence.canonical import canonical_data_bytes
            from code_visualizer.persistence.serialization import project_to_data

            retention.admit(sha256(canonical_data_bytes(project_to_data(project))).hexdigest())
        with self._lock:
            if self._closed or not attachment.attached:
                raise TransformationError(
                    "COMPUTATION_HOST_CLOSED", "The editing attachment is closed"
                )
            if attachment.id not in self._attachments:
                raise ValueError("Computation attachment belongs to another host")
            if len(self._jobs) >= self.max_attempts:
                raise TransformationError(
                    "COMPUTATION_ATTEMPT_LIMIT", "The host attempt limit was reached"
                )
            session = ComputationSession(
                retention.id if retention is not None else new_id("computation-session"),
                project.id,
                project.revision,
                request.backend_id,
                request.backend_version,
                ComputationStatus.QUEUED,
            )
            job = ComputationJob(
                attachment,
                project,
                request,
                host_registry.host_registry,
                resource_store,
                evidence_store,
                ComputationAttempt(session, attachment.id),
                retention=retention,
            )
            if self.in_process is not None:
                from code_visualizer.application.computation_jobs import prepare_in_process

                prepare_in_process(self, job)
            else:
                attachment.runtime.mark_computation_starting(session)
            self._jobs[session.id] = job
            if self.in_process is None:
                from code_visualizer.application.computation_jobs import run_process_job

                self._pool.submit(run_process_job, self, job)
            return job.view.session

    def attempts(self) -> tuple[ComputationAttempt, ...]:
        with self._lock:
            return tuple(job.view for job in self._jobs.values())

    def evidence(self, session_id: str) -> ComputationEvidence | None:
        return self.job(session_id).evidence

    def state(self, session_id: str) -> RuntimeSessionState | None:
        return self.job(session_id).attachment.runtime.session_state(session_id)

    def publication(self, publication_id: str) -> EvidencePublication | None:
        with self._lock:
            return next(
                (
                    job.publications[publication_id]
                    for job in self._jobs.values()
                    if publication_id in job.publications
                ),
                None,
            )

    def job(self, session_id: str) -> ComputationJob:
        with self._lock:
            job = self._jobs.get(session_id)
        if job is None:
            raise TransformationError(
                "COMPUTATION_SESSION", "No active computation has that identity"
            )
        return job

    def changed(self, job: ComputationJob, **changes: Unpack[AttemptChanges]) -> None:
        with job.condition:
            # All mutations are serialized by the one attempt driver. Readers get
            # an immutable snapshot, not a reference to mutable backend state.
            updated = replace(job.view, update_index=job.view.update_index + 1, **changes)
            if job.retention is not None:
                job.retention.changed(job.view, updated)
            job.view = updated
            job.condition.notify_all()

    def publish(self, job: ComputationJob, update: ComputationUpdate) -> None:
        runtime = job.attachment.runtime
        if isinstance(update, PublicationEvent):
            # Retention must accept the receipt before it enters the live plane
            # or the ledger used to construct failure evidence. A sealed orphan
            # receipt is not an acknowledged publication of this attempt.
            self.changed(job, publications=(*job.view.publications, update.publication.id))
            job.publications[update.publication.id] = update.publication
            state = runtime.record_computation_update(update)
        elif isinstance(update, ComputationEvidence):
            state = runtime.record_evidence(
                job.view.session.id,
                update,
                replay=job.execution is None or job.execution.backend.stream is None,
            )
            job.evidence = update
            session = replace(
                job.view.session,
                status=ComputationStatus(update.outcome.value),
                evidence_id=update.id,
            )
            self.changed(job, session=session, phase="finished")
        else:
            state = runtime.record_computation_update(update)
            if isinstance(update, ProgressEvent):
                self.changed(job, progress=update, phase="running")
            elif isinstance(update, PreviewEvent):
                self.changed(job, preview=update)
            else:
                self.changed(job)
        attachment = job.attachment
        if (
            (isinstance(update, ComputationEvidence) or self.in_process is not None)
            and attachment.attached
            and attachment.revision == job.request.revision
            and attachment.selection is not None
            and state.active_ids
        ):
            with self._lock:
                attachment.pending_selection = state
            if self.in_process is not None:
                self.deliver_selection(attachment)
        with job.condition:
            job.update = update
            if isinstance(update, ComputationEvidence):
                job.done.set()
            job.condition.notify_all()

    def deliver_selection(self, attachment: ComputationAttachment) -> None:
        """Deliver latest semantic selection on the observer/headless caller's thread.

        Worker admission only records data. GUI observers call this from their Qt
        timer, so a selection subscriber never runs on an orchestration thread.
        """
        with self._lock:
            state, attachment.pending_selection = attachment.pending_selection, None
            selection = attachment.selection
        if (
            state is not None
            and attachment.attached
            and attachment.revision == state.project_revision
            and selection is not None
        ):
            selection.select(
                state.active_ids,
                revision=state.project_revision,
                source="runtime.computation",
                execution_session_id=state.execution_session_id,
            )

    def begin_finalization(self, job: ComputationJob, outcome: ComputationOutcome) -> None:
        """Linearize terminal admission against cancellation, before durable writes.

        Once a terminal result is being verified, cancellation cannot retroactively
        alter it. Earlier accepted cancellation can never become successful evidence.
        """
        with job.condition:
            if job.cancelled.is_set() and outcome is ComputationOutcome.SUCCEEDED:
                raise TransformationError(
                    "COMPUTATION_CANCELLED", "Cancelled work cannot be admitted as successful"
                )
            self.changed(job, phase="finalizing")

    def advance(self, session_id: str) -> ComputationUpdate:
        job = self.job(session_id)
        if self.in_process is not None:
            from code_visualizer.application.computation_jobs import advance_in_process

            if job.done.is_set():
                raise TransformationError(
                    "COMPUTATION_SESSION", "No active computation has that identity"
                )
            return advance_in_process(self, job)
        with job.condition:
            job.condition.wait_for(
                lambda: (
                    job.done.is_set()
                    or (job.update is not None and job.view.update_index != job.delivered_index)
                )
            )
            if job.error is not None:
                raise job.error
            job.delivered_index = job.view.update_index
            assert job.update is not None
            update = job.update
        self.deliver_selection(job.attachment)
        return update

    def wait(self, session_id: str) -> ComputationEvidence:
        job = self.job(session_id)
        while not job.done.is_set():
            self.advance(session_id)
        if job.error is not None:
            raise job.error
        assert job.evidence is not None
        self.deliver_selection(job.attachment)
        return job.evidence

    def cancel(self, request: CancelRequest) -> ComputationSession:
        job = self.job(request.session_id)
        with job.condition:
            if job.done.is_set():
                raise TransformationError(
                    "COMPUTATION_SESSION", "No active computation has that identity"
                )
            if job.view.phase == "finalizing":
                raise TransformationError(
                    "COMPUTATION_FINALIZING", "The terminal result is already being verified"
                )
            if self.in_process is not None:
                if job.execution is None or not job.execution.session.cancellation_supported:
                    raise TransformationError(
                        "COMPUTATION_CANCEL_UNSUPPORTED",
                        "This backend does not support cancellation",
                    )
                job.execution.cancel(request)
            job.cancelled.set()
            self.changed(job, phase="cancelling")
            worker, managed = job.worker, job.managed
        if worker is not None:
            from code_visualizer.protocol.worker import worker_control_to_bytes

            backend = job.registry.backend(job.request.backend_id, job.request.backend_version)
            worker.cancel(
                worker_control_to_bytes(request),
                grace_seconds=backend.cancellation_grace_seconds if backend is not None else 0.5,
            )
        if managed is not None:
            managed.cancel(request)
        return job.view.session

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            jobs = tuple(self._jobs.values())
        for job in jobs:
            with job.condition:
                if job.done.is_set() or job.view.phase == "finalizing":
                    continue
                job.cancelled.set()
                worker, managed, execution = job.worker, job.managed, job.execution
            if worker is not None:
                worker.close()
            if managed is not None:
                managed.close()
            if self.in_process is not None and execution is not None:
                execution.close()
        self._pool.shutdown(wait=True, cancel_futures=False)
        for attachment in self._attachments.values():
            attachment.runtime.clear()
        for job in jobs:
            if job.temporary_store is not None:
                job.temporary_store.cleanup()
