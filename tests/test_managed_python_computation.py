"""Preparation exits before the established Python child executes its real files."""

import threading
import time
from dataclasses import replace

import pytest
from test_generated_symbol_execution_parity import _action, _case, _loop
from test_worker_process import _terminated

from code_visualizer.domain.computation import (
    CancelRequest,
    ComputationParameter,
    ComputationRequest,
)
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.domain.program_kinds import LoopKind
from code_visualizer.execution.computation_driver import ManagedPythonDriver
from code_visualizer.execution.python_backend import prepare_python
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.generation.computation import prepare_computation
from code_visualizer.persistence.python_execution import (
    load_python_execution,
    publish_python_execution,
)
from code_visualizer.persistence.resource_store import ResourceStore


def _prepared(project):
    request = ComputationRequest(
        project.id,
        project.revision,
        "code_visualizer.python",
        "1",
        configuration=(ComputationParameter("timeout_seconds", 10),),
    )
    return prepare_computation(project, request, builtin_registry())


def test_prepared_python_round_trip_preserves_files_maps_and_never_regenerates(
    tmp_path, monkeypatch
):
    project, expected = _case("nested_free_timer")
    snapshot = _prepared(project)
    generated = prepare_python(snapshot)
    store = ResourceStore(tmp_path)
    reference = publish_python_execution(generated, store)
    assert reference == publish_python_execution(generated, store)
    restored = load_python_execution(reference, store)
    assert restored == generated

    def reject(*args, **kwargs):
        raise AssertionError("Managed execution regenerated an admitted artifact")

    monkeypatch.setattr("code_visualizer.execution.python_backend.prepare_python", reject)
    monkeypatch.setattr("code_visualizer.execution.python_backend.lower_project", reject)
    driver = ManagedPythonDriver("prepared-python", snapshot, restored)
    try:
        result = driver.advance()
        assert result.outcome is ComputationOutcome.SUCCEEDED
        assert (
            next(item.value for item in result.observations if item.id == "python:stdout")
            == expected
        )
        assert any("parity:output" in item.semantic_ids for item in result.observations)
        # The host's terminal boundary owns admission; an already-admitted cancel
        # racing completion must be safe to dispatch to the matching driver.
        driver.cancel(CancelRequest("prepared-python"))
        with pytest.raises(ValueError, match="another Python session"):
            driver.cancel(CancelRequest("wrong-session"))
    finally:
        driver.close()


def test_cancel_before_managed_python_start_never_launches_a_child(monkeypatch):
    project, _ = _case("parameter_timer")
    snapshot = _prepared(project)
    driver = ManagedPythonDriver("cancel-before-start", snapshot, prepare_python(snapshot))

    def reject(*args, **kwargs):
        raise AssertionError("Cancellation launched Python")

    monkeypatch.setattr("code_visualizer.execution.runner.RunSession.start_project_trace", reject)
    driver.cancel(CancelRequest("cancel-before-start"))
    try:
        assert driver.advance().outcome is ComputationOutcome.CANCELLED
    finally:
        driver.close()


def test_managed_python_cancellation_owns_the_authored_childs_descendant(tmp_path):
    project, _ = _case("parameter_timer")
    pid_file = tmp_path / "descendant.pid"
    function = project.program_model.functions[0]
    loop = _loop(LoopKind.WHILE, (_action("cancel:tick", "counter += 1"),))
    from code_visualizer.domain.program import ExpressionRole, make_program_expression

    loop = replace(
        loop,
        condition=make_program_expression(loop.id, "condition", "True", ExpressionRole.CONDITION),
    )
    function = replace(
        function,
        body=replace(
            function.body,
            statements=(
                _action(
                    "cancel:setup",
                    "import subprocess, sys\nfrom pathlib import Path\n"
                    "child = subprocess.Popen([sys.executable, '-c', "
                    "'import time; time.sleep(60)'])\n"
                    f"Path({str(pid_file)!r}).write_text(str(child.pid))\ncounter = 0",
                ),
                loop,
            ),
        ),
    )
    project = replace(project, program_model=replace(project.program_model, functions=(function,)))
    snapshot = _prepared(project)
    driver = ManagedPythonDriver("cancel-python-tree", snapshot, prepare_python(snapshot))
    result = []
    thread = threading.Thread(target=lambda: result.append(driver.advance()))
    thread.start()
    try:
        deadline = time.monotonic() + 8
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert pid_file.exists(), f"Authored Python did not start its descendant: {result!r}"
        descendant = int(pid_file.read_text())
        assert not _terminated(descendant)
        driver.cancel(CancelRequest("cancel-python-tree"))
        thread.join(5)
        assert not thread.is_alive()
        assert result[0].outcome is ComputationOutcome.CANCELLED, result[0].diagnostics
        assert _terminated(descendant)
    finally:
        driver.close()
        thread.join(5)
