"""Accessible semantic-reference navigation dock."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from code_visualizer.application.navigation import (
    CallHierarchyNode,
    NavigationLocation,
    SemanticReference,
)


class SemanticNavigationWidget(QWidget):
    revealRequested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("semanticNavigationWidget")
        self.setAccessibleName("Semantic navigation")
        self.summary = QLabel("Choose Find Callers, Find Address Transitions, or Call Hierarchy.")
        self.summary.setWordWrap(True)
        self.results = QTreeWidget()
        self.results.setObjectName("semanticNavigationResults")
        self.results.setAccessibleName("Stable semantic navigation results")
        self.results.setHeaderLabels(["Reference", "Kind", "Stable target"])
        self.results.itemActivated.connect(self._activate)
        self.results.itemDoubleClicked.connect(self._activate)
        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addWidget(self.results, 1)

    def show_references(
        self,
        title: str,
        references: tuple[SemanticReference, ...],
    ) -> None:
        self.results.clear()
        self.summary.setText(f"{title}: {len(references)} stable semantic reference(s).")
        for reference in references:
            item = QTreeWidgetItem(
                [
                    reference.label,
                    reference.kind.value,
                    reference.stable_path,
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, reference.source)
            if reference.unresolved:
                item.setText(1, f"{reference.kind.value} - unresolved")
            self.results.addTopLevelItem(item)
        self._select_first_or_explain("No stable semantic references found.")

    def show_hierarchy(self, hierarchy: CallHierarchyNode) -> None:
        self.results.clear()
        self.summary.setText(
            "Call Hierarchy follows linked diagram IDs; recursive paths stop at a cycle marker."
        )

        def add(parent: QTreeWidgetItem | None, node: CallHierarchyNode) -> None:
            state = "cycle" if node.cycle else "unresolved" if node.unresolved else "diagram"
            item = QTreeWidgetItem([node.label, state, node.diagram_id])
            item.setData(0, Qt.ItemDataRole.UserRole, node.reveal)
            if parent is None:
                self.results.addTopLevelItem(item)
            else:
                parent.addChild(item)
            for child in node.children:
                add(item, child)

        add(None, hierarchy)
        self.results.expandAll()
        self._select_first_or_explain("No call hierarchy is available.")

    def _select_first_or_explain(self, empty_message: str) -> None:
        first = self.results.topLevelItem(0)
        if first is None:
            placeholder = QTreeWidgetItem([empty_message, "", ""])
            placeholder.setDisabled(True)
            self.results.addTopLevelItem(placeholder)
            return
        self.results.setCurrentItem(first)
        self.results.scrollToItem(first)

    def _activate(self, item: QTreeWidgetItem, _column: int) -> None:
        location = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(location, NavigationLocation):
            self.revealRequested.emit(location)
