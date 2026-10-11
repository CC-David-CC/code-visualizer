"""Adaptive decisions remain evidence inside the accepted P2 Git/authoring lifecycle."""

import pytest
from test_adaptive_computation import last_resource, reader
from test_adaptive_domain import change
from test_diffusion_git import finish_freeze
from test_git_experiments import finish_edit, git, untouched

from code_visualizer.application.adaptive_examples import adaptive_diffusion_project
from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.domain_commands import SetDomainProperty
from code_visualizer.application.git_service import GitProjectController
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.extensions.adaptive_diffusion.domain import BACKEND_ID, identity
from code_visualizer.extensions.adaptive_fields.records import HISTORY_TYPE
from code_visualizer.extensions.adaptive_fields.units import quantity
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.store import ProjectStore


@pytest.fixture
def experiment(tmp_path, request):
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "P7 adaptive proof")
    git(root, "config", "user.email", "p7@example.invalid")
    project = adaptive_diffusion_project()
    duration = getattr(request, "param", 20.0)
    if duration != 20:
        project = change(project, "adaptive:policy", "final_time", quantity(duration))
        project = change(project, "adaptive:policy", "checkpoint_interval", quantity(0.1))
    ProjectStore(root / "project").initialize(project)
    for name in ("staged.txt", "unstaged.txt", "selected.py"):
        (root / name).write_text("original\n", encoding="utf-8")
    git(root, "add", "project/project.json", "staged.txt", "unstaged.txt", "selected.py")
    git(root, "commit", "-m", "Authored adaptive source with unrelated files")
    (root / "staged.txt").write_text("staged change\n", encoding="utf-8")
    git(root, "add", "staged.txt")
    (root / "staged.txt").write_text("also unstaged\n", encoding="utf-8")
    (root / "unstaged.txt").write_text("unstaged change\n", encoding="utf-8")
    (root / "untracked.txt").write_text("untracked work\n", encoding="utf-8")
    host = ComputationService()
    original = ProjectSession.open(root / "project", computations=host)
    controller = GitProjectController(original)
    try:
        yield controller, original, host, root
    finally:
        controller.close_background(wait=True)
        controller.session.close()
        original.close()
        host.close()


def request(editor):
    project = editor.authority.snapshot()
    return ComputationRequest(project.id, project.revision, BACKEND_ID, "1", "adaptive:experiment")


def policy_edit(editor, tolerance=0.003):
    return editor.client.submit(
        SetDomainProperty(
            "adaptive:experiment",
            "adaptive:policy",
            identity("Policy", "spatial_atol"),
            quantity(tolerance, "kilogram_per_cubic_meter"),
        )
    )


def test_adaptation_rerun_fork_undo_resume_and_retained_reopen_use_real_git(experiment):
    controller, original, host, root = experiment
    before = untouched(root)
    first = controller.freeze_and_run(request(original))
    frozen_revision = controller.session.authority.revision
    result = host.wait(first.computation.id)
    assert result.outcome is ComputationOutcome.SUCCEEDED, result.diagnostics
    resources = ResourceStore(controller.experiments.store.root)
    history_root = last_resource(result, resources, HISTORY_TYPE)
    history = reader(history_root, resources)
    assert history.sample_count == 201 and len(history.series.epochs) > 1
    assert len(history.meshes[-1].cells) < len(history.meshes[0].cells)
    history.close()
    assert controller.session.authority.revision == frozen_revision
    assert len(controller.experiments.store.identities("variants")) == 1
    rerun = controller.freeze_and_run(request(controller.session))
    repeated = host.wait(rerun.computation.id)
    assert repeated.outcome is ComputationOutcome.SUCCEEDED, repeated.diagnostics
    assert rerun.attempt.id != first.attempt.id and rerun.attempt.commit == first.attempt.commit
    assert last_resource(repeated, resources, HISTORY_TYPE) == history_root
    predecessor = controller.session
    child = finish_edit(controller, policy_edit(predecessor))
    assert child.editor.experiment_context.attempt_id is None
    assert child.editor.root != predecessor.root
    assert isinstance(child.editor.client.undo(), CommandAccepted)
    assert isinstance(child.editor.client.redo(), CommandAccepted)
    assert isinstance(child.editor.client.undo(), CommandAccepted)
    assert len(controller.experiments.store.identities("variants")) == 2
    choices = controller.execute("experiment_checkpoints", {"attempt_id": first.attempt.id})[
        "checkpoints"
    ]
    selected = next(item for item in choices if "t=18 s" in item.label)
    continued = finish_freeze(
        controller,
        controller.execute(
            "resume_checkpoint",
            {"attempt_id": selected.attempt_id, "publication_id": selected.publication_id},
        ),
    )
    resumed = host.wait(continued.computation.id)
    assert resumed.outcome is ComputationOutcome.SUCCEEDED, resumed.diagnostics
    assert continued.attempt.parent_attempt == first.attempt.id
    assert last_resource(resumed, resources, HISTORY_TYPE) == history_root
    assert untouched(root) == before
    predecessor.close()
    controller.experiments.remove_worktree(first.attempt.variant_id)
    assert not predecessor.root.exists()
    active_root = controller.session.root
    controller.close_background(wait=True)
    controller.session.close()
    host.close()
    fresh_host = ComputationService()
    reopened = ProjectSession.open(active_root, computations=fresh_host)
    fresh = GitProjectController(reopened)
    try:
        assert reopened.experiment_context.attempt_id == continued.attempt.id
        assert fresh.experiments.verify_run(first.attempt.id).commit == first.attempt.commit
        inspector = fresh.experiments.reopen_run(first.attempt.id)
        try:
            assert inspector.read_only
            retained = reader(history_root, inspector.kernel.resource_store)
            assert retained.slice(200).position.time == quantity(20)
            retained.close()
        finally:
            inspector.close()
        assert untouched(root) == before
    finally:
        fresh.close_background(wait=True)
        reopened.close()
        fresh_host.close()


@pytest.mark.parametrize("experiment", [0.4], indirect=True)
def test_persistent_retained_association_failure_never_exposes_the_orphan_checkpoint(
    experiment, monkeypatch
):
    from code_visualizer.persistence.evidence_store import EvidenceStore

    controller, original, host, root = experiment
    before = untouched(root)
    store = controller.experiments.store
    record = store.record_publications
    faults = []

    def fail_association(identity, publications):
        evidence = EvidenceStore(store.root)
        if any(
            evidence.get_publication(item).artifact.id == "checkpoint:4096" for item in publications
        ):
            faults.append(identity)
            raise OSError("Retained association remains unwritable")
        return record(identity, publications)

    with monkeypatch.context() as patch:
        patch.setattr(store, "record_publications", fail_association)
        frozen = controller.freeze_and_run(request(original))
        result = host.wait(frozen.computation.id)
        assert result.outcome is ComputationOutcome.FAILED and faults
        assert all(item.id != "checkpoint:4096" for item in result.artifacts)
        assert controller.session.experiment_context.attempt_id == frozen.attempt.id
        choices = controller.execute("experiment_checkpoints", {"attempt_id": frozen.attempt.id})[
            "checkpoints"
        ]
        assert any("t=0.1 s" in item.label for item in choices)
        assert all("t=0.2 s" not in item.label for item in choices)
        active_root = controller.session.root
        controller.close_background(wait=True)
        controller.session.close()
        host.close()
    fresh_host = ComputationService()
    reopened = ProjectSession.open(active_root, computations=fresh_host)
    fresh = GitProjectController(reopened)
    try:
        assert reopened.experiment_context.attempt_id == frozen.attempt.id
        fresh.execute("recover_experiments", {})
        choices = fresh.execute("experiment_checkpoints", {"attempt_id": frozen.attempt.id})[
            "checkpoints"
        ]
        selected = next(item for item in choices if "t=0.1 s" in item.label)
        resumed = finish_freeze(
            fresh,
            fresh.execute(
                "resume_checkpoint",
                {"attempt_id": selected.attempt_id, "publication_id": selected.publication_id},
            ),
        )
        assert fresh_host.wait(resumed.computation.id).outcome is ComputationOutcome.SUCCEEDED
        assert untouched(root) == before
    finally:
        fresh.close_background(wait=True)
        fresh.session.close()
        reopened.close()
        fresh_host.close()
