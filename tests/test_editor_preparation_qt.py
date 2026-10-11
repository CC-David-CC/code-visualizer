"""Actual editor buttons prepare in the fixed child and consume pinned real files."""

import gc
import json
from dataclasses import replace
from itertools import pairwise
from threading import Event
from time import perf_counter

import pytest
from PySide6.QtCore import Qt, QTimer

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.editor_preparation import EditorPreparation, EditorPreparedSnapshot
from code_visualizer.application.project_factory import create_default_project
from code_visualizer.application.scale_fixture import build_scale_project
from code_visualizer.application.session import ProjectSession
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.serialization import project_to_data
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.ui_qt.document import UnifiedDocumentWidget
from code_visualizer.ui_qt.editor_preparation import EditorAction, QtEditorPreparation


@pytest.mark.parametrize("action", tuple(EditorAction))
def test_only_preview_coalesces_authority_changes_before_dispatch(qtbot, monkeypatch, action):
    original = create_default_project()
    # Different branch contents can share both project identity and revision.
    current = replace(original, title="Another branch at the same revision")
    adapter = QtEditorPreparation(current_project=lambda: current)
    dispatched = []

    def submit(project, **kwargs):
        dispatched.append(project)
        return "prepared"

    monkeypatch.setattr(adapter._preparation, "submit", submit)
    try:
        adapter.request(original, action)
        if action is EditorAction.PREVIEW:
            qtbot.waitUntil(lambda: bool(dispatched))
        assert dispatched == [current if action is EditorAction.PREVIEW else original]
        if action is EditorAction.PREVIEW:
            adapter.request(current, action)
            qtbot.wait(120)
            assert dispatched == [current]
    finally:
        adapter.close()


def test_completed_notification_cannot_stop_a_reentrantly_submitted_request(qtbot, monkeypatch):
    project = create_default_project()
    adapter = QtEditorPreparation()
    current = [EditorPreparedSnapshot("old", project.id, project.revision, "ready")]
    monkeypatch.setattr(adapter._preparation, "snapshot", lambda: current[0])
    monkeypatch.setattr(adapter._preparation, "submit", lambda *args, **kwargs: "new")
    delivered = []

    def receive(view):
        delivered.append(view.request_id)
        if view.request_id == "old":
            adapter.request(project, EditorAction.RUN)

    adapter.changed.connect(receive)
    adapter.request_id = "old"
    try:
        adapter.poll()
        assert adapter.request_id == "new"
        assert adapter.pending
        current[0] = EditorPreparedSnapshot("new", project.id, project.revision, "ready")
        adapter.poll()
        assert delivered == ["old", "new"]
        assert not adapter.pending
    finally:
        adapter.close()


@pytest.mark.parametrize("action", (EditorAction.RUN, EditorAction.TRACE, EditorAction.DEBUG))
def test_stop_during_preparation_reports_cancellation_and_cannot_start_execution(
    qtbot, monkeypatch, action
):
    from code_visualizer.generation import generate_python_project

    project = create_default_project()
    authority = ProjectAuthority(project)
    client = CodeVisualizerClient(authority, actor_id="preparation-stop-proof")
    project = authority.snapshot()
    generated = generate_python_project(project)
    started, release, finished = Event(), Event(), Event()

    def late_prepare(self, request):
        started.set()
        assert release.wait(5)
        self._publish(request, status="ready", source_digest="a" * 64, generated=generated)
        finished.set()

    monkeypatch.setattr(EditorPreparation, "_prepare", late_prepare)
    document = UnifiedDocumentWidget(client, project.documents[0].id)
    qtbot.addWidget(document)
    document.show()
    execution = []
    for runner, name in (
        (document._run_session, "start_project"),
        (document._run_session, "start_project_trace"),
        (document._debugger, "start"),
    ):
        monkeypatch.setattr(runner, name, lambda *args, **kwargs: execution.append(args))
    try:
        qtbot.mouseClick(getattr(document, f"{action.value}_button"), Qt.MouseButton.LeftButton)
        qtbot.waitUntil(started.is_set)
        assert document._preparation.pending
        assert not execution
        qtbot.mouseClick(document.stop_button, Qt.MouseButton.LeftButton)
        assert document.console.toPlainText() == (
            f"{action.value.title()} preparation stopped by the user.\n"
        )
        assert not document._preparation.pending
        assert document.run_button.isEnabled()
        assert not document.stop_button.isEnabled()
        release.set()
        qtbot.waitUntil(finished.is_set)
        document._preparation.poll()
        assert not execution
        assert document._preparation._preparation.snapshot().status == "cancelled"
        assert client.snapshot() is project
    finally:
        release.set()
        document._stop_child_processes()
        document._preparation._preparation.close(wait=True)
        client.close()


def test_real_run_and_trace_buttons_prepare_without_blocking_gui(qtbot, tmp_path):
    project = build_scale_project(500, atoms_per_diagram=20)
    authority = ProjectAuthority(project)
    client = CodeVisualizerClient(authority, actor_id="editor-preparation-proof")
    project = authority.snapshot()
    source_bytes = len(canonical_data_bytes(project_to_data(project)))
    assert source_bytes > 2 * 1024 * 1024
    document = UnifiedDocumentWidget(client, project.documents[0].id)
    qtbot.addWidget(document)
    document.show()
    pulses = []
    timer = QTimer(document)
    timer.setInterval(10)
    timer.timeout.connect(lambda: pulses.append(perf_counter()))
    receipts = []
    prepared_actions = []
    collections = []

    def collected(phase, info):
        collections.append((perf_counter(), phase, info["generation"]))

    gc.callbacks.append(collected)
    try:
        for action, button in (("run", document.run_button), ("trace", document.trace_button)):
            pulses.clear()
            timer.start()
            qtbot.wait(50)
            started = perf_counter()
            qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
            acknowledgement = perf_counter() - started
            assert not document.run_button.isEnabled()
            # Liveness follows the existing preparation lifecycle. Throughput is
            # recorded separately from the unchanged UI response-time gates.
            qtbot.waitUntil(document.run_button.isEnabled, timeout=120000)
            completion = perf_counter() - started
            qtbot.wait(30)
            timer.stop()
            assert "blocked:" not in document.console.toPlainText(), document.console.toPlainText()
            assert document._prepared_revision == project.revision
            assert authority.snapshot() is project
            assert len(pulses) > 2
            gap = max(right - left for left, right in pairwise(pulses))
            prepared = document._preparation._preparation.snapshot()
            assert prepared is not None and prepared.status == "ready"
            prepared_actions.append(prepared)
            receipts.append(
                {
                    "action": action,
                    "canonical_source_bytes": source_bytes,
                    "source_digest": prepared.source_digest,
                    "request_id": prepared.request_id,
                    "pulses": tuple(pulses),
                    "acknowledgement_seconds": acknowledgement,
                    "completion_seconds": completion,
                    "heartbeat_max_gap_seconds": gap,
                }
            )
            assert acknowledgement <= 0.2, receipts[-1]
            assert gap <= 0.25, receipts[-1]
        assert "--- mapped trace ---" in document.console.toPlainText()
        assert prepared_actions[0].request_id != prepared_actions[1].request_id
        assert prepared_actions[0].generated is prepared_actions[1].generated
        assert prepared_actions[0].binding_specs is prepared_actions[1].binding_specs
        assert prepared_actions[0].source_digest == prepared_actions[1].source_digest
        assert "app/main.py" in document.console.toPlainText()
        assert (
            document._execution_generated.invocation.callable_id
            == project.program_model.functions[0].id
        )
        (tmp_path / "editor-preparation-responsiveness.json").write_text(
            json.dumps(receipts, indent=2)
        )
    finally:
        gc.callbacks.remove(collected)
        timer.stop()
        pending = document._preparation._preparation.snapshot()
        (tmp_path / "editor-preparation-samples.json").write_text(
            json.dumps(
                {
                    "receipts": receipts,
                    "current_pulses": pulses,
                    "garbage_collections": collections,
                    "canonical_source_bytes": source_bytes,
                    "preparation": {
                        "request_id": pending.request_id,
                        "status": pending.status,
                        "source_digest": pending.source_digest,
                        "diagnostic": pending.diagnostic,
                    }
                    if pending is not None
                    else None,
                    "run_active": document._run_session.is_active,
                    "prepared_revision": document._prepared_revision,
                    "console": document.console.toPlainText(),
                }
            )
        )
        document._stop_child_processes()
        client.close()


def test_author_edit_cancels_pending_run_and_only_current_preview_can_arrive(qtbot, monkeypatch):
    session = ProjectSession.new()
    diagram = session.authority.snapshot().documents[0]
    session.client.insert_drakon_atom(diagram.id, "output", 0, source="'must not run'")
    document = UnifiedDocumentWidget(session.client, diagram.id)
    qtbot.addWidget(document)
    document.show()
    calls = []
    original = document._run_session.start_project

    def started(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(document._run_session, "start_project", started)
    try:
        qtbot.mouseClick(document.run_button, Qt.MouseButton.LeftButton)
        old_request = document._preparation.request_id
        session.client.rename_project("Changed while preparing")
        current = session.authority.snapshot()
        document.refresh(current)
        qtbot.waitUntil(lambda: document._prepared_revision == current.revision, timeout=15000)
        assert document._preparation.request_id != old_request
        assert not calls
        assert not document._run_session.is_active
        assert "must not run" in document.code.toPlainText()
        assert document.console.toPlainText() != "must not run\n"
    finally:
        document._stop_child_processes()
        session.close()


def test_trace_preview_is_bounded_but_every_event_and_full_selected_details_remain(qtbot):
    from code_visualizer.application.trace_presentation import (
        MAX_TRACE_CONSOLE_CHARS,
        TRACE_PREVIEW_NOTICE,
        map_trace,
    )
    from code_visualizer.execution import DebugEvent, DebugState, RunResult, TraceResult
    from code_visualizer.execution.runner import TraceEvent
    from code_visualizer.generation import generate_python_project

    session = ProjectSession.new()
    project = session.authority.snapshot()
    diagram = project.documents[0]
    generated = generate_python_project(project)
    span = next(item for item in generated.spans if item.presentation_id == diagram.id)
    snapshot = EditorPreparedSnapshot(
        "trace-proof", project.id, project.revision, "ready", "a" * 64, generated
    )
    full_value = "retained-value-" * 600
    events = tuple(
        TraceEvent(
            index,
            "line",
            span.start_line,
            "main",
            (("value", full_value),),
            file_path=span.file_path,
        )
        for index in range(300)
    )
    runtime = tuple(
        DebugEvent(
            index,
            "paused",
            DebugState.PAUSED,
            line=span.start_line,
            function="main",
            locals=event.locals,
            file_path=span.file_path,
            project_revision=project.revision,
            artifact_revision=project.revision,
        )
        for index, event in enumerate(events)
    )
    stdout = "semantic output\n" + "x\n" * 40000
    stderr = "captured error\n" * 10000
    result = TraceResult(RunResult(0, stdout, stderr), events, runtime_events=runtime)
    mapped = map_trace(snapshot, result)
    document = UnifiedDocumentWidget(session.client, diagram.id)
    qtbot.addWidget(document)
    document._preparation.cancel()
    document._set_generated(generated)
    document._trace_snapshot = snapshot
    document._execution_controls(True)
    delivered = []
    document.executionEvent.connect(lambda event, identity: delivered.append((event, identity)))
    try:
        document._trace_completed(mapped)
        assert not delivered  # No synchronous whole-trace publication on Qt.
        assert document._retained_trace.result is result
        assert document._retained_trace.result.runtime_events is runtime
        assert len(document.console.toPlainText()) <= MAX_TRACE_CONSOLE_CHARS
        assert TRACE_PREVIEW_NOTICE in document.console.toPlainText()
        qtbot.waitUntil(document.run_button.isEnabled, timeout=3000)
        assert tuple(event for event, _ in delivered) == runtime
        assert all(identity == span.semantic_id for _, identity in delivered)
        for channel, expected in (("stdout", stdout), ("stderr", stderr)):
            pages = []
            for page in mapped.output_pages:
                if page.channel == channel:
                    document.trace_event.setCurrentIndex(document.trace_event.findData(page))
                    pages.append(document.console.toPlainText())
            assert "".join(pages) == expected
        document.trace_event.setCurrentIndex(document.trace_event.findData(0))
        assert document.locals.topLevelItem(0).text(1) == full_value
        assert document._generated.path == span.file_path
        assert document.code.textCursor().blockNumber() + 1 == span.start_line
        session.client.rename_project("A later author revision")
        current = session.authority.snapshot()
        selected = []
        document.atomSelected.connect(lambda *args: selected.append(args))
        document.trace_event.setCurrentIndex(document.trace_event.findData(1))
        assert not selected
        assert f"current revision {current.revision}" in document.debug_state_label.text()
        assert session.authority.snapshot() is current
        assert document._retained_trace.result is result
    finally:
        document._stop_child_processes()
        session.close()
