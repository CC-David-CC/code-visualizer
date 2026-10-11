"""Coupled histories use the ordinary dirty-Git freeze, fork and selected resume."""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from test_diffusion_git import finish_freeze
from test_electrothermal_checkpoints import last_root, rows
from test_git_experiments import finish_edit, git, untouched

from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.coupled_examples import MODEL_ID, electrothermal_project
from code_visualizer.application.domain_commands import SetDomainProperty
from code_visualizer.application.git_service import GitProjectController
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.extensions.electrothermal.domain import BACKEND_ID, identity
from code_visualizer.extensions.electrothermal.units import quantity
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.store import ProjectStore


def repository(root, project):
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "P6 coupled proof")
    git(root, "config", "user.email", "p6@example.invalid")
    ProjectStore(root / "project").initialize(project)
    for name in ("staged.txt", "unstaged.txt", "selected.py"):
        (root / name).write_text("original\n", encoding="utf-8")
    git(root, "add", "project/project.json", "staged.txt", "unstaged.txt", "selected.py")
    git(root, "commit", "-m", "Authored electrothermal source and unrelated work")
    (root / "staged.txt").write_text("staged change\n", encoding="utf-8")
    git(root, "add", "staged.txt")
    (root / "staged.txt").write_text("also unstaged\n", encoding="utf-8")
    (root / "unstaged.txt").write_text("unstaged change\n", encoding="utf-8")
    (root / "untracked.txt").write_text("untracked work\n", encoding="utf-8")


@pytest.fixture
def experiment(tmp_path):
    root = tmp_path / "repository"
    repository(
        root, electrothermal_project(duration=6, windows=6, sample_every=1, checkpoint_every=2)
    )
    host = ComputationService(max_workers=1)
    editor = ProjectSession.open(root / "project", computations=host)
    controller = GitProjectController(editor)
    try:
        yield controller, editor, host, root
    finally:
        controller.close_background(wait=True)
        controller.session.close()
        editor.close()
        host.close()


def request(editor):
    project = editor.authority.snapshot()
    return ComputationRequest(project.id, project.revision, BACKEND_ID, "1", MODEL_ID)


def recover_fresh(editor_root, attempt_id, checkpoint_id, output):
    fixture = Path(__file__).parent / "fixtures/coupled_recovery_host.py"
    command = [
        sys.executable,
        "-I",
        str(fixture),
        "recover",
        str(editor_root),
        attempt_id,
        checkpoint_id,
        str(output),
    ]
    completed = subprocess.run(command, capture_output=True, timeout=180)
    assert completed.returncode == 0, (completed.stdout + completed.stderr).decode(
        "utf-8", errors="replace"
    )
    return json.loads(output.read_text(encoding="utf-8"))


def test_dirty_git_fork_undo_rerun_and_retained_history_after_worktree_removal(
    experiment, tmp_path
):
    controller, original, host, root = experiment
    before = untouched(root)
    first = controller.freeze_and_run(request(original))
    first_evidence = host.wait(first.computation.id)
    assert first_evidence.outcome is ComputationOutcome.SUCCEEDED, first_evidence.diagnostics
    resources = ResourceStore(controller.experiments.store.root)
    expected = rows(resources, last_root(first_evidence, resources))
    predecessor = controller.session
    child = finish_edit(
        controller,
        predecessor.client.submit(
            SetDomainProperty(
                MODEL_ID,
                "et:law",
                identity("ResistanceLaw", "alpha"),
                quantity(0.005, "per_kelvin"),
            )
        ),
    )
    assert child.editor.experiment_context.attempt_id is None
    assert isinstance(child.editor.client.undo(), CommandAccepted)
    assert isinstance(child.editor.client.redo(), CommandAccepted)
    assert isinstance(child.editor.client.undo(), CommandAccepted)
    assert len(controller.experiments.store.identities("variants")) == 2
    choices = controller.execute("experiment_checkpoints", {"attempt_id": first.attempt.id})[
        "checkpoints"
    ]
    choice = next(item for item in choices if "window 2" in item.label)
    resumed = finish_freeze(
        controller,
        controller.execute(
            "resume_checkpoint",
            {"attempt_id": choice.attempt_id, "publication_id": choice.publication_id},
        ),
    )
    result = host.wait(resumed.computation.id)
    assert result.outcome is ComputationOutcome.SUCCEEDED, result.diagnostics
    assert resumed.attempt.parent_attempt == first.attempt.id
    assert resumed.attempt.checkpoint_id == choice.publication_id
    assert np.array_equal(rows(resources, last_root(result, resources)), expected)
    rerun = finish_freeze(
        controller,
        controller.execute(
            "resume_checkpoint",
            {"attempt_id": choice.attempt_id, "publication_id": choice.publication_id},
        ),
    )
    repeated = host.wait(rerun.computation.id)
    assert repeated.outcome is ComputationOutcome.SUCCEEDED, repeated.diagnostics
    assert rerun.attempt.id != resumed.attempt.id and rerun.attempt.commit == resumed.attempt.commit
    assert untouched(root) == before
    git(predecessor.root, "branch", "-m", "human-renamed-coupled-run")
    predecessor.close()
    controller.experiments.remove_worktree(first.attempt.variant_id)
    assert not predecessor.root.exists()
    inspector = controller.experiments.reopen_run(first.attempt.id)
    try:
        assert inspector.read_only
        assert np.array_equal(
            rows(inspector.kernel.resource_store, last_root(first_evidence, resources)), expected
        )
    finally:
        inspector.close()
    active_root = controller.session.root
    controller.close_background(wait=True)
    controller.session.close()
    host.close()
    fresh = recover_fresh(
        active_root, first.attempt.id, choice.publication_id, tmp_path / "fresh.json"
    )
    assert fresh["frozen_before"] == rerun.attempt.id
    assert fresh["parent_attempt"] == first.attempt.id
    assert fresh["forked_after_resume"]
    assert np.array_equal(np.asarray(fresh["rows"]), expected)
    assert untouched(root) == before
