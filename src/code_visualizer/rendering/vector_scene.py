"""Deterministic off-screen scenes for mind maps and free-form documents."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from code_visualizer.domain.freeform import (
    ConnectorObject,
    FreeformDiagram,
    GuideOrientation,
    ShapeKind,
    ShapeObject,
)
from code_visualizer.domain.mindmap import MindMapDiagram, Topic
from code_visualizer.rendering.geometry import Point, Rect, union_rects


@dataclass(frozen=True, slots=True)
class VectorNode:
    object_id: str
    kind: str
    bounds: Rect
    text: str = ""
    fill: str = "#ffffff"
    stroke: str = "#1f2937"
    rotation: float = 0.0
    points: tuple[Point, ...] = ()
    locked: bool = False
    asset_id: str | None = None


@dataclass(frozen=True, slots=True)
class VectorEdge:
    object_id: str
    points: tuple[Point, ...]
    label: str = ""
    stroke: str = "#334155"
    arrow_start: bool = False
    arrow_end: bool = False
    cross_link: bool = False
    bridges: tuple[VectorBridge, ...] = ()


@dataclass(frozen=True, slots=True)
class VectorBridge:
    """A deterministic jump owned by the later edge at a proper crossing."""

    segment_index: int
    point: Point
    radius: float = 7.0


@dataclass(frozen=True, slots=True)
class VectorGuide:
    guide_id: str
    orientation: GuideOrientation
    position: float


@dataclass(frozen=True, slots=True)
class VectorScene:
    document_id: str
    title: str
    nodes: tuple[VectorNode, ...]
    edges: tuple[VectorEdge, ...]
    bounds: Rect
    mode: str
    guides: tuple[VectorGuide, ...] = ()
    grid_size: float | None = None


_TOPIC_WIDTH = 176.0
_TOPIC_HEIGHT = 58.0
_LEVEL_PITCH = 240.0
_ROW_PITCH = 94.0
_MARGIN = 48.0


def _visible_children(topic: Topic) -> tuple[Topic, ...]:
    return () if topic.collapsed else topic.children


def _leaf_weight(topic: Topic) -> int:
    children = _visible_children(topic)
    return max(1, sum(_leaf_weight(child) for child in children))


def _topic_width(topic: Topic) -> float:
    longest = max((len(line) for line in topic.text.splitlines()), default=0)
    return max(_TOPIC_WIDTH, min(340.0, 56.0 + longest * 7.2))


def _layout_horizontal(
    root: Topic,
    *,
    direction: int,
) -> dict[str, Point]:
    positions: dict[str, Point] = {}
    next_leaf = 0.0

    def place(topic: Topic, depth: int) -> float:
        nonlocal next_leaf
        children = _visible_children(topic)
        if children:
            child_rows = [place(child, depth + 1) for child in children]
            row = (child_rows[0] + child_rows[-1]) / 2
        else:
            row = next_leaf
            next_leaf += _leaf_weight(topic)
        positions[topic.id] = Point(direction * depth * _LEVEL_PITCH, row * _ROW_PITCH)
        return row

    place(root, 0)
    root_y = positions[root.id].y
    return {topic_id: Point(point.x, point.y - root_y) for topic_id, point in positions.items()}


def _layout_balanced(root: Topic) -> dict[str, Point]:
    positions = {root.id: Point(0.0, 0.0)}
    children = _visible_children(root)
    right = tuple(child for index, child in enumerate(children) if index % 2 == 0)
    left = tuple(child for index, child in enumerate(children) if index % 2 == 1)
    for direction, branch in ((1, right), (-1, left)):
        if not branch:
            continue
        synthetic = Topic(f"{root.id}:side:{direction}", "", branch)
        side = _layout_horizontal(synthetic, direction=direction)
        side.pop(synthetic.id, None)
        values = tuple(point.y for point in side.values())
        offset = (min(values) + max(values)) / 2 if values else 0.0
        positions.update(
            {topic_id: Point(point.x, point.y - offset) for topic_id, point in side.items()}
        )
    return positions


def _layout_radial(root: Topic) -> dict[str, Point]:
    positions = {root.id: Point(0.0, 0.0)}

    def place(topic: Topic, depth: int, start: float, end: float) -> None:
        children = _visible_children(topic)
        total = sum(_leaf_weight(child) for child in children)
        cursor = start
        for child in children:
            portion = (end - start) * _leaf_weight(child) / max(1, total)
            middle = cursor + portion / 2
            radius = depth * 205.0
            positions[child.id] = Point(math.cos(middle) * radius, math.sin(middle) * radius)
            place(child, depth + 1, cursor, cursor + portion)
            cursor += portion

    place(root, 1, -math.pi, math.pi)
    return positions


def layout_mind_map(diagram: MindMapDiagram) -> VectorScene:
    if diagram.layout == "left_to_right":
        positions = _layout_horizontal(diagram.root, direction=1)
    elif diagram.layout == "right_to_left":
        positions = _layout_horizontal(diagram.root, direction=-1)
    elif diagram.layout == "radial":
        positions = _layout_radial(diagram.root)
    else:
        positions = _layout_balanced(diagram.root)
    topics: dict[str, Topic] = {}

    def collect(topic: Topic) -> None:
        topics[topic.id] = topic
        for child in _visible_children(topic):
            collect(child)

    collect(diagram.root)
    nodes: list[VectorNode] = []
    node_bounds: dict[str, Rect] = {}
    for topic_id, point in positions.items():
        topic = topics[topic_id]
        width = _topic_width(topic)
        text_height = 30.0 + max(1, len(topic.text.splitlines())) * 18.0
        height = max(_TOPIC_HEIGHT, text_height) + (
            18.0 if topic.notes or topic.links or topic.attachments else 0.0
        )
        bounds = Rect(point.x - width / 2, point.y - height / 2, width, height)
        node_bounds[topic_id] = bounds
        nodes.append(
            VectorNode(
                topic_id,
                "mind_root" if topic_id == diagram.root.id else "mind_topic",
                bounds,
                topic.text,
                "#dbeafe" if topic_id == diagram.root.id else "#ffffff",
                "#1d4ed8" if topic_id == diagram.root.id else "#475569",
            )
        )
    edges: list[VectorEdge] = []

    def connect(topic: Topic) -> None:
        source = node_bounds[topic.id].center
        for child in _visible_children(topic):
            target = node_bounds[child.id].center
            middle_x = (source.x + target.x) / 2
            if abs(source.x - target.x) < 1.0:
                middle_y = (source.y + target.y) / 2
                points = (source, Point(source.x, middle_y), Point(target.x, middle_y), target)
            else:
                points = (source, Point(middle_x, source.y), Point(middle_x, target.y), target)
            edges.append(VectorEdge(f"tree:{topic.id}:{child.id}", points))
            connect(child)

    connect(diagram.root)
    for link in diagram.cross_links:
        if link.source_topic_id not in node_bounds or link.target_topic_id not in node_bounds:
            continue
        edges.append(
            VectorEdge(
                link.id,
                (
                    node_bounds[link.source_topic_id].center,
                    node_bounds[link.target_topic_id].center,
                ),
                link.label,
                "#7c3aed",
                arrow_end=True,
                cross_link=True,
            )
        )
    bounds = _vector_bounds(tuple(nodes), tuple(edges)).expanded(_MARGIN)
    return VectorScene(diagram.id, diagram.title, tuple(nodes), tuple(edges), bounds, "mind_map")


def _connector_points(
    item: ConnectorObject,
    shapes: dict[str, ShapeObject],
) -> tuple[Point, ...]:
    if item.points:
        return tuple(Point(point.x, point.y) for point in item.points)
    source = shapes[item.source_id].bounds
    target = shapes[item.target_id].bounds
    start = Point(source.x + source.width / 2, source.y + source.height / 2)
    end = Point(target.x + target.width / 2, target.y + target.height / 2)
    if not item.orthogonal:
        return (start, end)
    middle_x = (start.x + end.x) / 2
    return (start, Point(middle_x, start.y), Point(middle_x, end.y), end)


def _cross(left: Point, right: Point) -> float:
    return left.x * right.y - left.y * right.x


def _proper_intersection(
    first_start: Point,
    first_end: Point,
    second_start: Point,
    second_end: Point,
) -> Point | None:
    first = Point(first_end.x - first_start.x, first_end.y - first_start.y)
    second = Point(second_end.x - second_start.x, second_end.y - second_start.y)
    denominator = _cross(first, second)
    if abs(denominator) < 1e-9:
        return None
    delta = Point(second_start.x - first_start.x, second_start.y - first_start.y)
    first_factor = _cross(delta, second) / denominator
    second_factor = _cross(delta, first) / denominator
    # A crossing at a connector vertex or common endpoint needs no bridge.
    clearance = 0.04
    if not (
        clearance < first_factor < 1.0 - clearance and clearance < second_factor < 1.0 - clearance
    ):
        return None
    return Point(
        first_start.x + first.x * first_factor,
        first_start.y + first.y * first_factor,
    )


def _add_connector_bridges(edges: tuple[VectorEdge, ...]) -> tuple[VectorEdge, ...]:
    bridges: list[list[VectorBridge]] = [[] for _edge in edges]
    for later_index, later in enumerate(edges):
        for earlier in edges[:later_index]:
            for later_segment in range(len(later.points) - 1):
                start = later.points[later_segment]
                end = later.points[later_segment + 1]
                length = math.hypot(end.x - start.x, end.y - start.y)
                if length < 20.0:
                    continue
                for earlier_segment in range(len(earlier.points) - 1):
                    crossing = _proper_intersection(
                        start,
                        end,
                        earlier.points[earlier_segment],
                        earlier.points[earlier_segment + 1],
                    )
                    if crossing is None:
                        continue
                    if any(
                        math.hypot(item.point.x - crossing.x, item.point.y - crossing.y) < 18.0
                        for item in bridges[later_index]
                    ):
                        continue
                    bridges[later_index].append(VectorBridge(later_segment, crossing))
    return tuple(
        replace(
            edge,
            bridges=tuple(
                sorted(
                    bridges[index],
                    key=lambda bridge: (
                        bridge.segment_index,
                        bridge.point.x,
                        bridge.point.y,
                    ),
                )
            ),
        )
        for index, edge in enumerate(edges)
    )


def projected_edge_points(edge: VectorEdge, *, curve_steps: int = 8) -> tuple[Point, ...]:
    """Return the one shared polyline recipe used by canvas and every exporter."""

    if len(edge.points) < 2 or not edge.bridges:
        return edge.points
    result = [edge.points[0]]
    for segment_index, (start, end) in enumerate(zip(edge.points, edge.points[1:], strict=False)):
        dx, dy = end.x - start.x, end.y - start.y
        length = math.hypot(dx, dy)
        if length <= 0:
            result.append(end)
            continue
        ux, uy = dx / length, dy / length
        normal_x, normal_y = -uy, ux
        segment_bridges = sorted(
            (item for item in edge.bridges if item.segment_index == segment_index),
            key=lambda item: (item.point.x - start.x) * ux + (item.point.y - start.y) * uy,
        )
        for bridge in segment_bridges:
            radius = min(bridge.radius, length / 4)
            before = Point(bridge.point.x - ux * radius, bridge.point.y - uy * radius)
            result.append(before)
            for step in range(1, curve_steps + 1):
                portion = step / curve_steps
                along = -radius + 2 * radius * portion
                lift = math.sin(math.pi * portion) * radius
                result.append(
                    Point(
                        bridge.point.x + ux * along + normal_x * lift,
                        bridge.point.y + uy * along + normal_y * lift,
                    )
                )
        result.append(end)
    return tuple(result)


def layout_freeform(diagram: FreeformDiagram) -> VectorScene:
    visible_layers = {layer.id for layer in diagram.layers if not layer.hidden}
    shapes = {
        item.id: item
        for item in diagram.objects
        if isinstance(item, ShapeObject) and not item.hidden and item.layer_id in visible_layers
    }

    def shape_points(item: ShapeObject) -> tuple[Point, ...]:
        if item.points:
            return tuple(Point(point.x, point.y) for point in item.points)
        bounds = item.bounds
        if item.shape in {ShapeKind.LINE, ShapeKind.ARROW}:
            return (
                Point(bounds.x, bounds.y + bounds.height / 2),
                Point(bounds.x + bounds.width, bounds.y + bounds.height / 2),
            )
        if item.shape is ShapeKind.POLYLINE:
            return (
                Point(bounds.x, bounds.y + bounds.height),
                Point(bounds.x + bounds.width / 2, bounds.y),
                Point(bounds.x + bounds.width, bounds.y + bounds.height),
            )
        if item.shape is ShapeKind.POLYGON:
            return (
                Point(bounds.x + bounds.width / 2, bounds.y),
                Point(bounds.x + bounds.width, bounds.y + bounds.height),
                Point(bounds.x, bounds.y + bounds.height),
            )
        return ()

    nodes = tuple(
        VectorNode(
            item.id,
            item.shape.value,
            Rect(item.bounds.x, item.bounds.y, item.bounds.width, item.bounds.height),
            item.text,
            item.fill,
            item.stroke,
            item.rotation,
            shape_points(item),
            item.locked
            or next((layer.locked for layer in diagram.layers if layer.id == item.layer_id), False),
            item.asset_id,
        )
        for item in sorted(shapes.values(), key=lambda value: (value.z_index, value.id))
    )
    edges = _add_connector_bridges(
        tuple(
            VectorEdge(
                item.id,
                _connector_points(item, shapes),
                item.label,
                arrow_start=item.arrow_start,
                arrow_end=item.arrow_end,
            )
            for item in diagram.objects
            if isinstance(item, ConnectorObject)
            and item.layer_id in visible_layers
            and item.source_id in shapes
            and item.target_id in shapes
        )
    )
    if not nodes:
        marker = VectorNode(
            f"{diagram.id}:empty",
            ShapeKind.ROUNDED_RECTANGLE.value,
            Rect(0.0, 0.0, 360.0, 120.0),
            f"{diagram.title}\nEmpty free-form canvas",
            "#f8fafc",
            "#94a3b8",
        )
        return VectorScene(
            diagram.id,
            diagram.title,
            (marker,),
            (),
            marker.bounds.expanded(_MARGIN),
            "freeform",
            tuple(VectorGuide(item.id, item.orientation, item.position) for item in diagram.guides),
            diagram.grid_size,
        )
    return VectorScene(
        diagram.id,
        diagram.title,
        nodes,
        edges,
        _vector_bounds(nodes, edges).expanded(_MARGIN),
        "freeform",
        tuple(VectorGuide(item.id, item.orientation, item.position) for item in diagram.guides),
        diagram.grid_size,
    )


def _vector_bounds(nodes: tuple[VectorNode, ...], edges: tuple[VectorEdge, ...]) -> Rect:
    parts = [node.bounds for node in nodes]
    for edge in edges:
        projected = projected_edge_points(edge)
        if projected:
            xs = [point.x for point in projected]
            ys = [point.y for point in projected]
            parts.append(Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)))
    return union_rects(tuple(parts))
