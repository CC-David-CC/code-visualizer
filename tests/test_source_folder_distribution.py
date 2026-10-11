from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pinned_requirements_and_launcher_help_are_self_explanatory() -> None:
    runtime = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    development = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")

    assert "PySide6==" in runtime
    assert "Pillow==" in runtime
    assert "websockets==" in runtime
    assert "-r requirements.txt" in development
    result = subprocess.run(
        [sys.executable, str(ROOT / "launch.py"), "--launcher-help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "python launch.py" in result.stdout
    assert "--cli" in result.stdout


def test_launcher_runs_cli_and_gui_from_its_own_source_folder() -> None:
    common = [
        sys.executable,
        str(ROOT / "launch.py"),
        "--runtime-python",
        sys.executable,
        "--no-install",
    ]
    cli = subprocess.run(
        [*common, "--cli", "--version"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert cli.stdout.strip() == "code-visualizer 0.1.0"
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    subprocess.run(
        [*common, "--offscreen", "--smoke-test"],
        cwd=ROOT,
        check=True,
        env=environment,
        timeout=30,
    )
