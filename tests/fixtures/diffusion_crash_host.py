"""Crash target: a real host paused after acknowledging a numerical checkpoint."""

import json
import os
import sys
from pathlib import Path
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.git_service import GitProjectController
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.computation import ComputationRequest, ProgressEvent
from code_visualizer.extensions.diffusion.domain import BACKEND_ID
from code_visualizer.persistence.store import ProjectStore


def main():
    root, ready = (Path(value).resolve() for value in sys.argv[1:])
    host = ComputationService()
    editor = ProjectSession.open(root, computations=host)
    controller = GitProjectController(editor)
    publish = host.publish

    def after_ack(job, event):
        publish(job, event)
        if not isinstance(event, ProgressEvent) or job.retention is None or ready.exists():
            return
        checkpoint = next(
            (item for item in job.publications.values() if item.artifact.id == "checkpoint:1024"),
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
        # The next progress event proves the prior publication was acknowledged.
        # Only this test observer pauses; the ordinary worker/host protocol is used.
        Event().wait()

    host.publish = after_ack
    project = editor.authority.snapshot()
    run = controller.freeze_and_run(
        ComputationRequest(project.id, project.revision, BACKEND_ID, "1", "diffusion:experiment")
    )
    host.wait(run.computation.id)
    raise AssertionError("The crash target unexpectedly completed")


if __name__ == "__main__":
    main()
