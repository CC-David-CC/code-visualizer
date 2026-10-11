import asyncio
from collections.abc import Iterator
from pathlib import Path

from PySide6.QtCore import QPointF, QSettings, Qt, QTimer
from PySide6.QtWidgets import QApplication, QListView, QMessageBox, QTreeWidgetItem

from code_visualizer.application.commands import InsertDrakonAtom, RenameProject
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.session import ProjectSession
from code_visualizer.automation.service import AccessMode
from code_visualizer.domain.common import DocumentKind
from code_visualizer.domain.drakon import Assignment, Call, If, Loop, Output
from code_visualizer.sdk import AsyncRemoteClient
from code_visualizer.ui_qt.command_palette import CommandPalette
from code_visualizer.ui_qt.document import UnifiedDocumentWidget
from code_visualizer.ui_qt.main_window import (
    CloseDecision,
    DrakonDeleteChoice,
    MainWindow,
    SaveFailureDecision,
)


def _settings(path: Path) -> QSettings:
    return QSettings(str(path / "settings.ini"), QSettings.Format.IniFormat)


def _tree_items(root: QTreeWidgetItem) -> Iterator[QTreeWidgetItem]:
    yield root
    for index in range(root.childCount()):
        yield from _tree_items(root.child(index))


def _project_item(window: MainWindow, value: str) -> QTreeWidgetItem | None:
    root = window.project_tree.topLevelItem(0)
    if root is None:
        return None
    return next(
        (item for item in _tree_items(root) if item.data(0, Qt.ItemDataRole.UserRole) == value),
        None,
    )


def test_new_project_exposes_main_and_complete_unified_document(qtbot, tmp_path) -> None:
    window = MainWindow(
        path_chooser=lambda: tmp_path / "saved-project",
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()

    window.action_new.trigger()

    assert window.session is not None
    assert window.project_tree.topLevelItem(0).text(0) == "Untitled Project"
    document = window.documents.currentWidget()
    assert isinstance(document, UnifiedDocumentWidget)
    assert document.header_label.text() == "main()"
    assert document.empty_hint.isVisible()
    qtbot.waitUntil(lambda: document._generated is not None, timeout=10000)
    assert document.code.toPlainText().startswith("def main():")
    assert document.console.objectName() == "liveTestConsole"
    assert not document.signature.is_expanded
    assert document.signature.height() < 120
    qtbot.mouseClick(document.signature.toggle_details, Qt.MouseButton.LeftButton)
    assert document.signature.is_expanded
    assert document.signature.identifier.isVisible()
    qtbot.mouseClick(document.signature.toggle_details, Qt.MouseButton.LeftButton)
    assert not document.signature.is_expanded
    assert window.dockWidgetArea(window.inspector_dock) == Qt.DockWidgetArea.LeftDockWidgetArea
    assert window.dockWidgetArea(window.development_dock) == Qt.DockWidgetArea.BottomDockWidgetArea


def test_semantic_navigation_actions_and_history_use_stable_references(qtbot, tmp_path) -> None:
    window = MainWindow(
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()
    assert window.session is not None
    client = window.session.client
    main = window.session.authority.snapshot().documents[0]
    created = client.create_diagram(DocumentKind.DRAKON, "Helper", identifier="helper")
    assert isinstance(created, CommandAccepted)
    helper = window.session.authority.snapshot().documents[1]
    inserted = client.insert_drakon_atom(main.id, "call", 0)
    assert isinstance(inserted, CommandAccepted)
    call = window.session.authority.snapshot().documents[0].body.atoms[0]
    assert isinstance(call, Call)
    linked = client.replace_drakon_atom(main.id, Call(call.id, target_diagram_id=helper.id))
    assert isinstance(linked, CommandAccepted)
    qtbot.waitUntil(lambda: _project_item(window, helper.id) is not None)

    window.action_call_hierarchy.trigger()
    assert window.navigation_dock.isVisible()
    root = window.navigation.results.topLevelItem(0)
    assert root is not None and root.childCount() == 1
    child = root.child(0)
    window.navigation.results.setCurrentItem(child)
    qtbot.keyClick(window.navigation.results, Qt.Key.Key_Return)
    current = window.documents.currentWidget()
    assert isinstance(current, UnifiedDocumentWidget)
    assert current.diagram_id == main.id
    assert current.canvas.selected_atom_ids() == (call.id,)

    helper_item = _project_item(window, helper.id)
    assert helper_item is not None
    window.project_tree.setCurrentItem(helper_item)
    qtbot.keyClick(window.project_tree, Qt.Key.Key_Return)
    assert window.documents.currentWidget().diagram_id == helper.id
    before_revision = window.session.authority.revision

    window.action_navigation_back.trigger()
    assert window.documents.currentWidget().diagram_id == main.id
    assert window.session.authority.revision == before_revision
    window.action_navigation_forward.trigger()
    assert window.documents.currentWidget().diagram_id == helper.id
    assert window.session.authority.revision == before_revision


def test_welcome_example_opens_an_editable_copy_via_keyboard(qtbot, tmp_path) -> None:
    window = MainWindow(
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window.welcome.examples.setFocus()
    window.welcome.examples.setCurrentRow(0)
    qtbot.keyClick(window.welcome.examples, Qt.Key.Key_Return)

    assert window.session is not None
    assert window.session.root is None
    assert window.session.authority.snapshot().title == "Hello World Example"
    document = window.documents.currentWidget()
    assert isinstance(document, UnifiedDocumentWidget)
    qtbot.waitUntil(lambda: document._generated is not None, timeout=10000)
    assert "print('Hello, world!')" in document.code.toPlainText()


def test_shapes_are_recipe_thumbnails_and_one_click_inserts_without_modal(qtbot, tmp_path) -> None:
    window = MainWindow(
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()
    assert window.shape_list.viewMode() == QListView.ViewMode.IconMode
    assert window.shape_list.dragEnabled()
    item = window.shape_list.item(0)
    assert not item.icon().isNull()
    rect = window.shape_list.visualItemRect(item)

    qtbot.mouseClick(
        window.shape_list.viewport(),
        Qt.MouseButton.LeftButton,
        pos=rect.center(),
    )

    assert window.session is not None
    atom = window.session.authority.snapshot().documents[0].body.atoms[0]
    assert atom.source == "print('action')"


def test_hello_world_runs_saves_generates_and_full_project_runs(qtbot, tmp_path) -> None:
    root = tmp_path / "hello-project"
    window = MainWindow(path_chooser=lambda: root, settings=_settings(tmp_path))
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()
    document = window.documents.currentWidget()
    assert isinstance(document, UnifiedDocumentWidget)

    qtbot.mouseClick(document.hello_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: "'Hello, world!'" in document.code.toPlainText(), timeout=10000)
    assert "'Hello, world!'" in document.code.toPlainText()

    window.action_run_current.trigger()
    qtbot.waitUntil(lambda: document.console.toPlainText() == "Hello, world!\n")

    window.action_save.trigger()
    assert window.session is not None
    assert window.session.authority.snapshot().title == "hello-project"
    assert (root / "project.json").is_file()

    window.action_generate.trigger()
    qtbot.waitUntil(lambda: window.artifacts.topLevelItemCount() >= 3)
    assert (root / "generated" / "app" / "main.py").is_file()
    assert (root / "generated" / "run_project.py").is_file()
    assert not (root / "generated" / "project.py").exists()
    assert (root / "generated" / "generation.json").is_file()
    assert window.artifacts.topLevelItemCount() >= 3

    window.action_run.trigger()
    qtbot.waitUntil(lambda: window.run_output.toPlainText() == "Hello, world!\n")


def test_open_saved_project_replaces_welcome_without_untitled_phantom(qtbot, tmp_path) -> None:
    root = tmp_path / "saved"
    first = MainWindow(path_chooser=lambda: root, settings=_settings(tmp_path))
    qtbot.addWidget(first)
    first.show()
    first.action_new.trigger()
    first.action_save.trigger()
    first.close()

    second = MainWindow(path_chooser=lambda: root, settings=_settings(tmp_path))
    qtbot.addWidget(second)
    second.show()
    second.action_open.trigger()

    assert second.session is not None
    assert second.project_tree.topLevelItemCount() == 1
    assert second.project_tree.topLevelItem(0).text(0) == "saved"
    assert "Untitled" not in second.windowTitle()


def test_save_as_forks_read_only_snapshot_and_opens_editable_copy(qtbot, tmp_path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "editable-copy"
    owner = ProjectSession.new(actor_id="owner")
    owner.save_as(source)
    read_only = ProjectSession.open(source, actor_id="viewer", read_only=True)
    window = MainWindow(path_chooser=lambda: target, settings=_settings(tmp_path))
    qtbot.addWidget(window)
    window.show()
    window._install_session(read_only)

    window.action_save_as.trigger()

    assert window.session is not None
    assert window.session.root == target.resolve()
    assert not window.session.read_only
    assert (target / "project.json").is_file()
    assert window.action_save_as.shortcut().toString() == "Ctrl+Shift+S"
    owner.close()


def test_multi_selection_inspector_commits_all_common_edits_in_one_revision(
    qtbot, tmp_path
) -> None:
    window = MainWindow(
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()
    assert window.session is not None
    diagram = window.session.authority.snapshot().documents[0]
    first = window.session.client.insert_drakon_atom(diagram.id, "assignment", 0)
    second = window.session.client.insert_drakon_atom(diagram.id, "assignment", 1)
    assert isinstance(first, CommandAccepted)
    assert isinstance(second, CommandAccepted)
    qtbot.waitUntil(lambda: len(window.session.authority.snapshot().documents[0].body.atoms) == 2)
    document = window.documents.currentWidget()
    assert isinstance(document, UnifiedDocumentWidget)
    atom_ids = tuple(
        atom.id for atom in window.session.authority.snapshot().documents[0].body.atoms
    )
    qtbot.waitUntil(
        lambda: (
            document.canvas.layout_scene is not None
            and all(
                any(node.object_id == atom_id for node in document.canvas.layout_scene.nodes)
                for atom_id in atom_ids
            )
        )
    )
    document.canvas.select_atoms(atom_ids)
    assert document.canvas.selected_atom_ids() == atom_ids
    assert "2 operations selected" in window.inspector.purpose.text()
    revision = window.session.authority.revision
    window.inspector.properties.item(0, 1).setText("shared_value")
    qtbot.mouseClick(window.inspector.apply_button, Qt.MouseButton.LeftButton)

    assert window.session.authority.revision == revision + 1
    atoms = window.session.authority.snapshot().documents[0].body.atoms
    assert all(isinstance(atom, Assignment) for atom in atoms)
    assert [atom.target for atom in atoms] == ["shared_value", "shared_value"]


def test_drakon_delete_previews_owned_impact_and_cancel_preserves_revision(
    qtbot, tmp_path, monkeypatch
) -> None:
    window = MainWindow(
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()
    assert window.session is not None
    window._insert_atom("if")
    diagram = window.session.authority.snapshot().documents[0]
    decision = diagram.body.atoms[0]
    assert isinstance(decision, If)
    summary, can_unwrap = window._drakon_delete_preview((decision,))
    assert "owned operations" in summary
    assert "spliced" in summary
    assert can_unwrap
    document = window.documents.currentWidget()
    assert isinstance(document, UnifiedDocumentWidget)
    document.canvas.select_atom(decision.id)
    revision = window.session.authority.revision
    monkeypatch.setattr(
        window,
        "_preview_drakon_delete",
        lambda _atoms: DrakonDeleteChoice.CANCEL,
    )

    window.action_delete.trigger()

    assert window.session.authority.revision == revision
    assert isinstance(window.session.authority.snapshot().documents[0].body.atoms[0], If)


def test_keyboard_target_insertion_reorder_and_tidy_use_semantic_structure(qtbot, tmp_path) -> None:
    window = MainWindow(
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()
    assert window.session is not None
    window._insert_atom("if")
    project = window.session.authority.snapshot()
    diagram = project.documents[0]
    decision = diagram.body.atoms[0]
    assert isinstance(decision, If)
    document = window.documents.currentWidget()
    assert isinstance(document, UnifiedDocumentWidget)

    scene = document.canvas.layout_scene
    assert scene is not None
    routes = scene.insertion_routes()
    for _route in routes:
        boundary = document.canvas.cycle_insertion_target()
        if boundary is not None and (
            boundary.sequence_id,
            boundary.index,
        ) == (decision.false_branch.id, 0):
            break
    else:
        raise AssertionError("False-branch insertion target was not keyboard reachable")
    window._insert_atom("output")

    updated = window.session.authority.snapshot().documents[0]
    updated_decision = updated.body.atoms[0]
    assert isinstance(updated_decision, If)
    assert updated_decision.false_branch.atoms[0].expression == "'output'"
    assert len(updated.body.atoms) == 1

    document.canvas.select_atom(updated_decision.id)
    for _ in range(2):
        window._insert_atom("action")
    root_atoms = window.session.authority.snapshot().documents[0].body.atoms
    first_action, second_action = root_atoms[-2:]
    document.canvas.select_atom(second_action.id)
    revision = window.session.authority.revision
    window.action_move_up.trigger()
    reordered = window.session.authority.snapshot().documents[0].body.atoms
    assert [atom.id for atom in reordered[-2:]] == [second_action.id, first_action.id]
    assert window.session.authority.revision == revision + 1
    tidy_revision = window.session.authority.revision
    window.action_tidy_diagram.trigger()
    assert window.session.authority.revision == tidy_revision


def test_context_sensitive_shapes_disable_invalid_transfers_and_explain_why(
    qtbot, tmp_path
) -> None:
    window = MainWindow(
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()

    break_item = next(
        window.shape_list.item(row)
        for row in range(window.shape_list.count())
        if window.shape_list.item(row).data(Qt.ItemDataRole.UserRole) == "break"
    )
    assert not break_item.flags() & Qt.ItemFlag.ItemIsEnabled
    assert "inside a loop body" in break_item.toolTip()
    break_command = window.command_registry.get("drakon.insert_break")
    assert not break_command.is_enabled()
    assert "inside a loop body" in break_command.disabled_reason()

    window._insert_atom("while_loop")
    assert window.session is not None
    loop = window.session.authority.snapshot().documents[0].body.atoms[0]
    assert isinstance(loop, Loop)
    document = window.documents.currentWidget()
    assert isinstance(document, UnifiedDocumentWidget)
    document.canvas.select_atom(loop.body.atoms[0].id)
    assert break_item.flags() & Qt.ItemFlag.ItemIsEnabled
    assert break_command.is_enabled()

    scene = document.canvas.layout_scene
    assert scene is not None
    for _route in scene.insertion_routes():
        boundary = document.canvas.cycle_insertion_target()
        if boundary is not None and boundary.sequence_id == loop.else_body.id:
            break
    else:
        raise AssertionError("Loop else insertion target was not reachable")
    assert not break_item.flags() & Qt.ItemFlag.ItemIsEnabled


def test_visible_convert_statement_action_preserves_selection_and_undo(qtbot, tmp_path) -> None:
    window = MainWindow(
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()
    window._insert_atom("action")
    assert window.session is not None
    document = window.documents.currentWidget()
    assert isinstance(document, UnifiedDocumentWidget)
    atom = window.session.authority.snapshot().documents[0].body.atoms[0]
    document.canvas.select_atom(atom.id)
    command = window.command_registry.get("drakon.convert_statement")
    assert command.is_enabled()

    window.action_convert_statement.trigger()

    converted = window.session.authority.snapshot().documents[0].body.atoms[0]
    assert isinstance(converted, Output)
    assert converted.id == atom.id
    assert converted.expression == "'action'"
    window.action_undo.trigger()
    assert window.session.authority.snapshot().documents[0].body.atoms[0] == atom


def test_dirty_close_discard_closes_cancel_stays_and_unchanged_needs_no_prompt(
    qtbot, tmp_path
) -> None:
    decisions: list[str] = []

    def discard(_session) -> CloseDecision:
        decisions.append("discard")
        return CloseDecision.DISCARD

    dirty = MainWindow(close_decision=discard, settings=_settings(tmp_path))
    qtbot.addWidget(dirty)
    dirty.show()
    dirty.action_new.trigger()
    document = dirty.documents.currentWidget()
    assert isinstance(document, UnifiedDocumentWidget)
    document.insert_hello_world()

    assert dirty.close()
    assert decisions == ["discard"]

    cancel = MainWindow(
        close_decision=lambda _session: CloseDecision.CANCEL,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(cancel)
    cancel.show()
    cancel.action_new.trigger()
    current = cancel.documents.currentWidget()
    assert isinstance(current, UnifiedDocumentWidget)
    current.insert_hello_world()
    assert not cancel.close()
    assert cancel.isVisible()

    calls = 0

    def should_not_run(_session) -> CloseDecision:
        nonlocal calls
        calls += 1
        return CloseDecision.CANCEL

    unchanged = MainWindow(
        close_decision=should_not_run,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(unchanged)
    unchanged.show()
    unchanged.action_new.trigger()
    assert unchanged.close()
    assert calls == 0


def test_real_unsaved_dialog_discard_closes_instead_of_falling_through_to_cancel(
    qtbot, tmp_path
) -> None:
    window = MainWindow(settings=_settings(tmp_path))
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()
    document = window.documents.currentWidget()
    assert isinstance(document, UnifiedDocumentWidget)
    document.insert_hello_world()

    def click_discard() -> None:
        modal = QApplication.activeModalWidget()
        if not isinstance(modal, QMessageBox):
            QTimer.singleShot(1, click_discard)
            return
        button = modal.button(QMessageBox.StandardButton.Discard)
        assert button is not None
        button.click()

    QTimer.singleShot(0, click_discard)
    assert window.close()
    assert not window.isVisible()


def test_command_palette_inserts_complete_if_with_keyboard_only(qtbot, tmp_path) -> None:
    window = MainWindow(
        settings=_settings(tmp_path),
        close_decision=lambda _session: CloseDecision.DISCARD,
    )
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()

    palette = CommandPalette(window.command_registry, window)
    qtbot.addWidget(palette)
    palette.show()
    qtbot.wait(1)
    qtbot.keyClicks(palette.query, "insert if")
    qtbot.keyClick(palette.query, Qt.Key.Key_Return)

    assert window.session is not None
    diagram = window.session.authority.snapshot().documents[0]
    decision = diagram.body.atoms[0]
    assert isinstance(decision, If)
    assert decision.condition == "True"
    assert decision.true_branch.atoms[0].source == "print('true branch action')"
    assert decision.false_branch.atoms[0].source == "print('false branch action')"
    document = window.documents.currentWidget()
    assert isinstance(document, UnifiedDocumentWidget)
    qtbot.waitUntil(lambda: "if True:" in document.code.toPlainText(), timeout=10000)
    assert "if True:" in document.code.toPlainText()


def test_command_palette_wraps_selected_block_and_global_undo_restores_it(qtbot, tmp_path) -> None:
    window = MainWindow(
        settings=_settings(tmp_path),
        close_decision=lambda _session: CloseDecision.DISCARD,
    )
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()
    document = window.documents.currentWidget()
    assert isinstance(document, UnifiedDocumentWidget)
    output_item = next(
        window.shape_list.item(row)
        for row in range(window.shape_list.count())
        if window.shape_list.item(row).data(Qt.ItemDataRole.UserRole) == "output"
    )
    for _ in range(2):
        qtbot.mouseClick(
            window.shape_list.viewport(),
            Qt.MouseButton.LeftButton,
            pos=window.shape_list.visualItemRect(output_item).center(),
        )
    assert window.session is not None
    diagram = window.session.authority.snapshot().documents[0]
    first, second = diagram.body.atoms
    scene = document.canvas.layout_scene
    assert scene is not None

    def position(atom_id: str):
        node = next(item for item in scene.nodes if item.object_id == atom_id)
        return document.canvas.mapFromScene(QPointF(node.bounds.center.x, node.bounds.center.y))

    qtbot.mouseClick(
        document.canvas.viewport(),
        Qt.MouseButton.LeftButton,
        pos=position(first.id),
    )
    qtbot.mouseClick(
        document.canvas.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        pos=position(second.id),
    )

    palette = CommandPalette(window.command_registry, window)
    qtbot.addWidget(palette)
    palette.show()
    qtbot.keyClicks(palette.query, "wrap selection in if")
    qtbot.keyClick(palette.query, Qt.Key.Key_Return)

    wrapped = window.session.authority.snapshot().documents[0].body.atoms
    assert len(wrapped) == 1
    assert isinstance(wrapped[0], If)
    assert window.action_undo.shortcut().toString() == "Ctrl+Z"
    window.action_undo.trigger()
    qtbot.waitUntil(
        lambda: len(window.session.authority.snapshot().documents[0].body.atoms) == 2,
        timeout=2000,
    )


def test_dirty_close_save_uses_normal_project_path(qtbot, tmp_path) -> None:
    root = tmp_path / "saved-on-close"
    window = MainWindow(
        path_chooser=lambda: root,
        close_decision=lambda _session: CloseDecision.SAVE,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()
    document = window.documents.currentWidget()
    assert isinstance(document, UnifiedDocumentWidget)
    document.insert_hello_world()

    assert window.close()
    assert (root / "project.json").is_file()


def test_failed_close_save_can_write_recovery_copy(qtbot, tmp_path) -> None:
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("blocks directory creation", encoding="utf-8")
    recovery = tmp_path / "recovery-copy"
    failures: list[str] = []

    def choose_recovery(_session, error: Exception) -> SaveFailureDecision:
        failures.append(str(error))
        return SaveFailureDecision.RECOVERY_COPY

    window = MainWindow(
        path_chooser=lambda: blocked,
        recovery_path_chooser=lambda: recovery,
        close_decision=lambda _session: CloseDecision.SAVE,
        save_failure_decision=choose_recovery,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()
    document = window.documents.currentWidget()
    assert isinstance(document, UnifiedDocumentWidget)
    document.insert_hello_world()

    assert window.close()
    assert failures
    recovered = ProjectSession.open(recovery)
    try:
        assert recovered.authority.snapshot().revision == 1
        assert recovered.authority.snapshot().title == "Untitled Project"
    finally:
        recovered.close()


def test_failed_close_save_cancel_preserves_open_project(qtbot, tmp_path) -> None:
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("blocks directory creation", encoding="utf-8")
    window = MainWindow(
        path_chooser=lambda: blocked,
        close_decision=lambda _session: CloseDecision.SAVE,
        save_failure_decision=lambda _session, _error: SaveFailureDecision.CANCEL_CLOSE,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()
    document = window.documents.currentWidget()
    assert isinstance(document, UnifiedDocumentWidget)
    document.insert_hello_world()
    expected = window.session.authority.snapshot() if window.session else None

    assert not window.close()
    assert window.isVisible()
    assert window.session is not None
    assert window.session.authority.snapshot() == expected


def test_complete_documents_detach_compare_run_and_dock_without_state_loss(qtbot, tmp_path) -> None:
    window = MainWindow(
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window._open_example("python_modules")
    assert window.documents.count() == 2

    first = window.documents.widget(0)
    second = window.documents.widget(1)
    assert isinstance(first, UnifiedDocumentWidget)
    assert isinstance(second, UnifiedDocumentWidget)
    first.set_layout_mode("code")
    first.code.verticalScrollBar().setValue(1)
    first_scroll = first.code.verticalScrollBar().value()
    window.documents.setCurrentWidget(first)
    window.action_detach_document.trigger()
    first_window = window._detached_documents[first.diagram_id]
    qtbot.addWidget(first_window)
    assert first_window.centralWidget() is first
    assert first.layout_mode == "code"

    window.documents.setCurrentWidget(second)
    window.action_detach_document.trigger()
    second_window = window._detached_documents[second.diagram_id]
    qtbot.addWidget(second_window)
    second.set_layout_mode("diagram")
    assert second_window.centralWidget() is second
    assert window.documents.count() == 0

    first_window.action_run.trigger()
    qtbot.waitUntil(lambda: "Hello from two modules!" in first.console.toPlainText())
    first_window.action_trace.trigger()
    qtbot.waitUntil(first.trace_button.isEnabled)
    assert "mapped trace" in first.console.toPlainText()

    assert first_window.close()
    qtbot.waitUntil(lambda: window.documents.indexOf(first) >= 0)
    assert window.documents.currentWidget() is first
    assert first.layout_mode == "code"
    assert first.code.verticalScrollBar().value() == first_scroll
    assert second_window.close()
    qtbot.waitUntil(lambda: window.documents.indexOf(second) >= 0)
    assert window.documents.count() == 2
    assert window.documents.widget(window.documents.indexOf(second)) is second


def test_detached_view_menu_keeps_the_document_visible_across_every_layout(qtbot, tmp_path) -> None:
    window = MainWindow(
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window._open_example("silhouette")
    document = window.documents.currentWidget()
    assert isinstance(document, UnifiedDocumentWidget)

    window.action_detach_document.trigger()
    detached = window._detached_documents[document.diagram_id]
    qtbot.addWidget(detached)
    qtbot.waitUntil(lambda: detached.isVisible() and document.isVisible())
    assert detached.centralWidget() is document
    assert document._diagram_pane.isVisible()
    assert document.code.isVisible()

    detached.view_actions["diagram"].trigger()
    qtbot.waitUntil(lambda: document._diagram_pane.isVisible() and not document.code.isVisible())
    assert document.isVisible()
    assert detached.view_actions["diagram"].isChecked()
    document.canvas.scale(2.0, 2.0)
    zoomed_scale = document.canvas.transform().m11()
    detached.action_fit.trigger()
    assert document.canvas.transform().m11() != zoomed_scale

    detached.view_actions["code"].trigger()
    qtbot.waitUntil(lambda: not document._diagram_pane.isVisible() and document.code.isVisible())
    assert document.isVisible()
    assert detached.view_actions["code"].isChecked()

    detached.view_actions["stacked"].trigger()
    qtbot.waitUntil(lambda: document._diagram_pane.isVisible() and document.code.isVisible())
    assert document._comparison.orientation() is Qt.Orientation.Vertical

    detached.view_actions["tabbed"].trigger()
    assert document._inner_tabs is not None
    qtbot.waitUntil(document._inner_tabs.isVisible)
    assert document._inner_tabs.count() == 2
    document._inner_tabs.setCurrentWidget(document._diagram_pane)
    qtbot.waitUntil(document._diagram_pane.isVisible)
    document._inner_tabs.setCurrentWidget(document.code)
    qtbot.waitUntil(document.code.isVisible)

    detached.view_actions["side_by_side"].trigger()
    qtbot.waitUntil(lambda: document._diagram_pane.isVisible() and document.code.isVisible())
    assert document._comparison.orientation() is Qt.Orientation.Horizontal
    assert detached.view_actions["side_by_side"].isChecked()
    assert sum(action.isChecked() for action in detached.view_actions.values()) == 1

    assert detached.close()
    qtbot.waitUntil(lambda: window.documents.indexOf(document) >= 0)
    assert window.documents.currentWidget() is document
    assert document.isVisible()
    assert document._diagram_pane.isVisible()
    assert document.code.isVisible()


def test_live_agent_edit_and_proposal_are_visible_in_the_open_gui(qtbot, tmp_path) -> None:
    window = MainWindow(
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()
    assert window.session is not None
    assert window._automation_host is not None
    diagram = window.session.authority.snapshot().documents[0]

    async def agent_work() -> None:
        assert window._automation_host is not None
        async with AsyncRemoteClient(
            window._automation_host.endpoint,
            window._automation_host.token,
            actor_id="gui-collaborator",
        ) as agent:
            await agent.subscribe()
            result = await agent.submit(
                InsertDrakonAtom(
                    diagram.id,
                    "action",
                    0,
                    source='print("visible agent edit")',
                ),
                operation_id="gui-agent-edit",
            )
            assert isinstance(result, CommandAccepted)

        async with AsyncRemoteClient(
            window._automation_host.endpoint,
            window._automation_host.token,
            actor_id="proposal-agent",
            mode=AccessMode.PROPOSAL,
        ) as planner:
            await planner.propose(
                RenameProject("Reviewed Agent Title"),
                operation_id="gui-title-proposal",
                intent="Use a descriptive project title",
            )

    asyncio.run(agent_work())
    document = window.documents.currentWidget()
    assert isinstance(document, UnifiedDocumentWidget)
    qtbot.waitUntil(lambda: "visible agent edit" in document.code.toPlainText(), timeout=3000)
    qtbot.waitUntil(lambda: window.collaboration.proposals.topLevelItemCount() == 1)
    assert any(
        window.collaboration.actors.topLevelItem(row).text(0) == "gui-collaborator"
        for row in range(window.collaboration.actors.topLevelItemCount())
    )
    proposal = window.collaboration.proposals.topLevelItem(0)
    proposal.setSelected(True)
    qtbot.mouseClick(window.collaboration.accept_proposal, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: (
            window.session is not None
            and window.session.authority.snapshot().title == "Reviewed Agent Title"
            and window.project_tree.topLevelItem(0).text(0) == "Reviewed Agent Title"
        )
    )


def test_stop_button_terminates_a_nonterminating_live_run(qtbot, tmp_path) -> None:
    window = MainWindow(
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()
    assert window.session is not None
    diagram = window.session.authority.snapshot().documents[0]
    result = window.session.client.insert_drakon_atom(diagram.id, "while_loop", 0)
    assert isinstance(result, CommandAccepted)
    assert isinstance(
        window.session.client.set_drakon_text(
            diagram.id,
            result.affected_ids[0],
            "condition",
            "True",
        ),
        CommandAccepted,
    )
    document = window.documents.currentWidget()
    assert isinstance(document, UnifiedDocumentWidget)
    document.refresh(window.session.authority.snapshot())

    qtbot.mouseClick(document.run_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(document.stop_button.isEnabled)
    # Stop also cancels preparation; this test exercises the live runner.
    qtbot.waitUntil(lambda: document._run_session.is_active)
    qtbot.mouseClick(document.stop_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: "stopped by the user" in document.console.toPlainText())
    assert document.run_button.isEnabled()
    assert not document.stop_button.isEnabled()


def test_stop_action_terminates_a_nonterminating_full_project_run(qtbot, tmp_path) -> None:
    root = tmp_path / "stoppable-project"
    window = MainWindow(path_chooser=lambda: root, settings=_settings(tmp_path))
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()
    assert window.session is not None
    diagram = window.session.authority.snapshot().documents[0]
    inserted = window.session.client.insert_drakon_atom(
        diagram.id,
        "while_loop",
        0,
    )
    assert isinstance(inserted, CommandAccepted)
    window.session.client.set_drakon_text(
        diagram.id,
        inserted.affected_ids[0],
        "condition",
        "True",
    )
    window.action_save.trigger()
    window.action_generate.trigger()
    qtbot.waitUntil(lambda: window.development.reveal_button.isEnabled())

    window.action_run.trigger()
    qtbot.waitUntil(lambda: window._project_run_session.is_active)
    window.action_stop_current.trigger()

    qtbot.waitUntil(lambda: "stopped by the user" in window.run_output.toPlainText())
    assert not window._project_run_session.is_active
