"""Real emitted files are the shared Run, Trace, and Debug execution boundary."""

from dataclasses import replace
from threading import Event
from time import monotonic, sleep

import pytest

from code_visualizer.execution import (
    DebugLaunch,
    DebugSession,
    RunSession,
    SourceLocation,
    run_generated,
    run_project,
    trace_project,
)
from code_visualizer.execution.project_files import MaterializedProject
from code_visualizer.generation.emitter import GeneratedFile, GeneratedProject


def _project():
    return GeneratedProject(
        (
            GeneratedFile("sample/__init__.py", "from .worker import run\n", ()),
            GeneratedFile("sample/data.txt", "resource payload\n", ()),
            GeneratedFile(
                "sample/worker.py",
                "from pathlib import Path\nimport inspect\n"
                "from importlib.resources import files\n"
                "def run():\n"
                "    print(Path(__file__).is_file())\n"
                "    print('def run():' in inspect.getsource(run))\n"
                "    print(files('sample').joinpath('data.txt').read_text().strip())\n",
                (),
            ),
            GeneratedFile("run_project.py", "from sample import run\nrun()\n", ()),
        ),
        None,
        None,
    )


def test_files_inspection_and_package_resources_have_run_trace_debug_parity(tmp_path):
    project = _project()
    for item in project.files:
        path = tmp_path / item.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(item.source, encoding="utf-8")
    expected = "True\nTrue\nresource payload\n"
    trace = trace_project(project)
    for result in (
        run_generated(tmp_path / project.launcher_path),
        run_project(project),
        trace.run,
    ):
        assert result.return_code == 0, result.stderr
        assert result.stdout == expected
    assert {"sample/__init__.py", "sample/worker.py", "run_project.py"} <= {
        event.file_path for event in trace.events
    }
    assert any(event.location == SourceLocation("sample/worker.py", 5) for event in trace.events)
    with DebugSession() as debugger:
        debugger.start(
            DebugLaunch(project=project, breakpoints=(SourceLocation("sample/worker.py", 5),))
        )
        paused = debugger.wait_for("paused")
        assert paused.location == SourceLocation("sample/worker.py", 5)
        assert paused.reason == "breakpoint"
        assert {frame.file_path for frame in paused.stack} == {"sample/worker.py", "run_project.py"}
        debugger.set_breakpoints((SourceLocation("sample/worker.py", 7),))
        debugger.continue_execution()
        assert debugger.wait_for("paused").location == SourceLocation("sample/worker.py", 7)
        debugger.continue_execution()
        assert debugger.wait_for("finished").return_code == 0


def test_same_line_in_another_file_does_not_trigger_a_breakpoint():
    project = GeneratedProject(
        (
            GeneratedFile("left.py", "def run():\n    value = 1\n    return value\n", ()),
            GeneratedFile("right.py", "def run():\n    value = 2\n    return value\n", ()),
            GeneratedFile("run_project.py", "import left, right\nleft.run()\nright.run()\n", ()),
        ),
        None,
        None,
    )
    with DebugSession() as debugger:
        debugger.start(DebugLaunch(project=project, breakpoints=(SourceLocation("right.py", 2),)))
        paused = debugger.wait_for("paused")
        assert paused.location == SourceLocation("right.py", 2)
        assert paused.function == "run"
        debugger.continue_execution()
        assert debugger.wait_for("finished").return_code == 0


def test_live_project_preserves_explicit_working_directory_and_environment(tmp_path):
    project = GeneratedProject(
        (
            GeneratedFile(
                "run_project.py",
                "import os\nfrom pathlib import Path\n"
                "print(Path.cwd().name)\nprint(os.environ['CV_PROJECT_TEST'])\n",
                (),
            ),
        ),
        None,
        None,
    )
    for result in (
        run_project(project, working_directory=tmp_path, environment={"CV_PROJECT_TEST": "value"}),
        trace_project(
            project, working_directory=tmp_path, environment={"CV_PROJECT_TEST": "value"}
        ).run,
    ):
        assert result.return_code == 0, result.stderr
        assert result.stdout == f"{tmp_path.name}\nvalue\n"


@pytest.mark.parametrize(
    "path", ("../outside.py", "/absolute.py", "C:/absolute.py", "x/../y.py", "x\\y.py")
)
def test_generated_tree_rejects_escape_paths_before_writing(path):
    with pytest.raises(ValueError, match="relative and normalized"):
        MaterializedProject(GeneratedProject((GeneratedFile(path, "", ()),), None, None))


def test_project_breakpoints_cannot_be_unqualified():
    with pytest.raises(ValueError, match="file-qualified"):
        DebugLaunch(project=_project(), breakpoints=(2,))


def test_background_stop_releases_temporary_files(monkeypatch):
    roots = []
    original = MaterializedProject

    class ObservedTree(original):
        def __init__(self, project):
            super().__init__(project)
            roots.append(self.root)

    monkeypatch.setattr("code_visualizer.execution.runner.MaterializedProject", ObservedTree)
    project = GeneratedProject(
        (GeneratedFile("run_project.py", "import time\ntime.sleep(60)\n", ()),), None, None
    )
    session, done, results = RunSession(), Event(), []

    def complete(result):
        results.append(result)
        done.set()

    session.start_project(project, completed=complete)
    deadline = monotonic() + 5
    while not roots and monotonic() < deadline:
        sleep(0.01)
    assert roots
    session.stop()
    assert done.wait(5)
    assert results[0].termination_reason == "stopped"
    assert not roots[0].exists()


def test_module_initialization_exceptions_map_to_the_real_file():
    project = replace(
        _project(),
        files=(GeneratedFile("run_project.py", "raise RuntimeError('module failed')\n", ()),),
    )
    trace = trace_project(project)
    assert trace.run.return_code == 1
    assert "run_project.py" in trace.run.stderr
    assert any(
        event.file_path == "run_project.py" and event.event == "exception" for event in trace.events
    )


@pytest.mark.parametrize("tracing", (False, True))
def test_background_startup_failure_completes_without_leaking_a_tree(monkeypatch, tracing):
    roots = []

    class ObservedTree(MaterializedProject):
        def __init__(self, project):
            super().__init__(project)
            roots.append(self.root)

    for adapter in ("runner", "debugger"):
        monkeypatch.setattr(
            f"code_visualizer.execution.{adapter}.MaterializedProject", ObservedTree
        )
    session, done, results = RunSession(), Event(), []

    def complete(value):
        results.append(value.run if tracing else value)
        done.set()

    start = session.start_project_trace if tracing else session.start_project
    start(_project(), interpreter="missing-python-interpreter-for-test", completed=complete)
    assert done.wait(5)
    assert results[0].return_code != 0
    assert "FileNotFoundError" in results[0].stderr
    assert roots and all(not root.exists() for root in roots)


def test_debugger_restart_retains_locations_but_replaces_disposable_files():
    project = _project()
    with DebugSession() as debugger:
        debugger.start(
            DebugLaunch(project=project, breakpoints=(SourceLocation("sample/worker.py", 5),))
        )
        assert debugger.wait_for("paused").location == SourceLocation("sample/worker.py", 5)
        first = debugger._tree.root
        debugger.restart()
        assert debugger.wait_for("paused").location == SourceLocation("sample/worker.py", 5)
        second = debugger._tree.root
        assert first != second and not first.exists() and second.exists()
    assert not second.exists()
