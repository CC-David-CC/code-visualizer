"""P2 proofs use real Git trees/refs/indexes and the existing computation host."""

import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.experiment_inputs import INPUT_MANIFEST, SourceInput
from code_visualizer.application.git import GitError
from code_visualizer.application.git_service import GitProjectController
from code_visualizer.application.messages import CommandAccepted, CommandDeferred, CommandRejected
from code_visualizer.application.project_factory import create_default_project
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.persistence.store import ProjectStore

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="Real Git is required")


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, check=True, encoding="utf-8"
    ).stdout.strip()


@pytest.fixture
def dirty_experiment(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "P2 Proof")
    git(root, "config", "user.email", "p2@example.invalid")
    project_root = root / "project"
    ProjectStore(project_root).initialize(create_default_project())
    for name in ("staged.txt", "unstaged.txt", "selected.py"):
        (root / name).write_text("initial\n", encoding="utf-8")
    git(root, "add", "project/project.json", "staged.txt", "unstaged.txt", "selected.py")
    git(root, "commit", "-m", "Unrelated original history")
    (root / "staged.txt").write_text("staged change\n", encoding="utf-8")
    git(root, "add", "staged.txt")
    (root / "staged.txt").write_text("also unstaged\n", encoding="utf-8")
    (root / "unstaged.txt").write_text("unstaged change\n", encoding="utf-8")
    (root / "untracked.txt").write_text("untracked work\n", encoding="utf-8")
    (root / "selected.py").write_text("VALUE = 7\n", encoding="utf-8")
    host = ComputationService()
    session = ProjectSession.open(project_root, computations=host)
    controller = GitProjectController(session)
    try:
        yield controller, session, host, root
    finally:
        controller.close_background(wait=True)
        controller.session.close()
        session.close()
        host.close()


def request_for(session):
    project = session.authority.snapshot()
    return ComputationRequest(project.id, project.revision, "code_visualizer.python", "1")


def untouched(root):
    return (
        git(root, "rev-parse", "HEAD"),
        (root / ".git/index").read_bytes(),
        {
            name: (root / name).read_bytes()
            for name in (
                "staged.txt",
                "unstaged.txt",
                "untracked.txt",
                "selected.py",
                "project/project.json",
            )
        },
    )


def test_p2_first_freeze_run_in_dirty_real_git(dirty_experiment, monkeypatch):
    controller, original, host, root = dirty_experiment
    before = untouched(root)
    observed = []
    submit = host.submit

    def verify_before_execution(*args, **kwargs):
        adapter = kwargs["retention"]
        attempt = adapter.store.attempt(adapter.id)
        assert attempt.phase == "ready"
        assert adapter.repository.resolve_ref(attempt.reference) == attempt.commit
        assert git(root, "ls-tree", "-r", "--name-only", attempt.commit).splitlines() == [
            INPUT_MANIFEST,
            "project/project.json",
            "selected.py",
        ]
        manifest = json.loads(git(root, "show", f"{attempt.commit}:{INPUT_MANIFEST}"))
        assert manifest["closure_digest"] == attempt.closure_digest
        assert manifest["sources"][0]["path"] == "selected.py"
        assert untouched(root) == before
        observed.append(attempt.id)
        return submit(*args, **kwargs)

    monkeypatch.setattr(host, "submit", verify_before_execution)
    result = controller.freeze_and_run(
        request_for(original), sources=(SourceInput("selected.py", "selected.py"),)
    )
    evidence = host.wait(result.computation.id)
    assert evidence.outcome is ComputationOutcome.SUCCEEDED
    assert observed == [result.attempt.id]
    assert untouched(root) == before
    assert result.editor.root != original.root
    assert result.editor.retention_root == controller.experiments.store.root
    assert git(result.editor.root, "branch", "--show-current").startswith("experiment/")
    durable = controller.experiments.store.attempt(result.attempt.id)
    assert durable.phase == "finished" and durable.evidence_id == evidence.id


@pytest.mark.parametrize(
    "boundary",
    [
        "planned",
        "inputs_retained",
        "commit_created",
        "worktree_ready",
        "run_retained",
        "attempt_ready",
    ],
)
def test_p2_freeze_failure_never_executes_or_consumes_unrelated_work(
    dirty_experiment, monkeypatch, boundary
):
    controller, original, host, root = dirty_experiment
    before = untouched(root)
    experiments = controller.experiments
    phase = experiments._phase

    def fail(identity, data, current):
        phase(identity, data, current)
        if current == boundary:
            raise OSError(f"injected disk failure: {boundary}")

    monkeypatch.setattr(experiments, "_phase", fail)
    with pytest.raises(OSError, match="injected disk failure"):
        controller.freeze_and_run(request_for(original))
    assert untouched(root) == before
    assert host.attempts() == ()
    assert controller.session is original and not original.closed
    operations = list((experiments.store.root / "operations").glob("*.json"))
    assert len(operations) == 1
    record = json.loads(operations[0].read_text())
    assert record["phase"] == boundary
    assert "injected disk failure" in record["error"]


@pytest.mark.parametrize("change", ["index", "head", "selected"])
def test_p2_external_changes_conflict_before_execution(dirty_experiment, monkeypatch, change):
    controller, original, host, root = dirty_experiment
    experiments = controller.experiments
    phase = experiments._phase

    def external(identity, data, current):
        phase(identity, data, current)
        if current == "inputs_retained":
            if change == "index":
                git(root, "add", "unstaged.txt")
            elif change == "head":
                git(root, "commit", "--allow-empty", "-m", "External commit")
            else:
                (root / "selected.py").write_text("VALUE = 8\n")

    monkeypatch.setattr(experiments, "_phase", external)
    with pytest.raises(GitError, match="changed"):
        controller.freeze_and_run(
            request_for(original), sources=(SourceInput("selected.py", "selected.py"),)
        )
    assert host.attempts() == ()


def test_p2_identical_run_has_another_attempt_on_same_commit(dirty_experiment):
    controller, original, host, root = dirty_experiment
    first = controller.freeze_and_run(request_for(original))
    first_evidence = host.wait(first.computation.id)
    second = controller.freeze_and_run(request_for(controller.session))
    second_evidence = host.wait(second.computation.id)
    assert first.attempt.id != second.attempt.id
    assert first.attempt.commit == second.attempt.commit
    assert first.attempt.variant_id == second.attempt.variant_id
    assert first_evidence.id == second_evidence.id
    assert git(root, "show-ref", first.attempt.reference)
    assert git(root, "show-ref", second.attempt.reference)


def rename_entry(session, name):
    diagram = session.authority.snapshot().documents[0]
    return session.client.replace_program_function_signature(
        diagram.id, replace(diagram.header.function, identifier=name)
    )


def finish_edit(controller, result):
    assert isinstance(result, CommandDeferred)
    completed = controller.experiments.edits[result.details["operation_id"]].result(timeout=30)
    assert isinstance(completed.result, CommandAccepted)
    return completed


def test_p2_first_semantic_edit_forks_once_and_preserves_presentation(dirty_experiment):
    controller, original, host, root = dirty_experiment
    frozen = controller.freeze_and_run(request_for(original))
    host.wait(frozen.computation.id)
    old = controller.session
    old_input = git(root, "cat-file", "blob", f"{frozen.attempt.commit}:project/project.json")
    assert isinstance(old.client.rename_project("Presentation label"), CommandAccepted)
    # A rejected native command has no accepted semantic candidate. Incomplete
    # but accepted definitions remain legitimate authored work in this editor.
    assert isinstance(
        old.client.replace_program_function_signature(
            "missing-function", old.authority.snapshot().documents[0].header.function
        ),
        CommandRejected,
    )
    assert len(list((controller.experiments.store.root / "variants").glob("*.json"))) == 1
    child = finish_edit(controller, rename_entry(old, "first_edit"))
    assert child.editor.authority.snapshot().title == "Presentation label"
    assert child.editor.authority.snapshot().program_model.functions[0].identifier == "first_edit"
    assert git(child.editor.root, "rev-parse", "HEAD") == frozen.attempt.commit
    assert isinstance(rename_entry(child.editor, "second_edit"), CommandAccepted)
    assert isinstance(rename_entry(child.editor, "third_edit"), CommandAccepted)
    assert len(list((controller.experiments.store.root / "variants").glob("*.json"))) == 2
    assert (
        git(root, "cat-file", "blob", f"{frozen.attempt.commit}:project/project.json") == old_input
    )
    assert controller.experiments.store.attempt(frozen.attempt.id).evidence_id
    old.close()


def test_p2_undo_redo_preserves_explicit_predecessor_history(dirty_experiment):
    controller, original, host, _root = dirty_experiment
    assert isinstance(rename_entry(original, "before_freeze"), CommandAccepted)
    frozen = controller.freeze_and_run(request_for(original))
    host.wait(frozen.computation.id)
    old = controller.session
    child = finish_edit(controller, old.client.undo())
    assert child.editor.authority.snapshot().program_model.functions[0].identifier == "main"
    assert isinstance(child.editor.client.redo(), CommandAccepted)
    assert (
        child.editor.authority.snapshot().program_model.functions[0].identifier == "before_freeze"
    )
    second = controller.freeze_and_run(request_for(child.editor))
    host.wait(second.computation.id)
    grandchild = finish_edit(controller, controller.session.client.undo())
    assert grandchild.variant_id != child.variant_id
    assert git(grandchild.editor.root, "rev-parse", "HEAD") == second.attempt.commit
    assert isinstance(grandchild.editor.client.redo(), CommandAccepted)
    old.close()
    child.editor.close()


def test_p2_retained_run_survives_branch_rename_delete_and_clean_worktree_removal(dirty_experiment):
    controller, original, host, root = dirty_experiment
    run = controller.freeze_and_run(request_for(original))
    evidence = host.wait(run.computation.id)
    store = controller.experiments.store
    git(run.editor.root, "branch", "-m", "human-renamed-experiment")
    run.editor.close()
    controller.experiments.remove_worktree(run.attempt.variant_id)
    git(root, "branch", "-D", "human-renamed-experiment")
    assert not run.editor.root.exists()
    reopened = controller.experiments.reopen_run(run.attempt.id)
    try:
        assert reopened.read_only
        assert reopened.authority.snapshot().revision == evidence.provenance.revision
        assert reopened.kernel.evidence_store.get(evidence.id) == evidence
        assert reopened.kernel.resource_store.read(evidence.provenance.terminal_resource)
        assert reopened.kernel.runtime.session_state(run.attempt.id) is not None
        assert store.attempt(run.attempt.id).commit == run.attempt.commit
    finally:
        reopened.close()


def test_p2_dirty_inactive_worktree_is_not_removed(dirty_experiment):
    controller, original, host, _root = dirty_experiment
    run = controller.freeze_and_run(request_for(original))
    host.wait(run.computation.id)
    user_file = run.editor.root / "untracked-user-notes.txt"
    user_file.write_text("keep this")
    run.editor.close()
    with pytest.raises(GitError, match="Dirty"):
        controller.experiments.remove_worktree(run.attempt.variant_id)
    assert user_file.read_text() == "keep this"


def counter_composition(controller, original, host):
    from fixtures.experiment_worker_fixture import fixture_registry, worker_profile

    original.close()
    host.profiles = (worker_profile(),)
    session = ProjectSession.open(original.root, computations=host, extensions=fixture_registry())
    controller.session = session
    return session


def counter_request(session, *, hold=False, step=1):
    from fixtures.experiment_worker_fixture import BACKEND_ID

    from code_visualizer.domain.computation import ComputationParameter

    project = session.authority.snapshot()
    return ComputationRequest(
        project.id,
        project.revision,
        BACKEND_ID,
        "1",
        configuration=(
            ComputationParameter("hold", hold),
            ComputationParameter("step", step),
        ),
    )


def test_p2_checkpoint_resume_consumes_sealed_state_and_rejects_parameter_change(dirty_experiment):
    from code_visualizer.application.experiment_checkpoints import ResumeCheckpoint

    controller, original, host, _root = dirty_experiment
    author = counter_composition(controller, original, host)
    parent = controller.freeze_and_run(counter_request(author))
    first = host.wait(parent.computation.id)
    assert first.outcome is ComputationOutcome.SUCCEEDED
    assert first.observations[0].value == 1
    retained = controller.experiments.store.attempt(parent.attempt.id)
    resume = ResumeCheckpoint(parent.attempt.id, retained.publications[0])
    before_count = len(host.attempts())
    with pytest.raises(GitError, match="state-transfer"):
        controller.freeze_and_run(counter_request(controller.session, step=2), resume=resume)
    assert len(host.attempts()) == before_count
    child = controller.freeze_and_run(counter_request(controller.session), resume=resume)
    second = host.wait(child.computation.id)
    assert second.outcome is ComputationOutcome.SUCCEEDED
    assert second.observations[0].value == 2
    attempt = controller.experiments.store.attempt(child.attempt.id)
    assert attempt.parent_attempt == parent.attempt.id
    assert attempt.checkpoint_id == resume.publication_id
    assert attempt.commit != parent.attempt.commit
    parent.editor.close()
    author.close()


def test_p2_old_worker_and_resources_survive_editor_replacement(dirty_experiment):
    from time import monotonic, sleep

    from code_visualizer.domain.computation import CancelRequest

    controller, original, host, _root = dirty_experiment
    author = counter_composition(controller, original, host)
    run = controller.freeze_and_run(counter_request(author, hold=True))
    deadline = monotonic() + 30
    while not host.job(run.computation.id).view.publications and monotonic() < deadline:
        sleep(0.01)
    assert host.job(run.computation.id).view.publications
    child = finish_edit(controller, rename_entry(run.editor, "new_variant"))
    run.editor.close()
    assert not host.job(run.computation.id).done.is_set()
    assert child.editor.kernel.runtime.session_state(run.computation.id) is None
    host.cancel(CancelRequest(run.computation.id))
    evidence = host.wait(run.computation.id)
    assert evidence.outcome is ComputationOutcome.CANCELLED
    assert evidence.observations[0].value == 1
    publication = host.publication(host.job(run.computation.id).view.publications[0])
    assert child.editor.kernel.resource_store.read(publication.artifact.resource) == b"1"
    assert child.editor.kernel.runtime.session_state(run.computation.id) is None
    author.close()


@pytest.mark.parametrize("boundary", ["planned", "worktree_ready", "edit_persisted", "published"])
def test_p2_fork_transaction_failure_is_recoverable(dirty_experiment, monkeypatch, boundary):
    controller, original, host, _root = dirty_experiment
    frozen = controller.freeze_and_run(request_for(original))
    host.wait(frozen.computation.id)
    before = frozen.editor.authority.snapshot()
    experiments = controller.experiments
    phase = experiments._phase

    def fail(identity, data, current):
        phase(identity, data, current)
        if data["kind"] == "fork" and current == boundary:
            raise OSError(f"failure at {boundary}")

    monkeypatch.setattr(experiments, "_phase", fail)
    pending = rename_entry(frozen.editor, "recoverable")
    assert isinstance(pending, CommandDeferred)
    future = experiments.edits[pending.details["operation_id"]]
    if boundary in {"planned", "worktree_ready"}:
        with pytest.raises(OSError, match="failure at"):
            future.result(timeout=30)
        assert controller.session is frozen.editor
    else:
        transferred = future.result(timeout=30)
        assert isinstance(transferred.result, CommandAccepted)
        assert (
            ProjectStore(transferred.editor.root)
            .recover(promote=False)
            .program_model.functions[0]
            .identifier
            == "recoverable"
        )
        transferred.editor.close()
    assert frozen.editor.authority.snapshot() == before
    assert experiments.store.attempt(frozen.attempt.id).evidence_id
    frozen.editor.close()


def test_p2_fork_rejects_external_index_change_and_keeps_user_work(dirty_experiment, monkeypatch):
    controller, original, host, _root = dirty_experiment
    frozen = controller.freeze_and_run(request_for(original))
    host.wait(frozen.computation.id)
    phase = controller.experiments._phase
    user_file = frozen.editor.root / "user.txt"

    def external(identity, data, current):
        phase(identity, data, current)
        if data["kind"] == "fork" and current == "worktree_ready":
            user_file.write_text("external staged work")
            git(frozen.editor.root, "add", "user.txt")

    monkeypatch.setattr(controller.experiments, "_phase", external)
    result = rename_entry(frozen.editor, "not_accepted")
    with pytest.raises(GitError, match="changed"):
        controller.experiments.edits[result.details["operation_id"]].result(timeout=30)
    assert frozen.editor.authority.snapshot().program_model.functions[0].identifier == "main"
    assert user_file.read_text() == "external staged work"
    assert "user.txt" in git(frozen.editor.root, "diff", "--cached", "--name-only")


def test_p2_reopened_variant_preserves_frozen_edit_boundary(dirty_experiment):
    controller, original, host, _root = dirty_experiment
    frozen = controller.freeze_and_run(request_for(original))
    host.wait(frozen.computation.id)
    frozen.editor.close()
    reopened = ProjectSession.open(frozen.editor.root, computations=host)
    other = GitProjectController(reopened)
    try:
        assert reopened.kernel.resource_store.root == controller.session.kernel.resource_store.root
        child = finish_edit(other, rename_entry(reopened, "reopened_edit"))
        assert git(child.editor.root, "rev-parse", "HEAD") == frozen.attempt.commit
    finally:
        other.close_background(wait=True)
        other.session.close()
        reopened.close()


def test_p2_declared_source_executes_captured_bytes_in_normal_python_tree(dirty_experiment):
    from code_visualizer.application.computation import run_computation_plan

    controller, original, host, root = dirty_experiment
    diagram = original.authority.snapshot().documents[0]
    assert isinstance(
        original.client.insert_drakon_atom(
            diagram.id, "action", 0, source="print(__import__('selected').VALUE)"
        ),
        CommandAccepted,
    )
    run = controller.freeze_and_run(
        request_for(original), sources=(SourceInput("selected.py", "selected.py"),)
    )
    (root / "selected.py").write_text("VALUE = 99\n")
    evidence = host.wait(run.computation.id)
    assert evidence.outcome is ComputationOutcome.SUCCEEDED
    assert any("7" in str(observation.value) for observation in evidence.observations)
    assert not any("99" in str(observation.value) for observation in evidence.observations)
    assert evidence.provenance.resources
    replay = run_computation_plan(
        host.job(run.computation.id).plan,
        controller.session.kernel.host_extensions,
        controller.session.kernel.resource_store,
    )
    assert replay.outcome is ComputationOutcome.SUCCEEDED
    assert replay.provenance.input_digest == evidence.provenance.input_digest
    assert any("7" in str(observation.value) for observation in replay.observations)


def test_p2_same_revision_branches_do_not_share_late_runtime(dirty_experiment):
    from time import monotonic, sleep

    from fixtures.experiment_worker_fixture import fixture_registry

    from code_visualizer.domain.computation import CancelRequest

    controller, original, host, _root = dirty_experiment
    author = counter_composition(controller, original, host)
    base = controller.freeze_and_run(counter_request(author))
    host.wait(base.computation.id)
    alpha = finish_edit(controller, rename_entry(base.editor, "alpha"))
    running = controller.freeze_and_run(counter_request(alpha.editor, hold=True))
    deadline = monotonic() + 30
    while not host.job(running.computation.id).view.publications and monotonic() < deadline:
        sleep(0.01)
    assert host.job(running.computation.id).view.publications
    base.editor.close()
    reopened = ProjectSession.open(
        base.editor.root, computations=host, extensions=fixture_registry()
    )
    other = GitProjectController(reopened)
    try:
        beta = finish_edit(other, rename_entry(reopened, "beta"))
        assert alpha.editor.authority.revision == beta.editor.authority.revision == 1
        assert alpha.editor.authority.snapshot().id == beta.editor.authority.snapshot().id
        assert (
            alpha.editor.kernel.computation_attachment.id
            != beta.editor.kernel.computation_attachment.id
        )
        alpha.editor.close()
        host.cancel(CancelRequest(running.computation.id))
        evidence = host.wait(running.computation.id)
        assert evidence.provenance.revision == beta.editor.authority.revision
        assert beta.editor.kernel.runtime.session_state(running.computation.id) is None
        assert beta.editor.kernel.computation_attachment.pending_selection is None
        assert (
            controller.experiments.store.attempt(running.attempt.id).source_digest
            == host.job(running.computation.id).view.source_digest
        )
    finally:
        other.close_background(wait=True)
        other.session.close()
        reopened.close()
        author.close()


def test_p2_retention_repository_survives_its_discovering_worktree(dirty_experiment):
    controller, original, host, _root = dirty_experiment
    run = controller.freeze_and_run(request_for(original))
    host.wait(run.computation.id)
    run.editor.close()
    reopened = ProjectSession.open(run.editor.root, computations=host)
    other = GitProjectController(reopened)
    try:
        reopened.close()
        other.experiments.remove_worktree(run.attempt.variant_id)
        historical = other.experiments.reopen_run(run.attempt.id)
        assert historical.read_only and historical.root.exists()
        historical.close()
    finally:
        other.close_background(wait=True)


def test_p2_recovery_never_replays_unfinished_attempts(dirty_experiment, monkeypatch):
    controller, original, host, _root = dirty_experiment
    experiments = controller.experiments
    phase = experiments._phase

    def interrupted(identity, data, current):
        phase(identity, data, current)
        if current == "attempt_ready":
            raise OSError("host interrupted before submission")

    monkeypatch.setattr(experiments, "_phase", interrupted)
    with pytest.raises(OSError):
        controller.freeze_and_run(request_for(original))
    attempt = experiments.store.attempts()[0]
    assert experiments.store.interrupted() == (attempt.id,)
    assert experiments.store.attempt(attempt.id).phase == "interrupted"
    assert host.attempts() == ()
    reopened = experiments.reopen_run(attempt.id)
    assert reopened.authority.snapshot().id == original.authority.snapshot().id
    reopened.close()


@pytest.mark.parametrize("family", ["operations", "variants", "attempts"])
def test_p2_real_write_boundary_failure_preserves_original_checkout(
    dirty_experiment, monkeypatch, family
):
    controller, original, host, root = dirty_experiment
    before = untouched(root)
    store = controller.experiments.store
    write = store.write

    def denied(target, identity, data):
        if target == family:
            raise PermissionError(f"denied {family}")
        return write(target, identity, data)

    monkeypatch.setattr(store, "write", denied)
    with pytest.raises(PermissionError, match="denied"):
        controller.freeze_and_run(request_for(original))
    assert untouched(root) == before
    assert host.attempts() == ()
    assert isinstance(
        original.client.rename_project("Capture failed; editor still usable"), CommandAccepted
    )


def test_p2_missing_input_resource_never_reaches_computation(dirty_experiment):
    from code_visualizer.domain.values import ResourceReference

    controller, original, host, root = dirty_experiment
    before = untouched(root)
    request = replace(request_for(original), resources=(ResourceReference("missing", "0" * 64),))
    with pytest.raises((ValueError, OSError)):
        controller.freeze_and_run(request)
    assert host.attempts() == () and untouched(root) == before


def test_p2_reopening_rejects_inconsistent_retained_source_claims(dirty_experiment):
    controller, original, host, _root = dirty_experiment
    run = controller.freeze_and_run(request_for(original))
    host.wait(run.computation.id)
    store = controller.experiments.store
    metadata = store.read("attempts", run.attempt.id)
    metadata["source_digest"] = "0" * 64
    store.write("attempts", run.attempt.id, metadata)
    with pytest.raises(GitError, match="claims"):
        controller.experiments.reopen_run(run.attempt.id)


def test_p2_canonical_parameter_edit_forks_once(dirty_experiment):
    from code_visualizer.application.domain_commands import (
        PutDomainModel,
        PutDomainSchema,
        SetDomainProperty,
    )
    from code_visualizer.domain.intentional import (
        ConceptDefinition,
        DomainModel,
        DomainSchema,
        IntentionalNode,
        PropertyDefinition,
        PropertyValue,
        ValueKind,
    )

    controller, original, host, _root = dirty_experiment
    schema = DomainSchema(
        "parameters",
        "org.example.parameters",
        "1",
        (
            ConceptDefinition(
                "configuration",
                "Configuration",
                (PropertyDefinition("step", "Step", ValueKind.INTEGER, required=True),),
            ),
        ),
    )
    model = DomainModel(
        "parameters_model",
        schema.id,
        "1",
        ("settings",),
        (IntentionalNode("settings", "configuration", (PropertyValue("step", 1),)),),
    )
    for command in (PutDomainSchema(schema), PutDomainModel(model)):
        assert isinstance(original.client.submit(command), CommandAccepted)
    frozen = controller.freeze_and_run(request_for(original))
    host.wait(frozen.computation.id)
    child = finish_edit(
        controller, frozen.editor.client.submit(SetDomainProperty(model.id, "settings", "step", 2))
    )
    assert (
        child.editor.authority.snapshot()
        .domain_workspace.model(model.id)
        .node("settings")
        .property("step")
        == 2
    )
    assert (
        frozen.editor.authority.snapshot()
        .domain_workspace.model(model.id)
        .node("settings")
        .property("step")
        == 1
    )
    assert isinstance(
        child.editor.client.submit(SetDomainProperty(model.id, "settings", "step", 3)),
        CommandAccepted,
    )
    assert git(child.editor.root, "rev-parse", "HEAD") == frozen.attempt.commit
    assert len(list((controller.experiments.store.root / "variants").glob("*.json"))) == 2
    frozen.editor.close()


def test_p2_failure_after_submission_keeps_real_run_and_recovery_record(
    dirty_experiment, monkeypatch
):
    controller, original, host, root = dirty_experiment
    before = untouched(root)
    phase = controller.experiments._phase

    def fail(identity, data, current):
        phase(identity, data, current)
        if current == "submitted":
            raise PermissionError("injected after actual submission")

    monkeypatch.setattr(controller.experiments, "_phase", fail)
    run = controller.freeze_and_run(request_for(original))
    assert "submitted" in run.warning
    evidence = host.wait(run.computation.id)
    attempt = controller.experiments.store.attempt(run.attempt.id)
    assert attempt.evidence_id == evidence.id and attempt.phase == "finished"
    assert controller.experiments.verify_run(attempt.id) == attempt
    assert untouched(root) == before
    report = controller.experiments.recovery_report()
    assert any(
        item["operation_id"] == attempt.id and item["execution_replayed"] is False
        for item in report
    )


def test_p2_checkpoint_chain_uses_same_binding_through_git_automation(dirty_experiment):
    from code_visualizer.persistence.computation import computation_request_to_data

    controller, original, host, _root = dirty_experiment
    author = counter_composition(controller, original, host)
    first = controller.freeze_and_run(counter_request(author))
    host.wait(first.computation.id)
    parent = controller.experiments.store.attempt(first.attempt.id)
    editors = [author, first.editor]
    try:
        for expected in (2, 3):
            pending = controller.execute(
                "freeze_run",
                {
                    "request": computation_request_to_data(counter_request(controller.session)),
                    "resume": {"attempt_id": parent.id, "publication_id": parent.publications[0]},
                },
            )
            run = controller._freezes[pending["operation_id"]].result(timeout=30)
            editors.append(run.editor)
            assert host.wait(run.computation.id).observations[0].value == expected
            attempt = controller.experiments.store.attempt(run.attempt.id)
            assert attempt.parent_attempt == parent.id
            assert attempt.compatibility_digest == parent.compatibility_digest
            parent = attempt
    finally:
        for editor in editors:
            if editor is not controller.session:
                editor.close()
