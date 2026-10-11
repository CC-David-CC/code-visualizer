"""Capture reproducible off-screen M4 workbench inspection images."""

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

from code_visualizer.ui_qt.font_support import register_application_fonts
from code_visualizer.ui_qt.main_window import CloseDecision, MainWindow


def main() -> int:
    application = QApplication.instance() or QApplication(sys.argv[:1])
    fonts = register_application_fonts()
    application.setFont(QFont(fonts.interface, 10))
    output = Path(__file__).resolve().parents[1] / "assets" / "goldens"
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="code-visualizer-m4-") as raw:
        temporary = Path(raw)
        project_root = temporary / "module-example"
        settings = QSettings(
            str(temporary / "capture.ini"),
            QSettings.Format.IniFormat,
        )
        window = MainWindow(
            path_chooser=lambda: project_root,
            folder_revealer=lambda _path: True,
            close_decision=lambda _session: CloseDecision.DISCARD,
            settings=settings,
        )
        window.resize(1600, 1000)
        window.show()
        window.welcome.examples.setCurrentRow(1)
        QTest.keyClick(window.welcome.examples, Qt.Key.Key_Return)
        window.action_python_project.trigger()
        application.processEvents()
        if not window.grab().save(str(output / "m4-module-setup-workbench.png")):
            return 1

        window.action_save.trigger()
        window.action_generate.trigger()
        for _attempt in range(400):
            application.processEvents()
            if window.development.reveal_button.isEnabled():
                break
            QTest.qWait(25)
        if not window.development.reveal_button.isEnabled():
            raise RuntimeError("Timed out waiting for background generation")
        window.documents.setCurrentIndex(0)
        window.development.show_artifacts()
        for row in range(window.artifacts.topLevelItemCount()):
            item = window.artifacts.topLevelItem(row)
            if item.text(0) == "studio_demo/main.py":
                window.artifacts.setCurrentItem(item)
                window.artifacts.itemActivated.emit(item, 0)
                break
        application.processEvents()
        if not window.grab().save(str(output / "m4-artifacts-workbench.png")):
            return 1
        window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
