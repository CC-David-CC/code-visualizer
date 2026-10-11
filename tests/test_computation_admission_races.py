"""Real workers retain the cancellation boundary across host admission races."""

from dataclasses import replace
from hashlib import sha256
from threading import Event, Thread

import pytest
from fixtures.computation_worker_fixture import BACKEND_ID, fixture_registry, worker_profile

from code_visualizer.application import computation
from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.project_factory import create_default_project
from code_visualizer.domain.computation import (
    CancelRequest,
    ComputationParameter,
    ComputationRequest,
)
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.domain.program import ExpressionRole, ProgramAction, make_program_expression
from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.semantic import ProjectionKind
from code_visualizer.generation.computation import computation_input_digest
from code_visualizer.generation.transformation import TransformationError
from code_visualizer.persistence import python_execution
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.serialization import project_data_chunks
from code_visualizer.sdk import CodeVisualizerClient

WORKER_TIMEOUT = 40.0
GATE_TIMEOUT = 20.0


def test_cancel_after_real_python_preparation_before_managed_installation_skips_entrypoint(
    tmp_path, monkeypatch
):
    marker = tmp_path / "entrypoint-ran.txt"
    project = create_default_project()
    program = project.program_model
    function = program.functions[0]
    statement = ProgramAction(
        "race:marker",
        make_program_expression(
            "race:marker",
            "source",
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('entered', encoding='utf-8')",
            ExpressionRole.STATEMENTS,
        ),
    )
    function = replace(function, body=replace(function.body, statements=(statement,)))
    project = replace(project, program_model=replace(program, functions=(function,)))
    entered, release = Event(), Event()
    loaded = []
    original = python_execution.load_python_execution_artifact

    def pause_host_after_load(reference, store):
        generated = original(reference, store)
        loaded.append(generated)
        entered.set()
        assert release.wait(GATE_TIMEOUT), "The test did not release host artifact admission"
        return generated

    monkeypatch.setattr(python_execution, "load_python_execution_artifact", pause_host_after_load)
    service = ComputationService()
    evidence_store = EvidenceStore(tmp_path / "project")
    kernel = ProjectKernel(
        ProjectAuthority(project),
        computations=service,
        resource_store=ResourceStore(tmp_path / "project"),
        evidence_store=evidence_store,
    )
    project = kernel.authority.snapshot()
    request = ComputationRequest(
        project.id,
        project.revision,
        "code_visualizer.python",
        "1",
        configuration=(ComputationParameter("timeout_seconds", 10),),
    )
    try:
        session = computation.start_computation(kernel, request)
        job = service.job(session.id)
        assert entered.wait(WORKER_TIMEOUT), job.error or job.view.diagnostic
        assert job.snapshot is not None and job.plan is not None
        assert job.worker is None and job.managed is None
        assert loaded[0].generated.invocation.callable_id == function.id
        assert not marker.exists()
        service.cancel(CancelRequest(session.id))
        assert job.cancelled.is_set()
        release.set()
        assert job.done.wait(WORKER_TIMEOUT), job.view
        result = service.wait(session.id)
        assert result.outcome is ComputationOutcome.CANCELLED
        assert result.observations == ()
        assert not job.view.forced_termination
        assert evidence_store.get(result.id) == result
        assert not marker.exists(), "Cancellation lost in the managed-driver installation gap"

        # Positive control: the identical real prepared program has an observable entrypoint.
        control = computation.start_computation(kernel, request)
        assert service.job(control.id).done.wait(WORKER_TIMEOUT)
        executed = service.wait(control.id)
        assert executed.outcome is ComputationOutcome.SUCCEEDED, executed.diagnostics
        assert marker.read_text(encoding="utf-8") == "entered"
        assert evidence_store.get(result.id).outcome is ComputationOutcome.CANCELLED
        assert kernel.authority.snapshot() == project
    finally:
        release.set()
        kernel.close()
        service.close()


def test_cancel_rejects_finalization_and_close_drains_real_worker_before_success_commit(
    tmp_path, monkeypatch
):
    service = ComputationService(profiles=(worker_profile(),))
    evidence_store = EvidenceStore(tmp_path)
    resources = ResourceStore(tmp_path)
    source = resources.put(
        b"10,20,30",
        "text/csv",
        logical_type=ResourceLogicalTypeReference("org.codevisualizer.test:integer-series", "1"),
    ).reference
    project = create_default_project()
    kernel = ProjectKernel(
        ProjectAuthority(project),
        extensions=fixture_registry(),
        computations=service,
        resource_store=resources,
        evidence_store=evidence_store,
    )
    project = kernel.authority.snapshot()
    entered, release, shutdown_entered, closed = Event(), Event(), Event(), Event()
    proposals, close_errors = [], []
    original_evidence = computation._evidence
    original_shutdown = service._pool.shutdown

    def pause_host_evidence(*args, **kwargs):
        evidence = original_evidence(*args, **kwargs)
        if evidence.outcome is ComputationOutcome.SUCCEEDED:
            proposals.append(evidence)
            entered.set()
            assert release.wait(GATE_TIMEOUT), "The test did not release terminal admission"
        return evidence

    def observe_drain(*args, **kwargs):
        shutdown_entered.set()
        return original_shutdown(*args, **kwargs)

    def close_host():
        try:
            service.close()
        except Exception as error:
            close_errors.append(error)
        finally:
            closed.set()

    monkeypatch.setattr(computation, "_evidence", pause_host_evidence)
    monkeypatch.setattr(service._pool, "shutdown", observe_drain)
    closing = None
    try:
        session = computation.start_computation(
            kernel,
            ComputationRequest(
                project.id,
                project.revision,
                BACKEND_ID,
                "1",
                configuration=(
                    ComputationParameter("mode", "consume"),
                    ComputationParameter("input", source),
                ),
            ),
        )
        job = service.job(session.id)
        assert entered.wait(WORKER_TIMEOUT), job.error or job.view.diagnostic
        worker = job.worker
        assert worker is not None and worker.is_active
        assert job.view.phase == "finalizing" and not job.done.is_set()
        assert evidence_store.identities() == ()
        with pytest.raises(TransformationError) as rejected:
            service.cancel(CancelRequest(session.id))
        assert rejected.value.code == "COMPUTATION_FINALIZING"
        assert not job.cancelled.is_set()

        closing = Thread(target=close_host, name="test-finalizing-host-close", daemon=True)
        closing.start()
        assert shutdown_entered.wait(GATE_TIMEOUT)
        assert not closed.is_set(), "Host close returned before draining terminal admission"
        assert not job.cancelled.is_set(), "Host close cancelled an already finalizing attempt"
        assert worker.is_active, "Host close terminated the worker awaiting its terminal ACK"
        assert not worker.forced_termination
        release.set()
        assert closed.wait(WORKER_TIMEOUT), "Host close did not drain the admitted worker result"
        closing.join(GATE_TIMEOUT)
        assert not close_errors and not closing.is_alive()
        result = service.wait(session.id)
        assert result.outcome is ComputationOutcome.SUCCEEDED, result.diagnostics
        assert next(item.value for item in result.observations if item.id == "sum") == 60
        assert result == proposals[0] == evidence_store.get(result.id)
        assert not job.cancelled.is_set() and not job.view.forced_termination
        assert not worker.is_active
        assert kernel.authority.snapshot() == project
    finally:
        release.set()
        if closing is not None:
            closing.join(WORKER_TIMEOUT)
        kernel.close()
        service.close()


def test_authority_edit_during_real_final_admission_retains_historical_source_and_evidence(
    tmp_path, monkeypatch
):
    service = ComputationService(profiles=(worker_profile(),))
    evidence_store = EvidenceStore(tmp_path)
    resources = ResourceStore(tmp_path)
    source = resources.put(
        b"10,20,30",
        "text/csv",
        logical_type=ResourceLogicalTypeReference("org.codevisualizer.test:integer-series", "1"),
    ).reference
    authority = ProjectAuthority(create_default_project())
    kernel = ProjectKernel(
        authority,
        extensions=fixture_registry(),
        computations=service,
        resource_store=resources,
        evidence_store=evidence_store,
    )
    client = CodeVisualizerClient(authority, actor_id="admission-race-editor")
    original_project = authority.snapshot()
    function = original_project.program_model.functions[0]
    source_digest = sha256(b"".join(project_data_chunks(original_project))).hexdigest()
    entered, release = Event(), Event()
    proposals = []
    original_evidence = computation._evidence

    def pause_real_terminal_admission(*args, **kwargs):
        evidence = original_evidence(*args, **kwargs)
        if evidence.outcome is ComputationOutcome.SUCCEEDED:
            proposals.append(evidence)
            entered.set()
            assert release.wait(GATE_TIMEOUT), "The test did not release terminal admission"
        return evidence

    monkeypatch.setattr(computation, "_evidence", pause_real_terminal_admission)
    try:
        session = computation.start_computation(
            kernel,
            ComputationRequest(
                original_project.id,
                original_project.revision,
                BACKEND_ID,
                "1",
                configuration=(
                    ComputationParameter("mode", "consume"),
                    ComputationParameter("input", source),
                ),
            ),
        )
        job = service.job(session.id)
        assert entered.wait(WORKER_TIMEOUT), job.error or job.view.diagnostic
        worker = job.worker
        assert worker is not None and worker.is_active
        assert job.view.phase == "finalizing" and not job.done.is_set()
        assert evidence_store.identities() == ()
        assert service.evidence(session.id) is None
        assert job.project == original_project
        assert job.snapshot is not None and job.plan is not None
        input_digest = computation_input_digest(original_project, job.plan.request)
        assert job.view.source_digest == source_digest
        assert job.view.input_digest == input_digest

        # The real admitted observation currently decorates this exact authored function.
        assert function.id in kernel.current_runtime_ids()
        before = kernel.project_projection(ProjectionKind.ARCHITECTURE)
        assert any(
            node.semantic_id == function.id and "active" in node.badges for node in before.nodes
        )

        edit = client.insert_program_statement(
            function.id,
            function.body.id,
            0,
            "output",
            statement_id="race:authored-after-submission",
            expression="'edited during terminal admission'",
            expected_revision=original_project.revision,
        )
        assert isinstance(edit, CommandAccepted), edit
        changed_project = authority.snapshot()
        assert changed_project.revision == original_project.revision + 1
        assert changed_project.program_model != original_project.program_model
        assert sha256(b"".join(project_data_chunks(changed_project))).hexdigest() != source_digest
        assert (
            computation_input_digest(
                changed_project, replace(job.plan.request, revision=changed_project.revision)
            )
            != input_digest
        )
        assert kernel.computation_attachment.revision == changed_project.revision
        assert kernel.current_runtime_state() is None
        selection_after_edit = kernel.selection.state

        release.set()
        assert job.done.wait(WORKER_TIMEOUT), job.error or job.view.diagnostic
        result = service.wait(session.id)
        service.deliver_selection(kernel.computation_attachment)
        assert result.outcome is ComputationOutcome.SUCCEEDED, result.diagnostics
        assert next(item.value for item in result.observations if item.id == "sum") == 60
        assert result == proposals[0] == EvidenceStore(tmp_path).get(result.id)
        assert result.provenance.revision == original_project.revision
        assert result.provenance.origins.revision == original_project.revision
        assert result.provenance.input_digest == input_digest
        assert job.view.source_digest == source_digest
        assert job.view.input_digest == input_digest
        assert job.view.session.revision == original_project.revision
        assert job.view.session.evidence_id == result.id
        assert job.project == original_project
        assert not worker.is_active and not job.view.forced_termination

        # Completion remains inspectable on its historical revision, never the new source.
        historical = service.state(session.id)
        assert historical is not None and historical.evidence_id == result.id
        assert historical.project_revision == original_project.revision
        assert function.id in historical.active_ids
        assert kernel.runtime.evidence(result.id) == result
        assert kernel.current_runtime_state() is None and not kernel.current_runtime_ids()
        assert kernel.selection.state == selection_after_edit
        after = kernel.project_projection(ProjectionKind.ARCHITECTURE)
        assert any(node.semantic_id == function.id for node in after.nodes)
        assert all("active" not in node.badges for node in after.nodes)
        assert all(not edge.active for edge in after.edges)
        assert authority.snapshot() == changed_project
    finally:
        release.set()
        client.close()
        kernel.close()
        service.close()
