"""The physical examples execute from saved intentions with factory imports forbidden."""

import json
import subprocess
import sys
from pathlib import Path

import pytest


def test_physical_proof_runs_without_example_factories_or_qt(tmp_path):
    pytest.importorskip("numpy")
    pytest.importorskip("sympy")
    pytest.importorskip("pint")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(root / "tools/prove_physical_equations.py"),
            "--output",
            str(tmp_path / "physical-proof"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["passed"] and not report["program_lowering"]
    assert len(report["physical_examples"]) == 2
    for case in report["physical_examples"]:
        assert case["portable_replay_identical"] and case["canonical_unchanged"]
        assert set(case["highlighted_notations"]) == {"graph", "table", "tree_form"}
