"""P5 uses real P2 transactions, retained publications and explicit checkpoint selection."""

from time import monotonic, sleep

import pytest
from test_diffusion_checkpoints import history, latest
from test_git_experiments import finish_edit, git, untouched

from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.domain_commands import SetDomainProperty
from code_visualizer.application.field_examples import diffusion_project
from code_visualizer.application.git_service import GitProjectController
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.extensions.diffusion.domain import BACKEND_ID, identity, quantity
from code_visualizer.extensions.fields.records import SERIES_TYPE
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.store import ProjectStore


@pytest.fixture
def experiment(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "P5 field proof")
    git(root, "config", "user.email", "p5@example.invalid")
    ProjectStore(root / "project").initialize(
        diffusion_project(nodes=33, steps=512, checkpoint_every=256, sample_every=16)
    )
    for name in ("staged.txt", "unstaged.txt", "selected.py"):
        (root / name).write_text("original\n", encoding="utf-8")
    git(root, "add", "project/project.json", "staged.txt", "unstaged.txt", "selected.py")
    git(root, "commit", "-m", "Authored diffusion and unrelated work")
    (root / "staged.txt").write_text("staged change\n", encoding="utf-8")
    git(root, "add", "staged.txt")
    (root / "staged.txt").write_text("also unstaged\n", encoding="utf-8")
    (root / "unstaged.txt").write_text("unstaged change\n", encoding="utf-8")
    (root / "untracked.txt").write_text("untracked work\n", encoding="utf-8")
    host = ComputationService()
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
    return ComputationRequest(project.id, project.revision, BACKEND_ID, "1", "diffusion:experiment")


def finish_freeze(controller, operation):
    identity = operation["operation_id"]
    deadline = monotonic() + 90
    while monotonic() < deadline:
        result = controller.execute("experiment_operation", {"operation_id": identity})
        if result["status"] != "pending":
            assert result["status"] == "submitted", result
            return controller._freezes[identity].result()
        sleep(0.02)
    pytest.fail("Freeze operation did not complete in 90 seconds")


def test_dirty_git_field_fork_undo_resume_rerun_remove_and_reopen(experiment):
    controller, original, host, root = experiment
    before = untouched(root)
    first = controller.freeze_and_run(request(original))
    first_evidence = host.wait(first.computation.id)
    assert first_evidence.outcome is ComputationOutcome.SUCCEEDED, first_evidence.diagnostics
    retained_root = controller.experiments.store.root
    resources = ResourceStore(retained_root)
    initial_history = latest(first_evidence, resources, SERIES_TYPE)
    predecessor = controller.session
    child = finish_edit(
        controller,
        predecessor.client.submit(
            SetDomainProperty(
                "diffusion:experiment",
                "diffusion:initial",
                identity("SineInitial", "amplitude"),
                quantity(20.0, "kelvin"),
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
    assert len(choices) == 2
    choice = next(item for item in choices if "step 256" in item.label)
    resumed = finish_freeze(
        controller,
        controller.execute(
            "resume_checkpoint",
            {"attempt_id": choice.attempt_id, "publication_id": choice.publication_id},
        ),
    )
    resumed_evidence = host.wait(resumed.computation.id)
    assert resumed_evidence.outcome is ComputationOutcome.SUCCEEDED, resumed_evidence.diagnostics
    assert resumed.attempt.parent_attempt == first.attempt.id
    assert resumed.attempt.checkpoint_id == choice.publication_id
    rerun = finish_freeze(
        controller,
        controller.execute(
            "resume_checkpoint",
            {"attempt_id": choice.attempt_id, "publication_id": choice.publication_id},
        ),
    )
    assert host.wait(rerun.computation.id).outcome is ComputationOutcome.SUCCEEDED
    assert rerun.attempt.id != resumed.attempt.id and rerun.attempt.commit == resumed.attempt.commit
    assert untouched(root) == before
    predecessor.close()
    controller.experiments.remove_worktree(first.attempt.variant_id)
    assert not predecessor.root.exists()
    active_root = controller.session.root
    controller.close_background(wait=True)
    controller.session.close()
    host.close()
    restarted_host = ComputationService()
    reopened = ProjectSession.open(active_root, computations=restarted_host)
    restarted = GitProjectController(reopened)
    try:
        assert reopened.experiment_context.attempt_id == rerun.attempt.id
        assert restarted.experiments.verify_run(first.attempt.id).commit == first.attempt.commit
        inspector = restarted.experiments.reopen_run(first.attempt.id)
        assert inspector.read_only
        retained = history(initial_history, inspector.kernel.resource_store)
        assert retained.slice(32).position.time == quantity(1.0)
        retained.close()
        inspector.close()
        assert (
            len(
                restarted.execute("experiment_checkpoints", {"attempt_id": first.attempt.id})[
                    "checkpoints"
                ]
            )
            == 2
        )
    finally:
        restarted.close_background(wait=True)
        reopened.close()
        restarted_host.close()
