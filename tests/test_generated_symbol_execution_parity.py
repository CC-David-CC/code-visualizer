"""Authored lexical names keep their meaning on every real-file execution surface."""

import subprocess
import sys
from dataclasses import replace

import pytest

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.computation import execute_computation
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.project_factory import create_default_project
from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.domain.invocation_arguments import parse_invocation_arguments
from code_visualizer.domain.program import (
    ExpressionRole,
    ProgramAction,
    ProgramDelay,
    ProgramLoop,
    ProgramOutput,
    ProgramParallel,
    ProgramParallelBranch,
    ProgramParameter,
    ProgramPeriod,
    ProgramSequence,
    ProgramSilhouette,
    ProgramSilhouetteBranch,
    ProgramStartTimer,
    ProgramSymbol,
    ProgramSymbolKind,
    ProgramSynchronizer,
    ProgramTransfer,
    make_program_expression,
)
from code_visualizer.domain.program_kinds import CallableKind, LoopKind, ParallelMode, TransferKind
from code_visualizer.domain.python_declarations import parse_python_declarations
from code_visualizer.execution import (
    DebugLaunch,
    DebugSession,
    SourceLocation,
    run_project,
    trace_project,
)
from code_visualizer.generation import generate_python_project
from code_visualizer.validation import assess_project


def _expression(owner, source, role=ExpressionRole.VALUE):
    return make_program_expression(owner, role.value, source, role)


def _action(owner, source):
    return ProgramAction(owner, _expression(owner, source, ExpressionRole.STATEMENTS))


def _output(source, owner="parity:output"):
    return ProgramOutput(owner, _expression(owner, source))


def _loop(kind, statements):
    return ProgramLoop(
        "parity:loop",
        kind,
        ProgramSequence("parity:loop:body", statements),
        ProgramSequence("parity:loop:else", ()),
        _expression("parity:condition", "False", ExpressionRole.CONDITION),
        _expression("parity:target", "node", ExpressionRole.TARGET),
        _expression("parity:iterable", "[1]"),
        _expression("parity:children", "lambda node: []"),
        _expression("parity:wait", "0.0"),
    )


def _case(name):
    project = create_default_project()
    model = project.program_model
    function = model.functions[0]
    extra_symbols = ()
    module_source = ""
    startup_source = ""
    arguments = ""
    if name == "parameter_timer":
        parameter = ProgramParameter("parity:param", "parity:param:symbol", "_cv_time")
        function = replace(function, parameters=(parameter,))
        extra_symbols = (
            ProgramSymbol(
                parameter.symbol_id,
                parameter.name,
                ProgramSymbolKind.PARAMETER,
                function.id,
                parameter.id,
            ),
        )
        arguments = "7"
        statements = (
            ProgramDelay("parity:delay", _expression("parity:delay", "0.0"), False),
            _output("_cv_time"),
        )
        expected = "7\n"
    elif name == "nested_free_timer":
        statements = (
            _action(
                "parity:setup",
                "_cv_time = 'local'\n"
                "_cv_timer_tick = 'timer'\n_cv_tick_deadline = 'deadline'\n"
                "nested = lambda: (_cv_time, _cv_timer_tick, _cv_tick_deadline)",
            ),
            ProgramStartTimer("parity:start", "tick"),
            ProgramPeriod("parity:period", "tick", _expression("parity:period", "0.0"), False),
            _output("nested()"),
        )
        expected = "('local', 'timer', 'deadline')\n"
    elif name == "unicode_module_timer":
        # Python normalizes identifiers to NFKC before determining lexical identity.
        module_source = "_cv_t\uff49me = 'unicode'"
        statements = (
            ProgramDelay("parity:delay", _expression("parity:delay", "0.0"), False),
            _output("_cv_time"),
        )
        expected = "unicode\n"
    elif name == "async_nested_free":
        function = replace(function, kind=CallableKind.ASYNC)
        statements = (
            _action(
                "parity:setup",
                "_cv_asyncio = 'authored'\nnested = lambda: _cv_asyncio",
            ),
            ProgramDelay("parity:delay", _expression("parity:delay", "0.0"), True),
            _output("nested()"),
        )
        expected = "authored\n"
    elif name == "parallel_closure":
        statements = (
            _action(
                "parity:setup",
                "_cv_futures = 'futures'\n_cv_pool = 'pool'\n"
                "_cv_pending = 'pending'\n_cv_future = 'future'\nobserved = []\n"
                "_cv_worker = lambda: 'worker'",
            ),
            ProgramParallel(
                "parity:parallel",
                (
                    ProgramParallelBranch(
                        "parity:branch",
                        "worker",
                        ProgramSequence(
                            "parity:branch:body",
                            (
                                _action(
                                    "parity:append",
                                    "observed.append((_cv_worker(), _cv_pool, "
                                    "_cv_pending, _cv_future))",
                                ),
                            ),
                        ),
                    ),
                    ProgramParallelBranch(
                        "parity:other",
                        "other",
                        ProgramSequence(
                            "parity:other:body", (_action("parity:noop", "other = None"),)
                        ),
                    ),
                ),
                ParallelMode.SYNC,
            ),
            _output("(observed, _cv_futures)"),
        )
        expected = "([('worker', 'pool', 'pending', 'future')], 'futures')\n"
    elif name in {"parallel_inherited_timer", "async_parallel_inherited_timer"}:
        asynchronous = name.startswith("async_")
        if asynchronous:
            function = replace(function, kind=CallableKind.ASYNC)
        synchronizer = ProgramSynchronizer(
            "parity:synchronizer",
            "clock",
            _expression("parity:deadline", "3600.0"),
            ProgramSequence(
                "parity:on-time", (_action("parity:captured", "observed.append('captured')"),)
            ),
            ProgramSequence(
                "parity:too-late", (_action("parity:timeout", "observed.append('timeout')"),)
            ),
            True,
        )
        statements = (
            _action("parity:setup", "observed = []\n_cv_timer_clock = 'authored'"),
            ProgramStartTimer("parity:start", "clock"),
            ProgramParallel(
                "parity:parallel",
                (
                    ProgramParallelBranch(
                        "parity:reader",
                        "reader",
                        ProgramSequence(
                            "parity:reader:body",
                            (synchronizer,),
                        ),
                    ),
                    ProgramParallelBranch(
                        "parity:other",
                        "other",
                        ProgramSequence(
                            "parity:other:body",
                            (_action("parity:noop", "other = None"),),
                        ),
                    ),
                ),
                ParallelMode.ASYNC if asynchronous else ParallelMode.SYNC,
            ),
            _output("(observed, _cv_timer_clock)"),
        )
        expected = "(['captured'], 'authored')\n"
    elif name == "loop_free_reference":
        module_source = "_cv_first_iteration = 'outer'\n_cv_first_iteration_1 = 'outer one'"
        statements = (
            _action(
                "parity:setup",
                "nested = lambda: (_cv_first_iteration, _cv_first_iteration_1)",
            ),
            _loop(LoopKind.DO_FIRST, (_output("nested()"),)),
        )
        expected = "('outer', 'outer one')\n"
    elif name == "bfs_locals":
        statements = (
            _action(
                "parity:setup",
                "_cv_deque = 'deque'\n_cv_node_work = 'work'\n_cv_node_work_1 = 'work one'",
            ),
            _loop(
                LoopKind.TREE_BFS, (_output("(node, _cv_deque, _cv_node_work, _cv_node_work_1)"),)
            ),
        )
        expected = "(1, 'deque', 'work', 'work one')\n"
    elif name == "silhouette_local":
        statements = (
            _action("parity:setup", "_flow_state = 'authored'\nnested = lambda: _flow_state"),
            ProgramSilhouette(
                "parity:silhouette",
                "Flow",
                "flow",
                (
                    ProgramSilhouetteBranch(
                        "parity:state",
                        "only",
                        ProgramSequence("parity:state:body", (_output("nested()"),)),
                        None,
                    ),
                ),
                "parity:state",
            ),
        )
        expected = "authored\n"
    elif name == "async_generator_startup":
        function = replace(function, kind=CallableKind.ASYNC_GENERATOR)
        startup_source = (
            "_entrypoint = lambda: print('wrong')\n_cv_asyncio = 'asyncio'\n"
            "_cv_consume_entrypoint = 'consumer'\n_cv_item = 'item'\n"
            "_cv_invocation_result = 'result'\n"
            "def retained(values=(_cv_asyncio, _cv_consume_entrypoint, _cv_item)):\n"
            "    return values\n"
            "class Authored:\n    snapshot = retained()\n"
            "print(Authored.snapshot)"
        )
        statements = (
            ProgramTransfer(
                "parity:yield", TransferKind.YIELD, _expression("parity:yield", "1"), None
            ),
            _output("'body'"),
        )
        expected = "('asyncio', 'consumer', 'item')\nbody\n"
    else:
        raise AssertionError(name)
    function = replace(function, body=replace(function.body, statements=statements))
    module = model.modules[0]
    module = replace(
        module,
        body=(
            *parse_python_declarations(
                module.id, module_source, identity_namespace="parity:module"
            ),
            *module.body,
        ),
    )
    entrypoint = replace(
        model.entrypoint,
        arguments=parse_invocation_arguments(arguments),
        startup=parse_python_declarations(
            "parity:startup", startup_source, identity_namespace="parity:startup"
        ),
    )
    model = replace(
        model,
        functions=(function,),
        symbols=(*model.symbols, *extra_symbols),
        modules=(module,),
        entrypoint=entrypoint,
    )
    return replace(project, documents=(), drakon_views=(), program_model=model), expected


CASES = (
    "parameter_timer",
    "nested_free_timer",
    "unicode_module_timer",
    "async_nested_free",
    "parallel_closure",
    "parallel_inherited_timer",
    "async_parallel_inherited_timer",
    "loop_free_reference",
    "bfs_locals",
    "silhouette_local",
    "async_generator_startup",
)


@pytest.mark.parametrize("name", CASES)
def test_generated_symbols_preserve_authored_meaning_on_all_surfaces(name, tmp_path):
    project, expected = _case(name)
    assert assess_project(project).diagnostics == ()
    generated = generate_python_project(project)
    assert generated == generate_python_project(project), "Symbol allocation must be deterministic"
    for item in generated.files:
        path = tmp_path / item.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(item.source, encoding="utf-8")
    saved = subprocess.run(
        [sys.executable, "-B", str(tmp_path / generated.launcher_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=False,
    )
    assert saved.returncode == 0, saved.stderr
    assert saved.stdout == expected
    live = run_project(generated, timeout=10)
    trace = trace_project(generated, timeout=10)
    for result in (live, trace.run):
        assert result.return_code == 0, result.stderr
        assert result.stdout == expected
        assert result.stderr == ""
    span = next(item for item in generated.spans if item.semantic_id == "parity:output")
    location = SourceLocation(span.file_path, span.start_line)
    assert any(event.location == location for event in trace.events)
    output = []
    with DebugSession() as debugger:
        debugger.start(
            DebugLaunch(project=generated, breakpoints=(location,), pause_on_exception=False)
        )
        paused = False
        while True:
            event = debugger.wait_event(timeout=10)
            if event.event == "paused":
                assert event.location == location
                assert event.reason == "breakpoint"
                paused = True
                debugger.continue_execution()
            if event.event == "output" and event.channel == "stdout":
                output.append(event.text)
            if event.event in {"finished", "failed", "stopped"}:
                assert event.event == "finished", event.traceback
                break
        assert paused
    assert "".join(output) == expected
    kernel = ProjectKernel(ProjectAuthority(project))
    try:
        evidence = execute_computation(
            kernel, ComputationRequest(project.id, project.revision, "code_visualizer.python", "1")
        )
        assert evidence.outcome is ComputationOutcome.SUCCEEDED, evidence.diagnostics
        assert (
            next(item.value for item in evidence.observations if item.id == "python:stdout")
            == expected
        )
        assert any("parity:output" in item.semantic_ids for item in evidence.observations)
        assert kernel.authority.snapshot() == project
    finally:
        kernel.close()
