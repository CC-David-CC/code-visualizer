"""Derived trace locations and bounded console previews, prepared away from Qt."""

from __future__ import annotations

import re
from bisect import bisect_left
from dataclasses import dataclass, field
from enum import StrEnum
from heapq import heappop, heappush
from typing import Literal

from code_visualizer.application.editor_preparation import EditorPreparedSnapshot
from code_visualizer.execution.runner import TraceEvent, TraceResult
from code_visualizer.generation.emitter import SourceSpan

MAX_TRACE_CONSOLE_CHARS = 64 * 1024
MAX_TRACE_OUTPUT_PREVIEW_CHARS = 16 * 1024
MAX_TRACE_LOCALS_PREVIEW_CHARS = 512
MAX_TRACE_EVENT_PREVIEW_CHARS = 1024
MAX_TRACE_OUTPUT_PAGE_CHARS = 64 * 1024
MAX_TRACE_OUTPUT_PAGE_LINES = 512
_LINE_BREAK = re.compile(r"\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]")
TRACE_PREVIEW_NOTICE = (
    "Trace console preview truncated; full captured data is retained. "
    "Select an event for its locals or an output page for its captured text."
)


class SourceSpanPolicy(StrEnum):
    FIRST = "first"
    NARROWEST = "narrowest"


@dataclass(frozen=True, slots=True)
class TraceOutputPage:
    channel: Literal["stdout", "stderr"]
    number: int
    start: int
    end: int

    def __post_init__(self) -> None:
        if (
            self.channel not in {"stdout", "stderr"}
            or any(type(value) is not int for value in (self.number, self.start, self.end))
            or self.number < 1
            or self.start < 0
            or not 0 < self.end - self.start <= MAX_TRACE_OUTPUT_PAGE_CHARS
        ):
            raise ValueError(
                "An output page requires a channel, positive number and bounded offsets"
            )

    @property
    def label(self) -> str:
        return f"{self.channel} · page {self.number} · characters {self.start + 1}-{self.end}"


@dataclass(frozen=True, slots=True)
class MappedTrace:
    snapshot: EditorPreparedSnapshot
    result: TraceResult
    spans: tuple[SourceSpan | None, ...]
    console: str
    terminal_span: SourceSpan | None = None
    output_pages: tuple[TraceOutputPage, ...] = ()


def _output_pages(result: TraceResult) -> tuple[TraceOutputPage, ...]:
    pages = []
    channels: tuple[Literal["stdout", "stderr"], ...] = ("stdout", "stderr")
    for channel in channels:
        text = result.run.stdout if channel == "stdout" else result.run.stderr
        start, number = 0, 1
        while start < len(text):
            end = min(start + MAX_TRACE_OUTPUT_PAGE_CHARS, len(text))
            # Keep CRLF together when a character boundary lands within the pair.
            if end < len(text) and text[end - 1 : end + 1] == "\r\n":
                end -= 1
            for count, separator in enumerate(_LINE_BREAK.finditer(text, start, end), start=1):
                if count == MAX_TRACE_OUTPUT_PAGE_LINES - 1:
                    end = separator.end()
                    break
            pages.append(TraceOutputPage(channel, number, start, end))
            start, number = end, number + 1
    return tuple(pages)


def output_page_text(mapped: MappedTrace, page: TraceOutputPage) -> str:
    """Read one complete bounded page from its retained capture, without re-execution."""
    if not isinstance(page, TraceOutputPage) or page not in mapped.output_pages:
        raise ValueError("The output page does not belong to this mapped trace")
    text = mapped.result.run.stdout if page.channel == "stdout" else mapped.result.run.stderr
    if not 0 <= page.start < page.end <= len(text):
        raise ValueError("The output page extends beyond its captured channel")
    value = text[page.start : page.end]
    if sum(1 for _ in _LINE_BREAK.finditer(value)) >= MAX_TRACE_OUTPUT_PAGE_LINES:
        raise ValueError("The output page exceeds its display line bound")
    return value


@dataclass(slots=True)
class _Preview:
    limit: int
    parts: list[str] = field(default_factory=list)
    length: int = 0
    truncated: bool = False

    @property
    def remaining(self) -> int:
        return self.limit - self.length

    def append(self, value: str) -> None:
        count = min(len(value), self.remaining)
        if count:
            self.parts.append(value[:count])
            self.length += count
        if count < len(value):
            self.truncated = True

    def text(self) -> str:
        return "".join(self.parts)


def _mapped_spans(
    source: tuple[SourceSpan, ...],
    requested_locations: tuple[tuple[str, int], ...],
    policy: SourceSpanPolicy,
) -> tuple[SourceSpan | None, ...]:
    requested: dict[str, set[int]] = {}
    for path, line in requested_locations:
        requested.setdefault(path, set()).add(line)
    ordered_lines = {path: sorted(lines) for path, lines in requested.items()}
    candidates: dict[str, list[tuple[int, tuple[int, int, int], int, SourceSpan]]] = {}
    for index, span in enumerate(source):
        lines = ordered_lines.get(span.file_path)
        if lines is not None:
            start, end = span.start_line, span.end_line
            first = bisect_left(lines, start)
            # Unvisited intervals cannot win either policy. Avoid allocating a
            # second whole-module index for a trace through a small part of it.
            if first == len(lines) or lines[first] > end:
                continue
            priority = (
                (end - start, start, index)
                if policy is SourceSpanPolicy.NARROWEST
                else (0, 0, index)
            )
            candidates.setdefault(span.file_path, []).append((start, priority, end, span))
    locations: dict[tuple[str, int], SourceSpan | None] = {}
    for path, lines in ordered_lines.items():
        ordered = sorted(candidates.get(path, ()), key=lambda item: (item[0], item[1]))
        cursor = 0
        active: list[tuple[tuple[int, int, int], int, SourceSpan]] = []
        for line in lines:
            while cursor < len(ordered) and ordered[cursor][0] <= line:
                _start, priority, end, span = ordered[cursor]
                heappush(active, (priority, end, span))
                cursor += 1
            # Both established policies use original order for their final tie.
            # Expired lower-priority entries are removed lazily.
            while active and active[0][1] < line:
                heappop(active)
            locations[path, line] = active[0][2] if active else None
    return tuple(locations[location] for location in requested_locations)


def _event_preview(event: TraceEvent, span: SourceSpan | None) -> _Preview:
    output = _Preview(MAX_TRACE_EVENT_PREVIEW_CHARS)
    output.append(f"{event.index:04d} ")
    output.append(event.event)
    output.append(" " * max(1, 10 - len(event.event)))
    output.append(event.file_path)
    output.append(f":{event.line}")
    if span is not None:
        output.append(" · ")
        output.append(span.field)
        output.append(" · ")
        output.append(span.semantic_id)
    if event.locals:
        local = _Preview(MAX_TRACE_LOCALS_PREVIEW_CHARS)
        for index, (name, value) in enumerate(event.locals):
            if index:
                local.append(", ")
            local.append(name)
            local.append("=")
            local.append(value)
            if local.truncated:
                break
        output.append(" · ")
        output.append(local.text())
        output.truncated |= local.truncated
    return output


def _console_preview(result: TraceResult, spans: tuple[SourceSpan | None, ...]) -> str:
    ending = _Preview(256)
    ending.append("Process ")
    ending.append(result.run.termination_reason)
    ending.append(f"; exit {result.run.return_code}; {result.run.duration_seconds:.3f}s\n")
    summary = ending.text()
    recorded_limit = (
        "Trace event limit reached; remaining events were not recorded.\n"
        if result.events_truncated
        else ""
    )
    reserve = len(summary) + len(recorded_limit) + len(TRACE_PREVIEW_NOTICE) + 2
    preview = _Preview(max(0, MAX_TRACE_CONSOLE_CHARS - reserve))
    preview.truncated = ending.truncated
    for title, text in (("stdout", result.run.stdout), ("stderr", result.run.stderr)):
        if text:
            output = text.rstrip()
            preview.append(f"--- {title} ---\n")
            preview.append(output[:MAX_TRACE_OUTPUT_PREVIEW_CHARS])
            preview.append("\n")
            preview.truncated |= len(output) > MAX_TRACE_OUTPUT_PREVIEW_CHARS
    preview.append("--- mapped trace ---\n")
    for event, span in zip(result.events, spans, strict=True):
        if not preview.remaining:
            preview.truncated = True
            break
        line = _event_preview(event, span)
        preview.append(line.text())
        preview.append("\n")
        preview.truncated |= line.truncated
    notice = TRACE_PREVIEW_NOTICE + "\n" if preview.truncated else ""
    body = preview.text()
    if notice and not body.endswith("\n"):
        body += "\n"
    return body + notice + recorded_limit + summary


def map_trace(
    snapshot: EditorPreparedSnapshot,
    result: TraceResult,
    *,
    policy: SourceSpanPolicy = SourceSpanPolicy.FIRST,
) -> MappedTrace:
    """Map every captured event once; only the human console preview is abbreviated."""
    if snapshot.generated is None:
        raise ValueError("Trace presentation requires its pinned generated files")
    if not isinstance(policy, SourceSpanPolicy):
        raise ValueError("Trace presentation requires an explicit source span policy")
    requested = tuple((event.file_path, event.line) for event in result.events)
    terminal = result.terminal_event.location if result.terminal_event is not None else None
    if terminal is not None:
        requested += ((terminal.file_path, terminal.line),)
    mapped = _mapped_spans(snapshot.generated.spans, requested, policy)
    spans = mapped[: len(result.events)]
    terminal_span = mapped[-1] if terminal is not None else None
    return MappedTrace(
        snapshot,
        result,
        spans,
        _console_preview(result, spans),
        terminal_span,
        _output_pages(result),
    )
