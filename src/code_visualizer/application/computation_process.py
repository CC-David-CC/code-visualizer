"""Supervised preparation, execution and resource admission for submitted attempts."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import replace
from functools import cache
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from code_visualizer.application.computation_publications import (
    seal_admitted_publication,
)
from code_visualizer.application.resource_admission import (
    check_resource_descriptor,
    check_value_contracts,
)
from code_visualizer.domain.boundaries import MAX_PORTABLE_ENVELOPE_BYTES
from code_visualizer.domain.computation import CancelRequest, ComputationStatus, ProgressEvent
from code_visualizer.domain.evidence import (
    ComputationEvidence,
    ComputationOutcome,
    EvidenceArtifact,
    EvidenceDiagnostic,
    ObservationEvent,
    PublicationEvent,
)
from code_visualizer.domain.preview import PreviewEvent
from code_visualizer.domain.resource_transfer import (
    ResourceTransferAbort,
    ResourceTransferFinish,
    ResourceTransferStart,
)
from code_visualizer.domain.resources import DataResource
from code_visualizer.domain.values import ResourceReference
from code_visualizer.domain.worker import (
    WorkerCompletionVerified,
    WorkerEvidenceProposal,
    WorkerExecutionRequest,
    WorkerFailure,
    WorkerPreparationRequest,
    WorkerPrepared,
    WorkerPublicationOffer,
    WorkerResourceEvent,
    WorkerTerminalSecured,
)
from code_visualizer.execution.backends import (
    BackendResult,
    ProducedResource,
    ProducedResourceEvent,
    ResourceFile,
    resource_references,
)
from code_visualizer.execution.computation_driver import managed_driver
from code_visualizer.execution.lifecycle import BackendExecution
from code_visualizer.execution.publication_budget import computation_provenance
from code_visualizer.execution.worker_process import (
    WorkerExited,
    WorkerProcess,
    WorkerProfile,
    profile_for_backend,
)
from code_visualizer.extensions.languages import resolve_domain_languages
from code_visualizer.generation.computation import computation_input_digest
from code_visualizer.generation.transformation import TransformationError
from code_visualizer.persistence.computation_terminal import decode_terminal
from code_visualizer.persistence.evidence_store import validate_portable_evidence
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.resource_transfer import ResourceTransferReceiver
from code_visualizer.persistence.serialization import project_data_chunks
from code_visualizer.protocol.worker import (
    worker_control_to_bytes,
    worker_event_from_bytes,
    worker_event_to_bytes,
)

if TYPE_CHECKING:
    from code_visualizer.application.computation_service import ComputationJob, ComputationService
    from code_visualizer.extensions.registry import DomainExtensionRegistry

MAX_PHASE_TRANSFER_BYTES = 2 * 1024 * 1024 * 1024
MAX_PHASE_TRANSFER_METADATA_BYTES = MAX_PORTABLE_ENVELOPE_BYTES
MAX_PHASE_RESOURCE_TRANSFERS = 4096


def _check_resources(
    references: tuple[ResourceReference, ...], store: ResourceStore, job: ComputationJob
) -> None:
    for reference in references:
        store.verified_path(reference)
        check_resource_descriptor(store.describe(reference), job.registry)


@cache
def _backend_keys(
    factory: Callable[[], DomainExtensionRegistry],
) -> tuple[tuple[str, str], ...]:
    """Installed static composition is immutable for one factory identity.

    Cache only inert contract keys. Registries, projects, worker commands and
    attempts keep their existing ownership and lifetimes.
    """
    return tuple((b.definition.id, b.definition.version) for b in factory().backends())


def default_profiles() -> tuple[WorkerProfile, ...]:
    from code_visualizer.execution.child_process import computation_worker_command
    from code_visualizer.extensions.builtin import builtin_registry

    return (
        WorkerProfile(
            "code_visualizer.computation.worker",
            "1",
            tuple(computation_worker_command(Path(__file__).with_name("computation_worker.py"))),
            _backend_keys(builtin_registry),
        ),
    )


class _Resources:
    def __init__(self, store: ResourceStore, job: ComputationJob) -> None:
        self.store, self.job = store, job
        self.receiver: ResourceTransferReceiver | None = None
        self.remaining = MAX_PHASE_TRANSFER_BYTES
        self.metadata_bytes = 0
        self.transfer_count = 0
        self.transferred: set[ResourceReference] = set()
        self.claimed: set[ResourceReference] = set()

    def accept(self, event: WorkerResourceEvent) -> None:
        frame = event.frame
        if isinstance(frame, ResourceTransferStart):
            if self.receiver is not None:
                raise ValueError("Worker transfers must finish before starting another")
            check_resource_descriptor(frame.resource, self.job.registry)
            if frame.resource.byte_size > self.remaining:
                raise ValueError("Worker phase resource-transfer budget exceeded")
            size = len(worker_event_to_bytes(event))
            if self.metadata_bytes + size > MAX_PHASE_TRANSFER_METADATA_BYTES:
                raise ValueError("Worker resource-transfer metadata budget exceeded")
            if self.transfer_count >= MAX_PHASE_RESOURCE_TRANSFERS:
                raise ValueError("Worker resource-transfer count budget exceeded")
            self.remaining -= frame.resource.byte_size
            self.metadata_bytes += size
            self.transfer_count += 1
            self.receiver = ResourceTransferReceiver(
                self.store,
                ResourceReference(frame.resource.id, frame.resource.content_hash),
                max_resource_bytes=frame.resource.byte_size,
            )
        if self.receiver is None:
            raise ValueError("A worker resource frame has no admitted transfer start")
        self.receiver.accept(frame)
        if isinstance(frame, ResourceTransferAbort):
            raise ValueError("Worker aborted a declared resource transfer")
        if isinstance(frame, ResourceTransferFinish):
            self.receiver.commit()
            self.transferred.add(self.receiver.expected)
            self.receiver.close()
            self.receiver = None

    def claim(self, references: tuple[ResourceReference, ...]) -> None:
        """Associate already complete resources with explicit semantic worker output."""
        if self.receiver is not None:
            raise ValueError("A worker output cannot precede completion of its resource transfer")
        self.claimed.update(self.job.registry.resource_closure(references, self))

    def describe(self, reference: ResourceReference) -> DataResource:
        # Check the transfer boundary before traversing any root or child. A
        # missing transfer is an invalid worker output, not a storage lookup.
        if reference not in self.transferred:
            raise ValueError("Worker output omitted a complete resource transfer")
        return self.store.describe(reference)

    def verified_path(self, reference: ResourceReference) -> Path:
        return self.store.verified_path(reference)

    def claim_transferred(self, references: tuple[ResourceReference, ...]) -> None:
        # claim() verifies the whole closure through this ledger's describe(),
        # which rejects every child absent from the completed transfer set.
        # A second walk adds no admission condition, but rehashes all bulk data
        # while the producer is waiting for its publication acknowledgment.
        self.claim(references)

    def complete(self, references: tuple[ResourceReference, ...]) -> None:
        """Reject unsolicited or omitted resources before acknowledging terminal output."""
        self.claim(references)
        if self.transferred - self.claimed:
            raise ValueError("Worker transferred resources not claimed by its output")
        if self.claimed - self.transferred:
            raise ValueError("Worker output omitted its declared resource transfers")

    def close(self) -> None:
        if self.receiver is not None:
            self.receiver.close()


def _launch(
    service: ComputationService,
    job: ComputationJob,
    store: ResourceStore,
    profile: WorkerProfile,
    request: WorkerPreparationRequest | WorkerExecutionRequest,
) -> WorkerProcess:
    worker = WorkerProcess(profile, environment=worker_resource_environment(store))
    job.worker = worker
    worker.start()
    service.changed(job, worker_pid=worker.pid)
    worker.send(worker_control_to_bytes(request))
    if job.cancelled.is_set():
        worker.cancel(worker_control_to_bytes(CancelRequest(job.view.session.id)))
    return worker


def worker_resource_environment(store: ResourceStore) -> dict[str, str]:
    """Launch with scratch writes and one directly owned durable input store.

    ResourceStore supports read-through composition within a process, but this
    worker lifetime contract carries exactly one input root. Reject deeper chains
    before launch rather than silently losing their ancestor resources.
    """
    if store.inputs is not None and store.inputs.inputs is not None:
        raise ValueError(
            "Computation workers require one direct durable input store; "
            "nested read-through inputs are unsupported"
        )
    environment = dict(os.environ)
    environment["CODE_VISUALIZER_COMPUTATION_RESOURCES"] = str(store.root.parent)
    environment.pop("CODE_VISUALIZER_COMPUTATION_INPUT_RESOURCES", None)
    if store.inputs is not None:
        environment["CODE_VISUALIZER_COMPUTATION_INPUT_RESOURCES"] = str(store.inputs.root.parent)
    return environment


def _prepared(
    service: ComputationService,
    job: ComputationJob,
    store: ResourceStore,
    profile: WorkerProfile,
    reference: ResourceReference,
) -> WorkerPrepared:
    backend = job.registry.backend(job.request.backend_id, job.request.backend_version)
    if backend is None:
        raise TransformationError(
            "COMPUTATION_BACKEND_MISSING", "Requested backend implementation is unavailable"
        )
    worker = _launch(
        service,
        job,
        store,
        profile,
        WorkerPreparationRequest(job.view.session.id, reference, job.request, backend.definition),
    )
    resources = _Resources(store, job)
    prepared: WorkerPrepared | None = None
    try:
        while True:
            try:
                event = worker_event_from_bytes(worker.receive())
            except WorkerExited as exc:
                if exc.return_code == 0 and prepared is not None and resources.receiver is None:
                    return prepared
                raise
            if event.session_id != job.view.session.id:
                raise ValueError("Preparation event belongs to another attempt")
            if prepared is not None:
                raise ValueError("A prepared result must be followed by normal worker exit")
            if isinstance(event, WorkerResourceEvent):
                resources.accept(event)
            elif isinstance(event, WorkerPrepared) and prepared is None:
                expected = replace(
                    job.request,
                    configuration=tuple(
                        sorted(job.request.configuration, key=lambda item: item.name)
                    ),
                    resources=event.plan.request.resources,
                    inputs=tuple(sorted(job.request.inputs, key=lambda item: item.name)),
                    outputs=tuple(sorted(job.request.outputs, key=lambda item: item.name)),
                )
                if event.plan.request != expected or not set(job.request.resources) <= set(
                    event.plan.request.resources
                ):
                    raise ValueError("Prepared plan differs from the submitted computation request")
                if event.plan.input_digest != computation_input_digest(
                    job.project, event.plan.request
                ):
                    raise ValueError("Prepared plan differs from its exact source/input digest")
                resources.complete(
                    (event.plan.model,)
                    + ((event.execution_artifact,) if event.execution_artifact is not None else ())
                )
                prepared = event
                worker.expect_exit()
            elif isinstance(event, WorkerFailure):
                raise TransformationError(event.diagnostic.code, event.diagnostic.message)
            else:
                raise ValueError("Unexpected or repeated preparation result")
    finally:
        try:
            resources.close()
        finally:
            _close_worker(service, job, worker)


def _execution(
    service: ComputationService, job: ComputationJob, store: ResourceStore, profile: WorkerProfile
) -> ComputationEvidence:
    from code_visualizer.application.computation import _evidence

    assert job.snapshot is not None and job.plan is not None and job.execution is not None
    snapshot, plan, monitor = job.snapshot, job.plan, job.execution
    worker = _launch(
        service,
        job,
        store,
        profile,
        WorkerExecutionRequest(job.view.session.id, plan, monitor.backend.definition),
    )
    admitted_store = job.resource_store or store
    resources = _Resources(admitted_store, job)
    proposal: ComputationEvidence | None = None
    verified = False
    published_ids: set[str] = set()
    try:
        while True:
            try:
                event = worker_event_from_bytes(worker.receive())
            except WorkerExited as exc:
                if (
                    exc.return_code == 0
                    and proposal is not None
                    and verified
                    and resources.receiver is None
                ):
                    return proposal
                raise
            if event.session_id != job.view.session.id:
                raise ValueError("Execution event belongs to another attempt")
            if verified:
                raise ValueError("A verified result must be followed by normal worker exit")
            if proposal is not None and not isinstance(
                event, WorkerCompletionVerified | WorkerFailure
            ):
                raise ValueError("Evidence proposal must be followed by verification or failure")
            if isinstance(event, WorkerResourceEvent):
                resources.accept(event)
            elif isinstance(event, WorkerFailure):
                raise TransformationError(event.diagnostic.code, event.diagnostic.message)
            elif isinstance(event, ProgressEvent | ObservationEvent | PreviewEvent):
                monitor.accept(event)
                if isinstance(event, ObservationEvent):
                    check_value_contracts(event.observation.value, job.registry)
                    references = resource_references(event.observation.value)
                    _check_resources(references, admitted_store, job)
                    resources.claim(references)
                now = time.monotonic()
                if not isinstance(event, ProgressEvent) or now - job.last_progress_time >= 0.04:
                    service.publish(job, event)
                    # Preview/observation traffic must not indefinitely postpone
                    # a following progress update from this same attempt.
                    if isinstance(event, ProgressEvent):
                        job.last_progress_time = now
            elif isinstance(event, WorkerPublicationOffer):
                if not monitor.backend.definition.capabilities.publications:
                    raise ValueError("Backend did not declare publication capability")
                resources.claim_transferred((event.artifact.resource,))
                descriptor = admitted_store.describe(event.artifact.resource)
                path = admitted_store.verified_path(event.artifact.resource)
                output = ProducedResource(
                    event.artifact.id,
                    None,
                    descriptor.media_type,
                    event.artifact.semantic_ids,
                    event.artifact.label,
                    descriptor.tensor,
                    descriptor.logical_type,
                    file=ResourceFile(path, descriptor.byte_size, descriptor.content_hash),
                )
                monitor.accept(ProducedResourceEvent(event.session_id, event.sequence, output))
                receipt = seal_admitted_publication(
                    snapshot,
                    event.session_id,
                    event.sequence,
                    event.artifact,
                    plan.model,
                    admitted_store,
                    job.evidence_store,
                    job.registry,
                    budget=job.publication_budget,
                )
                monitor.acknowledge_publication(receipt)
                published_ids.add(event.artifact.id)
                service.publish(job, receipt)
                worker.send(worker_control_to_bytes(receipt))
            elif isinstance(event, WorkerEvidenceProposal) and proposal is None:
                if resources.receiver is not None:
                    raise ValueError("Evidence cannot precede completion of its resource transfer")
                if event.evidence.provenance != computation_provenance(snapshot, plan.model):
                    raise ValueError("Worker evidence does not match its frozen input provenance")
                resources.complete(
                    resource_references((event.evidence.observations, event.evidence.artifacts))
                )
                service.begin_finalization(job, event.evidence.outcome)
                if job.cancelled.is_set() and monitor.session.cancellation_supported:
                    monitor.cancel(CancelRequest(job.view.session.id))
                result = monitor.finish(
                    BackendResult(
                        event.evidence.outcome,
                        () if monitor.backend.stream is not None else event.evidence.observations,
                        tuple(
                            artifact
                            for artifact in event.evidence.artifacts
                            if artifact.id not in published_ids
                        ),
                        event.evidence.diagnostics,
                    )
                )
                if event.evidence.outcome is ComputationOutcome.CANCELLED:
                    worker.acknowledge_cancellation()
                expected = _evidence(
                    snapshot, result, admitted_store, plan.model, registry=job.registry
                )
                if expected != event.evidence:
                    raise ValueError(
                        "Worker terminal differs from the admitted observation/publication stream"
                    )
                for observation in expected.observations:
                    check_value_contracts(observation.value, job.registry)
                _check_resources(
                    resource_references((expected.observations, expected.artifacts)),
                    admitted_store,
                    job,
                )
                validate_portable_evidence(expected)
                proposal = expected
                worker.send(
                    worker_control_to_bytes(WorkerTerminalSecured(job.view.session.id, expected.id))
                )
                worker.expect_exit()
            elif (
                isinstance(event, WorkerCompletionVerified)
                and proposal is not None
                and not verified
            ):
                verified = True
                monitor.verify_completion()
            else:
                raise ValueError("Unexpected worker event or repeated terminal result")
    finally:
        try:
            resources.close()
        finally:
            _close_worker(service, job, worker)


def _close_worker(service: ComputationService, job: ComputationJob, worker: WorkerProcess) -> None:
    """Reap the captured owner before reporting whether cleanup required a kill."""
    try:
        worker.close()
    finally:
        if worker.forced_termination:
            service.changed(job, forced_termination=True)
        if job.worker is worker:
            job.worker = None


def _failure(service: ComputationService, job: ComputationJob, error: Exception) -> None:
    from code_visualizer.application.computation import _evidence

    worker = job.worker
    if worker is not None:
        _close_worker(service, job, worker)
    cancelled = job.cancelled.is_set()
    diagnostic = EvidenceDiagnostic(
        "COMPUTATION_FORCE_TERMINATED"
        if cancelled and job.view.forced_termination
        else getattr(error, "code", "COMPUTATION_WORKER_FAILED"),
        str(error)[:4096],
    )
    service.changed(
        job,
        phase="cancelled" if cancelled else "failed",
        diagnostic=diagnostic.message,
        forced_termination=job.view.forced_termination,
        session=replace(
            job.view.session,
            status=ComputationStatus.CANCELLED if cancelled else ComputationStatus.FAILED,
        ),
    )
    if job.snapshot is not None and job.plan is not None:
        evidence = _evidence(
            job.snapshot,
            BackendResult(
                ComputationOutcome.CANCELLED if cancelled else ComputationOutcome.FAILED,
                artifacts=tuple(p.artifact for p in job.publications.values()),
                diagnostics=(diagnostic,),
            ),
            job.resource_store,
            job.plan.model,
            registry=job.registry,
        )
        if job.evidence_store is not None:
            job.evidence_store.put(evidence)
        service.publish(job, evidence)
    else:
        job.attachment.runtime.fail_computation(
            job.view.session.id, diagnostic.message, cancelled=cancelled
        )
        with job.condition:
            job.error = error
            job.done.set()
            job.condition.notify_all()


def run_attempt(service: ComputationService, job: ComputationJob) -> None:
    from code_visualizer.application.computation import _evidence
    from code_visualizer.persistence.python_execution import load_python_execution_artifact

    temporary: TemporaryDirectory[str] | None = None
    try:
        service.changed(job, phase="preparing")
        try:
            profile = profile_for_backend(
                service.profiles if service.profiles is not None else default_profiles(),
                job.request.backend_id,
                job.request.backend_version,
            )
        except ValueError as exc:
            raise TransformationError("COMPUTATION_WORKER_UNAVAILABLE", str(exc)) from exc
        temporary = TemporaryDirectory(prefix="code-visualizer-computation-")
        store = ResourceStore(Path(temporary.name), inputs=job.resource_store)
        # Serialization and hashing happen on this orchestration thread; all
        # registered validators/transforms/solvers execute in the supervised child.
        source = store.put(
            b"".join(project_data_chunks(job.project)),
            "application/vnd.code-visualizer.project+json;version=11",
        )
        service.changed(job, source_digest=source.content_hash)
        job.registry = resolve_domain_languages(job.project, job.registry)
        prepared = _prepared(
            service, job, store, profile, ResourceReference(source.id, source.content_hash)
        )
        # Source snapshots and executable-file transports belong to this attempt.
        # Only its checked scientific terminal belongs in the durable resource closure.
        snapshot = decode_terminal(prepared.plan, store, job.registry)
        if job.resource_store is not None:
            job.resource_store.import_reference(store, prepared.plan.model)
        job.plan = prepared.plan
        job.snapshot = snapshot
        backend = job.registry.backend(job.request.backend_id, job.request.backend_version)
        assert backend is not None
        job.execution = BackendExecution(
            job.view.session.id, backend, job.snapshot, prepared.plan.model
        )
        job.execution.session = replace(job.execution.session, status=ComputationStatus.RUNNING)
        job.attachment.runtime.register_origins(job.view.session.id, job.snapshot.origins)
        service.changed(
            job,
            phase="running",
            input_digest=job.snapshot.input_digest,
            session=job.execution.session,
        )
        if job.cancelled.is_set():
            raise TransformationError(
                "COMPUTATION_CANCELLED", "Computation was cancelled during preparation"
            )
        if prepared.execution_artifact is not None:
            artifact = load_python_execution_artifact(prepared.execution_artifact, store)
            from code_visualizer.execution.python_artifacts import PythonArtifactContext

            sequence = 0

            def publish_python(output: EvidenceArtifact) -> PublicationEvent:
                nonlocal sequence
                if job.cancelled.is_set():
                    raise ValueError("COMPUTATION_CANCELLED: publication was cancelled")
                if job.resource_store is None or job.evidence_store is None:
                    raise ValueError("COMPUTATION_PUBLICATION_STORE: durable stores are required")
                descriptor = store.describe(output.resource)
                check_resource_descriptor(descriptor, job.registry)
                admitted = job.resource_store.import_reference(store, output.resource)
                monitor = job.execution
                assert monitor is not None and job.snapshot is not None
                offered = ProducedResource(
                    output.id,
                    media_type=admitted.media_type,
                    semantic_ids=output.semantic_ids,
                    label=output.label,
                    tensor=admitted.tensor,
                    logical_type=admitted.logical_type,
                    file=ResourceFile(
                        job.resource_store.verified_path(admitted.reference),
                        admitted.byte_size,
                        admitted.content_hash,
                    ),
                )
                monitor.accept(ProducedResourceEvent(job.view.session.id, sequence, offered))
                receipt = seal_admitted_publication(
                    job.snapshot,
                    job.view.session.id,
                    sequence,
                    output,
                    prepared.plan.model,
                    job.resource_store,
                    job.evidence_store,
                    job.registry,
                    budget=job.publication_budget,
                )
                monitor.acknowledge_publication(receipt)
                sequence += 1
                service.publish(job, receipt)
                return receipt

            context = (
                PythonArtifactContext(job.snapshot, artifact.generated, store, publish_python)
                if backend.definition.version == "2"
                else None
            )
            managed = managed_driver(
                job.view.session.id,
                backend.definition,
                job.snapshot,
                artifact.generated,
                binding_specs=artifact.binding_specs,
                computation=context,
            )
            job.managed = managed
            try:
                if job.cancelled.is_set():
                    managed.cancel(CancelRequest(job.view.session.id))
                result = managed.advance()
                if context is not None:
                    if context.error is not None:
                        raise TransformationError(
                            "COMPUTATION_PUBLICATION_FAILED", str(context.error)
                        )
                    for observation in result.observations:
                        job.execution.accept(
                            ObservationEvent(
                                job.view.session.id, replace(observation, sequence=sequence)
                            )
                        )
                        sequence += 1
                    if job.cancelled.is_set():
                        job.execution.cancel(CancelRequest(job.view.session.id))
                        result = replace(result, outcome=ComputationOutcome.CANCELLED)
                    result = job.execution.finish(replace(result, observations=()))
                    job.execution.verify_completion()
                service.begin_finalization(job, result.outcome)
                evidence = _evidence(
                    job.snapshot,
                    result,
                    job.resource_store or store,
                    prepared.plan.model,
                    registry=job.registry,
                )
                validate_portable_evidence(evidence)
            finally:
                managed.close()
                if managed.forced_termination:
                    service.changed(job, forced_termination=True)
                job.managed = None
        else:
            evidence = _execution(service, job, store, profile)
        if job.evidence_store is not None:
            job.evidence_store.put(evidence)
        service.publish(job, evidence)
    except Exception as exc:
        try:
            _failure(service, job, exc)
        finally:
            if not job.done.is_set():
                with job.condition:
                    job.error = exc
                    job.done.set()
                    job.condition.notify_all()
    finally:
        worker = job.worker
        if worker is not None:
            _close_worker(service, job, worker)
        # Without an explicit durable store, evidence may be inspected for this
        # attempt but no publication is admitted; produced resource lifetime is
        # retained by the host, not the Python child or editor widget.
        if temporary is not None:
            if job.resource_store is None:
                # Host retention is completed by the service's close boundary.
                job.temporary_store = temporary
            else:
                temporary.cleanup()
