"""Terminal protocol messages do not outrun child lifetime or consumer output."""

import sys
import threading
from pathlib import Path

import pytest

from code_visualizer.execution import DebugLaunch, DebugSession, DebugState
from code_visualizer.generation.emitter import GeneratedFile, GeneratedProject


def _held_worker(tmp_path, monkeypatch):
    worker = tmp_path / "held_worker.py"
    release = tmp_path / "release"
    worker.write_text(
        "import json, pathlib, sys, time\n"
        "configuration = json.loads(sys.stdin.readline())\n"
        "for sequence, event in enumerate((\n"
        "    {'event': 'started'},\n"
        "    {'event': 'output', 'channel': 'stdout', 'text': '42\\n'},\n"
        "    {'event': 'finished', 'return_code': 0},\n"
        ")):\n"
        "    print(json.dumps(dict(event, sequence=sequence)), flush=True)\n"
        "while not pathlib.Path(sys.argv[1]).exists():\n"
        "    time.sleep(0.01)\n"
        "print('shutdown drained', file=sys.stderr, flush=True)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "code_visualizer.execution.debugger.debug_worker_command",
        lambda *_args, **_kwargs: [sys.executable, "-I", str(worker), str(release)],
    )
    generated = GeneratedProject((GeneratedFile("run_project.py", "pass\n", ()),), None, None)
    return generated, release


def test_terminal_waits_for_child_exit_stderr_drain_and_generated_directory_release(
    tmp_path, monkeypatch
):
    generated, release = _held_worker(tmp_path, monkeypatch)
    session = DebugSession()
    try:
        session.start(DebugLaunch(project=generated))
        process, tree = session._process, session._tree
        assert process is not None and tree is not None
        assert session.wait_for("output").text == "42\n"
        assert session._terminal_received.wait(5)
        assert process.poll() is None
        assert tree.root.exists()
        assert session.is_active
        with pytest.raises(TimeoutError):
            session.wait_event(timeout=0.05)

        release.touch()
        assert session.wait_for("finished").return_code == 0
        assert process.poll() == 0
        assert not tree.root.exists()
        assert "shutdown drained\n" in session._stderr
        assert not session.is_active
    finally:
        release.touch()
        session.stop()


def test_public_state_follows_bounded_event_delivery_after_worker_exit(tmp_path, monkeypatch):
    generated, release = _held_worker(tmp_path, monkeypatch)
    session = DebugSession()
    try:
        session.start(DebugLaunch(project=generated))
        assert session._terminal_received.wait(5)
        assert session.state is DebugState.STARTING
        release.touch()
        # Wait for cleanup without consuming the public queue. This models a GUI
        # that resumes polling after the worker has already completely exited.
        process = session._process
        assert process is not None
        process.wait(timeout=5)
        assert session.state is DebugState.STARTING
        assert session.poll_events(maximum=1)[0].event == "started"
        assert session.is_active
        output = session.poll_events(maximum=1)
        assert len(output) == 1 and output[0].text == "42\n"
        assert session.is_active
        assert session.wait_for("finished").event == "finished"
        assert not session.is_active
    finally:
        release.touch()
        session.stop()


def test_stop_during_natural_shutdown_does_not_write_to_exiting_worker(tmp_path, monkeypatch):
    generated, release = _held_worker(tmp_path, monkeypatch)
    session = DebugSession()
    stopping = threading.Event()
    finished = threading.Event()
    errors = []
    try:
        session.start(DebugLaunch(project=generated))
        assert session._terminal_received.wait(5)
        process, tree = session._process, session._tree
        assert process is not None and tree is not None

        def forbidden_send(_payload):
            raise AssertionError("A terminal worker must not receive another stop command")

        monkeypatch.setattr(session, "_send", forbidden_send)

        def stop():
            stopping.set()
            try:
                session.stop()
            except BaseException as exc:
                errors.append(exc)
            finally:
                finished.set()

        thread = threading.Thread(target=stop)
        thread.start()
        assert stopping.wait(5)
        release.touch()
        assert finished.wait(5)
        thread.join()
        assert not errors
        assert process.poll() == 0
        assert not Path(tree.root).exists()
    finally:
        release.touch()
        session.stop()
