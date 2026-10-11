"""Keep a failed offscreen GUI assertion from hiding its own test report."""

import sys

import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or not report.failed:
        return
    widgets = sys.modules.get("PySide6.QtWidgets")
    main_window = sys.modules.get("code_visualizer.ui_qt.main_window")
    if widgets is None or main_window is None or widgets.QApplication.instance() is None:
        return
    # pytest-qt closes widgets after recording a failed call. An unsaved-change
    # dialog in that teardown cannot be answered in an offscreen test process.
    # The assertion and failed outcome are already fixed; passing tests and
    # their close/save decisions are untouched.
    for widget in widgets.QApplication.topLevelWidgets():
        if isinstance(widget, main_window.MainWindow):
            widget._close_decision = lambda _session: main_window.CloseDecision.DISCARD
