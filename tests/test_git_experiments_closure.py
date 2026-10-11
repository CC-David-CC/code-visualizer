"""Complete declared-input lifetimes and accepted/unpublished recovery (P2 only)."""

from pathlib import Path

import pytest
from test_git_experiments import (
    dirty_experiment as dirty_experiment,
)
from test_git_experiments import (
    finish_edit,
    git,
    rename_entry,
    request_for,
    untouched,
)

from code_visualizer.application.computation import run_computation_plan
from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.domain_commands import (
    PutDomainModel,
    PutDomainSchema,
    SetDomainProperty,
)
from code_visualizer.application.experiment_inputs import SourceInput, read_sources
from code_visualizer.application.git import GitError, GitRepository
from code_visualizer.application.git_service import GitProjectController
from code_visualizer.application.messages import CommandAccepted, CommandDeferred, CommandRejected
from code_visualizer.application.session import ProjectSession
from code_visualizer.config import PRODUCT
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.domain.intentional import (
    ConceptDefinition,
    DomainModel,
    DomainSchema,
    IntentionalNode,
    PropertyDefinition,
    PropertyValue,
    ValueKind,
)
from code_visualizer.persistence.store import ProjectStore

SOURCES = (SourceInput("selected.py", "selected.py"),)


def assert_output(evidence, value):
    assert evidence.outcome is ComputationOutcome.SUCCEEDED
    assert any(item.value == f"{value}\n" for item in evidence.observations)


def test_p2_source_lifecycle_survives_rerun_fork_history_reopen_and_producer_exit(
    dirty_experiment,
):
    controller, original, host, root = dirty_experiment
    diagram = original.authority.snapshot().documents[0]
    assert isinstance(
        original.client.insert_drakon_atom(
            diagram.id, "action", 0, source="print(__import__('selected').VALUE)"
        ),
        CommandAccepted,
    )
    schema = DomainSchema(
        "parameters",
        "org.example.parameters",
        "1",
        (
            ConceptDefinition(
                "configuration",
                "Settings",
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
    for operation in (PutDomainSchema(schema), PutDomainModel(model)):
        assert isinstance(original.client.submit(operation), CommandAccepted)
    initial = untouched(root)
    first = controller.freeze_and_run(request_for(original), sources=SOURCES)
    old_evidence = host.wait(first.computation.id)
    assert_output(old_evidence, 7)
    rerun = controller.freeze_and_run(request_for(first.editor), sources=SOURCES)
    assert_output(host.wait(rerun.computation.id), 7)
    assert first.attempt.commit == rerun.attempt.commit
    assert first.attempt.id != rerun.attempt.id
    repository = first.editor.git_repository()
    # Stage another version, then edit the declared working file again. Neither
    # this private index nor unrelated files belong to the declared closure.
    selected = repository.root / "selected.py"
    selected.write_bytes(b"VALUE = 22\r\n")
    git(repository.root, "add", "selected.py")
    selected.write_bytes(b"VALUE = 88\r\n")
    for name in ("staged.txt", "untracked.txt"):
        (repository.root / name).write_text("unrelated work", encoding="utf-8")
    git(repository.root, "add", "staged.txt")
    (repository.root / "staged.txt").write_text("also unstaged", encoding="utf-8")
    # Ordinary reloading establishes the current expected Git state; changing it
    # during a transaction is covered by explicit conflict tests below.
    first.editor.close()
    opened = ProjectSession.open(first.editor.root, computations=host)
    other = GitProjectController(opened)
    before_git = opened.git_repository().expected_state()
    try:
        child = finish_edit(
            other, opened.client.submit(SetDomainProperty(model.id, "settings", "step", 2))
        )
        child_root = child.editor.git_repository().root
        assert (child_root / "selected.py").read_bytes() == b"VALUE = 88\r\n"
        assert not (child_root / "staged.txt").exists()
        assert not (child_root / "untracked.txt").exists()
        assert opened.git_repository().expected_state() == before_git
        assert selected.read_bytes() == b"VALUE = 88\r\n"
        assert (repository.root / "staged.txt").read_text() == "also unstaged"
        assert isinstance(child.editor.client.undo(), CommandAccepted)
        assert isinstance(child.editor.client.redo(), CommandAccepted)
        assert (
            child.editor.authority.snapshot()
            .domain_workspace.model(model.id)
            .node("settings")
            .property("step")
            == 2
        )
        assert child_root.joinpath("selected.py").read_bytes() == b"VALUE = 88\r\n"
        changed = other.freeze_and_run(request_for(child.editor), sources=SOURCES)
        changed_evidence = host.wait(changed.computation.id)
        assert_output(changed_evidence, 88)
        assert changed.attempt.commit != first.attempt.commit
        assert changed.attempt.variant_id == child.variant_id
        assert untouched(root) == initial
        plan = host.job(changed.computation.id).plan
        assert plan is not None
        changed.editor.close()
        reopened = ProjectSession.open(changed.editor.root, computations=host)
        resumed = GitProjectController(reopened)
        try:
            assert resumed.experiments.frozen_attempt == changed.attempt.id
            next_run = resumed.freeze_and_run(request_for(reopened), sources=SOURCES)
            assert next_run.attempt.commit == changed.attempt.commit
            assert next_run.attempt.id != changed.attempt.id
            assert_output(host.wait(next_run.computation.id), 88)
        finally:
            resumed.close_background(wait=True)
            resumed.session.close()
    finally:
        other.close_background(wait=True)
        other.session.close()
        opened.close()
    host.close()
    # No producing process, editor, or host is needed to consume retained inputs.
    fresh_host = ComputationService()
    inspector = ProjectSession.open(original.root, read_only=True, computations=fresh_host)
    review = GitProjectController(inspector)
    try:
        historical = review.experiments.reopen_run(changed.attempt.id)
        old = review.experiments.reopen_run(first.attempt.id)
        try:
            assert historical.kernel.evidence_store.get(changed_evidence.id) == changed_evidence
            assert old.kernel.evidence_store.get(old_evidence.id) == old_evidence
            replay = run_computation_plan(
                plan, historical.kernel.host_extensions, historical.kernel.resource_store
            )
            assert_output(replay, 88)
            assert replay.provenance.input_digest == changed_evidence.provenance.input_digest
            assert (old.git_repository().root / "selected.py").read_bytes() == initial[2][
                "selected.py"
            ]
        finally:
            historical.close()
            old.close()
    finally:
        review.close_background(wait=True)
        inspector.close()
        fresh_host.close()


@pytest.mark.parametrize("side", ["predecessor", "candidate"])
@pytest.mark.parametrize("boundary", ["worktree_ready", "edit_persisted"])
def test_p2_source_change_during_fork_is_conflict_or_accepted_recovery(
    dirty_experiment, monkeypatch, side, boundary
):
    controller, original, host, _root = dirty_experiment
    frozen = controller.freeze_and_run(request_for(original), sources=SOURCES)
    host.wait(frozen.computation.id)
    experiments = controller.experiments
    context = frozen.editor.experiment_context
    phase = experiments._phase

    def change_source(identity, data, current):
        phase(identity, data, current)
        if data["kind"] == "fork" and current == boundary:
            worktree = (
                frozen.editor.git_repository().root
                if side == "predecessor"
                else Path(experiments.store.read("variants", data["variant_id"])["worktree"])
            )
            (worktree / "selected.py").write_bytes(b"VALUE = 99\n")

    monkeypatch.setattr(experiments, "_phase", change_source)
    pending = rename_entry(frozen.editor, "concurrent_source")
    future = experiments.edits[pending.details["operation_id"]]
    if boundary == "worktree_ready":
        with pytest.raises(GitError, match="declared source changed"):
            future.result(timeout=30)
    else:
        outcome = future.result(timeout=30)
        assert isinstance(outcome.result, CommandAccepted)
        assert outcome.recovery_required
        assert (
            controller.experiment_operation(pending.details["operation_id"])["status"]
            == "recovery_required"
        )
    assert controller.session is frozen.editor
    assert frozen.editor.experiment_context is context
    assert experiments.frozen_attempt == frozen.attempt.id
    assert frozen.editor.authority.snapshot().program_model.functions[0].identifier == "main"


@pytest.mark.parametrize("boundary", ["edit_persisted", "published"])
def test_p2_persistent_recovery_write_and_notification_failure_preserve_accepted_outcome(
    dirty_experiment, monkeypatch, boundary
):
    controller, original, host, _root = dirty_experiment
    frozen = controller.freeze_and_run(request_for(original))
    host.wait(frozen.computation.id)
    experiments = controller.experiments
    predecessor_context = frozen.editor.experiment_context
    write = experiments.store.write

    def unwritable(family, identity, data):
        if family == "operations" and data.get("kind") == "fork" and data.get("phase") == boundary:
            raise PermissionError("persistent metadata failure")
        return write(family, identity, data)

    def unavailable_notification(_event):
        raise OSError("notification unavailable")

    with monkeypatch.context() as m:
        m.setattr(experiments.store, "write", unwritable)
        m.setattr(controller, "changed", unavailable_notification)
        pending = rename_entry(frozen.editor, "durably_recoverable")
        outcome = experiments.edits[pending.details["operation_id"]].result(timeout=30)
    status = controller.experiment_operation(pending.details["operation_id"])
    assert status["status"] == "recovery_required"
    assert status["operation_id"] == pending.details["operation_id"]
    assert status["variant_id"] == outcome.variant_id
    assert status["root"] == str(outcome.editor.root)
    assert status["revision"] == outcome.result.revision
    assert status["command_operation_id"] == outcome.result.undo_group_id
    assert "metadata" in status["message"] and "notification" in status["message"]
    recovered = ProjectStore(outcome.editor.root).recover(promote=False)
    assert recovered.revision == status["revision"]
    assert recovered.program_model.functions[0].identifier == "durably_recoverable"
    if boundary == "edit_persisted":
        assert controller.session is frozen.editor
        assert frozen.editor.experiment_context is predecessor_context
        retry = rename_entry(frozen.editor, "retry_on_new_branch")
        assert isinstance(retry, CommandDeferred)
        finish_edit(controller, retry)
    else:
        assert controller.session is outcome.editor
        assert experiments.variant_id == outcome.variant_id
        assert experiments.frozen_attempt is None
        assert isinstance(rename_entry(outcome.editor, "continued_on_child"), CommandAccepted)
        assert isinstance(rename_entry(frozen.editor, "stale_editor"), CommandRejected)
    assert any(item.get("command_in_native_journal") for item in experiments.recovery_report())
    frozen.editor.close()


def test_p2_failed_freeze_handoff_preserves_the_predecessor_context(dirty_experiment, monkeypatch):
    controller, original, host, _root = dirty_experiment
    first = controller.freeze_and_run(request_for(original), sources=SOURCES)
    host.wait(first.computation.id)
    context = first.editor.experiment_context
    (first.editor.git_repository().root / "selected.py").write_bytes(b"VALUE = 88\n")
    expected_state = GitRepository.expected_state

    def unreadable_after_submit(repository):
        if repository.root != first.editor.git_repository().root and len(host.attempts()) == 2:
            raise OSError("freeze candidate Git state unavailable")
        return expected_state(repository)

    with monkeypatch.context() as m:
        m.setattr(GitRepository, "expected_state", unreadable_after_submit)
        run = controller.freeze_and_run(request_for(first.editor), sources=SOURCES)
        assert run.warning and run.editor.closed
    assert host.wait(run.computation.id).outcome is ComputationOutcome.SUCCEEDED
    assert controller.session is first.editor
    assert first.editor.experiment_context is context
    assert controller.experiments.frozen_attempt == first.attempt.id
    child = finish_edit(controller, rename_entry(first.editor, "after_failed_freeze"))
    assert not child.recovery_required
    assert (child.editor.git_repository().root / "selected.py").read_bytes() == b"VALUE = 88\n"
    first.editor.close()


def test_p2_source_admission_excludes_metadata_and_escapes_in_owned_worktree(dirty_experiment):
    controller, original, host, _root = dirty_experiment
    frozen = controller.freeze_and_run(request_for(original), sources=SOURCES)
    host.wait(frozen.computation.id)
    repository = frozen.editor.git_repository()
    assert read_sources(repository, SOURCES)[0].content == (_root / "selected.py").read_bytes()
    for path in ("../outside.py", ".git", "nested/.GIT/config"):
        with pytest.raises(GitError, match="portable"):
            SourceInput(path, "captured.py")
    for name in (PRODUCT.state_directory, PRODUCT.state_directory.upper()):
        path = repository.root / name / "internal.py"
        path.parent.mkdir(exist_ok=True)
        path.write_text("internal metadata", encoding="utf-8")
        with pytest.raises(GitError, match="ordinary files"):
            read_sources(repository, (SourceInput(f"{name}/internal.py", "internal.py"),))
    # A separate Git directory can have an ordinary-looking name. Its actual
    # ownership, not just the spelling '.git', must still exclude its contents.
    metadata = repository.root / "actual-metadata"
    metadata.mkdir()
    (metadata / "config.py").write_text("metadata", encoding="utf-8")
    repository._common_directory = metadata
    with pytest.raises(GitError, match="ordinary files"):
        read_sources(repository, (SourceInput("actual-metadata/config.py", "config.py"),))


def test_p2_source_symlink_is_never_captured(dirty_experiment, monkeypatch):
    controller, original, host, _root = dirty_experiment
    frozen = controller.freeze_and_run(request_for(original), sources=SOURCES)
    host.wait(frozen.computation.id)
    repository = frozen.editor.git_repository()
    path = repository.root / "selected.py"
    # The admission decision must be independent of Windows symlink-creation
    # privileges. Exercise the link predicate over a real owned worktree.
    is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path, "is_symlink", lambda candidate: candidate == path or is_symlink(candidate)
    )
    with pytest.raises(GitError, match="ordinary files"):
        read_sources(repository, SOURCES)
