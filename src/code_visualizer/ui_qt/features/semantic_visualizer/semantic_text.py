"""Command-backed textual interface into selected semantic program fields."""

from __future__ import annotations

from dataclasses import dataclass, replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from code_visualizer.application.commands import SetProgramDeclarationText
from code_visualizer.application.drakon_program_adapter import function_spec
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.messages import CommandAccepted, CommandRejected
from code_visualizer.application.notations import (
    NotationEditBinding,
    field_cell,
    notation_edit_command,
)
from code_visualizer.application.selection import SelectionState
from code_visualizer.application.semantic_text import (
    SemanticTextProjection,
    render_semantic_text,
)
from code_visualizer.domain.drakon import DrakonDiagram
from code_visualizer.domain.intentional import ValueKind
from code_visualizer.domain.notation import NotationField
from code_visualizer.domain.program import (
    ProgramClass,
    ProgramExpression,
    ProgramModule,
    ProgramNote,
    iter_program_nodes,
    program_node_id,
)
from code_visualizer.domain.project import Project
from code_visualizer.domain.semantic import (
    SemanticObject,
    SemanticObjectKind,
    SemanticProjection,
)
from code_visualizer.sdk import CodeVisualizerClient


@dataclass(frozen=True, slots=True)
class _EditTarget:
    kind: str
    owner_id: str
    field: str
    label: str
    value: str
    document_id: str | None = None
    notation_binding: NotationEditBinding | None = None


class SemanticTextWidget(QWidget):
    """Text is another authority client, never a detached source-of-truth buffer."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("semanticTextEditor")
        self._kernel: ProjectKernel | None = None
        self._client: CodeVisualizerClient | None = None
        self._text_projection: SemanticTextProjection | None = None
        self._targets: tuple[_EditTarget, ...] = ()
        self._applying_cursor = False

        self.outline = QPlainTextEdit()
        self.outline.setObjectName("semanticTextProjection")
        self.outline.setAccessibleName("Semantic text projection")
        self.outline.setReadOnly(True)
        self.outline.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.outline.cursorPositionChanged.connect(self._outline_cursor_changed)

        explanation = QLabel(
            "This text describes the canonical semantic lens. Select a line to share focus; "
            "edit supported fields below to issue typed commands. Generated Python remains an "
            "artifact, not a second editable truth."
        )
        explanation.setWordWrap(True)
        self.field_choice = QComboBox()
        self.field_choice.setObjectName("semanticTextField")
        self.field_choice.currentIndexChanged.connect(self._load_field)
        self.field_editor = QPlainTextEdit()
        self.field_editor.setObjectName("semanticTextFieldValue")
        self.field_editor.setAccessibleName("Selected canonical field text")
        self.field_editor.setMaximumHeight(150)
        self.apply_button = QPushButton("Apply semantic text change")
        self.apply_button.setObjectName("applySemanticTextChange")
        self.apply_button.clicked.connect(self._apply)
        self.status = QLabel("Select a semantic object or relationship to edit its text.")
        self.status.setObjectName("semanticTextStatus")
        self.status.setWordWrap(True)

        field_row = QHBoxLayout()
        field_row.addWidget(QLabel("Canonical field:"))
        field_row.addWidget(self.field_choice, 1)
        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.addWidget(explanation)
        editor_layout.addLayout(field_row)
        editor_layout.addWidget(self.field_editor)
        editor_layout.addWidget(self.apply_button)
        editor_layout.addWidget(self.status)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setObjectName("semanticTextSplitter")
        splitter.addWidget(self.outline)
        splitter.addWidget(editor)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)
        self._set_editor_enabled(False)

    def attach(
        self,
        kernel: ProjectKernel | None,
        client: CodeVisualizerClient | None,
    ) -> None:
        self._kernel = kernel
        self._client = client
        if kernel is None:
            self.outline.clear()
            self._targets = ()
            self.field_choice.clear()
            self._set_editor_enabled(False)

    def set_projection(self, projection: SemanticProjection) -> None:
        kernel = self._kernel
        current = kernel.selection.state.primary if kernel is not None else None
        self._text_projection = render_semantic_text(projection)
        self._applying_cursor = True
        try:
            self.outline.setPlainText(self._text_projection.source)
        finally:
            self._applying_cursor = False
        if current is not None and kernel is not None:
            self.apply_selection(kernel.selection.state)

    def apply_selection(self, state: SelectionState) -> None:
        primary = state.primary
        if primary is None:
            self._load_targets(None)
            return
        projection = self._text_projection
        if projection is not None:
            try:
                line = projection.line_semantic_ids.index(primary)
            except ValueError:
                line = -1
            if line >= 0:
                block = self.outline.document().findBlockByNumber(line)
                cursor = QTextCursor(block)
                self._applying_cursor = True
                try:
                    self.outline.setTextCursor(cursor)
                    self.outline.centerCursor()
                finally:
                    self._applying_cursor = False
        self._load_targets(primary)

    def _outline_cursor_changed(self) -> None:
        if self._applying_cursor or self._kernel is None or self._text_projection is None:
            return
        line = self.outline.textCursor().blockNumber()
        if not 0 <= line < len(self._text_projection.line_semantic_ids):
            return
        semantic_id = self._text_projection.line_semantic_ids[line]
        if semantic_id is None:
            return
        self._kernel.selection.select(
            (semantic_id,),
            revision=self._kernel.revision,
            source="ui.semantic_text",
        )

    def _load_targets(self, semantic_id: str | None) -> None:
        self._targets = self._edit_targets(semantic_id)
        self.field_choice.blockSignals(True)
        self.field_choice.clear()
        for index, target in enumerate(self._targets):
            self.field_choice.addItem(target.label, index)
        self.field_choice.blockSignals(False)
        self._set_editor_enabled(bool(self._targets) and self._client is not None)
        if self._targets:
            self.field_choice.setCurrentIndex(0)
            self._load_field(0)
            self.status.setText(
                "Editing this field submits a typed command to the shared project authority."
            )
        else:
            self.field_editor.clear()
            self.status.setText(
                "This semantic item is read-only in the initial text surface. "
                "Use its specialized editor for structural changes."
            )

    def _edit_targets(self, semantic_id: str | None) -> tuple[_EditTarget, ...]:
        if semantic_id is None or self._kernel is None:
            return ()
        project = self._kernel.authority.snapshot()
        for model in project.domain_workspace.models:
            node = model.node(semantic_id)
            schema = project.domain_workspace.schema(model.schema_id)
            if node is None or schema is None:
                continue
            definition = schema.concept(node.concept_id)
            if definition is None:
                return ()
            targets = []
            for prop in definition.properties:
                if prop.value_kind is not ValueKind.STRING:
                    continue
                cell = field_cell(
                    schema,
                    model,
                    node,
                    NotationField(prop.id),
                    cell_id=f"semantic-text:{node.id}:{prop.id}",
                    revision=project.revision,
                )
                targets.append(
                    _EditTarget(
                        "domain",
                        node.id,
                        prop.id,
                        prop.name,
                        cell.text,
                        notation_binding=cell.edit,
                    )
                )
            return tuple(targets)
        if semantic_id == project.id:
            return (_EditTarget("project", project.id, "title", "Project title", project.title),)
        for declaration in iter_program_nodes(
            (project.program_model.modules, project.program_model.entrypoint)
        ):
            if getattr(declaration, "id", None) != semantic_id:
                continue
            editable_fields = (
                ("path", "docstring")
                if isinstance(declaration, ProgramModule)
                else ("identifier", "docstring")
                if isinstance(declaration, ProgramClass)
                else ("source",)
                if isinstance(declaration, ProgramExpression)
                else ("text",)
                if isinstance(declaration, ProgramNote)
                else ()
            )
            if editable_fields:
                return tuple(
                    _EditTarget(
                        "program_declaration",
                        program_node_id(declaration),
                        field,
                        field.replace("_", " ").title(),
                        getattr(declaration, field) or "",
                    )
                    for field in editable_fields
                )
        authored_relation = next(
            (item for item in project.semantic_relations if item.id == semantic_id),
            None,
        )
        if authored_relation is not None:
            return (
                _EditTarget(
                    "relation",
                    authored_relation.id,
                    "label",
                    "Relationship label",
                    authored_relation.label,
                ),
                _EditTarget(
                    "relation",
                    authored_relation.id,
                    "description",
                    "Relationship explanation",
                    authored_relation.description,
                ),
            )
        semantic = self._kernel.queries.semantic_object(semantic_id)
        if semantic is None:
            return ()
        if semantic.kind is SemanticObjectKind.CONCEPT:
            concept = next((item for item in project.concepts if item.id == semantic.id), None)
            if concept is None:
                return ()
            return (
                _EditTarget("concept", concept.id, "title", "Concept name", concept.title),
                _EditTarget(
                    "concept",
                    concept.id,
                    "description",
                    "Concept explanation",
                    concept.description,
                ),
                _EditTarget(
                    "concept",
                    concept.id,
                    "tags",
                    "Concept tags (comma-separated)",
                    ", ".join(concept.tags),
                ),
            )
        if semantic.kind is SemanticObjectKind.FUNCTION:
            function = project.program_model.function(semantic.id)
            if function is None:
                return ()
            return (
                _EditTarget(
                    "function",
                    function.id,
                    "identifier",
                    "Python function name",
                    function.identifier,
                ),
                _EditTarget(
                    "function",
                    function.id,
                    "display_name",
                    "Human-facing function name",
                    function.display_name,
                ),
                _EditTarget(
                    "function",
                    function.id,
                    "docstring",
                    "Function documentation",
                    function.docstring or "",
                ),
            )
        expression_targets = self._expression_targets(semantic)
        if expression_targets:
            return expression_targets
        if semantic.kind is SemanticObjectKind.OPERATION:
            roots = tuple(
                item
                for item in self._kernel.queries.program.objects
                if item.parent_id == semantic.id
                and item.kind is SemanticObjectKind.EXPRESSION
                and item.field is not None
            )
            result: list[_EditTarget] = []
            for root in sorted(roots, key=lambda item: (item.field or "", item.id)):
                result.extend(self._expression_targets(root))
            return tuple(result)
        return ()

    @staticmethod
    def _source_property(semantic: SemanticObject) -> str:
        return next(
            (item.value for item in semantic.properties if item.name == "source"),
            semantic.detail,
        )

    def _expression_targets(self, semantic: SemanticObject) -> tuple[_EditTarget, ...]:
        if (
            semantic.kind is not SemanticObjectKind.EXPRESSION
            or semantic.parent_id is None
            or semantic.document_id is None
            or semantic.field is None
            or ":node:" in semantic.id
        ):
            return ()
        return (
            _EditTarget(
                "drakon",
                semantic.parent_id,
                semantic.field,
                semantic.field.replace("_", " ").title(),
                self._source_property(semantic),
                semantic.document_id,
            ),
        )

    def _load_field(self, index: int) -> None:
        if not 0 <= index < len(self._targets):
            return
        self.field_editor.setPlainText(self._targets[index].value)

    def _apply(self) -> None:
        if self._client is None or self._kernel is None:
            return
        index = self.field_choice.currentData()
        if not isinstance(index, int) or not 0 <= index < len(self._targets):
            return
        target = self._targets[index]
        value = self.field_editor.toPlainText()
        project = self._kernel.authority.snapshot()
        if target.kind == "project":
            result = self._client.rename_project(value)
        elif target.kind == "domain" and target.notation_binding is not None:
            try:
                command = notation_edit_command(
                    target.notation_binding,
                    value,
                    revision=project.revision,
                )
            except ValueError as exc:
                self.status.setText(str(exc))
                return
            result = self._client.submit(
                command, expected_revision=target.notation_binding.revision
            )
        elif target.kind == "drakon" and target.document_id is not None:
            result = self._client.set_drakon_text(
                target.document_id,
                target.owner_id,
                target.field,
                value,
            )
        elif target.kind == "program_declaration":
            result = self._client.submit(
                SetProgramDeclarationText(target.owner_id, target.field, value)
            )
        elif target.kind == "function":
            canonical = project.program_model.function(target.owner_id)
            if canonical is None:
                return
            signature = function_spec(canonical, project.program_model)
            if target.field == "identifier":
                function = replace(signature, identifier=value)
            elif target.field == "display_name":
                function = replace(signature, display_name=value)
            else:
                function = replace(signature, docstring=value or None)
            result = self._client.replace_program_function_signature(canonical.id, function)
        elif target.kind == "concept":
            concept = next(
                (item for item in project.concepts if item.id == target.owner_id),
                None,
            )
            if concept is None:
                return
            if target.field == "title":
                updated_concept = replace(concept, title=value)
            elif target.field == "description":
                updated_concept = replace(concept, description=value)
            else:
                tags = tuple(
                    dict.fromkeys(item.strip() for item in value.split(",") if item.strip())
                )
                updated_concept = replace(concept, tags=tags)
            result = self._client.put_semantic_concept(updated_concept)
        elif target.kind == "relation":
            relation = next(
                (item for item in project.semantic_relations if item.id == target.owner_id),
                None,
            )
            if relation is None:
                return
            updated_relation = (
                replace(relation, label=value)
                if target.field == "label"
                else replace(relation, description=value)
            )
            result = self._client.put_authored_semantic_relation(updated_relation)
        else:
            return
        if isinstance(result, CommandAccepted):
            self.status.setText(f"Applied {target.label} at revision {result.revision}.")
        elif isinstance(result, CommandRejected):
            self.status.setText(f"{result.code}: {result.message}")

    def _set_editor_enabled(self, enabled: bool) -> None:
        self.field_choice.setEnabled(enabled)
        self.field_editor.setEnabled(enabled)
        self.apply_button.setEnabled(enabled)


def _drakon_document(project: Project, document_id: str | None) -> DrakonDiagram | None:
    return next(
        (
            item
            for item in project.documents
            if isinstance(item, DrakonDiagram) and item.id == document_id
        ),
        None,
    )
