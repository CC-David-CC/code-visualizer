"""A killed real host cannot unfreeze authoring or retract acknowledged field evidence."""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from time import monotonic, sleep

import numpy as np
import pytest
from test_diffusion_checkpoints import history, latest
from test_diffusion_git import finish_freeze
from test_git_experiments import git
from test_worker_process import _terminated

from code_visualizer.application.computation import execute_computation
from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.field_examples import diffusion_project
from code_visualizer.application.git_service import GitProjectController
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.execution.worker_process import OwnedProcessTree
from code_visualizer.extensions.diffusion.domain import BACKEND_ID
from code_visualizer.extensions.fields.records import SERIES_TYPE
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.store import ProjectStore


def test_actual_host_kill_reopen_protects_frozen_definition_and_resumes_checkpoint(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    project = diffusion_project(
        nodes=65, steps=32768, sample_every=128, checkpoint_every=1024, preview_every=7
    )
    ProjectStore(root / "project").initialize(project)
    git(root, "init")
    git(root, "config", "user.name", "P5 crash proof")
    git(root, "config", "user.email", "p5@example.invalid")
    git(root, "add", "project/project.json")
    git(root, "commit", "-m", "Declared diffusion source")
    (root / "unrelated.txt").write_text("Unrelated untracked data\n", encoding="utf-8")
    before = (
        git(root, "rev-parse", "HEAD"),
        (root / ".git/index").read_bytes(),
        (root / "unrelated.txt").read_bytes(),
    )
    ready = tmp_path / "ready.json"
    fixture = Path(__file__).parent / "fixtures/diffusion_crash_host.py"
    process = subprocess.Popen(
        [sys.executable, "-I", str(fixture), str(root / "project"), str(ready)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **OwnedProcessTree.popen_options(),
    )
    owned = OwnedProcessTree(process)
    try:
        deadline = monotonic() + 90
        while not ready.exists() and monotonic() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                pytest.fail((stdout + stderr).decode("utf-8", errors="replace"))
            sleep(0.01)
        assert ready.exists(), "Real host did not acknowledge its checkpoint within 90 seconds"
        data = json.loads(ready.read_text(encoding="utf-8"))
        assert data["host_pid"] == process.pid or data["parent_pid"] == process.pid
        os.kill(data["host_pid"], signal.SIGTERM)
        process.wait(timeout=10)
        deadline = monotonic() + 10
        while not _terminated(data["worker_pid"]) and monotonic() < deadline:
            sleep(0.02)
        assert _terminated(data["worker_pid"]), "The owned worker outlived its killed host"
    finally:
        owned.close()
        process.communicate(timeout=10)
    host = ComputationService()
    editor = ProjectSession.open(Path(data["editor_root"]), computations=host)
    controller = GitProjectController(editor)
    try:
        assert editor.experiment_context.attempt_id == data["attempt_id"]
        report = controller.execute("recover_experiments", {})
        retained = controller.experiments.store.attempt(data["attempt_id"])
        assert retained.phase == "interrupted" and not retained.evidence_id
        assert data["checkpoint_id"] in retained.publications
        assert controller.experiments.verify_run(retained.id).commit == data["commit"]
        assert report["interrupted"] == [retained.id] or retained.phase == "interrupted"
        resumed = finish_freeze(
            controller,
            controller.execute(
                "resume_checkpoint",
                {"attempt_id": retained.id, "publication_id": data["checkpoint_id"]},
            ),
        )
        result = host.wait(resumed.computation.id)
        assert result.outcome is ComputationOutcome.SUCCEEDED, result.diagnostics
        resources = ResourceStore(Path(data["retention_root"]))
        continued = history(latest(result, resources, SERIES_TYPE), resources)
        actual = [continued.slice(i) for i in range(continued.sample_count)]
        continued.close()
        current = controller.session.authority.snapshot()
        reference = execute_computation(
            controller.session.kernel,
            ComputationRequest(
                current.id, current.revision, BACKEND_ID, "1", "diffusion:experiment"
            ),
        )
        assert reference.outcome is ComputationOutcome.SUCCEEDED, reference.diagnostics
        full = history(
            latest(reference, controller.session.kernel.resource_store, SERIES_TYPE),
            controller.session.kernel.resource_store,
        )
        assert full.sample_count == len(actual) == 257
        for sample in actual:
            expected = full.slice(sample.position.sample)
            assert sample.position == expected.position
            np.testing.assert_allclose(sample.values, expected.values, rtol=0, atol=1e-9)
        full.close()
        assert (
            git(root, "rev-parse", "HEAD"),
            (root / ".git/index").read_bytes(),
            (root / "unrelated.txt").read_bytes(),
        ) == before
    finally:
        controller.close_background(wait=True)
        controller.session.close()
        editor.close()
        host.close()
