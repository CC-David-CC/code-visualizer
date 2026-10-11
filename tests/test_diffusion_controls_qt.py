"""Actual desktop freeze/cancel/checkpoint/resume/reopen controls over real Git."""

from threading import get_ident

from PySide6.QtWidgets import QPushButton
from test_diffusion_git import experiment as experiment
from test_git_experiments import untouched

from code_visualizer.application.domain_commands import SetDomainProperty
from code_visualizer.application.git import GitRepository
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.extensions.diffusion.domain import BACKEND_ID, identity
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.ui_qt.main_window import CloseDecision, MainWindow


def button(widget, text):
    return next(item for item in widget.findChildren(QPushButton) if item.text() == text)


def test_desktop_field_freeze_cancel_resume_reopen_and_presentation_are_not_semantic_edits(
    qtbot, experiment, monkeypatch
):
    controller, original, host, root = experiment
    assert isinstance(
        original.client.transaction(
            tuple(
                SetDomainProperty(
                    "diffusion:experiment", "diffusion:policy", identity("TimePolicy", key), value
                )
                for key, value in (
                    ("steps", 8192),
                    ("sample_every", 64),
                    ("checkpoint_every", 1024),
                    ("preview_every", 7),
                )
            )
        ),
        CommandAccepted,
    )
    original.save_as(original.root)
    before = untouched(root)
    window = MainWindow(computations=host, close_decision=lambda _: CloseDecision.DISCARD)
    qtbot.addWidget(window)
    window._install_session(original)
    widget = window.domain_workbench
    qtbot.waitUntil(
        lambda: widget.model_choice.findData("diffusion:experiment") >= 0, timeout=10000
    )
    widget.reveal("diffusion:problem")
    qtbot.waitUntil(lambda: widget.backend_choice.findData(BACKEND_ID + "@1") >= 0, timeout=10000)
    widget.backend_choice.setCurrentIndex(widget.backend_choice.findData(BACKEND_ID + "@1"))
    gui_thread = get_ident()
    operations = []
    git_run, resource_write = GitRepository._run, ResourceStore._put_stream

    def observed_git(*args, **kwargs):
        operations.append(("git", get_ident()))
        return git_run(*args, **kwargs)

    def observed_resource(*args, **kwargs):
        operations.append(("resource", get_ident()))
        return resource_write(*args, **kwargs)

    monkeypatch.setattr(GitRepository, "_run", observed_git)
    monkeypatch.setattr(ResourceStore, "_put_stream", observed_resource)
    try:
        widget.freeze_computation_button.click()
        qtbot.waitUntil(lambda: window._session is not original, timeout=30000)
        frozen = window._session
        qtbot.waitUntil(lambda: bool(host.attempts()), timeout=15000)
        first = host.attempts()[0].session.id
        widget.reveal("diffusion:problem")
        draft = widget._properties[identity("Problem", "name")].control
        draft.setText("Unaccepted experiment title")
        project = frozen.authority.snapshot()
        qtbot.waitUntil(
            lambda: any(
                p.artifact.id == "checkpoint:1024" for p in host.job(first).publications.values()
            ),
            timeout=30000,
        )
        qtbot.waitUntil(lambda: widget.cancel_computation_button.isEnabled(), timeout=5000)
        widget.cancel_computation_button.click()
        qtbot.waitUntil(lambda: host.job(first).done.is_set(), timeout=15000)
        assert host.wait(first).outcome is ComputationOutcome.CANCELLED
        assert draft.text() == "Unaccepted experiment title"
        assert frozen.authority.snapshot() is project
        field = widget.field_history
        qtbot.waitUntil(lambda: field.presentation is not None, timeout=15000)
        field.time_cursor.setValue(0)
        qtbot.waitUntil(lambda: field.pending_tasks == 0, timeout=5000)
        field.play.click()
        qtbot.waitUntil(lambda: field.time_cursor.value() > 0, timeout=3000)
        field.play.click()
        assert frozen.authority.snapshot() is project
        assert len(window._git_controller.experiments.store.identities("variants")) == 1
        git_view = window.git_workbench
        git_view.refresh()
        qtbot.waitUntil(lambda: git_view.retained_runs.topLevelItemCount() == 1, timeout=10000)
        git_view.retained_runs.setCurrentItem(git_view.retained_runs.topLevelItem(0))
        button(git_view, "List checkpoints").click()
        qtbot.waitUntil(lambda: git_view.checkpoints.count() > 0, timeout=10000)
        choice = git_view.checkpoints.itemData(0)
        button(git_view, "Resume selected checkpoint").click()
        qtbot.waitUntil(lambda: len(host.attempts()) == 2, timeout=30000)
        resumed = next(item.session.id for item in host.attempts() if item.session.id != first)
        qtbot.waitUntil(lambda: host.job(resumed).done.is_set(), timeout=60000)
        assert host.wait(resumed).outcome is ComputationOutcome.SUCCEEDED
        active = window._git_controller
        attempts = active.experiments.store.attempts()
        resumed_record = next(item for item in attempts if item.parent_attempt == choice.attempt_id)
        assert resumed_record.checkpoint_id == choice.publication_id
        # Explicit resume adds the checkpoint to the input closure; freezing that
        # different input may create a variant. Playback and draft text did not.
        assert len(active.experiments.store.identities("variants")) == 2
        git_view.refresh()
        qtbot.waitUntil(lambda: git_view.retained_runs.topLevelItemCount() == 2, timeout=10000)
        for row in range(2):
            item = git_view.retained_runs.topLevelItem(row)
            if item.text(0) == choice.attempt_id:
                git_view.retained_runs.setCurrentItem(item)
        button(git_view, "Open retained run").click()
        qtbot.waitUntil(lambda: window._session.read_only, timeout=30000)
        assert window._session.authority.snapshot().domain_workspace == project.domain_workspace
        assert operations and all(thread != gui_thread for _, thread in operations)
        assert untouched(root) == before
    finally:
        if window._git_controller:
            window._git_controller.close_background(wait=True)
        window.close()
        controller.close_background(wait=True)
