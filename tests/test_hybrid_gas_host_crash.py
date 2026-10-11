"""Killing the real host preserves frozen authoring and the exact native prefix."""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from time import monotonic, sleep

import numpy as np
import pytest
from fixtures.gas_project import short_project, store
from test_diffusion_git import finish_freeze
from test_electrothermal_git import repository
from test_git_experiments import untouched
from test_hybrid_gas_computation import request, resources
from test_hybrid_gas_lifecycle import complete, samples
from test_hybrid_gas_particle import WINDOWS
from test_worker_process import _terminated

from code_visualizer.application.computation import execute_computation
from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.git_service import GitProjectController
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.execution.worker_process import OwnedProcessTree
from code_visualizer.extensions.hybrid_gas.records import HISTORY_TYPE
from code_visualizer.persistence.resource_store import ResourceStore


@WINDOWS
def test_killed_native_host_reopens_protected_source_and_resumes_acknowledged_checkpoint(tmp_path):
    root = tmp_path / "repository"
    project = short_project()
    repository(root, project)
    store(root / "project")
    before = untouched(root)
    ready = tmp_path / "ready.json"
    fixture = Path(__file__).parent / "fixtures/gas_crash_host.py"
    process = subprocess.Popen(
        [sys.executable, "-I", str(fixture), str(root / "project"), str(ready)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **OwnedProcessTree.popen_options(),
    )
    owned = OwnedProcessTree(process)
    try:
        deadline = monotonic() + 120
        while not ready.exists() and monotonic() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                pytest.fail((stdout + stderr).decode("utf-8", errors="replace"))
            sleep(0.01)
        assert ready.exists(), "The real gas host did not acknowledge its checkpoint"
        data = json.loads(ready.read_text(encoding="utf-8"))
        assert data["host_pid"] == process.pid or data["parent_pid"] == process.pid
        os.kill(data["host_pid"], signal.SIGTERM)
        process.wait(timeout=10)
        deadline = monotonic() + 10
        while not _terminated(data["worker_pid"]) and monotonic() < deadline:
            sleep(0.02)
        assert _terminated(data["worker_pid"]), "The native worker outlived its killed owner"
    finally:
        owned.close()
        process.communicate(timeout=10)
    host = ComputationService()
    editor = ProjectSession.open(Path(data["editor_root"]), computations=host)
    controller = GitProjectController(editor)
    try:
        assert editor.experiment_context.attempt_id == data["attempt_id"]
        controller.execute("recover_experiments", {})
        retained = controller.experiments.store.attempt(data["attempt_id"])
        assert retained.phase == "interrupted" and not retained.evidence_id
        assert data["checkpoint_id"] in retained.publications
        assert controller.experiments.verify_run(retained.id).commit == data["commit"]
        resumed = finish_freeze(
            controller,
            controller.execute(
                "resume_checkpoint",
                {"attempt_id": retained.id, "publication_id": data["checkpoint_id"]},
            ),
        )
        evidence = complete(host, resumed.computation.id)
        assert evidence.outcome is ComputationOutcome.SUCCEEDED, evidence.diagnostics
        retained_resources = ResourceStore(Path(data["retention_root"]))
        actual = samples(
            resources(evidence, retained_resources, HISTORY_TYPE)[-1], retained_resources
        )
        current = controller.session.authority.snapshot()
        expected = execute_computation(controller.session.kernel, request(current))
        assert expected.outcome is ComputationOutcome.SUCCEEDED, expected.diagnostics
        reference = samples(
            resources(expected, controller.session.kernel.resource_store, HISTORY_TYPE)[-1],
            controller.session.kernel.resource_store,
        )
        assert len(actual) == len(reference) == 3
        for a, b in zip(actual, reference, strict=True):
            assert a[:2] == b[:2]
            np.testing.assert_array_equal(a[2], b[2])
        assert untouched(root) == before
    finally:
        controller.close_background(wait=True)
        controller.session.close()
        editor.close()
        host.close()
