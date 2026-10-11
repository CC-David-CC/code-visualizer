import pytest

from code_visualizer.application.runtime_projection import (
    RuntimeAdapterKind,
    compile_runtime_projection,
    infer_runtime_adapter,
)
from code_visualizer.application.runtime_sessions import (
    RuntimeSessionRegistry,
    runtime_session_to_data,
)
from code_visualizer.application.session import ProjectSession
from code_visualizer.automation.service import (
    AccessMode,
    AutomationCapability,
    AutomationContext,
    AutomationService,
)
from code_visualizer.domain.projection import ProjectionLayout
from code_visualizer.domain.semantic import SemanticRelationKind
from code_visualizer.execution import (
    DebugEvent,
    DebugState,
    RuntimeBinding,
    RuntimeChild,
    RuntimeGraph,
    RuntimeValue,
    RuntimeValueKind,
    SourceLocation,
)


def _heap_graph(sequence: int = 1, project_revision: int = 7) -> RuntimeGraph:
    return RuntimeGraph(
        "execution_heap",
        project_revision,
        project_revision,
        sequence,
        "frame_main",
        (RuntimeBinding("frontier_heap", "heap", True),),
        (
            RuntimeValue(
                "heap",
                "builtins.list",
                RuntimeValueKind.SEQUENCE,
                "[1, 4, 3]",
                children=(
                    RuntimeChild("0", "one"),
                    RuntimeChild("1", "four"),
                    RuntimeChild("2", "three"),
                ),
            ),
            RuntimeValue("one", "builtins.int", RuntimeValueKind.SCALAR, "1", 1),
            RuntimeValue("four", "builtins.int", RuntimeValueKind.SCALAR, "4", 4),
            RuntimeValue("three", "builtins.int", RuntimeValueKind.SCALAR, "3", 3),
        ),
        history_index=sequence,
        checkpoint=True,
    )


def test_runtime_registry_keeps_a_bounded_queryable_timeline() -> None:
    registry = RuntimeSessionRegistry(history_limit=3)
    observed = []
    registry.subscribe(observed.append, replay=False)
    registry.mark_starting("execution_heap", 7, 7)
    for sequence in range(1, 4):
        registry.record(
            DebugEvent(
                sequence,
                "paused",
                DebugState.PAUSED,
                execution_session_id="execution_heap",
                project_revision=7,
                artifact_revision=7,
                runtime_graph=_heap_graph(sequence),
            ),
            semantic_id=f"operation_{sequence}",
        )

    history = registry.history()
    assert len(history) == 3
    assert [item.event_sequence for item in history] == [1, 2, 3]
    assert history[-1] == registry.active
    assert observed[-1] == registry.active
    assert registry.history("missing") == ()

    with pytest.raises(ValueError, match="must match"):
        registry.record(
            DebugEvent(
                4,
                "paused",
                DebugState.PAUSED,
                execution_session_id="execution_heap",
                project_revision=7,
                artifact_revision=7,
                runtime_graph=_heap_graph(99),
            )
        )


def test_runtime_history_and_automation_keep_same_line_in_different_files_distinct():
    registry = RuntimeSessionRegistry()
    for sequence, file_path in enumerate(("app/one.py", "app/two.py"), start=1):
        registry.record(
            DebugEvent(
                sequence,
                "paused",
                DebugState.PAUSED,
                line=7,
                file_path=file_path,
                execution_session_id="execution_files",
                project_revision=3,
                artifact_revision=3,
            ),
            semantic_id=f"operation:{sequence}",
        )
    assert tuple(item.location for item in registry.history()) == (
        SourceLocation("app/one.py", 7),
        SourceLocation("app/two.py", 7),
    )
    assert runtime_session_to_data(registry.active)["location"] == {
        "file_path": "app/two.py",
        "line": 7,
        "column": 0,
    }


def test_runtime_adapter_turns_a_sequence_into_heap_topology_without_mutation() -> None:
    registry = RuntimeSessionRegistry()
    state = registry.record(
        DebugEvent(
            9,
            "paused",
            DebugState.PAUSED,
            execution_session_id="execution_heap",
            project_revision=7,
            artifact_revision=7,
            runtime_graph=_heap_graph(9),
        ),
        semantic_id="operation_relax",
    )
    assert infer_runtime_adapter(state.graph, "frontier_heap") is RuntimeAdapterKind.HEAP

    projection = compile_runtime_projection(
        "project_graph",
        state,
        adapter=RuntimeAdapterKind.AUTO,
        binding_name="frontier_heap",
    )
    assert projection.definition_id == "runtime:heap"
    assert projection.layout == ProjectionLayout.HIERARCHICAL.value
    assert {item.semantic_id for item in projection.nodes} >= {
        "operation_relax",
        "heap",
        "one",
        "four",
        "three",
    }
    heap_edges = {
        (item.source_id.rsplit(":", 1)[-1], item.target_id.rsplit(":", 1)[-1])
        for item in projection.edges
        if item.kind is SemanticRelationKind.CONTAINS
    }
    assert ("one", "four") in heap_edges
    assert ("one", "three") in heap_edges
    assert any("heap index 0" in item.badges for item in projection.nodes)
    assert state.graph == _heap_graph(9)

    tensor_graph = RuntimeGraph(
        "execution_tensor",
        7,
        7,
        1,
        "frame_tensor",
        (RuntimeBinding("weights", "tensor"),),
        (
            RuntimeValue(
                "tensor",
                "torch.Tensor",
                RuntimeValueKind.OPAQUE,
                "tensor(shape=(2, 2))",
            ),
        ),
    )
    assert infer_runtime_adapter(tensor_graph, "weights") is RuntimeAdapterKind.TENSOR


def test_runtime_history_is_discoverable_through_the_shared_automation_service() -> None:
    session = ProjectSession.new()
    service = AutomationService(session.authority, kernel=session.kernel)
    context = AutomationContext(
        "runtime-reader",
        "runtime-connection",
        AccessMode.COMMIT,
        frozenset({AutomationCapability.READ}),
    )
    try:
        session.kernel.runtime.record(
            DebugEvent(
                5,
                "paused",
                DebugState.PAUSED,
                execution_session_id="execution_heap",
                project_revision=session.authority.revision,
                artifact_revision=session.authority.revision,
                runtime_graph=_heap_graph(5, session.authority.revision),
            )
        )
        capabilities = service.dispatch("service.capabilities", {}, context)
        assert isinstance(capabilities, dict)
        assert "runtime.history" in capabilities["methods"]
        history = service.dispatch(
            "runtime.history",
            {"execution_session_id": "execution_heap"},
            context,
        )
        assert isinstance(history, list)
        assert history[0]["event_sequence"] == 5
        assert history[0]["graph"]["history_index"] == 5
    finally:
        service.close()
        session.close()
