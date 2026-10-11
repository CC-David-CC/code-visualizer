"""Render compiled visual primitives and submit their explicit semantic edit intents."""

from __future__ import annotations

from math import atan2, cos, sin

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QKeyEvent,
    QMouseEvent,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QInputDialog,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.messages import CommandRejected
from code_visualizer.application.notation_canvas import CanvasItem, CanvasKind, NotationCanvas
from code_visualizer.application.notations import NotationEditKind, notation_edit_command
from code_visualizer.domain.intentional import DomainValue
from code_visualizer.domain.notation_syntax import VisualShape
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.ui_qt.features.domain_workbench.editors import (
    RICH_VALUE_KINDS,
    ReferenceEditor,
    ValueDialog,
    parse_scalar,
)
from code_visualizer.ui_qt.font_support import register_application_fonts

_ITEM = 71
_SEMANTICS = 72


class _CanvasView(QGraphicsView):
    editRequested = Signal(str)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        item = self.itemAt(event.position().toPoint())
        while item is not None and not isinstance(item.data(_ITEM), CanvasItem):
            item = item.parentItem()
        if item is not None and isinstance(item.data(_ITEM), CanvasItem):
            self.editRequested.emit(item.data(_ITEM).id)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in {Qt.Key.Key_F2, Qt.Key.Key_Return}:
            for item in self.scene().selectedItems():
                value = item.data(_ITEM)
                if isinstance(value, CanvasItem) and value.edit is not None:
                    self.editRequested.emit(value.id)
                    event.accept()
                    return
        super().keyPressEvent(event)


class ComposedCanvasWidget(QWidget):
    selectionRequested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("composedNotationCanvas")
        self.scene = QGraphicsScene(self)
        self.view = _CanvasView(self.scene)
        self.view.setObjectName("composedNotationView")
        self.view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.view.editRequested.connect(self.edit_item)
        self.scene.selectionChanged.connect(self._selected)
        self.status = QLabel(
            "Select a semantic element; double-click a bound field or press F2 to edit."
        )
        self.status.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view, 1)
        layout.addWidget(self.status)
        self._kernel: ProjectKernel | None = None
        self._client: CodeVisualizerClient | None = None
        self._guard = False
        self.canvas: NotationCanvas | None = None
        self.items_by_id: dict[str, QGraphicsItem] = {}
        self._adornments: list[QGraphicsItem] = []
        self._runtime_backgrounds: dict[str, QGraphicsRectItem] = {}
        self._connector_items: dict[str, QGraphicsPathItem] = {}

    def attach(self, kernel: ProjectKernel | None, client: CodeVisualizerClient | None) -> None:
        self._kernel, self._client = kernel, client

    def set_canvas(self, canvas: NotationCanvas | None) -> None:
        self._guard = True
        self.canvas = canvas
        self.items_by_id.clear()
        self._adornments.clear()
        self._runtime_backgrounds.clear()
        self._connector_items.clear()
        self.scene.clear()
        try:
            if canvas is None:
                return
            for value in canvas.items:
                item: QGraphicsItem
                if value.kind is CanvasKind.BOX:
                    path = QPainterPath()
                    rectangle = QRectF(0, 0, value.width, value.height)
                    if value.shape is VisualShape.ELLIPSE:
                        path.addEllipse(rectangle)
                    elif value.shape is VisualShape.ROUNDED:
                        path.addRoundedRect(rectangle, 8, 8)
                    else:
                        path.addRect(rectangle)
                    shape = QGraphicsPathItem(path)
                    shape.setBrush(QBrush(QColor("#ffe4b5" if value.active else value.fill)))
                    shape.setPen(QPen(QColor(value.stroke), 1.5))
                    shape.setZValue(-1)
                    item = shape
                elif value.kind is CanvasKind.PATH:
                    path = QPainterPath()
                    if value.points:
                        path.moveTo(*value.points[0])
                        for point in value.points[1:]:
                            path.lineTo(*point)
                    if value.closed:
                        path.closeSubpath()
                    drawing = QGraphicsPathItem(path)
                    drawing.setPen(QPen(QColor(value.stroke), 1.5))
                    drawing.setBrush(QBrush(QColor(value.fill)))
                    item = drawing
                else:
                    text = QGraphicsTextItem(value.text)
                    font = QFont(register_application_fonts().code)
                    font.setPixelSize(max(1, round(value.font_size)))
                    font.setBold(value.strong)
                    text.setFont(font)
                    text.document().setDocumentMargin(0)
                    text.setDefaultTextColor(QColor(value.stroke))
                    text.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
                    text.setZValue(2)
                    if value.active:
                        background = QGraphicsRectItem(0, 0, value.width, value.height, text)
                        background.setBrush(QBrush(QColor("#ffe4b5")))
                        background.setPen(QPen(Qt.PenStyle.NoPen))
                        background.setFlag(QGraphicsItem.GraphicsItemFlag.ItemStacksBehindParent)
                        self._adornments.append(background)
                        self._runtime_backgrounds[value.id] = background
                    item = text
                item.setPos(value.x, value.y)
                item.setData(_ITEM, value)
                item.setData(_SEMANTICS, value.semantic_ids)
                item.setFlag(
                    QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, bool(value.semantic_ids)
                )
                item.setToolTip(
                    ("Editable field" if value.edit else "Semantic element")
                    + (" · active" if value.active else "")
                )
                self.scene.addItem(item)
                self.items_by_id[value.id] = item
            for connector in canvas.connectors:
                path = QPainterPath(QPointF(*connector.start))
                path.lineTo(*connector.end)
                line = QGraphicsPathItem(path)
                line.setPen(QPen(QColor("#b45309" if connector.active else connector.stroke), 1.5))
                line.setData(_SEMANTICS, (connector.source_id, connector.target_id))
                line.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
                self.scene.addItem(line)
                self._connector_items[connector.id] = line
                if connector.arrow:
                    end = QPointF(*connector.end)
                    angle = atan2(
                        connector.end[1] - connector.start[1], connector.end[0] - connector.start[0]
                    )
                    arrow = QGraphicsPolygonItem(
                        QPolygonF(
                            (
                                end,
                                end - QPointF(cos(angle - 0.45) * 9, sin(angle - 0.45) * 9),
                                end - QPointF(cos(angle + 0.45) * 9, sin(angle + 0.45) * 9),
                            )
                        ),
                        line,
                    )
                    arrow.setBrush(QBrush(QColor(connector.stroke)))
                    arrow.setPen(QPen(QColor(connector.stroke)))
                    self._adornments.append(arrow)
                if connector.label:
                    label = QGraphicsTextItem(connector.label, line)
                    font = QFont(register_application_fonts().interface)
                    font.setPixelSize(12)
                    label.setFont(font)
                    label.setDefaultTextColor(QColor(connector.stroke))
                    bounds = label.boundingRect()
                    label.setPos(
                        (connector.start[0] + connector.end[0]) / 2 - bounds.width() / 2,
                        (connector.start[1] + connector.end[1]) / 2 - bounds.height() - 3,
                    )
                    self._adornments.append(label)
            self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-12, -12, 12, 12))
        finally:
            self._guard = False

    def update_runtime(self, canvas: NotationCanvas | None) -> None:
        """Apply new activity to existing geometry without losing selection or pan."""
        if canvas is None or self.canvas is None:
            if canvas is not self.canvas:
                self.set_canvas(canvas)
            return
        if (
            canvas.definition_id != self.canvas.definition_id
            or canvas.revision != self.canvas.revision
            or {item.id for item in canvas.items} != self.items_by_id.keys()
        ):
            self.set_canvas(canvas)
            return
        self.canvas = canvas
        for value in canvas.items:
            item = self.items_by_id[value.id]
            item.setData(_ITEM, value)
            if value.kind is CanvasKind.BOX and isinstance(item, QGraphicsPathItem):
                item.setBrush(QBrush(QColor("#ffe4b5" if value.active else value.fill)))
            elif isinstance(item, QGraphicsTextItem):
                background = self._runtime_backgrounds.get(value.id)
                if background is None and value.active:
                    background = QGraphicsRectItem(0, 0, value.width, value.height, item)
                    background.setBrush(QBrush(QColor("#ffe4b5")))
                    background.setPen(QPen(Qt.PenStyle.NoPen))
                    background.setFlag(QGraphicsItem.GraphicsItemFlag.ItemStacksBehindParent)
                    self._runtime_backgrounds[value.id] = background
                if background is not None:
                    background.setVisible(value.active)
            item.setToolTip(
                ("Editable field" if value.edit else "Semantic element")
                + (" · active" if value.active else "")
            )
        for connector in canvas.connectors:
            line = self._connector_items.get(connector.id)
            if line is not None:
                color = QColor("#b45309" if connector.active else connector.stroke)
                line.setPen(QPen(color, 1.5))
                for child in line.childItems():
                    if isinstance(child, QGraphicsPolygonItem):
                        child.setBrush(QBrush(color))
                        child.setPen(QPen(color))

    def _selected(self) -> None:
        if self._guard:
            return
        identities = tuple(
            dict.fromkeys(
                identity
                for item in self.scene.selectedItems()
                for identity in (item.data(_SEMANTICS) or ())
            )
        )
        if identities:
            self.selectionRequested.emit(identities)

    def select_semantic_ids(self, identities: tuple[str, ...]) -> None:
        self._guard = True
        try:
            for item in self.items_by_id.values():
                item.setSelected(bool(set(item.data(_SEMANTICS) or ()).intersection(identities)))
        finally:
            self._guard = False

    def edit_item(self, identity: str) -> None:
        if self.canvas is None or self._kernel is None or self._client is None:
            return
        item = next((value for value in self.canvas.items if value.id == identity), None)
        binding = item.edit if item else None
        if item is None or binding is None:
            return
        value: DomainValue | tuple[str, ...] | None
        workspace = self._kernel.authority.snapshot().domain_workspace
        owning_model = workspace.model(binding.model_id)
        resolved_node = owning_model.node(binding.node_id) if owning_model else None
        if resolved_node is None:
            return
        try:
            if binding.kind is NotationEditKind.REFERENCE:
                workspace = self._kernel.authority.snapshot().domain_workspace
                model = workspace.model(binding.model_id)
                schema = workspace.schema(model.schema_id) if model else None
                node = model.node(binding.node_id) if model else None
                if (
                    model is None
                    or schema is None
                    or node is None
                    or binding.role_definition is None
                ):
                    return
                dialog = QDialog(self)
                dialog.setWindowTitle(binding.role_definition.name)
                layout = QVBoxLayout(dialog)
                editor = ReferenceEditor(
                    binding.role_definition,
                    schema,
                    model,
                    node.reference_ids(binding.field_id),
                    workspace=self._kernel.authority.snapshot().domain_workspace,
                )
                layout.addWidget(editor)
                buttons = QDialogButtonBox(
                    QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
                )
                buttons.accepted.connect(dialog.accept)
                buttons.rejected.connect(dialog.reject)
                layout.addWidget(buttons)
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    return
                value = editor.target_ids()
            else:
                prop = binding.property_definition
                if prop is None:
                    return
                if prop.value_kind in RICH_VALUE_KINDS:
                    store = self._kernel.resource_store
                    dialog_value = ValueDialog(
                        prop,
                        resolved_node.property(prop.id),
                        self,
                        resources=store.descriptors() if store is not None else (),
                        resource_store=store,
                    )
                    if dialog_value.exec() != QDialog.DialogCode.Accepted:
                        return
                    value = dialog_value.result_value
                else:
                    entered, accepted = QInputDialog.getText(
                        self, "Edit semantic field", prop.name, text=item.text
                    )
                    if not accepted:
                        return
                    value = parse_scalar(entered, prop.value_kind)
            command = notation_edit_command(binding, value, revision=self._kernel.revision)
            result = self._client.submit(command, expected_revision=binding.revision)
            self.status.setText(
                result.message
                if isinstance(result, CommandRejected)
                else "Semantic field updated in every view."
            )
        except ValueError as exc:
            self.status.setText(str(exc))
