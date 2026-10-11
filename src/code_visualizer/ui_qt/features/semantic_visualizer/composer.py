"""Human-facing editors for semantic lenses and authored relationships."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from code_visualizer.domain.authoring import AuthoredRelationKind
from code_visualizer.domain.common import new_id
from code_visualizer.domain.projection import (
    ProjectionDecoration,
    ProjectionDefinition,
    ProjectionGrouping,
    ProjectionLabelStyle,
    ProjectionLayout,
    TraversalDirection,
)
from code_visualizer.domain.semantic import (
    SemanticObject,
    SemanticObjectKind,
    SemanticRelationKind,
)

_OBJECT_KINDS = tuple(
    kind
    for kind in SemanticObjectKind
    if kind
    not in {
        SemanticObjectKind.VIEW,
        SemanticObjectKind.GLYPH,
        SemanticObjectKind.ANNOTATION,
        SemanticObjectKind.GROUP,
    }
)


class ProjectionComposerDialog(QDialog):
    """Compose a view from vocabulary instead of writing visualization code."""

    def __init__(
        self,
        semantic_objects: tuple[SemanticObject, ...],
        existing: ProjectionDefinition | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Compose Semantic Lens")
        self.setObjectName("projectionComposerDialog")
        self.setMinimumSize(660, 670)
        self._existing_id = existing.id if existing is not None else new_id("projection")
        self._existing_definition = existing

        self.title_edit = QLineEdit(existing.title if existing is not None else "My semantic lens")
        self.title_edit.setObjectName("projectionTitle")
        self.scope_choice = QComboBox()
        self.scope_choice.setObjectName("projectionScope")
        self.scope_choice.addItem("Whole project", None)
        scope_kinds = {
            SemanticObjectKind.PROJECT,
            SemanticObjectKind.NAMESPACE,
            SemanticObjectKind.MODULE,
            SemanticObjectKind.CLASS,
            SemanticObjectKind.FUNCTION,
            SemanticObjectKind.CONCEPT,
        }
        for item in sorted(
            (value for value in semantic_objects if value.kind in scope_kinds),
            key=lambda value: (value.kind.value, value.label.casefold(), value.id),
        ):
            self.scope_choice.addItem(f"{item.kind.value}: {item.label}", item.id)

        self.object_kinds = self._check_list(
            "projectionObjectKinds",
            ((kind.value.replace("_", " ").title(), kind.value) for kind in _OBJECT_KINDS),
            {item.value for item in existing.object_kinds} if existing is not None else set(),
        )
        self.relation_kinds = self._check_list(
            "projectionRelationKinds",
            (
                (kind.value.replace("_", " ").title(), kind.value)
                for kind in SemanticRelationKind
                if kind is not SemanticRelationKind.ANCHORS
            ),
            {item.value for item in existing.relation_kinds} if existing is not None else set(),
        )
        self.direction_choice = self._enum_choice(
            "projectionDirection",
            TraversalDirection,
            existing.direction if existing is not None else TraversalDirection.BOTH,
        )
        self.depth_spin = QSpinBox()
        self.depth_spin.setObjectName("projectionDepth")
        self.depth_spin.setRange(1, 64)
        self.depth_spin.setValue(existing.max_depth if existing is not None else 4)
        self.node_limit_spin = QSpinBox()
        self.node_limit_spin.setObjectName("projectionNodeLimit")
        self.node_limit_spin.setRange(2, 1000)
        self.node_limit_spin.setValue(existing.node_limit if existing is not None else 100)
        self.grouping_choice = self._enum_choice(
            "projectionGrouping",
            ProjectionGrouping,
            existing.grouping if existing is not None else ProjectionGrouping.NONE,
        )
        self.label_choice = self._enum_choice(
            "projectionLabelStyle",
            ProjectionLabelStyle,
            existing.label_style if existing is not None else ProjectionLabelStyle.SHORT,
        )
        self.layout_choice = self._enum_choice(
            "projectionLayout",
            ProjectionLayout,
            existing.layout if existing is not None else ProjectionLayout.HIERARCHICAL,
        )
        self.include_isolated = QCheckBox("Include matching objects with no visible relationship")
        self.include_isolated.setObjectName("projectionIncludeIsolated")
        self.include_isolated.setChecked(
            existing.include_isolated if existing is not None else True
        )
        self.include_scope = QCheckBox("Always keep the selected scope object visible")
        self.include_scope.setObjectName("projectionIncludeScope")
        self.include_scope.setChecked(existing.include_scope if existing is not None else True)
        selected_decorations = (
            {item.value for item in existing.decorations}
            if existing is not None
            else {ProjectionDecoration.KIND.value}
        )
        self.decorations = self._check_list(
            "projectionDecorations",
            ((kind.value.replace("_", " ").title(), kind.value) for kind in ProjectionDecoration),
            selected_decorations,
        )

        form = QFormLayout()
        form.addRow("Lens name", self.title_edit)
        form.addRow("Scope", self.scope_choice)
        form.addRow("Traversal direction", self.direction_choice)
        form.addRow("Maximum relation depth", self.depth_spin)
        form.addRow("Visible object budget", self.node_limit_spin)
        form.addRow("Group by", self.grouping_choice)
        form.addRow("Labels", self.label_choice)
        form.addRow("Layout", self.layout_choice)
        form.addRow("Unconnected matches", self.include_isolated)
        form.addRow("Scope visibility", self.include_scope)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.setObjectName("projectionComposerButtons")
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Choose semantic kinds and relationships. Scope and traversal decide what "
                "is reachable; grouping and layout only change its presentation."
            )
        )
        layout.addLayout(form)
        layout.addWidget(QLabel("Show object kinds (none means all)"))
        layout.addWidget(self.object_kinds, 1)
        layout.addWidget(QLabel("Follow relationships (none means all)"))
        layout.addWidget(self.relation_kinds, 1)
        layout.addWidget(QLabel("Decorate nodes with"))
        layout.addWidget(self.decorations)
        layout.addWidget(buttons)

        if existing is not None:
            index = self.scope_choice.findData(existing.scope_id)
            if index >= 0:
                self.scope_choice.setCurrentIndex(index)

    @staticmethod
    def _check_list(
        object_name: str,
        values: Iterable[tuple[str, str]],
        checked: set[str],
    ) -> QListWidget:
        widget = QListWidget()
        widget.setObjectName(object_name)
        widget.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        for label, value in values:
            item = QListWidgetItem(str(label))
            item.setData(Qt.ItemDataRole.UserRole, str(value))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if value in checked else Qt.CheckState.Unchecked
            )
            widget.addItem(item)
        return widget

    @staticmethod
    def _enum_choice(
        object_name: str,
        enum_type: type[StrEnum],
        current: StrEnum,
    ) -> QComboBox:
        choice = QComboBox()
        choice.setObjectName(object_name)
        for item in enum_type:
            choice.addItem(item.value.replace("_", " ").title(), item.value)
        index = choice.findData(current.value)
        choice.setCurrentIndex(max(0, index))
        return choice

    @staticmethod
    def _checked(widget: QListWidget) -> tuple[str, ...]:
        return tuple(
            str(item.data(Qt.ItemDataRole.UserRole))
            for index in range(widget.count())
            if (item := widget.item(index)).checkState() is Qt.CheckState.Checked
        )

    def definition(self) -> ProjectionDefinition:
        return ProjectionDefinition(
            self._existing_id,
            self.title_edit.text().strip(),
            self.scope_choice.currentData(),
            tuple(SemanticObjectKind(item) for item in self._checked(self.object_kinds)),
            tuple(SemanticRelationKind(item) for item in self._checked(self.relation_kinds)),
            TraversalDirection(str(self.direction_choice.currentData())),
            self.depth_spin.value(),
            ProjectionGrouping(str(self.grouping_choice.currentData())),
            tuple(ProjectionDecoration(item) for item in self._checked(self.decorations)),
            ProjectionLabelStyle(str(self.label_choice.currentData())),
            ProjectionLayout(str(self.layout_choice.currentData())),
            include_scope=self.include_scope.isChecked(),
            include_isolated=self.include_isolated.isChecked(),
            node_limit=self.node_limit_spin.value(),
            expanded_ids=(
                self._existing_definition.expanded_ids
                if self._existing_definition is not None
                else ()
            ),
        )

    def _accept_if_valid(self) -> None:
        if not self.title_edit.text().strip():
            self.title_edit.setFocus()
            return
        self.accept()


class AuthoredRelationDialog(QDialog):
    def __init__(self, source_label: str, target_label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Describe Semantic Relationship")
        self.setObjectName("authoredRelationDialog")
        self._reversed = False
        self.source_label = QLabel(source_label)
        self.target_label = QLabel(target_label)
        self.kind_choice = QComboBox()
        self.kind_choice.setObjectName("authoredRelationKind")
        for kind in AuthoredRelationKind:
            self.kind_choice.addItem(kind.value.replace("_", " ").title(), kind.value)
        self.label_edit = QLineEdit()
        self.label_edit.setObjectName("authoredRelationLabel")
        self.description_edit = QPlainTextEdit()
        self.description_edit.setObjectName("authoredRelationDescription")
        self.description_edit.setMaximumHeight(100)

        form = QFormLayout()
        form.addRow("From", self.source_label)
        form.addRow("To", self.target_label)
        form.addRow("Meaning", self.kind_choice)
        form.addRow("Visible label", self.label_edit)
        form.addRow("Why this matters", self.description_edit)
        self.swap_button = QPushButton("Swap direction")
        self.swap_button.setObjectName("swapAuthoredRelationDirection")
        self.swap_button.clicked.connect(self._swap_direction)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.swap_button)
        layout.addWidget(buttons)

    @property
    def relation_kind(self) -> AuthoredRelationKind:
        return AuthoredRelationKind(str(self.kind_choice.currentData()))

    @property
    def relation_label(self) -> str:
        return self.label_edit.text().strip()

    @property
    def relation_description(self) -> str:
        return self.description_edit.toPlainText().strip()

    @property
    def direction_reversed(self) -> bool:
        return self._reversed

    def _swap_direction(self) -> None:
        source = self.source_label.text()
        self.source_label.setText(self.target_label.text())
        self.target_label.setText(source)
        self._reversed = not self._reversed


class SemanticConceptDialog(QDialog):
    """Name and explain an intentional grouping without moving source ownership."""

    def __init__(self, member_labels: tuple[str, ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Semantic Concept")
        self.setObjectName("semanticConceptDialog")
        self.setMinimumWidth(520)
        self.title_edit = QLineEdit()
        self.title_edit.setObjectName("semanticConceptTitle")
        self.title_edit.setPlaceholderText("For example: Motion safety")
        self.description_edit = QPlainTextEdit()
        self.description_edit.setObjectName("semanticConceptDescription")
        self.description_edit.setPlaceholderText(
            "Explain why these scattered program elements belong together."
        )
        self.description_edit.setMaximumHeight(110)
        self.tags_edit = QLineEdit()
        self.tags_edit.setObjectName("semanticConceptTags")
        self.tags_edit.setPlaceholderText("Optional comma-separated tags")
        members = QListWidget()
        members.setObjectName("semanticConceptMembers")
        members.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        members.setMaximumHeight(150)
        for label in member_labels:
            members.addItem(label)
        form = QFormLayout()
        form.addRow("Concept name", self.title_edit)
        form.addRow("Why it exists", self.description_edit)
        form.addRow("Tags", self.tags_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "This records programmer intent. It does not move modules or create another "
                "executable control-flow truth."
            )
        )
        layout.addLayout(form)
        layout.addWidget(QLabel("Selected semantic members"))
        layout.addWidget(members)
        layout.addWidget(buttons)

    @property
    def concept_title(self) -> str:
        return self.title_edit.text().strip()

    @property
    def concept_description(self) -> str:
        return self.description_edit.toPlainText().strip()

    @property
    def concept_tags(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(item.strip() for item in self.tags_edit.text().split(",") if item.strip())
        )

    def _accept_if_valid(self) -> None:
        if not self.concept_title:
            self.title_edit.setFocus()
            return
        self.accept()
