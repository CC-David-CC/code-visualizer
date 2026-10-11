"""Schema-driven scalar, reference, concept, and role editors."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from code_visualizer.domain.common import new_id
from code_visualizer.domain.intentional import (
    ConceptDefinition,
    DomainModel,
    DomainSchema,
    DomainValue,
    DomainWorkspace,
    IntentionalNode,
    PropertyDefinition,
    PropertyValue,
    RoleBinding,
    RoleDefinition,
    ValueKind,
    node_label,
)
from code_visualizer.domain.resources import DataResource
from code_visualizer.domain.values import (
    ComplexValue,
    Dimension,
    QuantityValue,
    ResourceReference,
    TensorDType,
    TensorValue,
    UnitReference,
    ValueConstraints,
    canonical_value_key,
    validate_canonical_value,
)
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.ui_qt.features.domain_workbench.value_editors import (
    ComplexValueEditor,
    DimensionValueEditor,
    QuantityValueEditor,
    ResourceValueEditor,
    TensorValueEditor,
    value_summary,
)

RICH_VALUE_KINDS = (ValueKind.COMPLEX, ValueKind.QUANTITY, ValueKind.TENSOR, ValueKind.RESOURCE)


def parse_scalar(text: str, kind: ValueKind) -> DomainValue:
    if kind in RICH_VALUE_KINDS:
        raise ValueError("Open the structured value editor for this property")
    if kind is ValueKind.INTEGER:
        return int(text)
    if kind is ValueKind.NUMBER:
        try:
            return int(text)
        except ValueError:
            return float(text)
    if kind is ValueKind.BOOLEAN:
        normalized = text.strip().casefold()
        if normalized not in {"true", "false"}:
            raise ValueError("Use true or false for a Boolean value")
        return normalized == "true"
    return text


class ScalarEditor(QWidget):
    def __init__(
        self,
        definition: PropertyDefinition,
        value: DomainValue | None,
        *,
        resources: tuple[DataResource, ...] = (),
        resource_store: ResourceStore | None = None,
        unit_choices: tuple[tuple[str, UnitReference], ...] = (),
    ) -> None:
        super().__init__()
        self.definition = definition
        self.enabled_value = QCheckBox("Set")
        self.enabled_value.setChecked(value is not None)
        self.enabled_value.setToolTip("Clear to leave this optional property unset")
        self.control: (
            QComboBox
            | QCheckBox
            | QLineEdit
            | ComplexValueEditor
            | QuantityValueEditor
            | TensorValueEditor
            | ResourceValueEditor
        )
        if definition.choices:
            choice = QComboBox()
            for index, item in enumerate(definition.choices):
                choice.addItem(str(item), index)
            if value is not None:
                choice.setCurrentIndex(
                    next(
                        (
                            index
                            for index, item in enumerate(definition.choices)
                            if canonical_value_key(item) == canonical_value_key(value)
                        ),
                        0,
                    )
                )
            self.control = choice
        elif definition.value_kind is ValueKind.BOOLEAN:
            checkbox = QCheckBox("True")
            checkbox.setChecked(value is True)
            self.control = checkbox
        elif definition.value_kind is ValueKind.COMPLEX:
            self.control = ComplexValueEditor(value if isinstance(value, ComplexValue) else None)
        elif definition.value_kind is ValueKind.QUANTITY:
            self.control = QuantityValueEditor(
                value if isinstance(value, QuantityValue) else None, unit_choices
            )
        elif definition.value_kind is ValueKind.TENSOR:
            self.control = TensorValueEditor(value if isinstance(value, TensorValue) else None)
        elif definition.value_kind is ValueKind.RESOURCE:
            self.control = ResourceValueEditor(
                value if isinstance(value, ResourceReference) else None, resources, resource_store
            )
        else:
            self.control = QLineEdit("" if value is None else str(value))
        self.control.setObjectName(f"domainProperty:{definition.id}")
        self.control.setAccessibleName(definition.name)
        self.control.setEnabled(self.enabled_value.isChecked())
        self.enabled_value.toggled.connect(self.control.setEnabled)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.enabled_value)
        layout.addWidget(self.control, 1)

    def value(self) -> DomainValue | None:
        if not self.enabled_value.isChecked():
            return None
        if isinstance(self.control, QComboBox):
            value = self.definition.choices[self.control.currentIndex()]
            validate_canonical_value(value)
            return value
        if isinstance(self.control, QCheckBox):
            return self.control.isChecked()
        if isinstance(
            self.control,
            (ComplexValueEditor, QuantityValueEditor, TensorValueEditor, ResourceValueEditor),
        ):
            return self.control.value()
        return parse_scalar(self.control.text(), self.definition.value_kind)


class ValueDialog(QDialog):
    def __init__(
        self,
        definition: PropertyDefinition,
        value: DomainValue | None,
        parent: QWidget | None = None,
        *,
        resources: tuple[DataResource, ...] = (),
        resource_store: ResourceStore | None = None,
        unit_choices: tuple[tuple[str, UnitReference], ...] = (),
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(definition.name)
        self.setObjectName("domainValueDialog")
        self.editor = ScalarEditor(
            definition,
            value,
            resources=resources,
            resource_store=resource_store,
            unit_choices=unit_choices,
        )
        self.result_value = value
        layout = QVBoxLayout(self)
        layout.addWidget(self.editor)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        try:
            self.result_value = self.editor.value()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid value", str(exc))
            return
        self.accept()


class ReferenceEditor(QListWidget):
    def __init__(
        self,
        definition: RoleDefinition,
        schema: DomainSchema,
        model: DomainModel,
        selected: tuple[str, ...] = (),
        *,
        workspace: DomainWorkspace | None = None,
    ) -> None:
        super().__init__()
        self.setObjectName(f"domainReference:{definition.id}")
        self.setAccessibleName(definition.name)
        self.setMaximumHeight(125)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        if definition.ordered:
            self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        models = workspace.models if workspace is not None else (model,)
        by_id = {node.id: (candidate, node) for candidate in models for node in candidate.nodes}
        identifiers = tuple(
            dict.fromkeys(
                (
                    *selected,
                    *(
                        node.id
                        for candidate in models
                        for node in candidate.nodes
                        if node.concept_id in definition.allowed_concept_ids
                    ),
                )
            )
        )
        for node_id in identifiers:
            found = by_id.get(node_id)
            owner, node = found if found else (model, None)
            owner_schema = workspace.schema(owner.schema_id) if workspace is not None else schema
            label = (
                node_label(owner_schema, node)
                if node is not None and owner_schema
                else f"Missing: {node_id}"
            )
            concept = owner_schema.concept(node.concept_id) if node and owner_schema else None
            display = (
                node.property(concept.display_property_id)
                if node and concept and concept.display_property_id
                else None
            )
            if display is not None:
                label = value_summary(display)
            if owner.id != model.id:
                label = f"{owner.title or owner.id} / {label}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, node_id)
            item.setToolTip(node_id + (f"\n{display}" if display is not None else ""))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if node_id in selected else Qt.CheckState.Unchecked
            )
            self.addItem(item)

    def target_ids(self) -> tuple[str, ...]:
        return tuple(
            str(item.data(Qt.ItemDataRole.UserRole))
            for index in range(self.count())
            if (item := self.item(index)).checkState() is Qt.CheckState.Checked
        )


class NodeDialog(QDialog):
    def __init__(
        self,
        schema: DomainSchema,
        model: DomainModel,
        concept_ids: tuple[str, ...],
        parent: QWidget | None = None,
        *,
        initial_references: tuple[RoleBinding, ...] = (),
        workspace: DomainWorkspace | None = None,
        resources: tuple[DataResource, ...] = (),
        resource_store: ResourceStore | None = None,
        unit_choices: tuple[tuple[str, UnitReference], ...] = (),
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create domain object")
        self.setObjectName("createDomainNodeDialog")
        self.schema, self.model = schema, model
        self.workspace, self.resources = workspace, resources
        self.resource_store = resource_store
        self.unit_choices = unit_choices
        self.initial_references = {
            binding.role_id: binding.node_ids for binding in initial_references
        }
        self.concept_choice = QComboBox()
        self.concept_choice.setObjectName("newDomainNodeConcept")
        for concept in schema.concepts:
            if not concept_ids or concept.id in concept_ids:
                self.concept_choice.addItem(concept.name, concept.id)
        self.fields = QFormLayout()
        self.properties: dict[str, ScalarEditor] = {}
        self.references: dict[str, ReferenceEditor] = {}
        self._node: IntentionalNode | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(self.concept_choice)
        layout.addLayout(self.fields)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.concept_choice.currentIndexChanged.connect(self._load)
        self._load()

    def _load(self) -> None:
        while self.fields.rowCount():
            self.fields.removeRow(0)
        self.properties.clear()
        self.references.clear()
        concept = self.schema.concept(str(self.concept_choice.currentData()))
        if concept is None:
            return
        for prop in concept.properties:
            value = prop.default
            if value is None and prop.required and prop.value_kind is ValueKind.STRING:
                value = ""
            editor = ScalarEditor(
                prop,
                value,
                resources=self.resources,
                resource_store=self.resource_store,
                unit_choices=self.unit_choices,
            )
            self.properties[prop.id] = editor
            self.fields.addRow(prop.name + (" *" if prop.required else ""), editor)
        for role in concept.reference_roles:
            reference_editor = ReferenceEditor(
                role,
                self.schema,
                self.model,
                self.initial_references.get(role.id, ()),
                workspace=self.workspace,
            )
            self.references[role.id] = reference_editor
            self.fields.addRow(role.name, reference_editor)

    def _accept(self) -> None:
        concept_id = str(self.concept_choice.currentData())
        if self.schema.concept(concept_id) is None:
            return
        try:
            properties = tuple(
                PropertyValue(prop_id, value)
                for prop_id, editor in self.properties.items()
                if (value := editor.value()) is not None
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid value", str(exc))
            return
        self._node = IntentionalNode(
            new_id("intention"),
            concept_id,
            properties,
            references=tuple(
                RoleBinding(role_id, editor.target_ids())
                for role_id, editor in self.references.items()
                if editor.target_ids()
            ),
        )
        self.accept()

    def node(self) -> IntentionalNode | None:
        return self._node


class PropertyDialog(QDialog):
    def __init__(
        self, existing: PropertyDefinition | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Property definition")
        self.setObjectName("domainPropertyDefinitionDialog")
        self.existing = existing
        self._typed_default = existing.default if existing else None
        self._default_kind = existing.value_kind if existing else ValueKind.STRING
        self.result_property: PropertyDefinition | None = None
        self.name = QLineEdit(existing.name if existing else "")
        self.name.setObjectName("domainPropertyName")
        self.kind = QComboBox()
        for kind in ValueKind:
            self.kind.addItem(kind.value.title(), kind.value)
        if existing:
            self.kind.setCurrentIndex(self.kind.findData(existing.value_kind.value))
        self.required = QCheckBox("Required")
        self.required.setChecked(existing.required if existing else False)
        self.default_enabled = QCheckBox("Use default")
        self.default_enabled.setChecked(existing is not None and existing.default is not None)
        self.default = QLineEdit(
            str(existing.default) if existing and existing.default is not None else ""
        )
        self.edit_default = QPushButton("Edit structured default")
        self.edit_default.setObjectName("editStructuredPropertyDefault")
        self.edit_default.clicked.connect(self._edit_default)
        self.choices = QPlainTextEdit(
            "\n".join(str(item) for item in existing.choices) if existing else ""
        )
        self.choices.setPlaceholderText("Optional allowed values, one per line")
        self.minimum = QLineEdit(
            str(existing.minimum) if existing and existing.minimum is not None else ""
        )
        self.maximum = QLineEdit(
            str(existing.maximum) if existing and existing.maximum is not None else ""
        )
        constraints = existing.value_constraints if existing else ValueConstraints()
        self.dimension_enabled = QCheckBox("Constrain dimension")
        self.dimension_enabled.setChecked(constraints.dimension is not None)
        self.dimension = DimensionValueEditor(constraints.dimension or Dimension())
        self.dimension.setObjectName("propertyDimensionConstraint")
        self.tensor_dtype = QComboBox()
        self.tensor_dtype.setObjectName("propertyTensorDType")
        self.tensor_dtype.addItem("Any element type", None)
        for dtype in TensorDType:
            self.tensor_dtype.addItem(dtype.value, dtype.value)
        if constraints.tensor_dtype is not None:
            self.tensor_dtype.setCurrentIndex(
                self.tensor_dtype.findData(constraints.tensor_dtype.value)
            )
        shape = constraints.tensor_shape
        self.tensor_shape = QLineEdit(
            ""
            if shape is None
            else "scalar"
            if not shape
            else ", ".join("?" if size is None else str(size) for size in shape)
        )
        self.tensor_shape.setObjectName("propertyTensorShape")
        self.tensor_shape.setPlaceholderText("Any shape: empty; scalar; or dimensions such as 2, ?")
        form = QFormLayout()
        for label, widget in (
            ("Name", self.name),
            ("Type", self.kind),
            ("Presence", self.required),
            ("Default", self.default_enabled),
            ("Default value", self.default),
            ("Structured value", self.edit_default),
            ("Allowed values", self.choices),
            ("Minimum", self.minimum),
            ("Maximum", self.maximum),
            ("Quantity constraint", self.dimension_enabled),
            ("Dimension", self.dimension),
            ("Tensor element type", self.tensor_dtype),
            ("Tensor shape", self.tensor_shape),
        ):
            form.addRow(label, widget)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.dimension_enabled.toggled.connect(self._kind_changed)
        self._kind_changed()

    def _kind_changed(self, _index: int = 0) -> None:
        kind = ValueKind(self.kind.currentData())
        rich = kind in RICH_VALUE_KINDS
        self.default.setReadOnly(rich)
        self.edit_default.setVisible(rich)
        self.choices.setEnabled(not rich)
        self.minimum.setEnabled(kind in (ValueKind.INTEGER, ValueKind.NUMBER))
        self.maximum.setEnabled(kind in (ValueKind.INTEGER, ValueKind.NUMBER))
        self.dimension_enabled.setEnabled(kind is ValueKind.QUANTITY)
        self.dimension.setEnabled(kind is ValueKind.QUANTITY and self.dimension_enabled.isChecked())
        self.tensor_dtype.setEnabled(kind is ValueKind.TENSOR)
        self.tensor_shape.setEnabled(kind is ValueKind.TENSOR)
        if kind != self._default_kind:
            self._typed_default = None
            self._default_kind = kind
            self.default.clear()

    def _edit_default(self) -> None:
        kind = ValueKind(self.kind.currentData())
        definition = PropertyDefinition(
            self.existing.id if self.existing else "draft:property",
            self.name.text() or "Default value",
            kind,
        )
        dialog = ValueDialog(definition, self._typed_default, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._typed_default = dialog.result_value
            self.default.setText("" if dialog.result_value is None else str(dialog.result_value))
            self.default_enabled.setChecked(dialog.result_value is not None)

    def _accept(self) -> None:
        try:
            if not self.name.text().strip():
                raise ValueError("A property needs a name")
            kind = ValueKind(self.kind.currentData())
            default = None
            if self.default_enabled.isChecked():
                default = (
                    self._typed_default
                    if kind in RICH_VALUE_KINDS
                    else parse_scalar(self.default.text(), kind)
                )
                if default is None:
                    raise ValueError("Choose the structured default value, or disable the default")
            choices = (
                (
                    self.existing.choices
                    if self.existing and self.existing.value_kind is kind
                    else ()
                )
                if kind in RICH_VALUE_KINDS
                else tuple(
                    parse_scalar(line, kind) for line in self.choices.toPlainText().splitlines()
                )
            )
            dimension = (
                self.dimension.value()
                if kind is ValueKind.QUANTITY and self.dimension_enabled.isChecked()
                else None
            )
            dtype = self.tensor_dtype.currentData() if kind is ValueKind.TENSOR else None
            shape_text = self.tensor_shape.text().strip() if kind is ValueKind.TENSOR else ""
            shape = (
                None
                if not shape_text
                else ()
                if shape_text == "scalar"
                else tuple(
                    None if part.strip() == "?" else int(part.strip())
                    for part in shape_text.split(",")
                )
            )
            constraints = ValueConstraints(dimension, TensorDType(dtype) if dtype else None, shape)
            numeric = kind in (ValueKind.INTEGER, ValueKind.NUMBER)
            self.result_property = PropertyDefinition(
                self.existing.id if self.existing else new_id("property"),
                self.name.text().strip(),
                kind,
                self.required.isChecked(),
                default,
                choices,
                float(self.minimum.text()) if numeric and self.minimum.text().strip() else None,
                float(self.maximum.text()) if numeric and self.maximum.text().strip() else None,
                constraints,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid property", str(exc))
            return
        self.accept()


class RoleDialog(QDialog):
    def __init__(
        self,
        concepts: tuple[ConceptDefinition, ...],
        existing: RoleDefinition | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Role definition")
        self.setObjectName("domainRoleDefinitionDialog")
        self.existing = existing
        self.result_role: RoleDefinition | None = None
        self.name = QLineEdit(existing.name if existing else "")
        self.allowed = QListWidget()
        for concept in concepts:
            item = QListWidgetItem(concept.name)
            item.setData(Qt.ItemDataRole.UserRole, concept.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if existing and concept.id in existing.allowed_concept_ids
                else Qt.CheckState.Unchecked
            )
            self.allowed.addItem(item)
        self.minimum = QSpinBox()
        self.minimum.setRange(0, 1_000_000)
        self.minimum.setValue(existing.min_count if existing else 0)
        self.maximum = QSpinBox()
        self.maximum.setRange(0, 1_000_000)
        self.maximum.setValue(
            existing.max_count if existing and existing.max_count is not None else 1
        )
        self.unlimited = QCheckBox("Unlimited")
        self.unlimited.setChecked(existing is None or existing.max_count is None)
        self.ordered = QCheckBox("Order matters")
        self.ordered.setChecked(existing.ordered if existing else True)
        form = QFormLayout()
        for label, widget in (
            ("Name", self.name),
            ("Allowed concepts", self.allowed),
            ("Minimum count", self.minimum),
            ("Maximum count", self.maximum),
            ("Upper limit", self.unlimited),
            ("Ordering", self.ordered),
        ):
            form.addRow(label, widget)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        allowed = tuple(
            str(item.data(Qt.ItemDataRole.UserRole))
            for index in range(self.allowed.count())
            if (item := self.allowed.item(index)).checkState() is Qt.CheckState.Checked
        )
        if not self.name.text().strip() or not allowed:
            QMessageBox.warning(
                self, "Incomplete role", "Supply a role name and at least one allowed concept."
            )
            return
        self.result_role = RoleDefinition(
            self.existing.id if self.existing else new_id("role"),
            self.name.text().strip(),
            allowed,
            self.minimum.value(),
            None if self.unlimited.isChecked() else self.maximum.value(),
            self.ordered.isChecked(),
        )
        self.accept()


class SchemaDialog(QDialog):
    """Edit schema definitions through typed fields without exposing serialized JSON."""

    def __init__(
        self,
        existing: DomainSchema | None = None,
        parent: QWidget | None = None,
        *,
        workspace: DomainWorkspace | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Domain schema")
        self.setObjectName("domainSchemaDialog")
        self.resize(760, 600)
        self.existing = existing
        self.workspace = workspace
        self.concepts = list(existing.concepts if existing else ())
        self._schema_id = existing.id if existing else new_id("domain-schema")
        self.namespace = QLineEdit(existing.namespace if existing else "")
        self.namespace.setObjectName("domainSchemaNamespace")
        self.version = QLineEdit(existing.version if existing else "1")
        self.description = QPlainTextEdit(existing.description if existing else "")
        self.description.setMaximumHeight(75)
        self.tree = QTreeWidget()
        self.tree.setObjectName("domainSchemaConcepts")
        self.tree.setHeaderLabels(["Definition", "Kind", "Constraints"])
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("Namespace", self.namespace)
        form.addRow("Version", self.version)
        form.addRow("Description", self.description)
        layout.addLayout(form)
        layout.addWidget(self.tree, 1)
        actions = QHBoxLayout()
        for label, callback in (
            ("Add concept", self.add_concept),
            ("Add property", self.add_property),
            ("Add child role", lambda: self.add_role(False)),
            ("Add reference role", lambda: self.add_role(True)),
            ("Edit selected", self.edit_selected),
            ("Delete selected", self.delete_selected),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def refresh(self) -> None:
        self.tree.clear()
        for concept in self.concepts:
            root = QTreeWidgetItem([concept.name, "Concept", concept.description])
            root.setData(0, Qt.ItemDataRole.UserRole, (concept.id, "concept", concept.id))
            self.tree.addTopLevelItem(root)
            for prop in concept.properties:
                item = QTreeWidgetItem(
                    [prop.name, prop.value_kind.value, "Required" if prop.required else "Optional"]
                )
                item.setData(0, Qt.ItemDataRole.UserRole, (concept.id, "property", prop.id))
                root.addChild(item)
            for kind, roles in (
                ("children", concept.containment_roles),
                ("reference", concept.reference_roles),
            ):
                for role in roles:
                    item = QTreeWidgetItem(
                        [
                            role.name,
                            kind,
                            f"{role.min_count}.."
                            f"{role.max_count if role.max_count is not None else '*'}",
                        ]
                    )
                    item.setData(0, Qt.ItemDataRole.UserRole, (concept.id, kind, role.id))
                    root.addChild(item)
            root.setExpanded(True)

    def selected(self) -> tuple[ConceptDefinition, str, str] | None:
        item = self.tree.currentItem()
        data = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(data, tuple) or len(data) != 3:
            return None
        concept = next((value for value in self.concepts if value.id == data[0]), None)
        return (concept, str(data[1]), str(data[2])) if concept else None

    def _replace(self, concept: ConceptDefinition) -> None:
        self.concepts = [concept if item.id == concept.id else item for item in self.concepts]
        self.refresh()
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item is not None and item.data(0, Qt.ItemDataRole.UserRole)[0] == concept.id:
                self.tree.setCurrentItem(item)
                break

    def add_concept(self) -> None:
        name, accepted = QInputDialog.getText(self, "Add concept", "Concept name")
        if accepted and name.strip():
            concept = ConceptDefinition(new_id("concept-definition"), name.strip())
            self.concepts.append(concept)
            self._replace(concept)

    def add_property(self) -> None:
        selected = self.selected()
        if selected is None:
            return
        concept = selected[0]
        dialog = PropertyDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_property:
            prop = dialog.result_property
            self._replace(
                replace(
                    concept,
                    properties=(*concept.properties, prop),
                    display_property_id=concept.display_property_id or prop.id,
                )
            )

    def add_role(self, reference: bool) -> None:
        selected = self.selected()
        if selected is None:
            return
        concept = selected[0]
        dialog = RoleDialog(self._role_concepts(reference), parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_role:
            roles = concept.reference_roles if reference else concept.containment_roles
            self._replace_roles(concept, reference, (*roles, dialog.result_role))

    def _replace_roles(
        self, concept: ConceptDefinition, reference: bool, roles: tuple[RoleDefinition, ...]
    ) -> None:
        self._replace(
            replace(concept, reference_roles=roles)
            if reference
            else replace(concept, containment_roles=roles)
        )

    def edit_selected(self) -> None:
        selected = self.selected()
        if selected is None:
            return
        concept, kind, value_id = selected
        if kind == "concept":
            name, accepted = QInputDialog.getText(
                self, "Rename concept", "Concept name", text=concept.name
            )
            if accepted and name.strip():
                self._replace(replace(concept, name=name.strip()))
        elif kind == "property":
            dialog = PropertyDialog(concept.property(value_id), self)
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_property:
                self._replace(
                    replace(
                        concept,
                        properties=tuple(
                            dialog.result_property if item.id == value_id else item
                            for item in concept.properties
                        ),
                    )
                )
        else:
            role_dialog = RoleDialog(
                self._role_concepts(kind == "reference"), concept.role(value_id), self
            )
            if role_dialog.exec() == QDialog.DialogCode.Accepted and role_dialog.result_role:
                roles = (
                    concept.reference_roles if kind == "reference" else concept.containment_roles
                )
                self._replace_roles(
                    concept,
                    kind == "reference",
                    tuple(
                        role_dialog.result_role if item.id == value_id else item for item in roles
                    ),
                )

    def _role_concepts(self, reference: bool) -> tuple[ConceptDefinition, ...]:
        local = tuple(self.concepts)
        if not reference or self.workspace is None:
            return local
        return (
            *local,
            *(
                concept
                for schema in self.workspace.schemas
                if schema.id != self._schema_id
                for concept in schema.concepts
            ),
        )

    def delete_selected(self) -> None:
        selected = self.selected()
        if selected is None:
            return
        concept, kind, value_id = selected
        if kind == "concept":
            self.concepts = [item for item in self.concepts if item.id != concept.id]
            self.refresh()
        elif kind == "property":
            self._replace(
                replace(
                    concept,
                    properties=tuple(item for item in concept.properties if item.id != value_id),
                    display_property_id=None
                    if concept.display_property_id == value_id
                    else concept.display_property_id,
                )
            )
        else:
            roles = concept.reference_roles if kind == "reference" else concept.containment_roles
            self._replace_roles(
                concept, kind == "reference", tuple(item for item in roles if item.id != value_id)
            )

    def schema(self) -> DomainSchema:
        return DomainSchema(
            self._schema_id,
            self.namespace.text().strip(),
            self.version.text().strip(),
            tuple(self.concepts),
            self.existing.bundle if self.existing else None,
            self.description.toPlainText(),
        )
