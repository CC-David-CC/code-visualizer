"""Sparse traces do not allocate a second index of unvisited source locations."""

import tracemalloc

import pytest

from code_visualizer.application.editor_preparation import EditorPreparedSnapshot
from code_visualizer.application.trace_presentation import SourceSpanPolicy, map_trace
from code_visualizer.execution.runner import RunResult, TraceEvent, TraceResult
from code_visualizer.generation.emitter import GeneratedFile, GeneratedProject, SourceSpan


@pytest.mark.parametrize("policy", tuple(SourceSpanPolicy))
def test_sparse_trace_mapping_allocates_only_for_visited_intervals(policy):
    spans = tuple(
        SourceSpan(
            f"map:{line}",
            "app/main.py",
            "project",
            f"operation:{line}",
            "diagram",
            "expression",
            line,
            0,
            line,
            4,
        )
        for line in range(1, 50_001)
    )
    generated = GeneratedProject(
        (GeneratedFile("app/main.py", "pass\n" * len(spans), spans),),
        None,
        None,
    )
    snapshot = EditorPreparedSnapshot("request", "project", 1, "ready", generated=generated)
    lines = (49_999, 10, 25_000, 10)
    result = TraceResult(
        RunResult(0, "", ""),
        tuple(
            TraceEvent(index, "line", line, "main", file_path="app/main.py")
            for index, line in enumerate(lines)
        ),
    )
    tracemalloc.start()
    try:
        mapped = map_trace(snapshot, result, policy=policy)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert mapped.spans == tuple(spans[line - 1] for line in lines)
    assert mapped.result is result
    # Includes the flat tuple of source-span references and complete result. The
    # 49,997 unvisited intervals must not acquire sorting/priority records.
    assert peak < 2 * 1024 * 1024, peak
