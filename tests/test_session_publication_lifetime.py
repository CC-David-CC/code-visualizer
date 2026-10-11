"""A session's publication cannot outlive its close or Git replacement barrier."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, local

import pytest

from code_visualizer.application.git_service import GitProjectController
from code_visualizer.application.session import ProjectSession


@pytest.fixture
def isolated_project_root():
    with TemporaryDirectory(prefix="code-visualizer-publication-") as directory:
        yield Path(directory) / "project"


@pytest.mark.parametrize("operation", ("close", "git_block"))
def test_session_barrier_drains_autosave_git_marker(isolated_project_root, monkeypatch, operation):
    import code_visualizer.application.git as git
    import code_visualizer.application.session as sessions

    session = ProjectSession.new()
    session.save_as(isolated_project_root)
    controller = GitProjectController(session)
    controller.execute("initialize", {})
    original_record = sessions.record_git_checkpoint
    original_fsync = git.os.fsync
    writing, release, barrier_started = Event(), Event(), Event()
    context = local()

    def record(repository, head):
        context.marker = True
        try:
            return original_record(repository, head)
        finally:
            context.marker = False

    def fsync(descriptor):
        if getattr(context, "marker", False):
            writing.set()
            assert release.wait(10), "Publication test did not release the actual marker writer"
        return original_fsync(descriptor)

    def barrier():
        barrier_started.set()
        if operation == "close":
            session.close()
        else:
            session.block_storage("Git replacement in progress")

    monkeypatch.setattr(sessions, "record_git_checkpoint", record)
    monkeypatch.setattr(git.os, "fsync", fsync)
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            saving = workers.submit(session.autosave, session.authority.revision)
            closing = None
            try:
                assert writing.wait(10), "Autosave did not reach its Git recovery marker"
                assert tuple((session.root / ".code-visualizer").glob(".git-checkpoint-*.tmp"))
                closing = workers.submit(barrier)
                assert barrier_started.wait(5)
                try:
                    closing.result(timeout=0.5)
                except TimeoutError:
                    returned_while_writing = False
                else:
                    returned_while_writing = True
            finally:
                release.set()
                saving.result(timeout=10)
                if closing is not None:
                    closing.result(timeout=10)
        assert not returned_while_writing, "Session barrier returned with its marker file open"
        assert not tuple((session.root / ".code-visualizer").glob(".git-checkpoint-*.tmp"))
        assert not session.autosave(session.authority.revision)
    finally:
        release.set()
        controller.close_background(wait=True)
        session.close()
