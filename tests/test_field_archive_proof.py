"""Saved native field source and a factory-free independent computation consumer."""

import json
import subprocess
import sys
from pathlib import Path


def test_saved_field_example_without_factories_or_producer_process(tmp_path):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            str(root / "tools/prove_field_history.py"),
            "--output",
            str(tmp_path / "proof"),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / "proof/proof.json").read_text(encoding="utf-8"))
    assert report["passed"] and report["producer_closed_before_consumer"]
    assert report["portable_consumer_replay"] and report["canonical_unchanged"]
    assert report["producer_location_unavailable_to_consumer"]
    assert report["portable_restart_identical"] and report["resume_max_error"] <= 1e-9
    assert report["absolute_error"] < 0.0008
