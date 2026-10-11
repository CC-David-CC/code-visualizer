"""Structured, schema-aware editing of inert domain language definitions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, fields, is_dataclass, replace
from enum import StrEnum
from typing import Any, cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from code_visualizer.domain import language as lang
from code_visualizer.domain import notation_syntax as visual
from code_visualizer.domain.common import new_id
from code_visualizer.domain.intentional import DomainSchema, DomainWorkspace
from code_visualizer.domain.notation import (
    NotationColumn,
    NotationDefinition,
    NotationEdgeRule,
    NotationField,
    NotationKind,
    NotationNodeRule,
)
from code_visualizer.domain.program_kinds import TransferKind
from code_visualizer.domain.project import Project
from code_visualizer.domain.projection import ProjectionLayout
from code_visualizer.domain.semantic import SemanticRelation
from code_visualizer.domain.transformation import (
    PROGRAM_REPRESENTATION,
    Representation,
    TransformationDefinition,
)

type EditPath = tuple[str | int, ...]

_QUERIES: tuple[type[object], ...] = (
    lang.QueryHole,
    lang.QueryLiteral,
    lang.QueryVariable,
    lang.QueryNodes,
    lang.QueryRole,
    lang.QueryProperty,
    lang.QueryIdentity,
    lang.QueryUnary,
    lang.QueryBinary,
    lang.QueryTuple,
    lang.QueryMap,
    lang.QueryFilter,
    lang.QueryAll,
    lang.QueryUnique,
)
_EXPRESSIONS: tuple[type[object], ...] = (
    lang.RuntimeHole,
    lang.RuntimeLiteral,
    lang.RuntimeVariable,
    lang.RuntimeBinary,
    lang.RuntimeCall,
)
_STATEMENTS: tuple[type[object], ...] = (
    lang.TemplateHole,
    lang.TemplateExpand,
    lang.TemplateWhen,
    lang.TemplateLet,
    lang.TemplateAssignment,
    lang.TemplateOutput,
    lang.TemplateIf,
    lang.TemplateFor,
    lang.TemplateTransfer,
)
_VISUALS: tuple[type[object], ...] = (
    visual.VisualHole,
    visual.VisualText,
    visual.VisualField,
    visual.VisualGroup,
    visual.VisualBox,
    visual.VisualPosition,
    visual.VisualRepeat,
    visual.VisualConditional,
    visual.VisualFraction,
    visual.VisualScript,
    visual.VisualPath,
    visual.VisualConnector,
)
_VISUAL_QUERIES: tuple[type[object], ...] = (
    visual.NotationObjects,
    visual.NotationRelated,
    visual.NotationQueryHole,
)
_LABELS: dict[type[object], str] = {
    lang.AuthoredDomainLanguage: "Domain language",
    NotationDefinition: "Notation",
    NotationColumn: "Table column",
    NotationField: "Property or reference binding",
    NotationNodeRule: "Graph node / hierarchy label",
    NotationEdgeRule: "Graph relationship",
    lang.ValidatorDefinition: "Validation rule",
    lang.AuthoredTransformation: "Transformation",
    lang.DomainTemplate: "Domain output",
    lang.DomainNodeTemplate: "Create target objects",
    lang.DomainPropertyTemplate: "Set target property",
    lang.DomainRoleTemplate: "Bind target role",
    TransformationDefinition: "Transformation contract",
    Representation: "Representation",
    lang.FunctionTemplate: "Function template",
    lang.TemplateParameter: "Function parameter",
    lang.TemplateSymbol: "Local variable",
    lang.QueryHole: "Choose a query",
    lang.QueryLiteral: "Literal value",
    lang.QueryVariable: "Bound domain object",
    lang.QueryNodes: "Objects of concept",
    lang.QueryRole: "Follow role",
    lang.QueryProperty: "Read property",
    lang.QueryIdentity: "Object identity",
    lang.QueryUnary: "Unary query",
    lang.QueryBinary: "Compare / combine queries",
    lang.QueryTuple: "Tuple of values",
    lang.QueryMap: "Map each object",
    lang.QueryFilter: "Filter objects",
    lang.QueryAll: "Every object satisfies",
    lang.QueryUnique: "Values are unique",
    lang.RuntimeHole: "Choose a runtime expression",
    lang.RuntimeLiteral: "Value from domain query",
    lang.RuntimeVariable: "Runtime variable",
    lang.RuntimeBinary: "Runtime operation",
    lang.RuntimeCall: "Built-in operation",
    lang.TemplateHole: "Choose a statement template",
    lang.TemplateExpand: "Expand for each object at build time",
    lang.TemplateWhen: "Include when query is true",
    lang.TemplateLet: "Bind domain value at build time",
    lang.TemplateAssignment: "Assign runtime variable",
    lang.TemplateOutput: "Output value",
    lang.TemplateIf: "Runtime decision",
    lang.TemplateFor: "Runtime loop",
    lang.TemplateTransfer: "Return / raise / transfer",
    visual.VisualHole: "Choose a visual element",
    visual.VisualText: "Text / token",
    visual.VisualField: "Editable domain field",
    visual.VisualGroup: "Row / column / wrapping layout",
    visual.VisualBox: "Box / shape",
    visual.VisualPosition: "Position / timeline placement",
    visual.VisualRepeat: "Display each object",
    visual.VisualConditional: "Conditional display",
    visual.VisualFraction: "Fraction",
    visual.VisualScript: "Superscript / subscript",
    visual.VisualPath: "Path / line",
    visual.VisualConnector: "Connect displayed objects",
    visual.VisualPoint: "Path point",
    visual.VisualNumber: "Number / numeric property",
    visual.VisualPredicate: "Display condition",
    visual.NotationObjects: "Objects from a domain",
    visual.NotationRelated: "Follow a role or semantic relationship",
    visual.NotationQueryHole: "Choose objects",
}


@dataclass(frozen=True, slots=True)
class _Slot:
    variants: tuple[type[object], ...]
    multiple: bool = False
    optional: bool = False


def _slot(*variants: type[object], multiple: bool = False, optional: bool = False) -> _Slot:
    return _Slot(variants, multiple, optional)


_SLOTS: dict[type[object], dict[str, _Slot]] = {
    lang.AuthoredDomainLanguage: {
        "notations": _slot(NotationDefinition, multiple=True),
        "validators": _slot(lang.ValidatorDefinition, multiple=True),
        "transformations": _slot(lang.AuthoredTransformation, multiple=True),
    },
    NotationDefinition: {
        "concept_ids": _slot(str, multiple=True),
        "node_rules": _slot(NotationNodeRule, multiple=True),
        "edge_rules": _slot(NotationEdgeRule, multiple=True),
        "columns": _slot(NotationColumn, multiple=True),
        "body": _slot(*_VISUALS, optional=True),
    },
    NotationColumn: {"field": _slot(NotationField)},
    NotationField: {"reference_role_ids": _slot(str, multiple=True)},
    NotationNodeRule: {"label_fields": _slot(NotationField, multiple=True)},
    NotationEdgeRule: {"label_fields": _slot(NotationField, multiple=True)},
    lang.ValidatorDefinition: {"predicate": _slot(*_QUERIES)},
    lang.AuthoredTransformation: {
        "definition": _slot(TransformationDefinition),
        "functions": _slot(lang.FunctionTemplate, multiple=True),
        "domain": _slot(lang.DomainTemplate, optional=True),
    },
    lang.DomainTemplate: {"nodes": _slot(lang.DomainNodeTemplate, multiple=True)},
    lang.DomainNodeTemplate: {
        "source": _slot(*_QUERIES),
        "properties": _slot(lang.DomainPropertyTemplate, multiple=True),
        "children": _slot(lang.DomainRoleTemplate, multiple=True),
        "references": _slot(lang.DomainRoleTemplate, multiple=True),
        "origins": _slot(*_QUERIES, multiple=True),
    },
    lang.DomainPropertyTemplate: {"value": _slot(*_QUERIES)},
    lang.DomainRoleTemplate: {"sources": _slot(*_QUERIES)},
    visual.VisualField: {"reference_role_ids": _slot(str, multiple=True)},
    visual.VisualGroup: {"children": _slot(*_VISUALS, multiple=True)},
    visual.VisualBox: {
        "body": _slot(*_VISUALS),
        "width": _slot(visual.VisualNumber, optional=True),
        "height": _slot(visual.VisualNumber, optional=True),
    },
    visual.VisualPosition: {
        "body": _slot(*_VISUALS),
        "x": _slot(visual.VisualNumber),
        "y": _slot(visual.VisualNumber),
    },
    visual.VisualRepeat: {"query": _slot(*_VISUAL_QUERIES), "body": _slot(*_VISUALS)},
    visual.VisualConditional: {
        "predicate": _slot(visual.VisualPredicate),
        "body": _slot(*_VISUALS),
        "otherwise": _slot(*_VISUALS, optional=True),
    },
    visual.VisualFraction: {"numerator": _slot(*_VISUALS), "denominator": _slot(*_VISUALS)},
    visual.VisualScript: {"base": _slot(*_VISUALS), "script": _slot(*_VISUALS)},
    visual.VisualPath: {"points": _slot(visual.VisualPoint, multiple=True)},
    visual.VisualPoint: {"x": _slot(visual.VisualNumber), "y": _slot(visual.VisualNumber)},
    TransformationDefinition: {
        "source": _slot(Representation),
        "target": _slot(Representation),
        "depends_on": _slot(str, multiple=True),
    },
    lang.FunctionTemplate: {
        "source": _slot(*_QUERIES),
        "display_name": _slot(*_QUERIES, optional=True),
        "parameters": _slot(lang.TemplateParameter, multiple=True),
        "symbols": _slot(lang.TemplateSymbol, multiple=True),
        "body": _slot(*_STATEMENTS, multiple=True),
    },
    lang.TemplateParameter: {"default": _slot(*_EXPRESSIONS, optional=True)},
    lang.QueryRole: {"source": _slot(*_QUERIES)},
    lang.QueryProperty: {"source": _slot(*_QUERIES)},
    lang.QueryIdentity: {"source": _slot(*_QUERIES)},
    lang.QueryUnary: {"operand": _slot(*_QUERIES)},
    lang.QueryBinary: {"left": _slot(*_QUERIES), "right": _slot(*_QUERIES)},
    lang.QueryTuple: {"items": _slot(*_QUERIES, multiple=True)},
    lang.QueryMap: {"collection": _slot(*_QUERIES), "value": _slot(*_QUERIES)},
    lang.QueryFilter: {"collection": _slot(*_QUERIES), "predicate": _slot(*_QUERIES)},
    lang.QueryAll: {"collection": _slot(*_QUERIES), "predicate": _slot(*_QUERIES)},
    lang.QueryUnique: {"collection": _slot(*_QUERIES), "key": _slot(*_QUERIES)},
    lang.RuntimeLiteral: {"query": _slot(*_QUERIES)},
    lang.RuntimeBinary: {"left": _slot(*_EXPRESSIONS), "right": _slot(*_EXPRESSIONS)},
    lang.RuntimeCall: {"arguments": _slot(*_EXPRESSIONS, multiple=True)},
    lang.TemplateExpand: {
        "collection": _slot(*_QUERIES),
        "body": _slot(*_STATEMENTS, multiple=True),
    },
    lang.TemplateWhen: {"predicate": _slot(*_QUERIES), "body": _slot(*_STATEMENTS, multiple=True)},
    lang.TemplateLet: {"value": _slot(*_QUERIES), "body": _slot(*_STATEMENTS, multiple=True)},
    lang.TemplateAssignment: {
        "value": _slot(*_EXPRESSIONS),
        "origins": _slot(*_QUERIES, multiple=True),
    },
    lang.TemplateOutput: {
        "value": _slot(*_EXPRESSIONS),
        "origins": _slot(*_QUERIES, multiple=True),
    },
    lang.TemplateIf: {
        "condition": _slot(*_EXPRESSIONS),
        "true_body": _slot(*_STATEMENTS, multiple=True),
        "false_body": _slot(*_STATEMENTS, multiple=True),
        "origins": _slot(*_QUERIES, multiple=True),
    },
    lang.TemplateFor: {
        "iterable": _slot(*_EXPRESSIONS),
        "body": _slot(*_STATEMENTS, multiple=True),
        "origins": _slot(*_QUERIES, multiple=True),
    },
    lang.TemplateTransfer: {
        "value": _slot(*_EXPRESSIONS, optional=True),
        "origins": _slot(*_QUERIES, multiple=True),
    },
}

_FIELD_LABELS = {
    "concept_ids": "Included concepts",
    "concept_id": "Concept",
    "reference_role_ids": "Reference path (in order)",
    "property_id": "Property",
    "label_property_id": "Label property",
    "source_role_id": "Source reference",
    "target_role_id": "Target reference",
    "role_id": "Role",
    "binding_id": "Bound domain object",
    "symbol_id": "Runtime variable",
    "source": "Source",
    "display_name": "Display label query",
    "origins": "Runtime source objects",
    "identifier_prefix": "Function name prefix",
    "node_rules": "Node labels",
    "edge_rules": "Relationships",
    "columns": "Table columns",
    "label_fields": "Derived label fields",
    "default": "Default value",
    "entrypoint": "Run this function",
    "roots_only": "Root objects only",
}


def _field_label(name: str) -> str:
    return _FIELD_LABELS.get(name, name.replace("_", " ").capitalize())


def language_kind_label(value: object) -> str:
    return _LABELS.get(type(value), "Definition")


def _at(value: object, path: EditPath) -> object:
    for component in path:
        value = (
            value[component]
            if isinstance(component, int) and isinstance(value, tuple)
            else getattr(value, str(component))
        )
    return value


def _replace_at(value: object, path: EditPath, replacement: object) -> object:
    if not path:
        return replacement
    first, *remaining = path
    if isinstance(first, int) and isinstance(value, tuple):
        return tuple(
            _replace_at(item, tuple(remaining), replacement) if index == first else item
            for index, item in enumerate(value)
        )
    if isinstance(first, str) and is_dataclass(value) and not isinstance(value, type):
        return replace(
            value, **{first: _replace_at(getattr(value, first), tuple(remaining), replacement)}
        )
    raise ValueError("The selected definition no longer exists")


class LanguageEditorDialog(QDialog):
    """Build typed trees through choices and fields, preserving all existing identities."""

    def __init__(
        self,
        schema: DomainSchema,
        existing: lang.AuthoredDomainLanguage | None = None,
        parent: QWidget | None = None,
        *,
        workspace: DomainWorkspace | None = None,
        project: Project | None = None,
        semantic_relations: tuple[SemanticRelation, ...] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("domainLanguageEditor")
        self.setWindowTitle("Domain language — notations, validation, and transformations")
        self.resize(1050, 720)
        self.schema = schema
        self.workspace = workspace or DomainWorkspace(schemas=(schema,))
        self.project = project
        self.semantic_relations = semantic_relations
        self._value = existing or lang.AuthoredDomainLanguage(
            new_id("domain-language"),
            schema.id,
            schema.version,
            title=f"{schema.namespace} language",
        )
        self._path: EditPath = ()
        self._controls: dict[str, QWidget] = {}
        self.tree = QTreeWidget()
        self.tree.setObjectName("languageDefinitionTree")
        self.tree.setHeaderLabels(["Definition / slot", "Value"])
        self.tree.setMinimumWidth(400)
        self.tree.currentItemChanged.connect(self._selected)
        self.variant = QComboBox()
        self.variant.setObjectName("languageNodeVariant")
        self.variant.setAccessibleName("Expression or definition kind")
        self.add_button = QPushButton("Add item")
        self.add_button.setObjectName("languageAddItem")
        self.add_button.clicked.connect(self.add_item)
        self.replace_button = QPushButton("Set kind")
        self.replace_button.setObjectName("languageSetKind")
        self.replace_button.clicked.connect(self.set_kind)
        self.remove_button = QPushButton("Remove")
        self.remove_button.setObjectName("languageRemoveItem")
        self.remove_button.clicked.connect(self.remove_item)
        self.form = QFormLayout()
        form_widget = QWidget()
        self.form_title = QLabel()
        self.form_title.setWordWrap(True)
        form_layout = QVBoxLayout(form_widget)
        form_layout.addWidget(self.form_title)
        form_layout.addLayout(self.form)
        self.apply_button = QPushButton("Apply fields")
        self.apply_button.setObjectName("languageApplyFields")
        self.apply_button.clicked.connect(self.apply_fields)
        form_layout.addWidget(self.apply_button)
        self.expression_button = QPushButton("Edit notation expression and preview…")
        self.expression_button.setObjectName("languageNotationExpression")
        self.expression_button.clicked.connect(self.edit_notation_expression)
        form_layout.addWidget(self.expression_button)
        self.query_expression_button = QPushButton("Edit query expression…")
        self.query_expression_button.setObjectName("languageQueryExpression")
        self.query_expression_button.clicked.connect(self.edit_query_expression)
        form_layout.addWidget(self.query_expression_button)
        form_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form_widget)
        splitter = QSplitter()
        splitter.addWidget(self.tree)
        splitter.addWidget(scroll)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([620, 400])
        layout = QVBoxLayout(self)
        description = QLabel(
            "Choose a slot in the tree, then add or change its kind. Queries inspect domain data; "
            "runtime expressions describe the program to generate. Unfinished slots can be saved."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        layout.addWidget(splitter, 1)
        toolbar = QHBoxLayout()
        toolbar.addWidget(self.variant, 1)
        for button in (self.add_button, self.replace_button, self.remove_button):
            toolbar.addWidget(button)
        for title, offset in (("Up", -1), ("Down", 1)):
            button = QPushButton(title)
            button.clicked.connect(lambda _checked=False, offset=offset: self.move_item(offset))
            toolbar.addWidget(button)
        layout.addLayout(toolbar)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def language(self) -> lang.AuthoredDomainLanguage:
        return self._value

    def _label(self, value: object) -> str:
        if isinstance(value, tuple):
            return f"{len(value)} items"
        if value is None:
            return "Not set"
        if isinstance(value, lang.QueryLiteral):
            return str(value.value)
        if isinstance(value, lang.QueryNodes):
            return f"{self._label(value.concept_id)} objects" + (
                " (roots)" if value.roots_only else ""
            )
        if isinstance(value, lang.QueryProperty):
            return f"Read {self._label(value.property_id)}"
        if isinstance(value, lang.QueryRole):
            return f"Follow {self._label(value.role_id)}"
        if isinstance(value, (lang.QueryBinary, lang.QueryUnary, lang.RuntimeBinary)):
            return value.operator.value.replace("_", " ").capitalize()
        if isinstance(value, lang.RuntimeCall):
            return value.builtin.value
        if isinstance(value, (lang.RuntimeVariable, lang.TemplateAssignment, lang.TemplateFor)):
            declared: list[lang.TemplateParameter | lang.TemplateSymbol] = []
            for transformation in self._value.transformations:
                for function in transformation.functions:
                    declared.extend(function.parameters)
                    declared.extend(function.symbols)
            name = next(
                (item.name for item in declared if item.id == value.symbol_id),
                "Unresolved variable",
            )
            return f"{_LABELS[type(value)]}: {name}"
        if isinstance(value, str):
            for concept in self.schema.concepts:
                if value == concept.id:
                    return concept.name
                for prop in concept.properties:
                    if value == prop.id:
                        return f"{concept.name} / {prop.name}"
                for role in (*concept.containment_roles, *concept.reference_roles):
                    if value == role.id:
                        return f"{concept.name} / {role.name}"
            return value
        detail = next(
            (
                getattr(value, name)
                for name in ("title", "name", "message", "label", "identifier_prefix")
                if getattr(value, name, "")
            ),
            "",
        )
        return str(detail or _LABELS.get(type(value), type(value).__name__))

    def refresh(self, path: EditPath | None = None) -> None:
        if path is not None:
            self._path = path
        self.tree.blockSignals(True)
        self.tree.clear()
        selected: QTreeWidgetItem | None = None

        def add(
            value: object, current: EditPath, title: str, parent: QTreeWidgetItem | None = None
        ) -> None:
            nonlocal selected
            item = QTreeWidgetItem([title, self._label(value)])
            item.setData(0, Qt.ItemDataRole.UserRole, current)
            identity = getattr(value, "id", "")
            if identity:
                item.setToolTip(0, str(identity))
            if parent:
                parent.addChild(item)
            else:
                self.tree.addTopLevelItem(item)
            if current == self._path:
                selected = item
            if isinstance(value, tuple):
                for index, child in enumerate(value):
                    add(
                        child,
                        (*current, index),
                        f"{index + 1}. {_LABELS.get(type(child), 'Binding')}",
                        item,
                    )
            else:
                for field_name in _SLOTS.get(type(value), {}):
                    add(
                        getattr(value, field_name),
                        (*current, field_name),
                        _field_label(field_name),
                        item,
                    )
            item.setExpanded(True)

        add(self._value, (), "Domain language")
        self.tree.blockSignals(False)
        target = selected or self.tree.topLevelItem(0)
        assert target is not None
        self.tree.setCurrentItem(target)
        self.tree.header().resizeSection(0, 330)

    def select_path(self, path: EditPath) -> None:
        """Select a stable structural address for navigation and automated UI checks."""
        pending = [self.tree.topLevelItem(0)]
        while pending:
            item = pending.pop()
            if item is None:
                continue
            if item.data(0, Qt.ItemDataRole.UserRole) == path:
                self.tree.setCurrentItem(item)
                self.tree.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)
                return
            pending.extend(item.child(index) for index in range(item.childCount()))
        raise ValueError("Definition path does not exist")

    def select_identity(self, identity: str) -> None:
        pending = [self.tree.topLevelItem(0)]
        while pending:
            item = pending.pop()
            if item is None:
                continue
            if item.toolTip(0) == identity:
                self.tree.setCurrentItem(item)
                self.tree.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)
                return
            pending.extend(item.child(index) for index in range(item.childCount()))
        raise ValueError("Definition identity does not exist")

    def _slot_for(self, path: EditPath) -> _Slot | None:
        slot_path = path[:-1] if path and isinstance(path[-1], int) else path
        if not slot_path:
            return None
        owner = _at(self._value, slot_path[:-1])
        return _SLOTS.get(type(owner), {}).get(str(slot_path[-1]))

    def _selected(self, item: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None) -> None:
        if item is None:
            return
        self._path = cast(EditPath, item.data(0, Qt.ItemDataRole.UserRole))
        value = _at(self._value, self._path)
        while self.form.rowCount():
            self.form.removeRow(0)
        self._controls.clear()
        slot = self._slot_for(self._path)
        self.variant.clear()
        if slot:
            for variant in slot.variants:
                self.variant.addItem(_LABELS.get(variant, "Schema binding"), variant)
            current_kind = self.variant.findData(type(value))
            if current_kind >= 0:
                self.variant.setCurrentIndex(current_kind)
        self.add_button.setEnabled(isinstance(value, tuple) and slot is not None)
        self.replace_button.setEnabled(not isinstance(value, tuple) and slot is not None)
        self.remove_button.setEnabled(
            bool(self._path) and (isinstance(self._path[-1], int) or bool(slot and slot.optional))
        )
        self.form_title.setText(self._label(value))
        self.expression_button.setVisible(isinstance(value, NotationDefinition))
        self.query_expression_button.setVisible(type(value) in _QUERIES)
        if isinstance(value, str):
            name = str(self._path[-2])
            self._controls["value"] = self._choice(name, value, optional=False)
            self._controls["value"].setObjectName("languageField:value")
            self.form.addRow("Binding", self._controls["value"])
        elif is_dataclass(value) and not isinstance(value, type):
            hidden = {"id"}
            if not isinstance(value, visual.NotationObjects):
                hidden.update({"schema_id", "schema_version"})
            if not isinstance(
                value,
                (
                    lang.QueryVariable,
                    visual.VisualField,
                    visual.VisualNumber,
                    visual.VisualPredicate,
                ),
            ):
                hidden.add("binding_id")
            for definition in fields(value):
                if definition.name in hidden or definition.name in _SLOTS.get(type(value), {}):
                    continue
                field_value = getattr(value, definition.name)
                control = self._control(value, definition.name, field_value)
                control.setObjectName(f"languageField:{definition.name}")
                self._controls[definition.name] = control
                self.form.addRow(_field_label(definition.name), control)
        self.apply_button.setEnabled(bool(self._controls))

    def _choices(
        self, name: str, *, owner_kind: type[object] | None = None
    ) -> tuple[tuple[str, object], ...]:
        selected = _at(self._value, self._path)
        kind = owner_kind or type(selected)
        schemas: tuple[DomainSchema, ...] = (self.schema,)
        if kind.__module__.endswith("notation_syntax") or kind is str:
            schemas = self.workspace.schemas
        if kind in {lang.DomainNodeTemplate, lang.DomainPropertyTemplate, lang.DomainRoleTemplate}:
            for index in range(len(self._path)):
                ancestor = _at(self._value, self._path[:index])
                if isinstance(ancestor, lang.DomainTemplate):
                    target = self.workspace.schema(ancestor.target_schema_id)
                    schemas = (target,) if target else ()
        if name in {"schema_id", "target_schema_id"}:
            return tuple((item.namespace, item.id) for item in self.workspace.schemas)
        if name == "model_id":
            return tuple((item.title or item.id, item.id) for item in self.workspace.models)
        if name == "target_template_id":
            for index in range(len(self._path)):
                ancestor = _at(self._value, self._path[:index])
                if isinstance(ancestor, lang.DomainTemplate):
                    return tuple((self._label(item.concept_id), item.id) for item in ancestor.nodes)
        if name in {"concept_id", "concept_ids"}:
            return tuple(
                (f"{schema.namespace} / {item.name}" if len(schemas) > 1 else item.name, item.id)
                for schema in schemas
                for item in schema.concepts
            )
        if name in {"property_id", "label_property_id"}:
            return tuple(
                (f"{concept.name} / {prop.name}", prop.id)
                for schema in schemas
                for concept in schema.concepts
                for prop in concept.properties
            )
        if name in {"role_id", "reference_role_ids", "source_role_id", "target_role_id"}:
            return tuple(
                (f"{concept.name} / {role.name}", role.id)
                for schema in schemas
                for concept in schema.concepts
                for role in (
                    (*concept.containment_roles, *concept.reference_roles)
                    if name == "role_id"
                    else concept.reference_roles
                )
            )
        if name in {"binding_id", "source_binding_id", "target_binding_id"}:
            is_visual = kind.__module__.endswith("notation_syntax")
            choices: list[tuple[str, object]] = [("Current root", "self")] if is_visual else []
            for index in range(len(self._path)):
                ancestor = _at(self._value, self._path[:index])
                field_name = self._path[index]
                available = (
                    isinstance(ancestor, lang.ValidatorDefinition) and field_name == "predicate"
                )
                available |= isinstance(ancestor, lang.FunctionTemplate) and field_name in {
                    "display_name",
                    "body",
                    "parameters",
                }
                available |= (
                    isinstance(ancestor, (lang.TemplateExpand, lang.TemplateLet))
                    and field_name == "body"
                )
                available |= (
                    isinstance(
                        ancestor, (lang.QueryMap, lang.QueryFilter, lang.QueryAll, lang.QueryUnique)
                    )
                    and field_name != "collection"
                )
                available |= (
                    isinstance(ancestor, lang.DomainNodeTemplate) and field_name != "source"
                )
                if isinstance(ancestor, visual.VisualRepeat) and field_name == "body":
                    choices.append((ancestor.binding_name, ancestor.binding_id))
                if available:
                    choices.append(
                        (
                            f"{_LABELS[type(ancestor)]}: {self._label(ancestor)}",
                            cast(Any, ancestor).binding_id,
                        )
                    )
            return tuple(choices)
        if name == "symbol_id":
            for index in range(len(self._path)):
                ancestor = _at(self._value, self._path[:index])
                if isinstance(ancestor, lang.FunctionTemplate):
                    declared: tuple[lang.TemplateParameter | lang.TemplateSymbol, ...] = (
                        *ancestor.parameters,
                        *ancestor.symbols,
                    )
                    return tuple((item.name, item.id) for item in declared)
        if name == "layout":
            return tuple((item.value.title(), item.value) for item in ProjectionLayout)
        if name == "depends_on":
            return tuple(
                (item.definition.id, item.definition.id) for item in self._value.transformations
            )
        return ()

    def _choice(self, name: str, value: object, *, optional: bool) -> QComboBox:
        control = QComboBox()
        if optional:
            control.addItem("Default / not set", None)
        for title, identity in self._choices(name):
            control.addItem(title, identity)
        selected = control.findData(value)
        if selected < 0 and value is not None:
            control.addItem(f"Unresolved: {value}", value)
            selected = control.count() - 1
        control.setCurrentIndex(selected)
        return control

    def _control(self, owner: object, name: str, value: object) -> QWidget:
        if isinstance(value, StrEnum):
            control = QComboBox()
            for member in type(value):
                control.addItem(member.value.replace("_", " ").title(), member)
            control.setCurrentIndex(control.findData(value))
            return control
        if (isinstance(owner, lang.QueryLiteral) and name == "value") or (
            isinstance(owner, visual.VisualPredicate) and name == "expected"
        ):
            return _LiteralEditor(value)
        if name in {
            "concept_id",
            "property_id",
            "label_property_id",
            "role_id",
            "source_role_id",
            "target_role_id",
            "binding_id",
            "source_binding_id",
            "target_binding_id",
            "schema_id",
            "target_schema_id",
            "model_id",
            "target_template_id",
            "symbol_id",
            "layout",
        }:
            return self._choice(
                name,
                value,
                optional=name
                in {"property_id", "label_property_id", "schema_id", "model_id", "role_id"},
            )
        if isinstance(value, bool):
            checkbox = QCheckBox()
            checkbox.setChecked(value)
            return checkbox
        return QLineEdit(str(value) if value is not None else "")

    def apply_fields(self) -> bool:
        value = _at(self._value, self._path)
        try:
            updates: dict[str, object] = {}
            for name, control in self._controls.items():
                if isinstance(control, _LiteralEditor):
                    updates[name] = control.value()
                elif isinstance(control, QComboBox):
                    chosen = control.currentData()
                    previous = getattr(value, name, None)
                    updates[name] = (
                        type(previous)(chosen) if isinstance(previous, StrEnum) else chosen
                    )
                elif isinstance(control, QCheckBox):
                    updates[name] = control.isChecked()
                elif isinstance(control, QLineEdit):
                    previous = getattr(value, name, None)
                    updates[name] = (
                        float(control.text())
                        if isinstance(previous, float)
                        else int(control.text())
                        if isinstance(previous, int)
                        else control.text() or (None if previous is None else "")
                    )
            if isinstance(value, (visual.NotationObjects, lang.DomainTemplate)):
                schema_field = (
                    "schema_id" if isinstance(value, visual.NotationObjects) else "target_schema_id"
                )
                version_field = (
                    "schema_version"
                    if isinstance(value, visual.NotationObjects)
                    else "target_schema_version"
                )
                chosen_schema = self.workspace.schema(
                    str(updates.get(schema_field, getattr(value, schema_field)))
                )
                updates[version_field] = chosen_schema.version if chosen_schema else None
            if isinstance(value, str):
                replacement = updates["value"]
            elif is_dataclass(value) and not isinstance(value, type):
                replacement = replace(value, **updates)
            else:
                return True
            self._set(self._path, replacement)
        except (TypeError, ValueError) as exc:
            self.status.setText(str(exc))
            return False
        self.status.setText("Fields applied to this draft. Save submits one authority command.")
        return True

    def _set(self, path: EditPath, value: object) -> None:
        updated = _replace_at(self._value, path, value)
        assert isinstance(updated, lang.AuthoredDomainLanguage)
        if "domain" in path:
            transformations = []
            for transformation in updated.transformations:
                target = (
                    self.workspace.schema(transformation.domain.target_schema_id)
                    if transformation.domain
                    else None
                )
                if target is not None:
                    transformation = replace(
                        transformation,
                        definition=replace(
                            transformation.definition,
                            target=Representation(target.namespace, target.version),
                        ),
                    )
                transformations.append(transformation)
            updated = replace(updated, transformations=tuple(transformations))
        if any(item.body is not None for item in updated.notations) or any(
            item.domain is not None for item in updated.transformations
        ):
            updated = replace(updated, syntax_version=2)
        self._value = updated
        self.refresh(path)

    def add_item(self) -> None:
        current = _at(self._value, self._path)
        if not isinstance(current, tuple):
            return
        variant = self.variant.currentData()
        if not isinstance(variant, type):
            return
        path = self._path
        self._set(path, (*current, self._starter(variant)))
        self.select_path((*path, len(current)))

    def set_kind(self) -> None:
        variant = self.variant.currentData()
        if not isinstance(variant, type):
            return
        previous = _at(self._value, self._path)
        if type(previous) is variant:
            return
        replacement = self._starter(variant)
        if (
            getattr(previous, "id", None) is not None
            and is_dataclass(replacement)
            and not isinstance(replacement, type)
        ):
            replacement = replace(replacement, id=cast(Any, previous).id)
        self._set(self._path, replacement)

    def remove_item(self) -> None:
        if not self._path:
            return
        if isinstance(self._path[-1], int):
            index = self._path[-1]
            parent = _at(self._value, self._path[:-1])
            assert isinstance(parent, tuple)
            self._set(
                self._path[:-1],
                tuple(item for number, item in enumerate(parent) if number != index),
            )
        else:
            slot = self._slot_for(self._path)
            if slot and slot.optional:
                self._set(self._path, None)

    def move_item(self, offset: int) -> None:
        if not self._path or not isinstance(self._path[-1], int):
            return
        index = self._path[-1]
        parent_path = self._path[:-1]
        parent = _at(self._value, parent_path)
        assert isinstance(parent, tuple)
        target = index + offset
        if not 0 <= target < len(parent):
            return
        values = list(parent)
        values[index], values[target] = values[target], values[index]
        self._set(parent_path, tuple(values))
        self.select_path((*parent_path, target))

    def _starter(self, variant: type[object]) -> object:
        identity = new_id("language-node")

        def query() -> lang.QueryHole:
            return lang.QueryHole(new_id("query"))

        def runtime() -> lang.RuntimeHole:
            return lang.RuntimeHole(new_id("runtime"))

        def hole() -> visual.VisualHole:
            return visual.VisualHole(new_id("visual"))

        def number(value: float = 0.0) -> visual.VisualNumber:
            return visual.VisualNumber(new_id("visual-number"), value)

        concept = self.schema.concepts[0].id if self.schema.concepts else ""

        def choice(field: str) -> str:
            choices = self._choices(field, owner_kind=variant)
            return str(choices[0][1]) if choices else ""

        factories: dict[type[object], Callable[[], object]] = {
            str: lambda: choice(str(self._path[-1])),
            NotationDefinition: lambda: NotationDefinition(
                identity, "New notation", NotationKind.GRAPH, schema_id=self.schema.id
            ),
            NotationColumn: lambda: NotationColumn(identity, "Column", NotationField()),
            NotationField: NotationField,
            NotationNodeRule: lambda: NotationNodeRule(concept),
            NotationEdgeRule: lambda: NotationEdgeRule(
                concept, choice("source_role_id"), choice("target_role_id")
            ),
            lang.ValidatorDefinition: lambda: lang.ValidatorDefinition(
                identity, concept, new_id("query-binding"), query(), "Domain rule failed"
            ),
            lang.AuthoredTransformation: lambda: lang.AuthoredTransformation(
                TransformationDefinition(
                    identity,
                    "1",
                    Representation(self.schema.namespace, self.schema.version),
                    PROGRAM_REPRESENTATION,
                )
            ),
            lang.DomainTemplate: lambda: lang.DomainTemplate(
                identity, self.schema.id, self.schema.version
            ),
            lang.DomainNodeTemplate: lambda: lang.DomainNodeTemplate(
                identity, query(), new_id("query-binding"), choice("concept_id")
            ),
            lang.DomainPropertyTemplate: lambda: lang.DomainPropertyTemplate(
                identity, choice("property_id"), query()
            ),
            lang.DomainRoleTemplate: lambda: lang.DomainRoleTemplate(
                identity, choice("role_id"), choice("target_template_id"), query()
            ),
            visual.VisualHole: lambda: visual.VisualHole(identity),
            visual.VisualText: lambda: visual.VisualText(identity),
            visual.VisualField: lambda: visual.VisualField(
                identity, choice("binding_id") or "self", choice("property_id") or None
            ),
            visual.VisualGroup: lambda: visual.VisualGroup(identity),
            visual.VisualBox: lambda: visual.VisualBox(identity, hole()),
            visual.VisualPosition: lambda: visual.VisualPosition(
                identity, hole(), number(), number()
            ),
            visual.VisualRepeat: lambda: visual.VisualRepeat(
                identity,
                visual.NotationObjects(new_id("visual-query"), concept),
                new_id("visual-binding"),
                hole(),
            ),
            visual.VisualConditional: lambda: visual.VisualConditional(
                identity, visual.VisualPredicate(new_id("visual-predicate")), hole()
            ),
            visual.VisualFraction: lambda: visual.VisualFraction(identity, hole(), hole()),
            visual.VisualScript: lambda: visual.VisualScript(identity, hole(), hole()),
            visual.VisualPath: lambda: visual.VisualPath(identity),
            visual.VisualConnector: lambda: visual.VisualConnector(identity, "self", "self"),
            visual.VisualPoint: lambda: visual.VisualPoint(identity, number(), number()),
            visual.VisualNumber: lambda: visual.VisualNumber(identity),
            visual.VisualPredicate: lambda: visual.VisualPredicate(identity),
            visual.NotationObjects: lambda: visual.NotationObjects(identity, concept),
            visual.NotationRelated: lambda: visual.NotationRelated(identity),
            visual.NotationQueryHole: lambda: visual.NotationQueryHole(identity),
            TransformationDefinition: lambda: TransformationDefinition(
                identity,
                "1",
                Representation(self.schema.namespace, self.schema.version),
                PROGRAM_REPRESENTATION,
            ),
            Representation: lambda: Representation(self.schema.namespace, self.schema.version),
            lang.FunctionTemplate: lambda: lang.FunctionTemplate(
                identity, lang.QueryNodes(new_id("query"), concept, True), new_id("query-binding")
            ),
            lang.TemplateParameter: lambda: lang.TemplateParameter(identity, "parameter"),
            lang.TemplateSymbol: lambda: lang.TemplateSymbol(identity, "variable"),
            lang.QueryHole: lambda: lang.QueryHole(identity),
            lang.QueryLiteral: lambda: lang.QueryLiteral(identity, ""),
            lang.QueryVariable: lambda: lang.QueryVariable(identity, choice("binding_id")),
            lang.QueryNodes: lambda: lang.QueryNodes(identity, concept),
            lang.QueryRole: lambda: lang.QueryRole(identity, query(), choice("role_id")),
            lang.QueryProperty: lambda: lang.QueryProperty(
                identity, query(), choice("property_id")
            ),
            lang.QueryIdentity: lambda: lang.QueryIdentity(identity, query()),
            lang.QueryUnary: lambda: lang.QueryUnary(
                identity, lang.QueryUnaryOperator.NOT, query()
            ),
            lang.QueryBinary: lambda: lang.QueryBinary(
                identity, lang.QueryBinaryOperator.EQUAL, query(), query()
            ),
            lang.QueryTuple: lambda: lang.QueryTuple(identity),
            lang.QueryMap: lambda: lang.QueryMap(
                identity, query(), new_id("query-binding"), query()
            ),
            lang.QueryFilter: lambda: lang.QueryFilter(
                identity, query(), new_id("query-binding"), query()
            ),
            lang.QueryAll: lambda: lang.QueryAll(
                identity, query(), new_id("query-binding"), query()
            ),
            lang.QueryUnique: lambda: lang.QueryUnique(
                identity, query(), new_id("query-binding"), query()
            ),
            lang.RuntimeHole: lambda: lang.RuntimeHole(identity),
            lang.RuntimeLiteral: lambda: lang.RuntimeLiteral(identity, query()),
            lang.RuntimeVariable: lambda: lang.RuntimeVariable(identity, choice("symbol_id")),
            lang.RuntimeBinary: lambda: lang.RuntimeBinary(
                identity, lang.RuntimeBinaryOperator.EQUAL, runtime(), runtime()
            ),
            lang.RuntimeCall: lambda: lang.RuntimeCall(identity, lang.RuntimeBuiltin.RANGE),
            lang.TemplateHole: lambda: lang.TemplateHole(identity),
            lang.TemplateExpand: lambda: lang.TemplateExpand(
                identity, query(), new_id("query-binding")
            ),
            lang.TemplateWhen: lambda: lang.TemplateWhen(identity, query()),
            lang.TemplateLet: lambda: lang.TemplateLet(identity, new_id("query-binding"), query()),
            lang.TemplateAssignment: lambda: lang.TemplateAssignment(
                identity, choice("symbol_id"), runtime()
            ),
            lang.TemplateOutput: lambda: lang.TemplateOutput(identity, runtime()),
            lang.TemplateIf: lambda: lang.TemplateIf(identity, runtime()),
            lang.TemplateFor: lambda: lang.TemplateFor(identity, choice("symbol_id"), runtime()),
            lang.TemplateTransfer: lambda: lang.TemplateTransfer(identity, TransferKind.RETURN),
        }
        return factories[variant]()

    def edit_notation_expression(self) -> None:
        from .notation_expression_editor import NotationExpressionDialog

        notation = _at(self._value, self._path)
        if not isinstance(notation, NotationDefinition) or not self.apply_fields():
            return
        notation = _at(self._value, self._path)
        assert isinstance(notation, NotationDefinition)
        dialog = NotationExpressionDialog(
            notation,
            self.schema,
            self.workspace,
            self.project,
            self,
            semantic_relations=self.semantic_relations,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._set(self._path, replace(notation, kind=NotationKind.COMPOSED, body=dialog.body))

    def edit_query_expression(self) -> None:
        from .query_expression_editor import QueryExpressionDialog, query_bindings_at

        value = _at(self._value, self._path)
        if type(value) not in _QUERIES or not self.apply_fields():
            return
        query = cast(lang.Query, _at(self._value, self._path))
        bindings = query_bindings_at(self._value, self._path, self.schema)
        dialog = QueryExpressionDialog(query, self.schema, bindings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._set(self._path, dialog.query)

    def _accept(self) -> None:
        if not self.apply_fields():
            return
        if not self._value.title.strip():
            QMessageBox.warning(self, "Language title", "Give the domain language a title.")
            return
        self.accept()


class _LiteralEditor(QWidget):
    def __init__(self, value: object) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.kind = QComboBox()
        self.kind.setObjectName("languageLiteralType")
        for label, type_name in (
            ("Text", "str"),
            ("Integer", "int"),
            ("Number", "float"),
            ("Boolean", "bool"),
            ("None", "none"),
        ):
            self.kind.addItem(label, type_name)
        self.kind.setCurrentIndex(
            self.kind.findData(type(value).__name__ if value is not None else "none")
        )
        self.text = QLineEdit(str(value) if value is not None else "")
        self.text.setObjectName("languageLiteralValue")
        layout.addWidget(self.kind)
        layout.addWidget(self.text, 1)

    def value(self) -> str | int | float | bool | None:
        kind = self.kind.currentData()
        text = self.text.text()
        if kind == "none":
            return None
        if kind == "bool":
            if text.lower() not in {"true", "false"}:
                raise ValueError("A Boolean literal must be true or false")
            return text.lower() == "true"
        if kind == "int":
            return int(text)
        if kind == "float":
            return float(text)
        return text
