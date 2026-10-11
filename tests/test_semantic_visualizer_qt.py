from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QGraphicsRectItem

from code_visualizer.domain.freeform import FreeformDiagram, ShapeObject
from code_visualizer.domain.mindmap import MindMapDiagram
from code_visualizer.domain.projection import ProjectionLayout
from code_visualizer.domain.semantic import (
    ProjectionEdge,
    ProjectionKind,
    ProjectionNode,
    SemanticObjectKind,
    SemanticProjection,
    SemanticRelationKind,
)
from code_visualizer.execution import (
    DebugEvent,
    DebugState,
    RuntimeBinding,
    RuntimeChild,
    RuntimeGraph,
    RuntimeValue,
    RuntimeValueKind,
)
from code_visualizer.ui_qt.features.semantic_visualizer.composer import (
    ProjectionComposerDialog,
)
from code_visualizer.ui_qt.features.semantic_visualizer.widget import (
    SemanticVisualizerWidget,
)
from code_visualizer.ui_qt.freeform_document import FreeformDocumentWidget
from code_visualizer.ui_qt.main_window import CloseDecision, MainWindow
from code_visualizer.ui_qt.mindmap_document import MindMapDocumentWidget


def _settings(path: Path) -> QSettings:
    return QSettings(str(path / "settings.ini"), QSettings.Format.IniFormat)


def test_code_visualizer_is_a_live_projection_with_shared_selection(qtbot, tmp_path) -> None:
    window = MainWindow(
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()
    assert window.session is not None

    visualizer = window.semantic_visualizer
    assert window.visualizer_dock.isVisible()
    assert visualizer._projection is not None
    assert visualizer._projection.kind is ProjectionKind.ARCHITECTURE
    selectable = [
        item
        for item in visualizer.scene.items()
        if isinstance(item, QGraphicsRectItem) and bool(item.flags())
    ]
    assert selectable

    selectable[0].setSelected(True)
    qtbot.waitUntil(lambda: window.session.kernel.selection.state.primary is not None)
    selected = window.session.kernel.selection.state
    assert selected.source == "ui.semantic_visualizer"
    assert selected.primary in {item.semantic_id for item in visualizer._projection.nodes}

    control_index = visualizer.projection_choice.findData(ProjectionKind.CONTROL.value)
    visualizer.projection_choice.setCurrentIndex(control_index)
    qtbot.waitUntil(
        lambda: (
            visualizer._projection is not None
            and visualizer._projection.kind is ProjectionKind.CONTROL
        )
    )
    assert visualizer.status.text().startswith("Revision 0")

    main = window.session.authority.snapshot().documents[0]
    runtime_graph = RuntimeGraph(
        "execution_test",
        0,
        0,
        3,
        "frame_main",
        (RuntimeBinding("answer", "value_42", True),),
        (RuntimeValue("value_42", "builtins.int", RuntimeValueKind.SCALAR, "42", 42),),
    )
    window.session.kernel.runtime.record(
        DebugEvent(
            3,
            "paused",
            DebugState.PAUSED,
            execution_session_id="execution_test",
            runtime_graph=runtime_graph,
        ),
        main.id,
    )
    runtime_index = visualizer.projection_choice.findData(ProjectionKind.RUNTIME.value)
    visualizer.projection_choice.setCurrentIndex(runtime_index)
    qtbot.waitUntil(
        lambda: (
            visualizer._projection is not None
            and visualizer._projection.kind is ProjectionKind.RUNTIME
        )
    )
    assert "answer" in {item.label for item in visualizer._projection.nodes}
    assert "42" in {item.label for item in visualizer._projection.nodes}
    window.close()


def test_human_can_link_mindmap_and_freeform_glyphs_to_selected_code(qtbot, tmp_path) -> None:
    window = MainWindow(
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()
    assert window.session is not None
    main = window.session.authority.snapshot().documents[0]
    window.session.client.insert_drakon_atom(main.id, "output", 0, source='"linked"')
    operation_id = window.session.authority.snapshot().documents[0].body.atoms[0].id

    window.action_new_mind_map.trigger()
    mind_editor = window.documents.currentWidget()
    assert isinstance(mind_editor, MindMapDocumentWidget)
    window.session.kernel.selection.select(
        (operation_id,),
        revision=window.session.authority.revision,
        source="test.code",
    )
    assert mind_editor.link_semantic_button.isEnabled()
    qtbot.mouseClick(mind_editor.link_semantic_button, Qt.MouseButton.LeftButton)
    mindmap = window.session.authority.snapshot().documents[-1]
    assert isinstance(mindmap, MindMapDiagram)
    assert mindmap.root.semantic_id == operation_id

    window.action_new_freeform.trigger()
    free_editor = window.documents.currentWidget()
    assert isinstance(free_editor, FreeformDocumentWidget)
    qtbot.mouseClick(free_editor.add_shape_button, Qt.MouseButton.LeftButton)
    freeform = window.session.authority.snapshot().documents[-1]
    assert isinstance(freeform, FreeformDiagram)
    shape = next(item for item in freeform.objects if isinstance(item, ShapeObject))
    free_editor.canvas.select_objects((shape.id,))
    window.session.kernel.selection.select(
        (operation_id,),
        revision=window.session.authority.revision,
        source="test.code",
    )
    assert free_editor.link_semantic_button.isEnabled()
    qtbot.mouseClick(free_editor.link_semantic_button, Qt.MouseButton.LeftButton)
    freeform = window.session.authority.snapshot().documents[-1]
    assert isinstance(freeform, FreeformDiagram)
    linked_shape = next(item for item in freeform.objects if item.id == shape.id)
    assert isinstance(linked_shape, ShapeObject)
    assert linked_shape.semantic_id == operation_id
    window.close()


def test_runtime_timeline_and_data_structure_adapter_are_live_controls(qtbot, tmp_path) -> None:
    window = MainWindow(
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()
    assert window.session is not None
    diagram = window.session.authority.snapshot().documents[0]
    visualizer = window.semantic_visualizer

    def graph(sequence: int, value: int) -> RuntimeGraph:
        return RuntimeGraph(
            "execution_timeline",
            0,
            0,
            sequence,
            "frame_main",
            (RuntimeBinding("frontier_queue", "queue", True),),
            (
                RuntimeValue(
                    "queue",
                    "builtins.list",
                    RuntimeValueKind.SEQUENCE,
                    f"[{value}]",
                    children=(RuntimeChild("0", f"value_{value}"),),
                ),
                RuntimeValue(
                    f"value_{value}",
                    "builtins.int",
                    RuntimeValueKind.SCALAR,
                    str(value),
                    value,
                ),
            ),
            history_index=sequence,
            checkpoint=True,
        )

    for sequence, value in ((1, 10), (2, 20)):
        window.session.kernel.runtime.record(
            DebugEvent(
                sequence,
                "paused",
                DebugState.PAUSED,
                execution_session_id="execution_timeline",
                runtime_graph=graph(sequence, value),
            ),
            diagram.id,
        )
    visualizer.projection_choice.setCurrentIndex(
        visualizer.projection_choice.findData(ProjectionKind.RUNTIME.value)
    )
    qtbot.waitUntil(lambda: visualizer.runtime_controls.isVisible())
    assert visualizer.runtime_history_slider.maximum() == 1
    assert visualizer.runtime_history_label.text().startswith("Live 2/2")
    assert visualizer._projection is not None
    assert "20" in {item.label for item in visualizer._projection.nodes}
    assert visualizer._projection.definition_id == "runtime:queue"

    qtbot.mouseClick(visualizer.runtime_previous_button, Qt.MouseButton.LeftButton)
    assert visualizer.runtime_history_label.text().startswith("History 1/2")
    assert visualizer._projection is not None
    assert "10" in {item.label for item in visualizer._projection.nodes}
    qtbot.mouseClick(visualizer.runtime_live_button, Qt.MouseButton.LeftButton)
    assert visualizer.runtime_history_label.text().startswith("Live 2/2")

    list_index = visualizer.runtime_adapter_choice.findData("list")
    visualizer.runtime_adapter_choice.setCurrentIndex(list_index)
    assert visualizer._projection is not None
    assert visualizer._projection.definition_id == "runtime:list"
    assert visualizer._projection.layout == "horizontal"
    window.close()


def test_no_code_lens_composer_and_materialized_mind_map_are_authority_clients(
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
    visualizer = window.semantic_visualizer
    assert visualizer.new_lens_button.isEnabled()
    assert visualizer.mind_map_button.isEnabled()
    command_ids = {item.id for item in window.command_registry.all()}
    assert {
        "visualizer.compose_lens",
        "visualizer.group_concept",
        "visualizer.relate_selection",
        "visualizer.make_mind_map",
        "visualizer.make_canvas",
        "visualizer.show_semantic_text",
        "visualizer.show_runtime",
    } <= command_ids

    composer = ProjectionComposerDialog(window.session.kernel.queries.program.objects)
    qtbot.addWidget(composer)
    composer.title_edit.setText("Human-composed lens")
    composer.layout_choice.setCurrentIndex(
        composer.layout_choice.findData(ProjectionLayout.RADIAL.value)
    )
    definition = composer.definition()
    assert definition.title == "Human-composed lens"
    assert definition.layout is ProjectionLayout.RADIAL

    document_count = len(window.session.authority.snapshot().documents)
    qtbot.mouseClick(visualizer.mind_map_button, Qt.MouseButton.LeftButton)
    project = window.session.authority.snapshot()
    assert len(project.documents) == document_count + 1
    created = project.documents[-1]
    assert isinstance(created, MindMapDiagram)
    assert any(topic.semantic_id is not None for topic in created.root.children)
    assert isinstance(window.documents.currentWidget(), MindMapDocumentWidget)
    window.close()


def test_semantic_nodes_wrap_long_text_inside_nonoverlapping_bounds(qtbot) -> None:
    visualizer = SemanticVisualizerWidget()
    qtbot.addWidget(visualizer)
    long_label = "qualified::" + "very_long_programmer_intent_" * 12
    projection = SemanticProjection(
        ProjectionKind.COMPOSED,
        "project_text_bounds",
        1,
        None,
        (
            ProjectionNode(
                "node_a",
                "semantic_a",
                SemanticObjectKind.CONCEPT,
                long_label,
                "A detailed explanation " * 30,
                badges=("concept", "anchor state", "another long semantic badge"),
            ),
            ProjectionNode(
                "node_b",
                "semantic_b",
                SemanticObjectKind.FUNCTION,
                long_label,
                "Another detailed explanation " * 30,
            ),
        ),
        (),
        "projection_bounds",
        "Long text bounds",
    )
    visualizer._render(projection)
    rectangles = [
        item
        for item in visualizer.scene.items()
        if isinstance(item, QGraphicsRectItem) and item.data(10_202) is not None
    ]
    assert len(rectangles) == 2
    for rectangle in rectangles:
        bounds = rectangle.sceneBoundingRect().adjusted(-1, -1, 1, 1)
        assert all(bounds.contains(child.sceneBoundingRect()) for child in rectangle.childItems())
    assert not rectangles[0].sceneBoundingRect().intersects(rectangles[1].sceneBoundingRect())


def test_scene_reconciler_preserves_item_identity_for_runtime_only_updates(qtbot) -> None:
    visualizer = SemanticVisualizerWidget()
    qtbot.addWidget(visualizer)
    nodes = (
        ProjectionNode("node_a", "semantic_a", SemanticObjectKind.OPERATION, "Start"),
        ProjectionNode("node_b", "semantic_b", SemanticObjectKind.OPERATION, "Finish"),
    )
    first = SemanticProjection(
        ProjectionKind.CONTROL,
        "project_reconcile",
        1,
        "semantic_a",
        nodes,
        (
            ProjectionEdge(
                "edge_a_b",
                "node_a",
                "node_b",
                SemanticRelationKind.CONTROL_FLOW,
            ),
        ),
        "projection_reconcile",
        "Reconcile",
    )
    visualizer._render(first)
    node_item = visualizer._scene_reconciler.node_items["node_a"]
    edge_item = visualizer._scene_reconciler.edge_items["edge_a_b"]
    original_position = node_item.pos()
    node_item.setSelected(True)

    second = replace(
        first,
        nodes=(replace(nodes[0], detail="runtime value = 42", badges=("active",)), nodes[1]),
        edges=(replace(first.edges[0], active=True),),
    )
    visualizer._render(second)

    assert visualizer._scene_reconciler.node_items["node_a"] is node_item
    assert visualizer._scene_reconciler.edge_items["edge_a_b"] is edge_item
    assert node_item.pos() == original_position
    assert node_item.isSelected()
    assert node_item.data(10_203) is True
    assert edge_item.data(10_203) is True
