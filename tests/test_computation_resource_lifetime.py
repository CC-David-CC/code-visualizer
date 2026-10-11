"""Operational transport objects never join the durable scientific resource closure."""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fixtures.computation_worker_fixture import BACKEND_ID, fixture_registry, worker_profile

from code_visualizer.application import computation_process, editor_preparation
from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.computation import execute_computation, start_computation
from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.editor_preparation import EditorPreparation
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.project_factory import create_default_project
from code_visualizer.domain.computation import (
    CancelRequest,
    ComputationParameter,
    ComputationRequest,
)
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.execution.backends import resource_references
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore


@pytest.fixture
def attempt_directories(monkeypatch):
    paths = []

    def tracked_temporary_directory(*args, **kwargs):
        directory = TemporaryDirectory(*args, **kwargs)
        paths.append(Path(directory.name))
        return directory

    monkeypatch.setattr(computation_process, "TemporaryDirectory", tracked_temporary_directory)
    monkeypatch.setattr(editor_preparation, "TemporaryDirectory", tracked_temporary_directory)
    return paths


@pytest.mark.parametrize(
    ("mode", "outcome"),
    (
        ("publish", ComputationOutcome.SUCCEEDED),
        ("publish_hold", ComputationOutcome.CANCELLED),
        ("publish_crash", ComputationOutcome.FAILED),
    ),
)
def test_sealed_scientific_closure_survives_attempt_scratch_cleanup(
    tmp_path, attempt_directories, mode, outcome
):
    resources = ResourceStore(tmp_path)
    evidence_store = EvidenceStore(tmp_path)
    service = ComputationService(profiles=(worker_profile(),))
    project = create_default_project()
    kernel = ProjectKernel(
        ProjectAuthority(project),
        extensions=fixture_registry(),
        computations=service,
        resource_store=resources,
        evidence_store=evidence_store,
    )
    try:
        session = start_computation(
            kernel,
            ComputationRequest(
                project.id,
                project.revision,
                BACKEND_ID,
                "1",
                configuration=(ComputationParameter("mode", mode),),
            ),
        )
        job = service.job(session.id)
        with job.condition:
            assert job.condition.wait_for(lambda: job.publications or job.done.is_set(), 40)
            assert job.publications, job.error or job.view.diagnostic
            publication = next(iter(job.publications.values()))
        if mode == "publish_hold":
            assert not job.done.is_set()
            service.cancel(CancelRequest(session.id))
        result = service.wait(session.id)
        assert result.outcome is outcome, result.diagnostics
        assert job.view.source_digest
        assert publication.provenance.terminal_resource is not None
        assert resources.read(publication.artifact.resource) == b"10,20,30"
        assert evidence_store.get_publication(publication.id) == publication
        expected = set(resource_references((publication, result)))
        assert {item.reference for item in resources.descriptors()} == expected
        assert kernel.authority.snapshot() == project
    finally:
        kernel.close()
        service.close()
    assert attempt_directories and all(not path.exists() for path in attempt_directories)
    assert {item.reference for item in ResourceStore(tmp_path).descriptors()} == expected
    assert EvidenceStore(tmp_path).get_publication(publication.id) == publication
    assert EvidenceStore(tmp_path).get(result.id) == result
    for reference in expected:
        assert ResourceStore(tmp_path).read(reference)


def test_managed_python_keeps_source_and_execution_artifact_out_of_durable_resources(
    tmp_path, attempt_directories
):
    resources = ResourceStore(tmp_path)
    unrelated = resources.put(b"authored input retained", "application/octet-stream")
    project = create_default_project()
    kernel = ProjectKernel(
        ProjectAuthority(project),
        resource_store=resources,
        evidence_store=EvidenceStore(tmp_path),
    )
    try:
        result = execute_computation(
            kernel,
            ComputationRequest(project.id, project.revision, "code_visualizer.python", "1"),
        )
        assert result.outcome is ComputationOutcome.SUCCEEDED, result.diagnostics
        assert result.provenance.terminal_resource is not None
        expected = {unrelated.reference, *resource_references(result)}
        assert {item.reference for item in resources.descriptors()} == expected
        assert kernel.authority.snapshot() == project
    finally:
        kernel.close()
    assert attempt_directories and all(not path.exists() for path in attempt_directories)
    assert {item.reference for item in resources.descriptors()} == expected
    assert resources.read(unrelated.reference) == b"authored input retained"
    assert EvidenceStore(tmp_path).get(result.id) == result


def test_editor_preparation_retains_admitted_preview_without_persisting_transport_objects(
    tmp_path, attempt_directories
):
    resources = ResourceStore(tmp_path)
    authored = resources.put(b"authored resource", "application/octet-stream")
    editor = EditorPreparation(resource_store=resources)
    project = create_default_project()
    try:
        identity = editor.submit(project, focus_diagram_id=project.documents[0].id)
        with editor._condition:
            assert editor._condition.wait_for(
                lambda: (
                    editor._view is not None
                    and editor._view.status in {"ready", "failed", "cancelled"}
                ),
                40,
            )
        preview = editor.snapshot()
        assert preview is not None and preview.status == "ready", preview
        assert preview.request_id == identity and preview.generated is not None
        assert preview.source_digest and preview.generated.files
        assert resources.descriptors() == (authored,)
    finally:
        editor.close(wait=True)
    assert attempt_directories and all(not path.exists() for path in attempt_directories)
    assert resources.descriptors() == (authored,)
    assert resources.read(authored.reference) == b"authored resource"
    assert preview.generated.files
