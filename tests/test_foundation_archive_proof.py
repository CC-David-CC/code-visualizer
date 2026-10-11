"""An extracted archive reproduces its portable mathematical evidence exactly."""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_extracted_foundation_proof_matches_and_rejects_changed_binary_plan(tmp_path):
    extracted = tmp_path / "extracted"
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".code-visualizer", ".pytest_cache")
    shutil.copytree(ROOT / "src", extracted / "src", ignore=ignore)
    tools = extracted / "tools"
    tools.mkdir()
    for name in ("verify_programmodel_archive.py", "prove_foundation_math.py"):
        shutil.copyfile(ROOT / "tools" / name, tools / name)
    shipped = extracted / "examples" / "proofs" / "foundation-math"
    shutil.copytree(ROOT / "examples" / "proofs" / "foundation-math", shipped, ignore=ignore)
    command = [
        sys.executable,
        "-I",
        "-B",
        str(tools / "verify_programmodel_archive.py"),
        "--verify-foundation-proof",
        str(extracted),
    ]
    result = subprocess.run(
        command, cwd=extracted, capture_output=True, text=True, timeout=60, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "foundation_proof=passed" in result.stdout
    assert "computation=python-adapter program_model=unused protobuf=round-trip" in result.stdout
    assert "worker_evidence=identical resources=matched" in result.stdout
    assert "runtime_origins=graph,table,form" in result.stdout

    plan = shipped / "plan.pb"
    plan.write_bytes(plan.read_bytes() + b"\x00")
    changed = subprocess.run(
        command, cwd=extracted, capture_output=True, text=True, timeout=60, check=False
    )
    assert changed.returncode != 0
    assert "Foundation proof re-creation mismatch: plan.pb" in changed.stderr
