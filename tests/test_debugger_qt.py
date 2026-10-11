from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor

from code_visualizer.application.examples import python_modules_session
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.session import ProjectSession
from code_visualizer.execution import DebugEvent, DebugState, SourceLocation
from code_visualizer.ui_qt.document import UnifiedDocumentWidget


def test_source_and_diagram_navigation_share_stable_spans(qtbot) -> None:
    session = ProjectSession.new()
    try:
        diagram = session.authority.snapshot().documents[0]
        session.client.insert_drakon_atom(diagram.id, "assignment", 0)
        session.client.insert_drakon_atom(diagram.id, "output", 1, source="answer")
        current = session.authority.snapshot().documents[0]
        first, second = current.body.atoms
        document = UnifiedDocumentWidget(session.client, diagram.id)
        qtbot.addWidget(document)
        document.show()

        qtbot.waitUntil(lambda: document._generated is not None, timeout=10000)

        document.canvas.select_atom(first.id)
        document._canvas_selection_changed(first.id, "target")
        assert document._selected_span is not None
        assert document._selected_span.semantic_id == first.id
        assert document.code.textCursor().blockNumber() + 1 == document._selected_span.start_line

        generated = document._generated
        assert generated is not None
        second_span = next(span for span in generated.spans if span.semantic_id == second.id)
        cursor = QTextCursor(document.code.document().findBlockByNumber(second_span.start_line - 1))
        document.code.setTextCursor(cursor)
        assert document.canvas.selected_atom_ids() == (second.id,)
    finally:
        session.close()


def test_unified_document_debug_controls_pause_map_continue_and_finish(qtbot) -> None:
    session = ProjectSession.new()
    try:
        diagram = session.authority.snapshot().documents[0]
        session.client.insert_drakon_atom(
            diagram.id,
            "action",
            0,
            source="value = 40",
        )
        session.client.insert_drakon_atom(
            diagram.id,
            "output",
            1,
            source="value + 2",
        )
        current = session.authority.snapshot().documents[0]
        first = current.body.atoms[0]
        document = UnifiedDocumentWidget(session.client, diagram.id)
        qtbot.addWidget(document)
        document.show()

        qtbot.waitUntil(lambda: document._generated is not None, timeout=10000)

        document.canvas.select_atom(first.id)
        document.toggle_node_breakpoint()
        assert document._source_breakpoints
        document.debug_current()
        qtbot.waitUntil(lambda: "Paused" in document.debug_state_label.text(), timeout=5000)
        assert "Paused" in document.debug_state_label.text()
        assert document._debug_span is not None
        assert document.canvas.selected_atom_ids() == (first.id,)
        assert document.continue_button.isEnabled()

        document.debug_continue()
        qtbot.waitUntil(
            lambda: document._debugger.state in {DebugState.FINISHED, DebugState.FAILED},
            timeout=5000,
        )
        document._poll_debugger()
        assert document._debugger.state is DebugState.FINISHED
        assert "42" in document.console.toPlainText()
        assert not document.stop_button.isEnabled()
    finally:
        session.close()


def test_live_buttons_and_breakpoints_preserve_module_locations_and_stack_navigation(qtbot):
    session = python_modules_session()
    document = None
    try:
        project = session.authority.snapshot()
        main, helper = project.documents
        document = UnifiedDocumentWidget(session.client, main.id)
        qtbot.addWidget(document)
        document.show()
        qtbot.waitUntil(lambda: document._generated is not None, timeout=10000)
        events: list[DebugEvent] = []
        document.executionEvent.connect(lambda event, _identity: events.append(event))
        generated = document._execution_generated
        assert generated is not None
        main_span = next(
            span for span in generated.spans if span.semantic_id == main.body.atoms[0].id
        )
        helper_span = next(
            span for span in generated.spans if span.semantic_id == helper.body.atoms[0].id
        )
        assert main_span.file_path != helper_span.file_path

        qtbot.mouseClick(document.run_button, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: document.run_button.isEnabled(), timeout=10000)
        assert "Hello from two modules!" in document.console.toPlainText()
        qtbot.mouseClick(document.trace_button, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: document.trace_button.isEnabled(), timeout=10000)
        assert main_span.file_path in document.console.toPlainText()
        assert helper_span.file_path in document.console.toPlainText()
        assert any(event.file_path == helper_span.file_path for event in events)

        for span in (main_span, helper_span):
            document.source_file.setCurrentIndex(document.source_file.findData(span.file_path))
            document.code.setTextCursor(
                QTextCursor(document.code.document().findBlockByNumber(span.start_line - 1))
            )
            qtbot.mouseClick(document.source_breakpoint_button, Qt.MouseButton.LeftButton)
        assert document._source_breakpoints == {
            SourceLocation(main_span.file_path, main_span.start_line),
            SourceLocation(helper_span.file_path, helper_span.start_line),
        }
        events.clear()
        qtbot.mouseClick(document.debug_button, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: document._debugger.state is DebugState.PAUSED, timeout=10000)
        qtbot.waitUntil(lambda: document.continue_button.isEnabled())
        qtbot.mouseClick(document.continue_button, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(
            lambda: any(
                event.event == "paused" and event.file_path == helper_span.file_path
                for event in events
            ),
            timeout=10000,
        )
        assert document.source_file.currentData() == helper_span.file_path
        assert document._debug_span.semantic_id == helper_span.semantic_id
        main_frame = next(
            document.call_stack.topLevelItem(index)
            for index in range(document.call_stack.topLevelItemCount())
            if document.call_stack.topLevelItem(index).data(0, Qt.ItemDataRole.UserRole).file_path
            == main_span.file_path
        )
        document.call_stack.itemActivated.emit(main_frame, 0)
        assert document.source_file.currentData() == main_span.file_path
        assert (
            document.code.textCursor().blockNumber() + 1
            == main_frame.data(0, Qt.ItemDataRole.UserRole).line
        )
        qtbot.mouseClick(document.continue_button, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: document._debugger.state is DebugState.FINISHED, timeout=10000)
        assert session.authority.snapshot() == project
    finally:
        if document is not None:
            document.stop_current()
        session.close()


def test_invalid_edit_while_paused_preserves_pinned_files_spans_and_breakpoints(qtbot):
    session = ProjectSession.new()
    document = None
    try:
        diagram_id = session.authority.snapshot().documents[0].id
        session.client.insert_drakon_atom(diagram_id, "action", 0, source="value = 40")
        session.client.insert_drakon_atom(diagram_id, "output", 1, source="value + 2")
        before = session.authority.snapshot()
        first, second = before.documents[0].body.atoms
        document = UnifiedDocumentWidget(session.client, diagram_id)
        qtbot.addWidget(document)
        document.show()
        qtbot.waitUntil(lambda: document._generated is not None, timeout=10000)
        document.canvas.select_atom(first.id)
        qtbot.mouseClick(document.node_breakpoint_button, Qt.MouseButton.LeftButton)
        qtbot.mouseClick(document.debug_button, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: document.continue_button.isEnabled(), timeout=10000)
        pinned = document._execution_generated
        source_file = document._generated
        breakpoints = set(document._source_breakpoints)
        assert document._debug_span.semantic_id == first.id
        assert isinstance(
            session.client.set_drakon_text(diagram_id, first.id, "source", "broken("),
            CommandAccepted,
        )
        document.refresh(session.authority.snapshot())
        assert document._execution_generated is pinned
        assert document._generated is source_file
        assert document._source_breakpoints == breakpoints
        assert document._debug_span.semantic_id == first.id
        assert "value = 40" in document.code.toPlainText()
        assert "broken(" not in document.code.toPlainText()
        qtbot.mouseClick(document.step_over_button, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(
            lambda: (
                document._debug_span is not None and document._debug_span.semantic_id == second.id
            ),
            timeout=10000,
        )
        assert document._debug_span.file_path == source_file.path
        assert document._debugger.launch.project_revision == before.revision
        assert session.authority.revision > before.revision
        qtbot.mouseClick(document.continue_button, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: document._debugger.state is DebugState.FINISHED, timeout=10000)
        assert "42" in document.console.toPlainText()
    finally:
        if document is not None:
            document.stop_current()
        session.close()
