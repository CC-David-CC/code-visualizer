"""Materialize disposable generated files for ordinary Python file execution."""

from __future__ import annotations

import threading
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from code_visualizer.generation.emitter import GeneratedProject


def _relative_file(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or ":" in value
        or "\0" in value
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValueError(f"Generated file path must be relative and normalized: {value!r}")
    return path


class MaterializedProject:
    """Own real emitted files until the child process has completely exited."""

    def __init__(self, project: GeneratedProject) -> None:
        paths = tuple(_relative_file(item.path) for item in project.files)
        if len({str(path).casefold() for path in paths}) != len(paths):
            raise ValueError("Generated project contains colliding file paths")
        launcher = _relative_file(project.launcher_path)
        if launcher not in paths:
            raise ValueError("Generated project launcher is missing")
        self._temporary = TemporaryDirectory(prefix="code-visualizer-python-")
        self._lock = threading.Lock()
        self.root = Path(self._temporary.name).resolve()
        self.launcher = self.root.joinpath(*launcher.parts)
        self.files: dict[str, str] = {}
        try:
            for item, relative in zip(project.files, paths, strict=True):
                target = self.root.joinpath(*relative.parts)
                if not target.resolve().is_relative_to(self.root):
                    raise ValueError("Generated file escaped its temporary root")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(item.source, encoding="utf-8", newline="")
                self.files[str(target)] = item.path
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        with self._lock:
            self._temporary.cleanup()

    def __enter__(self) -> MaterializedProject:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
