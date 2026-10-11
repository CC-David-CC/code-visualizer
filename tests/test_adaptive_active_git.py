"""Equal numeric revisions never equate different frozen adaptive definitions."""

from dataclasses import replace
from threading import Event

from test_adaptive_computation import last_resource, reader
from test_adaptive_domain import change
from test_adaptive_git import policy_edit, request
from test_coupled_active_git import result
from test_electrothermal_git import repository
from test_git_experiments import untouched

from code_visualizer.application.adaptive_examples import adaptive_diffusion_project
from code_visualizer.application.computation import execute_computation
from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.git_service import GitProjectController
from code_visualizer.application.messages import CommandAccepted, CommandDeferred
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.computation import ComputationParameter, ProgressEvent
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.extensions.adaptive_fields.records import HISTORY_TYPE
from code_visualizer.extensions.adaptive_fields.units import quantity
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.ui_qt.adaptive_history import CellHistoryPanel


def test_active_equal_revision_variants_keep_history_preview_and_checkpoint_isolated(
    qtbot, tmp_path, monkeypatch
):
    project = adaptive_diffusion_project()
    for name, value in (
        ("final_time", quantity(0.4)),
        ("checkpoint_interval", quantity(0.1)),
        ("preview_every", 1),
    ):
        project = change(project, "adaptive:policy", name, value)
    root = tmp_path / "repository"
    repository(root, project)
    before = untouched(root)
    host = ComputationService(max_workers=1)
    original = ProjectSession.open(root / "project", computations=host)
    editors, controllers = [original], [GitProjectController(original)]
    entered, released = Event(), Event()
    held = []
    publish = host.publish

    def hold_after_ack(job, event):
        publish(job, event)
        if isinstance(event, ProgressEvent) and event.completed == 0.1 and not held:
            held.append(job.view.session.id)
            entered.set()
            assert released.wait(120)

    monkeypatch.setattr(host, "publish", hold_after_ack)
    panel = CellHistoryPanel()
    qtbot.addWidget(panel)
    panel.show()

    def fork(controller, value):
        deferred = policy_edit(controller.session, value)
        assert isinstance(deferred, CommandDeferred)
        edit = result(qtbot, controller.experiments.edits[deferred.details["operation_id"]])
        assert isinstance(edit.result, CommandAccepted)
        editors.append(edit.editor)
        return edit.editor

    try:
        first = result(qtbot, controllers[0].submit_freeze_and_run(request(original)))
        old = first.editor
        editors.append(old)
        qtbot.waitUntil(entered.is_set, timeout=30000)
        panel.attach(old.kernel, old.client)
        panel.observe_attempt(host.job(first.computation.id).view)
        qtbot.waitUntil(lambda: panel.presentation is not None, timeout=10000)
        assert panel._source.current_source
        a = fork(controllers[0], 0.0001)
        panel.attach(a.kernel, a.client)
        old.close()
        reopened = ProjectSession.open(old.root, computations=host)
        editors.append(reopened)
        controllers.append(GitProjectController(reopened))
        b = fork(controllers[1], 0.01)
        assert a.authority.revision == b.authority.revision
        assert a.experiment_context.variant_id != b.experiment_context.variant_id
        for child in (a, b):
            assert isinstance(child.client.undo(), CommandAccepted)
            assert isinstance(child.client.redo(), CommandAccepted)
        assert a.authority.revision == b.authority.revision
        assert not host.job(first.computation.id).done.is_set()
        released.set()
        runs = [first]
        for controller, child in zip(controllers, (a, b), strict=True):
            run = result(qtbot, controller.submit_freeze_and_run(request(child)))
            runs.append(run)
            editors.append(run.editor)
            qtbot.waitUntil(lambda r=run: host.job(r.computation.id).done.is_set(), timeout=60000)
        store = ResourceStore(controllers[0].experiments.store.root)
        results, histories, cell_counts = [], [], []
        for run in runs:
            evidence = host.wait(run.computation.id)
            assert evidence.outcome is ComputationOutcome.SUCCEEDED, evidence.diagnostics
            results.append(evidence)
            history = reader(last_resource(evidence, store, HISTORY_TYPE), store)
            histories.append(history.series.source_digest)
            cell_counts.append(len(history.slice(0).mesh.cells))
            history.close()
            assert controllers[0].experiments.verify_run(run.attempt.id)
        assert len(set(histories)) == 3 and cell_counts[1] > cell_counts[2]
        assert len({run.attempt.commit for run in runs}) == 3
        assert len(controllers[0].experiments.store.identities("variants")) == 3
        panel.attach(a.kernel, a.client)
        panel.observe_attempt(host.job(runs[1].computation.id).view)
        qtbot.waitUntil(lambda: panel.presentation is not None, timeout=10000)
        assert panel._source.current_source and panel.presentation.definition_digest == histories[1]
        panel.attach(b.kernel, b.client)
        assert panel.presentation is None
        panel.observe_attempt(host.job(runs[1].computation.id).view)
        qtbot.waitUntil(lambda: panel.presentation is not None, timeout=10000)
        assert (
            not panel._source.current_source
            and panel.presentation.definition_digest == histories[1]
        )
        selected = b.kernel.selection.state
        panel.select.click()
        assert b.kernel.selection.state == selected
        panel.observe_attempt(host.job(runs[2].computation.id).view)
        qtbot.waitUntil(lambda: panel.presentation.definition_digest == histories[2], timeout=10000)
        assert panel._source.current_source
        preview = panel._preview
        panel.preview(host.job(runs[1].computation.id).view.preview)
        assert panel._preview == preview
        # Equal revision and shared object IDs cannot authorize another policy's checkpoint.
        checkpoint = next(a.resource for a in results[1].artifacts if a.id == "checkpoint:2048")
        for reference in b.kernel.extensions.resource_closure((checkpoint,), store):
            b.kernel.resource_store.import_reference(store, reference)
        mismatch = execute_computation(
            b.kernel,
            replace(request(b), configuration=(ComputationParameter("checkpoint", checkpoint),)),
        )
        assert mismatch.outcome is ComputationOutcome.FAILED
        assert any(
            d.code == "ADAPTIVE_CHECKPOINT_COMPATIBILITY" and "adaptive:policy" in d.semantic_ids
            for d in mismatch.diagnostics
        )
        assert untouched(root) == before
    finally:
        released.set()
        panel.attach(None, None)
        panel.shutdown()
        for controller in controllers:
            controller.close_background(wait=True)
        for editor in reversed(editors):
            editor.close()
        host.close()
