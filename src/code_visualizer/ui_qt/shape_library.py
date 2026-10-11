"""Drag-capable visual library for semantic DRAKON constructs."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QEvent, QMimeData, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QListView, QListWidget, QListWidgetItem

from code_visualizer.rendering.catalog import preview_for_atom_kind
from code_visualizer.rendering.recipes import solve_recipe
from code_visualizer.ui_qt.text_metrics import QtTextMeasurer
from code_visualizer.ui_qt.vector_projection import qt_path_for_shape

SHAPE_MIME_TYPE = "application/x-code-visualizer-d-r-a-k-o-n-shape"


class ShapeLibrary(QListWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setDragDropMode(QListWidget.DragDropMode.DragOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setViewMode(QListView.ViewMode.ListMode)
        self.setMovement(QListView.Movement.Static)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setIconSize(QSize(46, 26))
        self.setSpacing(2)
        self.setMinimumSize(0, 0)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWordWrap(True)
        # Keep source dragging enabled after configuring the compact list.
        self.setDragEnabled(True)

    def icon_for_kind(self, kind: str) -> QIcon:
        recipe_kind, texts = preview_for_atom_kind(kind)
        shape = solve_recipe(recipe_kind, texts, QtTextMeasurer.create())
        pixmap = QPixmap(self.iconSize())
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        available_width = pixmap.width() - 12
        available_height = pixmap.height() - 12
        scale = min(
            available_width / shape.bounds.width,
            available_height / shape.bounds.height,
        )
        painter.translate(
            (pixmap.width() - shape.bounds.width * scale) / 2,
            (pixmap.height() - shape.bounds.height * scale) / 2,
        )
        painter.scale(scale, scale)
        painter.setPen(QPen(self.palette().color(QPalette.ColorRole.Text), 2 / scale))
        painter.setBrush(self.palette().color(QPalette.ColorRole.Base))
        painter.drawPath(qt_path_for_shape(shape))
        for divider in shape.dividers:
            painter.drawLine(
                round(divider.start.x),
                round(divider.start.y),
                round(divider.end.x),
                round(divider.end.y),
            )
        painter.end()
        return QIcon(pixmap)

    def mimeTypes(self) -> list[str]:
        return [SHAPE_MIME_TYPE]

    def mimeData(self, items: Sequence[QListWidgetItem]) -> QMimeData:
        mime = QMimeData()
        if items:
            kind = items[0].data(Qt.ItemDataRole.UserRole)
            if isinstance(kind, str):
                mime.setData(SHAPE_MIME_TYPE, kind.encode("utf-8"))
        return mime

    def supportedDragActions(self) -> Qt.DropAction:
        return Qt.DropAction.CopyAction

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.PaletteChange:
            for row in range(self.count()):
                item = self.item(row)
                kind = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
                if item is not None and isinstance(kind, str):
                    item.setIcon(self.icon_for_kind(kind))
        super().changeEvent(event)
