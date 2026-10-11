from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QTextCursor

from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.semantic_text import render_semantic_text
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.drakon import Output
from code_visualizer.domain.semantic import ProjectionKind
from code_visualizer.ui_qt.main_window import CloseDecision, MainWindow


def _settings(path: Path) -> QSettings:
    return QSettings(str(path / "settings.ini"), QSettings.Format.IniFormat)


def test_semantic_text_projection_is_deterministic_and_identity_mapped() -> None:
    session = ProjectSession.new()
    try:
        diagram = session.authority.snapshot().documents[0]
        inserted = session.client.insert_drakon_atom(
            diagram.id,
            "output",
            0,
            source='"hello"',
        )
        assert isinstance(inserted, CommandAccepted)
        operation_id = session.authority.snapshot().documents[0].body.atoms[0].id
        projection = session.kernel.queries.projection(ProjectionKind.CONTROL, diagram.id)
        first = render_semantic_text(projection)
        second = render_semantic_text(projection)
        assert first == second
        assert "objects\n" in first.source
        assert "relationships\n" in first.source
        assert operation_id in first.line_semantic_ids
        assert len(first.source.splitlines()) == len(first.line_semantic_ids)
    finally:
        session.close()


def test_semantic_text_ui_edits_the_same_operation_and_shares_selection(qtbot, tmp_path) -> None:
    window = MainWindow(
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()
    assert window.session is not None
    diagram = window.session.authority.snapshot().documents[0]
    inserted = window.session.client.insert_drakon_atom(
        diagram.id,
        "output",
        0,
        source='"before"',
    )
    assert isinstance(inserted, CommandAccepted)
    operation = window.session.authority.snapshot().documents[0].body.atoms[0]
    assert isinstance(operation, Output)

    visualizer = window.semantic_visualizer
    visualizer.select_projection(ProjectionKind.CONTROL)
    visualizer.projection_tabs.setCurrentWidget(visualizer.semantic_text)
    window.session.kernel.selection.select(
        (operation.id,),
        revision=window.session.authority.revision,
        source="test.semantic_text",
    )
    qtbot.waitUntil(lambda: visualizer.semantic_text.apply_button.isEnabled())
    assert visualizer.semantic_text.field_choice.currentText() == "Expression"
    assert visualizer.semantic_text.field_editor.toPlainText() == "'before'"

    visualizer.semantic_text.field_editor.setPlainText('"after"')
    qtbot.mouseClick(visualizer.semantic_text.apply_button, Qt.MouseButton.LeftButton)
    updated = window.session.authority.snapshot().documents[0].body.atoms[0]
    assert isinstance(updated, Output)
    assert updated.expression == "'after'"

    projection = visualizer.semantic_text._text_projection
    assert projection is not None
    line = projection.line_semantic_ids.index(operation.id)
    visualizer.semantic_text.outline.setTextCursor(
        QTextCursor(visualizer.semantic_text.outline.document().findBlockByNumber(0))
    )
    block = visualizer.semantic_text.outline.document().findBlockByNumber(line)
    visualizer.semantic_text.outline.setTextCursor(QTextCursor(block))
    assert window.session.kernel.selection.state.primary == operation.id
    assert window.session.kernel.selection.state.source == "ui.semantic_text"
    window.close()
