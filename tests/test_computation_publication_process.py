"""Sealed typed outputs outlive producers and remain inputs to the same lifecycle."""

from contextlib import contextmanager
from hashlib import sha256

import pytest
from fixtures.computation_worker_fixture import BACKEND_ID, fixture_registry, worker_profile

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.computation import execute_computation, start_computation
from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.project_factory import create_default_project
from code_visualizer.domain.computation import (
    CancelRequest,
    ComputationParameter,
    ComputationRequest,
)
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.generation.transformation import TransformationError
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.publications import publication_to_data
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.serialization import project_to_data


@contextmanager
def _host(path, *, profiles=None):
    service = ComputationService(profiles=(worker_profile(),) if profiles is None else profiles)
    kernel = ProjectKernel(
        ProjectAuthority(create_default_project()),
        extensions=fixture_registry(),
        computations=service,
        resource_store=ResourceStore(path),
        evidence_store=EvidenceStore(path),
    )
    try:
        yield service, kernel
    finally:
        kernel.close()
        service.close()


def _request(kernel, mode, **configuration):
    project = kernel.authority.snapshot()
    return ComputationRequest(
        project.id,
        project.revision,
        BACKEND_ID,
        "1",
        configuration=tuple(
            ComputationParameter(name, value)
            for name, value in {"mode": mode, **configuration}.items()
        ),
    )


def _publication(service, session):
    job = service.job(session.id)
    with job.condition:
        assert job.condition.wait_for(lambda: bool(job.publications) or job.done.is_set(), 40)
        assert job.publications, job.error or job.view.diagnostic
        return next(iter(job.publications.values()))


def test_consumer_uses_sealed_output_while_producer_is_active_and_after_cancel(tmp_path):
    with _host(tmp_path) as (service, kernel):
        before = project_to_data(kernel.authority.snapshot())
        producer = start_computation(kernel, _request(kernel, "publish_hold"))
        publication = _publication(service, producer)
        resource = publication.artifact.resource
        assert kernel.resource_store is not None and kernel.evidence_store is not None
        assert not service.job(producer.id).done.is_set()
        assert kernel.evidence_store.get_publication(publication.id) == publication
        descriptor = kernel.resource_store.describe(resource)
        assert descriptor.logical_type == ResourceLogicalTypeReference(
            "org.codevisualizer.test:integer-series", "1"
        )
        assert kernel.resource_store.read(resource) == b"10,20,30"
        assert resource.content_hash == sha256(b"10,20,30").hexdigest()
        consumer = execute_computation(kernel, _request(kernel, "consume", input=resource))
        assert consumer.outcome is ComputationOutcome.SUCCEEDED
        assert next(item.value for item in consumer.observations if item.id == "sum") == 60
        assert resource in consumer.provenance.resources
        assert not service.job(producer.id).done.is_set()
        service.cancel(CancelRequest(producer.id))
        result = service.wait(producer.id)
        assert result.outcome is ComputationOutcome.CANCELLED
        assert not service.job(producer.id).view.forced_termination
        assert publication.artifact in result.artifacts
        assert kernel.evidence_store.get_publication(publication.id) == publication
        assert kernel.resource_store.read(resource) == b"10,20,30"
        assert project_to_data(kernel.authority.snapshot()) == before


def test_new_host_consumes_typed_publication_after_producer_process_and_host_exit(tmp_path):
    with _host(tmp_path) as (service, kernel):
        producer = start_computation(kernel, _request(kernel, "publish"))
        result = service.wait(producer.id)
        assert result.outcome is ComputationOutcome.SUCCEEDED
        publication = _publication(service, producer)
    with _host(tmp_path) as (_service, kernel):
        assert kernel.evidence_store is not None
        restored = kernel.evidence_store.get_publication(publication.id)
        assert restored == publication
        assert publication.id in kernel.capabilities.invoke("analysis.computation_publications", {})
        assert kernel.capabilities.invoke(
            "analysis.computation_publications", {"publication_id": publication.id}
        ) == publication_to_data(publication)
        assert kernel.capabilities.invoke("analysis.computation_attempts", {}) == ()
        result = execute_computation(
            kernel, _request(kernel, "consume", input=restored.artifact.resource)
        )
        assert result.outcome is ComputationOutcome.SUCCEEDED
        assert next(item.value for item in result.observations if item.id == "sum") == 60
        assert kernel.authority.snapshot().revision == 0


def test_native_crash_does_not_terminate_other_producer_or_retract_its_publication(tmp_path):
    with _host(tmp_path) as (service, kernel):
        producer = start_computation(kernel, _request(kernel, "publish_hold"))
        publication = _publication(service, producer)
        crash = start_computation(kernel, _request(kernel, "crash"))
        result = service.wait(crash.id)
        assert result.outcome is ComputationOutcome.FAILED
        assert not service.job(crash.id).view.forced_termination
        assert not service.job(producer.id).done.is_set()
        assert kernel.resource_store is not None
        assert kernel.resource_store.read(publication.artifact.resource) == b"10,20,30"
        consumer = execute_computation(
            kernel, _request(kernel, "consume", input=publication.artifact.resource)
        )
        assert consumer.outcome is ComputationOutcome.SUCCEEDED
        service.cancel(CancelRequest(producer.id))
        assert service.wait(producer.id).outcome is ComputationOutcome.CANCELLED


def test_uncooperative_cpu_worker_is_force_terminated_without_successful_evidence(tmp_path):
    with _host(tmp_path) as (service, kernel):
        session = start_computation(kernel, _request(kernel, "cpu"))
        job = service.job(session.id)
        with job.condition:
            assert job.condition.wait_for(
                lambda: job.view.progress is not None or job.done.is_set(), 40
            )
            assert job.view.progress is not None, job.error
        service.cancel(CancelRequest(session.id))
        result = service.wait(session.id)
        assert result.outcome is ComputationOutcome.CANCELLED
        assert job.view.forced_termination
        assert any(item.code == "COMPUTATION_FORCE_TERMINATED" for item in result.diagnostics)


def test_producer_crash_after_publication_ack_preserves_consumable_receipt(tmp_path):
    with _host(tmp_path) as (service, kernel):
        session = start_computation(kernel, _request(kernel, "publish_crash"))
        publication = _publication(service, session)
        result = service.wait(session.id)
        assert result.outcome is ComputationOutcome.FAILED
        assert not service.job(session.id).view.forced_termination
        assert kernel.evidence_store is not None and kernel.resource_store is not None
        assert kernel.evidence_store.get_publication(publication.id) == publication
        assert kernel.resource_store.read(publication.artifact.resource) == b"10,20,30"
        consumer = execute_computation(
            kernel, _request(kernel, "consume", input=publication.artifact.resource)
        )
        assert consumer.outcome is ComputationOutcome.SUCCEEDED
        assert next(item.value for item in consumer.observations if item.id == "sum") == 60
        assert publication.artifact.resource in consumer.provenance.resources


def test_unregistered_worker_composition_never_falls_back_to_local_callbacks(tmp_path):
    with _host(tmp_path, profiles=()) as (service, kernel):
        session = start_computation(kernel, _request(kernel, "cpu"))
        with pytest.raises(TransformationError) as caught:
            service.wait(session.id)
        assert caught.value.code == "COMPUTATION_WORKER_UNAVAILABLE"
        assert service.job(session.id).view.worker_pid is None
        assert kernel.authority.snapshot().revision == 0
