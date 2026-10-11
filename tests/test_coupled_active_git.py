"""Real active attempts survive forks, including different branches at equal revisions."""

from dataclasses import replace
from threading import Event

import numpy as np
from test_electrothermal_checkpoints import last_root, rows
from test_electrothermal_contracts import changed
from test_electrothermal_git import repository, request
from test_git_experiments import untouched

from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.coupled_examples import electrothermal_project
from code_visualizer.application.domain_commands import SetDomainProperty
from code_visualizer.application.git_service import GitProjectController
from code_visualizer.application.messages import CommandAccepted, CommandDeferred
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.computation import ProgressEvent
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.extensions.electrothermal.units import quantity
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.ui_qt.channel_history import ChannelHistoryPanel


def result(qtbot, future, timeout=90000):
    qtbot.waitUntil(future.done, timeout=timeout)
    return future.result()


def voltage_edit(editor, value):
    project = editor.authority.snapshot()
    model = next(m for m in project.domain_workspace.models if m.node("et:supply"))
    node = model.node("et:supply")
    return SetDomainProperty(
        model.id, node.id, node.concept_id + ":voltage", quantity(value, "volt")
    )


def fork(qtbot, controller, value):
    submitted = controller.session.client.submit(voltage_edit(controller.session, value))
    assert isinstance(submitted, CommandDeferred)
    operation = controller.experiments.edits[submitted.details["operation_id"]]
    completed = result(qtbot, operation)
    assert isinstance(completed.result, CommandAccepted)
    return completed.editor


def test_active_run_two_equal_revision_forks_keep_exact_inputs_and_history(
    qtbot, tmp_path, monkeypatch
):
    project = changed(
        electrothermal_project(duration=6, windows=6, sample_every=1, checkpoint_every=2),
        "et:policy",
        "preview_every",
        1,
    )
    root = tmp_path / "repository"
    repository(root, project)
    before = untouched(root)
    host = ComputationService(max_workers=2)
    original = ProjectSession.open(root / "project", computations=host)
    controllers = [GitProjectController(original)]
    editors = [original]
    entered, release = Event(), Event()
    publish = host.publish
    held = []

    def hold_after_accepted_checkpoint(job, event):
        publish(job, event)
        if isinstance(event, ProgressEvent) and event.completed == 2 and not held:
            held.append(job.view.session.id)
            entered.set()
            assert release.wait(120), "Test did not release the already accepted window"

    monkeypatch.setattr(host, "publish", hold_after_accepted_checkpoint)
    panel = ChannelHistoryPanel()
    qtbot.addWidget(panel)
    panel.show()
    try:
        first = result(qtbot, controllers[0].submit_freeze_and_run(request(original)))
        old = first.editor
        editors.append(old)
        qtbot.waitUntil(entered.is_set, timeout=30000)
        assert not host.job(first.computation.id).done.is_set()
        panel.attach(old.kernel, old.client)
        panel.observe_attempt(host.job(first.computation.id).view)
        qtbot.waitUntil(lambda: panel.presentation is not None, timeout=10000)
        assert panel.presentation.selected.step == 2
        assert panel._source.current_source
        child_a = fork(qtbot, controllers[0], 6)
        editors.append(child_a)
        assert child_a.experiment_context.attempt_id is None
        assert not host.job(first.computation.id).done.is_set()
        # Reopen the same frozen predecessor through the ordinary loader, then
        # fork a different child. Both have local revision 1, not shared meaning.
        panel.attach(child_a.kernel, child_a.client)
        old.close()
        reopened = ProjectSession.open(old.root, computations=host)
        editors.append(reopened)
        controllers.append(GitProjectController(reopened))
        child_b = fork(qtbot, controllers[1], 4)
        editors.append(child_b)
        assert child_a.authority.revision == child_b.authority.revision
        assert child_a.experiment_context.variant_id != child_b.experiment_context.variant_id
        assert isinstance(child_a.client.undo(), CommandAccepted)
        assert isinstance(child_a.client.redo(), CommandAccepted)
        # Restore equal revisions for this explicit isolation test by performing
        # the same native undo/redo on B, without altering either final meaning.
        assert isinstance(child_b.client.undo(), CommandAccepted)
        assert isinstance(child_b.client.redo(), CommandAccepted)
        assert child_a.authority.revision == child_b.authority.revision
        release.set()
        run_a = result(qtbot, controllers[0].submit_freeze_and_run(request(child_a)))
        run_b = result(qtbot, controllers[1].submit_freeze_and_run(request(child_b)))
        editors.extend((run_a.editor, run_b.editor))
        for run in (first, run_a, run_b):
            qtbot.waitUntil(lambda r=run: host.job(r.computation.id).done.is_set(), timeout=60000)
        resources = ResourceStore(controllers[0].experiments.store.root)
        decoded = []
        for run in (first, run_a, run_b):
            evidence = host.wait(run.computation.id)
            assert evidence.outcome is ComputationOutcome.SUCCEEDED, evidence.diagnostics
            decoded.append(rows(resources, last_root(evidence, resources)))
            assert controllers[0].experiments.verify_run(run.attempt.id)
        assert np.all(decoded[0][:, 5] == 5)
        assert np.all(decoded[1][:, 5] == 6)
        assert np.all(decoded[2][:, 5] == 4)
        assert len({r.attempt.commit for r in (first, run_a, run_b)}) == 3
        assert len(controllers[0].experiments.store.identities("variants")) == 3
        panel.attach(run_a.editor.kernel, run_a.editor.client)
        panel.observe_attempt(host.job(run_a.computation.id).view)
        qtbot.waitUntil(lambda: panel.presentation is not None, timeout=10000)
        assert panel._source.current_source and panel.presentation.values[3] == 6
        prior = panel._source
        panel.attach(run_b.editor.kernel, run_b.editor.client)
        assert panel.presentation is None and "current authoring" not in panel.status.text()
        panel.observe_attempt(host.job(run_a.computation.id).view)
        qtbot.waitUntil(lambda: panel.presentation is not None, timeout=10000)
        assert not panel._source.current_source and panel.presentation.values[3] == 6
        panel.observe_attempt(host.job(run_b.computation.id).view)
        qtbot.waitUntil(
            lambda: (
                panel._source.session_id == run_b.computation.id
                and panel.presentation.values[3] == 4
            ),
            timeout=10000,
        )
        assert panel._source.current_source
        previous_preview = panel._preview
        panel.preview(host.job(run_a.computation.id).view.preview)
        assert panel._preview == previous_preview
        # Historical reopening is explicit, even in the new equal-revision editor.
        panel.inspect(replace(prior, current_source=False))
        qtbot.waitUntil(lambda: panel.presentation.values[3] == 6, timeout=10000)
        assert not panel._source.current_source
        assert untouched(root) == before
    finally:
        release.set()
        panel.attach(None, None)
        panel.shutdown()
        for controller in controllers:
            controller.close_background(wait=True)
        for editor in reversed(editors):
            editor.close()
        host.close()
