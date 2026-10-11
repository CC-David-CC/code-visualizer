"""Project-wide deterministic semantic search and previewed replacement UI."""

from __future__ import annotations

import re

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.search import (
    SearchMatch,
    replacement_command,
    replacement_commands,
    search_project,
)
from code_visualizer.sdk import CodeVisualizerClient


class ProjectSearchWidget(QWidget):
    revealRequested = Signal(object)
    projectChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("projectSearchWidget")
        self.setAccessibleName("Project search and replace")
        self._client: CodeVisualizerClient | None = None
        self._matches: tuple[SearchMatch, ...] = ()

        self.query = QLineEdit()
        self.query.setObjectName("projectSearchQuery")
        self.query.setAccessibleName("Project search text")
        self.query.setPlaceholderText("Search names, Python fields, topics, and canvas text")
        self.replacement = QLineEdit()
        self.replacement.setObjectName("projectReplacement")
        self.replacement.setAccessibleName("Replacement text")
        self.replacement.setPlaceholderText("Replacement")
        self.find_button = QPushButton("Find")
        self.replace_one_button = QPushButton("Replace One")
        self.replace_all_button = QPushButton("Replace All")
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Find:"))
        controls.addWidget(self.query, 2)
        controls.addWidget(QLabel("Replace:"))
        controls.addWidget(self.replacement, 2)
        controls.addWidget(self.find_button)
        controls.addWidget(self.replace_one_button)
        controls.addWidget(self.replace_all_button)

        self.preview = QLabel("Enter text to search the complete project.")
        self.preview.setObjectName("replacePreview")
        self.preview.setWordWrap(True)
        self.preview.setAccessibleName("Replacement impact preview")
        self.results = QTreeWidget()
        self.results.setObjectName("projectSearchResults")
        self.results.setAccessibleName("Deterministic project search results")
        self.results.setHeaderLabels(["Text", "Kind", "Field", "Location", "Replace"])
        self.results.setRootIsDecorated(False)

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self.preview)
        layout.addWidget(self.results, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self.refresh_results)
        self.query.textChanged.connect(lambda _value: self._timer.start())
        self.replacement.textChanged.connect(lambda _value: self._update_preview())
        self.find_button.clicked.connect(self.refresh_results)
        self.replace_one_button.clicked.connect(self.replace_one)
        self.replace_all_button.clicked.connect(self.replace_all)
        self.results.itemClicked.connect(self._activate)
        self.results.itemActivated.connect(self._activate)
        self.results.itemDoubleClicked.connect(self._activate)
        self.results.itemSelectionChanged.connect(self._update_preview)
        self._set_replace_enabled(False)

    def attach(self, client: CodeVisualizerClient | None) -> None:
        self._client = client
        self.refresh_results()

    def refresh_results(self) -> None:
        client = self._client
        self.results.clear()
        self._matches = search_project(client.snapshot(), self.query.text()) if client else ()
        for index, match in enumerate(self._matches):
            item = QTreeWidgetItem(
                [
                    match.text.replace("\n", " ↵ ")[:180],
                    match.kind,
                    match.field,
                    match.path,
                    "Yes" if match.replace_supported else "Read only",
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, index)
            item.setToolTip(0, match.text)
            self.results.addTopLevelItem(item)
        if self.results.topLevelItemCount():
            first = self.results.topLevelItem(0)
            if first is not None:
                self.results.setCurrentItem(first)
        self._update_preview()

    def current_match(self) -> SearchMatch | None:
        selected = self.results.selectedItems()
        if not selected:
            return None
        index = selected[0].data(0, Qt.ItemDataRole.UserRole)
        if isinstance(index, int) and 0 <= index < len(self._matches):
            return self._matches[index]
        return None

    def replace_one(self) -> None:
        match = self.current_match()
        client = self._client
        if client is None or match is None:
            return
        command = replacement_command(client.snapshot(), match, self._replacement_for(match))
        if command is None:
            return
        result = client.submit(command, intent=f"Replace one search result at {match.path}")
        self._after_replace(result)

    def replace_all(self) -> None:
        client = self._client
        if client is None:
            return
        project = client.snapshot()
        commands = replacement_commands(
            project,
            tuple(
                (match, self._replacement_for(match))
                for match in self._matches
                if match.replace_supported
            ),
        )
        if not commands:
            return
        result = client.transaction(
            commands,
            intent=f"Replace all {len(commands)} matching semantic fields",
        )
        self._after_replace(result)

    def _replacement_for(self, match: SearchMatch) -> str:
        return re.sub(
            re.escape(self.query.text()),
            lambda _matched: self.replacement.text(),
            match.text,
            flags=re.IGNORECASE,
        )

    def _after_replace(self, result: object) -> None:
        if isinstance(result, CommandAccepted):
            self.preview.setText(
                f"Committed one replacement transaction at revision {result.revision}."
            )
            self.refresh_results()
            self.projectChanged.emit()
        else:
            self.preview.setText("Replacement was rejected; the project is unchanged.")

    def _activate(self, item: QTreeWidgetItem, _column: int) -> None:
        index = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(index, int) and 0 <= index < len(self._matches):
            self.revealRequested.emit(self._matches[index])

    def _update_preview(self) -> None:
        replaceable = tuple(match for match in self._matches if match.replace_supported)
        diagrams = {match.diagram_id for match in replaceable if match.diagram_id is not None}
        current = self.current_match()
        self.preview.setText(
            f"{len(self._matches)} results; {len(replaceable)} replaceable fields across "
            f"{len(diagrams)} diagrams. Replace All commits one undoable transaction."
        )
        self.replace_one_button.setEnabled(
            current is not None and current.replace_supported and bool(self.query.text())
        )
        self.replace_all_button.setEnabled(bool(replaceable) and bool(self.query.text()))

    def _set_replace_enabled(self, enabled: bool) -> None:
        self.replace_one_button.setEnabled(enabled)
        self.replace_all_button.setEnabled(enabled)
