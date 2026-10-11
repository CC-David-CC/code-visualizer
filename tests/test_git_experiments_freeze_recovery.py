"""Real Git proofs: durable freeze authority survives failed reporting and restart."""

from dataclasses import replace
from pathlib import Path

import pytest
from test_git_experiments import dirty_experiment as dirty_experiment
from test_git_experiments import finish_edit, rename_entry, request_for, untouched

from code_visualizer.application.git import GitError
from code_visualizer.application.git_service import GitProjectController
from code_visualizer.application.messages import CommandAccepted, CommandDeferred, CommandRejected
from code_visualizer.application.session import ProjectSession
from code_visualizer.persistence.experiment_store import now
from code_visualizer.persistence.lease import ProjectLease


@pytest.fixture
def unrun_child(dirty_experiment):
    controller, original, host, root = dirty_experiment
    first = controller.freeze_and_run(request_for(original))
    host.wait(first.computation.id)
    try:
        child = finish_edit(controller, rename_entry(first.editor, "unrun_child"))
        assert child.editor.experiment_context.attempt_id is None
        yield controller, first, child, host, root
    finally:
        first.editor.close()


@pytest.mark.parametrize(
    "failure",
    ["write_before", "write_after", "attempt_ready", "admission_before", "admission_after"],
)
def test_failed_same_editor_freeze_cannot_lose_durable_protection(
    unrun_child, monkeypatch, failure
):
    controller, _first, child, host, root = unrun_child
    experiments = controller.experiments
    store = experiments.store
    before = untouched(root)
    write, phase = store.write, experiments._phase
    with monkeypatch.context() as patch:
        if failure.startswith("write_"):

            def fail_write(family, identity, data):
                if family == "attempts":
                    if failure == "write_after":
                        write(family, identity, data)
                    raise OSError("uncertain attempt write")
                return write(family, identity, data)

            patch.setattr(store, "write", fail_write)
        elif failure == "attempt_ready":

            def fail_phase(identity, data, current):
                phase(identity, data, current)
                if current == "attempt_ready":
                    raise OSError("attempt reporting failed")

            patch.setattr(experiments, "_phase", fail_phase)
        else:

            def fail_admission(*args, **kwargs):
                if failure == "admission_after":
                    adapter = kwargs["retention"]
                    adapter.admit(store.attempt(adapter.id).source_digest)
                raise OSError("host admission interrupted")

            patch.setattr(host, "submit", fail_admission)
        with pytest.raises(OSError):
            controller.freeze_and_run(request_for(child.editor))
    assert len(host.attempts()) == 1
    assert untouched(root) == before
    result = rename_entry(child.editor, "after_failed_freeze")
    assert not isinstance(result, CommandAccepted)
    if isinstance(result, CommandDeferred):
        # Successful fork is as valid as explicit recovery blocking.
        assert finish_edit(controller, result).variant_id != child.variant_id
    child.editor.close()
    opened = ProjectSession.open(child.editor.root, computations=host)
    try:
        attempt = opened.experiment_context.attempt_id
        if failure == "write_before":
            assert attempt is None  # No durable binding and no execution admission.
        else:
            assert attempt is not None
            assert not isinstance(rename_entry(opened, "before_controller"), CommandAccepted)
            assert experiments.verify_run(attempt).variant_id == child.variant_id
            store.interrupted(frozenset(item.session.id for item in host.attempts()))
            assert store.attempt(attempt).phase == "interrupted"
        assert len(host.attempts()) == 1  # Reopening/recovery never replays.
    finally:
        opened.close()


@pytest.mark.parametrize("failure", ["marker", "operation", "both"])
def test_persistent_reporting_failure_keeps_same_editor_and_reopened_editor_frozen(
    unrun_child, monkeypatch, failure
):
    controller, first, child, host, root = unrun_child
    store = controller.experiments.store
    write = store.write
    before = untouched(root)

    def denied(family, identity, data):
        if (family == "variants" and failure in {"marker", "both"} and data.get("attempt_id")) or (
            family == "operations"
            and failure in {"operation", "both"}
            and (data.get("phase") == "submitted" or data.get("error"))
        ):
            raise PermissionError("persistent reporting failure")
        return write(family, identity, data)

    with monkeypatch.context() as patch:
        patch.setattr(store, "write", denied)
        run = controller.freeze_and_run(request_for(child.editor))
        assert run.warning
    host.wait(run.computation.id)
    assert untouched(root) == before
    assert child.editor.experiment_context.attempt_id == run.attempt.id
    child.editor.close()
    opened = ProjectSession.open(child.editor.root, computations=host)
    other = GitProjectController(opened)
    try:
        assert opened.experiment_context.attempt_id == run.attempt.id
        fork = finish_edit(other, rename_entry(opened, "after_recovery"))
        assert fork.variant_id != child.variant_id
        assert fork.editor.experiment_context.attempt_id is None
        assert isinstance(fork.editor.client.undo(), CommandAccepted)
        assert isinstance(fork.editor.client.redo(), CommandAccepted)
        assert other.experiments.variant_id == fork.variant_id
        assert len(host.attempts()) == 2
        for attempt in (first.attempt, run.attempt):
            assert other.experiments.verify_run(attempt.id).commit == attempt.commit
            inspection = other.experiments.reopen_run(attempt.id)
            assert inspection.read_only
            inspection.close()
    finally:
        other.close_background(wait=True)
        other.session.close()
        opened.close()


@pytest.mark.parametrize("cache", ["empty", "older", "no_operation"])
def test_reopen_derives_latest_identical_attempt_and_protects_without_controller(
    unrun_child, cache
):
    controller, _first, child, host, _root = unrun_child
    one = controller.freeze_and_run(request_for(child.editor))
    host.wait(one.computation.id)
    two = controller.freeze_and_run(request_for(child.editor))
    host.wait(two.computation.id)
    assert one.attempt.commit == two.attempt.commit
    assert one.attempt.id != two.attempt.id
    store = controller.experiments.store
    marker = store.read("variants", child.variant_id)
    marker.update(
        attempt_id="" if cache == "empty" else one.attempt.id,
        frozen_commit="" if cache == "empty" else one.attempt.commit,
    )
    store.write("variants", child.variant_id, marker)
    if cache == "no_operation":
        (store.root / "operations" / f"{two.attempt.id}.json").unlink()
    child.editor.close()
    opened = ProjectSession.open(child.editor.root, computations=host)
    try:
        assert opened.experiment_context.attempt_id == two.attempt.id
        assert isinstance(opened.client.rename_project("View label only"), CommandAccepted)
        revision = opened.authority.revision
        assert isinstance(rename_entry(opened, "semantic_edit"), CommandRejected)
        assert opened.authority.revision == revision
        assert len(host.attempts()) == 3
    finally:
        opened.close()


@pytest.mark.parametrize(
    "damage",
    [
        "missing_marker",
        "missing_attempt",
        "missing_ref",
        "cross_variant_marker",
        "conflicting_input",
        "unreadable_attempts",
        "unreadable_operations",
    ],
)
def test_uncertain_reopen_refuses_writable_authority_and_releases_lease(
    unrun_child, monkeypatch, damage
):
    controller, first, child, host, _root = unrun_child
    run = controller.freeze_and_run(request_for(child.editor))
    host.wait(run.computation.id)
    store = controller.experiments.store
    marker = store.read("variants", child.variant_id)
    marker.update(attempt_id="", frozen_commit="")
    store.write("variants", child.variant_id, marker)
    child.editor.close()
    if damage == "missing_marker":
        (store.root / "variants" / f"{child.variant_id}.json").unlink()
    elif damage == "missing_attempt":
        (store.root / "attempts" / f"{run.attempt.id}.json").unlink()
    elif damage == "missing_ref":
        controller.experiments.repository._run("update-ref", "-d", run.attempt.reference)
    elif damage == "cross_variant_marker":
        marker.update(attempt_id=first.attempt.id, frozen_commit=first.attempt.commit)
        store.write("variants", child.variant_id, marker)
    elif damage == "conflicting_input":
        conflict = replace(
            first.attempt,
            id="run_conflict",
            variant_id=child.variant_id,
            reference="refs/code-visualizer/runs/run_conflict",
            created_at=now(),
        )
        controller.experiments.repository.retain_ref(conflict.reference, conflict.commit)
        store.create_attempt(conflict)
    iterdir = Path.iterdir

    def unreadable(path):
        if path == store.root / damage.removeprefix("unreadable_"):
            raise PermissionError("retained history unreadable")
        return iterdir(path)

    with monkeypatch.context() as patch:
        if damage.startswith("unreadable_"):
            patch.setattr(Path, "iterdir", unreadable)
        with pytest.raises(GitError, match=r"recovery|Restore ownership"):
            ProjectSession.open(child.editor.root, computations=host)
    lease = ProjectLease.acquire(child.editor.root, owner_id="recovery-proof")
    lease.release()
    assert len(host.attempts()) == 2
