"""Canonical Python package/module paths shared by domain, UI, and generation."""

from __future__ import annotations

import keyword

from code_visualizer.domain.program_kinds import ProgramModuleKind


class PythonPathError(ValueError):
    """A user-facing package or module path cannot map to a safe Python path."""


def _normalize(
    value: str,
    *,
    allow_empty: bool,
    accept_python_file: bool,
) -> str:
    text = value.strip().replace("\\", "/")
    if not text:
        if allow_empty:
            return ""
        raise PythonPathError("A Python module path is required")
    if text.startswith("/") or ":" in text.split("/", 1)[0]:
        raise PythonPathError("Use a project-relative package or module path")
    if accept_python_file and text.casefold().endswith(".py"):
        text = text[:-3]
    parts = text.split("/") if "/" in text else text.split(".")
    if any(part in {"", ".", ".."} for part in parts):
        raise PythonPathError("Empty and parent-directory path segments are not allowed")
    invalid = next(
        (part for part in parts if not part.isidentifier() or keyword.iskeyword(part)),
        None,
    )
    if invalid is not None:
        raise PythonPathError(f"{invalid!r} is not a legal Python package name")
    return ".".join(parts)


def normalize_package_path(value: str, *, allow_empty: bool = True) -> str:
    """Accept dotted or slash-separated package input and return dotted form."""

    return _normalize(value, allow_empty=allow_empty, accept_python_file=False)


def normalize_module_path(value: str, *, kind: ProgramModuleKind = ProgramModuleKind.MODULE) -> str:
    """Accept ``math.vectors`` or ``math/vectors.py`` and return dotted form."""

    return _normalize(value, allow_empty=kind is ProgramModuleKind.PACKAGE, accept_python_file=True)


def canonical_package_path(value: str) -> str:
    """Best-effort normalization that preserves invalid text for diagnostics."""

    try:
        return normalize_package_path(value)
    except PythonPathError:
        return value.strip()


def canonical_module_path(value: str, *, kind: ProgramModuleKind = ProgramModuleKind.MODULE) -> str:
    """Best-effort normalization that preserves invalid text for diagnostics."""

    try:
        return normalize_module_path(value, kind=kind)
    except PythonPathError:
        return value.strip()


def python_module_file_path(
    package: str, module: str, *, kind: ProgramModuleKind = ProgramModuleKind.MODULE
) -> str:
    """Return a validated, project-relative POSIX path for one Python module."""

    normalized_package = normalize_package_path(package)
    normalized_module = normalize_module_path(module, kind=kind)
    parts = [
        *(normalized_package.split(".") if normalized_package else ()),
        *(normalized_module.split(".") if normalized_module else ()),
    ]
    if kind is ProgramModuleKind.PACKAGE:
        if not parts:
            raise PythonPathError("A package initializer needs a nonempty package import name")
        return "/".join((*parts, "__init__.py"))
    return "/".join(parts) + ".py"


def module_file_label(module: str, *, kind: ProgramModuleKind = ProgramModuleKind.MODULE) -> str:
    """Show a canonical module as the filesystem path users will receive."""

    try:
        normalized = normalize_module_path(module, kind=kind)
    except PythonPathError:
        return module
    if kind is ProgramModuleKind.PACKAGE:
        return (normalized.replace(".", "/") + "/" if normalized else "") + "__init__.py"
    return normalized.replace(".", "/") + ".py"


def qualified_module_name(
    package: str, module: str, *, kind: ProgramModuleKind = ProgramModuleKind.MODULE
) -> str:
    normalized_package = normalize_package_path(package)
    normalized_module = normalize_module_path(module, kind=kind)
    name = ".".join(part for part in (normalized_package, normalized_module) if part)
    if not name:
        raise PythonPathError("A package initializer needs a nonempty package import name")
    return name
