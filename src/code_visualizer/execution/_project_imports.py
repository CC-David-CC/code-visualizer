"""Standalone stdlib bootstrap for ordinary emitted Python files."""

from __future__ import annotations

import os
import pkgutil  # runpy imports this lazily; load its own dependency before the project path.
import runpy
import sys
from collections.abc import Callable
from importlib.machinery import BuiltinImporter, FrozenImporter, PathFinder
from pathlib import Path
from types import FrameType
from typing import Any


def _release_authored_imports(root: Path) -> None:
    candidates = {
        path.stem if path.is_file() else path.name
        for path in root.iterdir()
        if path.is_dir() or path.suffix == ".py"
    }
    selected = []
    for name in sorted(candidates):
        if (
            not name.isidentifier()
            or BuiltinImporter.find_spec(name) is not None
            or FrozenImporter.find_spec(name) is not None
        ):
            continue
        spec = PathFinder.find_spec(name, sys.path)
        if (
            spec is not None
            and isinstance(spec.origin, str)
            and Path(spec.origin).resolve().is_relative_to(root)
        ):
            selected.append(name)
    for name in tuple(sys.modules):
        if any(name == owner or name.startswith(owner + ".") for owner in selected):
            del sys.modules[name]


def execute_project(
    root: Path,
    launcher: Path,
    *,
    trace: Callable[[FrameType, str, object], Any] | None = None,
) -> None:
    """Enter real source after runpy setup, with normal authored import precedence."""

    # Retain the stdlib module object until runpy has loaded the actual launcher.
    # Its first call event precedes every authored statement and follows runpy's
    # lazy get_importer/read_code imports, so an authored pkgutil is safe there.
    root = root.resolve()
    launcher = launcher.resolve()
    pkgutil.get_importer(str(launcher))
    filename = os.path.normcase(str(launcher))
    prepared = False
    previous_path = sys.path[:]
    previous_argv = sys.argv
    previous_trace = sys.gettrace()
    previous_bytecode = sys.dont_write_bytecode

    def enter(frame: FrameType, event: str, argument: object) -> Any:
        nonlocal prepared
        if (
            not prepared
            and event == "call"
            and os.path.normcase(frame.f_code.co_filename) == filename
        ):
            _release_authored_imports(root)
            prepared = True
            if trace is None:
                sys.settrace(None)
        if trace is not None:
            return trace(frame, event, argument)
        return None

    try:
        sys.path.insert(0, str(root))
        sys.argv = [str(launcher)]
        sys.dont_write_bytecode = True
        sys.settrace(enter)
        runpy.run_path(str(launcher), run_name="__main__")
    finally:
        sys.settrace(previous_trace)
        sys.path[:] = previous_path
        sys.argv = previous_argv
        sys.dont_write_bytecode = previous_bytecode


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("A project worker requires its emitted root and launcher")
    execute_project(Path(sys.argv[1]), Path(sys.argv[2]))
