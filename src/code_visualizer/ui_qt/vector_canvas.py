"""Qt projections and drag ghosts for deterministic generic vector scenes."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import cast

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSignalBlocker, Qt, Signal
from PySide6.QtGui import (
    QAccessible,
    QAccessibleEvent,
    QColor,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsItemGroup,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

from code_visualizer.rendering.vector_scene import (
    VectorNode,
    VectorScene,
    projected_edge_points,
)

OBJECT_ID_ROLE = 0x4D01


class VectorCanvas(QGraphicsView):
    objectSelected = Signal(str)
    reparentRequested = Signal(str, str)
    moveRequested = Signal(object, float, float)
    addSiblingRequested = Signal()
    addChildRequested = Signal()
    promoteRequested = Signal()
    deleteRequested = Signal()

    def __init__(
        self,
        *,
        mode: str,
        asset_bytes: Callable[[str], bytes | None] | None = None,
    ) -> None:
        super().__init__()
        self.mode = mode
        self._asset_bytes = asset_bytes or (lambda _asset_id: None)
        self.setObjectName(f"{mode}Canvas")
        self.setAccessibleName(f"{mode.replace('_', ' ').title()} canvas")
        self._graphics = QGraphicsScene(self)
        self.setScene(self._graphics)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self._scene_model: VectorScene | None = None
        self._groups: dict[str, QGraphicsItemGroup] = {}
        self._pressed_id: str | None = None
        self._press_viewport: QPoint | None = None
        self._press_scene: QPointF | None = None
        self._ghost: QGraphicsRectItem | None = None
        self._panning = False
        self._pan_position: QPoint | None = None
        self._zoom = 1.0
        self._graphics.selectionChanged.connect(self._selection_changed)

    @property
    def drag_ghost_visible(self) -> bool:
        return self._ghost is not None

    def set_vector_scene(self, scene: VectorScene) -> None:
        selected = self.selected_object_ids()
        first = self._scene_model is None
        self._scene_model = scene
        signal_blocker = QSignalBlocker(self._graphics)
        self._graphics.clear()
        self._groups.clear()
        self.setBackgroundBrush(self.palette().color(QPalette.ColorRole.AlternateBase))
        for edge in scene.edges:
            projected = projected_edge_points(edge)
            if len(projected) < 2:
                continue
            path = QPainterPath(QPointF(projected[0].x, projected[0].y))
            for point in projected[1:]:
                path.lineTo(point.x, point.y)
            item = QGraphicsPathItem(path)
            item.setPen(
                QPen(
                    QColor(edge.stroke),
                    2,
                    Qt.PenStyle.DashLine if edge.cross_link else Qt.PenStyle.SolidLine,
                )
            )
            item.setZValue(-5)
            self._graphics.addItem(item)
            if edge.label:
                label = QGraphicsSimpleTextItem(edge.label)
                middle = edge.points[len(edge.points) // 2]
                label.setPos(middle.x + 4, middle.y - 20)
                label.setBrush(QColor(edge.stroke))
                label.setZValue(-4)
                self._graphics.addItem(label)
        for node in scene.nodes:
            self._add_node(node)
        self._graphics.setSceneRect(
            QRectF(scene.bounds.x, scene.bounds.y, scene.bounds.width, scene.bounds.height)
        )
        for object_id in selected:
            group = self._groups.get(object_id)
            if group is not None:
                group.setSelected(True)
        del signal_blocker
        if first:
            self.fit_content()

    def _add_node(self, node: VectorNode) -> None:
        bounds = QRectF(node.bounds.x, node.bounds.y, node.bounds.width, node.bounds.height)
        if node.kind == "ellipse":
            body: QGraphicsItem = QGraphicsEllipseItem(bounds)
        elif node.kind in {"line", "arrow", "polyline", "polygon"} and node.points:
            polygon = [QPointF(point.x, point.y) for point in node.points]
            if node.kind == "polygon":
                from PySide6.QtGui import QPolygonF

                body = QGraphicsPolygonItem(QPolygonF(polygon))
            else:
                path = QPainterPath(polygon[0])
                for point in polygon[1:]:
                    path.lineTo(point)
                body = QGraphicsPathItem(path)
        else:
            body = QGraphicsRectItem(bounds)
        if hasattr(body, "setBrush"):
            cast(object, body).setBrush(QColor(node.fill))  # type: ignore[attr-defined]
        if hasattr(body, "setPen"):
            cast(object, body).setPen(QPen(QColor(node.stroke), 2))  # type: ignore[attr-defined]
        if node.rotation:
            body.setTransformOriginPoint(bounds.center())
            body.setRotation(node.rotation)
        group = QGraphicsItemGroup()
        group.addToGroup(body)
        image_loaded = False
        if node.kind == "image" and node.asset_id is not None:
            data = self._asset_bytes(node.asset_id)
            pixmap = QPixmap()
            if data is not None and pixmap.loadFromData(data):
                scaled = pixmap.scaled(
                    max(1, round(bounds.width() - 4)),
                    max(1, round(bounds.height() - 4)),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                image_item = QGraphicsPixmapItem(scaled)
                image_item.setPos(
                    bounds.center().x() - scaled.width() / 2,
                    bounds.center().y() - scaled.height() / 2,
                )
                group.addToGroup(image_item)
                image_loaded = True
        if node.text and not image_loaded:
            label = QGraphicsSimpleTextItem(node.text)
            text_bounds = label.boundingRect()
            label.setPos(
                node.bounds.center.x - text_bounds.width() / 2,
                node.bounds.center.y - text_bounds.height() / 2,
            )
            label.setBrush(self.palette().color(QPalette.ColorRole.Text))
            group.addToGroup(label)
        group.setData(OBJECT_ID_ROLE, node.object_id)
        group.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, not node.locked)
        group.setToolTip(node.text or node.kind.replace("_", " ").title())
        group.setZValue(1)
        self._graphics.addItem(group)
        self._groups[node.object_id] = group

    def selected_object_ids(self) -> tuple[str, ...]:
        selected = {
            value
            for item in self._graphics.selectedItems()
            if isinstance((value := item.data(OBJECT_ID_ROLE)), str)
        }
        if self._scene_model is None:
            return ()
        return tuple(
            node.object_id for node in self._scene_model.nodes if node.object_id in selected
        )

    def select_objects(self, object_ids: tuple[str, ...]) -> None:
        self._graphics.clearSelection()
        for object_id in object_ids:
            group = self._groups.get(object_id)
            if group is not None:
                group.setSelected(True)

    def fit_content(self) -> None:
        if self._scene_model is None:
            return
        self.resetTransform()
        bounds = self._scene_model.bounds
        self.fitInView(
            QRectF(bounds.x, bounds.y, max(1.0, bounds.width), max(1.0, bounds.height)),
            Qt.AspectRatioMode.KeepAspectRatio,
        )
        self._zoom = self.transform().m11()

    def drawBackground(self, painter: QPainter, rect: QRectF | QRect) -> None:
        super().drawBackground(painter, rect)
        scene = self._scene_model
        if scene is None or scene.mode != "freeform" or scene.grid_size is None:
            return
        area = QRectF(rect)
        spacing = scene.grid_size
        while spacing * max(self.transform().m11(), 0.01) < 8.0:
            spacing *= 2.0
        painter.save()
        pen = QPen(self.palette().color(QPalette.ColorRole.Midlight), 1)
        pen.setCosmetic(True)
        painter.setPen(pen)
        start_x = math.floor(area.left() / spacing) * spacing
        end_x = math.ceil(area.right() / spacing) * spacing
        start_y = math.floor(area.top() / spacing) * spacing
        end_y = math.ceil(area.bottom() / spacing) * spacing
        x = start_x
        while x <= end_x:
            painter.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
            x += spacing
        y = start_y
        while y <= end_y:
            painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            y += spacing
        painter.restore()

    def drawForeground(self, painter: QPainter, rect: QRectF | QRect) -> None:
        super().drawForeground(painter, rect)
        scene = self._scene_model
        if scene is None or scene.mode != "freeform" or not scene.guides:
            return
        area = QRectF(rect)
        painter.save()
        pen = QPen(
            self.palette().color(QPalette.ColorRole.Highlight),
            1,
            Qt.PenStyle.DashLine,
        )
        pen.setCosmetic(True)
        painter.setPen(pen)
        for guide in scene.guides:
            if guide.orientation.value == "vertical":
                painter.drawLine(
                    QPointF(guide.position, area.top()),
                    QPointF(guide.position, area.bottom()),
                )
            else:
                painter.drawLine(
                    QPointF(area.left(), guide.position),
                    QPointF(area.right(), guide.position),
                )
        painter.restore()

    def _group_at(self, position: QPoint) -> QGraphicsItemGroup | None:
        item = self.itemAt(position)
        while item is not None:
            if isinstance(item, QGraphicsItemGroup) and isinstance(item.data(OBJECT_ID_ROLE), str):
                return item
            item = item.parentItem()
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_position = event.position().toPoint()
            event.accept()
            return
        group = self._group_at(event.position().toPoint())
        self._pressed_id = cast(str, group.data(OBJECT_ID_ROLE)) if group is not None else None
        self._press_viewport = event.position().toPoint()
        self._press_scene = self.mapToScene(self._press_viewport)
        super().mousePressEvent(event)

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
            self._pressed_id
            and self._press_viewport is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and (event.position().toPoint() - self._press_viewport).manhattanLength() >= 7
        ):
            group = self._groups.get(self._pressed_id)
            if group is not None:
                if self._ghost is None:
                    self._ghost = QGraphicsRectItem(group.sceneBoundingRect())
                    accent = self.palette().color(QPalette.ColorRole.Highlight)
                    fill = QColor(accent)
                    fill.setAlpha(55)
                    self._ghost.setPen(QPen(accent, 2, Qt.PenStyle.DashLine))
                    self._ghost.setBrush(fill)
                    self._ghost.setZValue(50)
                    self._graphics.addItem(self._ghost)
                assert self._press_scene is not None
                current_scene = self.mapToScene(event.position().toPoint())
                scene_delta = current_scene - self._press_scene
                self._ghost.setPos(scene_delta)
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._panning:
            self._panning = False
            self._pan_position = None
            event.accept()
            return
        if (
            self._ghost is not None
            and self._pressed_id is not None
            and self._press_scene is not None
        ):
            current_scene = self.mapToScene(event.position().toPoint())
            delta = current_scene - self._press_scene
            self._graphics.removeItem(self._ghost)
            self._ghost = None
            if self.mode == "mind_map":
                target = self._group_at(event.position().toPoint())
                target_id = cast(str, target.data(OBJECT_ID_ROLE)) if target is not None else None
                if target_id and target_id != self._pressed_id:
                    self.reparentRequested.emit(self._pressed_id, target_id)
            elif abs(delta.x()) + abs(delta.y()) > 0.5:
                selected = self.selected_object_ids()
                moving = selected if self._pressed_id in selected else (self._pressed_id,)
                self.moveRequested.emit(moving, delta.x(), delta.y())
            self._pressed_id = None
            event.accept()
            return
        super().mouseReleaseEvent(event)
        self._pressed_id = None

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y() or event.pixelDelta().y()
            factor = 1.15 if delta > 0 else 1 / 1.15
            new_zoom = self._zoom * factor
            if 0.08 <= new_zoom <= 8.0:
                self.scale(factor, factor)
                self._zoom = new_zoom
            event.accept()
            return
        pixel = event.pixelDelta()
        angle = event.angleDelta()
        dx = pixel.x() or angle.x() / 2
        dy = pixel.y() or angle.y() / 2
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - round(dx))
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() - round(dy))
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self.mode == "mind_map":
            if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
                self.addSiblingRequested.emit()
                event.accept()
                return
            if event.key() == Qt.Key.Key_Tab:
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    self.promoteRequested.emit()
                else:
                    self.addChildRequested.emit()
                event.accept()
                return
            if event.key() == Qt.Key.Key_Delete:
                self.deleteRequested.emit()
                event.accept()
                return
        super().keyPressEvent(event)

    def focusNextPrevChild(self, next: bool) -> bool:
        if self.mode == "mind_map":
            if next:
                self.addChildRequested.emit()
            else:
                self.promoteRequested.emit()
            return True
        return super().focusNextPrevChild(next)

    def _selection_changed(self) -> None:
        selected = self.selected_object_ids()
        if selected:
            self.objectSelected.emit(selected[-1])
        scene = self._scene_model
        names = []
        if scene is not None:
            for object_id in selected:
                node = next((item for item in scene.nodes if item.object_id == object_id), None)
                if node is not None:
                    names.append(f"{node.kind}: {node.text or 'unlabelled object'}")
        self.setAccessibleDescription(
            "; selected ".join(names) if names else "No vector object selected"
        )
        QAccessible.updateAccessibility(
            QAccessibleEvent(self, QAccessible.Event.DescriptionChanged)
        )

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.PaletteChange:
            self.setBackgroundBrush(self.palette().color(QPalette.ColorRole.AlternateBase))
            if self._scene_model is not None:
                self.set_vector_scene(self._scene_model)
        super().changeEvent(event)
