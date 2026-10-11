"""Keep executable semantics independent of their editors and projections."""

import ast
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
PACKAGE_ROOT = SOURCE_ROOT / "code_visualizer"


def _imports(relative_path: str) -> set[str]:
    tree = ast.parse((PACKAGE_ROOT / relative_path).read_text(encoding="utf-8"))
    result = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
            result.update(f"{node.module}.{alias.name}" for alias in node.names)
    return result


def _matches_module(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(f"{prefix}.")


@pytest.mark.parametrize(
    "module",
    ["program", "expression", "program_kinds", "program_signatures"],
)
def test_canonical_modules_have_no_projection_or_application_imports(module: str) -> None:
    forbidden = (
        "code_visualizer.domain.drakon",
        "code_visualizer.application",
        "code_visualizer.generation",
        "code_visualizer.persistence",
        "code_visualizer.ui_qt",
    )
    imports = _imports(f"domain/{module}.py")
    assert not {
        name for name in imports if any(_matches_module(name, prefix) for prefix in forbidden)
    }


def test_domain_has_no_outward_dependencies() -> None:
    forbidden = (
        "code_visualizer.application",
        "code_visualizer.generation",
        "code_visualizer.persistence",
        "code_visualizer.ui_qt",
        "code_visualizer.validation",
        "code_visualizer.protocol",
        "code_visualizer.execution",
        "code_visualizer.extensions",
        "google.protobuf",
    )
    violations = {}
    for source in (PACKAGE_ROOT / "domain").rglob("*.py"):
        relative_path = source.relative_to(PACKAGE_ROOT).as_posix()
        outward = {
            name
            for name in _imports(relative_path)
            if any(_matches_module(name, prefix) for prefix in forbidden)
        }
        if outward:
            violations[relative_path] = outward
    assert not violations


@pytest.mark.parametrize(
    "module", ["values", "resources", "intentional", "computation", "evidence"]
)
def test_universal_contracts_do_not_import_concrete_foundations_or_backends(module: str) -> None:
    imports = _imports(f"domain/{module}.py")
    assert not {
        name
        for name in imports
        if _matches_module(name, "code_visualizer.extensions")
        or _matches_module(name, "code_visualizer.execution")
        or _matches_module(name, "code_visualizer.protocol")
        or _matches_module(name, "PySide6")
    }


def test_canonical_model_imports_without_loading_an_editor_or_adapter() -> None:
    # A separate interpreter also detects dependencies hidden in package __init__ files.
    script = f"""
import importlib.abc
import sys

sys.path.insert(0, {str(SOURCE_ROOT)!r})

class RejectProjectionImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        forbidden = (
            'code_visualizer.domain.drakon',
            'code_visualizer.application',
            'code_visualizer.generation',
            'code_visualizer.persistence',
            'code_visualizer.ui_qt',
        )
        if any(fullname == item or fullname.startswith(item + '.') for item in forbidden):
            raise AssertionError('Canonical model imported ' + fullname)
        return None

sys.meta_path.insert(0, RejectProjectionImports())
from code_visualizer.domain.program import ProgramModel
from code_visualizer.domain.program_kinds import CallableKind
from code_visualizer.domain.program_signatures import FunctionSpec, ParameterSpec

assert ProgramModel().functions == ()
assert CallableKind.__module__ == 'code_visualizer.domain.program_kinds'
assert FunctionSpec.__module__ == 'code_visualizer.domain.program_signatures'
assert ParameterSpec.__module__ == 'code_visualizer.domain.program_signatures'
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "name",
    [
        "CallableKind",
        "ParameterKind",
        "MethodKind",
        "TransferKind",
        "LoopKind",
        "SelectMode",
        "ParallelMode",
        "NotePlacement",
        "SimpleKind",
    ],
)
def test_drakon_and_program_share_neutral_semantic_enum_identity(name: str) -> None:
    kinds = importlib.import_module("code_visualizer.domain.program_kinds")
    program = importlib.import_module("code_visualizer.domain.program")
    drakon = importlib.import_module("code_visualizer.domain.drakon")
    expected = getattr(kinds, name)
    assert expected.__module__ == kinds.__name__
    assert getattr(program, name) is expected
    assert getattr(drakon, name) is expected


@pytest.mark.parametrize("module", ["ir", "emitter", "lowering", "python"])
def test_python_lowering_and_ir_do_not_depend_on_drakon_semantics(module: str) -> None:
    forbidden = (
        "code_visualizer.domain.drakon",
        "code_visualizer.application",
    )
    imports = _imports(f"generation/{module}.py")
    assert not {
        name for name in imports if any(_matches_module(name, prefix) for prefix in forbidden)
    }


def test_drakon_conversion_apis_belong_to_the_application_adapter() -> None:
    program = importlib.import_module("code_visualizer.domain.program")
    adapter = importlib.import_module("code_visualizer.application.drakon_program_adapter")
    for name in (
        "promote_program_from_drakon",
        "drakon_from_program",
        "drakon_atom",
        "drakon_sequence",
    ):
        assert not hasattr(program, name)
        assert getattr(adapter, name).__module__ == adapter.__name__
