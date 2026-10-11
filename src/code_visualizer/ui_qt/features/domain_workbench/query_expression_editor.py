"""Readable query editing resolves names into the existing typed domain query AST."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from code_visualizer.domain import language as lang
from code_visualizer.domain.intentional import DomainSchema
from code_visualizer.domain.language_validation import QueryType
from code_visualizer.ui_qt.font_support import register_application_fonts

if TYPE_CHECKING:
    from code_visualizer.application.language_expression import QueryExpressionBinding


def query_bindings_at(
    language: lang.AuthoredDomainLanguage, path: tuple[str | int, ...], schema: DomainSchema
) -> tuple[QueryExpressionBinding, ...]:
    """Build the lexical authoring environment; collection/source slots do not bind themselves."""
    from code_visualizer.application.language_expression import (
        QueryExpressionBinding,
        infer_query_type,
    )

    bindings: list[QueryExpressionBinding] = []
    current: object = language
    for component in path:
        identity: str | None = None
        source: lang.Query | None = None
        element = False
        value_type: QueryType | None = None
        alias = "item"
        if isinstance(current, lang.ValidatorDefinition) and component == "predicate":
            identity = current.binding_id
            value_type = QueryType("node", (current.concept_id,))
        elif (
            isinstance(current, lang.FunctionTemplate)
            and component
            in {
                "display_name",
                "parameters",
                "body",
            }
        ) or (isinstance(current, lang.DomainNodeTemplate) and component != "source"):
            identity, source, element, alias = current.binding_id, current.source, True, "source"
        elif isinstance(current, lang.TemplateExpand) and component == "body":
            identity, source, element = current.binding_id, current.collection, True
        elif isinstance(current, lang.TemplateLet) and component == "body":
            identity, source, alias = current.binding_id, current.value, "value"
        elif (
            isinstance(current, (lang.QueryMap, lang.QueryFilter, lang.QueryAll, lang.QueryUnique))
            and component != "collection"
        ):
            identity, source, element = current.binding_id, current.collection, True
        if identity is not None:
            if source is not None:
                try:
                    value_type = infer_query_type(source, schema, bindings=tuple(bindings))
                except ValueError:
                    value_type = QueryType("unknown")
                if element:
                    value_type = value_type.element or QueryType("unknown")
            used = {item.name for item in bindings}
            suffix = 2
            name = alias
            while name in used:
                name = f"{alias}{suffix}"
                suffix += 1
            value_type = value_type or QueryType("unknown")
            bindings.append(
                QueryExpressionBinding(identity, name, value_type.concept_ids, value_type)
            )
        if isinstance(component, int) and isinstance(current, tuple):
            current = current[component]
        else:
            current = getattr(current, str(component))
    return tuple(bindings)


class QueryExpressionDialog(QDialog):
    def __init__(
        self,
        query: lang.Query,
        schema: DomainSchema,
        bindings: tuple[QueryExpressionBinding, ...] = (),
        parent: QWidget | None = None,
    ) -> None:
        from code_visualizer.application.language_expression import format_query_expression

        super().__init__(parent)
        self.setObjectName("queryExpressionEditor")
        self.setWindowTitle("Edit domain query")
        self.resize(840, 480)
        self.query, self.schema, self.bindings = query, schema, bindings
        self._valid = False
        self.editor = QPlainTextEdit()
        self.editor.setObjectName("queryExpressionText")
        self.editor.setFont(QFont(register_application_fonts().code, 11))
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        try:
            initial = format_query_expression(query, schema, bindings=bindings)
        except ValueError:
            initial = "hole()"
        self.editor.setPlainText(initial)
        self.status = QLabel()
        self.status.setObjectName("queryExpressionStatus")
        self.status.setWordWrap(True)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.validate_expression)
        self.editor.textChanged.connect(lambda: self.timer.start())
        layout = QVBoxLayout(self)
        help_text = QLabel(
            "Use property and role names, comparisons, and, or, count(…), first(…), "
            "nodes('Concept'), or where(…). These expressions describe domain data."
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text)

        def describe(binding: QueryExpressionBinding) -> str:
            names = [
                concept.name
                for identity in binding.concept_ids
                if (concept := schema.concept(identity)) is not None
            ]
            kind = ", ".join(names) or (binding.value_type.kind if binding.value_type else "value")
            return f"{binding.name} ({kind})"

        choices = QLabel(
            "Available objects: "
            + (
                ", ".join(describe(item) for item in bindings)
                or "none; begin with nodes('Concept')"
            )
        )
        choices.setWordWrap(True)
        layout.addWidget(choices)
        layout.addWidget(self.editor, 1)
        check = QPushButton("Check expression")
        check.setObjectName("queryExpressionCheck")
        check.clicked.connect(self.validate_expression)
        layout.addWidget(check)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.validate_expression()

    def validate_expression(self) -> None:
        from code_visualizer.application.language_expression import (
            infer_query_type,
            parse_query_expression,
        )

        self.timer.stop()
        try:
            query = parse_query_expression(
                self.editor.toPlainText(), self.schema, bindings=self.bindings, existing=self.query
            )
            result = infer_query_type(query, self.schema, bindings=self.bindings)
            self.query, self._valid = query, True
            self.status.setText(
                f"Checked {result.kind} expression. "
                "Save applies the typed query to this language draft."
            )
        except (TypeError, ValueError) as exc:
            self._valid = False
            self.status.setText(str(exc))

    def _accept(self) -> None:
        self.validate_expression()
        if self._valid:
            self.accept()
