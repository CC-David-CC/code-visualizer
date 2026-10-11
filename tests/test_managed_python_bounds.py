"""The existing Python child obeys bounded host capture and cancellation."""

import sys
import threading
import time
from dataclasses import replace

import pytest
from test_generated_symbol_execution_parity import _action, _case, _loop
from test_managed_python_computation import _prepared

from code_visualizer.domain.boundaries import MAX_PORTABLE_ENVELOPE_BYTES
from code_visualizer.domain.program import ExpressionRole, make_program_expression
from code_visualizer.domain.program_kinds import LoopKind
from code_visualizer.execution import DebugLaunch, DebugSession, DebugState, trace_project
from code_visualizer.execution.computation_driver import ManagedPythonDriver, managed_driver
from code_visualizer.execution.python_backend import prepare_python, python_backend
from code_visualizer.execution.runner import _BoundedCapture
from code_visualizer.generation.transformation import TransformationError


def _generated(source, *, tail=()):
    project, _ = _case("parameter_timer")
    function = project.program_model.functions[0]
    function = replace(
        function,
        body=replace(function.body, statements=(_action("bounded:output", source), *tail)),
    )
    project = replace(project, program_model=replace(project.program_model, functions=(function,)))
    snapshot = _prepared(project)
    return snapshot, prepare_python(snapshot)


def test_trace_output_is_bounded_during_capture_without_changing_its_prefix(monkeypatch):
    _, generated = _generated("print('Ω' * 50000)")
    lengths = []
    original = _BoundedCapture.append

    def capture(self, chunk):
        original(self, chunk)
        lengths.append(sum(map(len, self.parts)))
        assert lengths[-1] <= self.limit

    monkeypatch.setattr(_BoundedCapture, "append", capture)
    result = trace_project(generated, output_limit=1234)
    assert result.run.return_code == 0, result.run.stderr
    assert result.run.stdout.startswith("Ω" * 1234)
    assert len(result.run.stdout) < 1300
    assert result.run.output_truncated
    assert lengths and max(lengths) == 1234


def test_saturated_debugger_queue_does_not_block_stop_or_keep_generated_files():
    _, generated = _generated("print('x' * 1000000)")
    session = DebugSession(event_capacity=4)
    session.start(DebugLaunch(project=generated, record=True, max_history=1))
    process, tree = session._process, session._tree
    assert process is not None and tree is not None
    try:
        deadline = time.monotonic() + 5
        while session._events.qsize() < 4 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert session._events.qsize() == 4
        assert process.poll() is None
        assert session.is_active
        thread = threading.Thread(target=session.stop)
        thread.start()
        thread.join(5)
        assert not thread.is_alive(), "Backpressure held the debugger command lock"
        assert process.poll() is not None
        assert not tree.root.exists()
        assert session._events.qsize() <= session.event_capacity
        assert session.state is DebugState.STOPPED
    finally:
        session.stop()


def test_oversized_debugger_frame_fails_explicitly_before_publication(tmp_path, monkeypatch):
    _, generated = _generated("pass")
    worker = tmp_path / "oversized_debug_worker.py"
    worker.write_text(
        "import json, sys, time\njson.loads(sys.stdin.readline())\n"
        "print(json.dumps({'event': 'output', 'sequence': 0, "
        f"'text': 'x' * {MAX_PORTABLE_ENVELOPE_BYTES}}}), flush=True)\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "code_visualizer.execution.debugger.debug_worker_command",
        lambda *_args, **_kwargs: [sys.executable, "-I", str(worker)],
    )
    with DebugSession() as session:
        session.start(
            DebugLaunch(project=generated, execution_session_id="oversized", project_revision=7)
        )
        process, tree = session._process, session._tree
        assert process is not None and tree is not None
        event = session.wait_for("failed")
        assert event.reason == "protocol_limit"
        assert event.execution_session_id == "oversized"
        assert event.project_revision == 7
        assert session.poll_events() == ()
        assert session.forced_termination
        assert process.poll() is not None
        assert not tree.root.exists()


@pytest.mark.parametrize(
    "change",
    [{"id": "org.example.python"}, {"version": "2"}, {"description": "different contract"}],
)
def test_managed_artifact_requires_the_exact_registered_backend_definition(change):
    snapshot, generated = _generated("pass")
    definition = replace(python_backend().definition, **change)
    with pytest.raises(TransformationError) as rejected:
        managed_driver("unsupported", definition, snapshot, generated)
    assert rejected.value.code == "COMPUTATION_MANAGED_STRATEGY"


def test_registered_managed_artifact_strategy_does_not_infer_from_worker_capability():
    snapshot, generated = _generated("pass")
    driver = managed_driver("supported", python_backend().definition, snapshot, generated)
    assert driver.snapshot is snapshot
    assert driver.generated is generated
    driver.close()


def test_managed_close_waits_until_the_existing_trace_worker_has_shut_down(tmp_path):
    ready = tmp_path / "ready"
    loop = _loop(LoopKind.WHILE, (_action("bounded:repeat", "print('working')"),))
    loop = replace(
        loop,
        condition=make_program_expression(loop.id, "condition", "True", ExpressionRole.CONDITION),
    )
    snapshot, generated = _generated(
        f"from pathlib import Path\nPath({str(ready)!r}).touch()",
        tail=(loop,),
    )
    driver = ManagedPythonDriver("close-running", snapshot, generated)
    results = []
    errors = []

    def execute():
        try:
            results.append(driver.advance())
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=execute)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()
        driver.close()
        assert not driver._session.is_active
        thread.join(5)
        assert not thread.is_alive()
        assert not errors
        assert len(results) == 1
        assert results[0].outcome.value == "cancelled"
        assert driver.forced_termination
    finally:
        driver.close()
        thread.join(5)
