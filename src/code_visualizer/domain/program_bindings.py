"""Pure Python lexical binding for identity-linked canonical calls."""

from __future__ import annotations

import ast
from importlib.util import resolve_name
from unicodedata import normalize

from code_visualizer.domain.module_paths import qualified_module_name
from code_visualizer.domain.program import (
    ProgramClass,
    ProgramEntryPoint,
    ProgramFunction,
    ProgramImport,
    ProgramModel,
    ProgramModule,
)
from code_visualizer.domain.program_kinds import MethodKind, ProgramModuleKind

type ProgramScope = ProgramFunction | ProgramModule | ProgramClass | ProgramEntryPoint


def mangle_python_identifier(identifier: str, owner: str | None = None) -> str:
    """Spell a member outside its lexical class, retaining legal source spellings."""
    normalized = normalize("NFKC", identifier)
    owner = normalize("NFKC", owner).lstrip("_") if owner is not None else ""
    return (
        f"_{owner}{normalized}"
        if owner and normalized.startswith("__") and not normalized.endswith("__")
        else identifier
    )


def python_member_path(identifier: str, class_names: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Resolve a callable's external path using each original lexical class name.

    A private nested class has a different external attribute spelling, but that
    spelling never becomes the lexical owner used to mangle its own members.
    """
    owners = tuple(
        mangle_python_identifier(name, class_names[index - 1] if index else None)
        for index, name in enumerate(class_names)
    )
    return (*owners, mangle_python_identifier(identifier, class_names[-1] if class_names else None))


def _classes(model: ProgramModel, identity: str) -> tuple[ProgramClass, ...]:
    result = []
    owner = model.class_for(identity)
    while owner is not None:
        result.append(owner)
        owner = model.class_for(owner.id)
    return tuple(reversed(result))


def resolve_linked_callable(
    model: ProgramModel, scope: ProgramScope, target: ProgramFunction
) -> str | None:
    """Resolve the target using this Python scope's declared imports and ownership.

    Function bodies use module globals; a class body additionally has its own
    namespace while the class itself is still being constructed. Launcher startup
    has its own declared imports and never borrows the selected module's globals.
    This operation computes names only; it does not execute Python or import code.
    """
    target_module = model.module_for(target.id)
    if target_module is None:
        return None
    classes = _classes(model, target.id)
    if isinstance(scope, ProgramClass) and classes and classes[-1].id == scope.id:
        return None if target.method_kind is MethodKind.CLASS else target.identifier
    path = python_member_path(target.identifier, tuple(item.identifier for item in classes))
    parts, member = path[:-1], path[-1]
    suffix = (*parts[1:], member) if classes else ()
    root = parts[0] if classes else target.identifier
    local_module = model.module_for(scope.id)
    declarations = (
        scope.startup
        if isinstance(scope, ProgramEntryPoint)
        else scope.body
        if isinstance(scope, ProgramModule | ProgramClass)
        else local_module.body
        if local_module is not None
        else ()
    )
    if isinstance(scope, ProgramClass) and local_module is not None:
        declarations = (*declarations, *local_module.body)
    qualified_target = qualified_module_name(
        model.package, target_module.path, kind=target_module.kind
    )
    for item in declarations:
        if not isinstance(item, ProgramImport):
            continue
        try:
            imports = ast.parse(item.source.source).body
        except SyntaxError:
            continue
        for imported in imports:
            if isinstance(imported, ast.Import):
                for alias in imported.names:
                    if alias.name == qualified_target:
                        return ".".join((alias.asname or alias.name, root, *suffix))
            elif isinstance(imported, ast.ImportFrom):
                module_name = imported.module or ""
                if imported.level:
                    if local_module is None:
                        continue
                    package = qualified_module_name(
                        model.package, local_module.path, kind=local_module.kind
                    )
                    if local_module.kind is ProgramModuleKind.MODULE:
                        package = package.rpartition(".")[0]
                    try:
                        module_name = resolve_name("." * imported.level + module_name, package)
                    except ImportError:
                        continue
                for alias in imported.names:
                    if module_name == qualified_target and alias.name == normalize("NFKC", root):
                        return ".".join((alias.asname or alias.name, *suffix))
                    if f"{module_name}.{alias.name}" == qualified_target:
                        return ".".join((alias.asname or alias.name, root, *suffix))
    if local_module is not None and local_module.id == target_module.id:
        if isinstance(scope, ProgramClass):
            index = next((i for i, item in enumerate(classes) if item.id == scope.id), None)
            if index is not None:
                nested = classes[index + 1 :]
                if nested:
                    return ".".join((nested[0].identifier, *parts[index + 2 :], member))
        return ".".join((root, *suffix))
    return None
