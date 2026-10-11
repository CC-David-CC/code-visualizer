from __future__ import annotations

import ast
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "code_visualizer"
CORE_DIRECTORIES = {
    "application",
    "domain",
    "execution",
    "generation",
    "layout",
    "persistence",
    "protocol",
    "rendering",
    "validation",
}
PROTOTYPE_ROOTS = {"drakonpy", "drakon_editor1"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", maxsplit=1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", maxsplit=1)[0])
    return roots


def test_new_source_never_imports_parent_prototype() -> None:
    violations: list[str] = []
    for path in SOURCE_ROOT.rglob("*.py"):
        forbidden = _imports(path) & PROTOTYPE_ROOTS
        if forbidden:
            violations.append(f"{path.relative_to(SOURCE_ROOT)}: {sorted(forbidden)}")
    assert violations == []


def test_core_has_no_qt_dependency() -> None:
    violations: list[str] = []
    for directory in sorted(CORE_DIRECTORIES):
        root = SOURCE_ROOT / directory
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if "PySide6" in _imports(path):
                violations.append(str(path.relative_to(SOURCE_ROOT)))
    assert violations == []
