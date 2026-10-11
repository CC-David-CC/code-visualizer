"""Sanitized deterministic SVG for generic mind-map/free-form vector scenes."""

from __future__ import annotations

import base64
import html

from code_visualizer.rendering.geometry import Point
from code_visualizer.rendering.vector_scene import (
    VectorEdge,
    VectorNode,
    VectorScene,
    projected_edge_points,
)


def _number(value: float) -> str:
    rounded = round(value, 3)
    return str(int(rounded)) if rounded.is_integer() else f"{rounded:.3f}".rstrip("0")


def _points(points: tuple[Point, ...]) -> str:
    return " ".join(f"{_number(point.x)},{_number(point.y)}" for point in points)


def _edge(edge: VectorEdge) -> str:
    dash = ' stroke-dasharray="7 5"' if edge.cross_link else ""
    marker_start = ' marker-start="url(#arrow)"' if edge.arrow_start else ""
    marker_end = ' marker-end="url(#arrow)"' if edge.arrow_end else ""
    bridge_data = f' data-bridges="{len(edge.bridges)}"' if edge.bridges else ""
    return (
        f'<polyline id="{html.escape(edge.object_id, quote=True)}" '
        f'points="{_points(projected_edge_points(edge))}" fill="none" '
        f'stroke="{html.escape(edge.stroke)}" stroke-width="2"{dash}{marker_start}'
        f"{marker_end}{bridge_data}/>"
    )


def _node(node: VectorNode, images: dict[str, bytes]) -> list[str]:
    bounds = node.bounds
    transform = ""
    if node.rotation:
        center = bounds.center
        transform = (
            f' transform="rotate({_number(node.rotation)} {_number(center.x)} {_number(center.y)})"'
        )
    common = (
        f'id="{html.escape(node.object_id, quote=True)}" '
        f'stroke="{html.escape(node.stroke)}" stroke-width="2"{transform}'
    )
    if node.kind in {"ellipse"}:
        shape = (
            f'<ellipse {common} fill="{html.escape(node.fill)}" '
            f'cx="{_number(bounds.center.x)}" '
            f'cy="{_number(bounds.center.y)}" rx="{_number(bounds.width / 2)}" '
            f'ry="{_number(bounds.height / 2)}"/>'
        )
    elif node.kind in {"polygon", "polyline", "line", "arrow"} and node.points:
        tag = "polygon" if node.kind == "polygon" else "polyline"
        fill = html.escape(node.fill) if tag == "polygon" else "none"
        marker = ' marker-end="url(#arrow)"' if node.kind == "arrow" else ""
        shape = f'<{tag} {common} points="{_points(node.points)}" fill="{fill}"{marker}/>'
    else:
        radius = 14 if node.kind in {"rounded_rectangle", "mind_root", "mind_topic"} else 0
        shape = (
            f'<rect {common} fill="{html.escape(node.fill)}" '
            f'x="{_number(bounds.x)}" y="{_number(bounds.y)}" '
            f'width="{_number(bounds.width)}" height="{_number(bounds.height)}" '
            f'rx="{radius}"/>'
        )
    result = [shape]
    image_data = images.get(node.asset_id or "") if node.kind == "image" else None
    if image_data is not None:
        encoded = base64.b64encode(image_data).decode("ascii")
        result.append(
            f'<image x="{_number(bounds.x + 2)}" y="{_number(bounds.y + 2)}" '
            f'width="{_number(max(0.0, bounds.width - 4))}" '
            f'height="{_number(max(0.0, bounds.height - 4))}" '
            'preserveAspectRatio="xMidYMid meet" '
            f'href="data:image/png;base64,{encoded}"/>'
        )
    lines = node.text.splitlines() or [""]
    line_height = 17.0
    start_y = bounds.center.y - (len(lines) - 1) * line_height / 2
    for index, line in enumerate(() if image_data is not None else lines):
        result.append(
            f'<text x="{_number(bounds.center.x)}" '
            f'y="{_number(start_y + index * line_height + 5)}" '
            'text-anchor="middle" class="label">'
            f"{html.escape(line)}</text>"
        )
    return result


def vector_scene_to_svg(
    scene: VectorScene,
    *,
    include_background: bool = True,
    images: dict[str, bytes] | None = None,
) -> str:
    bounds = scene.bounds
    title = html.escape(scene.title)
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" role="img" '
        f'viewBox="{_number(bounds.x)} {_number(bounds.y)} {_number(bounds.width)} '
        f'{_number(bounds.height)}" width="{_number(bounds.width)}" '
        f'height="{_number(bounds.height)}">',
        f"<title>{title}</title>",
        '<defs><marker id="arrow" markerWidth="9" markerHeight="7" refX="8" '
        'refY="3.5" orient="auto-start-reverse"><polygon points="0 0, 9 3.5, 0 7" '
        'fill="#334155"/></marker></defs>',
        "<style>.label,.edge-label{fill:#0f172a;font-family:'DejaVu Sans',sans-serif;"
        "font-size:13px}</style>",
    ]
    if include_background:
        lines.append(
            f'<rect x="{_number(bounds.x)}" y="{_number(bounds.y)}" '
            f'width="{_number(bounds.width)}" height="{_number(bounds.height)}" '
            'fill="#f8fafc"/>'
        )
    for edge in scene.edges:
        lines.append(_edge(edge))
        if edge.label and edge.points:
            middle = edge.points[len(edge.points) // 2]
            lines.append(
                f'<text x="{_number(middle.x + 5)}" y="{_number(middle.y - 5)}" '
                f'class="edge-label">{html.escape(edge.label)}</text>'
            )
    resolved_images = images or {}
    for node in scene.nodes:
        lines.extend(_node(node, resolved_images))
    lines.append("</svg>")
    return "\n".join(lines) + "\n"
