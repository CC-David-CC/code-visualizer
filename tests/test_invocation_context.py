"""Execution context is a validated receiver plus immutable literal argument values."""

import json
from dataclasses import replace

import pytest
from python_persistence_fixtures import legacy_project_data

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.drakon_program_adapter import drakon_from_program
from code_visualizer.application.invocations import invocation_for_document
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.domain.drakon import create_empty_drakon
from code_visualizer.domain.invocation import bind_invocation
from code_visualizer.domain.invocation_arguments import (
    EMPTY_INVOCATION_ARGUMENTS,
    UnresolvedInvocationArguments,
    configured_arguments_from_text,
    parse_invocation_arguments,
    render_invocation_arguments,
)
from code_visualizer.domain.program import (
    ExpressionRole,
    ProgramAssignment,
    ProgramCall,
    ProgramEntryPoint,
    ProgramFunction,
    ProgramModel,
    ProgramModule,
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
from code_visualizer.domain.python_declarations import parse_python_declarations
from code_visualizer.execution import (
    DebugLaunch,
    DebugSession,
    run_generated,
    run_project,
    trace_project,
)
from code_visualizer.generation import (
    BuildBlockedError,
    GenerationError,
    generate_python_project,
)
from code_visualizer.persistence.decoding import (
    ProjectDecodeError,
    project_from_data,
    project_from_json,
)
from code_visualizer.persistence.serialization import normalized_project_json
from code_visualizer.persistence.store import JournalRecord, ProjectStore
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.validation import assess_project


def _expression(owner, source, role=ExpressionRole.VALUE):
    return make_program_expression(owner, "value", source, role)


def _parameter(name, owner, *, kind=ParameterKind.POSITIONAL_OR_KEYWORD, default=None):
    identity = f"{owner}:{name}"
    return ProgramParameter(identity, f"symbol:{identity}", name, kind, default=default)


def _function(name, parameters, statements, method=None):
    return ProgramFunction(
        name,
        f"symbol:{name}",
        name,
        name,
        CallableKind.SYNC,
        parameters,
        None,
        (),
        None,
        method,
        ProgramSequence(f"sequence:{name}", statements),
    )


def _project(functions, entrypoint, arguments=EMPTY_INVOCATION_ARGUMENTS):
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
                item.symbol_id, item.name, ProgramSymbolKind.PARAMETER, function.id, item.id
            )
            for item in function.parameters
        )
    program = ProgramModel(
        functions,
        tuple(symbols),
        (
            ProgramModule(
                "module:main",
                "main",
                parse_python_declarations("module:main", "VALUE = 7", identity_namespace="context"),
            ),
        ),
        entrypoint=ProgramEntryPoint("entrypoint:context", entrypoint, arguments),
    )
    for function in functions:
        program = place_program_function(
            program, function.id, "main", "Worker" if function.method_kind else None
        )
    return Project("context:project", "Invocation context", (), program_model=program)


def _worker(*, required=True, kind=ParameterKind.POSITIONAL_OR_KEYWORD, method=MethodKind.INSTANCE):
    constructor = _function(
        "__init__",
        (
            _parameter("self", "__init__"),
            _parameter(
                "x",
                "__init__",
                kind=kind,
                default=None if required else _expression("default:x", "7", ExpressionRole.DEFAULT),
            ),
        ),
        (
            ProgramAssignment(
                "set:x",
                _expression("target:x", "self.x", ExpressionRole.TARGET),
                _expression("value:x", "x"),
            ),
        ),
        MethodKind.INSTANCE,
    )
    parameters = (
        (_parameter("self" if method is MethodKind.INSTANCE else "cls", "run"),)
        if method is not MethodKind.STATIC
        else ()
    )
    run = _function(
        "run",
        parameters,
        (
            ProgramOutput(
                "output",
                _expression("output", "self.x" if method is MethodKind.INSTANCE else "'ok'"),
            ),
        ),
        method,
    )
    return _project((constructor, run), "run")


@pytest.mark.parametrize(
    "kind",
    [
        ParameterKind.POSITIONAL_ONLY,
        ParameterKind.POSITIONAL_OR_KEYWORD,
        ParameterKind.KEYWORD_ONLY,
    ],
)
def test_required_constructor_arguments_block_selected_instance_entrypoint(kind):
    project = _worker(kind=kind)
    assessment = assess_project(project)
    assert not assessment.buildable
    assert "INVOCATION_RECEIVER_REQUIRES_SETUP" in {item.code for item in assessment.diagnostics}
    with pytest.raises(BuildBlockedError, match="zero-argument"):
        generate_python_project(project)
    document = create_empty_drakon(identifier="run", diagram_id="view:run")
    view = DrakonViewDefinition(document.id, "run", "Run", document.header.id, document.end.id)
    document = drakon_from_program(
        project.program_model.function("run"), view, document, model=project.program_model
    )
    project = replace(project, documents=(document,), drakon_views=(view,))
    with pytest.raises(GenerationError, match="INVOCATION_RECEIVER"):
        invocation_for_document(project, "view:run")


@pytest.mark.parametrize("method", [MethodKind.STATIC, MethodKind.CLASS])
def test_static_and_class_methods_do_not_construct_required_receiver(method):
    project = _worker(method=method)
    assert assess_project(project).buildable
    generated = generate_python_project(project)
    result = run_project(generated)
    assert result.return_code == 0, result.stderr
    assert result.stdout == "ok\n"


def _assert_all_surfaces(project, tmp_path, expected, *, focus=None):
    generated = generate_python_project(project)
    for item in generated.files:
        path = tmp_path / item.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(item.source, encoding="utf-8")
    live = generate_python_project(project, focus_diagram_id=focus)
    invocation = bind_invocation(
        project.program_model,
        project.program_model.function(project.program_model.entrypoint_callable_id),
        project.program_model.entrypoint_arguments,
    )
    assert live.invocation == invocation
    results = [
        run_generated(tmp_path / "run_project.py"),
        run_project(live),
        trace_project(live).run,
    ]
    for result in results:
        assert result.return_code == 0, result.stderr
        assert result.stdout == expected
    with DebugSession() as session:
        session.start(DebugLaunch(project=live))
        output = []
        while True:
            event = session.wait_event(timeout=10)
            if event.event == "output" and event.channel == "stdout":
                output.append(event.text)
            if event.event == "paused":
                session.continue_execution()
            if event.event in {"finished", "failed", "stopped"}:
                assert event.event == "finished", event
                break
        assert "".join(output) == expected


def test_zero_argument_receiver_setup_is_present_in_focused_live_closure(tmp_path):
    project = _worker(required=False)
    assert assess_project(project).buildable
    _assert_all_surfaces(project, tmp_path, "7\n", focus="run")


def test_top_level_setup_entrypoint_constructs_a_stateful_receiver_in_all_surfaces(tmp_path):
    project = _worker(required=True)
    main = _function(
        "main",
        (),
        (
            ProgramCall(
                "setup:call",
                _expression("setup:call", "Worker(7).run()", ExpressionRole.CALL),
                _expression("setup:arguments", "", ExpressionRole.ARGUMENTS),
            ),
        ),
    )
    project = _project((*project.program_model.functions, main), "main")
    assert assess_project(project).buildable
    _assert_all_surfaces(project, tmp_path, "7\n", focus="main")


def test_literal_arguments_have_identical_meaning_in_every_namespace(tmp_path):
    function = _function(
        "main",
        (_parameter("n", "main"),),
        (ProgramOutput("output:n", _expression("output:n", "n")),),
    )
    project = _project((function,), "main", parse_invocation_arguments("7"))
    _assert_all_surfaces(project, tmp_path, "7\n")
    invalid = replace(
        project,
        program_model=replace(
            project.program_model,
            entrypoint=replace(
                project.program_model.entrypoint, arguments=configured_arguments_from_text("VALUE")
            ),
        ),
    )
    assert "INVOCATION_LITERAL_ARGUMENTS" in {
        item.code for item in assess_project(invalid).diagnostics
    }
    with pytest.raises(BuildBlockedError, match="INVOCATION_LITERAL_ARGUMENTS"):
        generate_python_project(invalid)


@pytest.mark.parametrize(
    "source",
    [
        "VALUE",
        "1 + 2",
        "make()",
        "*values",
        "**values",
        "x.y",
        "[x for x in ()]",
        "lambda: 1",
        "b'bytes'",
        "float('inf')",
    ],
)
def test_argument_editor_rejects_namespace_or_executable_expressions(source):
    with pytest.raises(ValueError):
        parse_invocation_arguments(source)


def test_nested_literals_roundtrip_including_unicode_and_keyword_values():
    text = "7, -2.5, None, ['timer', True], (1,), options={'label': 'λ', 'values': [2, 3]}"
    values = parse_invocation_arguments(text)
    assert parse_invocation_arguments(render_invocation_arguments(values)) == values
    project = _project((), None, values)
    encoded = normalized_project_json(project)
    assert project_from_json(encoded) == project
    assert normalized_project_json(project_from_json(encoded)) == encoded


@pytest.mark.parametrize("source", ["7, label='ready'", "VALUE"])
def test_format_seven_migration_preserves_literals_or_explicit_unresolved_text(source):
    data = legacy_project_data(_project((), None), 7)
    data["module_setup"]["entrypoint_arguments"] = source
    project = project_from_data(data)
    assert project.format_revision == 11
    assert render_invocation_arguments(project.program_model.entrypoint_arguments) == source
    assert isinstance(
        project.program_model.entrypoint_arguments, UnresolvedInvocationArguments
    ) == (source == "VALUE")
    data["format_revision"] = 8
    with pytest.raises(ProjectDecodeError, match="FORMAT_INVOCATION_ARGUMENTS"):
        project_from_data(data)


@pytest.mark.parametrize("transaction", [False, True])
@pytest.mark.parametrize("source", ["7", "VALUE"])
def test_format_seven_recovery_history_migrates_arguments_for_undo_and_redo(
    tmp_path, transaction, source
):
    project = replace(_project((), None, configured_arguments_from_text(source)), revision=1)
    legacy = legacy_project_data(project, 7)
    payload = legacy["module_setup"]
    inverse = {**payload, "entrypoint_arguments": ""}
    command_type = "python.replace_module_setup"
    if transaction:
        payload = {"operations": [{"command_type": command_type, "payload": payload}]}
        inverse = {"operations": [{"command_type": command_type, "payload": inverse}]}
        command_type = "transaction"
    record = JournalRecord(
        1,
        "editor",
        "old-edit",
        command_type,
        project,
        forward_type=command_type,
        forward_payload=payload,
        inverse_type=command_type,
        inverse_payload=inverse,
    ).to_data()
    record["project"] = legacy
    store = ProjectStore(tmp_path)
    store.save(project)
    store.journal_file.parent.mkdir(parents=True, exist_ok=True)
    store.journal_file.write_text(json.dumps(record) + "\n", encoding="utf-8")
    authority = ProjectAuthority(store.recover(), store=store)
    client = CodeVisualizerClient(authority, actor_id="editor")
    try:
        assert isinstance(client.undo(), CommandAccepted)
        assert (
            render_invocation_arguments(client.snapshot().program_model.entrypoint_arguments) == ""
        )
        assert isinstance(client.redo(), CommandAccepted)
        assert (
            render_invocation_arguments(client.snapshot().program_model.entrypoint_arguments)
            == source
        )
    finally:
        client.close()
