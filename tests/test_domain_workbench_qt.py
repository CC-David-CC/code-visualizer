from pathlib import Path

from PySide6.QtCore import QPoint, QRectF, QSettings, Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QInputDialog, QLineEdit, QPushButton

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.domain_commands import PutDomainSchema
from code_visualizer.application.domain_index import domain_relation_id
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.intentional import DomainSchema
from code_visualizer.domain.notation import NotationKind
from code_visualizer.domain.program import ProgramModule
from code_visualizer.domain.python_declarations import parse_python_declarations
from code_visualizer.domain.semantic import ProjectionEdge, SemanticRelationKind
from code_visualizer.extensions.fsm import traffic_light_project
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.ui_qt.features.domain_workbench.editors import (
    NodeDialog,
    PropertyDialog,
    SchemaDialog,
)
from code_visualizer.ui_qt.features.semantic_visualizer.scene_reconciler import ProjectionEdgeItem
from code_visualizer.ui_qt.main_window import CloseDecision, MainWindow


def _window(qtbot, path: Path):
    authority = ProjectAuthority(traffic_light_project())
    client = CodeVisualizerClient(authority, actor_id="domain-qt-test")
    session = ProjectSession(authority, client, None, 0)
    window = MainWindow(
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=QSettings(str(path / "settings.ini"), QSettings.Format.IniFormat),
    )
    qtbot.addWidget(window)
    window.show()
    window._install_session(session)
    window._show_domain_workbench()
    return window, session


def test_table_pointer_edit_renames_state_in_all_views_and_undo_restores_identity(qtbot, tmp_path):
    window, session = _window(qtbot, tmp_path)
    workbench = window.domain_workbench
    workbench.tabs.setCurrentWidget(workbench.table)
    assert (
        workbench.notation_choice.currentData()
        == workbench.projections[NotationKind.TABLE].definition.id
    )
    qtbot.waitUntil(lambda: workbench.table.rowCount() == 3)
    before = session.authority.snapshot().domain_workspace
    source_cell = workbench.table.item(0, 1)
    assert source_cell is not None
    binding = source_cell.data(Qt.ItemDataRole.UserRole)
    assert binding.semantic_id == "traffic:red"
    workbench.table.scrollToItem(source_cell)
    rectangle = workbench.table.visualItemRect(source_cell)
    qtbot.mouseClick(workbench.table.viewport(), Qt.MouseButton.LeftButton, pos=rectangle.center())
    qtbot.keyClick(workbench.table, Qt.Key.Key_F2)
    editor = workbench.table.findChild(QLineEdit)
    assert editor is not None
    editor.selectAll()
    qtbot.keyClicks(editor, "Stop")
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: (
            session.authority.snapshot()
            .domain_workspace.node("traffic:red")
            .property("fsm:state:name")
            == "Stop"
        )
    )
    graph = workbench.projections[NotationKind.GRAPH].graph
    assert next(node for node in graph.nodes if node.id == "traffic:red").label == "Stop"
    assert workbench.projections[NotationKind.TABLE].rows[0].cells[0].text == "Stop"
    assert session.kernel.selection.state.primary == "traffic:red"
    before_refs = before.node("traffic:red-green").references
    assert (
        session.authority.snapshot().domain_workspace.node("traffic:red-green").references
        == before_refs
    )
    workbench.undo()
    assert session.authority.snapshot().domain_workspace == before
    window.close()


def test_graph_pointer_selection_form_edit_and_generated_source_use_shared_identity(
    qtbot, tmp_path
):
    window, session = _window(qtbot, tmp_path)
    workbench = window.domain_workbench
    workbench._fit()
    item = workbench.reconciler.node_items["traffic:green"]
    point = workbench.graph_view.mapFromScene(item.sceneBoundingRect().center())
    qtbot.mouseClick(workbench.graph_view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    qtbot.waitUntil(lambda: workbench.apply_button.isEnabled())
    field = workbench._properties["fsm:state:name"].control
    assert isinstance(field, QLineEdit)
    field.selectAll()
    qtbot.keyClicks(field, "Proceed")
    qtbot.mouseClick(workbench.apply_button, Qt.MouseButton.LeftButton)
    assert (
        session.authority.snapshot()
        .domain_workspace.node("traffic:green")
        .property("fsm:state:name")
        == "Proceed"
    )
    workbench.build_model()
    qtbot.waitUntil(lambda: workbench._generated is not None, timeout=10000)
    assert "Proceed" in workbench.code.toPlainText()
    assert "import importlib as _cv_importlib" not in workbench.code.toPlainText()
    assert workbench.code.isReadOnly()
    session.kernel.selection.select(("traffic:green",), source="test.domain_selection")
    assert workbench.code.extraSelections()
    window.close()


def test_generated_preview_switches_real_modules_by_semantic_identity(qtbot, tmp_path):
    window, session = _window(qtbot, tmp_path)
    workbench = window.domain_workbench
    declarations = parse_python_declarations("module:unrelated", "UNRELATED = 123")
    assert isinstance(
        session.client.put_program_module(
            ProgramModule("module:unrelated", "unrelated", declarations)
        ),
        CommandAccepted,
    )
    before = session.authority.snapshot()
    workbench.build_model()
    qtbot.waitUntil(lambda: workbench._generated is not None, timeout=10000)
    assert "Red" in workbench.code.toPlainText()
    assert "UNRELATED" not in workbench.code.toPlainText()
    execution = workbench._generated
    assert execution is not None
    assert {"app/unrelated.py", execution.launcher_path}.issubset(
        file.path for file in execution.files
    )
    assert "_cv_importlib" not in execution.file(execution.launcher_path).source

    session.kernel.selection.select((declarations[0].id,), source="test.module_selection")
    assert workbench.code.toPlainText().strip() == "UNRELATED = 123"
    assert workbench.code.extraSelections()
    session.kernel.selection.select(("traffic:red",), source="test.domain_selection")
    assert "Red" in workbench.code.toPlainText()
    assert "UNRELATED" not in workbench.code.toPlainText()
    assert workbench.code.extraSelections()
    assert workbench._generated is execution
    assert session.authority.snapshot() == before
    window.close()


def test_schema_dialog_creates_a_user_domain_without_json_or_bundle_knowledge(qtbot, tmp_path):
    window, session = _window(qtbot, tmp_path)
    dialog = SchemaDialog(parent=window)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.keyClicks(dialog.namespace, "example.library")

    def enter_concept():
        popup = QApplication.activeModalWidget()
        assert isinstance(popup, QInputDialog)
        popup.setTextValue("Book")
        popup.accept()

    QTimer.singleShot(0, enter_concept)
    add_concept = next(
        button for button in dialog.findChildren(QPushButton) if button.text() == "Add concept"
    )
    qtbot.mouseClick(add_concept, Qt.MouseButton.LeftButton)

    def enter_property():
        popup = QApplication.activeModalWidget()
        assert isinstance(popup, PropertyDialog)
        qtbot.keyClicks(popup.name, "Title")
        qtbot.mouseClick(
            popup.required, Qt.MouseButton.LeftButton, pos=QPoint(8, popup.required.height() // 2)
        )
        buttons = popup.findChild(QDialogButtonBox)
        qtbot.mouseClick(
            buttons.button(QDialogButtonBox.StandardButton.Ok), Qt.MouseButton.LeftButton
        )

    QTimer.singleShot(0, enter_property)
    add_property = next(
        button for button in dialog.findChildren(QPushButton) if button.text() == "Add property"
    )
    qtbot.mouseClick(add_property, Qt.MouseButton.LeftButton)
    buttons = dialog.findChild(QDialogButtonBox)
    assert buttons is not None
    qtbot.mouseClick(buttons.button(QDialogButtonBox.StandardButton.Ok), Qt.MouseButton.LeftButton)
    schema = dialog.schema()
    assert schema.concepts[0].name == "Book"
    assert schema.concepts[0].properties[0].name == "Title"
    assert schema.concepts[0].properties[0].required
    assert isinstance(session.client.submit(PutDomainSchema(schema)), CommandAccepted)
    window.domain_workbench.refresh()
    assert window.domain_workbench.schema_choice.findText("example.library") >= 0
    window.domain_workbench.schema_choice.setCurrentIndex(
        window.domain_workbench.schema_choice.findData(schema.id)
    )

    def name_model():
        popup = QApplication.activeModalWidget()
        assert isinstance(popup, QInputDialog)
        popup.setTextValue("Reading list")
        popup.accept()

    QTimer.singleShot(0, name_model)
    qtbot.mouseClick(
        window.domain_workbench.findChild(QPushButton, "newDomainModel"), Qt.MouseButton.LeftButton
    )

    def fill_book():
        popup = QApplication.activeModalWidget()
        assert isinstance(popup, NodeDialog)
        prop = schema.concepts[0].properties[0]
        editor = popup.properties[prop.id].control
        assert isinstance(editor, QLineEdit)
        qtbot.keyClicks(editor, "The First Book")
        buttons = popup.findChild(QDialogButtonBox)
        qtbot.mouseClick(
            buttons.button(QDialogButtonBox.StandardButton.Ok), Qt.MouseButton.LeftButton
        )

    QTimer.singleShot(0, fill_book)
    qtbot.mouseClick(window.domain_workbench.add_root_button, Qt.MouseButton.LeftButton)
    model = window.domain_workbench.current_model()
    assert model is not None
    assert len(model.nodes) == 1
    diagnostic_codes = {
        window.domain_workbench.diagnostics.topLevelItem(index).toolTip(0)
        for index in range(window.domain_workbench.diagnostics.topLevelItemCount())
    }
    assert diagnostic_codes == {issue.code for issue in session.kernel.workbench().diagnostics}
    assert diagnostic_codes
    window.close()
    assert model.nodes[0].property(schema.concepts[0].properties[0].id) == "The First Book"
    window.close()


def test_shift_drag_connects_canonical_nodes_through_schema_reference_intents(qtbot, tmp_path):
    window, session = _window(qtbot, tmp_path)
    workbench = window.domain_workbench
    workbench._fit()
    before = session.authority.snapshot().domain_workspace
    source = workbench.reconciler.node_items["traffic:red"]
    target = workbench.reconciler.node_items["traffic:yellow"]
    source_point = workbench.graph_view.mapFromScene(source.sceneBoundingRect().center())
    target_point = workbench.graph_view.mapFromScene(target.sceneBoundingRect().center())

    def accept_relationship():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, NodeDialog)
        assert dialog.references["fsm:transition:source"].target_ids() == ("traffic:red",)
        assert dialog.references["fsm:transition:target"].target_ids() == ("traffic:yellow",)
        dialog.references["fsm:transition:event"].item(0).setCheckState(Qt.CheckState.Checked)
        buttons = dialog.findChild(QDialogButtonBox)
        qtbot.mouseClick(
            buttons.button(QDialogButtonBox.StandardButton.Ok), Qt.MouseButton.LeftButton
        )

    qtbot.mousePress(
        workbench.graph_view.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        pos=source_point,
    )
    qtbot.mouseMove(workbench.graph_view.viewport(), target_point)
    QTimer.singleShot(0, accept_relationship)
    qtbot.mouseRelease(
        workbench.graph_view.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        pos=target_point,
    )
    after = session.authority.snapshot().domain_workspace
    additions = tuple(node for node in after.models[0].nodes if before.node(node.id) is None)
    assert len(additions) == 1
    relation = additions[0]
    assert relation.reference_ids("fsm:transition:source") == ("traffic:red",)
    assert relation.reference_ids("fsm:transition:target") == ("traffic:yellow",)
    assert relation.id in after.node("traffic:machine").child_ids("fsm:machine:transitions")
    assert relation.id in workbench.reconciler.edge_items
    workbench.undo()
    assert session.authority.snapshot().domain_workspace == before
    window.close()


def test_debug_pause_highlights_canonical_graph_table_and_generated_source(qtbot, tmp_path):
    window, session = _window(qtbot, tmp_path)
    workbench = window.domain_workbench
    before = session.authority.snapshot()
    workbench.debug_model()
    try:
        qtbot.waitUntil(
            lambda: (
                session.kernel.runtime.active is not None
                and session.kernel.runtime.active.status.value == "paused"
            ),
            timeout=10000,
        )
        for _ in range(35):
            state = session.kernel.runtime.active
            if "traffic:red" in state.active_ids:
                break
            sequence = state.event_sequence
            workbench.step_debug()
            qtbot.waitUntil(
                lambda sequence=sequence: session.kernel.runtime.active.event_sequence > sequence,
                timeout=10000,
            )
        state = session.kernel.runtime.active
        assert "traffic:red" in state.active_ids
        qtbot.waitUntil(
            lambda: (
                "active"
                in next(
                    node
                    for node in workbench.projections[NotationKind.GRAPH].graph.nodes
                    if node.id == "traffic:red"
                ).badges
            )
        )
        assert workbench.table.item(0, 1).background().color().name() == "#ffe4b5"
        machine = workbench.tree.topLevelItem(0)
        red = next(
            machine.child(index)
            for index in range(machine.childCount())
            if machine.child(index).data(0, Qt.ItemDataRole.UserRole) == "traffic:red"
        )
        assert red.background(0).color().name() == "#ffe4b5"
        assert workbench.code.extraSelections()
        assert "import importlib as _cv_importlib" not in workbench.code.toPlainText()
        assert any(
            "Red" in selection.cursor.selectedText()
            for selection in workbench.code.extraSelections()
        )
        assert session.authority.snapshot() == before
        assert session.authority.snapshot().program_model.functions == ()
    finally:
        workbench.stop_debug()
        window.close()


def test_graph_routes_self_loops_and_opposite_edges_without_overlap(qtbot):
    source, target = QRectF(0, 0, 100, 60), QRectF(280, 0, 100, 60)
    loop = ProjectionEdgeItem()
    loop.update_edge(
        ProjectionEdge("loop", "a", "a", SemanticRelationKind.REFERENCES), source, source
    )
    assert loop.path().boundingRect().right() > source.right()
    assert loop.path().boundingRect().top() < source.top()
    forward, reverse = ProjectionEdgeItem(), ProjectionEdgeItem()
    forward.update_edge(
        ProjectionEdge("forward", "a", "b", SemanticRelationKind.REFERENCES),
        source,
        target,
        lane_offset=-21,
    )
    reverse.update_edge(
        ProjectionEdge("reverse", "b", "a", SemanticRelationKind.REFERENCES),
        target,
        source,
        lane_offset=21,
    )
    assert forward.path().pointAtPercent(0.5).y() != reverse.path().pointAtPercent(0.5).y()
    assert forward.arrow_item.polygon().first() != reverse.arrow_item.polygon().first()


def test_semantic_reveal_selects_schema_definitions_by_stable_identity(qtbot, tmp_path):
    window, session = _window(qtbot, tmp_path)
    workbench = window.domain_workbench
    accepted = session.client.submit(
        PutDomainSchema(DomainSchema("other:schema", "example.other", "1"))
    )
    assert isinstance(accepted, CommandAccepted)
    before = session.authority.snapshot()
    for identifier in (
        "fsm:schema",
        "fsm:state",
        "fsm:state:name",
        "fsm:transition:source",
        "fsm:machine:states",
    ):
        workbench.schema_choice.setCurrentIndex(workbench.schema_choice.findData("other:schema"))
        workbench.tabs.setCurrentWidget(workbench.graph_view)
        window._reveal_semantic_id(identifier)
        assert workbench.current_schema().id == "fsm:schema"
        assert workbench.tabs.currentWidget() is workbench.definitions
        item = workbench.definitions.currentItem()
        assert item.data(0, Qt.ItemDataRole.UserRole) == identifier
        assert item.isSelected()
        assert session.kernel.selection.state.primary == identifier
    relation_id = domain_relation_id(SemanticRelationKind.CONTAINS, "fsm:state", "fsm:state:name")
    window._reveal_semantic_id(relation_id)
    assert workbench.definitions.currentItem().data(0, Qt.ItemDataRole.UserRole) == "fsm:state"
    assert session.authority.snapshot() == before
    window.close()
