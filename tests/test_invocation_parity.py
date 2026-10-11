"""Every execution surface must enter the selected canonical callable body."""

from __future__ import annotations

import threading
from dataclasses import replace

import pytest

from code_visualizer.application.examples import example_session
from code_visualizer.domain.invocation import bind_invocation
from code_visualizer.domain.invocation_arguments import parse_invocation_arguments
from code_visualizer.domain.program import (
    ExpressionRole,
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
    ProgramTransfer,
    make_program_expression,
)
from code_visualizer.domain.program_kinds import (
    CallableKind,
    MethodKind,
    ParameterKind,
    TransferKind,
)
from code_visualizer.domain.program_ownership import place_program_function
from code_visualizer.domain.project import Project
from code_visualizer.domain.python_declarations import parse_python_declarations
from code_visualizer.execution import (
    DebugLaunch,
    DebugSession,
    RunSession,
    SourceLocation,
    run_generated,
    run_project,
    trace_project,
)
from code_visualizer.generation import generate_python_project


def _project(
    kind: CallableKind, method_kind: MethodKind | None, *, failing: bool = False
) -> Project:
    def expression(owner: str, source: str, role: ExpressionRole = ExpressionRole.VALUE):
        return make_program_expression(owner, "value", source, role)

    receiver = (
        ("self",)
        if method_kind is MethodKind.INSTANCE
        else ("cls",)
        if method_kind is MethodKind.CLASS
        else ()
    )
    parameters = (
        *(
            ProgramParameter(
                f"parameter:{name}", f"symbol:{name}", name, ParameterKind.POSITIONAL_ONLY
            )
            for name in receiver
        ),
        ProgramParameter("parameter:n", "symbol:n", "n", ParameterKind.POSITIONAL_ONLY),
        ProgramParameter(
            "parameter:scale",
            "symbol:scale",
            "scale",
            ParameterKind.KEYWORD_ONLY,
            default=expression("parameter:scale", "3", ExpressionRole.DEFAULT),
        ),
    )
    statements = []
    if kind in {CallableKind.ASYNC, CallableKind.ASYNC_GENERATOR}:
        statements.append(
            ProgramCall(
                "statement:await",
                expression("statement:await:call", "asyncio.sleep(0)", ExpressionRole.CALL),
                expression("statement:await:args", "0", ExpressionRole.ARGUMENTS),
                awaited=True,
            )
        )
    statements.append(
        ProgramOutput("statement:body", expression("statement:body", 'f"body:{n * scale}"'))
    )
    if kind in {CallableKind.GENERATOR, CallableKind.ASYNC_GENERATOR}:
        statements.append(
            ProgramTransfer(
                "statement:yield",
                TransferKind.YIELD,
                expression("statement:yield", "n * scale"),
                None,
            )
        )
        statements.append(
            ProgramOutput(
                "statement:after-yield", expression("statement:after-yield", '"after yield"')
            )
        )
    if failing:
        statements.append(
            ProgramTransfer(
                "statement:raise",
                TransferKind.RAISE,
                expression("statement:raise", 'ValueError("body failed")'),
                None,
            )
        )
    elif kind is not CallableKind.ASYNC_GENERATOR:
        statements.append(
            ProgramTransfer(
                "statement:return",
                TransferKind.RETURN,
                expression("statement:return", "n * scale"),
                None,
            )
        )
    function = ProgramFunction(
        "function:calculate",
        "symbol:calculate",
        "calculate",
        "Calculate",
        kind,
        parameters,
        None,
        (),
        None,
        method_kind,
        ProgramSequence("sequence:body", tuple(statements)),
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
    program = ProgramModel(
        (function,),
        symbols,
        (
            ProgramModule(
                "module:main",
                "main",
                parse_python_declarations(
                    "module:main", "import asyncio", identity_namespace="parity"
                ),
            ),
        ),
        entrypoint=ProgramEntryPoint(
            "entrypoint:parity", function.id, parse_invocation_arguments("4, scale=6")
        ),
    )
    program = place_program_function(
        program, function.id, "main", "Calculator" if method_kind else None
    )
    return Project("project:invocation", "Invocation parity", (), program_model=program)


def _debug(project):
    events = []
    with DebugSession() as session:
        positions = tuple(
            SourceLocation(span.file_path, span.start_line)
            for span in project.spans
            if span.field != "signature"
        )
        session.start(DebugLaunch(project=project, breakpoints=positions))
        for _ in range(100):
            event = session.wait_event(timeout=10)
            events.append(event)
            if event.event == "paused":
                session.continue_execution()
            if event.event in {"finished", "failed", "stopped"}:
                return event, tuple(events)
    raise AssertionError("Invocation failed to reach a terminal debugger event")


def _live(project):
    session = RunSession()
    done = threading.Event()
    results = []

    def completed(result):
        results.append(result)
        done.set()

    session.start_project(project, timeout=10, completed=completed)
    try:
        assert done.wait(12), "Live invocation did not complete"
    finally:
        if session.is_active:
            session.stop()
    assert len(results) == 1
    return results[0]


def _disk(project: Project, directory):
    generated = generate_python_project(project)
    for file in generated.files:
        path = directory / file.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(file.source, encoding="utf-8")
    return run_generated(directory / "run_project.py", timeout=10)


@pytest.mark.parametrize("kind", tuple(CallableKind))
@pytest.mark.parametrize("method_kind", (None, *MethodKind))
def test_all_callable_and_method_shapes_execute_across_surfaces(kind, method_kind, tmp_path):
    project = _project(kind, method_kind)
    generated = generate_python_project(project)
    function = project.program_model.functions[0]
    invocation = bind_invocation(
        project.program_model, function, arguments=project.program_model.entrypoint_arguments
    )
    assert generated.invocation == invocation
    assert generate_python_project(project).invocation == invocation
    generator = kind in {CallableKind.GENERATOR, CallableKind.ASYNC_GENERATOR}
    body = "body:24\n" + ("after yield\n" if generator else "")
    disk = _disk(project, tmp_path)
    assert disk.return_code == 0, disk.stderr
    assert disk.stdout == body
    direct = run_project(generated)
    live = _live(generated)
    trace = trace_project(generated, timeout=10)
    for result in (direct, live, trace.run):
        assert result.return_code == 0, result.stderr
        assert result.stdout == disk.stdout
        assert result.stderr == ""
        assert not result.timed_out
    body_events = tuple(event for event in trace.events if event.function == "calculate")
    assert body_events
    assert any(dict(event.locals).get("n") == "4" for event in body_events)
    assert any(dict(event.locals).get("scale") == "6" for event in body_events)
    terminal, events = _debug(generated)
    assert terminal.event == "finished"
    assert terminal.result == "None"
    assert any(event.event == "paused" and event.function == "calculate" for event in events)
    assert (
        "".join(
            event.text for event in events if event.event == "output" and event.channel == "stdout"
        )
        == body
    )
    assert not any(event.event == "output" and event.channel == "stderr" for event in events)


@pytest.mark.parametrize("example_id", ("async", "generators", "classes"))
def test_existing_examples_execute_the_body_in_editor_run_trace_and_debug(example_id, tmp_path):
    session = example_session(example_id)
    try:
        project = session.authority.snapshot()
        generated = generate_python_project(project)
        invocation = generated.invocation
        assert invocation is not None
        disk = _disk(project, tmp_path)
        assert disk.return_code == 0 and disk.stdout
        direct = run_project(generated, timeout=10)
        trace = trace_project(generated, timeout=10)
        live = _live(generated)
        for result in (direct, trace.run, live):
            assert result.return_code == 0, result.stderr
            assert result.stdout == disk.stdout
            assert result.stderr == ""
        assert trace.events
        assert any(event.function == invocation.identifier for event in trace.events)
        terminal, events = _debug(generated)
        assert terminal.event == "finished"
        assert any(
            event.event == "paused" and event.function == invocation.identifier for event in events
        )
        output = "".join(
            event.text for event in events if event.event == "output" and event.channel == "stdout"
        )
        assert output == disk.stdout
    finally:
        session.close()


@pytest.mark.parametrize("kind", tuple(CallableKind))
def test_failure_inside_every_callable_body_surfaces_in_all_execution_paths(kind, tmp_path):
    project = _project(kind, MethodKind.INSTANCE, failing=True)
    generated = generate_python_project(project)
    invocation = generated.invocation
    assert invocation is not None
    direct = run_project(generated)
    live = _live(generated)
    trace = trace_project(generated, timeout=10)
    disk = _disk(project, tmp_path)
    for result in (disk, direct, live, trace.run):
        assert result.return_code != 0
        assert "ValueError: body failed" in result.stderr
        assert "body:24" in result.stdout
        assert "was never awaited" not in result.stderr
    assert any(
        event.function == "calculate" and "body failed" in event.detail for event in trace.events
    )
    terminal, events = _debug(generated)
    assert terminal.event == "failed"
    assert terminal.detail == "body failed"
    assert any(event.reason == "exception" and event.function == "calculate" for event in events)


def test_default_and_keyword_arguments_share_the_same_invocation_without_mutating_program():
    project = _project(CallableKind.ASYNC, MethodKind.CLASS)
    function = project.program_model.functions[0]
    generated = generate_python_project(project)
    invocation = bind_invocation(
        project.program_model, function, arguments=parse_invocation_arguments("5")
    )
    live = generate_python_project(project, invocation=invocation)
    for call in (run_project, trace_project):
        result = call(live)
        run = result.run if hasattr(result, "run") else result
        assert run.return_code == 0, run.stderr
        assert run.stdout == "body:15\n"
    assert generated.invocation == replace(
        invocation, arguments=parse_invocation_arguments("4, scale=6")
    )
    assert function == project.program_model.functions[0]
