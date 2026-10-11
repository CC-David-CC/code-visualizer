"""Fresh interpreter/crash target; all recovery and execution use the normal host."""

import json
import os
import sys
from pathlib import Path
from threading import Event
from time import monotonic, sleep

from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.domain_commands import SetDomainProperty
from code_visualizer.application.git_service import GitProjectController
from code_visualizer.application.messages import CommandAccepted, CommandDeferred
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.computation import ComputationRequest, ProgressEvent
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.extensions.channels.history import ChannelHistory
from code_visualizer.extensions.channels.records import SERIES_TYPE
from code_visualizer.extensions.electrothermal.domain import BACKEND_ID, identity
from code_visualizer.extensions.electrothermal.units import quantity
from code_visualizer.persistence.computation_resources import resolve_computation_resource
from code_visualizer.persistence.store import ProjectStore


def finish(controller, pending, expected):
    deadline = monotonic() + 90
    while monotonic() < deadline:
        result = controller.execute(
            "experiment_operation", {"operation_id": pending["operation_id"]}
        )
        if result["status"] != "pending":
            assert result["status"] == expected, result
            return result
        sleep(0.02)
    raise AssertionError("Operation exceeded 90 seconds")


def main():
    mode, root, *arguments = sys.argv[1:]
    host = ComputationService(max_workers=1)
    editor = ProjectSession.open(Path(root), computations=host)
    controller = GitProjectController(editor)
    try:
        if mode == "crash":
            ready = Path(arguments[0])
            publish = host.publish

            def after_ack(job, event):
                publish(job, event)
                if not isinstance(event, ProgressEvent) or job.retention is None or ready.exists():
                    return
                checkpoint = next(
                    (
                        item
                        for item in job.publications.values()
                        if item.artifact.id == "checkpoint:2"
                    ),
                    None,
                )
                if checkpoint is None:
                    return
                retained = job.retention.store.attempt(job.retention.id)
                assert checkpoint.id in retained.publications
                variant = job.retention.store.read("variants", retained.variant_id)
                document = {
                    "attempt_id": retained.id,
                    "checkpoint_id": checkpoint.id,
                    "commit": retained.commit,
                    "retention_root": str(job.retention.store.root),
                    "editor_root": str((Path(variant["worktree"]) / retained.project_path).parent),
                    "host_pid": os.getpid(),
                    "parent_pid": os.getppid(),
                    "worker_pid": job.view.worker_pid,
                    "input_digest": retained.input_digest,
                }
                ProjectStore(ready.parent)._atomic_write(ready, json.dumps(document))
                Event().wait()  # Test observer alone waits after the preceding ACK.

            host.publish = after_ack
            project = editor.authority.snapshot()
            frozen = controller.freeze_and_run(
                ComputationRequest(
                    project.id, project.revision, BACKEND_ID, "1", "electrothermal:experiment"
                )
            )
            host.wait(frozen.computation.id)
            raise AssertionError("Crash target completed unexpectedly")

        assert mode == "recover"
        attempt_id, checkpoint_id, target = arguments
        frozen_before = editor.experiment_context.attempt_id
        assert frozen_before is not None, "Reload must never silently unfreeze the definition"
        report = controller.execute("recover_experiments", {})
        retained = controller.experiments.verify_run(attempt_id)
        choices = controller.execute("experiment_checkpoints", {"attempt_id": attempt_id})[
            "checkpoints"
        ]
        assert any(item.publication_id == checkpoint_id for item in choices)
        phase_before = controller.experiments.store.attempt(attempt_id).phase
        pending = controller.execute(
            "resume_checkpoint", {"attempt_id": attempt_id, "publication_id": checkpoint_id}
        )
        finish(controller, pending, "submitted")
        run = controller._freezes[pending["operation_id"]].result()
        result = host.wait(run.computation.id)
        assert result.outcome == ComputationOutcome.SUCCEEDED, result.diagnostics
        store = controller.session.kernel.resource_store
        root_ref = [
            item.resource
            for item in result.artifacts
            if store.describe(item.resource).logical_type == SERIES_TYPE
        ][-1]
        history = ChannelHistory(
            root_ref, lambda ref: resolve_computation_resource(store, ref, file_backed=True)
        )
        try:
            data = [row.tolist() for _, chunk in history.iter_chunks() for row in chunk]
        finally:
            history.close()
        old = controller.session
        old_variant = old.experiment_context.variant_id
        edit = old.client.submit(
            SetDomainProperty(
                "electrothermal:experiment",
                "et:law",
                identity("ResistanceLaw", "alpha"),
                quantity(0.005, "per_kelvin"),
            )
        )
        # The client bridge returns the same pending-operation shape as GUI/automation.
        assert isinstance(edit, CommandDeferred)
        accepted = controller.experiments.edits[edit.details["operation_id"]].result(timeout=30)
        assert isinstance(accepted.result, CommandAccepted)
        document = {
            "frozen_before": frozen_before,
            "phase_before": phase_before,
            "retained_commit": retained.commit,
            "parent_attempt": run.attempt.parent_attempt,
            "resumed_attempt": run.attempt.id,
            "forked_after_resume": controller.session.experiment_context.variant_id != old_variant,
            "child_unrun": controller.session.experiment_context.attempt_id is None,
            "rows": data,
            "recovery": report,
        }
        Path(target).write_text(json.dumps(document), encoding="utf-8")
    finally:
        controller.close_background(wait=True)
        controller.session.close()
        editor.close()
        host.close()


if __name__ == "__main__":
    main()
