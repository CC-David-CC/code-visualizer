"""Viewport-independent deterministic SVG, PNG, and PDF document export."""

from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass, replace
from enum import StrEnum
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageDraw, ImageFont

from code_visualizer.asset_management import resolve_project_asset, verify_managed_asset
from code_visualizer.domain.assets import ManagedAsset
from code_visualizer.domain.drakon import DrakonDiagram
from code_visualizer.domain.freeform import FreeformDiagram
from code_visualizer.domain.mindmap import MindMapDiagram
from code_visualizer.domain.project import ProjectDocument
from code_visualizer.rendering.geometry import Point, Rect
from code_visualizer.rendering.scene import DiagramScene, layout_drakon
from code_visualizer.rendering.svg import scene_to_svg
from code_visualizer.rendering.vector_scene import (
    VectorEdge,
    VectorNode,
    VectorScene,
    layout_freeform,
    layout_mind_map,
    projected_edge_points,
)
from code_visualizer.rendering.vector_svg import vector_scene_to_svg


class ExportFormat(StrEnum):
    SVG = "svg"
    PNG = "png"
    PDF = "pdf"


@dataclass(frozen=True, slots=True)
class ExportOptions:
    margin: float = 24.0
    scale: float = 1.0
    dpi: int = 96
    transparent: bool = False
    background: str = "#f8fafc"
    asset_root: Path | None = None
    managed_assets: tuple[ManagedAsset, ...] = ()


@dataclass(frozen=True, slots=True)
class ExportResult:
    path: Path
    format: ExportFormat
    width: int
    height: int
    sha256: str
    font_substitutions: tuple[str, ...] = ()


type RenderScene = DiagramScene | VectorScene
DEFAULT_EXPORT_OPTIONS = ExportOptions()


def project_document(document: ProjectDocument, *, margin: float = 24.0) -> RenderScene:
    scene: RenderScene
    if isinstance(document, DrakonDiagram):
        scene = layout_drakon(document)
    elif isinstance(document, MindMapDiagram):
        scene = layout_mind_map(document)
    elif isinstance(document, FreeformDiagram):
        scene = layout_freeform(document)
    else:
        raise TypeError(type(document).__name__)
    return replace(scene, bounds=scene.bounds.expanded(max(0.0, margin)))


def _asset_images(options: ExportOptions) -> dict[str, bytes]:
    if options.asset_root is None:
        return {}
    result: dict[str, bytes] = {}
    for asset in options.managed_assets:
        if not verify_managed_asset(options.asset_root, asset):
            continue
        try:
            result[asset.id] = resolve_project_asset(
                options.asset_root,
                asset.relative_path,
            ).read_bytes()
        except (OSError, ValueError):
            continue
    return result


def document_to_svg(
    document: ProjectDocument,
    *,
    margin: float = 24.0,
    options: ExportOptions | None = None,
) -> str:
    scene = project_document(document, margin=margin)
    if isinstance(scene, DiagramScene):
        return scene_to_svg(scene)
    return vector_scene_to_svg(scene, images=_asset_images(options or ExportOptions()))


def _font(size: int, *, mono: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    name = "DejaVuSansMono.ttf" if mono else "DejaVuSans.ttf"
    path = Path(__file__).resolve().parents[1] / "resources" / "fonts" / name
    try:
        return ImageFont.truetype(str(path), size=size)
    except OSError:
        return ImageFont.load_default()


def _xy(point: Point, bounds: Rect, scale: float) -> tuple[float, float]:
    return ((point.x - bounds.x) * scale, (point.y - bounds.y) * scale)


def _box(rect: Rect, bounds: Rect, scale: float) -> tuple[float, float, float, float]:
    return (
        (rect.x - bounds.x) * scale,
        (rect.y - bounds.y) * scale,
        (rect.right - bounds.x) * scale,
        (rect.bottom - bounds.y) * scale,
    )


def _arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[float, float],
    end: tuple[float, float],
    color: str,
    scale: float,
) -> None:
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    length = 9.0 * scale
    spread = 0.55
    left = (
        end[0] - math.cos(angle - spread) * length,
        end[1] - math.sin(angle - spread) * length,
    )
    right = (
        end[0] - math.cos(angle + spread) * length,
        end[1] - math.sin(angle + spread) * length,
    )
    draw.polygon((end, left, right), fill=color)


def _draw_drakon(
    draw: ImageDraw.ImageDraw,
    scene: DiagramScene,
    scale: float,
) -> None:
    bounds = scene.bounds
    width = max(1, round(2 * scale))
    for route in scene.routes:
        draw.line(
            (_xy(route.segment.start, bounds, scale), _xy(route.segment.end, bounds, scale)),
            fill="#111827",
            width=width,
        )
        if route.arrow_at_end:
            _arrow(
                draw,
                _xy(route.segment.start, bounds, scale),
                _xy(route.segment.end, bounds, scale),
                "#111827",
                scale,
            )
    code_font = _font(max(8, round(13 * scale)), mono=True)
    for node in scene.nodes:
        outline = tuple(
            _xy(point.translated(node.origin.x, node.origin.y), bounds, scale)
            for point in node.shape.outline
        )
        if node.shape.corner_radius and len(outline) == 4:
            draw.rounded_rectangle(
                _box(node.bounds, bounds, scale),
                radius=node.shape.corner_radius * scale,
                fill="#ffffff",
                outline="#111827",
                width=width,
            )
        else:
            draw.polygon(outline, fill="#ffffff", outline="#111827", width=width)
        for divider in node.shape.dividers:
            draw.line(
                (
                    _xy(divider.start.translated(node.origin.x, node.origin.y), bounds, scale),
                    _xy(divider.end.translated(node.origin.x, node.origin.y), bounds, scale),
                ),
                fill="#111827",
                width=width,
            )
        for block in node.shape.text_blocks:
            safe = block.safe_bounds.translated(node.origin.x, node.origin.y)
            x = (safe.x - bounds.x) * scale
            y = (safe.y - bounds.y) * scale
            line_height = safe.height * scale / max(1, len(block.lines))
            for index, line in enumerate(block.lines):
                draw.text((x, y + index * line_height), line, fill="#111827", font=code_font)
    label_font = _font(max(8, round(12 * scale)))
    for label in scene.labels:
        draw.text(
            ((label.bounds.x - bounds.x) * scale, (label.bounds.y - bounds.y) * scale),
            label.text,
            fill="#111827",
            font=label_font,
        )


def _rotated_rect(node: VectorNode) -> tuple[Point, ...]:
    bounds = node.bounds
    corners = (
        Point(bounds.left, bounds.top),
        Point(bounds.right, bounds.top),
        Point(bounds.right, bounds.bottom),
        Point(bounds.left, bounds.bottom),
    )
    if not node.rotation:
        return corners
    angle = math.radians(node.rotation)
    center = bounds.center
    return tuple(
        Point(
            center.x
            + (point.x - center.x) * math.cos(angle)
            - (point.y - center.y) * math.sin(angle),
            center.y
            + (point.x - center.x) * math.sin(angle)
            + (point.y - center.y) * math.cos(angle),
        )
        for point in corners
    )


def _draw_edge(
    draw: ImageDraw.ImageDraw,
    edge: VectorEdge,
    bounds: Rect,
    scale: float,
) -> None:
    points = tuple(_xy(point, bounds, scale) for point in projected_edge_points(edge))
    if len(points) < 2:
        return
    draw.line(points, fill=edge.stroke, width=max(1, round(2 * scale)), joint="curve")
    if edge.arrow_start:
        _arrow(draw, points[1], points[0], edge.stroke, scale)
    if edge.arrow_end:
        _arrow(draw, points[-2], points[-1], edge.stroke, scale)


def _draw_vector(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    scene: VectorScene,
    scale: float,
    images: dict[str, bytes],
) -> None:
    bounds = scene.bounds
    font = _font(max(8, round(13 * scale)))
    for edge in scene.edges:
        _draw_edge(draw, edge, bounds, scale)
        if edge.label and edge.points:
            point = _xy(edge.points[len(edge.points) // 2], bounds, scale)
            draw.text((point[0] + 5, point[1] - 18), edge.label, fill=edge.stroke, font=font)
    line_width = max(1, round(2 * scale))
    for node in scene.nodes:
        box = _box(node.bounds, bounds, scale)
        if node.kind == "ellipse":
            draw.ellipse(box, fill=node.fill, outline=node.stroke, width=line_width)
        elif node.kind in {"line", "arrow", "polyline", "polygon"} and node.points:
            points = tuple(_xy(point, bounds, scale) for point in node.points)
            if node.kind == "polygon":
                draw.polygon(points, fill=node.fill, outline=node.stroke)
            else:
                draw.line(points, fill=node.stroke, width=line_width, joint="curve")
                if node.kind == "arrow" and len(points) >= 2:
                    _arrow(draw, points[-2], points[-1], node.stroke, scale)
        elif node.rotation:
            draw.polygon(
                tuple(_xy(point, bounds, scale) for point in _rotated_rect(node)),
                fill=node.fill,
                outline=node.stroke,
            )
        elif node.kind in {"rounded_rectangle", "mind_root", "mind_topic", "reusable"}:
            draw.rounded_rectangle(
                box,
                radius=14 * scale,
                fill=node.fill,
                outline=node.stroke,
                width=line_width,
            )
        else:
            draw.rectangle(box, fill=node.fill, outline=node.stroke, width=line_width)
        image_data = images.get(node.asset_id or "") if node.kind == "image" else None
        if image_data is not None:
            try:
                with Image.open(BytesIO(image_data)) as opened:
                    source = opened.convert("RGBA")
                    available_width = max(1, round((node.bounds.width - 4) * scale))
                    available_height = max(1, round((node.bounds.height - 4) * scale))
                    source.thumbnail((available_width, available_height), Image.Resampling.LANCZOS)
                    center = _xy(node.bounds.center, bounds, scale)
                    destination = (
                        round(center[0] - source.width / 2),
                        round(center[1] - source.height / 2),
                    )
                    image.paste(source, destination, source)
            except (OSError, ValueError):
                image_data = None
        if node.text and image_data is None:
            text_box = draw.multiline_textbbox((0, 0), node.text, font=font, align="center")
            text_width = text_box[2] - text_box[0]
            text_height = text_box[3] - text_box[1]
            center = _xy(node.bounds.center, bounds, scale)
            draw.multiline_text(
                (center[0] - text_width / 2, center[1] - text_height / 2),
                node.text,
                fill="#0f172a",
                font=font,
                align="center",
            )


def document_to_png(
    document: ProjectDocument,
    *,
    options: ExportOptions = DEFAULT_EXPORT_OPTIONS,
) -> bytes:
    if options.scale <= 0 or options.dpi <= 0:
        raise ValueError("PNG scale and DPI must be positive")
    scene = project_document(document, margin=options.margin)
    width = max(1, math.ceil(scene.bounds.width * options.scale))
    height = max(1, math.ceil(scene.bounds.height * options.scale))
    background = (0, 0, 0, 0) if options.transparent else options.background
    mode = "RGBA" if options.transparent else "RGB"
    image = Image.new(mode, (width, height), background)
    draw = ImageDraw.Draw(image)
    if isinstance(scene, DiagramScene):
        _draw_drakon(draw, scene, options.scale)
    else:
        _draw_vector(image, draw, scene, options.scale, _asset_images(options))
    output = BytesIO()
    image.save(output, format="PNG", dpi=(options.dpi, options.dpi), compress_level=9)
    return output.getvalue()


def _pdf_escape(text: str) -> str:
    safe = text.encode("latin-1", errors="replace").decode("latin-1")
    return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _pdf_document(width: float, height: float, content: str) -> bytes:
    stream = content.encode("latin-1", errors="replace")
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width:.3f} {height:.3f}] "
            "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ).encode("ascii"),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length "
        + str(len(stream)).encode("ascii")
        + b" >>\nstream\n"
        + stream
        + b"endstream",
    )
    result = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, value in enumerate(objects, start=1):
        offsets.append(len(result))
        result.extend(f"{index} 0 obj\n".encode("ascii"))
        result.extend(value)
        result.extend(b"\nendobj\n")
    xref = len(result)
    result.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    result.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        result.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    result.extend(
        (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n").encode(
            "ascii"
        )
    )
    return bytes(result)


def _pdf_line(points: tuple[Point, ...], bounds: Rect) -> str:
    if len(points) < 2:
        return ""
    transformed = tuple(Point(point.x - bounds.x, bounds.bottom - point.y) for point in points)
    commands = [f"{transformed[0].x:.3f} {transformed[0].y:.3f} m"]
    commands.extend(f"{point.x:.3f} {point.y:.3f} l" for point in transformed[1:])
    commands.append("S")
    return "\n".join(commands)


def document_to_pdf(document: ProjectDocument, *, margin: float = 24.0) -> bytes:
    scene = project_document(document, margin=margin)
    bounds = scene.bounds
    commands = ["0.97 0.98 0.99 rg", f"0 0 {bounds.width:.3f} {bounds.height:.3f} re f"]
    commands.append("0.12 0.16 0.22 RG 2 w")
    if isinstance(scene, DiagramScene):
        for route in scene.routes:
            commands.append(_pdf_line((route.segment.start, route.segment.end), bounds))
        for node in scene.nodes:
            points = tuple(
                point.translated(node.origin.x, node.origin.y) for point in node.shape.outline
            )
            commands.append(_pdf_line((*points, points[0]), bounds))
            for block in node.shape.text_blocks:
                safe = block.safe_bounds.translated(node.origin.x, node.origin.y)
                for index, line in enumerate(block.lines):
                    x = safe.x - bounds.x
                    y = bounds.bottom - safe.y - 12 - index * 14
                    commands.append(f"BT /F1 10 Tf {x:.3f} {y:.3f} Td ({_pdf_escape(line)}) Tj ET")
    else:
        for edge in scene.edges:
            commands.append(_pdf_line(projected_edge_points(edge), bounds))
        for vector_node in scene.nodes:
            rect = vector_node.bounds
            x = rect.x - bounds.x
            y = bounds.bottom - rect.bottom
            commands.append(f"{x:.3f} {y:.3f} {rect.width:.3f} {rect.height:.3f} re S")
            for index, line in enumerate(vector_node.text.splitlines()):
                text_x = x + 8
                text_y = y + rect.height / 2 - index * 14
                commands.append(
                    f"BT /F1 10 Tf {text_x:.3f} {text_y:.3f} Td ({_pdf_escape(line)}) Tj ET"
                )
    content = "\n".join(command for command in commands if command) + "\n"
    return _pdf_document(bounds.width, bounds.height, content)


def export_document(
    document: ProjectDocument,
    path: Path,
    *,
    format: ExportFormat | None = None,
    options: ExportOptions = DEFAULT_EXPORT_OPTIONS,
) -> ExportResult:
    resolved_format = format or ExportFormat(path.suffix.lower().lstrip("."))
    if resolved_format is ExportFormat.SVG:
        data = document_to_svg(document, margin=options.margin, options=options).encode("utf-8")
    elif resolved_format is ExportFormat.PNG:
        data = document_to_png(document, options=options)
    else:
        data = document_to_pdf(document, margin=options.margin)
    scene = project_document(document, margin=options.margin)
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.{uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return ExportResult(
        target,
        resolved_format,
        max(1, math.ceil(scene.bounds.width * options.scale)),
        max(1, math.ceil(scene.bounds.height * options.scale)),
        hashlib.sha256(data).hexdigest(),
        () if resolved_format is not ExportFormat.PDF else ("DejaVu Sans → Helvetica",),
    )
