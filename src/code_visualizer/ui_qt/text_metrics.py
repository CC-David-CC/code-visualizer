"""Qt-backed implementation of the core text-measurement port."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QFont, QFontMetricsF

from code_visualizer.rendering.text import TextSize
from code_visualizer.ui_qt.font_support import register_application_fonts


@dataclass(slots=True)
class QtTextMeasurer:
    code_font: QFont
    title_font: QFont

    @classmethod
    def create(cls) -> QtTextMeasurer:
        code = QFont(register_application_fonts().code)
        code.setPointSizeF(10.0)
        title = QFont(code)
        title.setBold(True)
        return cls(code, title)

    @property
    def line_height(self) -> float:
        return QFontMetricsF(self.code_font).height()

    def measure_line(self, text: str, *, role: str = "code") -> TextSize:
        font = self.title_font if role in {"title", "branch"} else self.code_font
        metrics = QFontMetricsF(font)
        return TextSize(metrics.horizontalAdvance(text.expandtabs(4)), metrics.height())
