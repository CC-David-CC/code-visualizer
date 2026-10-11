"""Readable text projection over the same semantic graph used by visual lenses."""

from __future__ import annotations

import json
from dataclasses import dataclass

from code_visualizer.domain.semantic import SemanticProjection


@dataclass(frozen=True, slots=True)
class SemanticTextProjection:
    project_id: str
    revision: int
    title: str
    source: str
    line_semantic_ids: tuple[str | None, ...]


def render_semantic_text(projection: SemanticProjection) -> SemanticTextProjection:
    """Render deterministic human-readable text with a semantic identity per line."""

    title = projection.title or projection.kind.value.replace("_", " ").title()
    lines = [
        f"view {json.dumps(title, ensure_ascii=False)}",
        f"revision {projection.revision}",
        "",
        "objects",
    ]
    line_ids: list[str | None] = [None] * len(lines)
    nodes = sorted(
        projection.nodes,
        key=lambda item: (item.kind.value, item.label.casefold(), item.id),
    )
    label_by_id = {item.id: item.label for item in projection.nodes}
    for node in nodes:
        visible_badges = (
            (*node.badges, f"{node.hidden_count} hidden") if node.hidden_count else node.badges
        )
        badges = f"  [{', '.join(visible_badges)}]" if visible_badges else ""
        lines.append(f"  {node.kind.value} {json.dumps(node.label, ensure_ascii=False)}{badges}")
        line_ids.append(node.semantic_id)
        if node.detail and node.detail != node.label:
            detail = " ".join(node.detail.split())
            lines.append(f"    detail {json.dumps(detail, ensure_ascii=False)}")
            line_ids.append(node.semantic_id)
    lines.extend(("", "relationships"))
    line_ids.extend((None, None))
    for edge in sorted(projection.edges, key=lambda item: item.id):
        source = label_by_id.get(edge.source_id, edge.source_id)
        target = label_by_id.get(edge.target_id, edge.target_id)
        visible_label = edge.label or edge.kind.value.replace("_", " ")
        if edge.active:
            visible_label += " [active]"
        lines.append(
            f"  {json.dumps(source, ensure_ascii=False)} "
            f"--{visible_label}--> {json.dumps(target, ensure_ascii=False)}"
        )
        line_ids.append(edge.id)
    return SemanticTextProjection(
        projection.project_id,
        projection.revision,
        title,
        "\n".join(lines) + "\n",
        tuple(line_ids),
    )
