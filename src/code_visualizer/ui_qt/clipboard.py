"""Semantic clipboard writes and the lifetime of Qt's virtual clipboard."""

from __future__ import annotations

import atexit
from functools import cache

from PySide6.QtCore import QMimeData
from PySide6.QtWidgets import QApplication

from code_visualizer.application.clipboard import SEMANTIC_FRAGMENT_MIME, SemanticFragment


def _release_virtual_clipboard() -> None:
    application = QApplication.instance()
    if isinstance(application, QApplication) and application.platformName() in {
        "offscreen",
        "minimal",
    }:
        application.clipboard().clear()


@cache
def _register_virtual_clipboard_cleanup() -> None:
    # Virtual platform plugins retain their process-local QMimeData until native
    # teardown. Release it while Python bindings are alive. Desktop clipboard
    # ownership and copying across ordinary window closes are unaffected.
    atexit.register(_release_virtual_clipboard)


def set_semantic_clipboard(fragment: SemanticFragment) -> None:
    """Transfer MIME ownership to Qt and retain both machine and readable forms."""

    mime = QMimeData()
    mime.setData(SEMANTIC_FRAGMENT_MIME, fragment.to_json().encode("utf-8"))
    mime.setText(fragment.summary)
    QApplication.clipboard().setMimeData(mime)
    if QApplication.platformName() in {"offscreen", "minimal"}:
        _register_virtual_clipboard_cleanup()
