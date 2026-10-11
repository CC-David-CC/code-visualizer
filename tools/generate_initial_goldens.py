"""Regenerate initial vector contact-sheet fixtures at 1x and 2x."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from code_visualizer.rendering.contact_sheet import (
    CONTACT_SHEET_HEIGHT,
    CONTACT_SHEET_WIDTH,
    initial_contact_sheet_svg,
    initial_if_layout_scene,
    initial_if_layout_svg,
)
from code_visualizer.ui_qt.font_support import register_application_fonts


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    application = QGuiApplication.instance() or QGuiApplication([])
    del application
    register_application_fonts()
    root = Path(__file__).resolve().parents[1]
    target = root / "assets" / "goldens"
    target.mkdir(parents=True, exist_ok=True)
    svg = initial_contact_sheet_svg()
    (target / "initial-icon-contact-sheet.svg").write_text(svg, encoding="utf-8")
    _render_pngs(
        svg, target / "initial-icon-contact-sheet", CONTACT_SHEET_WIDTH, CONTACT_SHEET_HEIGHT
    )
    if_scene = initial_if_layout_scene()
    if_svg = initial_if_layout_svg()
    (target / "initial-if-layout.svg").write_text(if_svg, encoding="utf-8")
    _render_pngs(
        if_svg,
        target / "initial-if-layout",
        if_scene.bounds.width,
        if_scene.bounds.height,
    )
    return 0


def _render_pngs(svg: str, target: Path, width: float, height: float) -> None:
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        raise RuntimeError(f"Generated SVG is invalid: {target.name}")
    for scale in (1, 2):
        image = QImage(
            round(width * scale),
            round(height * scale),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        image.fill(QColor("#dff4f8"))
        painter = QPainter(image)
        painter.scale(scale, scale)
        renderer.render(painter)
        painter.end()
        suffix = "" if scale == 1 else "@2x"
        if not image.save(str(target.with_name(f"{target.name}{suffix}.png")), "PNG"):
            raise RuntimeError("Could not save contact-sheet PNG")


if __name__ == "__main__":
    raise SystemExit(main())
