from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QApplication

from code_visualizer.application.messages import CommandAccepted
from code_visualizer.domain.drakon import If
from code_visualizer.ui_qt.command_palette import CommandPalette
from code_visualizer.ui_qt.document import UnifiedDocumentWidget
from code_visualizer.ui_qt.main_window import CloseDecision, MainWindow
from code_visualizer.ui_qt.theme import THEMES, ThemeName, contrast_ratio


def _settings(path: Path) -> QSettings:
    return QSettings(str(path / "accessibility.ini"), QSettings.Format.IniFormat)


def test_all_theme_text_pairs_meet_wcag_aa_and_highlight_is_distinct() -> None:
    for tokens in THEMES.values():
        assert contrast_ratio(tokens.text, tokens.window) >= 4.5
        assert contrast_ratio(tokens.text, tokens.surface) >= 4.5
        assert contrast_ratio(tokens.accent, tokens.window) >= 3.0
    classic = THEMES[ThemeName.CLASSIC]
    assert classic.surface != "#ffffff"
    assert classic.window != classic.surface


def test_first_release_appearance_migrates_once_then_preserves_user_theme(qtbot, tmp_path) -> None:
    settings = _settings(tmp_path)
    settings.setValue("appearance/theme", ThemeName.HIGH_CONTRAST.value)

    migrated = MainWindow(settings=settings)
    qtbot.addWidget(migrated)
    assert migrated.theme_actions[ThemeName.CLASSIC].isChecked()
    assert settings.value("appearance/theme") == ThemeName.CLASSIC.value
    assert int(settings.value("appearance/revision")) == 1
    migrated.theme_actions[ThemeName.DARK].trigger()
    migrated.close()

    reopened = MainWindow(settings=settings)
    qtbot.addWidget(reopened)
    assert reopened.theme_actions[ThemeName.DARK].isChecked()
    reopened.theme_actions[ThemeName.CLASSIC].trigger()
    reopened.close()


def test_theme_switch_preserves_geometry_and_reduced_motion_is_explicit(qtbot, tmp_path) -> None:
    window = MainWindow(
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()
    document = window.documents.currentWidget()
    assert isinstance(document, UnifiedDocumentWidget)
    before = document.canvas.layout_scene
    assert before is not None

    window.theme_actions[ThemeName.HIGH_CONTRAST].trigger()
    after = document.canvas.layout_scene
    assert after is not None
    assert after.bounds == before.bounds
    assert after.nodes == before.nodes

    window.action_reduced_motion.trigger()
    application = QApplication.instance()
    assert application is not None
    assert application.property("codeVisualizerReducedMotion") is True
    assert application.property("codeVisualizerTheme") == "high_contrast"


def test_qt_accessibility_names_palette_announcement_and_preferred_tab_order(
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
    inserted = window.session.client.insert_drakon_atom(
        diagram.id,
        "if",
        0,
        source="ready",
    )
    assert isinstance(inserted, CommandAccepted)
    updated = window.session.authority.snapshot().documents[0]
    decision = updated.body.atoms[0]
    assert isinstance(decision, If)
    window.session.client.replace_drakon_atom(
        updated.id,
        If(
            decision.id,
            decision.condition,
            decision.true_branch,
            decision.false_branch,
            preferred_truth=False,
        ),
    )
    document = window.documents.currentWidget()
    assert isinstance(document, UnifiedDocumentWidget)
    document.refresh(window.session.authority.snapshot())

    for widget, expected_name in (
        (window.project_tree, "Project explorer"),
        (window.shape_list, "Semantic shape library"),
        (document.canvas, "Structural DRAKON canvas"),
        (document.code, "Generated Python"),
        (document.console, "Live test output"),
    ):
        interface = QAccessible.queryAccessibleInterface(widget)
        assert interface is not None
        assert interface.text(QAccessible.Text.Name) == expected_name

    palette = CommandPalette(window.command_registry, window)
    qtbot.addWidget(palette)
    palette.show()
    qtbot.keyClicks(palette.query, "insert")
    qtbot.keyClick(palette.query, Qt.Key.Key_Down)
    assert palette.results.accessibleDescription().startswith("Active command:")

    traversal = document.canvas.semantic_traversal()
    assert traversal[0] == decision.id
    assert traversal[1] == decision.false_branch.atoms[0].id
    document.canvas.setFocus()
    qtbot.keyClick(document.canvas, Qt.Key.Key_Tab)
    assert document.canvas.selected_atom_ids() == (decision.id,)
    assert "traversal 1" in document.canvas.accessibleDescription()
    qtbot.keyClick(document.canvas, Qt.Key.Key_Tab)
    assert document.canvas.selected_atom_ids() == (decision.false_branch.atoms[0].id,)
