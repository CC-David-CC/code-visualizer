"""Capture reproducible M9 three-mode and accessibility review images."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from code_visualizer.domain.common import DocumentKind
from code_visualizer.ui_qt.font_support import register_application_fonts
from code_visualizer.ui_qt.main_window import CloseDecision, MainWindow


def _open_example(window: MainWindow, example_id: str) -> None:
    for row in range(window.welcome.examples.count()):
        item = window.welcome.examples.item(row)
        if item.data(Qt.ItemDataRole.UserRole) == example_id:
            window.welcome.examples.setCurrentItem(item)
            window.welcome.examples.setFocus()
            QTest.keyClick(window.welcome.examples, Qt.Key.Key_Return)
            return
    raise RuntimeError(f"Example {example_id!r} is not listed")


def _select_document(window: MainWindow, kind: DocumentKind, title_fragment: str) -> None:
    if window.session is None:
        raise RuntimeError("No example session")
    document = next(
        item
        for item in window.session.authority.snapshot().documents
        if item.kind is kind and title_fragment.casefold() in item.title.casefold()
    )
    widget = next(
        window.documents.widget(index)
        for index in range(window.documents.count())
        if getattr(window.documents.widget(index), "diagram_id", None) == document.id
    )
    window.documents.setCurrentWidget(widget)
    canvas = getattr(widget, "canvas", None)
    if canvas is not None:
        canvas.fit_content()


def _save(window: MainWindow, target: Path) -> None:
    QApplication.processEvents()
    QTest.qWait(50)
    if not window.grab().save(str(target)):
        raise RuntimeError(f"Could not save {target}")


def main() -> int:
    application = QApplication.instance() or QApplication(sys.argv[:1])
    fonts = register_application_fonts()
    application.setFont(QFont(fonts.interface, 10))
    output = Path(__file__).resolve().parents[1] / "assets" / "goldens"
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="code-visualizer-m9-capture-") as temporary:
        settings = QSettings(
            str(Path(temporary) / "capture.ini"),
            QSettings.Format.IniFormat,
        )
        window = MainWindow(
            close_decision=lambda _session: CloseDecision.DISCARD,
            settings=settings,
        )
        window.resize(1680, 1050)
        window.show()
        _open_example(window, "first_delivery")
        window.reset_workspace()

        _select_document(window, DocumentKind.DRAKON, "Decision")
        _save(window, output / "m9-first-delivery-drakon.png")
        _select_document(window, DocumentKind.MIND_MAP, "Plan")
        _save(window, output / "m9-first-delivery-mind-map.png")
        _select_document(window, DocumentKind.FREEFORM, "Architecture")
        _save(window, output / "m9-first-delivery-free-form.png")

        _select_document(window, DocumentKind.DRAKON, "Decision")
        window.theme_actions[
            next(theme for theme in window.theme_actions if theme.value == "dark")
        ].trigger()
        _save(window, output / "m9-dark-theme-decision.png")
        window.theme_actions[
            next(theme for theme in window.theme_actions if theme.value == "high_contrast")
        ].trigger()
        _save(window, output / "m9-high-contrast-decision.png")
        window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
