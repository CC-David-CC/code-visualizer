from pathlib import Path

from PIL import Image
from PySide6.QtCore import QPointF, QSettings, Qt

from code_visualizer.domain.freeform import ConnectorObject, FreeformDiagram, ShapeObject
from code_visualizer.domain.mindmap import MindMapDiagram, find_topic
from code_visualizer.ui_qt.freeform_document import FreeformDocumentWidget
from code_visualizer.ui_qt.main_window import CloseDecision, MainWindow
from code_visualizer.ui_qt.mindmap_document import MindMapDocumentWidget


def _settings(path: Path) -> QSettings:
    return QSettings(str(path / "settings.ini"), QSettings.Format.IniFormat)


def test_mindmap_editor_keyboard_construction_layout_notes_and_delete_preview(
    qtbot, tmp_path
) -> None:
    window = MainWindow(
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()
    window.action_new_mind_map.trigger()
    editor = window.documents.currentWidget()
    assert isinstance(editor, MindMapDocumentWidget)
    assert window.session is not None

    editor.canvas.setFocus()
    qtbot.keyClick(editor.canvas, Qt.Key.Key_Tab)
    project = window.session.authority.snapshot()
    mindmap = project.documents[-1]
    assert isinstance(mindmap, MindMapDiagram)
    first = mindmap.root.children[0]
    assert first.text == "New child topic"
    assert editor.canvas.selected_object_ids() == (first.id,)

    qtbot.keyClick(editor.canvas, Qt.Key.Key_Return)
    mindmap = window.session.authority.snapshot().documents[-1]
    assert isinstance(mindmap, MindMapDiagram)
    assert len(mindmap.root.children) == 2
    selected = mindmap.root.children[1]
    editor.topic_text.setText("Release checks")
    editor.topic_notes.setPlainText("Run all deterministic tests")
    editor.topic_links.setPlainText("https://example.invalid/release")
    qtbot.mouseClick(editor.apply_topic_button, Qt.MouseButton.LeftButton)
    mindmap = window.session.authority.snapshot().documents[-1]
    assert isinstance(mindmap, MindMapDiagram)
    changed = find_topic(mindmap.root, selected.id)
    assert changed is not None
    assert changed.text == "Release checks"
    assert changed.notes == "Run all deterministic tests"

    radial = editor.layout_choice.findData("radial")
    editor.layout_choice.setCurrentIndex(radial)
    editor.layout_choice.activated.emit(radial)
    mindmap = window.session.authority.snapshot().documents[-1]
    assert isinstance(mindmap, MindMapDiagram)
    assert mindmap.layout == "radial"

    qtbot.keyClick(editor.canvas, Qt.Key.Key_Delete)
    assert editor.delete_preview.isVisible()
    assert "Delete" in editor.delete_explanation.text()
    qtbot.mouseClick(editor.cancel_delete_button, Qt.MouseButton.LeftButton)
    assert not editor.delete_preview.isVisible()


def test_freeform_editor_adds_connects_drags_and_exports_from_visible_actions(
    qtbot, tmp_path, monkeypatch
) -> None:
    root = tmp_path / "three-mode"
    export_path = tmp_path / "canvas.svg"
    monkeypatch.setattr(
        "code_visualizer.ui_qt.main_window.QFileDialog.getSaveFileName",
        lambda *_args, **_kwargs: (str(export_path), "SVG vector (*.svg)"),
    )
    window = MainWindow(
        path_chooser=lambda: root,
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()
    window.action_new_freeform.trigger()
    editor = window.documents.currentWidget()
    assert isinstance(editor, FreeformDocumentWidget)
    assert window.session is not None

    qtbot.mouseClick(editor.add_shape_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(editor.add_shape_button, Qt.MouseButton.LeftButton)
    diagram = window.session.authority.snapshot().documents[-1]
    assert isinstance(diagram, FreeformDiagram)
    shapes = [item for item in diagram.objects if isinstance(item, ShapeObject)]
    assert len(shapes) == 2

    editor.canvas.select_objects(tuple(item.id for item in shapes))
    qtbot.mouseClick(editor.connect_button, Qt.MouseButton.LeftButton)
    diagram = window.session.authority.snapshot().documents[-1]
    assert isinstance(diagram, FreeformDiagram)
    assert any(isinstance(item, ConnectorObject) for item in diagram.objects)

    editor.canvas.select_objects((shapes[0].id,))
    scene = editor.canvas._scene_model
    assert scene is not None
    node = next(item for item in scene.nodes if item.object_id == shapes[0].id)
    start = editor.canvas.mapFromScene(QPointF(node.bounds.center.x, node.bounds.center.y))
    before_revision = window.session.authority.revision
    qtbot.mousePress(editor.canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(editor.canvas.viewport(), pos=start + QPointF(50, 35).toPoint())
    assert editor.canvas.drag_ghost_visible
    qtbot.mouseRelease(
        editor.canvas.viewport(),
        Qt.MouseButton.LeftButton,
        pos=start + QPointF(50, 35).toPoint(),
    )
    qtbot.waitUntil(lambda: window.session.authority.revision > before_revision)
    moved = window.session.authority.snapshot().documents[-1]
    assert isinstance(moved, FreeformDiagram)
    moved_shape = next(
        item for item in moved.objects if isinstance(item, ShapeObject) and item.id == shapes[0].id
    )
    assert moved_shape.bounds.x > shapes[0].bounds.x
    assert moved_shape.bounds.y > shapes[0].bounds.y

    window.action_export_document.trigger()
    assert export_path.is_file()
    assert "canvas" in export_path.read_text(encoding="utf-8").casefold()

    window.action_save.trigger()
    window.action_generate.trigger()
    graph_artifact = root / "generated" / "diagrams" / "design" / "freeform" / f"{diagram.id}.svg"
    qtbot.waitUntil(graph_artifact.is_file)
    assert graph_artifact.is_file()


def test_freeform_layers_guides_grid_and_managed_image_use_visible_controls(
    qtbot, tmp_path, monkeypatch
) -> None:
    root = tmp_path / "asset-project"
    source = tmp_path / "source.png"
    Image.new("RGB", (32, 20), "#38bdf8").save(source)
    monkeypatch.setattr(
        "code_visualizer.ui_qt.freeform_document.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(source), "Images"),
    )
    window = MainWindow(
        path_chooser=lambda: root,
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()
    window.action_new_freeform.trigger()
    editor = window.documents.currentWidget()
    assert isinstance(editor, FreeformDocumentWidget)
    assert window.session is not None

    editor.layer_name.setText("Annotations")
    qtbot.mouseClick(editor.add_layer_button, Qt.MouseButton.LeftButton)
    assert editor.layer_choice.currentText() == "Annotations"
    editor.layer_hidden.setChecked(True)
    qtbot.mouseClick(editor.update_layer_button, Qt.MouseButton.LeftButton)
    assert "hidden" in editor.layer_choice.currentText()
    editor.layer_hidden.setChecked(False)
    qtbot.mouseClick(editor.update_layer_button, Qt.MouseButton.LeftButton)

    editor.guide_position.setValue(96.0)
    qtbot.mouseClick(editor.add_guide_button, Qt.MouseButton.LeftButton)
    assert editor.guide_choice.count() == 1
    editor.grid_size.setValue(24.0)
    editor.snap_to_grid.setChecked(True)
    qtbot.mouseClick(editor.apply_canvas_button, Qt.MouseButton.LeftButton)

    qtbot.mouseClick(editor.import_image_button, Qt.MouseButton.LeftButton)
    project = window.session.authority.snapshot()
    assert root.joinpath("project.json").is_file()
    assert len(project.managed_assets) == 1
    managed_path = root / Path(project.managed_assets[0].relative_path)
    assert managed_path.is_file()
    diagram = project.documents[-1]
    assert isinstance(diagram, FreeformDiagram)
    image_shape = next(
        item
        for item in diagram.objects
        if isinstance(item, ShapeObject) and item.shape.value == "image"
    )
    assert image_shape.asset_id == project.managed_assets[0].id
    assert diagram.grid_size == 24.0
    assert diagram.guides[0].position == 96.0
