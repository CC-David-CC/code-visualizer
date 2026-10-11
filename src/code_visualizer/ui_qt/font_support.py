"""Application-font registration for reproducible UI and export text."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from importlib.resources import as_file, files

from PySide6.QtGui import QFontDatabase, QGuiApplication


@dataclass(frozen=True, slots=True)
class ApplicationFonts:
    interface: str
    code: str


def _register(filename: str) -> str:
    resource = files("code_visualizer").joinpath(f"resources/fonts/{filename}")
    with as_file(resource) as path:
        font_id = QFontDatabase.addApplicationFont(str(path))
    if font_id < 0:
        raise RuntimeError(f"Could not register bundled font {filename}")
    families = QFontDatabase.applicationFontFamilies(font_id)
    if not families:
        raise RuntimeError(f"Bundled font {filename} did not expose a family")
    return families[0]


@cache
def register_application_fonts() -> ApplicationFonts:
    if QGuiApplication.instance() is None:
        raise RuntimeError("A QGuiApplication must exist before registering fonts")
    return ApplicationFonts(
        interface=_register("DejaVuSans.ttf"),
        code=_register("DejaVuSansMono.ttf"),
    )
