"""Debug-worker imports cannot take ownership of authored Python package names."""

import subprocess
import sys
from dataclasses import replace
from importlib.machinery import FrozenImporter

import pytest

from code_visualizer.application.project_factory import create_default_project
from code_visualizer.domain.program import ExpressionRole, ProgramOutput, make_program_expression
from code_visualizer.domain.program_kinds import ProgramModuleKind
from code_visualizer.execution import (
    DebugLaunch,
    DebugSession,
    SourceLocation,
    run_generated,
    run_project,
    trace_project,
)
from code_visualizer.generation import generate_python_project
from code_visualizer.generation.emitter import GeneratedFile, GeneratedProject
from code_visualizer.validation import assess_project


@pytest.mark.parametrize("package", ("json", "traceback", "pkgutil"))
def test_authored_package_names_keep_direct_run_trace_and_debug_semantics(package, tmp_path):
    project = create_default_project()
    function = project.program_model.functions[0]
    operation = ProgramOutput(
        "operation:authored",
        make_program_expression(
            "operation:authored", "value", repr(f"authored {package}"), ExpressionRole.VALUE
        ),
    )
    function = replace(function, body=replace(function.body, statements=(operation,)))
    owner = replace(project.program_model.modules[0], path="", kind=ProgramModuleKind.PACKAGE)
    project = replace(
        project,
        documents=(),
        drakon_views=(),
        program_model=replace(
            project.program_model, functions=(function,), modules=(owner,), package=package
        ),
    )
    assert assess_project(project).diagnostics == ()
    generated = generate_python_project(project)
    for item in generated.files:
        target = tmp_path / item.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item.source, encoding="utf-8")
    expected = f"authored {package}\n"
    direct = subprocess.run(
        [sys.executable, "-B", str(tmp_path / generated.launcher_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=5,
        check=False,
    )
    assert direct.returncode == 0, direct.stderr
    assert direct.stdout == expected
    for result in (run_generated(tmp_path / generated.launcher_path), run_project(generated)):
        assert result.return_code == 0, result.stderr
        assert result.stdout == expected
    traced = trace_project(generated)
    assert traced.run.return_code == 0, traced.run.stderr
    assert traced.run.stdout == expected
    span = next(item for item in generated.spans if item.semantic_id == operation.id)
    location = SourceLocation(span.file_path, span.start_line)
    assert span.file_path == f"{package}/__init__.py"
    assert any(event.location == location for event in traced.events)
    with DebugSession() as debugger:
        debugger.start(DebugLaunch(project=generated, breakpoints=(location,)))
        paused = debugger.wait_for("paused")
        assert paused.location == location
        assert paused.reason == "breakpoint"
        assert paused.function == function.identifier
        debugger.continue_execution()
        output = []
        while True:
            event = debugger.wait_event()
            if event.event == "output" and event.channel == "stdout":
                output.append(event.text)
            if event.event in {"finished", "failed", "stopped"}:
                assert event.event == "finished", event.traceback
                assert event.return_code == 0
                break
        assert "".join(output) == expected


def test_live_run_and_trace_expose_only_the_launcher_in_sys_argv():
    project = GeneratedProject(
        (
            GeneratedFile(
                "run_project.py",
                "import sys\nfrom pathlib import Path\n"
                "print(sys.argv[1:])\nprint(Path(sys.argv[0]).name)\n",
                (),
            ),
        ),
        None,
        None,
    )
    for result in (run_project(project), trace_project(project).run):
        assert result.return_code == 0, result.stderr
        assert result.stdout == "[]\nrun_project.py\n"


@pytest.mark.parametrize("module, origin", (("sys", "built-in"), ("runpy", "frozen")))
def test_authored_files_preserve_builtin_and_frozen_import_precedence(module, origin):
    if origin == "frozen" and FrozenImporter.find_spec(module) is None:
        pytest.skip(f"{module} is not frozen in this interpreter")
    project = GeneratedProject(
        (
            GeneratedFile(
                f"{module}.py",
                "raise AssertionError('Authored file displaced Python module')\n",
                (),
            ),
            GeneratedFile(
                "run_project.py", f"import {module}\nprint({module}.__spec__.origin)\n", ()
            ),
        ),
        None,
        None,
    )
    for result in (run_project(project), trace_project(project).run):
        assert result.return_code == 0, result.stderr
        assert result.stdout == f"{origin}\n"


def test_plain_run_removes_bootstrap_trace_before_any_authored_code():
    project = GeneratedProject(
        (
            GeneratedFile(
                "json/__init__.py",
                "import sys\ntrace_during_import = sys.gettrace()\n"
                "def current_trace():\n    return sys.gettrace()\n",
                (),
            ),
            GeneratedFile(
                "run_project.py",
                "import sys\nprint(sys.gettrace() is None)\n"
                "from json import trace_during_import, current_trace\n"
                "print(trace_during_import is None)\nprint(current_trace() is None)\n",
                (),
            ),
        ),
        None,
        None,
    )
    result = run_project(project)
    assert result.return_code == 0, result.stderr
    assert result.stdout == "True\nTrue\nTrue\n"
