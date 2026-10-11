import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.drakon import If
from code_visualizer.ui_qt.document import UnifiedDocumentWidget
from code_visualizer.ui_qt.shape_library import SHAPE_MIME_TYPE


def _wheel(
    widget,
    *,
    pixel: QPoint | None = None,
    angle: QPoint | None = None,
    modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier,
) -> None:
    local = QPointF(widget.viewport().rect().center())
    event = QWheelEvent(
        local,
        widget.mapToGlobal(local.toPoint()).toPointF(),
        pixel or QPoint(),
        angle or QPoint(),
        Qt.MouseButton.NoButton,
        modifiers,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    QApplication.sendEvent(widget.viewport(), event)


def test_unmodified_two_axis_scroll_pans_and_ctrl_scroll_zooms(qtbot) -> None:
    session = ProjectSession.new()
    diagram = session.authority.snapshot().documents[0]
    for index in range(16):
        inserted = session.client.insert_drakon_atom(
            diagram.id,
            "action",
            index,
            source=f"value_{index} = {index}",
        )
        assert isinstance(inserted, CommandAccepted)
    session.client.insert_drakon_atom(diagram.id, "if", 16)
    document = UnifiedDocumentWidget(session.client, diagram.id)
    qtbot.addWidget(document)
    document.resize(640, 420)
    document.show()
    qtbot.wait(1)
    canvas = document.canvas
    canvas.resetTransform()
    canvas.horizontalScrollBar().setValue(canvas.horizontalScrollBar().maximum() // 2)
    canvas.verticalScrollBar().setValue(canvas.verticalScrollBar().maximum() // 2)
    before_transform = canvas.transform()
    before_horizontal = canvas.horizontalScrollBar().value()
    before_vertical = canvas.verticalScrollBar().value()

    _wheel(canvas, pixel=QPoint(22, 35))

    assert canvas.transform() == before_transform
    assert canvas.horizontalScrollBar().value() != before_horizontal
    assert canvas.verticalScrollBar().value() != before_vertical

    before_zoom = canvas.transform().m11()
    _wheel(
        canvas,
        angle=QPoint(0, 120),
        modifiers=Qt.KeyboardModifier.ControlModifier,
    )
    assert canvas.transform().m11() > before_zoom
    session.close()


def test_middle_and_space_primary_drag_pan_while_zero_fits(qtbot) -> None:
    session = ProjectSession.new()
    diagram = session.authority.snapshot().documents[0]
    for index in range(14):
        session.client.insert_drakon_atom(
            diagram.id,
            "action",
            index,
            source=f"step_{index} = {index}",
        )
    session.client.insert_drakon_atom(diagram.id, "if", 14)
    document = UnifiedDocumentWidget(session.client, diagram.id)
    qtbot.addWidget(document)
    document.resize(560, 360)
    document.show()
    qtbot.wait(1)
    canvas = document.canvas
    canvas.resetTransform()
    canvas.horizontalScrollBar().setValue(canvas.horizontalScrollBar().maximum() // 2)
    canvas.verticalScrollBar().setValue(canvas.verticalScrollBar().maximum() // 2)
    center = canvas.viewport().rect().center()
    before = (
        canvas.horizontalScrollBar().value(),
        canvas.verticalScrollBar().value(),
    )

    qtbot.mousePress(canvas.viewport(), Qt.MouseButton.MiddleButton, pos=center)
    qtbot.mouseMove(canvas.viewport(), center + QPoint(30, 35))
    qtbot.mouseRelease(
        canvas.viewport(),
        Qt.MouseButton.MiddleButton,
        pos=center + QPoint(30, 35),
    )
    after_middle = (
        canvas.horizontalScrollBar().value(),
        canvas.verticalScrollBar().value(),
    )
    assert after_middle != before

    qtbot.keyPress(canvas, Qt.Key.Key_Space)
    qtbot.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=center)
    qtbot.mouseMove(canvas.viewport(), center - QPoint(25, 25))
    qtbot.mouseRelease(
        canvas.viewport(),
        Qt.MouseButton.LeftButton,
        pos=center - QPoint(25, 25),
    )
    qtbot.keyRelease(canvas, Qt.Key.Key_Space)
    after_space = (
        canvas.horizontalScrollBar().value(),
        canvas.verticalScrollBar().value(),
    )
    assert after_space != after_middle

    qtbot.keyClick(canvas, Qt.Key.Key_0)
    assert canvas.zoom_factor == canvas.transform().m11()
    session.close()


def test_shift_click_toggles_and_directional_marquee_has_documented_semantics(qtbot) -> None:
    session = ProjectSession.new()
    diagram = session.authority.snapshot().documents[0]
    for index in range(2):
        session.client.insert_drakon_atom(
            diagram.id,
            "action",
            index,
            source=f"value_{index} = {index}",
        )
    projected = session.authority.snapshot().documents[0]
    first, second = projected.body.atoms
    document = UnifiedDocumentWidget(session.client, diagram.id)
    qtbot.addWidget(document)
    document.resize(900, 700)
    document.show()
    qtbot.wait(1)
    canvas = document.canvas
    scene = canvas.layout_scene
    assert scene is not None

    def node_center(atom_id: str) -> QPoint:
        node = next(item for item in scene.nodes if item.object_id == atom_id)
        return canvas.mapFromScene(QPointF(node.bounds.center.x, node.bounds.center.y))

    qtbot.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=node_center(first.id))
    qtbot.mouseClick(
        canvas.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        pos=node_center(second.id),
    )
    assert canvas.selected_atom_ids() == (first.id, second.id)
    qtbot.mouseClick(
        canvas.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        pos=node_center(first.id),
    )
    assert canvas.selected_atom_ids() == (second.id,)

    canvas.select_atoms(())
    first_node = next(item for item in scene.nodes if item.object_id == first.id)
    bounds = first_node.bounds
    left = bounds.x - 24
    right = bounds.x + bounds.width + 24
    middle_y = bounds.y + bounds.height / 2
    below = bounds.y + bounds.height + 8

    left_start = canvas.mapFromScene(QPointF(left, middle_y))
    right_end = canvas.mapFromScene(QPointF(right, below))
    qtbot.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=left_start)
    qtbot.mouseMove(canvas.viewport(), right_end, delay=20)
    qtbot.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=right_end)
    assert first.id not in canvas.selected_atom_ids()

    right_start = canvas.mapFromScene(QPointF(right, middle_y))
    left_end = canvas.mapFromScene(QPointF(left, below))
    qtbot.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=right_start)
    qtbot.mouseMove(canvas.viewport(), left_end, delay=20)
    qtbot.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=left_end)
    assert first.id in canvas.selected_atom_ids()
    session.close()


def test_canvas_f2_f3_edit_fields_and_keyboard_cycles_semantic_targets(qtbot) -> None:
    session = ProjectSession.new()
    diagram = session.authority.snapshot().documents[0]
    session.client.insert_drakon_atom(diagram.id, "assignment", 0)
    session.client.insert_drakon_atom(diagram.id, "if", 1)
    projected = session.authority.snapshot().documents[0]
    assignment = projected.body.atoms[0]
    document = UnifiedDocumentWidget(session.client, diagram.id)
    qtbot.addWidget(document)
    document.resize(900, 700)
    document.show()
    qtbot.wait(1)
    canvas = document.canvas
    edits: list[tuple[str, str]] = []
    canvas.atomSelected.connect(lambda atom_id, field: edits.append((atom_id, field)))
    canvas.select_atom(assignment.id)

    qtbot.keyClick(canvas, Qt.Key.Key_F2)
    qtbot.keyClick(canvas, Qt.Key.Key_F3)

    assert edits[-2:] == [(assignment.id, "target"), (assignment.id, "value")]
    assert canvas.active_insertion_boundary is None
    qtbot.keyClick(
        canvas,
        Qt.Key.Key_BracketRight,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier,
    )
    first = canvas.active_insertion_boundary
    assert first is not None
    assert "insertion target" in canvas.accessibleDescription().casefold()
    qtbot.keyClick(
        canvas,
        Qt.Key.Key_BracketRight,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier,
    )
    assert canvas.active_insertion_boundary is not None
    assert canvas.active_insertion_boundary != first
    qtbot.keyClick(canvas, Qt.Key.Key_Escape)
    assert canvas.active_insertion_boundary is None
    session.close()


@pytest.mark.parametrize(
    ("branch_name", "horizontal"),
    (("false_branch", True), ("true_branch", False)),
)
def test_existing_two_atom_block_drags_to_every_route_orientation_with_ghost_and_undo(
    qtbot,
    branch_name: str,
    horizontal: bool,
) -> None:
    session = ProjectSession.new()
    diagram = session.authority.snapshot().documents[0]
    for index, label in enumerate(("one", "two")):
        session.client.insert_drakon_atom(
            diagram.id,
            "action",
            index,
            source=f'print("{label}")',
        )
    session.client.insert_drakon_atom(diagram.id, "if", 2)
    before = session.authority.snapshot().documents[0]
    first, second, decision = before.body.atoms
    assert isinstance(decision, If)
    destination = getattr(decision, branch_name)
    document = UnifiedDocumentWidget(session.client, diagram.id)
    qtbot.addWidget(document)
    document.resize(1100, 760)
    document.show()
    qtbot.wait(1)
    canvas = document.canvas
    scene = canvas.layout_scene
    assert scene is not None
    target = next(
        route
        for route in scene.insertion_routes()
        if route.boundary
        and route.boundary.sequence_id == destination.id
        and route.boundary.index == 0
        and route.segment.is_horizontal is horizontal
    )

    def viewport_center(atom_id: str) -> QPoint:
        node = next(item for item in scene.nodes if item.object_id == atom_id)
        return canvas.mapFromScene(QPointF(node.bounds.center.x, node.bounds.center.y))

    first_pos = viewport_center(first.id)
    second_pos = viewport_center(second.id)
    target_scene = target.segment.start
    target_pos = canvas.mapFromScene(
        QPointF(
            (target.segment.start.x + target.segment.end.x) / 2,
            target_scene.y,
        )
    )
    qtbot.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=first_pos)
    qtbot.mouseClick(
        canvas.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        pos=second_pos,
    )
    assert canvas.selected_atom_ids() == (first.id, second.id)

    qtbot.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=first_pos)
    qtbot.mouseMove(canvas.viewport(), target_pos, delay=20)
    assert canvas.drag_ghost_visible
    assert canvas.active_insertion_boundary == target.boundary
    qtbot.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=target_pos)

    qtbot.waitUntil(
        lambda: len(session.authority.snapshot().documents[0].body.atoms) == 1,
        timeout=2000,
    )
    moved = session.authority.snapshot().documents[0]
    moved_decision = moved.body.atoms[0]
    assert isinstance(moved_decision, If)
    moved_destination = getattr(moved_decision, branch_name)
    assert [atom.id for atom in moved_destination.atoms[:2]] == [
        first.id,
        second.id,
    ]
    assert isinstance(session.client.undo(), CommandAccepted)
    assert [atom.id for atom in session.authority.snapshot().documents[0].body.atoms[:2]] == [
        first.id,
        second.id,
    ]
    session.close()


def test_palette_drop_shows_scaled_ghost_and_inserts_at_vertical_boundary(qtbot) -> None:
    session = ProjectSession.new()
    diagram = session.authority.snapshot().documents[0]
    document = UnifiedDocumentWidget(session.client, diagram.id)
    qtbot.addWidget(document)
    document.resize(800, 600)
    document.show()
    qtbot.wait(1)
    canvas = document.canvas
    scene = canvas.layout_scene
    assert scene is not None
    route = next(item for item in scene.insertion_routes() if not item.segment.is_horizontal)
    target = canvas.mapFromScene(
        QPointF(
            route.segment.start.x,
            (route.segment.start.y + route.segment.end.y) / 2,
        )
    )
    mime = QMimeData()
    mime.setData(SHAPE_MIME_TYPE, b"if")
    enter = QDragEnterEvent(
        target,
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    move = QDragMoveEvent(
        target,
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    drop = QDropEvent(
        QPointF(target),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    QApplication.sendEvent(canvas.viewport(), enter)
    QApplication.sendEvent(canvas.viewport(), move)
    assert canvas.drag_ghost_visible
    assert canvas.active_insertion_boundary == route.boundary
    QApplication.sendEvent(canvas.viewport(), drop)
    qtbot.waitUntil(
        lambda: bool(session.authority.snapshot().documents[0].body.atoms),
        timeout=2000,
    )

    assert isinstance(session.authority.snapshot().documents[0].body.atoms[0], If)
    session.close()
