"""Failed real participants, independent computation and complete cancelled prefixes."""

from threading import Event

import numpy as np
import pytest
from test_diffusion_checkpoints import host
from test_electrothermal_checkpoints import last_root, request, rows
from test_electrothermal_window import prepared

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.computation import execute_computation, start_computation
from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.coupled_examples import electrothermal_project
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.physical_examples import spring_equation_project
from code_visualizer.domain.computation import CancelRequest, ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome, PublicationEvent
from code_visualizer.execution.backends import BackendContext
from code_visualizer.execution.worker_process import WorkerProcess
from code_visualizer.extensions.electrothermal.checkpoint import CODEC, CoupledCheckpoint
from code_visualizer.extensions.electrothermal.problem import CouplingError
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.protocol.worker import worker_control_from_bytes


@pytest.mark.parametrize("boundary", ("thermal", "final_electrical"))
def test_repeated_rejection_after_real_calculation_restores_every_accepted_value(
    monkeypatch, boundary
):
    _, _, _, solver = prepared()
    base = solver.initial()
    expected = list(solver.trials(base, BackendContext("reference", Event())))[-1]
    method = "thermal" if boundary == "thermal" else "electrical"
    original = getattr(solver, method)
    for _ in range(3):
        calls = []

        def reject(*args, calls=calls):
            result = original(*args)
            calls.append(result)
            if method == "thermal" or len(calls) == 3:
                raise CouplingError(
                    "PARTICIPANT_TEST_FAULT", "Failure after actual evaluation", solver.problem.id
                )
            return result

        with monkeypatch.context() as patch:
            patch.setattr(solver, method, reject)
            with pytest.raises(CouplingError, match="actual evaluation"):
                list(solver.trials(base, BackendContext("failure", Event())))
        assert calls
        assert base == solver.initial()
        recovered = list(solver.trials(base, BackendContext("retry", Event())))[-1]
        assert recovered == expected
        assert solver.accept(recovered) == solver.accept(expected)


def test_actual_unrelated_equation_job_succeeds_while_coupling_budget_fails(tmp_path):
    service = ComputationService(max_workers=2)
    coupled = electrothermal_project(duration=2, windows=2, max_iterations=1)
    spring = spring_equation_project()
    kernels = [
        ProjectKernel(
            ProjectAuthority(project),
            computations=service,
            resource_store=ResourceStore(tmp_path / name),
            evidence_store=EvidenceStore(tmp_path / name),
        )
        for name, project in (("coupled", coupled), ("independent", spring))
    ]
    try:
        failed = start_computation(kernels[0], request(coupled))
        unrelated = start_computation(
            kernels[1],
            ComputationRequest(
                spring.id,
                spring.revision,
                "foundation.math.linear_equations",
                "1",
                model_id="spring:equations",
            ),
        )
        failure = service.wait(failed.id)
        success = service.wait(unrelated.id)
        assert failure.outcome is ComputationOutcome.FAILED
        assert any(
            item.code == "COUPLING_NOT_CONVERGED" and item.semantic_ids == ("et:policy",)
            for item in failure.diagnostics
        )
        assert success.outcome is ComputationOutcome.SUCCEEDED, success.diagnostics
        assert any(
            item.id == "spring:x:solution" and item.value.magnitude == pytest.approx(0.05)
            for item in success.observations
        )
        assert (
            kernels[0].authority.snapshot() == coupled and kernels[1].authority.snapshot() == spring
        )
    finally:
        for kernel in kernels:
            kernel.close()
        service.close()


def test_actual_cancelled_attempt_keeps_only_scheduled_prefix_and_resume_matches_all_channels(
    tmp_path, monkeypatch
):
    project = electrothermal_project(duration=10, windows=10, sample_every=1, checkpoint_every=2)
    with host(project, tmp_path) as kernel:
        service = kernel.computations
        original = WorkerProcess.send
        cancelled = []
        cancel_sent = Event()

        def cancel_before_checkpoint_ack(worker, payload):
            control = worker_control_from_bytes(payload)
            if isinstance(control, CancelRequest):
                original(worker, payload)
                cancel_sent.set()
                return
            if (
                isinstance(control, PublicationEvent)
                and control.publication.artifact.id == "checkpoint:2"
                and not cancelled
            ):
                # The real worker is waiting for this admitted checkpoint's ACK.
                # Order cancellation before that ACK on its ordinary control
                # channel. A progress notification has no such barrier: a short
                # computation can finish before the asynchronous cancel arrives.
                cancelled.append(control.session_id)
                service.cancel(CancelRequest(control.session_id))
                assert cancel_sent.wait(5), "The host did not send cancellation"
            original(worker, payload)

        with monkeypatch.context() as patch:
            patch.setattr(WorkerProcess, "send", cancel_before_checkpoint_ack)
            result = execute_computation(kernel, request(project))
        assert cancelled and result.outcome is ComputationOutcome.CANCELLED
        assert not service.job(cancelled[0]).view.forced_termination
        store = kernel.resource_store
        retained = rows(store, last_root(result, store))
        checkpoint = [
            item.resource for item in result.artifacts if item.id.startswith("checkpoint:")
        ][-1]
        record = CODEC.decode(store.read(checkpoint), CoupledCheckpoint)
        assert record.position.step == retained[-1, 0] == 2
        assert len(retained) == record.position.step + 1
        continued = execute_computation(kernel, request(project, checkpoint))
        full = execute_computation(kernel, request(project))
        assert continued.outcome is full.outcome is ComputationOutcome.SUCCEEDED
        assert np.array_equal(
            rows(store, last_root(continued, store)), rows(store, last_root(full, store))
        )
        assert result.outcome is ComputationOutcome.CANCELLED
