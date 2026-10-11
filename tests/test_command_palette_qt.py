from PySide6.QtCore import Qt

from code_visualizer.ui_qt.command_palette import CommandPalette
from code_visualizer.ui_qt.commands import CommandRegistry, CommandSpec


def _registry(calls: list[str]) -> CommandRegistry:
    registry = CommandRegistry()
    registry.register(
        CommandSpec(
            "first",
            "Generate Preview",
            "Python",
            "Preview generated source",
            lambda: calls.append("first"),
        )
    )
    registry.register(
        CommandSpec(
            "disabled",
            "Generate Disabled",
            "Python",
            "Unavailable generation command",
            lambda: calls.append("disabled"),
            is_enabled=lambda: False,
            disabled_reason=lambda: "No project",
        )
    )
    registry.register(
        CommandSpec(
            "second",
            "Generate Project",
            "Python",
            "Generate all modules",
            lambda: calls.append("second"),
        )
    )
    registry.register(
        CommandSpec(
            "third",
            "Generate Report",
            "Python",
            "Open generation report",
            lambda: calls.append("third"),
        )
    )
    return registry


def test_search_retains_focus_while_arrows_and_enter_execute(qtbot) -> None:
    calls: list[str] = []
    palette = CommandPalette(_registry(calls))
    qtbot.addWidget(palette)
    palette.show()
    qtbot.wait(1)
    palette.query.setFocus()
    qtbot.keyClicks(palette.query, "generate")

    assert palette.query.hasFocus()
    assert palette.results.currentItem().data(Qt.ItemDataRole.UserRole) == "first"

    qtbot.keyClick(palette.query, Qt.Key.Key_Down)
    assert palette.query.hasFocus()
    assert palette.results.currentItem().data(Qt.ItemDataRole.UserRole) == "second"

    qtbot.keyClick(palette.query, Qt.Key.Key_Down)
    assert palette.results.currentItem().data(Qt.ItemDataRole.UserRole) == "third"

    qtbot.keyClick(palette.query, Qt.Key.Key_Up)
    assert palette.results.currentItem().data(Qt.ItemDataRole.UserRole) == "second"

    qtbot.keyClick(palette.query, Qt.Key.Key_Return)
    assert calls == ["second"]


def test_boundary_clamps_disabled_rows_are_skipped_and_no_results_do_nothing(qtbot) -> None:
    calls: list[str] = []
    palette = CommandPalette(_registry(calls))
    qtbot.addWidget(palette)
    palette.show()
    qtbot.wait(1)
    palette.query.setFocus()
    qtbot.keyClicks(palette.query, "generate")

    qtbot.keyClick(palette.query, Qt.Key.Key_Up)
    assert palette.results.currentItem().data(Qt.ItemDataRole.UserRole) == "first"
    qtbot.keyClick(palette.query, Qt.Key.Key_End)
    assert palette.results.currentItem().data(Qt.ItemDataRole.UserRole) == "third"
    qtbot.keyClick(palette.query, Qt.Key.Key_Down)
    assert palette.results.currentItem().data(Qt.ItemDataRole.UserRole) == "third"

    palette.query.selectAll()
    qtbot.keyClicks(palette.query, "no such command")
    assert palette.empty_label.isVisible()
    qtbot.keyClick(palette.query, Qt.Key.Key_Return)
    assert calls == []


def test_one_mouse_click_executes_exactly_once(qtbot) -> None:
    calls: list[str] = []
    palette = CommandPalette(_registry(calls))
    qtbot.addWidget(palette)
    palette.show()
    qtbot.wait(1)

    item = palette.results.item(0)
    rect = palette.results.visualItemRect(item)
    qtbot.mouseClick(
        palette.results.viewport(),
        Qt.MouseButton.LeftButton,
        pos=rect.center(),
    )

    assert calls == ["first"]
