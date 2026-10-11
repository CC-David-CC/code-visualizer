"""A failed GUI call remains failed and reports its error without modal teardown."""

import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from textwrap import dedent


def test_failed_gui_assertion_is_reported_and_passing_close_policy_is_preserved(tmp_path):
    (tmp_path / "conftest.py").write_bytes(Path(__file__).with_name("conftest.py").read_bytes())
    (tmp_path / "test_child.py").write_text(
        dedent(
            """
            import pytest
            from PySide6.QtCore import QSettings
            from code_visualizer.ui_qt.main_window import MainWindow, CloseDecision

            def test_failed_dirty_window(qtbot, tmp_path):
                settings = QSettings(str(tmp_path / 'failed.ini'), QSettings.Format.IniFormat)
                window = MainWindow(settings=settings)
                qtbot.addWidget(window)
                window.action_new.trigger()
                assert False, 'Intentional failed-call report; never an accepted test result'

            @pytest.fixture
            def unchanged_policy(qtbot, tmp_path):
                policy = lambda _session: CloseDecision.CANCEL
                settings = QSettings(str(tmp_path / 'passed.ini'), QSettings.Format.IniFormat)
                window = MainWindow(settings=settings, close_decision=policy)
                qtbot.addWidget(window)
                window.action_new.trigger()
                yield window, policy
                # This finalizer runs after the passing call report.
                assert window._close_decision is policy
                window._close_decision = lambda _session: CloseDecision.DISCARD

            def test_passing_close_policy(unchanged_policy):
                window, policy = unchanged_policy
                assert window._close_decision is policy
            """
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "pytestqt.plugin",
            "-q",
            "test_child.py",
            "--junitxml=result.xml",
            "--basetemp=temporary",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=90,
    )
    (tmp_path / "child-output.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
    assert result.returncode == 1, result.stdout + result.stderr
    cases = ET.parse(tmp_path / "result.xml").findall(".//testcase")
    assert len(cases) == 2
    assert sum(case.find("failure") is not None for case in cases) == 1
    assert all(case.find("error") is None for case in cases)
    assert "Intentional failed-call report" in cases[0].find("failure").text
