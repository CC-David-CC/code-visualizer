"""Identity-keyed semantic scene diffing and in-place Qt reconciliation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from math import atan2, cos, sin

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QBrush, QColor, QFont, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsTextItem,
)

from code_visualizer.domain.semantic import (
    ProjectionEdge,
    ProjectionNode,
    SemanticObjectKind,
    SemanticProjection,
)

SEMANTIC_ID_ROLE = 10_201
NODE_ID_ROLE = 10_202
RUNTIME_ACTIVE_ROLE = 10_203


@dataclass(frozen=True, slots=True)
class ProjectionDiff:
    added_node_ids: tuple[str, ...] = ()
    removed_node_ids: tuple[str, ...] = ()
    updated_node_ids: tuple[str, ...] = ()
    unchanged_node_ids: tuple[str, ...] = ()
    added_edge_ids: tuple[str, ...] = ()
    removed_edge_ids: tuple[str, ...] = ()
    updated_edge_ids: tuple[str, ...] = ()
    unchanged_edge_ids: tuple[str, ...] = ()


def diff_projections(
    previous: SemanticProjection | None,
    current: SemanticProjection,
) -> ProjectionDiff:
    old_nodes = {item.id: item for item in previous.nodes} if previous is not None else {}
    new_nodes = {item.id: item for item in current.nodes}
    old_edges = {item.id: item for item in previous.edges} if previous is not None else {}
    new_edges = {item.id: item for item in current.edges}
    shared_nodes = old_nodes.keys() & new_nodes.keys()
    shared_edges = old_edges.keys() & new_edges.keys()
    return ProjectionDiff(
        tuple(sorted(new_nodes.keys() - old_nodes.keys())),
        tuple(sorted(old_nodes.keys() - new_nodes.keys())),
        tuple(sorted(item for item in shared_nodes if old_nodes[item] != new_nodes[item])),
        tuple(sorted(item for item in shared_nodes if old_nodes[item] == new_nodes[item])),
        tuple(sorted(new_edges.keys() - old_edges.keys())),
        tuple(sorted(old_edges.keys() - new_edges.keys())),
        tuple(sorted(item for item in shared_edges if old_edges[item] != new_edges[item])),
        tuple(sorted(item for item in shared_edges if old_edges[item] == new_edges[item])),
    )


class ProjectionNodeItem(QGraphicsRectItem):
    def __init__(self) -> None:
        super().__init__()
        self.label_item = QGraphicsTextItem(self)
        self.detail_item = QGraphicsTextItem(self)
        self.badge_item = QGraphicsTextItem(self)
        self.label_item.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        self.label_item.setDefaultTextColor(QColor("#1f2937"))
        self.detail_item.setFont(QFont("Segoe UI", 8))
        self.detail_item.setDefaultTextColor(QColor("#475569"))
        self.badge_item.setFont(QFont("Segoe UI", 7))
        self.badge_item.setDefaultTextColor(QColor("#5f6b78"))
        for item in (self.label_item, self.detail_item, self.badge_item):
            item.document().setDocumentMargin(0.0)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(2)

    def update_node(
        self,
        node: ProjectionNode,
        position: tuple[float, float],
        *,
        node_color: Callable[[SemanticObjectKind], QColor],
        bounded_text: Callable[[str, int], str],
        move: bool,
    ) -> None:
        detail = node.detail.strip()
        visible_badges = (
            (*node.badges, f"{node.hidden_count} hidden") if node.hidden_count else node.badges
        )
        badge_text = " | ".join(visible_badges)
        width = min(
            430.0,
            max(190.0, 24.0 + max(len(node.label), len(detail), len(badge_text)) * 7.2),
        )
        self.setData(SEMANTIC_ID_ROLE, node.semantic_id)
        self.setData(NODE_ID_ROLE, node.id)
        active = "active" in node.badges
        self.setData(RUNTIME_ACTIVE_ROLE, active)
        self.setToolTip(f"{node.kind.value}: {node.label}\n{detail}\n{node.semantic_id}")
        self.setPen(
            QPen(
                QColor("#b45309") if active else QColor("#64748b"),
                2.6 if active else 1.4,
            )
        )
        self.setBrush(QBrush(node_color(node.kind)))
        if move:
            self.setPos(*position)

        self.label_item.setPlainText(bounded_text(node.label, 120))
        self.label_item.setTextWidth(width - 20.0)
        self.label_item.setPos(10.0, 8.0)
        self.label_item.setData(SEMANTIC_ID_ROLE, node.semantic_id)
        next_y = self.label_item.boundingRect().bottom() + 14.0

        detail_visible = bool(detail and detail != node.label)
        self.detail_item.setVisible(detail_visible)
        if detail_visible:
            self.detail_item.setPlainText(bounded_text(detail, 180))
            self.detail_item.setTextWidth(width - 20.0)
            self.detail_item.setPos(10.0, next_y)
            self.detail_item.setData(SEMANTIC_ID_ROLE, node.semantic_id)
            next_y += self.detail_item.boundingRect().height() + 5.0
        else:
            self.detail_item.setPlainText(" ")
            self.detail_item.setTextWidth(width - 20.0)
            self.detail_item.setPos(10.0, 8.0)

        self.badge_item.setVisible(bool(badge_text))
        if badge_text:
            self.badge_item.setPlainText(bounded_text(badge_text, 120))
            self.badge_item.setTextWidth(width - 20.0)
            self.badge_item.setPos(10.0, next_y)
            self.badge_item.setData(SEMANTIC_ID_ROLE, node.semantic_id)
            next_y += self.badge_item.boundingRect().height() + 7.0
        else:
            self.badge_item.setPlainText(" ")
            self.badge_item.setTextWidth(width - 20.0)
            self.badge_item.setPos(10.0, 8.0)
        self.setRect(QRectF(0.0, 0.0, width, max(52.0, next_y)))


class ProjectionEdgeItem(QGraphicsPathItem):
    def __init__(self) -> None:
        super().__init__()
        self.arrow_item = QGraphicsPolygonItem(self)
        self.label_item = QGraphicsSimpleTextItem(self)
        self.label_item.setFont(QFont("Segoe UI", 7))
        self.label_item.setBrush(QBrush(QColor("#475569")))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(0)
        self.arrow_item.setZValue(1)
        self.label_item.setZValue(1)

    def update_edge(
        self,
        edge: ProjectionEdge,
        source: QRectF,
        target: QRectF,
        *,
        lane_offset: float = 0.0,
    ) -> None:
        start = source.center()
        end = target.center()
        if abs(end.x() - start.x()) >= abs(end.y() - start.y()):
            start.setX(source.right() if end.x() >= start.x() else source.left())
            end.setX(target.left() if end.x() >= start.x() else target.right())
        else:
            start.setY(source.bottom() if end.y() >= start.y() else source.top())
            end.setY(target.top() if end.y() >= start.y() else target.bottom())
        path = QPainterPath(start)
        if edge.source_id == edge.target_id:
            start = QPointF(source.right(), source.center().y())
            end = QPointF(source.center().x(), source.top())
            path = QPainterPath(start)
            radius = 60.0 + abs(lane_offset)
            path.cubicTo(
                source.right() + radius,
                source.center().y(),
                source.center().x(),
                source.top() - radius,
                end.x(),
                end.y(),
            )
        elif lane_offset:
            dx, dy = end.x() - start.x(), end.y() - start.y()
            distance = max(1.0, (dx * dx + dy * dy) ** 0.5)
            sign = 1.0 if edge.source_id < edge.target_id else -1.0
            normal = QPointF(
                -dy / distance * lane_offset * sign, dx / distance * lane_offset * sign
            )
            first_control = start + (end - start) / 3 + normal
            second_control = start + (end - start) * (2 / 3) + normal
            path.cubicTo(first_control, second_control, end)
        elif abs(end.x() - start.x()) >= abs(end.y() - start.y()):
            midpoint = (start.x() + end.x()) / 2
            path.cubicTo(midpoint, start.y(), midpoint, end.y(), end.x(), end.y())
        else:
            midpoint = (start.y() + end.y()) / 2
            path.cubicTo(start.x(), midpoint, end.x(), midpoint, end.x(), end.y())
        self.setPath(path)
        self.setData(SEMANTIC_ID_ROLE, edge.id)
        self.setData(RUNTIME_ACTIVE_ROLE, edge.active)
        self.setToolTip(f"Relationship: {edge.label or edge.id}\n{edge.id}")
        color = QColor("#b45309") if edge.active else QColor("#7c8795")
        self.setPen(QPen(color, 2.8 if edge.active else 1.25))
        angle = atan2(
            end.y() - path.pointAtPercent(0.96).y(),
            end.x() - path.pointAtPercent(0.96).x(),
        )
        self.arrow_item.setPolygon(
            QPolygonF(
                (
                    end,
                    end - QPointF(cos(angle - 0.45) * 9, sin(angle - 0.45) * 9),
                    end - QPointF(cos(angle + 0.45) * 9, sin(angle + 0.45) * 9),
                )
            )
        )
        self.arrow_item.setPen(QPen(color))
        self.arrow_item.setBrush(QBrush(color))
        self.label_item.setText(edge.label)
        self.label_item.setVisible(bool(edge.label))
        self.label_item.setPos(path.pointAtPercent(0.5) + QPointF(4, -14))


class SceneReconciler:
    def __init__(
        self,
        scene: QGraphicsScene,
        *,
        node_color: Callable[[SemanticObjectKind], QColor],
        bounded_text: Callable[[str, int], str],
    ) -> None:
        self.scene = scene
        self.node_color = node_color
        self.bounded_text = bounded_text
        self.projection: SemanticProjection | None = None
        self.node_items: dict[str, ProjectionNodeItem] = {}
        self.edge_items: dict[str, ProjectionEdgeItem] = {}

    def clear(self) -> None:
        self.scene.clear()
        self.node_items.clear()
        self.edge_items.clear()
        self.projection = None

    def reconcile(
        self,
        projection: SemanticProjection,
        positions: Mapping[str, tuple[float, float]],
    ) -> ProjectionDiff:
        diff = diff_projections(self.projection, projection)
        previous = self.projection
        relayout_all = (
            previous is None
            or previous.layout != projection.layout
            or previous.definition_id != projection.definition_id
        )
        current_edges = {item.id: item for item in projection.edges}
        previous_edges = {item.id: item for item in previous.edges} if previous is not None else {}
        structural_node_ids = {
            endpoint
            for edge_id in (
                *diff.added_edge_ids,
                *diff.updated_edge_ids,
                *diff.removed_edge_ids,
            )
            if (edge := current_edges.get(edge_id, previous_edges.get(edge_id))) is not None
            for endpoint in (edge.source_id, edge.target_id)
        }
        selected_semantic_ids = {
            value
            for item in self.scene.selectedItems()
            if isinstance((value := item.data(SEMANTIC_ID_ROLE)), str)
        }
        for edge_id in diff.removed_edge_ids:
            removed_edge_item = self.edge_items.pop(edge_id, None)
            if removed_edge_item is not None:
                self.scene.removeItem(removed_edge_item)
        for node_id in diff.removed_node_ids:
            removed_node_item = self.node_items.pop(node_id, None)
            if removed_node_item is not None:
                self.scene.removeItem(removed_node_item)

        new_node_ids = frozenset(diff.added_node_ids)
        for node in projection.nodes:
            node_item = self.node_items.get(node.id)
            if node_item is None:
                node_item = ProjectionNodeItem()
                self.node_items[node.id] = node_item
                self.scene.addItem(node_item)
            node_item.update_node(
                node,
                positions.get(node.id, (0.0, 0.0)),
                node_color=self.node_color,
                bounded_text=self.bounded_text,
                move=relayout_all or node.id in new_node_ids or node.id in structural_node_ids,
            )
            node_item.setSelected(node.semantic_id in selected_semantic_ids)

        edge_groups: dict[tuple[str, str], list[str]] = defaultdict(list)
        for edge in current_edges.values():
            endpoints = tuple(sorted((edge.source_id, edge.target_id)))
            edge_groups[(endpoints[0], endpoints[1])].append(edge.id)
        lane_offsets = {
            edge_id: (index if source_id == target_id else index - (len(edge_ids) - 1) / 2) * 42.0
            for (source_id, target_id), edge_ids in edge_groups.items()
            for index, edge_id in enumerate(sorted(edge_ids))
        }
        for edge_id, edge in current_edges.items():
            source = self.node_items.get(edge.source_id)
            target = self.node_items.get(edge.target_id)
            if source is None or target is None:
                stale = self.edge_items.pop(edge_id, None)
                if stale is not None:
                    self.scene.removeItem(stale)
                continue
            edge_item = self.edge_items.get(edge_id)
            if edge_item is None:
                edge_item = ProjectionEdgeItem()
                self.edge_items[edge_id] = edge_item
                self.scene.addItem(edge_item)
            edge_item.update_edge(
                edge,
                source.sceneBoundingRect(),
                target.sceneBoundingRect(),
                lane_offset=lane_offsets[edge_id],
            )
            edge_item.setSelected(edge.id in selected_semantic_ids)

        valid_edges = set(current_edges)
        for edge_id in tuple(self.edge_items):
            if edge_id in valid_edges:
                continue
            self.scene.removeItem(self.edge_items.pop(edge_id))
        self.projection = projection
        return diff

    def items_by_semantic_id(self) -> dict[str, list[QGraphicsItem]]:
        result: dict[str, list[QGraphicsItem]] = defaultdict(list)
        nodes = {item.id: item for item in self.projection.nodes} if self.projection else {}
        for node_id, item in self.node_items.items():
            node = nodes.get(node_id)
            if node is not None:
                result[node.semantic_id].append(item)
        for edge_id, edge_item in self.edge_items.items():
            result[edge_id].append(edge_item)
        return dict(result)
