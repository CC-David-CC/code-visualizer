"""Keyboard-complete command palette."""

from __future__ import annotations

from collections.abc import Iterable
from typing import cast

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QAccessible, QAccessibleEvent, QKeyEvent, QShowEvent
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from code_visualizer.ui_qt.commands import CommandRegistry, CommandSpec

COMMAND_ID_ROLE = int(Qt.ItemDataRole.UserRole)


def _score(command: CommandSpec, needle: str) -> tuple[int, str, str] | None:
    if not needle:
        return (0, command.category.casefold(), command.label.casefold())
    label = command.label.casefold()
    category = command.category.casefold()
    description = command.description.casefold()
    aliases = f"{label} {category} {description}"
    if label.startswith(needle):
        rank = 0
    elif needle in label:
        rank = 1
    elif all(token in aliases for token in needle.split()):
        rank = 2
    else:
        return None
    return (rank, category, label)


class CommandPalette(QDialog):
    def __init__(self, registry: CommandRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("commandPalette")
        self.setWindowTitle("Command Palette")
        self.resize(620, 460)
        self._registry = registry
        self._executing = False

        self.query = QLineEdit()
        self.query.setObjectName("commandPaletteSearch")
        self.query.setPlaceholderText("Search commands")
        self.query.setAccessibleName("Command search")
        self.query.installEventFilter(self)
        self.setFocusProxy(self.query)

        self.results = QListWidget()
        self.results.setObjectName("commandPaletteResults")
        self.results.setAccessibleName("Matching commands")
        self.results.setAlternatingRowColors(True)
        # Arrow-key navigation is handled while the search field keeps focus.
        # NoFocus does not prevent normal mouse selection or activation.
        self.results.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.empty_label = QLabel("No matching commands")
        self.empty_label.setObjectName("commandPaletteEmpty")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        hint = QLabel("Type to search · Up/Down to choose · Enter to run · Escape to close")
        hint.setAccessibleName("Command palette keyboard help")

        layout = QVBoxLayout(self)
        layout.addWidget(self.query)
        layout.addWidget(self.results, 1)
        layout.addWidget(self.empty_label)
        layout.addWidget(hint)

        self.query.textChanged.connect(self._refill)
        self.results.itemClicked.connect(self._activate_item)
        self.results.currentItemChanged.connect(self._announce_current)
        self._refill("")

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.raise_()
        self.activateWindow()
        self.query.setFocus(Qt.FocusReason.PopupFocusReason)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.query and event.type() == QEvent.Type.KeyPress:
            key_event = cast(QKeyEvent, event)
            key = key_event.key()
            if key == Qt.Key.Key_Down:
                self._move(1)
                return True
            if key == Qt.Key.Key_Up:
                self._move(-1)
                return True
            if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
                self._activate_current()
                return True
            if key == Qt.Key.Key_Escape:
                self.reject()
                return True
            if key == Qt.Key.Key_Home:
                self._select_boundary(first=True)
                return True
            if key == Qt.Key.Key_End:
                self._select_boundary(first=False)
                return True
            if key == Qt.Key.Key_PageDown:
                self._move(5)
                return True
            if key == Qt.Key.Key_PageUp:
                self._move(-5)
                return True
        return super().eventFilter(watched, event)

    def _matching(self, query: str) -> tuple[CommandSpec, ...]:
        needle = query.casefold().strip()
        if not needle:
            # The registry order is the product-defined default ordering.
            # Search results below are relevance-ranked and deterministic.
            return self._registry.all()
        ranked: list[tuple[tuple[int, str, str], CommandSpec]] = []
        for command in self._registry.all():
            score = _score(command, needle)
            if score is not None:
                ranked.append((score, command))
        ranked.sort(key=lambda item: item[0])
        return tuple(command for _, command in ranked)

    def _refill(self, query: str) -> None:
        previous = self._current_command_id()
        self.results.clear()
        for command in self._matching(query):
            text = f"{command.label}    {command.shortcut}".rstrip()
            item = QListWidgetItem(text)
            item.setData(COMMAND_ID_ROLE, command.id)
            item.setToolTip(command.description)
            item.setData(
                Qt.ItemDataRole.AccessibleTextRole,
                f"{command.label}, {command.category}",
            )
            if not command.is_enabled():
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                reason = command.disabled_reason() or "Unavailable"
                item.setToolTip(f"{command.description}\nUnavailable: {reason}")
                item.setText(f"{text}    —    {reason}")
            self.results.addItem(item)
        has_results = self.results.count() > 0
        self.results.setVisible(has_results)
        self.empty_label.setVisible(not has_results)
        if not has_results:
            return
        preserved = self._row_for_command(previous)
        if preserved is not None and self._row_enabled(preserved):
            self.results.setCurrentRow(preserved)
        else:
            self._select_boundary(first=True)

    def _enabled_rows(self) -> tuple[int, ...]:
        return tuple(row for row in range(self.results.count()) if self._row_enabled(row))

    def _row_enabled(self, row: int) -> bool:
        item = self.results.item(row)
        return item is not None and bool(item.flags() & Qt.ItemFlag.ItemIsEnabled)

    def _move(self, delta: int) -> None:
        rows = self._enabled_rows()
        if not rows:
            return
        current = self.results.currentRow()
        if current not in rows:
            target_index = 0 if delta >= 0 else len(rows) - 1
        else:
            target_index = rows.index(current) + delta
            target_index = max(0, min(len(rows) - 1, target_index))
        self.results.setCurrentRow(rows[target_index])
        self.results.scrollToItem(self.results.currentItem())
        self.query.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _select_boundary(self, *, first: bool) -> None:
        rows = self._enabled_rows()
        if not rows:
            self.results.setCurrentRow(-1)
            return
        self.results.setCurrentRow(rows[0] if first else rows[-1])
        self.results.scrollToItem(self.results.currentItem())
        self.query.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _current_command_id(self) -> str | None:
        item = cast(QListWidgetItem | None, self.results.currentItem())
        if item is None:
            return None
        value = item.data(COMMAND_ID_ROLE)
        return value if isinstance(value, str) else None

    def _row_for_command(self, command_id: str | None) -> int | None:
        if command_id is None:
            return None
        for row in range(self.results.count()):
            item = self.results.item(row)
            if item is not None and item.data(COMMAND_ID_ROLE) == command_id:
                return row
        return None

    def _activate_item(self, item: QListWidgetItem) -> None:
        if not bool(item.flags() & Qt.ItemFlag.ItemIsEnabled):
            return
        self.results.setCurrentItem(item)
        self._activate_current()

    def _activate_current(self) -> None:
        if self._executing:
            return
        command_id = self._current_command_id()
        if command_id is None:
            return
        command = self._registry.get(command_id)
        if not command.is_enabled():
            return
        self._executing = True
        try:
            command.execute()
            self.accept()
        finally:
            self._executing = False

    def _announce_current(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if current is None:
            self.results.setAccessibleDescription("No active command")
        else:
            self.results.setAccessibleDescription(f"Active command: {current.text()}")
        QAccessible.updateAccessibility(
            QAccessibleEvent(self.results, QAccessible.Event.DescriptionChanged)
        )


def command_ids(commands: Iterable[CommandSpec]) -> tuple[str, ...]:
    return tuple(command.id for command in commands)
