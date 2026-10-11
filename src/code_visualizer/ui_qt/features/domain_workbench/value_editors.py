"""Structured controls for the canonical value algebra; no serialized JSON editor."""

from __future__ import annotations

import math
import mimetypes
import re
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from code_visualizer.domain.resources import DataResource
from code_visualizer.domain.values import (
    MAX_INLINE_ELEMENTS,
    CanonicalValue,
    ComplexValue,
    Dimension,
    DimensionPower,
    QuantityValue,
    ResourceReference,
    TensorDType,
    TensorValue,
    UnitReference,
)
from code_visualizer.persistence.resource_store import ResourceStore


def value_summary(value: CanonicalValue, maximum: int = 180) -> str:
    """Concise display only; the typed value remains available to editors and tooltips."""
    if isinstance(value, TensorValue):
        shape = " x ".join(str(size) for size in value.shape) or "scalar"
        cells = ", ".join(_element_text(item) for item in value.elements[:12])
        if len(value.elements) > 12:
            cells += ", …"
        text = f"{value.dtype.value} · {shape} · [{cells}]"
    elif isinstance(value, ComplexValue):
        text = _element_text(value)
    elif isinstance(value, QuantityValue):
        text = f"{_element_text(value.magnitude)} {value.unit.id}"
    elif isinstance(value, ResourceReference):
        text = f"Resource {value.id}"
    else:
        text = str(value)
    return text if len(text) <= maximum else text[: maximum - 1] + "…"


class ComplexValueEditor(QWidget):
    def __init__(self, value: ComplexValue | None = None) -> None:
        super().__init__()
        self.real = QLineEdit(str(value.real) if value else "0.0")
        self.imaginary = QLineEdit(str(value.imaginary) if value else "0.0")
        self.real.setObjectName("complexReal")
        self.imaginary.setObjectName("complexImaginary")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.real)
        layout.addWidget(QLabel("+"))
        layout.addWidget(self.imaginary)
        layout.addWidget(QLabel("i"))

    def value(self) -> ComplexValue:
        return ComplexValue(float(self.real.text()), float(self.imaginary.text()))


def _element_text(value: bool | int | float | ComplexValue) -> str:
    if isinstance(value, ComplexValue):
        return str(complex(value.real, value.imaginary))
    return str(value).lower() if isinstance(value, bool) else str(value)


class TensorValueEditor(QWidget):
    def __init__(self, value: TensorValue | None = None) -> None:
        super().__init__()
        value = value or TensorValue(TensorDType.FLOAT64, (1,), (0.0,))
        self.dtype = QComboBox()
        self.dtype.setObjectName("tensorDType")
        for kind in TensorDType:
            self.dtype.addItem(kind.value, kind.value)
        self.dtype.setCurrentIndex(self.dtype.findData(value.dtype.value))
        self.shape = QLineEdit(", ".join(str(size) for size in value.shape))
        self.shape.setObjectName("tensorShape")
        self.shape.setPlaceholderText("Dimensions, e.g. 2, 3; empty means scalar")
        self.table = QTableWidget()
        self.table.setObjectName("tensorElements")
        self.table.setMinimumHeight(125)
        self.message = QLabel(
            "Edit element cells. Higher dimensions are flattened into labeled rows."
        )
        self.message.setWordWrap(True)
        self._shape = value.shape
        self._set_cells(value.shape, tuple(_element_text(item) for item in value.elements))
        self.shape.editingFinished.connect(self.reshape)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        fields = QFormLayout()
        fields.addRow("Element type", self.dtype)
        fields.addRow("Shape", self.shape)
        layout.addLayout(fields)
        layout.addWidget(self.table)
        layout.addWidget(self.message)

    def _parsed_shape(self) -> tuple[int, ...]:
        text = self.shape.text().strip()
        shape = tuple(int(part) for part in re.split(r"[, x\u00d7]+", text)) if text else ()
        if (
            len(shape) > 16
            or any(size < 0 for size in shape)
            or math.prod(shape) > MAX_INLINE_ELEMENTS
        ):
            raise ValueError(
                "Use at most 16 dimensions and 1024 inline elements; larger data uses a resource"
            )
        return shape

    def _texts(self) -> tuple[str, ...]:
        return tuple(
            item.text() if (item := self.table.item(row, col)) is not None else "0"
            for row in range(self.table.rowCount())
            for col in range(self.table.columnCount())
        )

    def _set_cells(self, shape: tuple[int, ...], values: tuple[str, ...]) -> None:
        columns = min(shape[-1], MAX_INLINE_ELEMENTS) if shape else 1
        rows = math.prod(shape[:-1]) if shape else 1
        self.table.setRowCount(rows if math.prod(shape) else 0)
        self.table.setColumnCount(columns)
        for index in range(rows * columns):
            self.table.setItem(
                index // columns,
                index % columns,
                QTableWidgetItem(values[index] if index < len(values) else "0"),
            )
        self.table.setHorizontalHeaderLabels([str(index) for index in range(columns)])
        self._shape = shape

    def reshape(self) -> None:
        try:
            shape = self._parsed_shape()
            if shape != self._shape:
                self._set_cells(shape, self._texts())
            self.message.setText(
                "Edit element cells. Higher dimensions are flattened into labeled rows."
            )
        except ValueError as exc:
            self.message.setText(str(exc))

    def value(self) -> TensorValue:
        shape = self._parsed_shape()
        if shape != self._shape:
            self._set_cells(shape, self._texts())
        dtype = TensorDType(self.dtype.currentData())
        elements: list[bool | int | float | ComplexValue] = []
        for text in self._texts():
            if dtype is TensorDType.BOOL:
                if text.strip().lower() not in {"true", "false"}:
                    raise ValueError("Boolean tensor cells use true or false")
                elements.append(text.strip().lower() == "true")
            elif dtype.value.startswith(("int", "uint")):
                elements.append(int(text))
            elif dtype.value.startswith("complex"):
                scalar = complex(text.replace("i", "j"))
                elements.append(ComplexValue(float(scalar.real), float(scalar.imag)))
            else:
                elements.append(float(text))
        return TensorValue(dtype, shape, tuple(elements))


class DimensionValueEditor(QWidget):
    def __init__(self, value: Dimension | None = None) -> None:
        super().__init__()
        value = value or Dimension()
        self.table = QTableWidget(len(value.powers), 2)
        self.table.setHorizontalHeaderLabels(["Dimension identity", "Exact exponent (e.g. 1/2)"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.setMaximumHeight(145)
        for row, power in enumerate(value.powers):
            self.table.setItem(row, 0, QTableWidgetItem(power.basis_id))
            self.table.setItem(row, 1, QTableWidgetItem(str(power.exponent)))
        add = QPushButton("Add dimension")
        remove = QPushButton("Remove dimension")
        add.clicked.connect(lambda: self.table.insertRow(self.table.rowCount()))
        remove.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        actions = QHBoxLayout()
        actions.addWidget(add)
        actions.addWidget(remove)
        layout.addLayout(actions)

    def value(self) -> Dimension:
        powers = []
        for row in range(self.table.rowCount()):
            name, exponent = self.table.item(row, 0), self.table.item(row, 1)
            if name is None or exponent is None:
                raise ValueError("Every dimension needs an identity and an exact exponent")
            from fractions import Fraction

            raw = exponent.text().strip()
            pieces = raw.split("/")
            if len(pieces) not in (1, 2) or any(
                not piece.lstrip("+-").isdigit() for piece in pieces
            ):
                raise ValueError("Dimension powers use an integer or a ratio such as 1/2")
            try:
                power = Fraction(int(pieces[0]), int(pieces[1]) if len(pieces) == 2 else 1)
            except ZeroDivisionError as exc:
                raise ValueError("Dimension denominator cannot be zero") from exc
            powers.append(DimensionPower(name.text(), power))
        return Dimension(tuple(sorted(powers, key=lambda item: item.basis_id)))


class QuantityValueEditor(QWidget):
    def __init__(
        self,
        value: QuantityValue | None = None,
        unit_choices: tuple[tuple[str, UnitReference], ...] = (),
    ) -> None:
        super().__init__()
        self.magnitude_kind = QComboBox()
        for kind in ("integer", "real", "complex"):
            self.magnitude_kind.addItem(kind, kind)
        magnitude = value.magnitude if value else 0.0
        self.magnitude_kind.setCurrentIndex(
            2 if isinstance(magnitude, ComplexValue) else 0 if type(magnitude) is int else 1
        )
        self.real = QLineEdit(
            str(magnitude.real if isinstance(magnitude, ComplexValue) else magnitude)
        )
        self.imaginary = QLineEdit(
            str(magnitude.imaginary if isinstance(magnitude, ComplexValue) else 0.0)
        )
        self.unit_id = QLineEdit(value.unit.id if value else "unit:dimensionless")
        self.unit_version = QLineEdit(value.unit.version if value else "1")
        self.unit_id.setObjectName("quantityUnitId")
        self.unit_version.setObjectName("quantityUnitVersion")
        self.dimension_editor = DimensionValueEditor(value.unit.dimension if value else Dimension())
        self.dimensions = self.dimension_editor.table
        self.dimensions.setObjectName("quantityDimensions")
        self.unit_choice = QComboBox()
        self.unit_choice.setObjectName("quantityCatalogUnit")
        self.unit_choice.addItem("Enter an explicit unit reference", None)
        for label, unit in unit_choices:
            self.unit_choice.addItem(label, unit)
            if value is not None and value.unit == unit:
                self.unit_choice.setCurrentIndex(self.unit_choice.count() - 1)
        self.unit_choice.currentIndexChanged.connect(self._unit_selected)
        form = QFormLayout()
        form.addRow("Magnitude type", self.magnitude_kind)
        form.addRow("Real magnitude", self.real)
        form.addRow("Imaginary magnitude", self.imaginary)
        form.addRow("Declared unit", self.unit_choice)
        form.addRow("Unit identity", self.unit_id)
        form.addRow("Unit version", self.unit_version)
        form.addRow("Dimension", self.dimension_editor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(form)
        self.magnitude_kind.currentIndexChanged.connect(self._toggle)
        self._toggle()
        self._unit_selected()

    def _unit_selected(self, _index: int = 0) -> None:
        unit = self.unit_choice.currentData()
        selected = isinstance(unit, UnitReference)
        self.unit_id.setEnabled(not selected)
        self.unit_version.setEnabled(not selected)
        self.dimension_editor.setEnabled(not selected)
        if selected:
            self.unit_id.setText(unit.id)
            self.unit_version.setText(unit.version)
            self.dimensions.setRowCount(len(unit.dimension.powers))
            for row, power in enumerate(unit.dimension.powers):
                self.dimensions.setItem(row, 0, QTableWidgetItem(power.basis_id))
                self.dimensions.setItem(row, 1, QTableWidgetItem(str(power.exponent)))

    def _toggle(self, _index: int = 0) -> None:
        self.imaginary.setEnabled(self.magnitude_kind.currentData() == "complex")

    def value(self) -> QuantityValue:
        magnitude: int | float | ComplexValue
        if self.magnitude_kind.currentData() == "integer":
            magnitude = int(self.real.text())
        elif self.magnitude_kind.currentData() == "complex":
            magnitude = ComplexValue(float(self.real.text()), float(self.imaginary.text()))
        else:
            magnitude = float(self.real.text())
        selected = self.unit_choice.currentData()
        if isinstance(selected, UnitReference):
            return QuantityValue(magnitude, selected)
        dimension = self.dimension_editor.value()
        return QuantityValue(
            magnitude,
            UnitReference(self.unit_id.text(), self.unit_version.text(), dimension),
        )


class ResourceValueEditor(QWidget):
    def __init__(
        self,
        value: ResourceReference | None = None,
        resources: tuple[DataResource, ...] = (),
        resource_store: ResourceStore | None = None,
    ) -> None:
        super().__init__()
        self.resource_store = resource_store
        self.choice = QComboBox()
        self.choice.addItem("Enter an explicit resource reference", None)
        for resource in resources:
            self.choice.addItem(
                f"{resource.id} · {resource.media_type} · {resource.byte_size} bytes",
                resource.reference,
            )
        self.resource_id = QLineEdit(value.id if value else "")
        self.content_hash = QLineEdit(value.content_hash if value else "")
        self.resource_id.setObjectName("resourceReferenceId")
        self.content_hash.setObjectName("resourceReferenceHash")
        self.content_hash.setPlaceholderText("SHA-256 content hash")
        self.choice.currentIndexChanged.connect(self._selected)
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow("Resource", self.choice)
        form.addRow("Identity", self.resource_id)
        form.addRow("Content hash", self.content_hash)
        self.import_button = QPushButton("Import file into project resources")
        self.import_button.setObjectName("importDomainResource")
        self.import_button.setEnabled(resource_store is not None)
        self.import_button.setToolTip(
            "Save the project first to make a managed resource store available"
        )
        self.import_button.clicked.connect(self.import_file)
        form.addRow(self.import_button)

    def import_file(self) -> None:
        if self.resource_store is None:
            return
        filename, _filter = QFileDialog.getOpenFileName(self, "Import data resource")
        if not filename:
            return
        try:
            descriptor = self.resource_store.import_file(
                Path(filename), mimetypes.guess_type(filename)[0] or "application/octet-stream"
            )
            self.choice.addItem(
                f"{descriptor.id} · {descriptor.byte_size} bytes", descriptor.reference
            )
            self.choice.setCurrentIndex(self.choice.count() - 1)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Resource import failed", str(exc))

    def _selected(self, _index: int) -> None:
        value = self.choice.currentData()
        if isinstance(value, ResourceReference):
            self.resource_id.setText(value.id)
            self.content_hash.setText(value.content_hash)

    def value(self) -> ResourceReference:
        return ResourceReference(self.resource_id.text(), self.content_hash.text())
