"""Select a real child-Python boundary in source and frozen installations."""

from __future__ import annotations

import runpy
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

INTERNAL_PYTHON_WORKER = "--code-visualizer-internal-python"
DEBUG_WORKER = "--debug-worker"
PROJECT_WORKER = "--project-worker"
COMPUTATION_WORKER = "--computation-worker"


def is_frozen_application() -> bool:
    """Return whether the current interpreter is a frozen application bootloader."""

    return bool(getattr(sys, "frozen", False))


def python_child_command(
    arguments: Sequence[str],
    *,
    interpreter: str = "",
) -> list[str]:
    """Build a command for isolated Python code without re-entering a frozen CLI."""

    configured = interpreter.strip()
    if configured:
        return [configured, *arguments]
    if is_frozen_application():
        return [sys.executable, INTERNAL_PYTHON_WORKER, *arguments]
    return [sys.executable, *arguments]


def debug_worker_command(source_worker: Path, *, interpreter: str = "") -> list[str]:
    """Build the interactive-debug worker command for either distribution form."""

    if interpreter.strip():
        return [interpreter.strip(), "-I", str(source_worker)]
    if is_frozen_application():
        return [sys.executable, INTERNAL_PYTHON_WORKER, DEBUG_WORKER]
    return [sys.executable, "-I", str(source_worker)]


def project_child_command(root: Path, launcher: Path, *, interpreter: str = "") -> list[str]:
    """Use one real-file bootstrap in source and frozen installations."""

    if is_frozen_application() and not interpreter.strip():
        return [sys.executable, INTERNAL_PYTHON_WORKER, PROJECT_WORKER, str(root), str(launcher)]
    return python_child_command(
        [
            "-I",
            "-B",
            str(Path(__file__).with_name("_project_imports.py")),
            str(root),
            str(launcher),
        ],
        interpreter=interpreter,
    )


def computation_worker_command(source_worker: Path) -> list[str]:
    """Choose the fixed trusted computation entry in either distribution."""
    if is_frozen_application():
        return [sys.executable, INTERNAL_PYTHON_WORKER, COMPUTATION_WORKER]
    return [sys.executable, "-I", str(source_worker)]


def dispatch_internal_worker(
    arguments: Sequence[str] | None = None,
    *,
    computation_worker: Callable[[], int] | None = None,
) -> int | None:
    """Run the private frozen child mode, or return ``None`` for the normal entry."""

    values = list(sys.argv[1:] if arguments is None else arguments)
    if not values or values[0] != INTERNAL_PYTHON_WORKER:
        return None
    values.pop(0)
    if values == [COMPUTATION_WORKER]:
        if computation_worker is None:
            raise SystemExit("No trusted computation worker entry is installed")
        return computation_worker()
    if values == [DEBUG_WORKER]:
        from code_visualizer.execution.debug_worker import main as debug_main

        return debug_main()
    if len(values) == 3 and values[0] == PROJECT_WORKER:
        from code_visualizer.execution._project_imports import execute_project

        execute_project(Path(values[1]), Path(values[2]))
        return 0
    while values and values[0] in {"-I", "-B"}:
        flag = values.pop(0)
        if flag == "-B":
            sys.dont_write_bytecode = True
    if len(values) >= 2 and values[0] == "-c":
        source = values[1]
        previous_argv = sys.argv
        sys.argv = ["-c", *values[2:]]
        try:
            scope: dict[str, object] = {
                "__builtins__": __builtins__,
                "__name__": "__main__",
            }
            exec(compile(source, "<string>", "exec"), scope, scope)
        finally:
            sys.argv = previous_argv
        return 0
    if len(values) == 1:
        runpy.run_path(values[0], run_name="__main__")
        return 0
    raise SystemExit("Invalid internal Python worker invocation")
