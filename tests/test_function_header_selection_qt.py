"""Intrinsic headers bridge presentation selection to canonical callable source."""

from dataclasses import replace

import pytest
from PySide6.QtCore import QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QPalette, QTextCursor
from PySide6.QtWidgets import QGraphicsPathItem

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.examples import example_session
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.common import DocumentKind
from code_visualizer.domain.drakon import find_atom_location
from code_visualizer.domain.program_signatures import ParameterSpec
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.ui_qt.document import UnifiedDocumentWidget
from code_visualizer.ui_qt.main_window import CloseDecision, MainWindow


@pytest.fixture
def session():
    value = example_session("values")
    try:
        yield value
    finally:
        value.close()


def _open_document(qtbot, session):
    diagram = session.authority.snapshot().documents[0]
    document = UnifiedDocumentWidget(session.client, diagram.id)
    qtbot.addWidget(document)
    document.resize(1100, 800)
    document.show()
    qtbot.waitUntil(lambda: document._generated is not None, timeout=10000)
    document.canvas.fit_content()
    return document, diagram


def _node_position(canvas, object_id):
    node = next(node for node in canvas.layout_scene.nodes if node.object_id == object_id)
    return canvas.mapFromScene(QPointF(node.bounds.center.x, node.bounds.center.y))


def _click_node(qtbot, document, object_id):
    qtbot.mouseClick(
        document.canvas.viewport(),
        Qt.MouseButton.LeftButton,
        pos=_node_position(document.canvas, object_id),
    )


def _highlighted_source(document):
    selections = document.code.extraSelections()
    assert len(selections) == 1
    return selections[0].cursor.selectedText().replace("\u2029", "\n")


def _assert_header_selected(document, diagram):
    assert document.canvas.selected_object_ids() == (diagram.header.id,)
    assert document.canvas.selected_atom_ids() == ()
    group = document.canvas._node_groups[diagram.header.id]
    assert group.isSelected()
    outline = next(child for child in group.childItems() if isinstance(child, QGraphicsPathItem))
    assert outline.pen().color() == document.canvas.palette().color(QPalette.ColorRole.Highlight)
    assert outline.pen().widthF() == 3.5


@pytest.mark.parametrize("distinct_view_id", (False, True))
def test_mouse_click_header_selects_whole_function_and_publishes_callable(
    qtbot, session, distinct_view_id
):
    if distinct_view_id:
        project = session.authority.snapshot()
        authority = ProjectAuthority(
            replace(
                project,
                documents=(replace(project.documents[0], id="view_values"),),
                drakon_views=(replace(project.drakon_views[0], document_id="view_values"),),
            )
        )
        independent = ProjectSession(
            authority, CodeVisualizerClient(authority, actor_id="header-test"), None, -1
        )
    else:
        independent = session
    try:
        document, diagram = _open_document(qtbot, independent)
        view = independent.authority.snapshot().drakon_views[0]
        generated = document._execution_generated
        original_spans = generated.spans
        selected = []
        document.semanticSelectionChanged.connect(selected.append)

        _click_node(qtbot, document, diagram.header.id)

        _assert_header_selected(document, diagram)
        assert selected[-1] == (view.function_id,)
        assert diagram.header.id != view.function_id
        assert _highlighted_source(document) == (
            "def main():\n    result = 6 * 7\n    print(f'The answer is {result}')"
        )
        assert generated.spans == original_spans
        signature = next(span for span in generated.spans if span.field == "signature")
        assert signature.semantic_id == view.function_id
        assert signature.start_line == signature.end_line
        assert all(span.semantic_id != diagram.header.id for span in generated.spans)
    finally:
        if distinct_view_id:
            independent.close()


def test_source_cursor_on_signature_visibly_selects_header(qtbot, session):
    document, diagram = _open_document(qtbot, session)
    _click_node(qtbot, document, diagram.body.atoms[-1].id)
    signature = next(span for span in document._generated.spans if span.field == "signature")

    document.code.setTextCursor(
        QTextCursor(document.code.document().findBlockByNumber(signature.start_line - 1))
    )

    _assert_header_selected(document, diagram)
    assert _highlighted_source(document) == document.code.toPlainText().rstrip()
    assert document.code.textCursor().blockNumber() + 1 == signature.start_line


def test_body_click_after_header_highlights_only_assignment(qtbot, session):
    document, diagram = _open_document(qtbot, session)
    _click_node(qtbot, document, diagram.header.id)

    _click_node(qtbot, document, diagram.body.atoms[0].id)

    assert document.canvas.selected_atom_ids() == (diagram.body.atoms[0].id,)
    assert document.canvas.selected_object_ids() == (diagram.body.atoms[0].id,)
    assert _highlighted_source(document) == "    result = 6 * 7"


def test_click_selected_header_reveals_function_after_browsing_another_file(qtbot, session):
    document, diagram = _open_document(qtbot, session)
    _click_node(qtbot, document, diagram.header.id)
    expected = _highlighted_source(document)
    document.source_file.setCurrentIndex(
        document.source_file.findData(document._execution_generated.launcher_path)
    )
    assert document.code.extraSelections() == []

    _click_node(qtbot, document, diagram.header.id)

    _assert_header_selected(document, diagram)
    assert _highlighted_source(document) == expected


def test_header_selection_cannot_delete_reorder_or_drag_body(qtbot, tmp_path, session):
    window = MainWindow(
        settings=QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
        close_decision=lambda _session: CloseDecision.DISCARD,
    )
    qtbot.addWidget(window)
    window.show()
    window._install_session(session)
    document = window.documents.currentWidget()
    qtbot.waitUntil(lambda: document._generated is not None, timeout=10000)
    before = session.authority.snapshot()
    diagram = before.documents[0]
    _click_node(qtbot, document, diagram.header.id)

    assert session.kernel.selection.state.semantic_ids == (before.drakon_views[0].function_id,)
    assert window._structural_selection() is None
    assert find_atom_location(diagram.body, diagram.header.id) is None
    window._remove_selection()
    window._move_selection_by(1)
    window._move_selection_by(-1)
    window._duplicate_selection()
    moves = []
    document.canvas.moveRequested.connect(lambda *args: moves.append(args))
    start = _node_position(document.canvas, diagram.header.id)
    qtbot.mousePress(document.canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(document.canvas.viewport(), start + QPoint(30, 35))
    assert not document.canvas.drag_ghost_visible
    qtbot.mouseRelease(
        document.canvas.viewport(), Qt.MouseButton.LeftButton, pos=start + QPoint(30, 35)
    )

    assert moves == []
    assert session.authority.snapshot() == before
    _assert_header_selected(document, diagram)
    document.canvas.select_atoms((diagram.header.id,))
    assert document.canvas.selected_object_ids() == ()
    session.kernel.selection.select((before.drakon_views[0].function_id,), source="test")
    _assert_header_selected(document, diagram)


def test_complex_function_selection_includes_decorators_docstring_and_body_only(qtbot, session):
    diagram = session.authority.snapshot().documents[0]
    assert isinstance(
        session.client.replace_function_spec(
            diagram.id,
            replace(
                diagram.header.function,
                parameters=(ParameterSpec("count", annotation="int", default="7"),),
                decorators=("lambda function: function", "lambda function: function"),
                docstring="Calculate an answer.\nKeep the complete function selected.",
            ),
        ),
        CommandAccepted,
    )
    assert isinstance(
        session.client.insert_drakon_atom(diagram.id, "action", 2, source="result += count"),
        CommandAccepted,
    )
    assert isinstance(
        session.client.create_diagram(DocumentKind.DRAKON, "Neighbor", identifier="neighbor"),
        CommandAccepted,
    )
    document, diagram = _open_document(qtbot, session)
    source = document.code.toPlainText()
    assert "def neighbor():" in source
    expected = source[source.index("@lambda") : source.index("    result += count")]
    expected += "    result += count"

    _click_node(qtbot, document, diagram.header.id)

    assert _highlighted_source(document) == expected
    assert "def main(count: int = 7):" in expected
    assert "Keep the complete function selected." in expected
    signature = next(
        span
        for span in document._generated.spans
        if span.field == "signature"
        and source.splitlines()[span.start_line - 1].startswith("def main")
    )
    document.code.setTextCursor(
        QTextCursor(document.code.document().findBlockByNumber(signature.start_line - 1))
    )
    _assert_header_selected(document, diagram)
    assert _highlighted_source(document) == expected
    assert document.code.textCursor().blockNumber() + 1 == signature.start_line


def test_header_selection_tracks_regenerated_function_extent(qtbot, session):
    document, diagram = _open_document(qtbot, session)
    _click_node(qtbot, document, diagram.header.id)
    assert isinstance(
        session.client.insert_drakon_atom(diagram.id, "action", 2, source="result += 1"),
        CommandAccepted,
    )

    document.refresh(session.authority.snapshot())
    qtbot.waitUntil(lambda: "result += 1" in document.code.toPlainText(), timeout=10000)

    _assert_header_selected(document, diagram)
    assert _highlighted_source(document).endswith("    result += 1")


def test_empty_function_header_includes_generated_pass(qtbot):
    session = ProjectSession.new()
    try:
        document, diagram = _open_document(qtbot, session)
        _click_node(qtbot, document, diagram.header.id)
        _assert_header_selected(document, diagram)
        assert _highlighted_source(document) == "def main():\n    pass"
    finally:
        session.close()
