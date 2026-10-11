"""The single Qt path projection for solved vector recipes."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath, QPolygonF

from code_visualizer.rendering.recipes import SolvedShape


def qt_path_for_shape(shape: SolvedShape) -> QPainterPath:
    path = QPainterPath()
    if shape.corner_radius and len(shape.outline) == 4:
        path.addRoundedRect(
            QRectF(
                shape.bounds.x,
                shape.bounds.y,
                shape.bounds.width,
                shape.bounds.height,
            ),
            shape.corner_radius,
            shape.corner_radius,
        )
        return path
    polygon = QPolygonF([QPointF(point.x, point.y) for point in shape.outline])
    path.addPolygon(polygon)
    path.closeSubpath()
    return path
