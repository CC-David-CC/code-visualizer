"""Visible, typed function-signature editor for a DRAKON document."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from code_visualizer.application.commands import (
    ConfigureProgram,
    RenameDiagram,
    ReplaceProgramFunctionSignature,
    TypedCommand,
)
from code_visualizer.application.drakon_program_adapter import function_spec
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.domain.program_kinds import CallableKind, MethodKind, ParameterKind
from code_visualizer.domain.program_ownership import place_program_function
from code_visualizer.domain.program_signatures import FunctionSpec, ParameterSpec
from code_visualizer.domain.project import Project
from code_visualizer.sdk import CodeVisualizerClient


class FunctionSignatureEditor(QGroupBox):
    applied = Signal()

    def __init__(
        self,
        client: CodeVisualizerClient,
        diagram_id: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Function Signature · Python semantics", parent)
        self.setObjectName("functionSignatureEditor")
        self.setAccessibleName("Typed Python function signature")
        self._client = client
        self._diagram_id = diagram_id

        self.summary = QLabel("Function signature")
        self.summary.setObjectName("functionSignatureSummary")
        self.summary.setAccessibleName("Current Python function signature")
        self.toggle_details = QPushButton("Edit signature")
        self.toggle_details.setObjectName("toggleFunctionSignature")
        self.toggle_details.setCheckable(True)
        self.toggle_details.setAccessibleName("Show or hide typed function signature fields")

        self.identifier = QLineEdit()
        self.identifier.setObjectName("functionIdentifier")
        self.display_name = QLineEdit()
        self.display_name.setObjectName("functionDisplayName")
        self.callable_kind = QComboBox()
        self.callable_kind.setObjectName("functionCallableKind")
        for callable_kind in CallableKind:
            self.callable_kind.addItem(
                callable_kind.value.replace("_", " ").title(), callable_kind.value
            )
        self.module = QLineEdit()
        self.module.setObjectName("functionModule")
        self.return_annotation = QLineEdit()
        self.return_annotation.setObjectName("functionReturnAnnotation")
        self.return_annotation.setPlaceholderText("Optional Python type")
        self.owning_class = QLineEdit()
        self.owning_class.setObjectName("functionOwningClass")
        self.owning_class.setPlaceholderText("Blank for module-level function")
        self.method_kind = QComboBox()
        self.method_kind.setObjectName("functionMethodKind")
        self.method_kind.addItem("Module function", None)
        for method_kind in MethodKind:
            self.method_kind.addItem(method_kind.value.title(), method_kind.value)

        identity = QGridLayout()
        identity.addWidget(QLabel("Python name"), 0, 0)
        identity.addWidget(self.identifier, 0, 1)
        identity.addWidget(QLabel("Display name"), 0, 2)
        identity.addWidget(self.display_name, 0, 3)
        identity.addWidget(QLabel("Kind"), 1, 0)
        identity.addWidget(self.callable_kind, 1, 1)
        identity.addWidget(QLabel("Module"), 1, 2)
        identity.addWidget(self.module, 1, 3)
        identity.addWidget(QLabel("Returns"), 2, 0)
        identity.addWidget(self.return_annotation, 2, 1)
        identity.addWidget(QLabel("Owning class"), 2, 2)
        identity.addWidget(self.owning_class, 2, 3)
        identity.addWidget(QLabel("Method"), 3, 0)
        identity.addWidget(self.method_kind, 3, 1)

        self.parameters = QTableWidget(0, 4)
        self.parameters.setObjectName("functionParameters")
        self.parameters.setHorizontalHeaderLabels(["Name", "Kind", "Annotation", "Default"])
        self.parameters.setMaximumHeight(150)
        add_parameter = QPushButton("Add parameter")
        add_parameter.clicked.connect(self._add_parameter)
        remove_parameter = QPushButton("Remove selected")
        remove_parameter.clicked.connect(self._remove_parameters)
        parameter_buttons = QHBoxLayout()
        parameter_buttons.addWidget(add_parameter)
        parameter_buttons.addWidget(remove_parameter)
        parameter_buttons.addStretch(1)

        self.decorators = QLineEdit()
        self.decorators.setObjectName("functionDecorators")
        self.decorators.setPlaceholderText("One or more decorators, separated by commas")
        self.docstring = QPlainTextEdit()
        self.docstring.setObjectName("functionDocstring")
        self.docstring.setPlaceholderText("Optional function documentation")
        self.docstring.setMaximumHeight(70)
        extras = QFormLayout()
        extras.addRow("Decorators", self.decorators)
        extras.addRow("Docstring", self.docstring)

        self.message = QLabel()
        self.message.setObjectName("functionSignatureMessage")
        apply_button = QPushButton("Apply signature")
        apply_button.setObjectName("applyFunctionSignature")
        apply_button.clicked.connect(self.apply)

        footer = QHBoxLayout()
        footer.addWidget(self.message, 1)
        footer.addWidget(apply_button)

        details = QWidget()
        details.setObjectName("functionSignatureDetails")
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.addLayout(identity)
        details_layout.addWidget(self.parameters)
        details_layout.addLayout(parameter_buttons)
        details_layout.addLayout(extras)
        details_layout.addLayout(footer)
        self._details = details

        summary_row = QHBoxLayout()
        summary_row.addWidget(self.summary, 1)
        summary_row.addWidget(self.toggle_details)
        layout = QVBoxLayout(self)
        layout.addLayout(summary_row)
        layout.addWidget(details)
        self.toggle_details.toggled.connect(self.set_expanded)
        self.set_expanded(False)

    @property
    def is_expanded(self) -> bool:
        return not self._details.isHidden()

    def set_expanded(self, expanded: bool) -> None:
        self._details.setVisible(expanded)
        self.toggle_details.setChecked(expanded)
        self.toggle_details.setText("Hide signature" if expanded else "Edit signature")
        if expanded:
            self.identifier.setFocus()

    def _kind_combo(self, value: ParameterKind) -> QComboBox:
        combo = QComboBox()
        for kind in ParameterKind:
            combo.addItem(kind.value.replace("_", " ").title(), kind.value)
        combo.setCurrentIndex(max(0, combo.findData(value.value)))
        return combo

    def _add_parameter(self, parameter: ParameterSpec | None = None) -> None:
        item = parameter or ParameterSpec("value")
        row = self.parameters.rowCount()
        self.parameters.insertRow(row)
        self.parameters.setItem(row, 0, QTableWidgetItem(item.name))
        self.parameters.setCellWidget(row, 1, self._kind_combo(item.kind))
        self.parameters.setItem(row, 2, QTableWidgetItem(item.annotation or ""))
        self.parameters.setItem(row, 3, QTableWidgetItem(item.default or ""))

    def _remove_parameters(self) -> None:
        rows = sorted({index.row() for index in self.parameters.selectedIndexes()}, reverse=True)
        for row in rows:
            self.parameters.removeRow(row)

    def refresh(self, project: Project) -> None:
        view = next(
            (item for item in project.drakon_views if item.document_id == self._diagram_id), None
        )
        self._function_id = view.function_id if view is not None else self._diagram_id
        self._revision = project.revision
        canonical = project.program_model.function(self._function_id)
        if canonical is None:
            self.setEnabled(False)
            return
        self.setEnabled(True)
        function = function_spec(canonical, project.program_model)
        self.identifier.setText(function.identifier)
        self.display_name.setText(function.display_name)
        self.callable_kind.setCurrentIndex(max(0, self.callable_kind.findData(function.kind.value)))
        self.module.setText(function.module)
        self.return_annotation.setText(function.return_annotation or "")
        self.owning_class.setText(function.owning_class or "")
        method_value = function.method_kind.value if function.method_kind else None
        self.method_kind.setCurrentIndex(max(0, self.method_kind.findData(method_value)))
        self.parameters.setRowCount(0)
        for parameter in function.parameters:
            self._add_parameter(parameter)
        self.decorators.setText(", ".join(function.decorators))
        self.docstring.setPlainText(function.docstring or "")
        parameters = ", ".join(
            parameter.name
            + (f": {parameter.annotation}" if parameter.annotation else "")
            + (f" = {parameter.default}" if parameter.default else "")
            for parameter in function.parameters
        )
        returns = f" -> {function.return_annotation}" if function.return_annotation else ""
        self.summary.setText(
            f"{function.display_name}: {function.identifier}({parameters}){returns}"
            f"  ·  module {function.module}"
        )

    def _parameters(self) -> tuple[ParameterSpec, ...]:
        result: list[ParameterSpec] = []
        for row in range(self.parameters.rowCount()):
            name_item = self.parameters.item(row, 0)
            annotation_item = self.parameters.item(row, 2)
            default_item = self.parameters.item(row, 3)
            combo = self.parameters.cellWidget(row, 1)
            kind_value = combo.currentData() if isinstance(combo, QComboBox) else None
            result.append(
                ParameterSpec(
                    name_item.text().strip() if name_item else "",
                    ParameterKind(str(kind_value)),
                    (annotation_item.text().strip() or None) if annotation_item else None,
                    (default_item.text().strip() or None) if default_item else None,
                )
            )
        return tuple(result)

    def apply(self) -> None:
        method_value = self.method_kind.currentData()
        function = FunctionSpec(
            identifier=self.identifier.text().strip(),
            display_name=self.display_name.text().strip(),
            kind=CallableKind(str(self.callable_kind.currentData())),
            parameters=self._parameters(),
            return_annotation=self.return_annotation.text().strip() or None,
            decorators=tuple(
                value.strip() for value in self.decorators.text().split(",") if value.strip()
            ),
            docstring=self.docstring.toPlainText().strip() or None,
            module=self.module.text().strip(),
            owning_class=self.owning_class.text().strip() or None,
            method_kind=MethodKind(str(method_value)) if method_value is not None else None,
        )
        project = self._client.snapshot()
        model = place_program_function(
            project.program_model, self._function_id, function.module, function.owning_class
        )
        commands: list[TypedCommand] = [
            ReplaceProgramFunctionSignature(self._function_id, function),
            ConfigureProgram(model.package, model.modules, model.entrypoint),
        ]
        if any(item.id == self._diagram_id for item in project.documents):
            commands.append(RenameDiagram(self._diagram_id, function.display_name))
        result = self._client.transaction(
            tuple(commands),
            expected_revision=self._revision,
            intent="Edit canonical function signature and owner",
        )
        if isinstance(result, CommandAccepted):
            self.message.setText(f"Applied at revision {result.revision}")
            self.applied.emit()
        else:
            self.message.setText(f"Not applied: {result.code} · {result.message}")
