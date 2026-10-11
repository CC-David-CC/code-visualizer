"""A saved gas definition and its calibrated closure execute without example factories."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from test_hybrid_gas_particle import WINDOWS

from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.store import ProjectStore

ROOT = Path(__file__).resolve().parents[1]


@WINDOWS
def test_saved_gas_source_authors_explicit_smoke_and_retains_consumer_and_restart(tmp_path):
    output = tmp_path / "gas-saved-proof"
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            str(ROOT / "tools/prove_hybrid_gas.py"),
            "--output",
            str(output),
            "--smoke",
        ],
        cwd=tmp_path,
        capture_output=True,
        encoding="utf-8",
        timeout=300,
    )
    (tmp_path / "proof.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (tmp_path / "proof.stderr.log").write_text(completed.stderr, encoding="utf-8")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads((output / "proof.json").read_text(encoding="utf-8"))
    assert report["phase"] == "P7-gas" and report["passed"]
    assert report["smoke"] and not report["scientific_ensemble_qualification"]
    assert not report["p7_complete"]
    for key in (
        "producer_location_unavailable_to_consumer",
        "exact_cell_consumer",
        "portable_consumer_replay",
        "complete_resume_identical",
        "canonical_unchanged_by_computation",
        "example_factory_imports_forbidden",
    ):
        assert report[key]
    source = (ROOT / "examples/physical/hybrid-gas/project.json").read_bytes()
    assert report["source_sha256"] == hashlib.sha256(source).hexdigest()
    assert (output / "received-source.json").read_bytes() == source
    original = project_from_json(source.decode("utf-8"))
    authored = ProjectStore(output / "authored-source")
    current = authored.recover(promote=False)
    assert current.revision == original.revision + 1 == report["source_revision"]
    journal = authored.read_journal()
    assert len(journal) == 1
    assert report["sample_count"] == 3 and report["final_tick"] == 1000
    assert len(report["maximum_balance_residuals"]) == 5
    assert max(report["maximum_balance_residuals"]) <= 1e-10
    # Only the declared schedule changes. All physical properties and identities
    # remain the received saved model's; the accepted edit is recoverable natively.
    for before, after in zip(
        original.domain_workspace.models, current.domain_workspace.models, strict=True
    ):
        for a, b in zip(before.nodes, after.nodes, strict=True):
            if a.id != "gas:policy":
                assert a == b
            else:
                changed = {
                    item.property_id.rsplit(":", 1)[-1]
                    for item in b.properties
                    if item.value != a.property(item.property_id)
                }
                assert changed == {
                    "final_tick",
                    "sample_ticks",
                    "checkpoint_ticks",
                    "statistics_ticks",
                    "block_ticks",
                    "warmup_ticks",
                    "preview_windows",
                }
