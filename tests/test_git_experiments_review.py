"""Independent review probes; assertions express the required invariant.

Run from the extracted archive with PYTHONPATH=src:tests.
"""

from contextlib import suppress
from pathlib import Path

from test_git_experiments import (
    dirty_experiment as dirty_experiment,
)
from test_git_experiments import (
    finish_edit,
    rename_entry,
    request_for,
)

from code_visualizer.application.experiment_inputs import SourceInput
from code_visualizer.application.git import GitRepository
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.persistence.store import ProjectStore


def test_failed_fork_arm_must_not_unfreeze_the_old_editor(dirty_experiment, monkeypatch):
    controller, original, host, _root = dirty_experiment
    frozen = controller.freeze_and_run(request_for(original))
    host.wait(frozen.computation.id)
    exp = controller.experiments
    expected_state = GitRepository.expected_state

    def unavailable_for_new_worktree(repository):
        if repository.root != frozen.editor.git_repository().root:
            current = ProjectStore((repository.root / repository.project_path).parent).recover(
                promote=False
            )
            if (
                current.program_model.functions[0].identifier
                == "first_edit_durable_but_unpublished"
            ):
                raise OSError("review: Git expected-state read failed at new editor arm")
        return expected_state(repository)

    with monkeypatch.context() as m:
        m.setattr(GitRepository, "expected_state", unavailable_for_new_worktree)
        pending = rename_entry(frozen.editor, "first_edit_durable_but_unpublished")
        outcome = exp.edits[pending.details["operation_id"]].result(timeout=30)
        assert outcome.recovery_required
    assert controller.session is frozen.editor
    print(
        "after_failed_arm",
        {
            "active_is_old": True,
            "frozen_attempt": exp.frozen_attempt,
            "old_attempt": frozen.attempt.id,
            "variant_id": exp.variant_id,
        },
    )
    second = rename_entry(frozen.editor, "second_edit")
    print("second_edit_result", type(second).__name__)
    assert not isinstance(second, CommandAccepted), (
        "A frozen editor must not accept a semantic edit in place after a failed fork arm"
    )


def test_durable_edit_with_persistent_metadata_failure_must_report_recovery(
    dirty_experiment, monkeypatch
):
    controller, original, host, _root = dirty_experiment
    frozen = controller.freeze_and_run(request_for(original))
    host.wait(frozen.computation.id)
    exp = controller.experiments
    write = exp.store.write

    def metadata_unwritable(family, identity, data):
        if (
            family == "operations"
            and data.get("kind") == "fork"
            and data.get("phase") == "edit_persisted"
        ):
            raise PermissionError(
                "review: operation metadata remains unwritable after edit journal commit"
            )
        return write(family, identity, data)

    monkeypatch.setattr(exp.store, "write", metadata_unwritable)
    pending = rename_entry(frozen.editor, "durably_accepted")
    future = exp.edits[pending.details["operation_id"]]
    with suppress(PermissionError):
        future.result(timeout=30)
    status = controller.experiment_operation(pending.details["operation_id"])
    journals = []
    for marker in (exp.store.root / "variants").glob("*.json"):
        variant = exp.store.read("variants", marker.stem)
        root = (Path(variant["worktree"]) / variant["project_path"]).parent
        if root == frozen.editor.root:
            continue
        recovered = ProjectStore(root).recover(promote=False)
        journals.append((str(root), recovered.program_model.functions[0].identifier))
    print("poll_result", status, "recovered_journals", journals)
    assert any(name == "durably_accepted" for _, name in journals)
    assert status["status"] == "recovery_required", (
        "A native-journal accepted edit must not be reported as simply failed"
    )


def test_semantic_fork_must_not_silently_revert_declared_source_edits(dirty_experiment):
    controller, original, host, _root = dirty_experiment
    diagram = original.authority.snapshot().documents[0]
    assert isinstance(
        original.client.insert_drakon_atom(
            diagram.id, "action", 0, source="print(__import__('selected').VALUE)"
        ),
        CommandAccepted,
    )
    frozen = controller.freeze_and_run(
        request_for(original), sources=(SourceInput("selected.py", "selected.py"),)
    )
    host.wait(frozen.computation.id)
    selected = frozen.editor.git_repository().root / "selected.py"
    selected.write_text("VALUE = 88\n", encoding="utf-8")
    child = finish_edit(controller, rename_entry(frozen.editor, "edited_with_source"))
    try:
        child_bytes = (child.editor.git_repository().root / "selected.py").read_text()
        print(
            "source_before_fork",
            selected.read_text().strip(),
            "source_after_fork",
            child_bytes.strip(),
        )
        assert child_bytes == "VALUE = 88\n", (
            "Fork must preserve changed declared source inputs, or reject explicitly; "
            "it cannot silently select historical bytes"
        )
    finally:
        frozen.editor.close()


def test_declared_sources_can_be_refrozen_in_the_managed_worktree(dirty_experiment):
    controller, original, host, _root = dirty_experiment
    sources = (SourceInput("selected.py", "selected.py"),)
    first = controller.freeze_and_run(request_for(original), sources=sources)
    host.wait(first.computation.id)
    repository = first.editor.git_repository()
    selected = repository.root / "selected.py"
    print(
        "refreeze_source_path",
        {
            "inside_worktree": selected.is_relative_to(repository.root),
            "inside_common_git_directory": selected.is_relative_to(repository.common_directory),
            "ordinary_file": selected.is_file(),
            "bytes": selected.read_text().strip(),
        },
    )
    repeated = controller.freeze_and_run(request_for(first.editor), sources=sources)
    host.wait(repeated.computation.id)
    assert repeated.attempt.commit == first.attempt.commit
    assert repeated.attempt.id != first.attempt.id
