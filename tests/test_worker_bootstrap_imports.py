"""Generic worker bootstrap does not load the Python execution implementation."""

import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
FORBIDDEN = (
    "code_visualizer.execution.debugger",
    "code_visualizer.execution.runner",
    "code_visualizer.execution.project_files",
    "code_visualizer.generation.artifacts",
    "code_visualizer.generation.python",
    "code_visualizer.rendering",
    "code_visualizer.ui_qt",
    "PySide6",
)


def guarded_source():
    return (
        f"import sys\nsys.path[:0] = {[str(SOURCE), str(TESTS)]!r}\n"
        + f"forbidden = {FORBIDDEN!r}\n"
        + dedent(
            """
            class RejectExecutionImplementation:
                def find_spec(self, fullname, path=None, target=None):
                    if any(
                        fullname == name or fullname.startswith(name + '.') for name in forbidden
                    ):
                        raise ImportError('Unexpected generic-worker dependency: ' + fullname)
            sys.meta_path.insert(0, RejectExecutionImplementation())
            """
        )
    )


@pytest.mark.parametrize(
    "module",
    (
        "code_visualizer.execution.worker_process",
        "code_visualizer.generation.computation",
    ),
)
def test_leaf_imports_do_not_eagerly_load_python_execution(module, tmp_path):
    result = subprocess.run(
        [sys.executable, "-I", "-c", guarded_source() + f"import {module}\n"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_real_generic_worker_prepares_and_executes_without_python_runner(tmp_path):
    from fixtures.computation_worker_fixture import BACKEND_ID, fixture_registry

    from code_visualizer.application.authority import ProjectAuthority
    from code_visualizer.application.computation import execute_computation
    from code_visualizer.application.computation_service import ComputationService
    from code_visualizer.application.kernel import ProjectKernel
    from code_visualizer.application.project_factory import create_default_project
    from code_visualizer.domain.computation import ComputationParameter, ComputationRequest
    from code_visualizer.domain.evidence import ComputationOutcome
    from code_visualizer.execution.worker_process import WorkerProfile
    from code_visualizer.persistence.evidence_store import EvidenceStore
    from code_visualizer.persistence.resource_store import ResourceStore

    script = tmp_path / "guarded_worker.py"
    script.write_text(
        guarded_source()
        + "from fixtures.computation_worker_fixture import fixture_registry\n"
        + "from code_visualizer.application.computation_worker import serve\n"
        + "raise SystemExit(serve(fixture_registry))\n",
        encoding="utf-8",
    )
    profile = WorkerProfile(
        "guarded-generic-worker",
        "1",
        (sys.executable, "-I", str(script)),
        ((BACKEND_ID, "1"),),
    )
    project = create_default_project()
    service = ComputationService(profiles=(profile,))
    kernel = ProjectKernel(
        ProjectAuthority(project),
        computations=service,
        extensions=fixture_registry(),
        resource_store=ResourceStore(tmp_path / "store"),
        evidence_store=EvidenceStore(tmp_path / "store"),
    )
    before = kernel.authority.snapshot()
    try:
        evidence = execute_computation(
            kernel,
            ComputationRequest(
                project.id,
                project.revision,
                BACKEND_ID,
                "1",
                configuration=(ComputationParameter("count", 2),),
            ),
        )
        assert evidence.outcome is ComputationOutcome.SUCCEEDED, evidence.diagnostics
        assert evidence.provenance.terminal_resource is not None
        assert kernel.authority.snapshot() is before
    finally:
        kernel.close()
        service.close()
