"""Trace previews are bounded derived data; mappings and captured values remain complete."""

from dataclasses import replace

import pytest

from code_visualizer.application.editor_preparation import EditorPreparedSnapshot
from code_visualizer.application.trace_presentation import (
    MAX_TRACE_CONSOLE_CHARS,
    MAX_TRACE_OUTPUT_PAGE_CHARS,
    MAX_TRACE_OUTPUT_PAGE_LINES,
    TRACE_PREVIEW_NOTICE,
    SourceSpanPolicy,
    TraceOutputPage,
    map_trace,
    output_page_text,
)
from code_visualizer.execution.debugger import DebugEvent, DebugState
from code_visualizer.execution.runner import RunResult, TraceEvent, TraceResult
from code_visualizer.generation.emitter import GeneratedFile, GeneratedProject, SourceSpan


def _span(identity, start, end=None, path="app/main.py"):
    return SourceSpan(
        f"map:{identity}",
        path,
        "project",
        identity,
        "diagram",
        "expression",
        start,
        0,
        end or start,
        4,
    )


def _snapshot(spans):
    files = {}
    for span in spans:
        files.setdefault(span.file_path, []).append(span)
    generated = GeneratedProject(
        (
            *(
                GeneratedFile(
                    path,
                    "pass\n" * max(span.end_line for span in entries),
                    tuple(entries),
                )
                for path, entries in files.items()
            ),
            GeneratedFile("run_project.py", "pass\n", ()),
        ),
        None,
        None,
    )
    return EditorPreparedSnapshot("request", "project", 7, "ready", generated=generated)


def test_small_trace_preserves_console_format_and_exact_captured_objects():
    span = _span("operation", 10)
    snapshot = _snapshot((span,))
    event = TraceEvent(7, "line", 10, "main", (("value", "42"),), file_path=span.file_path)
    runtime = DebugEvent(7, "trace", DebugState.RUNNING, 10, "main", file_path=span.file_path)
    result = TraceResult(
        RunResult(0, "Hello\n", "warning\n", duration_seconds=0.25),
        (event,),
        runtime_events=(runtime,),
    )
    mapped = map_trace(snapshot, result)
    assert mapped.snapshot is snapshot
    assert mapped.result is result
    assert mapped.spans == (span,)
    assert mapped.terminal_span is None
    assert mapped.console == (
        "--- stdout ---\nHello\n--- stderr ---\nwarning\n--- mapped trace ---\n"
        "0007 line      app/main.py:10 · expression · operation · value=42\n"
        "Process exited; exit 0; 0.250s\n"
    )


def test_interval_lookup_preserves_original_span_priority_file_identity_and_event_order():
    broad = _span("first-broad", 5, 20)
    narrow = _span("later-narrow", 10)
    early = _span("early-line", 1, 2)
    other = _span("other-file", 10, path="app/other.py")
    snapshot = _snapshot((broad, narrow, early, other))
    events = tuple(
        TraceEvent(index, "line", line, "main", file_path=path)
        for index, (path, line) in enumerate(
            (
                ("app/main.py", 10),
                ("app/other.py", 10),
                ("app/main.py", 2),
                ("missing.py", 10),
                ("app/main.py", 21),
                ("app/main.py", 10),
            )
        )
    )
    mapped = map_trace(snapshot, TraceResult(RunResult(0, "", ""), events))
    assert mapped.spans == (broad, other, early, None, None, broad)


def test_narrowest_policy_preserves_width_start_and_original_order_ties():
    broad = _span("broad", 1, 40)
    later = _span("same-width-later-start", 11, 13)
    first = _span("first-tied-span", 10, 12)
    second = _span("second-tied-span", 10, 12)
    other = _span("other-file", 11, path="app/other.py")
    spans = (broad, later, first, second, other)
    snapshot = _snapshot(spans)
    events = tuple(
        TraceEvent(index, "line", line, "main", file_path=path)
        for index, (path, line) in enumerate(
            (
                ("app/main.py", 11),
                ("app/main.py", 13),
                ("app/other.py", 11),
                ("app/main.py", 14),
                ("app/main.py", 12),
                ("app/main.py", 41),
            )
        )
    )
    result = TraceResult(RunResult(0, "", ""), events)
    mapped = map_trace(snapshot, result, policy=SourceSpanPolicy.NARROWEST)
    assert mapped.spans == (first, later, other, broad, first, None)
    assert mapped.result is result
    assert map_trace(snapshot, result).spans == (broad, broad, other, broad, broad, None)


@pytest.mark.parametrize("policy", tuple(SourceSpanPolicy))
def test_terminal_location_uses_the_same_policy_without_creating_a_trace_event(policy):
    broad = _span("terminal-broad", 5, 20)
    narrow = _span("terminal-narrow", 10)
    event_span = _span("operation", 1)
    snapshot = _snapshot((broad, narrow, event_span))
    event = TraceEvent(0, "line", 1, "main", file_path="app/main.py")
    terminal = DebugEvent(1, "finished", DebugState.FINISHED, 10, "main", file_path="app/main.py")
    result = TraceResult(RunResult(0, "", ""), (event,), terminal_event=terminal)
    mapped = map_trace(snapshot, result, policy=policy)
    assert mapped.spans == (event_span,)
    assert mapped.terminal_span is (narrow if policy is SourceSpanPolicy.NARROWEST else broad)
    assert mapped.result is result
    assert mapped.result.terminal_event is terminal
    assert mapped.result.events == (event,)

    without_events = map_trace(snapshot, replace(result, events=()), policy=policy)
    assert without_events.spans == ()
    assert without_events.terminal_span is mapped.terminal_span
    missing = replace(terminal, file_path="missing.py")
    assert (
        map_trace(snapshot, replace(result, terminal_event=missing), policy=policy).terminal_span
        is None
    )
    no_location = replace(terminal, line=0)
    assert (
        map_trace(
            snapshot, replace(result, terminal_event=no_location), policy=policy
        ).terminal_span
        is None
    )


def test_large_console_is_a_preview_without_truncating_trace_output_values_or_mappings():
    span = _span("operation", 1)
    snapshot = _snapshot((span,))
    captured = "full value " * 10_000
    events = tuple(
        TraceEvent(index, "line", 1, "main", (("large", captured),), file_path=span.file_path)
        for index in range(2000)
    )
    result = TraceResult(RunResult(0, "stdout " * 20_000, "stderr " * 20_000), events, True)
    mapped = map_trace(snapshot, result)
    assert len(mapped.console) <= MAX_TRACE_CONSOLE_CHARS
    assert mapped.console.count(TRACE_PREVIEW_NOTICE) == 1
    assert "--- stdout ---" in mapped.console
    assert "--- stderr ---" in mapped.console
    assert "--- mapped trace ---" in mapped.console
    assert "Trace event limit reached; remaining events were not recorded." in mapped.console
    assert mapped.console.endswith("Process exited; exit 0; 0.000s\n")
    assert mapped.result is result
    assert mapped.result.events is events
    assert mapped.result.events[-1].locals[0][1] is captured
    assert mapped.result.run.stdout == "stdout " * 20_000
    assert mapped.result.run.stderr == "stderr " * 20_000
    assert len(mapped.spans) == 2000
    assert all(value is span for value in mapped.spans)


@pytest.mark.parametrize("policy", tuple(SourceSpanPolicy))
def test_mapping_work_does_not_rescan_all_source_spans_for_each_event(monkeypatch, policy):
    spans = tuple(_span(f"operation:{line}", line) for line in range(1, 10_503))
    snapshot = _snapshot(spans)
    events = tuple(
        TraceEvent(index, "line", line, "main", file_path="app/main.py")
        for index, line in enumerate(range(8503, 10_503))
    )
    original = SourceSpan.__getattribute__
    line_reads = 0

    def measured(instance, name):
        nonlocal line_reads
        if name in {"start_line", "end_line"}:
            line_reads += 1
        return original(instance, name)

    monkeypatch.setattr(SourceSpan, "__getattribute__", measured)
    mapped = map_trace(snapshot, TraceResult(RunResult(0, "", ""), events), policy=policy)
    assert mapped.spans == spans[-2000:]
    assert line_reads <= 4 * (len(spans) + len(events))


def test_trace_mapping_requires_its_pinned_artifact():
    snapshot = replace(_snapshot(()), generated=None)
    with pytest.raises(ValueError, match="pinned generated files"):
        map_trace(snapshot, TraceResult(RunResult(0, "", ""), ()))


@pytest.mark.parametrize(
    "stdout,stderr",
    (
        ("x" * (MAX_TRACE_OUTPUT_PAGE_CHARS * 2 + 1), "final diagnostic\n"),
        ("\n" * 10_000, "error\r\n" * 2500),
        (
            "x" * (MAX_TRACE_OUTPUT_PAGE_CHARS - 1) + "\r\nlast\n",
            "\r\n\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029" * 200,
        ),
    ),
    ids=("long-lines", "dense-newlines", "mixed-separators"),
)
def test_output_pages_losslessly_cover_retained_channels_with_bounded_layout(stdout, stderr):
    span = _span("operation", 1)
    event = TraceEvent(0, "line", 1, "main", file_path=span.file_path)
    terminal = DebugEvent(1, "finished", DebugState.FINISHED, 1, "main", file_path=span.file_path)
    result = TraceResult(
        RunResult(0, stdout, stderr), (event,), runtime_events=(terminal,), terminal_event=terminal
    )
    mapped = map_trace(_snapshot((span,)), result)
    for channel, original in (("stdout", stdout), ("stderr", stderr)):
        pages = tuple(page for page in mapped.output_pages if page.channel == channel)
        pieces = []
        offset = 0
        for number, page in enumerate(pages, start=1):
            assert page.number == number and page.start == offset
            assert f"{channel} · page {number}" in page.label
            text = output_page_text(mapped, page)
            assert text == original[page.start : page.end]
            assert 0 < len(text) <= MAX_TRACE_OUTPUT_PAGE_CHARS
            assert len(text.splitlines()) <= MAX_TRACE_OUTPUT_PAGE_LINES
            assert text.count("\n") + 1 <= MAX_TRACE_OUTPUT_PAGE_LINES
            pieces.append(text)
            offset = page.end
        assert offset == len(original)
        assert "".join(pieces) == original
    assert mapped.result is result
    assert mapped.result.events == (event,)
    assert mapped.result.runtime_events == (terminal,)
    assert mapped.result.terminal_event is terminal
    assert mapped.spans == (span,) and mapped.terminal_span is span


def test_output_pages_validate_membership_capture_bounds_and_line_limits():
    mapped = map_trace(_snapshot(()), TraceResult(RunResult(0, "a\nb\n", ""), ()))
    assert mapped.output_pages == (TraceOutputPage("stdout", 1, 0, 4),)
    unrelated = TraceOutputPage("stderr", 1, 0, 1)
    with pytest.raises(ValueError, match="does not belong"):
        output_page_text(mapped, unrelated)
    beyond_capture = TraceOutputPage("stdout", 1, 0, 5)
    with pytest.raises(ValueError, match="beyond"):
        output_page_text(replace(mapped, output_pages=(beyond_capture,)), beyond_capture)
    dense = TraceOutputPage("stdout", 1, 0, MAX_TRACE_OUTPUT_PAGE_LINES)
    forged = replace(
        mapped,
        result=TraceResult(RunResult(0, "\n" * MAX_TRACE_OUTPUT_PAGE_LINES, ""), ()),
        output_pages=(dense,),
    )
    with pytest.raises(ValueError, match="line bound"):
        output_page_text(forged, dense)
    with pytest.raises(ValueError, match="bounded offsets"):
        TraceOutputPage("stdout", 1, 0, MAX_TRACE_OUTPUT_PAGE_CHARS + 1)
    assert map_trace(_snapshot(()), TraceResult(RunResult(0, "", ""), ())).output_pages == ()
