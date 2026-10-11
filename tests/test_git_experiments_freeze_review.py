"""Independent follow-up: execution must never leave its source editor silently unfrozen."""

from test_git_experiments import dirty_experiment as dirty_experiment
from test_git_experiments import finish_edit, rename_entry, request_for

from code_visualizer.application.git import GitError, GitRepository
from code_visualizer.application.git_service import GitProjectController
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.evidence import ComputationOutcome


def test_submitted_run_on_unrun_variant_must_protect_next_edit_when_arming_fails(
    dirty_experiment, monkeypatch
):
    controller, original, host, _root = dirty_experiment
    first = controller.freeze_and_run(request_for(original))
    host.wait(first.computation.id)
    try:
        child = finish_edit(controller, rename_entry(first.editor, "child_before_run"))
        assert child.editor.experiment_context.attempt_id is None
        expected_state = GitRepository.expected_state

        def fail_after_second_submission(repository):
            if repository.root == child.editor.git_repository().root and len(host.attempts()) == 2:
                raise OSError(
                    "review: Git state read failed after submission in current unrun editor"
                )
            return expected_state(repository)

        with monkeypatch.context() as m:
            m.setattr(GitRepository, "expected_state", fail_after_second_submission)
            run = controller.freeze_and_run(request_for(child.editor))
        evidence = host.wait(run.computation.id)
        assert evidence.outcome is ComputationOutcome.SUCCEEDED
        assert controller.session is child.editor
        assert controller.experiments.verify_run(run.attempt.id).commit == run.attempt.commit
        before = child.editor.authority.revision
        result = rename_entry(child.editor, "edit_after_executed_input")
        print(
            "SAME_EDITOR_ARM_FAILURE",
            {
                "warning": run.warning,
                "attempt_id": run.attempt.id,
                "stored_editor_attempt": child.editor.experiment_context.attempt_id,
                "next_edit_result": type(result).__name__,
                "before_revision": before,
                "after_revision": child.editor.authority.revision,
                "input_commit": run.attempt.commit,
                "retained_input_valid_after_edit": controller.experiments.verify_run(
                    run.attempt.id
                ).commit
                == run.attempt.commit,
            },
        )
        assert not isinstance(result, CommandAccepted), (
            "A submitted run froze this editor input; a post-submit arm failure must not permit "
            "its next semantic edit in place"
        )
    finally:
        first.editor.close()


def test_reopen_must_not_trust_stale_unfrozen_marker_after_submitted_run(
    dirty_experiment, monkeypatch
):
    controller, original, host, _root = dirty_experiment
    first = controller.freeze_and_run(request_for(original))
    host.wait(first.computation.id)
    try:
        child = finish_edit(controller, rename_entry(first.editor, "child_before_run"))
        store = controller.experiments.store
        write = store.write
        marker_failures = []

        def fail_frozen_marker(family, identity, data):
            if family == "variants" and identity == child.variant_id and data.get("attempt_id"):
                marker_failures.append(identity)
                raise PermissionError("review: persistent frozen-variant metadata failure")
            return write(family, identity, data)

        with monkeypatch.context() as m:
            m.setattr(store, "write", fail_frozen_marker)
            try:
                run = controller.freeze_and_run(request_for(child.editor))
            except (OSError, GitError):
                # It is valid to establish the durable binding before admission
                # and reject this request if that prerequisite cannot be stored.
                assert marker_failures and len(host.attempts()) == 1
                return
        evidence = host.wait(run.computation.id)
        assert evidence.outcome is ComputationOutcome.SUCCEEDED
        assert child.editor.experiment_context.attempt_id == run.attempt.id
        assert controller.experiments.verify_run(run.attempt.id).commit == run.attempt.commit
        marker = store.read("variants", child.variant_id)
        child.editor.close()
        reopened = ProjectSession.open(child.editor.root, computations=host)
        other = GitProjectController(reopened)
        try:
            before = reopened.authority.revision
            result = rename_entry(reopened, "edit_after_reopened_executed_input")
            print(
                "STALE_MARKER_AFTER_REOPEN",
                {
                    "warning": run.warning,
                    "attempt_id": run.attempt.id,
                    "marker_attempt": marker.get("attempt_id"),
                    "reopened_editor_attempt": reopened.experiment_context.attempt_id,
                    "next_edit_result": type(result).__name__,
                    "before_revision": before,
                    "after_revision": reopened.authority.revision,
                    "input_commit": run.attempt.commit,
                    "recovery_report": other.experiments.recovery_report(),
                    "retained_input_valid_after_edit": other.experiments.verify_run(
                        run.attempt.id
                    ).commit
                    == run.attempt.commit,
                },
            )
            assert not isinstance(result, CommandAccepted), (
                "Reopening must reconcile durable submitted attempts or block editing; "
                "a stale variant marker must not make a frozen input editable in place"
            )
        finally:
            other.close_background(wait=True)
            other.session.close()
            reopened.close()
    finally:
        first.editor.close()
