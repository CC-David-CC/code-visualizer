"""P2 desktop admission and unaccepted text use the real existing editor widgets."""

from threading import get_ident

from test_git_experiments import dirty_experiment as dirty_experiment
from test_git_experiments import rename_entry

from code_visualizer.application.git import GitRepository
from code_visualizer.application.messages import CommandAccepted, CommandDeferred
from code_visualizer.ui_qt.function_signature import FunctionSignatureEditor
from code_visualizer.ui_qt.main_window import CloseDecision, MainWindow


def test_p2_desktop_freeze_and_fork_keep_git_off_gui_and_unaccepted_text_unforked(
    dirty_experiment, qtbot, monkeypatch
):
    _controller, original, host, _root = dirty_experiment
    window = MainWindow(computations=host, close_decision=lambda _session: CloseDecision.DISCARD)
    qtbot.addWidget(window)
    window._install_session(original)
    qtbot.waitUntil(lambda: window.domain_workbench.backend_choice.count() > 0, timeout=10000)
    gui_thread = get_ident()
    git_threads = []
    run = GitRepository._run

    def observed(repository, *args, **kwargs):
        git_threads.append(get_ident())
        return run(repository, *args, **kwargs)

    monkeypatch.setattr(GitRepository, "_run", observed)
    window.domain_workbench.freeze_computation_button.click()
    qtbot.waitUntil(lambda: window._session is not original, timeout=30000)
    frozen = window._session
    active = window._git_controller
    assert frozen.root != original.root
    signature = FunctionSignatureEditor(frozen.client, frozen.authority.snapshot().documents[0].id)
    qtbot.addWidget(signature)
    signature.identifier.setText("incomplete text !!!")
    assert frozen.authority.snapshot().program_model.functions[0].identifier == "main"
    assert len(list((active.experiments.store.root / "variants").glob("*.json"))) == 1
    assert isinstance(frozen.client.rename_project("Presentation only"), CommandAccepted)
    pending = rename_entry(frozen, "accepted_edit")
    assert isinstance(pending, CommandDeferred)
    qtbot.waitUntil(lambda: window._session is not frozen, timeout=30000)
    assert (
        window._session.authority.snapshot().program_model.functions[0].identifier
        == "accepted_edit"
    )
    assert git_threads and gui_thread not in git_threads
    # The active host/controller belongs to the window after handoff.
    active.close_background(wait=True)
    window.close()
