"""Deterministic presentation-neutral positions for general semantic projections."""

from __future__ import annotations

from collections import defaultdict, deque
from math import ceil, cos, sin, sqrt, tau

from code_visualizer.domain.projection import ProjectionLayout
from code_visualizer.domain.semantic import SemanticProjection


def projection_positions(projection: SemanticProjection) -> dict[str, tuple[float, float]]:
    nodes = {item.id for item in projection.nodes}
    incoming: dict[str, int] = dict.fromkeys(nodes, 0)
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in projection.edges:
        if edge.source_id in nodes and edge.target_id in nodes:
            outgoing[edge.source_id].append(edge.target_id)
            incoming[edge.target_id] += 1
    roots = sorted(item for item, count in incoming.items() if count == 0)
    if not roots and nodes:
        roots = [sorted(nodes)[0]]
    level: dict[str, int] = {}
    pending = deque((item, 0) for item in roots)
    while pending:
        current, depth = pending.popleft()
        if current in level and level[current] <= depth:
            continue
        level[current] = depth
        for target in sorted(outgoing[current]):
            pending.append((target, depth + 1))
    for orphan in sorted(nodes - level.keys()):
        level[orphan] = 0
    try:
        layout = ProjectionLayout(projection.layout)
    except ValueError:
        layout = ProjectionLayout.HIERARCHICAL
    if layout is ProjectionLayout.RADIAL and nodes:
        identifiers = sorted(nodes)
        radius = max(300.0, len(identifiers) * 72.0)
        return {
            identifier: (
                cos(tau * index / len(identifiers)) * radius,
                sin(tau * index / len(identifiers)) * radius,
            )
            for index, identifier in enumerate(identifiers)
        }
    if layout is ProjectionLayout.GRID and nodes:
        columns = max(1, ceil(sqrt(len(nodes))))
        return {
            identifier: ((index % columns) * 460.0, (index // columns) * 260.0)
            for index, identifier in enumerate(sorted(nodes))
        }
    by_level: dict[int, list[str]] = defaultdict(list)
    for item, depth in level.items():
        by_level[depth].append(item)
    result: dict[str, tuple[float, float]] = {}
    horizontal = layout is ProjectionLayout.HORIZONTAL
    for depth, identifiers in sorted(by_level.items()):
        for index, identifier in enumerate(sorted(identifiers)):
            if horizontal:
                result[identifier] = (depth * 460.0, index * 240.0)
            else:
                result[identifier] = (index * 460.0, depth * 260.0)
    return result
