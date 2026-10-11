"""Plain Run uses the same process-tree lifetime boundary as Trace and Debug."""

import json
import time
from dataclasses import replace
from pathlib import Path

from test_generated_symbol_execution_parity import _action, _loop
from test_managed_python_bounds import _generated
from test_worker_process import _terminated

from code_visualizer.domain.program import ExpressionRole, make_program_expression
from code_visualizer.domain.program_kinds import LoopKind
from code_visualizer.execution.runner import RunSession, run_project


def _spawning_source(record: Path, ready: Path) -> str:
    return (
        "import subprocess, sys, os, json\nfrom pathlib import Path\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"Path({str(record)!r}).write_text(json.dumps({{'pid': child.pid, 'root': os.getcwd()}}))\n"
        f"Path({str(ready)!r}).touch()\n"
        "print('ready', flush=True)\ncounter = 0"
    )


def test_plain_run_stop_returns_before_owned_descendants_and_files_are_released(tmp_path):
    record, ready = tmp_path / "child.json", tmp_path / "ready"
    loop = _loop(LoopKind.WHILE, (_action("plain:tick", "counter += 1"),))
    loop = replace(
        loop,
        condition=make_program_expression(loop.id, "condition", "True", ExpressionRole.CONDITION),
    )
    _snapshot, generated = _generated(_spawning_source(record, ready), tail=(loop,))
    session = RunSession()
    results = []
    session.start_project(generated, timeout=30, completed=results.append)
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), results
        child = json.loads(record.read_text())
        assert not _terminated(child["pid"])
        assert Path(child["root"]).is_dir()
        started = time.monotonic()
        assert session.stop()
        assert time.monotonic() - started < 0.2
        assert session.wait(5)
        assert len(results) == 1
        assert results[0].termination_reason == "stopped"
        assert results[0].stdout == "ready\n"
        assert session.forced_termination
        assert _terminated(child["pid"])
        assert not Path(child["root"]).exists()
    finally:
        session.stop()
        assert session.wait(5)


def test_natural_plain_run_exit_reaps_descendants_before_output_and_tree_cleanup(tmp_path):
    record, ready = tmp_path / "child.json", tmp_path / "ready"
    _snapshot, generated = _generated(_spawning_source(record, ready))
    result = run_project(generated, timeout=5)
    assert result.return_code == 0, result.stderr
    assert result.stdout == "ready\n"
    assert result.termination_reason == "exited"
    child = json.loads(record.read_text())
    assert _terminated(child["pid"])
    assert not Path(child["root"]).exists()
