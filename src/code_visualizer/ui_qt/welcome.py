"""Useful startup surface for new, open, recent, and example projects."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from code_visualizer.application.examples import EXAMPLE_CATALOG


class WelcomePage(QWidget):
    newRequested = Signal()
    helloRequested = Signal()
    openRequested = Signal()
    recentRequested = Signal(str)
    exampleRequested = Signal(str)
    documentRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("welcomePage")
        title = QLabel("Code Visualizer")
        title.setObjectName("welcomeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle = QLabel(
            "Build Python with structural DRAKON diagrams, mind maps, and free-form scenes."
        )
        subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.new_button = QPushButton("New Project")
        self.new_button.setObjectName("welcomeNewProject")
        self.new_button.clicked.connect(self.newRequested)
        self.hello_button = QPushButton("Start with Hello World")
        self.hello_button.setObjectName("welcomeHelloWorld")
        self.hello_button.clicked.connect(self.helloRequested)
        self.open_button = QPushButton("Open Project")
        self.open_button.setObjectName("welcomeOpenProject")
        self.open_button.clicked.connect(self.openRequested)

        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(self.new_button)
        actions.addWidget(self.hello_button)
        actions.addWidget(self.open_button)
        actions.addStretch(1)

        self.project_hint = QLabel()
        self.project_hint.setWordWrap(True)
        self.open_documents = QListWidget()
        self.open_documents.setObjectName("reopenProjectDocuments")
        self.open_documents.setAccessibleName("Reopen a document in the current project")
        self.open_documents.itemActivated.connect(self._activate_document)
        self.open_documents.hide()
        self.project_hint.hide()
        self.recent = QListWidget()
        self.recent.setObjectName("recentProjects")
        self.recent.setAccessibleName("Recent saved projects")
        self.recent.itemActivated.connect(self._activate_recent)

        self.examples = QListWidget()
        self.examples.setObjectName("exampleProjects")
        self.examples.setAccessibleName("Bundled example projects")
        for example in EXAMPLE_CATALOG:
            item = QListWidgetItem(f"{example.label} — {example.description}")
            item.setData(Qt.ItemDataRole.UserRole, example.id)
            item.setToolTip("Open an unsaved editable copy; the bundled template is never changed")
            self.examples.addItem(item)
        self.examples.itemActivated.connect(self._activate_example)

        layout = QVBoxLayout(self)
        layout.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(actions)
        layout.addWidget(self.project_hint)
        layout.addWidget(self.open_documents, 1)
        layout.addWidget(QLabel("Recent Projects"))
        layout.addWidget(self.recent, 1)
        layout.addWidget(QLabel("Examples"))
        layout.addWidget(self.examples, 1)
        layout.addStretch(1)

    def set_project_documents(self, title: str, documents: tuple[tuple[str, str], ...]) -> None:
        self.open_documents.clear()
        for identity, label in documents:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, identity)
            item.setToolTip("Reopen this document; closing its tab did not delete it.")
            self.open_documents.addItem(item)
        self.project_hint.setText(
            f"{title} is still open. Reopen a document below, or choose an example."
        )
        self.project_hint.setVisible(bool(title))
        self.open_documents.setVisible(bool(documents))

    def _activate_document(self, item: QListWidgetItem) -> None:
        identity = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(identity, str):
            self.documentRequested.emit(identity)

    def set_recent_paths(self, paths: tuple[Path, ...]) -> None:
        self.recent.clear()
        for path in paths:
            item = QListWidgetItem(f"{path.name}    {path}")
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(str(path))
            self.recent.addItem(item)

    def _activate_recent(self, item: QListWidgetItem) -> None:
        value = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(value, str):
            self.recentRequested.emit(value)

    def _activate_example(self, item: QListWidgetItem) -> None:
        value = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(value, str):
            self.exampleRequested.emit(value)
