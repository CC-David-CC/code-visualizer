from pathlib import Path

from PySide6.QtCore import QSettings, Qt

from code_visualizer.application.messages import CommandAccepted
from code_visualizer.ui_qt.document import UnifiedDocumentWidget
from code_visualizer.ui_qt.main_window import CloseDecision, MainWindow


def _settings(path: Path) -> QSettings:
    return QSettings(str(path / "search.ini"), QSettings.Format.IniFormat)


def test_project_search_reveals_and_replace_all_is_one_undoable_transaction(
    qtbot, tmp_path
) -> None:
    window = MainWindow(
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()
    assert window.session is not None
    diagram = window.session.authority.snapshot().documents[0]
    for index, source in enumerate(('print("needle one")', 'print("needle two")')):
        inserted = window.session.client.insert_drakon_atom(
            diagram.id,
            "action",
            index,
            source=source,
        )
        assert isinstance(inserted, CommandAccepted)
    before_replace = window.session.authority.revision

    window.action_replace.trigger()
    qtbot.keyClicks(window.search_widget.query, "needle")
    qtbot.mouseClick(window.search_widget.find_button, Qt.MouseButton.LeftButton)
    assert window.search_widget.results.topLevelItemCount() == 2
    assert "2 replaceable fields" in window.search_widget.preview.text()
    qtbot.wait(50)

    first = window.search_widget.results.topLevelItem(0)
    assert first is not None
    revealed = []
    window.search_widget.revealRequested.connect(revealed.append)
    window.search_widget.results.setCurrentItem(first)
    first_rect = window.search_widget.results.visualItemRect(first)
    assert not first_rect.isEmpty(), (
        first_rect,
        window.search_dock.isVisible(),
        window.search_widget.results.size(),
    )
    qtbot.mouseClick(
        window.search_widget.results.viewport(),
        Qt.MouseButton.LeftButton,
        pos=first_rect.center(),
    )
    assert revealed
    document = window.documents.currentWidget()
    assert isinstance(document, UnifiedDocumentWidget)
    assert len(document.canvas.selected_atom_ids()) == 1

    window.search_widget.replacement.setText("found")
    qtbot.mouseClick(window.search_widget.replace_all_button, Qt.MouseButton.LeftButton)
    assert window.session.authority.revision == before_replace + 1
    qtbot.waitUntil(lambda: document.code.toPlainText().count("found") == 2, timeout=10000)
    assert document.code.toPlainText().count("found") == 2
    assert "needle" not in document.code.toPlainText()

    window.action_undo.trigger()
    qtbot.waitUntil(lambda: document.code.toPlainText().count("needle") == 2)


def test_module_setup_replace_all_is_one_non_clobbering_transaction(qtbot, tmp_path) -> None:
    window = MainWindow(
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()
    assert window.session is not None
    before = window.session.authority.revision

    window.action_replace.trigger()
    window.search_widget.query.setText("Default")
    qtbot.mouseClick(window.search_widget.find_button, Qt.MouseButton.LeftButton)
    assert window.search_widget.results.topLevelItemCount() == 2
    assert "2 replaceable fields" in window.search_widget.preview.text()
    window.search_widget.replacement.setText("Development")
    qtbot.mouseClick(window.search_widget.replace_all_button, Qt.MouseButton.LeftButton)

    setup = window.session.authority.snapshot().runtime_settings
    assert setup.run_profiles[0].name == "Development"
    assert setup.active_run_profile == "Development"
    assert window.session.authority.revision == before + 1

    window.action_undo.trigger()
    qtbot.waitUntil(
        lambda: (
            window.session is not None
            and window.session.authority.snapshot().runtime_settings.active_run_profile == "Default"
        )
    )
