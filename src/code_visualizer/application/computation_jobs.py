"""Drivers and admission for host-owned attempts, independent of editor lifetime."""

from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING

from code_visualizer.application.computation_publications import seal_publication
from code_visualizer.application.resource_admission import validate_value_contracts
from code_visualizer.domain.computation import ComputationPlan
from code_visualizer.domain.evidence import ComputationEvidence, ObservationEvent
from code_visualizer.execution.backends import (
    BackendResult,
    ProducedResourceEvent,
    resource_references,
)
from code_visualizer.extensions.languages import resolve_domain_languages
from code_visualizer.generation.computation import prepare_computation
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.serialization import project_to_data

if TYPE_CHECKING:
    from code_visualizer.application.computation_service import (
        ComputationJob,
        ComputationService,
        ComputationUpdate,
    )


def prepare_in_process(service: ComputationService, job: ComputationJob) -> None:
    from code_visualizer.application.computation import (
        _publish_input,
        _resolve_resources,
        _validate_input_values,
    )

    registry = resolve_domain_languages(job.project, job.registry)
    snapshot = _resolve_resources(
        job.resource_store, prepare_computation(job.project, job.request, registry), registry
    )
    _validate_input_values(snapshot, registry)
    terminal = _publish_input(snapshot, job.resource_store, job.evidence_store, registry)
    backend = registry.backend(job.request.backend_id, job.request.backend_version)
    assert backend is not None and service.in_process is not None
    job.registry, job.snapshot = registry, snapshot
    job.execution = service.in_process.start(job.view.session.id, backend, snapshot, terminal)
    if terminal is not None:
        job.plan = ComputationPlan(
            snapshot.request,
            snapshot.representation,
            terminal,
            snapshot.transformations,
            snapshot.origins,
            snapshot.input_digest,
        )
    service.changed(
        job,
        session=job.execution.session,
        source_digest=sha256(canonical_data_bytes(project_to_data(job.project))).hexdigest(),
        input_digest=snapshot.input_digest,
    )
    job.attachment.runtime.bind_computation(job.execution)


def advance_in_process(service: ComputationService, job: ComputationJob) -> ComputationUpdate:
    from code_visualizer.application.computation import (
        _admit_evidence,
        _advance_backend,
        _validate_resource_values,
    )

    execution = job.execution
    assert execution is not None
    try:
        update = _advance_backend(execution)
        service.changed(job, session=execution.session)
        if isinstance(update, BackendResult):
            admitted: ComputationUpdate = _admit_evidence(
                execution.snapshot,
                update,
                job.resource_store,
                job.evidence_store,
                execution.terminal_resource,
                job.registry,
                execution,
            )
        elif isinstance(update, ProducedResourceEvent):
            admitted = seal_publication(
                execution.snapshot,
                update,
                execution.terminal_resource,
                job.resource_store,
                job.evidence_store,
                job.registry,
                budget=job.publication_budget,
            )
            execution.acknowledge_publication(admitted)
        else:
            if isinstance(update, ObservationEvent):
                validate_value_contracts(update.observation.value, job.registry)
                _validate_resource_values(
                    resource_references(update.observation.value), job.resource_store, job.registry
                )
            admitted = update
        service.publish(job, admitted)
        if isinstance(admitted, ComputationEvidence):
            job.attachment.runtime.release_computation(execution.session.id)
        return admitted
    except Exception as exc:
        job.attachment.runtime.abandon_computation(execution.session.id)
        job.error = exc
        job.done.set()
        with job.condition:
            job.condition.notify_all()
        raise


def run_process_job(service: ComputationService, job: ComputationJob) -> None:
    from code_visualizer.application.computation_process import run_attempt

    run_attempt(service, job)
