"""Saved authored input, real ordinary workers and portable retained continuation."""

from contextlib import contextmanager

from fixtures.adaptive_reference import weighted_error

from code_visualizer.application.adaptive_examples import adaptive_diffusion_project
from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.computation import (
    execute_computation,
    export_computation_plan,
    run_computation_plan,
)
from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.domain.computation import ComputationParameter, ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.extensions.adaptive_diffusion.checkpoint import CHECKPOINT_TYPE
from code_visualizer.extensions.adaptive_diffusion.domain import BACKEND_ID
from code_visualizer.extensions.adaptive_fields.history import AdaptiveHistory
from code_visualizer.extensions.adaptive_fields.records import HISTORY_TYPE
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.persistence.computation_resources import resolve_computation_resource
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.serialization import normalized_project_json


@contextmanager
def host(project, path):
    service = ComputationService()
    kernel = ProjectKernel(
        ProjectAuthority(project),
        computations=service,
        resource_store=ResourceStore(path),
        evidence_store=EvidenceStore(path),
    )
    try:
        yield kernel
    finally:
        kernel.close()
        service.close()


def request(project, checkpoint=None):
    return ComputationRequest(
        project.id,
        project.revision,
        BACKEND_ID,
        "1",
        model_id="adaptive:experiment",
        configuration=(ComputationParameter("checkpoint", checkpoint),) if checkpoint else (),
    )


def last_resource(evidence, store, logical):
    return [
        artifact.resource
        for artifact in evidence.artifacts
        if store.describe(artifact.resource).logical_type == logical
    ][-1]


def reader(root, store):
    return AdaptiveHistory(
        root, lambda ref: resolve_computation_resource(store, ref, file_backed=True)
    )


def test_saved_definition_executes_in_existing_worker_and_portable_terminal(tmp_path, monkeypatch):
    import code_visualizer.application.adaptive_examples as examples

    project = adaptive_diffusion_project()
    saved = tmp_path / "source.json"
    saved.write_text(normalized_project_json(project), encoding="utf-8")
    project = project_from_json(saved.read_text(encoding="utf-8"))

    def forbidden():
        raise AssertionError("Execution cannot reconstruct meaning from an example factory")

    monkeypatch.setattr(examples, "adaptive_diffusion_project", forbidden)
    with host(project, tmp_path / "producer") as kernel:
        evidence = execute_computation(kernel, request(project))
        assert evidence.outcome is ComputationOutcome.SUCCEEDED, evidence.diagnostics
        root = last_resource(evidence, kernel.resource_store, HISTORY_TYPE)
        history = reader(root, kernel.resource_store)
        assert history.sample_count == 201 and len(history.series.epochs) > 1
        for sample in range(history.sample_count):
            value = history.slice(sample)
            assert (
                weighted_error(
                    value.mesh.faces, value.values[:, 0], float(value.position.time.magnitude)
                )
                <= 0.005
            )
        assert all("adaptive:field" in item.semantic_ids for item in evidence.observations)
        plan = export_computation_plan(kernel, request(project))
        replay = run_computation_plan(
            plan, kernel.extensions, kernel.resource_store, kernel.evidence_store
        )
        assert replay.outcome is ComputationOutcome.SUCCEEDED, replay.diagnostics
        assert replay.artifacts == evidence.artifacts
        assert replay.observations == evidence.observations
        checkpoint = next(
            artifact.resource
            for artifact in evidence.artifacts
            if kernel.resource_store.describe(artifact.resource).logical_type == CHECKPOINT_TYPE
            and artifact.id != "checkpoint:0"
        )
        destination = ResourceStore(tmp_path / "consumer")
        for ref in builtin_registry().resource_closure((checkpoint,), kernel.resource_store):
            destination.import_reference(kernel.resource_store, ref)
        history.close()
    # The producing Python worker and host have exited. Only the saved source and
    # typed, content-addressed closure are supplied to a fresh host.
    with host(project, tmp_path / "consumer") as fresh:
        resumed = execute_computation(fresh, request(project, checkpoint))
        assert resumed.outcome is ComputationOutcome.SUCCEEDED, resumed.diagnostics
        assert last_resource(resumed, fresh.resource_store, HISTORY_TYPE) == root
