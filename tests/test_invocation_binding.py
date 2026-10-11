"""Canonical call admission follows Python binding without executing authored expressions."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.drakon_program_adapter import drakon_from_program
from code_visualizer.application.invocations import invocation_for_document
from code_visualizer.automation.protocol import RpcError
from code_visualizer.automation.service import (
    AccessMode,
    AutomationCapability,
    AutomationContext,
    AutomationService,
)
from code_visualizer.cli import main
from code_visualizer.domain.drakon import create_empty_drakon
from code_visualizer.domain.invocation import InvocationBindingError, bind_invocation
from code_visualizer.domain.invocation_arguments import (
    EMPTY_INVOCATION_ARGUMENTS,
    InvocationArguments,
    InvocationKeyword,
    parse_invocation_arguments,
)
from code_visualizer.domain.program import (
    ExpressionRole,
    ProgramCall,
    ProgramEntryPoint,
    ProgramFunction,
    ProgramModel,
    ProgramOutput,
    ProgramParameter,
    ProgramSequence,
    ProgramSymbol,
    ProgramSymbolKind,
    make_program_expression,
)
from code_visualizer.domain.program_kinds import CallableKind, MethodKind, ParameterKind
from code_visualizer.domain.program_ownership import place_program_function
from code_visualizer.domain.project import Project
from code_visualizer.domain.projection import DrakonViewDefinition
from code_visualizer.execution import (
    DebugLaunch,
    DebugSession,
    DebugState,
    run_generated,
    run_project,
    trace_project,
)
from code_visualizer.generation import (
    BuildBlockedError,
    GenerationError,
    generate_python,
    generate_python_project,
)
from code_visualizer.persistence import ProjectStore
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.ui_qt.document import UnifiedDocumentWidget
from code_visualizer.validation import assess_project


def _expression(owner, source, role=ExpressionRole.VALUE):
    return make_program_expression(owner, "value", source, role)


def _parameter(name, kind=ParameterKind.POSITIONAL_OR_KEYWORD, default=None, *, owner="entry"):
    identity = f"parameter:{owner}:{name}"
    return ProgramParameter(
        identity,
        f"symbol:{identity}",
        name,
        kind,
        default=None if default is None else _expression(identity, default, ExpressionRole.DEFAULT),
    )


def _function(
    parameters=(),
    *,
    identifier="entry",
    method=None,
    module="main",
    output="'entered'",
    kind=CallableKind.SYNC,
):
    identity = f"function:{module}:{identifier}"
    return ProgramFunction(
        identity,
        f"symbol:{identity}",
        identifier,
        identifier,
        kind,
        tuple(parameters),
        None,
        (),
        None,
        method,
        ProgramSequence(
            f"sequence:{identity}",
            (ProgramOutput(f"output:{identity}", _expression(f"output:{identity}", output)),),
        ),
    )


def _program(*functions, class_name="Worker"):
    symbols = []
    for function in functions:
        symbols.append(
            ProgramSymbol(
                function.symbol_id,
                function.identifier,
                ProgramSymbolKind.FUNCTION,
                function.id,
                function.id,
            )
        )
        symbols.extend(
            ProgramSymbol(
                parameter.symbol_id,
                parameter.name,
                ProgramSymbolKind.PARAMETER,
                function.id,
                parameter.id,
            )
            for parameter in function.parameters
        )
    program = ProgramModel(tuple(functions), tuple(symbols))
    for function in functions:
        program = place_program_function(
            program,
            function.id,
            function.id.split(":")[1],
            class_name if function.method_kind else None,
            identity_namespace="binding-fixture",
        )
    if functions:
        program = replace(
            program, entrypoint=ProgramEntryPoint("entrypoint:binding", functions[0].id)
        )
    return program


def _project(*, arguments="7", method=None, parameters=None, output="f'entered:{x}'"):
    if parameters is None:
        receiver = (
            (_parameter("self" if method is MethodKind.INSTANCE else "cls"),)
            if method in {MethodKind.INSTANCE, MethodKind.CLASS}
            else ()
        )
        parameters = (*receiver, _parameter("x"))
    function = _function(parameters, method=method, output=output)
    program = _program(function)
    document = create_empty_drakon(identifier="entry", diagram_id="view:entry")
    view = DrakonViewDefinition(
        document.id, function.id, "Entry", document.header.id, document.end.id
    )
    document = drakon_from_program(function, view, document, model=program)
    return Project(
        "project:binding",
        "Invocation binding",
        (document,),
        program_model=replace(
            program,
            entrypoint=ProgramEntryPoint(
                "entrypoint:binding",
                function.id,
                parse_invocation_arguments(arguments),
            ),
        ),
        drakon_views=(view,),
    )


PO = ParameterKind.POSITIONAL_ONLY
PK = ParameterKind.POSITIONAL_OR_KEYWORD
KO = ParameterKind.KEYWORD_ONLY
VP = ParameterKind.VAR_POSITIONAL
VK = ParameterKind.VAR_KEYWORD

BINDING_CASES = (
    pytest.param((), "", True, id="empty"),
    pytest.param((), "1", False, id="excess-positional"),
    pytest.param((_parameter("x"),), "", False, id="missing-required"),
    pytest.param((_parameter("x"),), "1", True, id="positional"),
    pytest.param((_parameter("x"),), "x=1", True, id="keyword"),
    pytest.param((_parameter("x"),), "1, 2", False, id="excess-positional-with-param"),
    pytest.param((_parameter("x"),), "1, unknown=2", False, id="unknown-keyword"),
    pytest.param((_parameter("x"),), "1, x=2", False, id="duplicate-positional-and-keyword"),
    pytest.param((_parameter("x", PO),), "1", True, id="positional-only"),
    pytest.param((_parameter("x", PO),), "x=1", False, id="positional-only-as-keyword"),
    pytest.param((_parameter("x", KO),), "x=1", True, id="keyword-only"),
    pytest.param((_parameter("x", KO),), "1", False, id="keyword-only-as-positional"),
    pytest.param((_parameter("x", KO),), "", False, id="missing-keyword-only"),
    pytest.param((_parameter("x", PK, "None"),), "", True, id="none-default-is-present"),
    pytest.param((_parameter("x", KO, "False"),), "", True, id="keyword-only-default"),
    pytest.param((_parameter("x", PO, "0"),), "", True, id="positional-only-default"),
    pytest.param((_parameter("args", VP),), "1, 2, 3", True, id="var-positional"),
    pytest.param(
        (_parameter("args", VP),), "args=1", False, id="var-positional-name-is-not-keyword"
    ),
    pytest.param((_parameter("kwargs", VK),), "x=1, y=2", True, id="var-keyword"),
    pytest.param(
        (_parameter("kwargs", VK),), "1", False, id="var-keyword-does-not-take-positional"
    ),
    pytest.param(
        (_parameter("x", PO), _parameter("kwargs", VK)),
        "1, x=2",
        True,
        id="posonly-name-can-be-extra-keyword",
    ),
    pytest.param(
        (_parameter("x", PO), _parameter("kwargs", VK)),
        "x=2",
        False,
        id="extra-keyword-cannot-satisfy-posonly",
    ),
    pytest.param(
        (_parameter("x"), _parameter("kwargs", VK)),
        "1, x=2",
        False,
        id="varkw-does-not-mask-duplicate",
    ),
    pytest.param(
        (
            _parameter("x", PO),
            _parameter("y", PK, "2"),
            _parameter("args", VP),
            _parameter("flag", KO),
            _parameter("kwargs", VK),
        ),
        "1, 3, 4, 5, flag=True, extra='ok'",
        True,
        id="complete-mixed-signature",
    ),
    pytest.param(
        (
            _parameter("x", PO),
            _parameter("args", VP),
            _parameter("flag", KO),
            _parameter("kwargs", VK),
        ),
        "1, 2, extra='ok'",
        False,
        id="varargs-and-varkw-do-not-fill-required-kwonly",
    ),
)


@pytest.mark.parametrize(("parameters", "text", "accepted"), BINDING_CASES)
def test_canonical_argument_binding_matrix(parameters, text, accepted):
    function = _function(parameters)
    program = _program(function)
    arguments = parse_invocation_arguments(text)
    if not accepted:
        with pytest.raises(InvocationBindingError) as caught:
            bind_invocation(program, function, arguments)
        assert caught.value.code == "INVOCATION_ARGUMENT_MISMATCH"
    else:
        result = bind_invocation(program, function, arguments)
        assert result.callable_id == function.id
        assert result.arguments is arguments
        assert result.identifier == "entry"
    assert program.function(function.id) == function


@pytest.mark.parametrize("kind", tuple(CallableKind))
def test_callable_execution_kind_does_not_change_argument_binding(kind):
    function = _function((_parameter("x"),), kind=kind)
    program = _program(function)
    assert bind_invocation(program, function, parse_invocation_arguments("4")).kind is kind
    with pytest.raises(InvocationBindingError, match="x"):
        bind_invocation(program, function)


@pytest.mark.parametrize("method", (MethodKind.INSTANCE, MethodKind.CLASS))
@pytest.mark.parametrize(
    ("receiver_kind", "extra_kwargs", "text", "accepted"),
    (
        (PK, False, "9", True),
        (PO, True, "9, RECEIVER=3", True),
        (PK, True, "9, RECEIVER=3", False),
        (VP, False, "", True),
        (VP, False, "1, 2", True),
        (VK, False, "", False),
        (KO, False, "", False),
    ),
)
def test_bound_receiver_uses_full_signature_not_parameter_slicing(
    method, receiver_kind, extra_kwargs, text, accepted
):
    receiver = "self" if method is MethodKind.INSTANCE else "cls"
    parameters = [_parameter(receiver, receiver_kind)]
    if receiver_kind in {PK, PO}:
        parameters.append(_parameter("x"))
    if extra_kwargs:
        parameters.append(_parameter("kwargs", VK))
    function = _function(parameters, method=method)
    arguments = parse_invocation_arguments(text.replace("RECEIVER", receiver))
    if accepted:
        invocation = bind_invocation(_program(function), function, arguments)
        assert invocation.method_kind is method
        assert invocation.arguments == arguments
    else:
        with pytest.raises(InvocationBindingError) as caught:
            bind_invocation(_program(function), function, arguments)
        assert caught.value.code == "INVOCATION_ARGUMENT_MISMATCH"


@pytest.mark.parametrize("method", (MethodKind.INSTANCE, MethodKind.CLASS))
def test_bound_method_without_any_parameter_has_no_room_for_receiver(method):
    function = _function(method=method)
    with pytest.raises(InvocationBindingError) as caught:
        bind_invocation(_program(function), function)
    assert caught.value.code == "INVOCATION_ARGUMENT_MISMATCH"


def test_static_method_parameters_named_self_are_ordinary_explicit_arguments():
    function = _function((_parameter("self"),), method=MethodKind.STATIC)
    program = _program(function)
    with pytest.raises(InvocationBindingError):
        bind_invocation(program, function)
    result = bind_invocation(program, function, parse_invocation_arguments("self=3"))
    assert result.callable_source() == "Worker.entry"


@pytest.mark.parametrize("method", tuple(MethodKind))
@pytest.mark.parametrize(
    ("owner", "parameter_name", "external_name"),
    (
        ("Worker", "__x", "_Worker__x"),
        ("_Worker", "__x", "_Worker__x"),
        ("__Worker", "__x", "_Worker__x"),
        ("___", "__x", "__x"),
        ("Worker", "__dunder__", "__dunder__"),
        ("_\u212a", "__x", "_K__x"),
    ),
)
def test_private_parameters_bind_using_python_class_scope_names(
    method, owner, parameter_name, external_name
):
    receiver = () if method is MethodKind.STATIC else (_parameter("receiver"),)
    function = _function((*receiver, _parameter(parameter_name)), method=method)
    program = _program(function, class_name=owner)
    for text in ("7", f"{external_name}=7"):
        arguments = parse_invocation_arguments(text)
        assert bind_invocation(program, function, arguments).arguments == arguments
    if parameter_name != external_name:
        with pytest.raises(InvocationBindingError) as caught:
            bind_invocation(program, function, parse_invocation_arguments(f"{parameter_name}=7"))
        assert caught.value.code == "INVOCATION_ARGUMENT_MISMATCH"
    assert function.parameters[-1].name == parameter_name


@pytest.mark.parametrize("method", tuple(MethodKind))
@pytest.mark.parametrize(
    ("kind", "default", "arguments", "accepted"),
    (
        (PK, None, "__x=7", False),
        (PK, None, "_Worker__x=7", True),
        (PK, "None", "__x=7", True),
        (PK, None, "7, __x=8", True),
        (PK, None, "7, _Worker__x=8", False),
        (PO, None, "7, _Worker__x=8", True),
    ),
)
def test_private_parameter_binding_preserves_external_kwargs_semantics(
    method, kind, default, arguments, accepted
):
    receiver = () if method is MethodKind.STATIC else (_parameter("receiver", PO),)
    function = _function(
        (*receiver, _parameter("__x", kind, default), _parameter("kwargs", VK)), method=method
    )
    program = _program(function)
    values = parse_invocation_arguments(arguments)
    if accepted:
        assert bind_invocation(program, function, values).arguments == values
    else:
        with pytest.raises(InvocationBindingError) as caught:
            bind_invocation(program, function, values)
        assert caught.value.code == "INVOCATION_ARGUMENT_MISMATCH"


@pytest.mark.parametrize("method", (MethodKind.INSTANCE, MethodKind.CLASS))
def test_private_receiver_retains_descriptor_binding_and_keyword_collision_rules(method):
    function = _function((_parameter("__receiver"), _parameter("kwargs", VK)), method=method)
    program = _program(function)
    arguments = parse_invocation_arguments("__receiver=7")
    assert bind_invocation(program, function, arguments).arguments == arguments
    with pytest.raises(InvocationBindingError) as caught:
        bind_invocation(program, function, parse_invocation_arguments("_Worker__receiver=7"))
    assert caught.value.code == "INVOCATION_ARGUMENT_MISMATCH"


def test_private_parameter_collision_after_mangling_is_an_explicit_binding_error():
    function = _function(
        (_parameter("self"), _parameter("__x"), _parameter("_Worker__x")),
        method=MethodKind.INSTANCE,
    )
    with pytest.raises(InvocationBindingError) as caught:
        bind_invocation(_program(function), function, parse_invocation_arguments("1, 2"))
    assert caught.value.code == "INVOCATION_ARGUMENT_MISMATCH"


@pytest.mark.parametrize("method", tuple(MethodKind))
def test_private_parameter_validated_invocation_executes_existing_generated_python(method):
    receiver = (
        ()
        if method is MethodKind.STATIC
        else (_parameter("self" if method is MethodKind.INSTANCE else "cls"),)
    )
    project = _project(
        method=method,
        arguments="_Worker__x=7",
        parameters=(*receiver, _parameter("__x")),
        output="__x",
    )
    assert assess_project(project).buildable
    result = run_project(generate_python_project(project))
    assert result.return_code == 0, result.stderr
    assert result.stdout == "7\n"
    invalid = replace(
        project,
        program_model=replace(
            project.program_model,
            entrypoint=replace(
                project.program_model.entrypoint, arguments=parse_invocation_arguments("__x=7")
            ),
        ),
    )
    with pytest.raises(BuildBlockedError, match="INVOCATION_ARGUMENT_MISMATCH"):
        generate_python(invalid)


@pytest.mark.parametrize(
    ("name", "method", "parameters", "accepted"),
    (
        ("__init__", MethodKind.INSTANCE, (_parameter("self", owner="ctor"),), True),
        (
            "__init__",
            MethodKind.INSTANCE,
            (_parameter("self", owner="ctor"), _parameter("needed", KO, owner="ctor")),
            False,
        ),
        ("__init__", MethodKind.INSTANCE, (_parameter("self", VP, owner="ctor"),), True),
        ("__init__", MethodKind.INSTANCE, (_parameter("self", VK, owner="ctor"),), False),
        ("__new__", MethodKind.STATIC, (_parameter("cls", owner="ctor"),), True),
        (
            "__new__",
            MethodKind.STATIC,
            (_parameter("cls", owner="ctor"), _parameter("needed", owner="ctor")),
            False,
        ),
        ("__new__", MethodKind.STATIC, (_parameter("cls", VP, owner="ctor"),), True),
        ("__new__", MethodKind.STATIC, (_parameter("cls", VK, owner="ctor"),), False),
        ("__new__", MethodKind.STATIC, (_parameter("cls", KO, owner="ctor"),), False),
        ("__new__", MethodKind.STATIC, (), False),
    ),
)
def test_constructor_binding_accounts_for_new_and_variadic_implicit_receiver(
    name, method, parameters, accepted
):
    constructor = _function(parameters, identifier=name, method=method)
    function = _function((_parameter("self"),), method=MethodKind.INSTANCE)
    program = _program(constructor, function)
    if accepted:
        assert bind_invocation(program, function).callable_source() == "Worker().entry"
    else:
        with pytest.raises(InvocationBindingError) as caught:
            bind_invocation(program, function)
        assert caught.value.code == "INVOCATION_RECEIVER_REQUIRES_SETUP"


@pytest.mark.parametrize("name", ("__\uff4e\uff45\uff57__", "__\uff49\uff4e\uff49\uff54__"))
def test_constructor_eligibility_uses_python_normalized_special_method_names(name):
    constructor = _function(
        (_parameter("receiver", owner="ctor"), _parameter("needed", owner="ctor")),
        identifier=name,
        method=MethodKind.INSTANCE,
    )
    function = _function((_parameter("self"),), method=MethodKind.INSTANCE)
    with pytest.raises(InvocationBindingError) as caught:
        bind_invocation(_program(constructor, function), function)
    assert caught.value.code == "INVOCATION_RECEIVER_REQUIRES_SETUP"


def test_normalized_new_name_retains_python_automatic_static_descriptor_binding():
    function = _function(
        (_parameter("cls"),),
        identifier="__\uff4e\uff45\uff57__",
        method=MethodKind.INSTANCE,
    )
    program = _program(function)
    arguments = parse_invocation_arguments("7")
    assert bind_invocation(program, function, arguments).arguments == arguments
    with pytest.raises(InvocationBindingError) as caught:
        bind_invocation(program, function)
    assert caught.value.code == "INVOCATION_ARGUMENT_MISMATCH"


@pytest.mark.parametrize("method", (MethodKind.STATIC, MethodKind.CLASS))
def test_non_instance_invocation_does_not_bind_constructor(method):
    constructor = _function(
        (_parameter("self", owner="ctor"), _parameter("needed", owner="ctor")),
        identifier="__init__",
        method=MethodKind.INSTANCE,
    )
    function = _function((_parameter("cls"),) if method is MethodKind.CLASS else (), method=method)
    assert bind_invocation(_program(constructor, function), function).method_kind is method


def test_same_class_name_in_another_module_does_not_change_receiver_admission():
    constructor = _function(
        (_parameter("self", owner="ctor"), _parameter("needed", owner="ctor")),
        identifier="__init__",
        method=MethodKind.INSTANCE,
        module="other",
    )
    function = _function((_parameter("self"),), method=MethodKind.INSTANCE)
    assert bind_invocation(_program(constructor, function), function).callable_id == function.id


def test_binding_never_evaluates_default_or_annotation_expressions(capsys):
    parameter = _parameter("x", default="print('MUST NOT EXECUTE')")
    parameter = replace(
        parameter,
        annotation=_expression("annotation:x", "UnavailableType", ExpressionRole.ANNOTATION),
    )
    function = _function((parameter,))
    assert bind_invocation(_program(function), function).arguments == EMPTY_INVOCATION_ARGUMENTS
    assert capsys.readouterr().out == ""


def test_binding_rejects_foreign_or_stale_callable_values():
    function = _function((_parameter("x"),))
    program = _program(function)
    for wrong in (replace(function, id="foreign"), replace(function, parameters=())):
        with pytest.raises(InvocationBindingError) as caught:
            bind_invocation(program, wrong, parse_invocation_arguments("1"))
        assert caught.value.code == "INVOCATION_CALLABLE_MISMATCH"


@pytest.mark.parametrize("field", ("identifier", "owning_class"))
def test_incomplete_callable_metadata_produces_diagnostics_and_blocks_selection(field):
    project = _project(method=MethodKind.INSTANCE if field == "owning_class" else None)
    function = project.program_model.functions[0]
    if field == "identifier":
        function = replace(function, identifier="bad-name")
    program = _program(function, class_name="bad-name" if field == "owning_class" else "Worker")
    program = replace(program, entrypoint=project.program_model.entrypoint)
    project = replace(project, program_model=program)
    with pytest.raises(InvocationBindingError) as caught:
        bind_invocation(project.program_model, function, parse_invocation_arguments("7"))
    assert caught.value.code == "INVOCATION_CALLABLE_INVALID"
    assessment = assess_project(project)
    assert not assessment.buildable
    assert any(item.code == "INVOCATION_CALLABLE_INVALID" for item in assessment.diagnostics)
    if field == "identifier":
        assert any(item.code == "PY_INVALID_IDENTIFIER" for item in assessment.diagnostics)
    with pytest.raises(GenerationError, match="INVOCATION_CALLABLE_INVALID"):
        invocation_for_document(project, "view:entry", "7")
    with pytest.raises(BuildBlockedError, match="INVOCATION_CALLABLE_INVALID"):
        generate_python(project)


@pytest.mark.parametrize("name", ("bad-name", "class", ""))
def test_binding_aliases_do_not_accept_invalid_raw_parameter_names(name):
    function = _function((_parameter(name),))
    with pytest.raises(InvocationBindingError) as caught:
        bind_invocation(_program(function), function, parse_invocation_arguments("7"))
    assert caught.value.code == "INVOCATION_ARGUMENT_MISMATCH"


def test_generation_override_rebinds_identity_arguments_and_metadata_before_emission():
    project = _project()
    invocation = invocation_for_document(project, "view:entry", "7")
    forged = (
        replace(invocation, callable_id=None),
        replace(invocation, callable_id="foreign"),
        replace(invocation, identifier="different"),
        replace(invocation, kind=CallableKind.ASYNC),
        replace(invocation, owning_class="Worker", method_kind=MethodKind.STATIC),
        replace(invocation, arguments=EMPTY_INVOCATION_ARGUMENTS),
    )
    for override in forged:
        with pytest.raises(GenerationError, match="INVOCATION_"):
            generate_python(project, invocation=override)
    other = _function(identifier="other")
    expanded = replace(project, program_model=_program(*project.program_model.functions, other))
    with pytest.raises(GenerationError, match="INVOCATION_SCOPE"):
        generate_python(expanded, focus_diagram_id=other.id, invocation=invocation)
    assert project.program_model.entrypoint_arguments == parse_invocation_arguments("7")


def test_duplicate_keyword_slots_are_rejected_before_binding():
    with pytest.raises(ValueError, match="distinct"):
        InvocationArguments(keywords=(InvocationKeyword("x", 1), InvocationKeyword("x", 2)))


@pytest.mark.parametrize(("parameter_name", "keyword_name"), (("\u212a", "K"), ("\uff4e", "n")))
def test_binding_uses_python_nfkc_identifier_rules_without_changing_canonical_text(
    parameter_name, keyword_name
):
    function = _function((_parameter(parameter_name),))
    arguments = InvocationArguments(keywords=(InvocationKeyword(keyword_name, 4),))
    result = bind_invocation(_program(function), function, arguments)
    assert result.arguments == arguments
    assert function.parameters[0].name == parameter_name


def test_nfkc_keyword_parameter_accepts_positional_call_as_python_does():
    parameter_name = "\uff43\uff4c\uff41\uff53\uff53"
    project = _project(arguments="7", parameters=(_parameter(parameter_name),), output="'entered'")
    function = project.program_model.functions[0]
    arguments = parse_invocation_arguments("7")
    assert bind_invocation(project.program_model, function, arguments).arguments == arguments
    assert assess_project(project).buildable
    result = run_project(generate_python_project(project))
    assert result.return_code == 0, result.stderr
    assert result.stdout == "entered\n"
    assert function.parameters[0].name == parameter_name


def test_normalized_keyword_and_parameter_collisions_are_explicit_errors():
    function = _function((_parameter("kwargs", VK),))
    arguments = InvocationArguments(
        keywords=(InvocationKeyword("K", 1), InvocationKeyword("\u212a", 2))
    )
    with pytest.raises(InvocationBindingError) as caught:
        bind_invocation(_program(function), function, arguments)
    assert caught.value.code == "INVOCATION_ARGUMENT_MISMATCH"
    assert len(arguments.keywords) == 2
    duplicate_parameters = _function((_parameter("K"), _parameter("\u212a")))
    with pytest.raises(InvocationBindingError) as caught:
        bind_invocation(
            _program(duplicate_parameters), duplicate_parameters, parse_invocation_arguments("1, 2")
        )
    assert caught.value.code == "INVOCATION_ARGUMENT_MISMATCH"


@pytest.mark.parametrize("text", ("", "1, 2", "other=1", "1, x=2"))
def test_configured_entrypoint_mismatch_is_a_build_diagnostic(text):
    project = _project(arguments=text)
    assessment = assess_project(project)
    assert not assessment.buildable
    diagnostics = [
        item for item in assessment.diagnostics if item.code == "INVOCATION_ARGUMENT_MISMATCH"
    ]
    assert diagnostics
    assert diagnostics[0].object_id == project.program_model.entrypoint_callable_id
    for generate in (generate_python, generate_python_project):
        with pytest.raises(BuildBlockedError, match="INVOCATION_ARGUMENT_MISMATCH"):
            generate(project)


def test_editor_run_trace_debug_reject_missing_argument_before_starting_execution_worker(
    qtbot, monkeypatch
):
    project = _project()
    authority = ProjectAuthority(project)
    client = CodeVisualizerClient(authority, actor_id="binding-test")
    widget = UnifiedDocumentWidget(client, "view:entry")
    qtbot.addWidget(widget)

    def must_not_start(*_args, **_kwargs):
        pytest.fail("Invalid call reached a child process or debugger")

    monkeypatch.setattr(widget._run_session, "start_project", must_not_start)
    monkeypatch.setattr(widget._debugger, "start", must_not_start)
    monkeypatch.setattr(widget._run_session, "start_project_trace", must_not_start)
    try:
        widget.arguments.setText("")
        for action in (widget.run_current, widget.trace_current, widget.debug_current):
            action()
            qtbot.waitUntil(lambda: not widget._preparation.pending, timeout=10000)
            assert "INVOCATION_ARGUMENT_MISMATCH" in widget.console.toPlainText()
        assert authority.snapshot() == project
    finally:
        widget.stop_current()
        client.close()


def test_cli_trace_rejects_invalid_call_before_starting_worker(tmp_path, capsys, monkeypatch):
    project = _project()
    root = tmp_path / "binding-cli"
    ProjectStore(root).initialize(project)

    def must_not_trace(*_args, **_kwargs):
        pytest.fail("CLI admitted a mismatched invocation")

    monkeypatch.setattr("code_visualizer.cli.trace_project", must_not_trace)
    assert main(["trace", str(root), "view:entry"]) == 2
    result = capsys.readouterr()
    assert "INVOCATION_ARGUMENT_MISMATCH" in result.err


def test_automation_run_and_trace_reject_invalid_calls_before_registering_jobs(monkeypatch):
    project = _project()
    authority = ProjectAuthority(project)
    service = AutomationService(authority)
    context = AutomationContext(
        "runner",
        "binding-test",
        AccessMode.COMMIT,
        frozenset({AutomationCapability.READ, AutomationCapability.EXECUTE}),
    )

    def must_not_register(*_args, **_kwargs):
        pytest.fail("Mismatched invocation created an execution job")

    monkeypatch.setattr(service, "_register_execution", must_not_register)
    try:
        for method in ("test.run_diagram", "test.trace_diagram"):
            with pytest.raises(RpcError, match="INVOCATION_ARGUMENT_MISMATCH"):
                service.dispatch(
                    method, {"diagram_id": "view:entry", "arguments": "1, x=2"}, context
                )
        assert authority.snapshot() == project
    finally:
        service.close()


def test_complete_mixed_signature_executes_generated_live_trace_and_debug(tmp_path):
    parameters = (
        _parameter("x", PO),
        _parameter("y", PK, "2"),
        _parameter("args", VP),
        _parameter("flag", KO),
        _parameter("kwargs", VK),
    )
    project = _project(
        parameters=parameters,
        arguments="1, 3, 4, 5, flag=True, extra='ok'",
        output="(x, y, args, flag, kwargs['extra'])",
    )
    function = project.program_model.functions[0]
    invocation = bind_invocation(
        project.program_model, function, project.program_model.entrypoint_arguments
    )
    generated = generate_python_project(project)
    for file in generated.files:
        path = tmp_path / file.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(file.source, encoding="utf-8")
    live = generate_python_project(project)
    assert live.invocation == invocation
    expected = "(1, 3, (4, 5), True, 'ok')\n"
    assert run_generated(tmp_path / "run_project.py").stdout == expected
    assert run_project(live).stdout == expected
    traced = trace_project(live)
    assert traced.run.stdout == expected
    assert traced.run.return_code == 0
    with DebugSession() as debugger:
        debugger.start(DebugLaunch(project=live))
        output = []
        for _ in range(100):
            event = debugger.wait_event(timeout=10)
            if event.event == "output" and event.channel == "stdout":
                output.append(event.text)
            if event.event == "paused":
                debugger.continue_execution()
            if event.event in {"finished", "failed", "stopped"}:
                assert event.event == "finished", event
                break
        else:
            pytest.fail("Debugger did not finish a valid invocation")
    assert "".join(output) == expected


def test_selected_valid_call_runs_even_when_configured_project_arguments_are_invalid(
    qtbot, tmp_path, capsys
):
    project = _project(arguments="")
    assert not assess_project(project).buildable
    invocation = invocation_for_document(project, "view:entry", "9")
    assert invocation.arguments == parse_invocation_arguments("9")
    authority = ProjectAuthority(project)
    client = CodeVisualizerClient(authority, actor_id="selected-call")
    widget = UnifiedDocumentWidget(client, "view:entry")
    qtbot.addWidget(widget)
    try:
        widget.arguments.setText("9")
        widget.run_current()
        qtbot.waitUntil(lambda: widget.run_button.isEnabled(), timeout=10000)
        assert widget.console.toPlainText() == "entered:9\n"
        widget.trace_current()
        qtbot.waitUntil(lambda: widget.trace_button.isEnabled(), timeout=10000)
        assert "entered:9" in widget.console.toPlainText()
        assert "exit 0" in widget.console.toPlainText()
        widget.pause_exceptions.setChecked(False)
        widget.debug_current()
        qtbot.waitUntil(lambda: widget.continue_button.isEnabled(), timeout=10000)
        widget.debug_continue()
        qtbot.waitUntil(
            lambda: widget._debugger.state in {DebugState.FINISHED, DebugState.FAILED},
            timeout=10000,
        )
        widget._poll_debugger()
        assert widget._debugger.state is DebugState.FINISHED, widget.console.toPlainText()
        assert "entered:9" in widget.console.toPlainText()
        root = tmp_path / "selected-call"
        ProjectStore(root).initialize(project)
        assert main(["trace", str(root), "view:entry", "--arguments", "9"]) == 0
        assert json.loads(capsys.readouterr().out)["stdout"] == "entered:9\n"
        assert authority.snapshot() == project
    finally:
        widget.stop_current()
        client.close()


def test_automation_selected_call_overrides_invalid_configured_arguments_without_editing(qtbot):
    project = _project(arguments="")
    authority = ProjectAuthority(project)
    service = AutomationService(authority)
    context = AutomationContext(
        "runner",
        "selected-call",
        AccessMode.COMMIT,
        frozenset({AutomationCapability.READ, AutomationCapability.EXECUTE}),
    )
    try:
        for method in ("test.run_diagram", "test.trace_diagram"):
            launched = service.dispatch(
                method, {"diagram_id": "view:entry", "arguments": "9"}, context
            )
            params = {"job_id": launched["job_id"]}
            qtbot.waitUntil(
                lambda params=params: (
                    service.dispatch("test.status", params, context)["status"] != "running"
                ),
                timeout=10000,
            )
            result = service.dispatch("test.status", params, context)["result"]
            assert result["return_code"] == 0, result
            assert result["stdout"] == "entered:9\n"
            if method == "test.trace_diagram":
                assert result["events"]
        assert authority.snapshot() == project
        assert not assess_project(authority.snapshot()).buildable
    finally:
        service.close()


@pytest.mark.parametrize("calls_configured_entrypoint", (False, True))
def test_selected_other_function_is_not_blocked_by_unrelated_or_dependency_entrypoint_arguments(
    calls_configured_entrypoint,
):
    project = _project(arguments="")
    configured = project.program_model.functions[0]
    selected = _function(identifier="selected", output="'selected'")
    if calls_configured_entrypoint:
        call = ProgramCall(
            "call:configured",
            _expression("call:configured", "entry(3)", ExpressionRole.CALL),
            _expression("args:configured", "3", ExpressionRole.ARGUMENTS),
            target_function_id=configured.id,
        )
        selected = replace(
            selected, body=replace(selected.body, statements=(*selected.body.statements, call))
        )
    document = create_empty_drakon(identifier="selected", diagram_id="view:selected")
    view = DrakonViewDefinition(
        document.id, selected.id, "Selected", document.header.id, document.end.id
    )
    document = drakon_from_program(selected, view, document, model=_program(configured, selected))
    project = replace(
        project,
        program_model=_program(configured, selected),
        documents=(*project.documents, document),
        drakon_views=(*project.drakon_views, view),
    )
    assert not assess_project(project).buildable
    invocation = invocation_for_document(project, "view:selected")
    generated = generate_python_project(
        project, focus_diagram_id="view:selected", invocation=invocation
    )
    result = run_project(generated)
    assert result.return_code == 0, result.stderr
    assert result.stdout == "selected\n" + ("entered:3\n" if calls_configured_entrypoint else "")
    assert project.program_model.entrypoint_arguments == EMPTY_INVOCATION_ARGUMENTS
    assert project.program_model.entrypoint_callable_id == configured.id
