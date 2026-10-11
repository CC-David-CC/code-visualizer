"""Conventional free-form vector editor over typed semantic commands."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from code_visualizer.application.commands import (
    CreateFreeformConnector,
    CreateFreeformShape,
    RegisterManagedAsset,
    SetFreeformObjectProperties,
    TransformFreeformObject,
)
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.selection import SelectionState
from code_visualizer.asset_management import (
    AssetSafetyError,
    import_managed_image,
    resolve_project_asset,
    verify_managed_asset,
)
from code_visualizer.domain.common import new_id
from code_visualizer.domain.freeform import (
    ConnectorObject,
    FreeformDiagram,
    GuideOrientation,
    Rect,
    ShapeKind,
    ShapeObject,
)
from code_visualizer.domain.project import Project
from code_visualizer.domain.semantic import SemanticObjectKind
from code_visualizer.rendering import layout_freeform
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.ui_qt.vector_canvas import VectorCanvas


class FreeformDocumentWidget(QWidget):
    projectChanged = Signal()

    def __init__(
        self,
        client: CodeVisualizerClient,
        diagram_id: str,
        project_root: Callable[[], Path | None] | None = None,
        ensure_saved: Callable[[], bool] | None = None,
        parent: QWidget | None = None,
        *,
        kernel: ProjectKernel | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("freeformDocument")
        self._client = client
        self.diagram_id = diagram_id
        self._selected_id: str | None = None
        self._project_root = project_root or (lambda: None)
        self._ensure_saved = ensure_saved or (lambda: False)
        self._asset_cache: dict[str, bytes] = {}
        self._kernel = kernel
        self._anchor_target: str | None = None

        self.header = QLabel()
        self.shape_kind = QComboBox()
        self.shape_kind.setObjectName("freeformShapeKind")
        for kind in ShapeKind:
            self.shape_kind.addItem(kind.value.replace("_", " ").title(), kind)
        self.add_shape_button = QPushButton("Add Shape")
        self.import_image_button = QPushButton("Import Image…")
        self.connector_style = QComboBox()
        self.connector_style.setObjectName("freeformConnectorStyle")
        self.connector_style.addItem("Orthogonal connector", True)
        self.connector_style.addItem("Free connector", False)
        self.connect_button = QPushButton("Connect Selected")
        self.duplicate_button = QPushButton("Duplicate")
        self.delete_button = QPushButton("Delete")
        self.group_button = QPushButton("Group")
        self.ungroup_button = QPushButton("Ungroup")
        self.lock_button = QPushButton("Lock / Unlock")
        self.front_button = QPushButton("Bring Front")
        self.back_button = QPushButton("Send Back")
        self.fit_button = QPushButton("Fit")
        self.add_shape_button.clicked.connect(self.add_shape)
        self.import_image_button.clicked.connect(self.import_image)
        self.connect_button.clicked.connect(self.connect_selected)
        self.duplicate_button.clicked.connect(self.duplicate_selected)
        self.delete_button.clicked.connect(self.delete_selected)
        self.group_button.clicked.connect(self.group_selected)
        self.ungroup_button.clicked.connect(self.ungroup_selected)
        self.lock_button.clicked.connect(self.toggle_lock)
        self.front_button.clicked.connect(lambda: self._z_order(True))
        self.back_button.clicked.connect(lambda: self._z_order(False))
        self.fit_button.clicked.connect(self._fit)
        controls = QHBoxLayout()
        controls.addWidget(self.header, 1)
        controls.addWidget(self.shape_kind)
        controls.addWidget(self.add_shape_button)
        controls.addWidget(self.import_image_button)
        controls.addWidget(self.connector_style)
        controls.addWidget(self.connect_button)
        controls.addWidget(self.duplicate_button)
        controls.addWidget(self.delete_button)
        controls.addWidget(self.group_button)
        controls.addWidget(self.ungroup_button)
        controls.addWidget(self.lock_button)
        controls.addWidget(self.front_button)
        controls.addWidget(self.back_button)
        controls.addWidget(self.fit_button)

        self.layer_choice = QComboBox()
        self.layer_choice.setObjectName("freeformActiveLayer")
        self.layer_name = QLineEdit()
        self.layer_name.setObjectName("freeformLayerName")
        self.layer_hidden = QCheckBox("Hidden")
        self.layer_locked = QCheckBox("Locked")
        self.add_layer_button = QPushButton("Add Layer")
        self.update_layer_button = QPushButton("Update Layer")
        self.remove_layer_button = QPushButton("Remove Layer")
        self.add_layer_button.clicked.connect(self.add_layer)
        self.update_layer_button.clicked.connect(self.update_layer)
        self.remove_layer_button.clicked.connect(self.remove_layer)
        self.layer_choice.currentIndexChanged.connect(self._load_layer_controls)
        layer_row = QHBoxLayout()
        layer_row.addWidget(QLabel("Active layer:"))
        layer_row.addWidget(self.layer_choice)
        layer_row.addWidget(QLabel("Name:"))
        layer_row.addWidget(self.layer_name)
        layer_row.addWidget(self.layer_hidden)
        layer_row.addWidget(self.layer_locked)
        layer_row.addWidget(self.add_layer_button)
        layer_row.addWidget(self.update_layer_button)
        layer_row.addWidget(self.remove_layer_button)

        self.guide_orientation = QComboBox()
        self.guide_orientation.addItem("Vertical", GuideOrientation.VERTICAL.value)
        self.guide_orientation.addItem("Horizontal", GuideOrientation.HORIZONTAL.value)
        self.guide_position = self._number("freeformGuidePosition")
        self.guide_choice = QComboBox()
        self.guide_choice.setObjectName("freeformGuideChoice")
        self.add_guide_button = QPushButton("Add Guide")
        self.remove_guide_button = QPushButton("Remove Guide")
        self.grid_size = self._number("freeformGridSize", minimum=1.0, maximum=10_000.0)
        self.snap_to_grid = QCheckBox("Snap to grid")
        self.apply_canvas_button = QPushButton("Apply Grid")
        self.add_guide_button.clicked.connect(self.add_guide)
        self.remove_guide_button.clicked.connect(self.remove_guide)
        self.apply_canvas_button.clicked.connect(self.apply_canvas_options)
        guide_row = QHBoxLayout()
        guide_row.addWidget(QLabel("Guide:"))
        guide_row.addWidget(self.guide_orientation)
        guide_row.addWidget(self.guide_position)
        guide_row.addWidget(self.add_guide_button)
        guide_row.addWidget(self.guide_choice)
        guide_row.addWidget(self.remove_guide_button)
        guide_row.addSpacing(16)
        guide_row.addWidget(QLabel("Grid size:"))
        guide_row.addWidget(self.grid_size)
        guide_row.addWidget(self.snap_to_grid)
        guide_row.addWidget(self.apply_canvas_button)
        guide_row.addStretch(1)

        self.canvas = VectorCanvas(mode="freeform", asset_bytes=self._managed_asset_bytes)
        self.canvas.objectSelected.connect(self._select_object)
        self.canvas.moveRequested.connect(self._move_objects)

        self.text = QLineEdit()
        self.text.setObjectName("freeformObjectText")
        self.x_value = self._number("freeformX")
        self.y_value = self._number("freeformY")
        self.width_value = self._number("freeformWidth", minimum=1.0)
        self.height_value = self._number("freeformHeight", minimum=1.0)
        self.rotation = self._number("freeformRotation", minimum=-360.0, maximum=360.0)
        self.fill = QLineEdit("#ffffff")
        self.fill.setObjectName("freeformFill")
        self.stroke = QLineEdit("#1f2937")
        self.stroke.setObjectName("freeformStroke")
        self.object_layer = QComboBox()
        self.object_layer.setObjectName("freeformObjectLayer")
        self.apply_button = QPushButton("Apply Object")
        self.apply_button.clicked.connect(self.apply_object)
        self.live_label_button = QPushButton("Use Live Label")
        self.live_label_button.setObjectName("freeformUseLiveLabel")
        self.live_label_button.setToolTip(
            "Remove the authored label override and follow semantic renames again."
        )
        self.live_label_button.clicked.connect(self.use_live_label)
        properties = QHBoxLayout()
        for label, widget in (
            ("Text", self.text),
            ("X", self.x_value),
            ("Y", self.y_value),
            ("Width", self.width_value),
            ("Height", self.height_value),
            ("Rotation", self.rotation),
            ("Fill", self.fill),
            ("Stroke", self.stroke),
            ("Layer", self.object_layer),
        ):
            properties.addWidget(QLabel(label + ":"))
            properties.addWidget(widget)
        properties.addWidget(self.apply_button)
        properties.addWidget(self.live_label_button)

        self.anchor_target = QLabel("Select code or a relationship in Code Visualizer first.")
        self.anchor_target.setObjectName("freeformAnchorTarget")
        self.anchor_state = QLabel("Annotation only")
        self.anchor_state.setObjectName("freeformAnchorState")
        self.link_semantic_button = QPushButton("Link Shape / Connector")
        self.link_semantic_button.setObjectName("linkFreeformSemantic")
        self.clear_semantic_button = QPushButton("Make Annotation Only")
        self.clear_semantic_button.setObjectName("clearFreeformSemantic")
        self.link_semantic_button.clicked.connect(self.link_to_selected_semantic)
        self.clear_semantic_button.clicked.connect(self.clear_semantic_anchor)
        anchor_row = QHBoxLayout()
        anchor_row.addWidget(QLabel("Semantic link:"))
        anchor_row.addWidget(self.anchor_state)
        anchor_row.addWidget(self.anchor_target, 1)
        anchor_row.addWidget(self.link_semantic_button)
        anchor_row.addWidget(self.clear_semantic_button)

        self.arrangement = QComboBox()
        for label, value in (
            ("Align left", "align_left"),
            ("Align right", "align_right"),
            ("Align top", "align_top"),
            ("Align bottom", "align_bottom"),
            ("Align horizontal centers", "align_horizontal_center"),
            ("Align vertical centers", "align_vertical_center"),
            ("Distribute horizontally", "distribute_horizontal"),
            ("Distribute vertically", "distribute_vertical"),
        ):
            self.arrangement.addItem(label, value)
        self.arrange_button = QPushButton("Arrange Selected")
        self.arrange_button.clicked.connect(self.arrange_selected)
        arrange_row = QHBoxLayout()
        arrange_row.addWidget(QLabel("Alignment / distribution:"))
        arrange_row.addWidget(self.arrangement)
        arrange_row.addWidget(self.arrange_button)
        arrange_row.addStretch(1)

        self.status = QLabel()
        self.status.setObjectName("freeformStatus")
        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addLayout(layer_row)
        layout.addLayout(guide_row)
        layout.addWidget(self.canvas, 1)
        layout.addLayout(properties)
        layout.addLayout(anchor_row)
        layout.addLayout(arrange_row)
        layout.addWidget(self.status)
        self.refresh(client.snapshot())
        if kernel is not None:
            self.update_shared_selection(kernel.selection.state)

    @staticmethod
    def _number(
        name: str,
        *,
        minimum: float = -1_000_000.0,
        maximum: float = 1_000_000.0,
    ) -> QDoubleSpinBox:
        widget = QDoubleSpinBox()
        widget.setObjectName(name)
        widget.setRange(minimum, maximum)
        widget.setDecimals(2)
        return widget

    def _document(self, project: Project) -> FreeformDiagram | None:
        if self._kernel is not None and self._kernel.revision == project.revision:
            resolved = self._kernel.queries.resolved_document(self.diagram_id)
            if isinstance(resolved, FreeformDiagram):
                return resolved
        return next(
            (
                item
                for item in project.documents
                if isinstance(item, FreeformDiagram) and item.id == self.diagram_id
            ),
            None,
        )

    def _managed_asset_bytes(self, asset_id: str) -> bytes | None:
        cached = self._asset_cache.get(asset_id)
        if cached is not None:
            return cached
        root = self._project_root()
        asset = next(
            (item for item in self._client.snapshot().managed_assets if item.id == asset_id),
            None,
        )
        if root is None or asset is None or not verify_managed_asset(root, asset):
            return None
        try:
            data = resolve_project_asset(root, asset.relative_path).read_bytes()
        except (OSError, AssetSafetyError):
            return None
        self._asset_cache[asset_id] = data
        return data

    def refresh(self, project: Project) -> None:
        document = self._document(project)
        if document is None:
            self.header.setText("Free-form document unavailable")
            return
        self.header.setText(document.title)
        active_layer = self.layer_choice.currentData()
        object_layer = self.object_layer.currentData()
        layer_blocker = QSignalBlocker(self.layer_choice)
        object_layer_blocker = QSignalBlocker(self.object_layer)
        self.layer_choice.clear()
        self.object_layer.clear()
        for layer in document.layers:
            flags = ""
            if layer.hidden:
                flags += " · hidden"
            if layer.locked:
                flags += " · locked"
            self.layer_choice.addItem(layer.name + flags, layer.id)
            self.object_layer.addItem(layer.name + flags, layer.id)
        layer_index = self.layer_choice.findData(active_layer)
        self.layer_choice.setCurrentIndex(max(0, layer_index))
        object_layer_index = self.object_layer.findData(object_layer)
        self.object_layer.setCurrentIndex(max(0, object_layer_index))
        del layer_blocker, object_layer_blocker
        self._load_layer_controls()
        guide_blocker = QSignalBlocker(self.guide_choice)
        self.guide_choice.clear()
        for guide in document.guides:
            self.guide_choice.addItem(
                f"{guide.orientation.value.title()} · {guide.position:g}",
                guide.id,
            )
        del guide_blocker
        self.grid_size.setValue(document.grid_size)
        self.snap_to_grid.setChecked(document.snap_to_grid)
        self.canvas.set_vector_scene(layout_freeform(document))
        if self._selected_id in {item.id for item in document.objects}:
            self.canvas.select_objects((self._selected_id,))
            self._select_object(self._selected_id or "")

    def _shape(self, object_id: str | None = None) -> ShapeObject | None:
        document = self._document(self._client.snapshot())
        selected = object_id or self._selected_id
        if document is None or selected is None:
            return None
        return next(
            (
                item
                for item in document.objects
                if isinstance(item, ShapeObject) and item.id == selected
            ),
            None,
        )

    def _selected_object(self) -> ShapeObject | ConnectorObject | None:
        document = self._document(self._client.snapshot())
        if document is None or self._selected_id is None:
            return None
        return next(
            (item for item in document.objects if item.id == self._selected_id),
            None,
        )

    def _select_object(self, object_id: str) -> None:
        self._selected_id = object_id
        selected_object = self._selected_object()
        self._update_anchor_state(selected_object)
        shape = self._shape(object_id)
        if shape is None:
            self.apply_button.setEnabled(False)
            self.live_label_button.setEnabled(False)
            return
        self.apply_button.setEnabled(not shape.locked)
        document = self._document(self._client.snapshot())
        self.live_label_button.setEnabled(
            not shape.locked
            and document is not None
            and document.live_projection is not None
            and shape.semantic_id is not None
            and shape.label_override is not None
        )
        self.text.setText(shape.text)
        self.x_value.setValue(shape.bounds.x)
        self.y_value.setValue(shape.bounds.y)
        self.width_value.setValue(shape.bounds.width)
        self.height_value.setValue(shape.bounds.height)
        self.rotation.setValue(shape.rotation)
        self.fill.setText(shape.fill)
        self.stroke.setText(shape.stroke)
        layer_index = self.object_layer.findData(shape.layer_id)
        if layer_index >= 0:
            self.object_layer.setCurrentIndex(layer_index)

    def update_shared_selection(self, state: SelectionState) -> None:
        self._anchor_target = state.primary
        kernel = self._kernel
        selected = self._selected_object()
        semantic = (
            kernel.queries.semantic_object(state.primary)
            if (kernel is not None and state.primary is not None)
            else None
        )
        relation = (
            kernel.queries.semantic_relation(state.primary)
            if (kernel is not None and state.primary is not None)
            else None
        )
        usable_object = (
            isinstance(selected, ShapeObject)
            and semantic is not None
            and (
                semantic.kind
                not in {
                    SemanticObjectKind.VIEW,
                    SemanticObjectKind.GLYPH,
                    SemanticObjectKind.ANNOTATION,
                }
            )
        )
        usable_relation = isinstance(selected, ConnectorObject) and relation is not None
        self.link_semantic_button.setEnabled(usable_object or usable_relation)
        if semantic is not None:
            self.anchor_target.setText(
                f"Selected object: {semantic.label} · {semantic.kind.value} · {semantic.id}"
            )
        elif relation is not None:
            self.anchor_target.setText(f"Selected relation: {relation.kind.value} · {relation.id}")
        else:
            self.anchor_target.setText("Select code or a relationship in Code Visualizer first.")

    def _update_anchor_state(self, selected: ShapeObject | ConnectorObject | None) -> None:
        if isinstance(selected, ShapeObject):
            anchor = selected.semantic_id
        elif isinstance(selected, ConnectorObject):
            anchor = selected.semantic_relation_id
        else:
            anchor = None
        if anchor is None:
            self.anchor_state.setText("Annotation only")
            self.clear_semantic_button.setEnabled(False)
            return
        kernel = self._kernel
        semantic = kernel.queries.semantic_object(anchor) if kernel is not None else None
        relation = kernel.queries.semantic_relation(anchor) if kernel is not None else None
        label = (
            semantic.label
            if semantic is not None
            else (relation.kind.value if relation is not None else "Unresolved")
        )
        self.anchor_state.setText(f"Linked: {label} · {anchor}")
        self.clear_semantic_button.setEnabled(True)

    def link_to_selected_semantic(self) -> None:
        document = self._document(self._client.snapshot())
        selected = self._selected_object()
        kernel = self._kernel
        target = self._anchor_target
        if document is None or selected is None or kernel is None or target is None:
            self.status.setText("Select a shape/connector and a semantic target first.")
            return
        if isinstance(selected, ShapeObject):
            semantic = kernel.queries.semantic_object(target)
            if semantic is None or semantic.kind in {
                SemanticObjectKind.VIEW,
                SemanticObjectKind.GLYPH,
                SemanticObjectKind.ANNOTATION,
            }:
                self.status.setText("Shapes link to executable semantic objects.")
                return
            result = self._client.set_view_anchor(
                document.id,
                selected.id,
                semantic_id=semantic.id,
            )
        else:
            relation = kernel.queries.semantic_relation(target)
            if relation is None:
                self.status.setText("Connectors link to semantic relationships.")
                return
            result = self._client.set_view_anchor(
                document.id,
                selected.id,
                semantic_relation_id=relation.id,
            )
        self._after(result, (selected.id,))

    def clear_semantic_anchor(self) -> None:
        document = self._document(self._client.snapshot())
        selected = self._selected_object()
        if document is None or selected is None:
            return
        self._after(
            self._client.set_view_anchor(document.id, selected.id),
            (selected.id,),
        )

    def _after(self, result: object, selected: tuple[str, ...] = ()) -> None:
        if not isinstance(result, CommandAccepted):
            self.status.setText(
                "The semantic edit was rejected; locked or invalid objects remain unchanged."
            )
            return
        if selected:
            self._selected_id = selected[-1]
        self.refresh(self._client.snapshot())
        if selected:
            self.canvas.select_objects(selected)
        self.status.setText(f"Applied at revision {result.revision}")
        self.projectChanged.emit()

    def add_shape(self) -> None:
        document = self._document(self._client.snapshot())
        raw_kind = self.shape_kind.currentData()
        try:
            kind = ShapeKind(str(raw_kind))
        except ValueError:
            self.status.setText("Choose a supported free-form shape kind.")
            return
        if document is None:
            return
        layer_id = self.layer_choice.currentData()
        if not isinstance(layer_id, str):
            self.status.setText("Choose an active layer before adding a shape.")
            return
        count = sum(isinstance(item, ShapeObject) for item in document.objects)
        object_id = new_id("shape")
        result = self._client.create_freeform_shape(
            document.id,
            kind,
            Rect(
                40.0 + count * 220.0,
                40.0 + (count % 3) * 130.0,
                180.0,
                84.0,
            ),
            text=f"{kind.value.replace('_', ' ').title()} {count + 1}",
            object_id=object_id,
            layer_id=layer_id,
        )
        self._after(result, (object_id,))

    def import_image(self) -> None:
        source_name, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Import managed image",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif);;All files (*)",
        )
        if not source_name:
            return
        root = self._project_root()
        if root is None:
            if not self._ensure_saved():
                self.status.setText("Save the project to a folder before importing an image.")
                return
            root = self._project_root()
        if root is None:
            self.status.setText("A project folder is required for managed images.")
            return
        document = self._document(self._client.snapshot())
        layer_id = self.layer_choice.currentData()
        if document is None or not isinstance(layer_id, str):
            return
        try:
            asset = import_managed_image(root, Path(source_name))
        except AssetSafetyError as exc:
            self.status.setText(f"Image rejected ({exc.code}): {exc}")
            return
        object_id = new_id("shape")
        max_width = 360.0
        source_width = float(asset.width or 240)
        source_height = float(asset.height or 180)
        width = min(max_width, max(80.0, source_width))
        height = max(60.0, width * source_height / max(1.0, source_width))
        count = sum(isinstance(item, ShapeObject) for item in document.objects)
        bounds = Rect(40.0 + count * 28.0, 40.0 + count * 28.0, width, height)
        commands: list[RegisterManagedAsset | CreateFreeformShape | TransformFreeformObject] = []
        if not any(item.id == asset.id for item in self._client.snapshot().managed_assets):
            commands.append(RegisterManagedAsset(asset))
        commands.extend(
            (
                CreateFreeformShape(
                    document.id,
                    ShapeKind.IMAGE,
                    bounds,
                    asset.original_name,
                    object_id,
                    layer_id,
                ),
                TransformFreeformObject(
                    document.id,
                    object_id,
                    bounds,
                    asset_id=asset.id,
                ),
            )
        )
        self._after(
            self._client.transaction(commands, intent="Import a sanitized managed image"),
            (object_id,),
        )

    def connect_selected(self) -> None:
        document = self._document(self._client.snapshot())
        selected = self.canvas.selected_object_ids()
        if document is None or len(selected) != 2:
            self.status.setText("Select exactly two shapes to create a connector.")
            return
        orthogonal = self.connector_style.currentData()
        self._after(
            self._client.connect_freeform_objects(
                document.id,
                selected[0],
                selected[1],
                orthogonal=bool(orthogonal),
            ),
            selected,
        )

    def apply_object(self) -> None:
        document = self._document(self._client.snapshot())
        shape = self._shape()
        if document is None or shape is None:
            return
        bounds = Rect(
            self.x_value.value(),
            self.y_value.value(),
            self.width_value.value(),
            self.height_value.value(),
        )
        layer_id = self.object_layer.currentData()
        commands: list[TransformFreeformObject | SetFreeformObjectProperties] = [
            TransformFreeformObject(
                document.id,
                shape.id,
                bounds,
                self.rotation.value(),
                self.text.text(),
                self.fill.text().strip() or "#ffffff",
                self.stroke.text().strip() or "#1f2937",
            )
        ]
        if isinstance(layer_id, str) and layer_id != shape.layer_id:
            commands.append(
                SetFreeformObjectProperties(document.id, (shape.id,), layer_id=layer_id)
            )
        self._after(
            self._client.transaction(commands, intent="Edit free-form object"),
            (shape.id,),
        )

    def use_live_label(self) -> None:
        document = self._document(self._client.snapshot())
        shape = self._shape()
        if document is None or shape is None:
            return
        self._after(
            self._client.transform_freeform_object(
                document.id,
                shape.id,
                shape.bounds,
                rotation=shape.rotation,
                derive_label=True,
            ),
            (shape.id,),
        )

    def _move_objects(self, raw_ids: object, dx: float, dy: float) -> None:
        if not isinstance(raw_ids, tuple) or not all(isinstance(item, str) for item in raw_ids):
            return
        document = self._document(self._client.snapshot())
        if document is None:
            return
        by_id = {item.id: item for item in document.objects if isinstance(item, ShapeObject)}
        moving_ids = tuple(item for item in raw_ids if item in by_id and not by_id[item].locked)
        if document.snap_to_grid and moving_ids:
            anchor = by_id[moving_ids[0]].bounds
            dx = round((anchor.x + dx) / document.grid_size) * document.grid_size - anchor.x
            dy = round((anchor.y + dy) / document.grid_size) * document.grid_size - anchor.y
        commands = tuple(
            TransformFreeformObject(
                document.id,
                object_id,
                Rect(
                    by_id[object_id].bounds.x + dx,
                    by_id[object_id].bounds.y + dy,
                    by_id[object_id].bounds.width,
                    by_id[object_id].bounds.height,
                ),
                by_id[object_id].rotation,
            )
            for object_id in raw_ids
            if object_id in moving_ids
        )
        if commands:
            self._after(
                self._client.transaction(commands, intent="Move free-form selection"),
                tuple(command.object_id for command in commands),
            )

    def duplicate_selected(self) -> None:
        document = self._document(self._client.snapshot())
        selected = set(self.canvas.selected_object_ids())
        if document is None or not selected:
            return
        shapes = [
            item
            for item in document.objects
            if isinstance(item, ShapeObject) and item.id in selected
        ]
        identifiers = {item.id: new_id("shape") for item in shapes}
        commands: list[CreateFreeformShape | TransformFreeformObject | CreateFreeformConnector] = []
        for item in shapes:
            bounds = Rect(
                item.bounds.x + 24.0,
                item.bounds.y + 24.0,
                item.bounds.width,
                item.bounds.height,
            )
            copied_id = identifiers[item.id]
            commands.append(
                CreateFreeformShape(
                    document.id,
                    item.shape,
                    bounds,
                    item.text,
                    copied_id,
                    item.layer_id,
                )
            )
            commands.append(
                TransformFreeformObject(
                    document.id,
                    copied_id,
                    bounds,
                    item.rotation,
                    item.text,
                    item.fill,
                    item.stroke,
                    item.asset_id or "",
                )
            )
        for connector in document.objects:
            if (
                isinstance(connector, ConnectorObject)
                and connector.source_id in identifiers
                and connector.target_id in identifiers
            ):
                commands.append(
                    CreateFreeformConnector(
                        document.id,
                        identifiers[connector.source_id],
                        identifiers[connector.target_id],
                        connector.label,
                        connector.orthogonal,
                    )
                )
        if commands:
            self._after(
                self._client.transaction(tuple(commands), intent="Duplicate free-form selection"),
                tuple(identifiers.values()),
            )

    def delete_selected(self) -> None:
        document = self._document(self._client.snapshot())
        selected = self.canvas.selected_object_ids()
        if document is not None and selected:
            self._after(self._client.remove_freeform_objects(document.id, selected))

    def group_selected(self) -> None:
        document = self._document(self._client.snapshot())
        selected = self.canvas.selected_object_ids()
        if document is not None and len(selected) >= 2:
            self._after(
                self._client.set_freeform_properties(
                    document.id,
                    selected,
                    group_id=new_id("group"),
                ),
                selected,
            )

    def ungroup_selected(self) -> None:
        document = self._document(self._client.snapshot())
        selected = self.canvas.selected_object_ids()
        if document is not None and selected:
            self._after(
                self._client.set_freeform_properties(document.id, selected, group_id=""),
                selected,
            )

    def toggle_lock(self) -> None:
        document = self._document(self._client.snapshot())
        selected = self.canvas.selected_object_ids()
        if document is None or not selected:
            return
        objects = {item.id: item for item in document.objects}
        lock = not all(getattr(objects[item], "locked", False) for item in selected)
        self._after(
            self._client.set_freeform_properties(document.id, selected, locked=lock),
            selected,
        )

    def _z_order(self, front: bool) -> None:
        document = self._document(self._client.snapshot())
        selected = self.canvas.selected_object_ids()
        shapes = (
            [item for item in document.objects if isinstance(item, ShapeObject)] if document else []
        )
        if document is None or not selected or not shapes:
            return
        z_index = (
            (max(item.z_index for item in shapes) + 1)
            if front
            else (min(item.z_index for item in shapes) - 1)
        )
        self._after(
            self._client.set_freeform_properties(document.id, selected, z_index=z_index),
            selected,
        )

    def arrange_selected(self) -> None:
        document = self._document(self._client.snapshot())
        selected = self.canvas.selected_object_ids()
        arrangement = self.arrangement.currentData()
        if document is None or len(selected) < 2 or not isinstance(arrangement, str):
            self.status.setText("Select at least two shapes to align or distribute.")
            return
        self._after(
            self._client.arrange_freeform_objects(document.id, selected, arrangement),
            selected,
        )

    def _load_layer_controls(self, _index: int = -1) -> None:
        document = self._document(self._client.snapshot())
        layer_id = self.layer_choice.currentData()
        layer = (
            next((item for item in document.layers if item.id == layer_id), None)
            if document is not None and isinstance(layer_id, str)
            else None
        )
        if layer is None:
            return
        self.layer_name.setText(layer.name)
        self.layer_hidden.setChecked(layer.hidden)
        self.layer_locked.setChecked(layer.locked)
        self.remove_layer_button.setEnabled(layer.id != "layer_default")
        self.add_shape_button.setEnabled(not layer.locked)

    def add_layer(self) -> None:
        document = self._document(self._client.snapshot())
        if document is None:
            return
        layer_id = new_id("layer")
        result = self._client.add_freeform_layer(
            document.id,
            self.layer_name.text().strip() or f"Layer {len(document.layers) + 1}",
            layer_id=layer_id,
        )
        self._after(result)
        index = self.layer_choice.findData(layer_id)
        if index >= 0:
            self.layer_choice.setCurrentIndex(index)

    def update_layer(self) -> None:
        document = self._document(self._client.snapshot())
        layer_id = self.layer_choice.currentData()
        if document is None or not isinstance(layer_id, str):
            return
        self._after(
            self._client.update_freeform_layer(
                document.id,
                layer_id,
                self.layer_name.text().strip() or "Layer",
                hidden=self.layer_hidden.isChecked(),
                locked=self.layer_locked.isChecked(),
            )
        )

    def remove_layer(self) -> None:
        document = self._document(self._client.snapshot())
        layer_id = self.layer_choice.currentData()
        if document is None or not isinstance(layer_id, str):
            return
        self._after(self._client.remove_freeform_layer(document.id, layer_id))

    def add_guide(self) -> None:
        document = self._document(self._client.snapshot())
        raw_orientation = self.guide_orientation.currentData()
        if document is None or not isinstance(raw_orientation, str):
            return
        self._after(
            self._client.add_freeform_guide(
                document.id,
                GuideOrientation(raw_orientation),
                self.guide_position.value(),
            )
        )

    def remove_guide(self) -> None:
        document = self._document(self._client.snapshot())
        guide_id = self.guide_choice.currentData()
        if document is not None and isinstance(guide_id, str):
            self._after(self._client.remove_freeform_guide(document.id, guide_id))

    def apply_canvas_options(self) -> None:
        document = self._document(self._client.snapshot())
        if document is not None:
            self._after(
                self._client.configure_freeform_canvas(
                    document.id,
                    self.grid_size.value(),
                    self.snap_to_grid.isChecked(),
                )
            )

    def _fit(self) -> None:
        self.canvas.fit_content()
