"""Desktop application entry point."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from code_visualizer.application.computation_service import ComputationService
from code_visualizer.config import PRODUCT
from code_visualizer.ui_qt.font_support import register_application_fonts
from code_visualizer.ui_qt.main_window import MainWindow
from code_visualizer.ui_qt.theme import ThemeName, apply_theme


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="code-visualizer-gui")
    parser.add_argument("--offscreen", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    existing = QApplication.instance()
    application = existing if isinstance(existing, QApplication) else QApplication(sys.argv[:1])
    families = register_application_fonts()
    interface_font = QFont(families.interface)
    interface_font.setPointSizeF(10.0)
    application.setFont(interface_font)
    application.setApplicationName(PRODUCT.name)
    application.setOrganizationDomain(PRODUCT.application_id)
    apply_theme(application, ThemeName.CLASSIC)
    computations = ComputationService()
    try:
        window = MainWindow(computations=computations)
        window.show()
        if args.smoke_test:
            QTimer.singleShot(100, window.close)
        return application.exec()
    finally:
        computations.close()
