"""Deterministic, self-contained SVG projection of the canonical vector scene."""

from __future__ import annotations

import html

from code_visualizer.rendering.geometry import Point
from code_visualizer.rendering.scene import DiagramScene, SceneNode


def _number(value: float) -> str:
    rounded = round(value, 3)
    return str(int(rounded)) if rounded.is_integer() else f"{rounded:.3f}".rstrip("0")


def _point(point: Point) -> str:
    return f"{_number(point.x)},{_number(point.y)}"


def _node_svg(node: SceneNode) -> list[str]:
    shape = node.shape
    bounds = node.bounds
    name = html.escape(shape.accessibility_name, quote=True)
    result = [f'<g id="{html.escape(node.object_id, quote=True)}" aria-label="{name}">']
    if shape.corner_radius and len(shape.outline) == 4:
        result.append(
            "<rect "
            f'x="{_number(bounds.x)}" y="{_number(bounds.y)}" '
            f'width="{_number(bounds.width)}" height="{_number(bounds.height)}" '
            f'rx="{_number(shape.corner_radius)}" class="icon"/>'
        )
    else:
        points = " ".join(
            _point(point.translated(node.origin.x, node.origin.y)) for point in shape.outline
        )
        result.append(f'<polygon points="{points}" class="icon"/>')
    for divider in shape.dividers:
        start = divider.start.translated(node.origin.x, node.origin.y)
        end = divider.end.translated(node.origin.x, node.origin.y)
        result.append(
            f'<line x1="{_number(start.x)}" y1="{_number(start.y)}" '
            f'x2="{_number(end.x)}" y2="{_number(end.y)}" class="divider"/>'
        )
    for block in shape.text_blocks:
        safe = block.safe_bounds.translated(node.origin.x, node.origin.y)
        line_height = safe.height / max(1, len(block.lines))
        for index, line in enumerate(block.lines):
            y = safe.y + line_height * (index + 0.72)
            result.append(
                f'<text x="{_number(safe.x)}" y="{_number(y)}" class="code">'
                f"{html.escape(line)}</text>"
            )
    result.append("</g>")
    return result


def scene_to_svg(scene: DiagramScene, *, include_background: bool = True) -> str:
    bounds = scene.bounds
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" role="img" '
        f'viewBox="{_number(bounds.x)} {_number(bounds.y)} '
        f'{_number(bounds.width)} {_number(bounds.height)}" '
        f'width="{_number(bounds.width)}" height="{_number(bounds.height)}">',
        "<title>DRAKON algorithm</title>",
        "<style>"
        ".field{fill:#dff4f8}.route,.divider{fill:none;stroke:#111827;stroke-width:2}"
        ".icon{fill:#fff;stroke:#111827;stroke-width:2;stroke-linejoin:round}"
        ".code,.route-label{fill:#111827;font-family:'DejaVu Sans Mono',monospace;"
        "font-size:13px}"
        "</style>",
    ]
    if include_background:
        lines.append(
            f'<rect x="{_number(bounds.x)}" y="{_number(bounds.y)}" '
            f'width="{_number(bounds.width)}" height="{_number(bounds.height)}" '
            'class="field"/>'
        )
    for route in scene.routes:
        segment = route.segment
        boundary = (
            f"{route.boundary.sequence_id}:{route.boundary.index}"
            if route.boundary is not None
            else ""
        )
        lines.append(
            f'<line id="{route.id}" data-insertion-boundary="{html.escape(boundary)}" '
            f'x1="{_number(segment.start.x)}" y1="{_number(segment.start.y)}" '
            f'x2="{_number(segment.end.x)}" y2="{_number(segment.end.y)}" class="route"/>'
        )
    for node in scene.nodes:
        lines.extend(_node_svg(node))
    for label in scene.labels:
        lines.append(
            f'<text x="{_number(label.bounds.x)}" '
            f'y="{_number(label.bounds.y + label.bounds.height * 0.75)}" '
            f'class="route-label">{html.escape(label.text)}</text>'
        )
    lines.append("</svg>")
    return "\n".join(lines) + "\n"
