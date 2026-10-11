"""Ownership selection exercised through real saved example diagrams and Qt input."""

import ast
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QPalette, QTextCursor
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.drakon import Parallel, Select, SelectMode, Silhouette, Try
from code_visualizer.domain.drakon_selection import selection_objects, selection_ownership
from code_visualizer.persistence import ProjectStore
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.ui_qt.document import UnifiedDocumentWidget
from code_visualizer.ui_qt.main_window import CloseDecision, MainWindow

ROOT = Path(__file__).resolve().parents[1]


def _saved_session(name):
    project = ProjectStore(ROOT / "examples" / "projects" / name).load()
    authority = ProjectAuthority(project)
    return ProjectSession(
        authority, CodeVisualizerClient(authority, actor_id="selection-test"), None, -1
    )


@pytest.fixture
def select_session():
    session = _saved_session("05-select-match")
    try:
        yield session
    finally:
        session.close()


def _document(qtbot, session):
    diagram = session.authority.snapshot().documents[0]
    document = UnifiedDocumentWidget(session.client, diagram.id)
    qtbot.addWidget(document)
    document.resize(1400, 1100)
    document.show()
    qtbot.waitUntil(lambda: document._generated is not None, timeout=10000)
    document.canvas.fit_content()
    return document, diagram


def _point(canvas, identity):
    node = next(node for node in canvas.layout_scene.nodes if node.object_id == identity)
    return canvas.mapFromScene(QPointF(node.bounds.center.x, node.bounds.center.y))


def _click(qtbot, document, identity):
    qtbot.mouseClick(
        document.canvas.viewport(), Qt.MouseButton.LeftButton, pos=_point(document.canvas, identity)
    )


def _visible_selection(document, identity):
    assert document.canvas.selected_object_ids() == (identity,)
    group = document.canvas._node_groups[identity]
    assert group.isSelected()
    outline = next(child for child in group.childItems() if isinstance(child, QGraphicsPathItem))
    assert outline.pen().widthF() == 3.5
    assert outline.pen().color() == document.canvas.palette().color(QPalette.ColorRole.Highlight)


def _highlight(document):
    selections = document.code.extraSelections()
    assert len(selections) == 1
    cursor = selections[0].cursor
    return cursor.selectedText().replace("\u2029", "\n"), cursor.document().findBlock(
        cursor.selectionStart()
    ).blockNumber() + 1


def _match_targets(document, diagram):
    match = next(
        atom
        for atom in diagram.body.atoms
        if isinstance(atom, Select) and atom.mode is SelectMode.MATCH
    )
    parsed = ast.parse(document.code.toPlainText()).body[0]
    statement = next(item for item in parsed.body if isinstance(item, ast.Match))
    return {
        "leaf": (
            match.cases[0].body.atoms[0].id,
            "            print('first case action')",
            statement.cases[0].body[0].lineno,
        ),
        "first": (
            match.cases[0].id,
            "        case 1:\n            print('first case action')",
            statement.cases[0].pattern.lineno,
        ),
        "default": (
            match.cases[1].id,
            "        case _:\n            print('default case action')",
            statement.cases[1].pattern.lineno,
        ),
        "match": (
            match.id,
            "    match value:\n"
            "        case 1:\n            print('first case action')\n"
            "        case _:\n            print('default case action')",
            statement.lineno,
        ),
        "final": (
            diagram.body.atoms[-1].id,
            "    print(f'selected value: {value}')",
            parsed.body[-1].lineno,
        ),
    }


@pytest.mark.parametrize("target", ("leaf", "first", "default", "match", "final"))
@pytest.mark.parametrize("direction", ("canvas", "source"))
def test_real_match_example_selects_exact_owner_or_leaf(qtbot, select_session, target, direction):
    document, diagram = _document(qtbot, select_session)
    identity, expected, line = _match_targets(document, diagram)[target]
    original_spans = document._execution_generated.spans
    if direction == "canvas":
        _click(qtbot, document, identity)
    else:
        document.code.setTextCursor(
            QTextCursor(document.code.document().findBlockByNumber(line - 1))
        )

    _visible_selection(document, identity)
    assert _highlight(document) == (expected, line)
    assert document.code.textCursor().blockNumber() + 1 == line
    assert document._execution_generated.spans == original_spans
    if target in {"first", "default"}:
        assert document.canvas.selected_atom_ids() == ()
    else:
        assert document.canvas.selected_atom_ids() == (identity,)


def test_selecting_match_then_inner_action_contracts_to_leaf(qtbot, select_session):
    document, diagram = _document(qtbot, select_session)
    targets = _match_targets(document, diagram)
    _click(qtbot, document, targets["match"][0])
    assert _highlight(document) == targets["match"][1:]

    _click(qtbot, document, targets["leaf"][0])

    _visible_selection(document, targets["leaf"][0])
    assert _highlight(document) == targets["leaf"][1:]


def test_conditions_select_owner_includes_cases_despite_having_no_direct_span(
    qtbot, select_session
):
    document, diagram = _document(qtbot, select_session)
    owner = next(
        atom
        for atom in diagram.body.atoms
        if isinstance(atom, Select) and atom.mode is SelectMode.CONDITIONS
    )
    assert not any(span.semantic_id == owner.id for span in document._generated.spans)

    _click(qtbot, document, owner.id)

    _visible_selection(document, owner.id)
    assert (
        _highlight(document)[0] == "    if value == 1:\n        print('first case action')\n"
        "    else:\n        print('default case action')"
    )


@pytest.mark.parametrize(
    ("example", "owner_type", "attribute", "expected"),
    (
        (
            "05-select-match",
            Select,
            "cases",
            "    if value == 1:\n        print('first case action')",
        ),
        (
            "07-contexts",
            Try,
            "handlers",
            "    except Exception as error:\n        print('exception action')",
        ),
        (
            "09-parallel",
            Parallel,
            "branches",
            "    def _cv_first_process():\n        print('first process')",
        ),
        (
            "13-silhouette",
            Silhouette,
            "branches",
            "        if _golden_node_state == 'Start':\n"
            "            print('start state action')\n"
            "            _golden_node_state = 'Finish'",
        ),
    ),
)
def test_intrinsic_headers_select_bidirectionally_but_cannot_edit_as_atoms(
    qtbot, tmp_path, example, owner_type, attribute, expected
):
    session = _saved_session(example)
    try:
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
        owner = next(atom for atom in diagram.body.atoms if isinstance(atom, owner_type))
        lead = getattr(owner, attribute)[0]
        _click(qtbot, document, lead.id)

        _visible_selection(document, lead.id)
        assert _highlight(document)[0] == expected
        assert session.kernel.selection.state.semantic_ids == (lead.id,)
        assert document.canvas.selected_atom_ids() == ()
        assert window._structural_selection() is None
        window._remove_selection()
        window._move_selection_by(-1)
        window._move_selection_by(1)
        window._duplicate_selection()
        assert not document.canvas.request_selected_field_edit()
        moves = []
        document.canvas.moveRequested.connect(lambda *args: moves.append(args))
        start = _point(document.canvas, lead.id)
        qtbot.mousePress(document.canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
        qtbot.mouseMove(document.canvas.viewport(), start + QPoint(30, 30))
        assert not document.canvas.drag_ghost_visible
        qtbot.mouseRelease(
            document.canvas.viewport(), Qt.MouseButton.LeftButton, pos=start + QPoint(30, 30)
        )
        assert not moves
        assert session.authority.snapshot() == before

        line = _highlight(document)[1]
        _click(qtbot, document, lead.body.atoms[0].id)
        document.code.setTextCursor(
            QTextCursor(document.code.document().findBlockByNumber(line - 1))
        )
        _visible_selection(document, lead.id)
        assert _highlight(document)[0] == expected
        document.canvas.select_atoms((lead.id,))
        assert document.canvas.selected_object_ids() == ()
        session.kernel.selection.select((lead.id,), source="test.external")
        _visible_selection(document, lead.id)
    finally:
        session.close()


def test_empty_case_selection_includes_its_generated_pass(qtbot, select_session):
    diagram = select_session.authority.snapshot().documents[0]
    match = next(
        atom
        for atom in diagram.body.atoms
        if isinstance(atom, Select) and atom.mode is SelectMode.MATCH
    )
    case = match.cases[0]
    assert isinstance(
        select_session.client.remove_drakon_block(
            diagram.id, case.body.id, (case.body.atoms[0].id,)
        ),
        CommandAccepted,
    )
    document, _diagram = _document(qtbot, select_session)

    _click(qtbot, document, case.id)

    _visible_selection(document, case.id)
    assert _highlight(document)[0] == "        case 1:\n            pass"


@pytest.mark.parametrize("example", ("06-loops", "07-contexts", "13-silhouette"))
def test_layout_plumbing_cannot_be_selected(qtbot, example):
    session = _saved_session(example)
    try:
        document, diagram = _document(qtbot, session)
        allowed = {item.id for item in selection_objects(diagram)}
        synthetic = [
            node.object_id
            for node in document.canvas.layout_scene.nodes
            if node.object_id not in allowed
        ]
        assert len(synthetic) > 1
        for identity in synthetic:
            assert selection_ownership(diagram, identity) == ()
            assert (
                not document.canvas._node_groups[identity].flags()
                & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            )
            document.canvas.select_objects((identity,))
            assert document.canvas.selected_object_ids() == ()
    finally:
        session.close()
