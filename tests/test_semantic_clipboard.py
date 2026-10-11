import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from textwrap import dedent

import pytest
from PySide6.QtCore import QSettings, Qt

from code_visualizer.application.clipboard import (
    MAX_SEMANTIC_FRAGMENT_BYTES,
    ClipboardFormatError,
    drakon_fragment,
    freeform_fragment,
    mindmap_fragment,
    paste_freeform_fragment,
    paste_mindmap_fragment,
    semantic_fragment_from_json,
    unresolved_references,
)
from code_visualizer.application.drakon_structure import clone_atoms_with_fresh_ids
from code_visualizer.application.project_factory import create_default_project
from code_visualizer.domain.drakon import Call, If, drakon_atom_ids
from code_visualizer.domain.freeform import (
    ConnectorObject,
    FreeformDiagram,
    Rect,
    ShapeKind,
    ShapeObject,
)
from code_visualizer.domain.mindmap import CrossLink, MindMapDiagram, Topic, walk_topics
from code_visualizer.ui_qt.document import UnifiedDocumentWidget
from code_visualizer.ui_qt.main_window import CloseDecision, MainWindow


def _settings(path: Path) -> QSettings:
    return QSettings(str(path / "clipboard.ini"), QSettings.Format.IniFormat)


def test_drakon_fragment_round_trip_fresh_ids_and_unresolved_link() -> None:
    project = create_default_project()
    source = (
        If("if_original"),
        Call("call_original", "missing()", target_diagram_id="diagram_missing"),
    )
    fragment = semantic_fragment_from_json(drakon_fragment(project.id, source).to_json())
    clones = clone_atoms_with_fresh_ids(source)

    assert fragment.summary == "DRAKON block: 2 operations"
    assert (
        set()
        .union(*(set(drakon_atom_ids(atom)) for atom in source))
        .isdisjoint(set().union(*(set(drakon_atom_ids(atom)) for atom in clones)))
    )
    assert unresolved_references(fragment, project) == ("linked Call target diagram_missing",)


def test_clipboard_parser_is_bounded_and_versioned() -> None:
    with pytest.raises(ClipboardFormatError) as too_large:
        semantic_fragment_from_json(b" " * (MAX_SEMANTIC_FRAGMENT_BYTES + 1))
    assert too_large.value.code == "CLIPBOARD_TOO_LARGE"

    with pytest.raises(ClipboardFormatError) as future:
        semantic_fragment_from_json(
            '{"format":"code-visualizer-semantic-fragment","mode":"drakon",'
            '"payload":{},"source_project_id":"p","summary":"x","version":2}'
        )
    assert future.value.code == "CLIPBOARD_UNSUPPORTED_VERSION"


def test_mindmap_subtree_paste_preserves_internal_links_and_reports_external_assets() -> None:
    project = create_default_project()
    subtree = Topic(
        "topic_source",
        "Source",
        (Topic("topic_child", "Child", attachments=("asset_missing",)),),
    )
    source = MindMapDiagram(
        "mind_source",
        "Source map",
        Topic("root_source", "Root", (subtree, Topic("topic_external", "External"))),
        (
            CrossLink("link_internal", "topic_source", "topic_child", "contains"),
            CrossLink("link_external", "topic_child", "topic_external", "depends"),
        ),
    )
    destination = MindMapDiagram("mind_destination", "Destination", Topic("root_dest", "Root"))
    fragment = mindmap_fragment(project.id, source, subtree)

    updated, identifiers, unresolved = paste_mindmap_fragment(
        fragment,
        project,
        destination,
        destination.root.id,
        0,
    )

    pasted = updated.root.children[0]
    assert len(identifiers) == 2
    assert {topic.id for topic in walk_topics(pasted)}.isdisjoint({"topic_source", "topic_child"})
    assert len(updated.cross_links) == 1
    assert updated.cross_links[0].source_topic_id == pasted.id
    assert updated.cross_links[0].target_topic_id == pasted.children[0].id
    assert pasted.children[0].attachments == ()
    assert "managed asset asset_missing" in unresolved
    assert "external relationship 1" in unresolved


def test_freeform_paste_preserves_style_geometry_and_internal_connector() -> None:
    project = create_default_project()
    source = FreeformDiagram(
        "free_source",
        "Source",
        (
            ShapeObject(
                "shape_a",
                ShapeKind.POLYGON,
                Rect(10, 20, 100, 60),
                "A",
                rotation=15,
                group_id="group_source",
                fill="#112233",
                stroke="#abcdef",
            ),
            ShapeObject(
                "shape_b",
                ShapeKind.ROUNDED_RECTANGLE,
                Rect(200, 20, 100, 60),
                "B",
                group_id="group_source",
            ),
            ConnectorObject("connector_ab", "shape_a", "shape_b", label="data"),
        ),
    )
    destination = replace(source, id="free_dest", title="Destination", objects=())
    fragment = freeform_fragment(project.id, source, ("shape_a", "shape_b"))

    updated, identifiers, unresolved = paste_freeform_fragment(fragment, project, destination)

    assert len(identifiers) == 2
    assert set(identifiers).isdisjoint({"shape_a", "shape_b"})
    pasted_shapes = [item for item in updated.objects if isinstance(item, ShapeObject)]
    pasted_connector = next(item for item in updated.objects if isinstance(item, ConnectorObject))
    assert pasted_shapes[0].bounds.x == 34
    assert pasted_shapes[0].rotation == 15
    assert pasted_shapes[0].fill == "#112233"
    assert pasted_shapes[0].group_id == pasted_shapes[1].group_id
    assert pasted_connector.source_id in identifiers
    assert pasted_connector.target_id in identifiers
    assert unresolved == ()


def test_keyboard_copy_paste_is_one_undoable_semantic_edit(qtbot, tmp_path) -> None:
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
        diagram.id, "if", 0, operation_id="clipboard-source"
    )
    assert inserted.affected_ids
    editor = window.documents.currentWidget()
    assert isinstance(editor, UnifiedDocumentWidget)
    editor.refresh(window.session.authority.snapshot())
    editor.canvas.select_atoms((inserted.affected_ids[0],))
    window.activateWindow()
    window.raise_()
    qtbot.wait(50)
    editor.canvas.setFocus()
    qtbot.waitUntil(editor.canvas.hasFocus)
    before = window.session.authority.revision

    qtbot.keyClick(editor.canvas, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert window.statusBar().currentMessage().startswith("Copied"), (
        window.statusBar().currentMessage(),
        window.action_copy.shortcuts(),
        editor.canvas.hasFocus(),
    )
    qtbot.keyClick(editor.canvas, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)

    current = window.session.authority.snapshot().documents[0]
    assert len(current.body.atoms) == 2
    original, clone = current.body.atoms
    assert isinstance(original, If) and isinstance(clone, If)
    assert set(drakon_atom_ids(original)).isdisjoint(drakon_atom_ids(clone))
    assert window.session.authority.revision == before + 1
    window.action_undo.trigger()
    assert len(window.session.authority.snapshot().documents[0].body.atoms) == 1


@pytest.mark.parametrize("platform", ["offscreen", "minimal"])
def test_virtual_clipboard_survives_window_close_and_exits_cleanly(tmp_path, platform) -> None:
    script = tmp_path / "clipboard_shutdown.py"
    script.write_text(
        dedent(
            """\
            import sys
            if sys.platform == "win32":
                import ctypes
                ctypes.windll.kernel32.SetErrorMode(0x0002)
            from PySide6.QtWidgets import QApplication, QWidget
            from code_visualizer.application.clipboard import (
                SEMANTIC_FRAGMENT_MIME, drakon_fragment,
            )
            from code_visualizer.domain.drakon import If
            from code_visualizer.ui_qt.clipboard import set_semantic_clipboard

            application = QApplication([])
            fragment = drakon_fragment("clipboard_project", (If("copied_if"),))
            set_semantic_clipboard(fragment)
            window = QWidget()
            window.show()
            application.processEvents()
            window.close()
            application.processEvents()
            clipboard = application.clipboard()
            assert clipboard.text() == fragment.summary
            copied = bytes(clipboard.mimeData().data(SEMANTIC_FRAGMENT_MIME))
            assert copied == fragment.to_json().encode("utf-8")
            """
        ),
        encoding="utf-8",
    )
    environment = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        "QT_QPA_PLATFORM": platform,
    }
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_desktop_clipboard_does_not_register_virtual_shutdown_cleanup(qapp, monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication

    from code_visualizer.ui_qt.clipboard import set_semantic_clipboard

    def unexpected_cleanup() -> None:
        raise AssertionError("A native desktop clipboard must retain its platform lifetime")

    monkeypatch.setattr(QApplication, "platformName", lambda: "windows")
    monkeypatch.setattr(
        "code_visualizer.ui_qt.clipboard._register_virtual_clipboard_cleanup", unexpected_cleanup
    )
    fragment = drakon_fragment("desktop_clipboard", (If("copied_if"),))
    try:
        set_semantic_clipboard(fragment)
        assert qapp.clipboard().text() == fragment.summary
    finally:
        # The test still uses a virtual backend, so retire its test payload here.
        qapp.clipboard().clear()
