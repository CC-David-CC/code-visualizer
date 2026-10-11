"""The normal host executes canonical diffusion and retains independently readable data."""

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.computation import (
    execute_computation,
    export_computation_plan,
    run_computation_plan,
)
from code_visualizer.application.field_examples import diffusion_project
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.extensions.diffusion.domain import BACKEND_ID
from code_visualizer.extensions.fields.history import FieldHistory
from code_visualizer.extensions.fields.records import SERIES_TYPE
from code_visualizer.persistence.computation_resources import resolve_computation_resource
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore


def test_diffusion_ordinary_worker_and_portable_terminal(tmp_path):
    project = diffusion_project(nodes=33, steps=512, sample_every=16, checkpoint_every=256)
    kernel = ProjectKernel(
        ProjectAuthority(project),
        resource_store=ResourceStore(tmp_path),
        evidence_store=EvidenceStore(tmp_path),
    )
    try:
        request = ComputationRequest(
            project.id, project.revision, BACKEND_ID, "1", model_id="diffusion:experiment"
        )
        evidence = execute_computation(kernel, request)
        assert evidence.outcome is ComputationOutcome.SUCCEEDED, evidence.diagnostics
        roots = [
            item.resource
            for item in evidence.artifacts
            if kernel.resource_store.describe(item.resource).logical_type == SERIES_TYPE
        ]
        history = FieldHistory(
            roots[-1],
            lambda ref: resolve_computation_resource(kernel.resource_store, ref, file_backed=True),
        )
        final = history.slice(history.sample_count - 1)
        assert abs(final.values[16] - 3.7270783885343794) < 0.003
        assert final.position.step == 512 and final.position.time.magnitude == 1.0
        assert history.sample_count == 33
        history.close()
        plan = export_computation_plan(kernel, request)
        replay = run_computation_plan(
            plan, kernel.extensions, kernel.resource_store, kernel.evidence_store
        )
        assert replay.outcome is ComputationOutcome.SUCCEEDED, replay.diagnostics
        assert replay.artifacts == evidence.artifacts
        assert replay.observations == evidence.observations
    finally:
        kernel.close()
