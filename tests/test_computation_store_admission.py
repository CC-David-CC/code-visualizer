"""Every submitted strategy rejects durable receipts backed only by temporary bytes."""

import pytest

from code_visualizer.application import computation_jobs, computation_service
from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.computation import execute_computation, start_computation
from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.project_factory import create_default_project
from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.execution.computation_driver import InProcessDriver
from code_visualizer.generation.transformation import TransformationError
from code_visualizer.persistence.evidence_store import EvidenceStore


@pytest.mark.parametrize("strategy", ("production", "in_process"))
@pytest.mark.parametrize("submit", (start_computation, execute_computation))
def test_durable_evidence_without_resources_is_rejected_before_any_attempt_or_worker(
    tmp_path, monkeypatch, strategy, submit
):
    host = ComputationService(in_process=InProcessDriver() if strategy == "in_process" else None)
    project = create_default_project()
    evidence = EvidenceStore(tmp_path)
    kernel = ProjectKernel(ProjectAuthority(project), computations=host, evidence_store=evidence)

    def unexpected_work(*_args, **_kwargs):
        raise AssertionError("Invalid storage must be rejected before allocating or preparing work")

    # Even transient session allocation or synchronous preparation is too early.
    monkeypatch.setattr(computation_service, "new_id", unexpected_work)
    monkeypatch.setattr(computation_jobs, "prepare_in_process", unexpected_work)
    monkeypatch.setattr(host._pool, "submit", unexpected_work)
    try:
        with pytest.raises(TransformationError) as caught:
            submit(
                kernel,
                ComputationRequest(project.id, project.revision, "code_visualizer.python", "1"),
            )
        assert caught.value.code == "COMPUTATION_RESOURCE_STORE"
        assert str(caught.value) == (
            "Durable evidence requires a resource store for its reproducible terminal input"
        )
        assert host.attempts() == ()
        assert kernel.runtime.sessions() == () and kernel.runtime.active is None
        assert kernel.resource_store is None
        assert evidence.identities() == () and evidence.publication_identities() == ()
        assert tuple(tmp_path.rglob("*")) == ()
        assert kernel.authority.snapshot() == project
    finally:
        kernel.close()
        host.close()


def test_production_without_either_store_remains_explicitly_ephemeral():
    project = create_default_project()
    kernel = ProjectKernel(ProjectAuthority(project))
    try:
        result = execute_computation(
            kernel,
            ComputationRequest(project.id, project.revision, "code_visualizer.python", "1"),
        )
        assert result.outcome is ComputationOutcome.SUCCEEDED, result.diagnostics
        assert result.provenance.terminal_resource is not None
        assert kernel.resource_store is None and kernel.evidence_store is None
        assert len(kernel.computations.attempts()) == 1
        assert kernel.authority.snapshot() == project
    finally:
        kernel.close()
