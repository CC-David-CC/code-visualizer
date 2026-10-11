"""Generic graph gestures resolve identities before proposing semantic edits."""

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QMouseEvent, QPen
from PySide6.QtWidgets import QGraphicsLineItem, QGraphicsScene

from code_visualizer.ui_qt.features.semantic_visualizer.scene_reconciler import SEMANTIC_ID_ROLE
from code_visualizer.ui_qt.features.semantic_visualizer.widget import _ProjectionView


class NotationGraphView(_ProjectionView):
    connectRequested = Signal(str, str)

    def __init__(self, scene: QGraphicsScene) -> None:
        super().__init__(scene)
        self._source_id: str | None = None
        self._connection_ghost: QGraphicsLineItem | None = None
        self.setToolTip("Select an object to edit. Shift-drag between objects to connect them.")

    def _semantic_at(self, point: QPoint) -> str | None:
        item = self.itemAt(point)
        while item is not None:
            identity = item.data(SEMANTIC_ID_ROLE)
            if isinstance(identity, str):
                return identity
            item = item.parentItem()
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() is Qt.MouseButton.LeftButton
            and event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self._source_id = self._semantic_at(event.position().toPoint())
            if self._source_id is not None:
                point = self.mapToScene(event.position().toPoint())
                self._connection_ghost = self.scene().addLine(
                    point.x(), point.y(), point.x(), point.y()
                )
                pen = QPen(Qt.GlobalColor.darkBlue, 2)
                pen.setStyle(Qt.PenStyle.DashLine)
                self._connection_ghost.setPen(pen)
                self._connection_ghost.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                self._connection_ghost.setZValue(10)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._connection_ghost is not None:
            point = self.mapToScene(event.position().toPoint())
            line = self._connection_ghost.line()
            line.setP2(point)
            self._connection_ghost.setLine(line)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._source_id is not None:
            source = self._source_id
            self._source_id = None
            if self._connection_ghost is not None:
                self.scene().removeItem(self._connection_ghost)
                self._connection_ghost = None
            target = self._semantic_at(event.position().toPoint())
            event.accept()
            if target is not None:
                self.connectRequested.emit(source, target)
            return
        super().mouseReleaseEvent(event)
