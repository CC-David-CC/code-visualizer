"""Generic domain traces use the established runtime plane in bounded Qt turns."""

from PySide6.QtCore import Qt

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.editor_preparation import EditorPreparedSnapshot
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.trace_presentation import SourceSpanPolicy, map_trace
from code_visualizer.execution import DebugEvent, DebugState, RunResult, TraceResult
from code_visualizer.execution.runner import TraceEvent
from code_visualizer.extensions.fsm import traffic_light_project
from code_visualizer.generation import generate_python_project
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.ui_qt.features.domain_workbench.widget import DomainWorkbenchWidget


def test_domain_trace_batches_retain_origins_and_detach_discards_pending_delivery(
    qtbot, monkeypatch
):
    authority = ProjectAuthority(traffic_light_project())
    kernel = ProjectKernel(authority)
    client = CodeVisualizerClient(authority, actor_id="domain-trace-proof")
    project = authority.snapshot()
    generated = generate_python_project(project)
    span = next(
        item
        for item in generated.spans
        if "traffic:red-green" in generated.origins.sources(item.semantic_id)
    )
    prepared = EditorPreparedSnapshot(
        "domain-trace", project.id, project.revision, "ready", "a" * 64, generated
    )
    locals_ = (("captured", "full captured value" * 300),)
    events = tuple(
        TraceEvent(index, "line", span.start_line, "main", locals_, file_path=span.file_path)
        for index in range(100)
    )
    runtime = tuple(
        DebugEvent(
            index,
            "paused",
            DebugState.PAUSED,
            span.start_line,
            "main",
            locals=locals_,
            execution_session_id="domain-trace",
            project_revision=project.revision,
            artifact_revision=project.revision,
            file_path=span.file_path,
        )
        for index in range(100)
    )
    terminal = DebugEvent(
        100,
        "finished",
        DebugState.FINISHED,
        span.start_line,
        "main",
        execution_session_id="domain-trace",
        project_revision=project.revision,
        artifact_revision=project.revision,
        file_path=span.file_path,
    )
    result = TraceResult(
        RunResult(0, "semantic output\n", "captured error\n" * 10000),
        events,
        runtime_events=runtime,
        terminal_event=terminal,
    )
    mapped = map_trace(prepared, result, policy=SourceSpanPolicy.NARROWEST)
    workbench = DomainWorkbenchWidget()
    qtbot.addWidget(workbench)
    workbench.attach(kernel, client)
    registrations = []
    original = kernel.runtime.register_origins

    def register(identity, origins):
        registrations.append(identity)
        return original(identity, origins)

    monkeypatch.setattr(kernel.runtime, "register_origins", register)
    delivered = []
    unsubscribe = kernel.runtime.subscribe(delivered.append, replay=False)
    try:
        workbench._trace_snapshot = prepared
        workbench._trace_completed(mapped)
        assert not delivered
        assert registrations == ["domain-trace"]
        assert workbench._retained_trace.result is result
        qtbot.waitUntil(lambda: workbench._trace_delivery is None, timeout=5000)
        assert [state.event_sequence for state in delivered] == list(range(101))
        assert all("traffic:red-green" in state.origin_ids for state in delivered)
        assert workbench.status.text() == "semantic output\n"
        assert "traffic:red-green" in kernel.selection.state.semantic_ids
        pages = []
        for page in mapped.output_pages:
            if page.channel == "stderr":
                workbench.trace_event.setCurrentIndex(workbench.trace_event.findData(page))
                pages.append(workbench.trace_details.toPlainText())
        assert "".join(pages) == result.run.stderr
        workbench.trace_event.setCurrentIndex(workbench.trace_event.findData(0))
        assert locals_[0][1] in workbench.trace_details.toPlainText()
        assert workbench.projections
        assert any(
            workbench.table.item(row, 0).data(Qt.ItemDataRole.UserRole).semantic_id
            == "traffic:red-green"
            for row in range(workbench.table.rowCount())
        )
        workbench._trace_snapshot = prepared
        workbench._trace_completed(mapped)
        count = len(delivered)
        workbench.attach(None, None)
        qtbot.wait(50)
        assert len(delivered) == count
        assert workbench._retained_trace is None
        workbench._trace_completed(mapped)
        assert workbench._retained_trace is None
    finally:
        unsubscribe()
        workbench.attach(None, None)
        kernel.close()
        client.close()
