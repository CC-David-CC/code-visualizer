"""Authored package initializers are canonical modules with ordinary Python behavior."""

from dataclasses import replace

import pytest

from code_visualizer.application.queries import ProjectQueries
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.program import (
    ExpressionRole,
    ProgramAction,
    ProgramEntryPoint,
    ProgramFunctionReference,
    ProgramModel,
    ProgramModule,
    ProgramSequence,
    make_program_expression,
)
from code_visualizer.domain.program_kinds import ProgramModuleKind
from code_visualizer.domain.project import Project
from code_visualizer.domain.python_declarations import parse_python_declarations
from code_visualizer.execution import run_generated, run_project, trace_project
from code_visualizer.generation import generate_python_project
from code_visualizer.generation.program_composition import compose_programs
from code_visualizer.generation.transformation import TransformationError
from code_visualizer.validation import assess_project


def _module(identity, path, source, *, package=False):
    return ProgramModule(
        identity,
        path,
        parse_python_declarations(identity, source, identity_namespace=identity),
        kind=ProgramModuleKind.PACKAGE if package else ProgramModuleKind.MODULE,
    )


def _project(*, root_entrypoint=False):
    session = ProjectSession.new()
    try:
        project = session.authority.snapshot()
    finally:
        session.close()
    function = project.program_model.functions[0]
    action = ProgramAction(
        "entry:action",
        make_program_expression(
            "entry:action", "source", "print(__name__, VALUE, log)", ExpressionRole.STATEMENTS
        ),
    )
    function = replace(function, body=ProgramSequence(function.body.id, (action,)))
    modules = [
        _module("events", "events", "log = []"),
        _module(
            "nested:package",
            "nested",
            "from ..events import log\nlog.append('nested')\n"
            "from .. import ROOT\nNESTED = ROOT + 1",
            package=True,
        ),
        _module(
            "helper",
            "nested.helper",
            "from . import NESTED\nfrom ..events import log\n"
            "log.append('helper')\nVALUE = NESTED + 1",
        ),
    ]
    root = _module(
        "root:package", "", "from .events import log\nlog.append('root')\nROOT = 7", package=True
    )
    owner = root if root_entrypoint else _module("main:module", "main", "")
    tail = parse_python_declarations(
        owner.id,
        "from .nested.helper import VALUE\nfrom .events import log",
        identity_namespace="entry:imports",
    )
    owner = replace(owner, body=(*owner.body, *tail, ProgramFunctionReference(function.id)))
    # Deliberately put children first: import dependencies, not tuple order, initialize packages.
    modules.extend((owner,) if root_entrypoint else (owner, root))
    model = replace(
        project.program_model,
        functions=(function,),
        modules=tuple(modules),
        entrypoint=ProgramEntryPoint("entrypoint", function.id),
    )
    return replace(project, program_model=model, documents=(), drakon_views=())


@pytest.mark.parametrize("root_entrypoint", (False, True))
def test_authored_initializers_relative_imports_and_entrypoints_use_one_file_tree(
    tmp_path,
    root_entrypoint,
):
    project = _project(root_entrypoint=root_entrypoint)
    assert assess_project(project).diagnostics == ()
    generated = generate_python_project(project)
    assert "ROOT = 7" in generated.file("app/__init__.py").source
    assert "NESTED = ROOT + 1" in generated.file("app/nested/__init__.py").source
    assert not any("MetaPathFinder" in item.source for item in generated.files)
    assert "project.py" not in {item.path for item in generated.files}
    for item in generated.files:
        target = tmp_path / item.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item.source, encoding="utf-8")
    persistent = run_generated(tmp_path / generated.launcher_path, working_directory=tmp_path)
    live = run_project(generated)
    trace = trace_project(generated)
    expected = f"{'app' if root_entrypoint else 'app.main'} 9 ['root', 'nested', 'helper']\n"
    for result in (persistent, live, trace.run):
        assert result.return_code == 0, result.stderr
        assert result.stdout == expected
    paths = {event.file_path for event in trace.events}
    assert {"app/__init__.py", "app/nested/__init__.py", "app/nested/helper.py"} <= paths
    queries = ProjectQueries.from_project(project)
    assert queries.semantic_object("nested:package").parent_id == "root:package"
    assert queries.semantic_object("helper").parent_id == "nested:package"
    assert all(item.id != "namespace:app.nested" for item in queries.program.objects)


@pytest.mark.parametrize(
    "package,path,kind,other,code",
    (
        ("app", "", ProgramModuleKind.MODULE, None, "PY_INVALID_MODULE_PATH"),
        ("", "", ProgramModuleKind.PACKAGE, None, "PY_INVALID_PACKAGE_PATH"),
        ("app", "tools", ProgramModuleKind.MODULE, "tools.child", "PY_MODULE_PACKAGE_COLLISION"),
        ("app", "__init__", ProgramModuleKind.MODULE, None, "PY_RESERVED_MODULE_PATH"),
    ),
)
def test_invalid_package_layout_is_explicit(package, path, kind, other, code):
    modules = (ProgramModule("module", path, kind=kind),)
    if other:
        modules += (ProgramModule("other", other),)
    project = Project(
        "project", "Packages", (), program_model=ProgramModel(modules=modules, package=package)
    )
    assert code in {item.code for item in assess_project(project).diagnostics}


def test_derived_contributions_cannot_change_module_to_package():
    authored = ProgramModel(modules=(ProgramModule("module", "tools"),))
    derived = ProgramModel(
        modules=(ProgramModule("package", "tools", kind=ProgramModuleKind.PACKAGE),)
    )
    with pytest.raises(TransformationError, match="both a module and a package"):
        compose_programs(authored, derived)
