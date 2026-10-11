"""External invocation paths retain Python's original lexical class ownership."""

from dataclasses import replace

import pytest

from code_visualizer.domain.invocation import InvocationBindingError, bind_invocation
from code_visualizer.domain.invocation_arguments import parse_invocation_arguments
from code_visualizer.domain.program import (
    ExpressionRole,
    ProgramClass,
    ProgramEntryPoint,
    ProgramFunction,
    ProgramFunctionReference,
    ProgramModel,
    ProgramModule,
    ProgramOutput,
    ProgramParameter,
    ProgramSequence,
    ProgramSymbol,
    ProgramSymbolKind,
    make_program_expression,
)
from code_visualizer.domain.program_bindings import python_member_path, resolve_linked_callable
from code_visualizer.domain.program_kinds import CallableKind, MethodKind
from code_visualizer.domain.project import Project
from code_visualizer.execution import run_generated, run_project, trace_project
from code_visualizer.execution.runtime import program_binding_specs
from code_visualizer.generation.emitter import emit_project
from code_visualizer.generation.lowering import lower_project
from code_visualizer.persistence.serialization import project_to_data
from code_visualizer.validation import assess_project


def _project(method):
    parameters = (
        *(
            (
                ProgramParameter(
                    "receiver",
                    "symbol:receiver",
                    "self" if method is MethodKind.INSTANCE else "cls",
                ),
            )
            if method is not MethodKind.STATIC
            else ()
        ),
        ProgramParameter("value", "symbol:value", "__value"),
    )
    function = ProgramFunction(
        "function:entry",
        "symbol:entry",
        "__run",
        "Private entrypoint",
        CallableKind.SYNC,
        parameters,
        None,
        (),
        None,
        method,
        ProgramSequence(
            "body:entry",
            (
                ProgramOutput(
                    "output:entry",
                    make_program_expression(
                        "output:entry", "value", "__value", ExpressionRole.VALUE
                    ),
                ),
            ),
        ),
    )
    symbols = (
        ProgramSymbol(
            function.symbol_id,
            function.identifier,
            ProgramSymbolKind.FUNCTION,
            function.id,
            function.id,
        ),
        *(
            ProgramSymbol(
                parameter.symbol_id,
                parameter.name,
                ProgramSymbolKind.PARAMETER,
                function.id,
                parameter.id,
            )
            for parameter in parameters
        ),
    )
    inner = ProgramClass("class:inner", "__Inner", (ProgramFunctionReference(function.id),))
    outer = ProgramClass("class:outer", "Outer", (inner,))
    model = ProgramModel(
        (function,),
        symbols,
        (ProgramModule("module:main", "main", (outer,)),),
        entrypoint=ProgramEntryPoint(
            "entrypoint", function.id, parse_invocation_arguments("_Inner__value=7")
        ),
    )
    return Project("project:private-entry", "Private entrypoint", (), program_model=model)


def test_private_nested_parameter_keeps_its_semantic_symbol_in_runtime_bindings():
    project = _project(MethodKind.STATIC)
    model = project.program_model
    generated = emit_project(lower_project(project))
    traced = trace_project(generated, binding_specs=program_binding_specs(model))
    assert traced.run.return_code == 0, traced.run.stderr
    assert traced.run.stdout == "7\n"
    bindings = tuple(
        binding
        for event in traced.runtime_events
        if event.runtime_graph is not None
        for binding in event.runtime_graph.bindings
        if binding.name == "_Inner__value"
    )
    assert bindings
    assert all(binding.semantic_symbol_id == "symbol:value" for binding in bindings)
    assert model.symbol("symbol:value").name == "__value"
    assert project.program_model == model


@pytest.mark.parametrize("method", tuple(MethodKind))
def test_private_nested_entrypoint_has_generated_live_trace_parity(method, tmp_path):
    project = _project(method)
    before = project_to_data(project)
    model = project.program_model
    function = model.functions[0]
    assessment = assess_project(project)
    assert assessment.buildable, assessment.diagnostics
    invocation = bind_invocation(model, function, model.entrypoint_arguments)
    receiver = "()" if method is MethodKind.INSTANCE else ""
    assert invocation.callable_source() == f"Outer._Outer__Inner{receiver}._Inner__run"
    assert invocation.callable_source(imported_alias="selected") == (
        f"selected._Outer__Inner{receiver}._Inner__run"
    )
    assert resolve_linked_callable(model, model.modules[0], function) == (
        "Outer._Outer__Inner._Inner__run"
    )
    for keyword in ("__value", "_Outer__Inner__value"):
        with pytest.raises(InvocationBindingError) as caught:
            bind_invocation(model, function, parse_invocation_arguments(f"{keyword}=7"))
        assert caught.value.code == "INVOCATION_ARGUMENT_MISMATCH"

    ir = lower_project(project)
    assert ir.entrypoint.invocation == invocation
    generated = emit_project(ir)
    for file in generated.files:
        path = tmp_path / file.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(file.source, encoding="utf-8")
    trace = trace_project(generated)
    for result in (
        run_generated(tmp_path / "run_project.py"),
        run_project(generated),
        trace.run,
    ):
        assert result.return_code == 0, result.stderr
        assert result.stdout == "7\n"
        assert not result.stderr
    assert any(event.function == "__run" for event in trace.events)
    assert project_to_data(project) == before


@pytest.mark.parametrize(
    "classes,member,expected",
    (
        (("_Outer", "__Inner", "__Leaf"), "__run", "_Outer._Outer__Inner._Inner__Leaf._Leaf__run"),
        (("___", "__Inner"), "__run", "___.__Inner._Inner__run"),
        (("Outer", "__Inner"), "__run__", "Outer._Outer__Inner.__run__"),
        (("Outer", "__\u212a"), "__run", "Outer._Outer__K._K__run"),
    ),
)
def test_external_member_paths_match_python_lexical_mangling(classes, member, expected):
    path = ".".join(python_member_path(member, classes))
    assert path == expected
    lines = [f"{'    ' * index}class {name}:" for index, name in enumerate(classes)]
    indent = "    " * len(classes)
    lines.extend((f"{indent}@staticmethod", f"{indent}def {member}():", f"{indent}    return 7"))
    lines.append(f"result = {path}()")
    scope = {}
    exec(compile("\n".join(lines), "<private-lexical-owners>", "exec"), scope)
    assert scope["result"] == 7


def test_private_keyword_mangling_uses_renamed_lexical_owner_without_mutating_meaning():
    project = _project(MethodKind.STATIC)
    model = project.program_model
    outer = model.modules[0].body[0]
    renamed_inner = replace(outer.body[0], identifier="__Renamed")
    renamed = replace(
        model,
        modules=(replace(model.modules[0], body=(replace(outer, body=(renamed_inner,)),)),),
    )
    invocation = bind_invocation(
        renamed, renamed.functions[0], parse_invocation_arguments("_Renamed__value=7")
    )
    assert invocation.callable_source() == "Outer._Outer__Renamed._Renamed__run"
    assert renamed.functions == model.functions
    assert renamed_inner.id == outer.body[0].id
