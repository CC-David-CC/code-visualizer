from dataclasses import replace
from threading import Event

import pytest

from code_visualizer.domain.invocation import InvocationSpec, invocation_symbols, render_invocation
from code_visualizer.domain.invocation_arguments import parse_invocation_arguments
from code_visualizer.domain.program_kinds import CallableKind
from code_visualizer.execution.runner import (
    RunSession,
    run_generated,
    run_project,
    run_source,
    trace_project,
    trace_source,
)
from code_visualizer.execution.runtime import RuntimeBindingSpec
from code_visualizer.generation.emitter import emit_project
from code_visualizer.generation.ir import (
    EntryPointIR,
    ModuleIR,
    Origin,
    PythonProjectIR,
    RawStatementIR,
)


@pytest.mark.parametrize(
    "name,kind",
    [
        ("_cv_invocation_result", CallableKind.GENERATOR),
        ("_cv_item", CallableKind.GENERATOR),
        ("_cv_consume_entrypoint", CallableKind.ASYNC_GENERATOR),
        ("_cv_asyncio", CallableKind.ASYNC),
    ],
)
def test_wrapper_bindings_do_not_overwrite_legal_entrypoint_names(name, kind, tmp_path):
    generator = kind in {CallableKind.GENERATOR, CallableKind.ASYNC_GENERATOR}
    prefix = "async " if kind in {CallableKind.ASYNC, CallableKind.ASYNC_GENERATOR} else ""
    source = f'{prefix}def {name}():\n    print("entered")\n'
    if generator:
        source += '    yield 1\n    print("completed")\n'
    invocation = InvocationSpec(name, kind, callable_id="canonical:function")
    expected = "entered\n" + ("completed\n" if generator else "")
    origin = Origin("project", "canonical:function", "body")
    module = ModuleIR("main", "", (RawStatementIR(source, origin),), origin)
    ir = PythonProjectIR(
        "project", 0, "app", (module,), (), EntryPointIR("main", invocation, origin)
    )
    emitted = emit_project(ir)
    for item in emitted.files:
        path = tmp_path / item.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(item.source, encoding="utf-8")
    results = (
        run_project(emitted),
        trace_project(emitted).run,
        run_generated(tmp_path / "run_project.py"),
    )
    for result in results:
        assert result.return_code == 0, result.stderr
        assert result.stdout == expected
        assert not result.stderr


def test_argument_bindings_are_preserved_until_generator_call_has_finished():
    source = "_cv_invocation_result = 7\ndef values(value):\n    print(value)\n    yield value\n"
    with pytest.raises(ValueError, match="literal"):
        parse_invocation_arguments("_cv_invocation_result")
    invocation = InvocationSpec(
        "values", CallableKind.GENERATOR, arguments=parse_invocation_arguments("7")
    )
    assert run_source(source, invocation=invocation).stdout == "7\n"
    assert trace_source(source, invocation=invocation).run.stdout == "7\n"


def test_allocated_async_names_are_shared_and_avoid_argument_names():
    invocation = InvocationSpec(
        "run",
        CallableKind.ASYNC_GENERATOR,
        arguments=parse_invocation_arguments(
            "'_cv_asyncio', '_cv_asyncio_2', '_cv_consume_entrypoint', '_cv_item'"
        ),
    )
    symbols = invocation_symbols(invocation)
    assert symbols.asyncio_alias == "_cv_asyncio"
    assert symbols.consumer == "_cv_consume_entrypoint"
    assert symbols.item == "_cv_item"
    rendered = render_invocation(invocation)
    assert f"import asyncio as {symbols.asyncio_alias}" in rendered
    assert f"async def {symbols.consumer}():" in rendered
    scope = {}
    exec("async def selected():\n    yield 1\n_cv_consume_entrypoint = selected\n", scope)
    exec(
        render_invocation(
            InvocationSpec("selected", CallableKind.ASYNC_GENERATOR),
            imported_alias="_cv_consume_entrypoint",
        ),
        scope,
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("identifier", None),
        ("identifier", 7),
        ("owning_class", 7),
        ("callable_id", False),
    ],
)
def test_typed_invocation_rejects_mistyped_direct_values(field, value):
    with pytest.raises(ValueError):
        replace(InvocationSpec("run"), **{field: value})


def test_asynchronous_trace_session_forwards_revision_pins_and_semantic_bindings():
    completed = Event()
    results = []
    session = RunSession()

    def receive(result):
        results.append(result)
        completed.set()

    try:
        session.start_trace(
            "def main():\n    value = 7\n    print(value)\n",
            invocation=InvocationSpec("main", callable_id="canonical:main"),
            project_revision=47,
            artifact_revision=47,
            binding_specs=(RuntimeBindingSpec("main", "value", "canonical:value"),),
            completed=receive,
        )
        assert completed.wait(10)
        result = results[0]
        assert result.run.return_code == 0, result.run.stderr
        assert result.run.stdout == "7\n"
        assert result.runtime_events
        assert all(
            (event.project_revision, event.artifact_revision) == (47, 47)
            for event in result.runtime_events
        )
        assert result.terminal_event.project_revision == 47
        assert any(
            binding.semantic_symbol_id == "canonical:value"
            for event in result.runtime_events
            if event.runtime_graph is not None
            for binding in event.runtime_graph.bindings
        )
    finally:
        session.stop()


@pytest.mark.parametrize("initialization_fails", [False, True])
def test_source_initialization_output_and_failure_use_structured_debug_transport(
    initialization_fails,
):
    source = 'print("initializing")\n'
    if initialization_fails:
        source += 'raise ValueError("initialization failed")\n'
    source += 'def main():\n    print("body")\n'
    invocation = InvocationSpec("main")
    direct = run_source(source, invocation=invocation)
    traced = trace_source(source, invocation=invocation)
    assert traced.run.stdout == direct.stdout
    assert traced.run.return_code == direct.return_code
    assert traced.terminal_event is not None
    if initialization_fails:
        assert traced.terminal_event.event == "failed"
        assert "ValueError: initialization failed" in traced.terminal_event.traceback
        assert not traced.events
    else:
        assert traced.run.stdout == "initializing\nbody\n"
        assert traced.terminal_event.event == "finished"
        assert traced.events
        assert all(event.function == "main" for event in traced.events)
