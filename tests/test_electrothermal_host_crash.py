"""Kill the real owning process after ACK; recover and resume in another interpreter."""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from time import monotonic, sleep

import numpy as np
from test_electrothermal_contracts import changed
from test_electrothermal_git import recover_fresh, repository
from test_electrothermal_references import Parameters, assert_accounting, discrete
from test_git_experiments import untouched
from test_worker_process import _terminated

from code_visualizer.application.coupled_examples import electrothermal_project
from code_visualizer.execution.worker_process import OwnedProcessTree


def test_killed_host_retains_complete_coupled_prefix_and_cannot_unfreeze_on_restart(tmp_path):
    root = tmp_path / "repository"
    project = changed(
        electrothermal_project(duration=6, windows=6, sample_every=1, checkpoint_every=2),
        "et:policy",
        "preview_every",
        2,
    )
    repository(root, project)
    before = untouched(root)
    ready = tmp_path / "ready.json"
    fixture = Path(__file__).parent / "fixtures/coupled_recovery_host.py"
    process = subprocess.Popen(
        [sys.executable, "-I", str(fixture), "crash", str(root / "project"), str(ready)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **OwnedProcessTree.popen_options(),
    )
    owned = OwnedProcessTree(process)
    try:
        deadline = monotonic() + 90
        while not ready.exists() and monotonic() < deadline:
            assert process.poll() is None, process.communicate()[1].decode(
                "utf-8", errors="replace"
            )
            sleep(0.01)
        assert ready.exists(), "Host did not acknowledge the coupled checkpoint within 90 seconds"
        recorded = json.loads(ready.read_text(encoding="utf-8"))
        assert recorded["host_pid"] == process.pid or recorded["parent_pid"] == process.pid
        os.kill(recorded["host_pid"], signal.SIGTERM)
        process.wait(timeout=10)
        deadline = monotonic() + 10
        while not _terminated(recorded["worker_pid"]) and monotonic() < deadline:
            sleep(0.02)
        assert _terminated(recorded["worker_pid"]), "Owned worker outlived its killed host"
    finally:
        owned.close()
        process.communicate(timeout=10)
    fresh = recover_fresh(
        recorded["editor_root"],
        recorded["attempt_id"],
        recorded["checkpoint_id"],
        tmp_path / "recovered.json",
    )
    assert fresh["phase_before"] == "interrupted"
    assert fresh["frozen_before"] == recorded["attempt_id"]
    assert fresh["retained_commit"] == recorded["commit"]
    assert fresh["forked_after_resume"] and fresh["child_unrun"]
    assert_accounting(np.asarray(fresh["rows"]), Parameters(), discrete(Parameters(), 1, 6))
    assert untouched(root) == before
