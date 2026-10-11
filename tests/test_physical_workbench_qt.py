"""Real desktop gestures author a load and compare retained physical runs."""

from pathlib import Path
from threading import get_ident

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QInputDialog, QPushButton
from test_physical_experiments import physical_experiment as physical_experiment

from code_visualizer.application.git import GitRepository
from code_visualizer.domain.computation import ComputationStatus
from code_visualizer.domain.notation import NotationKind
from code_visualizer.extensions.dc import identity
from code_visualizer.extensions.foundations.equations import BACKEND_ID
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.ui_qt.features.domain_workbench.editors import NodeDialog
from code_visualizer.ui_qt.main_window import CloseDecision, MainWindow


def test_p3_desktop_load_edit_freezes_forks_and_compares_on_git_worker(
    physical_experiment, qtbot, monkeypatch, tmp_path
):
    _controller, original, host, _root = physical_experiment
    window = MainWindow(
        computations=host,
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=QSettings(str(tmp_path / "desktop.ini"), QSettings.Format.IniFormat),
    )
    qtbot.addWidget(window)
    window.resize(1550, 980)
    window.show()
    window._install_session(original)
    window._show_domain_workbench()
    widget = window.domain_workbench
    widget.reveal("dc:upper")
    gui_thread = get_ident()
    git_threads, resource_threads = [], []
    run, verify = GitRepository._run, ResourceStore.verified_path

    def observed_git(repository, *args, **kwargs):
        git_threads.append(get_ident())
        return run(repository, *args, **kwargs)

    def observed_resource(store, *args, **kwargs):
        resource_threads.append(get_ident())
        return verify(store, *args, **kwargs)

    monkeypatch.setattr(GitRepository, "_run", observed_git)
    monkeypatch.setattr(ResourceStore, "verified_path", observed_resource)

    def freeze_and_wait(count):
        widget.backend_choice.setCurrentIndex(widget.backend_choice.findData(f"{BACKEND_ID}@1"))
        assert widget.backend_choice.currentData() == f"{BACKEND_ID}@1"
        widget.freeze_computation_button.click()
        qtbot.waitUntil(lambda: len(host.attempts()) == count, timeout=60000)
        qtbot.waitUntil(
            lambda: all(item.phase == "finished" for item in host.attempts()), timeout=60000
        )
        assert all(item.session.status is ComputationStatus.SUCCEEDED for item in host.attempts())

    try:
        freeze_and_wait(1)
        frozen = window._session
        assert frozen is not original and frozen.experiment_context.attempt_id
        # Text is only a buffer; no fork or authored mutation until acceptance.
        widget.reveal("dc:upper")
        field = widget._properties[identity("Resistor", "resistance")].control
        field.real.setText("not accepted")
        assert frozen.authority.snapshot().revision == 0
        widget.reveal("dc:circuit")

        created = []
        role_choice = ["components"]
        concept_choice = ["Resistor"]
        net_choice = [None]
        monkeypatch.setattr(
            QInputDialog,
            "getItem",
            lambda *_a, **_k: (
                next(name for name in _a[3] if name.lower().startswith(role_choice[0])),
                True,
            ),
        )

        def fill_real_dialog(dialog):
            dialog.concept_choice.setCurrentIndex(
                dialog.concept_choice.findData(identity(concept_choice[0]))
            )
            dialog.properties[identity(concept_choice[0], "name")].control.setText("Load")
            if net_choice[0]:
                editor = dialog.references[identity("Terminal", "net")]
                for index in range(editor.count()):
                    item = editor.item(index)
                    if item.data(Qt.ItemDataRole.UserRole) == net_choice[0]:
                        item.setCheckState(Qt.CheckState.Checked)
            dialog._accept()
            created.append(dialog.node().id)
            return dialog.result()

        monkeypatch.setattr(NodeDialog, "exec", fill_real_dialog)
        widget.create_node(True)
        qtbot.waitUntil(lambda: window._session is not frozen, timeout=60000)
        child = window._session
        load_id = created[0]
        assert child.experiment_context.attempt_id is None
        assert frozen.authority.snapshot().domain_workspace.node(load_id) is None
        concept_choice[0] = "Terminal"
        for role, net in (("positive", "dc:middle"), ("negative", "dc:ground")):
            role_choice[0], net_choice[0] = "+" if role == "positive" else "-", net
            widget.reveal(load_id)
            widget.create_node(True)
        assert child.authority.snapshot().revision == 3
        assert (
            len(list((window._git_controller.experiments.store.root / "variants").glob("*.json")))
            == 2
        )
        widget.undo()
        widget.redo()
        assert child.authority.snapshot().domain_workspace.node(created[-1]) is not None
        widget.reveal("dc:middle")
        freeze_and_wait(2)
        assert child.experiment_context.attempt_id
        git_widget = window.git_workbench
        git_widget.perform("experiment_runs")
        qtbot.waitUntil(lambda: not git_widget._busy, timeout=30000)
        qtbot.waitUntil(lambda: git_widget.retained_runs.topLevelItemCount() == 2, timeout=30000)
        for index in range(2):
            git_widget.retained_runs.topLevelItem(index).setSelected(True)
        compare_button = next(
            item
            for item in git_widget.findChildren(QPushButton)
            if item.text() == "Compare selected runs"
        )
        compare_button.click()
        qtbot.waitUntil(lambda: git_widget.comparison.topLevelItemCount() > 0, timeout=30000)
        rows = [
            git_widget.comparison.topLevelItem(i)
            for i in range(git_widget.comparison.topLevelItemCount())
        ]
        midpoint = next(
            row for row in rows if row.text(1) == "2.5 V" and row.text(2).startswith("1.6666667")
        )
        assert midpoint.text(3).startswith("-0.83333333")
        # Retained comparison navigation uses the same authoring selection in all lenses.
        upper = next(
            row
            for row in rows
            if "dc:upper" in row.data(0, Qt.ItemDataRole.UserRole) and row.text(1) == "0.0025 A"
        )
        git_widget.comparison.setCurrentItem(upper)
        assert "dc:upper" in child.kernel.selection.state.semantic_ids
        assert widget.reconciler.node_items["dc:upper"].isSelected()
        assert any(item.isSelected() for item in widget.table.selectedItems())
        assert any(item.isSelected() for item in widget.tree.selectedItems())
        assert widget.projections[NotationKind.GRAPH].graph.nodes
        assert git_threads and gui_thread not in git_threads
        assert resource_threads and gui_thread not in resource_threads
        git_widget.tabs.setCurrentIndex(git_widget.tabs.count() - 1)
        window._show_git_workbench()
        qtbot.wait(100)
        # A local review image; it is not a replacement for the behavioral assertions.
        window.grab().save(str(Path(".test-p3-physical-workbench.png").resolve()))
    finally:
        window._git_controller.close_background(wait=True)
        window.close()
