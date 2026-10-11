"""Geometry-neutral color themes and reduced-motion application settings."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


class ThemeName(StrEnum):
    CLASSIC = "classic"
    LIGHT = "light"
    DARK = "dark"
    HIGH_CONTRAST = "high_contrast"


@dataclass(frozen=True, slots=True)
class ThemeTokens:
    window: str
    field: str
    surface: str
    text: str
    muted_text: str
    border: str
    accent: str
    selected_text: str
    diagnostic: str


THEMES: dict[ThemeName, ThemeTokens] = {
    ThemeName.CLASSIC: ThemeTokens(
        "#d8dcda",
        "#e6e4dc",
        "#f3f1eb",
        "#20252b",
        "#5a6268",
        "#899195",
        "#315f78",
        "#fbfaf6",
        "#8a3d2f",
    ),
    ThemeName.LIGHT: ThemeTokens(
        "#f1f5f9",
        "#f8fafc",
        "#ffffff",
        "#111827",
        "#475569",
        "#94a3b8",
        "#005fcc",
        "#ffffff",
        "#a1260d",
    ),
    ThemeName.DARK: ThemeTokens(
        "#111827",
        "#172033",
        "#1f2937",
        "#f9fafb",
        "#cbd5e1",
        "#526077",
        "#78b7ff",
        "#07111f",
        "#ffb4a2",
    ),
    ThemeName.HIGH_CONTRAST: ThemeTokens(
        "#000000",
        "#000000",
        "#000000",
        "#ffffff",
        "#ffffff",
        "#ffffff",
        "#ffff00",
        "#000000",
        "#ff7b7b",
    ),
}


def contrast_ratio(foreground: str, background: str) -> float:
    def luminance(value: str) -> float:
        color = QColor(value)
        channels = (color.redF(), color.greenF(), color.blueF())
        linear = tuple(
            channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        )
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    first = luminance(foreground)
    second = luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def apply_theme(
    application: QApplication,
    theme: ThemeName,
    *,
    reduced_motion: bool = False,
) -> None:
    tokens = THEMES[theme]
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(tokens.window))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(tokens.text))
    palette.setColor(QPalette.ColorRole.Base, QColor(tokens.surface))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(tokens.field))
    palette.setColor(QPalette.ColorRole.Text, QColor(tokens.text))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(tokens.muted_text))
    palette.setColor(QPalette.ColorRole.Button, QColor(tokens.field))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(tokens.text))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(tokens.surface))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(tokens.text))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(tokens.accent))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(tokens.selected_text))
    palette.setColor(QPalette.ColorRole.Link, QColor(tokens.accent))
    palette.setColor(QPalette.ColorRole.Mid, QColor(tokens.border))
    palette.setColor(QPalette.ColorRole.Midlight, QColor(tokens.field))
    palette.setColor(QPalette.ColorRole.Dark, QColor(tokens.border))
    palette.setColor(QPalette.ColorRole.Shadow, QColor(tokens.text))
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(tokens.muted_text))
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Base,
        QColor(tokens.field),
    )
    application.setPalette(palette)
    application.setProperty("codeVisualizerTheme", theme.value)
    application.setProperty("codeVisualizerReducedMotion", reduced_motion)
    application.setStyleSheet(
        "QMenuBar, QToolBar, QStatusBar {"
        f" background: {tokens.window}; color: {tokens.text}; }}"
        "QDockWidget::title, QHeaderView::section {"
        f" background: {tokens.field}; color: {tokens.text};"
        f" border: 0; border-bottom: 1px solid {tokens.border}; padding: 4px; }}"
        "QTabBar::tab {"
        f" background: {tokens.field}; color: {tokens.text};"
        f" border: 1px solid {tokens.border}; padding: 5px 10px; }}"
        "QTabBar::tab:selected {"
        f" background: {tokens.surface}; border-top: 2px solid {tokens.accent}; }}"
        "QPushButton, QToolButton, QComboBox {"
        f" background: {tokens.field}; color: {tokens.text};"
        f" border: 1px solid {tokens.border}; padding: 3px 8px; min-height: 28px; }}"
        "QPushButton:hover, QToolButton:hover, QComboBox:hover {"
        f" border-color: {tokens.accent}; }}"
        "QLineEdit, QPlainTextEdit, QTextEdit, QTreeView, QListView, QTableView {"
        f" background: {tokens.surface}; color: {tokens.text};"
        f" border: 1px solid {tokens.border}; selection-background-color: {tokens.accent};"
        f" selection-color: {tokens.selected_text}; }}"
        "QLineEdit { min-height: 28px; padding: 0 5px; }"
        "QSplitter::handle {"
        f" background: {tokens.border}; }}"
        "QPushButton:focus, QToolButton:focus, QComboBox:focus, QLineEdit:focus, "
        "QTreeView:focus, QListView:focus, QPlainTextEdit:focus {"
        f" border: 2px solid {tokens.accent}; }}"
        "QPushButton:disabled, QToolButton:disabled, QComboBox:disabled, "
        "QLineEdit:disabled {"
        f" color: {tokens.muted_text}; background: {tokens.field}; }}"
        "QWidget[diagnostic='true'] {"
        f" color: {tokens.diagnostic}; font-weight: 600; }}"
    )
