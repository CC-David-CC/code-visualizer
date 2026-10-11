"""Create editable, semantically anchored compositions from disposable lenses."""

from __future__ import annotations

import hashlib
from collections import defaultdict, deque

from code_visualizer.application.projection_layout import projection_positions
from code_visualizer.domain.freeform import (
    ConnectorObject,
    FreeformDiagram,
    Rect,
    ShapeKind,
    ShapeObject,
)
from code_visualizer.domain.mindmap import CrossLink, MindMapDiagram, Topic
from code_visualizer.domain.project import ProjectDocument
from code_visualizer.domain.projection import ProjectionDefinition, ProjectionViewTarget
from code_visualizer.domain.semantic import (
    SemanticObjectKind,
    SemanticProjection,
    SemanticRelationKind,
)


def materialize_projection(
    projection: SemanticProjection,
    target: ProjectionViewTarget,
    *,
    document_id: str,
    title: str,
    definition: ProjectionDefinition | None = None,
) -> ProjectDocument:
    if target is ProjectionViewTarget.MIND_MAP:
        return _mind_map(projection, document_id, title, definition)
    return _freeform(projection, document_id, title, definition)


def _stable_id(prefix: str, document_id: str, semantic_id: str) -> str:
    digest = hashlib.sha256(f"{document_id}\0{semantic_id}".encode()).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _mind_map(
    projection: SemanticProjection,
    document_id: str,
    title: str,
    definition: ProjectionDefinition | None,
) -> MindMapDiagram:
    nodes = {item.id: item for item in projection.nodes}
    topic_ids = {node_id: _stable_id("topic", document_id, node_id) for node_id in nodes}
    hierarchy_kinds = {
        SemanticRelationKind.CONTAINS,
        SemanticRelationKind.CONCEPTUALLY_CONTAINS,
    }
    hierarchical_edges = tuple(
        edge
        for edge in projection.edges
        if edge.kind in hierarchy_kinds and edge.source_id in nodes and edge.target_id in nodes
    )
    incoming = dict.fromkeys(nodes, 0)
    outgoing: dict[str, list[str]] = defaultdict(list)
    edge_for_pair: dict[tuple[str, str], str] = {}
    for edge in hierarchical_edges:
        outgoing[edge.source_id].append(edge.target_id)
        incoming[edge.target_id] += 1
        edge_for_pair.setdefault((edge.source_id, edge.target_id), edge.id)
    roots = sorted(node_id for node_id, count in incoming.items() if count == 0)
    if not roots and nodes:
        roots = [sorted(nodes)[0]]
    tree_children: dict[str, list[str]] = defaultdict(list)
    tree_edge_ids: set[str] = set()
    visited: set[str] = set()
    parented: set[str] = set()
    pending = deque(roots)
    while pending:
        source = pending.popleft()
        if source in visited:
            continue
        visited.add(source)
        for target_id in sorted(set(outgoing.get(source, ()))):
            if target_id in visited or target_id in parented:
                continue
            tree_children[source].append(target_id)
            parented.add(target_id)
            tree_edge_ids.add(edge_for_pair[(source, target_id)])
            pending.append(target_id)
    top_level = list(roots)
    for node_id in sorted(nodes):
        if node_id not in visited:
            top_level.append(node_id)

    def make_topic(node_id: str) -> Topic:
        node = nodes[node_id]
        notes = "\n".join(item for item in (node.detail, " | ".join(node.badges)) if item)
        return Topic(
            topic_ids[node_id],
            node.label,
            tuple(make_topic(child_id) for child_id in tree_children.get(node_id, ())),
            notes=notes,
            semantic_id=(None if node.kind is SemanticObjectKind.GROUP else node.semantic_id),
        )

    root = Topic(
        _stable_id("topic_root", document_id, projection.definition_id or projection.kind.value),
        title,
        tuple(make_topic(node_id) for node_id in dict.fromkeys(top_level)),
        notes=f"Editable semantic composition from {projection.title or projection.kind.value}.",
    )
    cross_links = tuple(
        CrossLink(
            _stable_id("crosslink", document_id, edge.id),
            topic_ids[edge.source_id],
            topic_ids[edge.target_id],
            edge.label or edge.kind.value.replace("_", " "),
            None if edge.id.startswith("projection-edge:") else edge.id,
        )
        for edge in projection.edges
        if edge.id not in tree_edge_ids
        and edge.source_id in topic_ids
        and edge.target_id in topic_ids
    )
    return MindMapDiagram(
        document_id,
        title,
        root,
        cross_links,
        live_projection=definition,
    )


def _freeform(
    projection: SemanticProjection,
    document_id: str,
    title: str,
    definition: ProjectionDefinition | None,
) -> FreeformDiagram:
    positions = projection_positions(projection)
    shape_ids = {node.id: _stable_id("shape", document_id, node.id) for node in projection.nodes}
    shapes: list[ShapeObject] = []
    for index, node in enumerate(projection.nodes):
        x, y = positions.get(node.id, ((index % 4) * 250.0, (index // 4) * 120.0))
        width = min(390.0, max(180.0, 28.0 + len(node.label) * 7.2))
        shapes.append(
            ShapeObject(
                shape_ids[node.id],
                ShapeKind.ROUNDED_RECTANGLE,
                Rect(x, y, width, 72.0),
                node.label,
                z_index=index,
                fill=_fill_for(node.kind),
                stroke="#5f6b78",
                semantic_id=(None if node.kind is SemanticObjectKind.GROUP else node.semantic_id),
            )
        )
    connectors = tuple(
        ConnectorObject(
            _stable_id("connector", document_id, edge.id),
            shape_ids[edge.source_id],
            shape_ids[edge.target_id],
            label=edge.label or edge.kind.value.replace("_", " "),
            semantic_relation_id=(None if edge.id.startswith("projection-edge:") else edge.id),
        )
        for edge in projection.edges
        if edge.source_id in shape_ids and edge.target_id in shape_ids
    )
    return FreeformDiagram(
        document_id,
        title,
        (*shapes, *connectors),
        live_projection=definition,
    )


def _fill_for(kind: SemanticObjectKind) -> str:
    return {
        SemanticObjectKind.PROJECT: "#d8e3ef",
        SemanticObjectKind.MODULE: "#dde7d8",
        SemanticObjectKind.CLASS: "#e8dfcf",
        SemanticObjectKind.FUNCTION: "#d9e5f2",
        SemanticObjectKind.OPERATION: "#e8edf2",
        SemanticObjectKind.SYMBOL: "#dce9df",
        SemanticObjectKind.CONCEPT: "#eadff0",
        SemanticObjectKind.GROUP: "#e2e8f0",
    }.get(kind, "#e7e9ec")
