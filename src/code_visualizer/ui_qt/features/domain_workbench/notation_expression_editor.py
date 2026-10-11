"""A readable, typed notation expression with a disposable live preview."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from code_visualizer.application.notation_canvas import compile_notation_canvas
from code_visualizer.domain.intentional import DomainSchema, DomainWorkspace
from code_visualizer.domain.notation import NotationDefinition, NotationKind
from code_visualizer.domain.notation_syntax import Visual, VisualText
from code_visualizer.domain.project import Project
from code_visualizer.domain.semantic import SemanticRelation
from code_visualizer.ui_qt.font_support import register_application_fonts

from .composed_canvas import ComposedCanvasWidget


class NotationExpressionDialog(QDialog):
    """Parsing changes a typed draft; Save remains the authority boundary."""

    def __init__(
        self,
        definition: NotationDefinition,
        schema: DomainSchema,
        workspace: DomainWorkspace,
        project: Project | None = None,
        parent: QWidget | None = None,
        *,
        semantic_relations: tuple[SemanticRelation, ...] | None = None,
    ) -> None:
        from code_visualizer.application.notation_expression import format_notation_expression

        super().__init__(parent)
        self.setObjectName("notationExpressionEditor")
        self.setWindowTitle(f"Compose notation — {definition.title}")
        self.resize(1100, 740)
        self.definition, self.schema, self.workspace, self.project = (
            definition,
            schema,
            workspace,
            project,
        )
        self.body: Visual = definition.body or VisualText(f"{definition.id}:body", "Your notation")
        if semantic_relations is None and project is not None:
            from code_visualizer.application.queries import ProjectQueries

            semantic_relations = ProjectQueries.from_project(project).program.relations
        self.semantic_relations = semantic_relations or ()
        self.editor = QPlainTextEdit()
        self.editor.setObjectName("notationExpressionText")
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.setFont(QFont(register_application_fonts().code, 11))
        self.editor.setPlainText(format_notation_expression(self.body, schema, workspace=workspace))
        self.preview = ComposedCanvasWidget()
        self.preview.status.setText(
            "Preview of the notation draft. Open the saved view to edit object fields."
        )
        self.models = QComboBox()
        self.models.setObjectName("notationPreviewModel")
        for model in workspace.models:
            if model.schema_id == schema.id:
                self.models.addItem(model.title or model.id, model.id)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName("notationExpressionStatus")
        self._valid = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.update_preview)
        self.editor.textChanged.connect(lambda: self.timer.start())
        self.models.currentIndexChanged.connect(self.update_preview)
        layout = QVBoxLayout(self)
        help_text = QLabel(
            "Compose typed visual elements using row(…), column(…), box(…), text('…'), "
            "field('object', 'Property'), fraction(…), and superscript(…). "
            "each('Concept', 'object', …) repeats over objects; related(…) follows semantic links. "
            "Use schema names and property names from your domain. Bound fields stay editable."
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Preview model"))
        bar.addWidget(self.models, 1)
        refresh = QPushButton("Preview")
        refresh.setObjectName("notationPreviewButton")
        refresh.clicked.connect(self.update_preview)
        bar.addWidget(refresh)
        layout.addLayout(bar)
        splitter = QSplitter()
        splitter.addWidget(self.editor)
        splitter.addWidget(self.preview)
        splitter.setSizes([520, 560])
        layout.addWidget(splitter, 1)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.update_preview()

    def update_preview(self) -> None:
        from code_visualizer.application.notation_expression import parse_notation_expression
        from code_visualizer.domain.notation_validation import validate_composed_notation

        self.timer.stop()
        try:
            body = parse_notation_expression(
                self.editor.toPlainText(), self.schema, workspace=self.workspace, existing=self.body
            )
            issues = validate_composed_notation(body, self.schema, self.workspace)
            fatal = tuple(issue for issue in issues if not issue.incomplete)
            if fatal:
                raise ValueError(fatal[0].message)
            self.body = body
            self._valid = True
            if self.project is not None and self.models.currentData():
                self.preview.set_canvas(
                    compile_notation_canvas(
                        self.project,
                        str(self.models.currentData()),
                        replace(self.definition, kind=NotationKind.COMPOSED, body=body),
                        relations=self.semantic_relations,
                    )
                )
                self.status.setText(
                    "Preview updated. Save applies this typed notation to the language draft."
                )
            else:
                self.status.setText("Expression is valid. Create a model to preview its objects.")
        except (TypeError, ValueError) as exc:
            self._valid = False
            self.status.setText(str(exc))

    def _accept(self) -> None:
        self.update_preview()
        if self._valid:
            self.accept()
