"""Normal saved physical examples exercise the application with factories forbidden."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from code_visualizer.application.examples import PHYSICAL_EXAMPLE_CATALOG, example_session
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.serialization import normalized_project_json

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("identity", ("electrothermal", "axial_bar"))
def test_saved_physical_example_matches_normal_catalog(identity):
    assert identity in {entry.id for entry in PHYSICAL_EXAMPLE_CATALOG}
    path = ROOT / "examples/physical" / identity.replace("_", "-") / "project.json"
    source = path.read_text(encoding="utf-8")
    project = project_from_json(source)
    session = example_session(identity)
    try:
        assert normalized_project_json(session.authority.snapshot()) == normalized_project_json(
            project
        )
    finally:
        session.close()
    assert (path.parent / "README.md").is_file()


def test_saved_sources_execute_without_factories_and_survive_producer_exit(tmp_path):
    output = tmp_path / "p6-proof"
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tools/prove_coupled_physics.py"), "--output", str(output)],
        cwd=tmp_path,
        capture_output=True,
        encoding="utf-8",
        timeout=300,
    )
    assert completed.returncode == 0, (completed.stdout, completed.stderr)
    report = json.loads((output / "proof.json").read_text(encoding="utf-8"))
    assert report["passed"] and report["phase"] == "P6"
    for name in (
        "portable_consumer_replay",
        "complete_resume_identical",
        "portable_axial_identical",
        "producer_location_unavailable_to_consumer",
        "source_only_producers",
        "example_factory_imports_forbidden",
        "canonical_unchanged_by_computation",
    ):
        assert report[name]
    assert (
        report["source_sha256"]
        == hashlib.sha256(
            (ROOT / "examples/physical/electrothermal/project.json").read_bytes()
        ).hexdigest()
    )
    assert (
        report["cad_source_sha256"]
        == hashlib.sha256(
            (ROOT / "examples/physical/axial-bar/project.json").read_bytes()
        ).hexdigest()
    )
