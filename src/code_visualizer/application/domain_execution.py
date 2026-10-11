"""Workbench execution through the existing Python and revision-pinned runtime planes."""

from __future__ import annotations

from dataclasses import dataclass

from code_visualizer.application.editor_preparation import EditorPreparedSnapshot
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.execution import (
    DebugEvent,
    DebugLaunch,
    DebugSession,
    RuntimeBindingSpec,
    TraceResult,
)
from code_visualizer.execution import (
    trace_project as trace_generated_project,
)
from code_visualizer.execution.runtime import program_binding_specs
from code_visualizer.generation.build import BuildSnapshot, prepare_build
from code_visualizer.generation.emitter import GeneratedProject, SourceSpan
from code_visualizer.generation.python import prepare_python_project


@dataclass(frozen=True, slots=True)
class ExecutionSnapshot:
    project_id: str
    revision: int
    build: BuildSnapshot
    generated: GeneratedProject
    binding_specs: tuple[RuntimeBindingSpec, ...]


def build_project(kernel: ProjectKernel, *, model_id: str | None = None) -> BuildSnapshot:
    return prepare_build(
        kernel.authority.snapshot(), kernel.extensions, entrypoint_model_id=model_id
    )


def execution_snapshot(kernel: ProjectKernel, *, model_id: str | None = None) -> ExecutionSnapshot:
    authored = kernel.authority.snapshot()
    build, generated = prepare_python_project(
        authored, extensions=kernel.extensions, entrypoint_model_id=model_id
    )
    program = build.project.program_model
    return ExecutionSnapshot(
        authored.id,
        authored.revision,
        build,
        generated,
        program_binding_specs(program),
    )


def _record(
    kernel: ProjectKernel, snapshot: ExecutionSnapshot | EditorPreparedSnapshot, event: DebugEvent
) -> None:
    assert snapshot.generated is not None
    if snapshot.generated.origins is not None:
        kernel.runtime.register_origins(event.execution_session_id, snapshot.generated.origins)
    spans = tuple(
        span
        for span in snapshot.generated.spans
        if span.file_path == event.file_path and span.start_line <= event.line <= span.end_line
    )
    span = (
        min(spans, key=lambda item: (item.end_line - item.start_line, item.start_line))
        if spans
        else None
    )
    record_mapped_trace_event(kernel, snapshot, event, span)


def record_mapped_trace_event(
    kernel: ProjectKernel,
    snapshot: ExecutionSnapshot | EditorPreparedSnapshot,
    event: DebugEvent,
    span: SourceSpan | None,
) -> None:
    """Record an already mapped event on the caller's thread using the one runtime plane."""
    state = kernel.runtime.record(event, span.semantic_id if span is not None else None)
    if state.active_ids and kernel.revision == snapshot.revision:
        kernel.selection.select(
            state.active_ids,
            revision=snapshot.revision,
            source="runtime.workbench",
            execution_session_id=event.execution_session_id,
        )


def trace_project(kernel: ProjectKernel, *, model_id: str | None = None) -> TraceResult:
    snapshot = execution_snapshot(kernel, model_id=model_id)
    result = trace_generated_project(
        snapshot.generated,
        project_revision=snapshot.revision,
        artifact_revision=snapshot.revision,
        binding_specs=snapshot.binding_specs,
    )
    for event in result.runtime_events:
        _record(kernel, snapshot, event)
    if result.terminal_event is not None:
        _record(kernel, snapshot, result.terminal_event)
    return result


@dataclass(slots=True)
class WorkbenchDebugSession:
    kernel: ProjectKernel
    snapshot: ExecutionSnapshot | EditorPreparedSnapshot
    debugger: DebugSession

    def poll_events(self, *, maximum: int = 100) -> tuple[DebugEvent, ...]:
        events = self.debugger.poll_events(maximum=maximum)
        for event in events:
            _record(self.kernel, self.snapshot, event)
        return events

    def wait_event(self, timeout: float = 5.0) -> DebugEvent:
        event = self.debugger.wait_event(timeout)
        _record(self.kernel, self.snapshot, event)
        return event

    def stop(self) -> None:
        self.debugger.stop()
        self.poll_events()

    def step_into(self) -> None:
        self.debugger.step_into()

    def step_over(self) -> None:
        self.debugger.step_over()

    def step_out(self) -> None:
        self.debugger.step_out()

    def continue_execution(self) -> None:
        self.debugger.continue_execution()


def debug_project(kernel: ProjectKernel, *, model_id: str | None = None) -> WorkbenchDebugSession:
    snapshot = execution_snapshot(kernel, model_id=model_id)
    return debug_prepared(kernel, snapshot)


def debug_prepared(
    kernel: ProjectKernel, snapshot: ExecutionSnapshot | EditorPreparedSnapshot
) -> WorkbenchDebugSession:
    """Start the established debugger with already admitted emitted files and maps."""
    assert snapshot.generated is not None
    debugger = DebugSession()
    launch = DebugLaunch(
        project=snapshot.generated,
        project_revision=snapshot.revision,
        artifact_revision=snapshot.revision,
        binding_specs=snapshot.binding_specs,
    )
    kernel.runtime.mark_starting(launch.execution_session_id, snapshot.revision, snapshot.revision)
    if snapshot.generated.origins is not None:
        kernel.runtime.register_origins(launch.execution_session_id, snapshot.generated.origins)
    debugger.start(launch)
    return WorkbenchDebugSession(kernel, snapshot, debugger)
