"""Actual gas computations retain inputs across the accepted Git variant lifecycle."""

from threading import Event

import numpy as np
import pytest
from fixtures.gas_project import change, short_project, store
from test_diffusion_git import finish_freeze
from test_git_experiments import finish_edit, git, untouched
from test_hybrid_gas_computation import reader, request, resources
from test_hybrid_gas_particle import WINDOWS

from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.domain_commands import SetDomainProperty
from code_visualizer.application.experiment_checkpoints import ResumeCheckpoint
from code_visualizer.application.git import GitError
from code_visualizer.application.git_service import GitProjectController
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.computation import ProgressEvent
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.extensions.hybrid_gas.domain import identity
from code_visualizer.extensions.hybrid_gas.records import HISTORY_TYPE
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.store import ProjectStore


def authored_seed(editor, value):
    return editor.client.submit(
        SetDomainProperty("gas:experiment", "gas:policy", identity("Policy", "seed"), value)
    )


def initialize_repository(root, project):
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "P7 gas lifecycle proof")
    git(root, "config", "user.email", "p7@example.invalid")
    store(root / "project")
    ProjectStore(root / "project").initialize(project)
    for name in ("staged.txt", "unstaged.txt", "selected.py"):
        (root / name).write_text("original\n", encoding="utf-8")
    git(root, "add", "project/project.json", "staged.txt", "unstaged.txt", "selected.py")
    git(root, "commit", "-m", "Authored gas source and immutable input references")
    (root / "staged.txt").write_text("staged change\n", encoding="utf-8")
    git(root, "add", "staged.txt")
    (root / "staged.txt").write_text("also unstaged\n", encoding="utf-8")
    (root / "unstaged.txt").write_text("unstaged change\n", encoding="utf-8")
    (root / "untracked.txt").write_text("untracked work\n", encoding="utf-8")


def completed(host, session_id):
    assert host.job(session_id).done.wait(180), host.job(session_id).view
    return host.wait(session_id)


@WINDOWS
def test_native_policy_forks_at_equal_revisions_and_retained_runs_survive_removal(
    tmp_path, monkeypatch
):
    project = change(short_project(), "gas:policy", "final_tick", 2000)
    root = tmp_path / "repository"
    initialize_repository(root, project)
    before = untouched(root)
    host = ComputationService(max_workers=2)
    original = ProjectSession.open(root / "project", computations=host)
    controllers = [GitProjectController(original)]
    editors = [original]
    entered, release = Event(), Event()
    publish = host.publish
    held = []

    def hold_at_acknowledged_boundary(job, event):
        publish(job, event)
        if isinstance(event, ProgressEvent) and event.completed == 600 and not held:
            held.append(job.view.session.id)
            entered.set()
            assert release.wait(180), "The test must release the real accepted gas boundary"

    monkeypatch.setattr(host, "publish", hold_at_acknowledged_boundary)
    try:
        first = controllers[0].freeze_and_run(request(original.authority.snapshot()))
        predecessor = first.editor
        editors.append(predecessor)
        assert entered.wait(120), host.job(first.computation.id).view
        assert held == [first.computation.id]
        assert not host.job(first.computation.id).done.is_set()
        assert len(controllers[0].experiments.store.identities("variants")) == 1
        revision = predecessor.authority.revision
        a = finish_edit(controllers[0], authored_seed(predecessor, 10009)).editor
        editors.append(a)
        assert a.experiment_context.attempt_id is None
        predecessor.close()
        reopened = ProjectSession.open(predecessor.root, computations=host)
        editors.append(reopened)
        controllers.append(GitProjectController(reopened))
        b = finish_edit(controllers[1], authored_seed(reopened, 10037)).editor
        editors.append(b)
        assert a.authority.revision == b.authority.revision == revision + 1
        assert a.experiment_context.variant_id != b.experiment_context.variant_id
        for editor in (a, b):
            assert isinstance(editor.client.undo(), CommandAccepted)
            assert isinstance(editor.client.redo(), CommandAccepted)
        assert a.authority.revision == b.authority.revision
        assert len(controllers[0].experiments.store.identities("variants")) == 3
        assert not host.job(first.computation.id).done.is_set()
        release.set()
        run_a = controllers[0].freeze_and_run(request(a.authority.snapshot()))
        run_b = controllers[1].freeze_and_run(request(b.authority.snapshot()))
        editors.extend((run_a.editor, run_b.editor))
        retained = ResourceStore(controllers[0].experiments.store.root)
        roots, values = [], []
        for run in (first, run_a, run_b):
            evidence = completed(host, run.computation.id)
            assert evidence.outcome is ComputationOutcome.SUCCEEDED, evidence.diagnostics
            history_root = resources(evidence, retained, HISTORY_TYPE)[-1]
            roots.append(history_root)
            history = reader(history_root, retained)
            try:
                assert history.sample_count == 5
                values.append(history.gas_slice(4).conserved.copy())
            finally:
                history.close()
            assert controllers[0].experiments.verify_run(run.attempt.id)
        assert len(set(roots)) == 3
        assert not np.array_equal(values[0], values[1])
        assert not np.array_equal(values[1], values[2])
        assert len(controllers[0].experiments.store.identities("variants")) == 3
        assert untouched(root) == before
        assert run_a.editor.authority.revision == run_b.editor.authority.revision
        choices = controllers[0].execute(
            "experiment_checkpoints", {"attempt_id": first.attempt.id}
        )["checkpoints"]
        # A different seed at the same local revision cannot adopt this checkpoint.
        attempts = len(host.attempts())
        active = controllers[0].session
        with pytest.raises(GitError, match="Changed inputs") as rejected:
            controllers[0].freeze_and_run(
                request(active.authority.snapshot()),
                resume=ResumeCheckpoint(first.attempt.id, choices[1].publication_id),
            )
        assert rejected.value.code == "CHECKPOINT_INCOMPATIBLE"
        assert len(host.attempts()) == attempts
        assert controllers[0].session is active
        assert active.experiment_context.attempt_id == run_a.attempt.id
        # Explicitly open the retained source's editor before requesting a
        # compatible continuation. Checkpoint selection never changes its meaning.
        reopened.close()
        parent_editor = ProjectSession.open(predecessor.root, computations=host)
        editors.append(parent_editor)
        parent_controller = GitProjectController(parent_editor)
        controllers.append(parent_controller)
        offered = parent_controller.execute(
            "resume_checkpoint",
            {"attempt_id": first.attempt.id, "publication_id": choices[1].publication_id},
        )
        recovered = finish_freeze(parent_controller, offered)
        editors.append(recovered.editor)
        resumed = completed(host, recovered.computation.id)
        assert recovered.attempt.parent_attempt == first.attempt.id
        assert resources(resumed, retained, HISTORY_TYPE)[-1] == roots[0]
        assert resumed.outcome is ComputationOutcome.SUCCEEDED, resumed.diagnostics
        parent_editor.close()
        controllers[1].close_background(wait=True)
        controllers[1].session.close()
        controllers[0].experiments.remove_worktree(first.attempt.variant_id)
        assert not predecessor.root.exists()
        inspector = controllers[0].experiments.reopen_run(first.attempt.id)
        try:
            assert inspector.read_only
            history = reader(roots[0], inspector.kernel.resource_store)
            try:
                np.testing.assert_array_equal(history.gas_slice(4).conserved, values[0])
            finally:
                history.close()
        finally:
            inspector.close()
        assert untouched(root) == before
    finally:
        release.set()
        for controller in controllers:
            controller.close_background(wait=True)
        for editor in editors:
            editor.close()
        for controller in controllers:
            controller.session.close()
        host.close()
