"""Real ordinary worker, saved source, complete resources and exact fresh continuation."""

from contextlib import contextmanager

import numpy as np
from fixtures.gas_project import short_project, store
from test_hybrid_gas_particle import WINDOWS

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
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.hybrid_gas.domain import BACKEND_ID
from code_visualizer.extensions.hybrid_gas.history import GasHistory
from code_visualizer.extensions.hybrid_gas.records import (
    CHECKPOINT_TYPE,
    HISTORY_TYPE,
    STATISTICS_TYPE,
)
from code_visualizer.persistence.computation_resources import resolve_computation_resource
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore


@contextmanager
def host(project, root, *, inputs=True):
    service = ComputationService()
    kernel = ProjectKernel(
        ProjectAuthority(project),
        computations=service,
        resource_store=store(root) if inputs else ResourceStore(root),
        evidence_store=EvidenceStore(root),
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
        "gas:experiment",
        configuration=(ComputationParameter("checkpoint", checkpoint),) if checkpoint else (),
    )


def resources(evidence, store, logical_type):
    return tuple(
        artifact.resource
        for artifact in evidence.artifacts
        if store.describe(artifact.resource).logical_type == logical_type
    )


def reader(root, resource_store):
    return GasHistory(
        root, lambda r: resolve_computation_resource(resource_store, r, file_backed=True)
    )


@WINDOWS
def test_saved_source_real_worker_portable_replay_and_fresh_checkpoint(tmp_path, monkeypatch):
    import code_visualizer.application.gas_examples as examples

    project = short_project()

    def forbidden(*args, **kwargs):
        raise AssertionError("Execution cannot reconstruct meaning from an example helper")

    monkeypatch.setattr(examples, "hybrid_gas_project", forbidden)
    with host(project, tmp_path / "producer") as kernel:
        evidence = execute_computation(kernel, request(project))
        assert evidence.outcome is ComputationOutcome.SUCCEEDED, evidence.diagnostics
        attempt = kernel.computations.attempts()[-1]
        assert attempt.preview is not None
        assert attempt.progress is not None, "A preview must not starve the following progress"
        assert attempt.progress.completed > 0
        result = resources(evidence, kernel.resource_store, HISTORY_TYPE)[-1]
        history = reader(result, kernel.resource_store)
        assert history.sample_count == 3
        expected = tuple(history.gas_slice(i).conserved.copy() for i in range(3))
        assert all(history.gas_slice(i).particle for i in range(3))
        assert resources(evidence, kernel.resource_store, STATISTICS_TYPE)
        history.close()
        plan = export_computation_plan(kernel, request(project))
        replay = run_computation_plan(
            plan, kernel.extensions, kernel.resource_store, kernel.evidence_store
        )
        assert replay.outcome is ComputationOutcome.SUCCEEDED, replay.diagnostics
        assert replay.artifacts == evidence.artifacts
        assert replay.observations == evidence.observations
        checkpoint = resources(evidence, kernel.resource_store, CHECKPOINT_TYPE)[1]
        destination = ResourceStore(tmp_path / "consumer")
        # Copy both retained state and the actual authored input resource closure.
        roots = (
            checkpoint,
            project.domain_workspace.models[0]
            .node("gas:gas")
            .property("code_visualizer.hybrid_gas:Gas:calibration"),
        )
        for ref in builtin_registry().resource_closure(roots, kernel.resource_store):
            destination.import_reference(kernel.resource_store, ref)
    with host(project, tmp_path / "consumer", inputs=False) as kernel:
        resumed = execute_computation(kernel, request(project, checkpoint))
        assert resumed.outcome is ComputationOutcome.SUCCEEDED, resumed.diagnostics
        final = resources(resumed, kernel.resource_store, HISTORY_TYPE)[-1]
        assert final == result
        history = reader(final, kernel.resource_store)
        for i, values in enumerate(expected):
            np.testing.assert_array_equal(history.gas_slice(i).conserved, values)
        history.close()
