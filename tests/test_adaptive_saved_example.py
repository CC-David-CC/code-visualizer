"""A normal saved physical example, never a hidden execution-time factory."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from code_visualizer.application.examples import PHYSICAL_EXAMPLE_CATALOG, example_session
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.serialization import normalized_project_json

ROOT = Path(__file__).resolve().parents[1]


def test_adaptive_saved_source_matches_normal_catalog():
    identity = "adaptive_diffusion"
    assert identity in {entry.id for entry in PHYSICAL_EXAMPLE_CATALOG}
    path = ROOT / "examples/physical/adaptive-diffusion/project.json"
    project = project_from_json(path.read_text(encoding="utf-8"))
    session = example_session(identity)
    try:
        assert normalized_project_json(session.authority.snapshot()) == normalized_project_json(
            project
        )
    finally:
        session.close()
    assert (path.parent / "README.md").is_file()


def test_saved_adaptive_source_runs_and_survives_producer_exit(tmp_path):
    output = tmp_path / "p7-continuum"
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tools/prove_adaptive_physics.py"), "--output", str(output)],
        cwd=tmp_path,
        capture_output=True,
        encoding="utf-8",
        timeout=300,
    )
    (tmp_path / "proof.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (tmp_path / "proof.stderr.log").write_text(completed.stderr, encoding="utf-8")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads((output / "proof.json").read_text(encoding="utf-8"))
    assert report["passed"] and report["phase"] == "P7-continuum" and not report["p7_complete"]
    for key in (
        "producer_location_unavailable_to_consumer",
        "exact_cell_consumer",
        "portable_consumer_replay",
        "complete_resume_identical",
        "canonical_unchanged_by_computation",
        "example_factory_imports_forbidden",
    ):
        assert report[key]
    assert report["sample_count"] == 201 and report["max_l2_error"] <= 0.005
    assert (
        report["source_sha256"]
        == hashlib.sha256(
            (ROOT / "examples/physical/adaptive-diffusion/project.json").read_bytes()
        ).hexdigest()
    )
