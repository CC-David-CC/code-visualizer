"""Static composition executes through the host's actual preparation/worker path."""

from fixtures.computation_worker_fixture import BACKEND_ID, fixture_registry, worker_profile

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.computation import execute_computation
from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.project_factory import create_default_project
from code_visualizer.domain.computation import ComputationParameter, ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore


def test_static_backend_runs_after_supervised_preparation(tmp_path):
    service = ComputationService(profiles=(worker_profile(),))
    project = create_default_project()
    kernel = ProjectKernel(
        ProjectAuthority(project),
        extensions=fixture_registry(),
        computations=service,
        resource_store=ResourceStore(tmp_path),
        evidence_store=EvidenceStore(tmp_path),
    )
    try:
        evidence = execute_computation(
            kernel,
            ComputationRequest(
                project.id,
                project.revision,
                BACKEND_ID,
                "1",
                configuration=(
                    ComputationParameter("mode", "progress"),
                    ComputationParameter("count", 3),
                ),
            ),
        )
        assert evidence.outcome is ComputationOutcome.SUCCEEDED
        assert evidence.provenance.backend_id == BACKEND_ID
        assert evidence.provenance.terminal_resource is not None
        assert kernel.authority.snapshot() == project
    finally:
        kernel.close()
        service.close()
