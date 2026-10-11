"""Interactive projection of the canonical DRAKON vector scene."""

from __future__ import annotations

from math import pow
from typing import cast

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAccessible,
    QAccessibleEvent,
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QKeyEvent,
    QMouseEvent,
    QNativeGestureEvent,
    QPainter,
    QPalette,
    QPen,
    QResizeEvent,
    QShowEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsItemGroup,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QWidget,
)

from code_visualizer.domain.drakon import (
    Action,
    Assignment,
    Call,
    Delay,
    DrakonAtom,
    DrakonDiagram,
    If,
    Input,
    Loop,
    Note,
    Output,
    Period,
    RealtimeProcess,
    Select,
    Sequence,
    Silhouette,
    SimpleStatement,
    StartTimer,
    Synchronizer,
    Transfer,
    find_atom_location,
    nested_sequences,
)
from code_visualizer.domain.drakon_selection import selection_objects, selection_ownership
from code_visualizer.rendering.catalog import preview_for_atom_kind
from code_visualizer.rendering.geometry import Point
from code_visualizer.rendering.recipes import solve_recipe
from code_visualizer.rendering.scene import (
    DiagramScene,
    SceneNode,
    SceneRoute,
    SequenceBoundary,
    layout_drakon,
)
from code_visualizer.ui_qt.shape_library import SHAPE_MIME_TYPE
from code_visualizer.ui_qt.text_metrics import QtTextMeasurer
from code_visualizer.ui_qt.vector_projection import qt_path_for_shape

NODE_ID_ROLE = 1


class DrakonCanvas(QGraphicsView):
    atomSelected = Signal(str, str)
    objectClicked = Signal(str)
    objectSelectionChanged = Signal(object)
    insertionTargetChanged = Signal(object)
    insertRequested = Signal(str, str, int)
    moveRequested = Signal(str, object, str, int)
    autoFitChanged = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("drakonCanvas")
        self.setAccessibleName("Structural DRAKON canvas")
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(self.palette().color(QPalette.ColorRole.AlternateBase))
        self._graphics = QGraphicsScene(self)
        self._graphics.selectionChanged.connect(self._update_selection_visuals)
        self.setScene(self._graphics)
        self._diagram: DrakonDiagram | None = None
        self._selectable_ids: tuple[str, ...] = ()
        self._selectable_id_set: frozenset[str] = frozenset()
        self._layout: DiagramScene | None = None
        self._measurer = QtTextMeasurer.create()
        self._node_groups: dict[str, QGraphicsItemGroup] = {}
        self._route_items: dict[str, QGraphicsLineItem] = {}
        self._press_position: QPoint | None = None
        self._pressed_atom_id: str | None = None
        self._ghost: QGraphicsItemGroup | None = None
        self._ghost_origin = QPointF()
        self._active_route: SceneRoute | None = None
        self._panning = False
        self._pan_position: QPoint | None = None
        self._space_down = False
        self._zoom = 1.0
        self._auto_fit = True
        self._fitting = False
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(40)
        self._fit_timer.timeout.connect(self._fit_settled_view)
        self.horizontalScrollBar().sliderPressed.connect(lambda: self.set_auto_fit(False))
        self.verticalScrollBar().sliderPressed.connect(lambda: self.set_auto_fit(False))

    @property
    def layout_scene(self) -> DiagramScene | None:
        return self._layout

    @property
    def zoom_factor(self) -> float:
        return self._zoom

    @property
    def drag_ghost_visible(self) -> bool:
        return self._ghost is not None

    @property
    def active_insertion_boundary(self) -> SequenceBoundary | None:
        return self._active_route.boundary if self._active_route is not None else None

    def cycle_insertion_target(self, *, forward: bool = True) -> SequenceBoundary | None:
        if self._layout is None:
            return None
        routes = tuple(route for route in self._layout.insertion_routes() if route.boundary)
        if not routes:
            self._set_active_route(None)
            return None
        current = next(
            (
                index
                for index, route in enumerate(routes)
                if self._active_route is not None and route.id == self._active_route.id
            ),
            -1 if forward else 0,
        )
        step = 1 if forward else -1
        route = routes[(current + step) % len(routes)]
        self._set_active_route(route)
        item = self._route_items.get(route.id)
        if item is not None:
            self.ensureVisible(item, 24, 24)
        return route.boundary

    def clear_insertion_target(self) -> None:
        self._set_active_route(None)

    def request_selected_field_edit(self, *, secondary: bool = False) -> bool:
        selected = self.selected_atom_ids()
        if len(selected) != 1:
            return False
        field = self._edit_field_for_atom(selected[0], secondary=secondary)
        if field is None:
            return False
        self.atomSelected.emit(selected[0], field)
        return True

    def set_diagram(self, diagram: DrakonDiagram) -> None:
        selected = self.selected_object_ids()
        self._diagram = diagram
        self._selectable_ids = tuple(item.id for item in selection_objects(diagram))
        self._selectable_id_set = frozenset(self._selectable_ids)
        self._layout = layout_drakon(diagram, measurer=self._measurer)
        self._project_scene()
        for atom_id in selected:
            group = self._node_groups.get(atom_id)
            if group is not None:
                group.setSelected(True)
        self.schedule_fit()

    def selected_atom_ids(self) -> tuple[str, ...]:
        if self._diagram is None:
            return ()
        selected = {
            value
            for item in self._graphics.selectedItems()
            if isinstance((value := item.data(NODE_ID_ROLE)), str)
        }
        ordered: list[str] = []

        def collect(sequence: Sequence) -> None:
            for atom in sequence.atoms:
                if atom.id in selected:
                    ordered.append(atom.id)
                for nested in nested_sequences(atom):
                    collect(nested)

        collect(self._diagram.body)
        return tuple(ordered)

    def selected_object_ids(self) -> tuple[str, ...]:
        """Selected semantic presentations, independently of atom editing."""
        return tuple(
            identity
            for identity in self._selectable_ids
            if (group := self._node_groups.get(identity)) is not None and group.isSelected()
        )

    def selection_ownership(self, object_id: str) -> tuple[str, ...]:
        return selection_ownership(self._diagram, object_id) if self._diagram is not None else ()

    def select_atom(self, atom_id: str) -> None:
        self.select_atoms((atom_id,))

    def select_atoms(self, atom_ids: tuple[str, ...]) -> None:
        self.select_objects(
            tuple(
                atom_id
                for atom_id in atom_ids
                if self._diagram is not None
                and find_atom_location(self._diagram.body, atom_id) is not None
            )
        )

    def select_objects(self, object_ids: tuple[str, ...]) -> None:
        self._graphics.clearSelection()
        last: QGraphicsItemGroup | None = None
        for object_id in object_ids:
            group = self._node_groups.get(object_id)
            if group is not None and object_id in self._selectable_id_set:
                group.setSelected(True)
                last = group
        if last is not None:
            self.centerOn(last)

    @property
    def auto_fit(self) -> bool:
        return self._auto_fit

    def set_auto_fit(self, enabled: bool) -> None:
        if self._auto_fit != enabled:
            self._auto_fit = enabled
            self.autoFitChanged.emit(enabled)
        if enabled:
            self.schedule_fit()
        else:
            self._fit_timer.stop()

    def schedule_fit(self) -> None:
        if self._auto_fit and not self._fitting:
            self._fit_timer.start()

    def fit_content(self) -> None:
        """Explicit Fit returns to auto-fit; layout-triggered fits respect manual zoom."""
        self.set_auto_fit(True)
        self._fit_settled_view()
        self.schedule_fit()

    def _fit_settled_view(self) -> None:
        if (
            not self._auto_fit
            or self._fitting
            or not self.isVisible()
            or self._layout is None
            or self._layout.bounds.width <= 0
            or self.viewport().width() <= 1
            or self.viewport().height() <= 1
        ):
            return
        self._fitting = True
        try:
            self.resetTransform()
            bounds = self._layout.bounds
            self.fitInView(
                QRectF(bounds.x, bounds.y, bounds.width, bounds.height),
                Qt.AspectRatioMode.KeepAspectRatio,
            )
            self._zoom = self.transform().m11()
        finally:
            self._fitting = False

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_fit_timer"):
            self.schedule_fit()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.schedule_fit()

    def _manual_zoom(self, factor: float) -> None:
        self.set_auto_fit(False)
        target = max(0.02, min(4.0, self._zoom * factor))
        self.scale(target / self._zoom, target / self._zoom)
        self._zoom = target

    def _project_scene(self) -> None:
        assert self._layout is not None
        self._node_groups.clear()
        self._route_items.clear()
        self._active_route = None
        self._ghost = None
        self._graphics.clear()
        text_color = self.palette().color(QPalette.ColorRole.Text)
        route_pen = QPen(text_color, 2.0)
        for route in self._layout.routes:
            segment = route.segment
            item = self._graphics.addLine(
                segment.start.x,
                segment.start.y,
                segment.end.x,
                segment.end.y,
                route_pen,
            )
            item.setZValue(-10)
            item.setToolTip(route.tooltip)
            self._route_items[route.id] = item
        for label in self._layout.labels:
            label_item = self._graphics.addSimpleText(label.text, self._measurer.code_font)
            label_item.setBrush(text_color)
            label_item.setPos(label.bounds.x, label.bounds.y)
            label_item.setZValue(2)
        for node in self._layout.nodes:
            self._draw_node(node)
        bounds = self._layout.bounds
        self._graphics.setSceneRect(bounds.x, bounds.y, bounds.width, bounds.height)

    def _node_pieces(self, node: SceneNode, *, ghost: bool = False) -> list[QGraphicsItem]:
        shape = node.shape
        text_color = self.palette().color(QPalette.ColorRole.Text)
        accent = self.palette().color(QPalette.ColorRole.Highlight)
        surface = self.palette().color(QPalette.ColorRole.Base)
        ghost_fill = QColor(accent)
        ghost_fill.setAlpha(70)
        outline = QGraphicsPathItem(qt_path_for_shape(shape))
        outline.setPos(node.origin.x, node.origin.y)
        outline.setPen(QPen(accent if ghost else text_color, 2.0))
        outline.setBrush(ghost_fill if ghost else surface)
        pieces: list[QGraphicsItem] = [outline]
        for divider in shape.dividers:
            line = QGraphicsLineItem(
                divider.start.x,
                divider.start.y,
                divider.end.x,
                divider.end.y,
            )
            line.setPos(node.origin.x, node.origin.y)
            line.setPen(QPen(accent if ghost else text_color, 2.0))
            pieces.append(line)
        for block in shape.text_blocks:
            font = (
                self._measurer.title_font
                if block.role in {"title", "branch"}
                else self._measurer.code_font
            )
            for index, line_text in enumerate(block.lines):
                text = QGraphicsSimpleTextItem(line_text)
                text.setFont(font)
                text.setBrush(accent if ghost else text_color)
                text.setPos(
                    node.origin.x + block.safe_bounds.x,
                    node.origin.y + block.safe_bounds.y + index * self._measurer.line_height,
                )
                pieces.append(text)
        return pieces

    def _draw_node(self, node: SceneNode) -> None:
        pieces = self._node_pieces(node)
        group = self._create_group(pieces)
        group.setData(NODE_ID_ROLE, node.object_id)
        group.setToolTip(node.shape.accessibility_name)
        if node.object_id in self._selectable_id_set:
            group.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        group.setZValue(1)
        self._node_groups[node.object_id] = group

    def _update_selection_visuals(self) -> None:
        accent = self.palette().color(QPalette.ColorRole.Highlight)
        text_color = self.palette().color(QPalette.ColorRole.Text)
        for group in self._node_groups.values():
            outline = next(
                (child for child in group.childItems() if isinstance(child, QGraphicsPathItem)),
                None,
            )
            if outline is not None:
                outline.setPen(
                    QPen(
                        accent if group.isSelected() else text_color,
                        3.5 if group.isSelected() else 2.0,
                    )
                )
        self._announce_selection()
        self.objectSelectionChanged.emit(self.selected_object_ids())

    @staticmethod
    def _preferred_sequences(atom: DrakonAtom) -> tuple[Sequence, ...]:
        if isinstance(atom, If):
            return (
                (atom.true_branch, atom.false_branch)
                if atom.preferred_truth
                else (atom.false_branch, atom.true_branch)
            )
        if isinstance(atom, Select) and atom.preferred_case_id is not None:
            preferred = tuple(case.body for case in atom.cases if case.id == atom.preferred_case_id)
            remaining = tuple(case.body for case in atom.cases if case.id != atom.preferred_case_id)
            return (*preferred, *remaining)
        if isinstance(atom, Synchronizer) and not atom.preferred_on_time:
            return (atom.on_timeout, atom.on_time)
        if isinstance(atom, Silhouette):
            preferred = tuple(
                branch.body for branch in atom.branches if branch.id == atom.initial_branch_id
            )
            remaining = tuple(
                branch.body for branch in atom.branches if branch.id != atom.initial_branch_id
            )
            return (*preferred, *remaining)
        return nested_sequences(atom)

    def semantic_traversal(self) -> tuple[str, ...]:
        if self._diagram is None:
            return ()
        ordered: list[str] = []

        def visit(sequence: Sequence) -> None:
            for atom in sequence.atoms:
                ordered.append(atom.id)
                for nested in self._preferred_sequences(atom):
                    visit(nested)

        visit(self._diagram.body)
        return tuple(ordered)

    def _announce_selection(self) -> None:
        selected = self.selected_object_ids()
        traversal = self.semantic_traversal()
        descriptions: list[str] = []
        for atom_id in selected:
            node = (
                next(
                    (item for item in self._layout.nodes if item.object_id == atom_id),
                    None,
                )
                if self._layout is not None
                else None
            )
            if node is None:
                continue
            position = traversal.index(atom_id) + 1 if atom_id in traversal else 0
            ports = ", ".join(
                f"{port.name} {port.valence}"
                + (f" truth {port.truth}" if port.truth is not None else "")
                for port in node.shape.ports
            )
            descriptions.append(
                f"{node.shape.accessibility_name}; valid semantic icon; "
                f"traversal {position} of {len(traversal)}; ports {ports or 'none'}"
            )
        description = "; selected ".join(descriptions) if descriptions else "No icon selected"
        if self._active_route is not None and self._active_route.boundary is not None:
            description += f"; insertion target: {self._active_route.tooltip}"
        self.setAccessibleDescription(description)
        QAccessible.updateAccessibility(
            QAccessibleEvent(self, QAccessible.Event.DescriptionChanged)
        )

    def _create_group(self, pieces: list[QGraphicsItem]) -> QGraphicsItemGroup:
        group = QGraphicsItemGroup()
        self._graphics.addItem(group)
        for piece in pieces:
            group.addToGroup(piece)
        return group

    def _group_for_item(self, item: QGraphicsItem | None) -> QGraphicsItemGroup | None:
        current = item
        while current is not None:
            if isinstance(current, QGraphicsItemGroup) and isinstance(
                current.data(NODE_ID_ROLE), str
            ):
                return current
            current = current.parentItem()
        return None

    def _field_for_atom(self, atom_id: str) -> str | None:
        if self._diagram is None:
            return None
        location = find_atom_location(self._diagram.body, atom_id)
        if location is None:
            return None
        atom = location[0].atoms[location[1]]
        if isinstance(atom, Action):
            return "source"
        if isinstance(atom, Output):
            return "expression"
        if isinstance(atom, Assignment):
            return "value"
        if isinstance(atom, If):
            return "condition"
        if isinstance(atom, Transfer):
            return "expression"
        if isinstance(atom, SimpleStatement):
            return "source"
        if isinstance(atom, Call):
            return "expression"
        if isinstance(atom, Input):
            return "prompt"
        if isinstance(atom, Delay):
            return "seconds"
        if isinstance(atom, StartTimer):
            return "timer"
        if isinstance(atom, Period):
            return "seconds"
        if isinstance(atom, RealtimeProcess):
            return "call"
        if isinstance(atom, Note):
            return "text"
        if isinstance(atom, Select):
            return "expression"
        if isinstance(atom, Loop):
            return "condition"
        if isinstance(atom, Synchronizer):
            return "deadline"
        if isinstance(atom, Silhouette):
            return "identifier"
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton and self._space_down
        ):
            self.set_auto_fit(False)
            self._panning = True
            self._pan_position = event.position().toPoint()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        group = self._group_for_item(self.itemAt(event.position().toPoint()))
        self._pressed_atom_id = cast(str, group.data(NODE_ID_ROLE)) if group is not None else None
        self._press_position = event.position().toPoint()
        if (
            group is not None
            and event.button() == Qt.MouseButton.LeftButton
            and event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            group.setSelected(not group.isSelected())
            if group.isSelected() and self._pressed_atom_id is not None:
                self.objectClicked.emit(self._pressed_atom_id)
                field = self._field_for_atom(self._pressed_atom_id)
                if field is not None:
                    self.atomSelected.emit(self._pressed_atom_id, field)
            self._pressed_atom_id = None
            self._press_position = None
            event.accept()
            return
        if group is None and event.button() == Qt.MouseButton.LeftButton:
            route = self._route_at(self.mapToScene(event.position().toPoint()))
            if route is not None and route.boundary is not None:
                self._set_active_route(route)
                self._pressed_atom_id = None
                self._press_position = None
                event.accept()
                return
        super().mousePressEvent(event)
        if self._pressed_atom_id:
            self.objectClicked.emit(self._pressed_atom_id)
            field = self._field_for_atom(self._pressed_atom_id)
            if field is not None:
                self.atomSelected.emit(self._pressed_atom_id, field)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._panning and self._pan_position is not None:
            current = event.position().toPoint()
            delta = current - self._pan_position
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            self._pan_position = current
            event.accept()
            return
        if (
            self._pressed_atom_id
            and self._press_position is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            delta = event.position().toPoint() - self._press_position
            if self._ghost is None and delta.manhattanLength() >= 8:
                self._begin_existing_drag()
            if self._ghost is not None:
                scene_delta = self.mapToScene(event.position().toPoint()) - self.mapToScene(
                    self._press_position
                )
                self._ghost.setPos(self._ghost_origin + scene_delta)
                self._set_active_route(self._route_at(self.mapToScene(event.position().toPoint())))
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._panning:
            self._panning = False
            self._pan_position = None
            self.viewport().unsetCursor()
            event.accept()
            return
        if self._ghost is not None:
            route = self._active_route
            move_payload: tuple[str, tuple[str, ...], str, int] | None = None
            if route is not None and route.boundary is not None and self._diagram is not None:
                selected = self.selected_atom_ids()
                locations = [
                    find_atom_location(self._diagram.body, atom_id) for atom_id in selected
                ]
                valid_locations = [location for location in locations if location is not None]
                if selected and len(valid_locations) == len(locations):
                    source_ids = {location[0].id for location in valid_locations}
                    if len(source_ids) == 1:
                        move_payload = (
                            source_ids.pop(),
                            selected,
                            route.boundary.sequence_id,
                            route.boundary.index,
                        )
            self._finish_drag()
            if move_payload is not None:
                self.moveRequested.emit(*move_payload)
            event.accept()
            return
        press_position = self._press_position
        pressed_atom_id = self._pressed_atom_id
        self._pressed_atom_id = None
        self._press_position = None
        super().mouseReleaseEvent(event)
        if (
            press_position is not None
            and pressed_atom_id is None
            and event.button() == Qt.MouseButton.LeftButton
            and (event.position().toPoint() - press_position).manhattanLength() >= 8
        ):
            self._apply_directional_marquee(
                press_position,
                event.position().toPoint(),
                preserve=bool(
                    event.modifiers()
                    & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
                ),
            )

    def _apply_directional_marquee(
        self,
        start: QPoint,
        end: QPoint,
        *,
        preserve: bool,
    ) -> None:
        scene_start = self.mapToScene(start)
        scene_end = self.mapToScene(end)
        bounds = QRectF(scene_start, scene_end).normalized()
        require_containment = end.x() >= start.x()
        if not preserve:
            self._graphics.clearSelection()
        for group in self._node_groups.values():
            if not group.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable:
                continue
            item_bounds = group.sceneBoundingRect()
            matched = (
                bounds.contains(item_bounds)
                if require_containment
                else bounds.intersects(item_bounds)
            )
            if matched:
                group.setSelected(True)

    def _begin_existing_drag(self) -> None:
        if (
            self._diagram is None
            or self._pressed_atom_id is None
            or find_atom_location(self._diagram.body, self._pressed_atom_id) is None
        ):
            return
        selected = self.selected_atom_ids()
        if self._pressed_atom_id and self._pressed_atom_id not in selected:
            self.select_atom(self._pressed_atom_id)
            selected = (self._pressed_atom_id,)
        pieces: list[QGraphicsItem] = []
        for atom_id in selected:
            node = (
                next(
                    (item for item in self._layout.nodes if item.object_id == atom_id),
                    None,
                )
                if self._layout is not None
                else None
            )
            if node is not None:
                pieces.extend(self._node_pieces(node, ghost=True))
            group = self._node_groups.get(atom_id)
            if group is not None:
                group.setOpacity(0.35)
        if not pieces:
            return
        self._ghost = self._create_group(pieces)
        self._ghost.setOpacity(0.65)
        self._ghost.setZValue(100)
        self._ghost_origin = self._ghost.pos()

    def _finish_drag(self) -> None:
        if self._ghost is not None:
            # Keep scene ownership stable until the next projection rebuild.
            # Deleting a graphics group during its originating pointer event is
            # unsafe on some Windows Qt backends.
            self._ghost.hide()
            self._ghost = None
        for group in self._node_groups.values():
            group.setOpacity(1.0)
        self._set_active_route(None)
        self._pressed_atom_id = None
        self._press_position = None

    def _route_at(self, position: QPointF) -> SceneRoute | None:
        if self._layout is None:
            return None
        point = Point(position.x(), position.y())
        candidates = [
            route
            for route in self._layout.insertion_routes()
            if route.hit_bounds(self._layout.metrics).contains(point)
        ]
        if not candidates:
            return None

        def distance(route: SceneRoute) -> float:
            segment = route.segment
            if segment.is_horizontal:
                return abs(point.y - segment.start.y)
            return abs(point.x - segment.start.x)

        return min(candidates, key=lambda route: (distance(route), route.id))

    def _set_active_route(self, route: SceneRoute | None) -> None:
        if self._active_route is route:
            return
        if self._active_route is not None:
            item = self._route_items.get(self._active_route.id)
            if item is not None:
                item.setPen(QPen(self.palette().color(QPalette.ColorRole.Text), 2.0))
        self._active_route = route
        if route is not None:
            item = self._route_items.get(route.id)
            if item is not None:
                item.setPen(QPen(self.palette().color(QPalette.ColorRole.Highlight), 5.0))
        self._announce_selection()
        self.insertionTargetChanged.emit(route.boundary if route is not None else None)

    def wheelEvent(self, event: QWheelEvent) -> None:
        pixel = event.pixelDelta()
        angle = event.angleDelta()
        dx = pixel.x() if not pixel.isNull() else angle.x() / 4
        dy = pixel.y() if not pixel.isNull() else angle.y() / 4
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            amount = dy or dx
            factor = pow(1.0015, amount)
            self._manual_zoom(factor)
        else:
            self.set_auto_fit(False)
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier and not dx:
                dx, dy = dy, 0
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - round(dx))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - round(dy))
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in {
            Qt.Key.Key_F2,
            Qt.Key.Key_F3,
        } and self.request_selected_field_edit(secondary=event.key() == Qt.Key.Key_F3):
            event.accept()
            return
        if event.modifiers() & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
        ) == (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
        ) and event.key() in {Qt.Key.Key_BracketLeft, Qt.Key.Key_BracketRight}:
            self.cycle_insertion_target(forward=event.key() == Qt.Key.Key_BracketRight)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self._active_route is not None:
            self.clear_insertion_target()
            event.accept()
            return
        if event.key() in {
            Qt.Key.Key_Tab,
            Qt.Key.Key_Backtab,
        } and self._advance_semantic_selection(event.key() != Qt.Key.Key_Backtab):
            event.accept()
            return
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_down = True
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        if event.key() in {Qt.Key.Key_Plus, Qt.Key.Key_Equal}:
            self._manual_zoom(1.15)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Minus:
            self._manual_zoom(1 / 1.15)
            event.accept()
            return
        if event.key() == Qt.Key.Key_0:
            self.fit_content()
            event.accept()
            return
        super().keyPressEvent(event)

    def _edit_field_for_atom(self, atom_id: str, *, secondary: bool) -> str | None:
        if self._diagram is None:
            return None
        location = find_atom_location(self._diagram.body, atom_id)
        if location is None:
            return None
        atom = location[0].atoms[location[1]]
        fields: tuple[str, str | None]
        if isinstance(atom, Assignment):
            fields = ("target", "value")
        elif isinstance(atom, Output):
            fields = ("expression", "destination")
        elif isinstance(atom, Input):
            fields = ("target", "prompt")
        elif isinstance(atom, Call):
            fields = ("expression", "arguments")
        elif isinstance(atom, Transfer):
            fields = ("expression", "cause")
        elif isinstance(atom, SimpleStatement):
            fields = ("source", "secondary")
        elif isinstance(atom, Loop):
            fields = (
                "iterable" if atom.iterable else "condition",
                "target" if atom.iterable else None,
            )
        elif isinstance(atom, Synchronizer):
            fields = ("deadline", "timer")
        elif isinstance(atom, Silhouette):
            fields = ("display_name", "identifier")
        else:
            fields = (self._field_for_atom(atom_id) or "", None)
        return fields[1] if secondary else fields[0] or None

    def focusNextPrevChild(self, next: bool) -> bool:
        return self._advance_semantic_selection(next) or super().focusNextPrevChild(next)

    def _advance_semantic_selection(self, forward: bool) -> bool:
        traversal = self.semantic_traversal()
        if not traversal:
            return False
        selected = self.selected_atom_ids()
        current = traversal.index(selected[-1]) if selected[-1:] else (-1 if forward else 0)
        step = 1 if forward else -1
        self.select_atom(traversal[(current + step) % len(traversal)])
        return True

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_down = False
            self.viewport().unsetCursor()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.PaletteChange:
            selected = self.selected_object_ids()
            self.setBackgroundBrush(self.palette().color(QPalette.ColorRole.AlternateBase))
            if self._layout is not None:
                self._project_scene()
                self.select_objects(selected)
        super().changeEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(SHAPE_MIME_TYPE):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if not event.mimeData().hasFormat(SHAPE_MIME_TYPE):
            super().dragMoveEvent(event)
            return
        position = self.mapToScene(event.position().toPoint())
        if self._ghost is None:
            kind = bytes(event.mimeData().data(SHAPE_MIME_TYPE).data()).decode("utf-8")
            self._begin_palette_ghost(kind, position)
        elif self._ghost is not None:
            self._ghost.setPos(position - self._ghost.boundingRect().center())
        route = self._route_at(position)
        self._set_active_route(route)
        if route is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._finish_drag()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if not event.mimeData().hasFormat(SHAPE_MIME_TYPE):
            super().dropEvent(event)
            return
        route = self._active_route
        insertion: tuple[str, str, int] | None = None
        if route is not None and route.boundary is not None:
            kind = bytes(event.mimeData().data(SHAPE_MIME_TYPE).data()).decode("utf-8")
            insertion = (
                kind,
                route.boundary.sequence_id,
                route.boundary.index,
            )
            event.acceptProposedAction()
        else:
            event.ignore()
        self._finish_drag()
        if insertion is not None:
            self.insertRequested.emit(*insertion)

    def _begin_palette_ghost(self, kind: str, position: QPointF) -> None:
        try:
            recipe_kind, texts = preview_for_atom_kind(kind)
        except KeyError:
            return
        shape = solve_recipe(recipe_kind, texts, self._measurer)
        node = SceneNode("palette-ghost", shape, Point(0, 0))
        self._ghost = self._create_group(self._node_pieces(node, ghost=True))
        self._ghost.setOpacity(0.65)
        self._ghost.setZValue(100)
        self._ghost.setPos(position - self._ghost.boundingRect().center())

    def viewportEvent(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.NativeGesture:
            gesture = cast(QNativeGestureEvent, event)
            if gesture.gestureType() == Qt.NativeGestureType.ZoomNativeGesture:
                factor = max(0.5, min(2.0, 1.0 + float(gesture.value())))
                self._manual_zoom(factor)
                gesture.accept()
                return True
        return super().viewportEvent(event)
