from code_visualizer.domain.invocation import InvocationSpec
from code_visualizer.execution import (
    DebugLaunch,
    DebugSession,
    DebugState,
    RuntimeBinding,
    RuntimeBindingSpec,
    RuntimeGraphDelta,
    RuntimeTraceStore,
    RuntimeValue,
    RuntimeValueKind,
)


def _paused(session: DebugSession):
    while True:
        event = session.wait_event()
        if event.event == "paused":
            return event


def test_debugger_steps_breaks_and_reports_changed_locals() -> None:
    source = """def helper(value):
    doubled = value * 2
    return doubled

def main():
    number = 20
    answer = helper(number) + 2
    print(answer)
    return answer
"""
    with DebugSession(history_limit=20) as session:
        session.start(DebugLaunch(source, InvocationSpec("main"), breakpoints=(7,)))
        first = _paused(session)
        assert first.line == 6
        assert first.function == "main"
        assert first.reason == "step"

        session.step_over()
        second = _paused(session)
        assert second.line == 7
        assert second.reason == "breakpoint"
        assert dict(second.locals)["number"] == "20"
        assert "number" in second.changed_locals

        session.step_into()
        helper = _paused(session)
        assert helper.function == "helper"
        assert helper.line == 2
        assert helper.stack[0].function == "helper"
        assert helper.stack[1].function == "main"

        session.step_out()
        returned = _paused(session)
        assert returned.function == "main"
        assert returned.line == 8
        assert "answer" in returned.changed_locals
        session.continue_execution()
        finished = session.wait_for("finished")
        assert finished.result == "42"
        assert session.state is DebugState.FINISHED
        assert len(session.history) == 4


def test_debugger_pauses_on_exception_and_can_restart_and_stop() -> None:
    source = """def main():
    value = 1
    raise ValueError("broken")
"""
    with DebugSession() as session:
        session.start(DebugLaunch(source, InvocationSpec("main")))
        _paused(session)
        session.continue_execution()
        exception = _paused(session)
        assert exception.reason == "exception"
        assert "broken" in exception.detail
        session.continue_execution()
        failed = session.wait_for("failed")
        assert failed.return_code == 1
        assert failed.detail == "broken"

        session.restart()
        assert _paused(session).line == 2
        session.stop()
        assert session.state is DebugState.STOPPED


def test_debugger_streams_output_and_accepts_stdin() -> None:
    source = """def main():
    name = input("Name? ")
    print("Hello", name)
"""
    with DebugSession() as session:
        session.start(DebugLaunch(source, InvocationSpec("main")))
        _paused(session)
        session.continue_execution()
        output = session.wait_for("output")
        assert output.text == "Name? "
        session.wait_for("input_requested")
        session.send_stdin("Ada")
        chunks: list[str] = []
        while True:
            event = session.wait_event()
            if event.event == "output":
                chunks.append(event.text)
            if event.event == "finished":
                break
        assert "Hello" in "".join(chunks)
        assert "Ada" in "".join(chunks)


def test_runtime_graph_preserves_aliases_cycles_bounds_and_revision_identity() -> None:
    source = """def main():
    shared = []
    model = {"left": shared, "right": shared}
    model["self"] = model
    many = list(range(100))
    return len(many)
"""
    with DebugSession(history_limit=20) as session:
        session.start(
            DebugLaunch(
                source,
                InvocationSpec("main"),
                execution_session_id="execution_revision_17",
                project_revision=17,
                artifact_revision=17,
            )
        )
        paused = _paused(session)
        while paused.line < 6:
            session.step_over()
            paused = _paused(session)

        graph = paused.runtime_graph
        assert graph is not None
        assert graph.execution_session_id == "execution_revision_17"
        assert graph.project_revision == 17
        assert graph.artifact_revision == 17
        assert not graph.checkpoint
        values = {item.value_id: item for item in graph.values}
        bindings = {item.name: item for item in graph.bindings}
        model = values[bindings["model"].value_id]
        model_children = {item.label: item.value_id for item in model.children}
        assert model_children["'left'"] == model_children["'right'"]
        assert model_children["'self'"] == model.value_id
        many = values[bindings["many"].value_id]
        assert len(many.children) == 64
        assert many.truncated

        session.continue_execution()
        assert session.wait_for("finished").result == "100"


def test_runtime_bindings_carry_stable_semantic_symbol_and_frame_ids() -> None:
    source = """def main():
    answer = 42
    return answer
"""
    with DebugSession() as session:
        session.start(
            DebugLaunch(
                source,
                InvocationSpec("main"),
                binding_specs=(RuntimeBindingSpec("main", "answer", "symbol_answer"),),
            )
        )
        paused = _paused(session)
        while "answer" not in dict(paused.locals):
            session.step_over()
            paused = _paused(session)
        assert paused.runtime_graph is not None
        binding = next(item for item in paused.runtime_graph.bindings if item.name == "answer")
        assert binding.semantic_symbol_id == "symbol_answer"
        assert binding.frame_id == paused.runtime_graph.frame_id
        assert session.runtime_trace.latest == paused.runtime_graph
        assert session.history[-1].runtime_graph is None


def test_runtime_trace_store_reconstructs_and_rebases_bounded_deltas() -> None:
    first_value = RuntimeValue("value", "builtins.int", RuntimeValueKind.SCALAR, "1", 1)
    second_value = RuntimeValue("value", "builtins.int", RuntimeValueKind.SCALAR, "2", 2)
    store = RuntimeTraceStore(history_limit=2, cache_size=1)
    store.append(
        RuntimeGraphDelta(
            "execution_compact",
            3,
            3,
            10,
            "frame",
            (RuntimeBinding("answer", "value"),),
            (first_value,),
            history_index=0,
            checkpoint=True,
        )
    )
    store.append(
        RuntimeGraphDelta(
            "execution_compact",
            3,
            3,
            11,
            "frame",
            (RuntimeBinding("answer", "value", True),),
            (second_value,),
            history_index=1,
        )
    )
    reconstructed = store.graph_at(1)
    assert reconstructed is not None
    assert reconstructed.value("value") == second_value
    store.append(
        RuntimeGraphDelta(
            "execution_compact",
            3,
            3,
            12,
            "frame",
            (),
            (),
            ("value",),
            history_index=2,
        )
    )
    assert store.indices == (1, 2)
    assert store.updates[0].checkpoint
    latest = store.latest
    assert latest is not None and latest.value("value") is None
