"""Disposable semantic graph projections over the shared project kernel."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QKeyEvent,
    QPainter,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from code_visualizer.application.kernel import KernelEvent, ProjectKernel
from code_visualizer.application.messages import CommandAccepted, CommandRejected
from code_visualizer.application.projection_language import builtin_projection_definition
from code_visualizer.application.projection_layout import projection_positions
from code_visualizer.application.runtime_overlay import RuntimeOverlayContext
from code_visualizer.application.runtime_projection import (
    RuntimeAdapterKind,
)
from code_visualizer.application.runtime_sessions import RuntimeSessionState
from code_visualizer.application.selection import SelectionState
from code_visualizer.domain.common import new_id
from code_visualizer.domain.projection import ProjectionDefinition, ProjectionViewTarget
from code_visualizer.domain.semantic import (
    ProjectionKind,
    SemanticObjectKind,
    SemanticProjection,
)
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.ui_qt.features.semantic_visualizer.composer import (
    AuthoredRelationDialog,
    ProjectionComposerDialog,
    SemanticConceptDialog,
)
from code_visualizer.ui_qt.features.semantic_visualizer.scene_reconciler import (
    SceneReconciler,
)
from code_visualizer.ui_qt.features.semantic_visualizer.semantic_text import (
    SemanticTextWidget,
)
from code_visualizer.ui_qt.runtime_observer import QtRuntimeObserver

_SEMANTIC_ID_ROLE = 10_201
_NODE_ID_ROLE = 10_202
_RUNTIME_ACTIVE_ROLE = 10_203


class _ProjectionView(QGraphicsView):
    activated = Signal(str)
    expandRequested = Signal(str)

    def __init__(self, scene: QGraphicsScene) -> None:
        super().__init__(scene)
        self.setObjectName("semanticProjectionView")
        self.setAccessibleName("Semantic code projection")
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._zoom = 1.0

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y() or event.pixelDelta().y()
            factor = 1.15 if delta > 0 else 1 / 1.15
            proposed = self._zoom * factor
            if 0.08 <= proposed <= 8.0:
                self.scale(factor, factor)
                self._zoom = proposed
            event.accept()
            return
        pixel = event.pixelDelta()
        angle = event.angleDelta()
        dx = pixel.x() or angle.x() / 2
        dy = pixel.y() or angle.y() / 2
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - round(dx))
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() - round(dy))
        event.accept()

    def mouseDoubleClickEvent(self, event: object) -> None:
        # PySide's concrete event type is deliberately not imported just for this hook.
        position = getattr(event, "position", lambda: QPointF())().toPoint()
        item = self.itemAt(position)
        while item is not None:
            node_id = item.data(_NODE_ID_ROLE)
            if isinstance(node_id, str):
                self.expandRequested.emit(node_id)
            semantic_id = item.data(_SEMANTIC_ID_ROLE)
            if isinstance(semantic_id, str):
                self.activated.emit(semantic_id)
                break
            item = item.parentItem()
        super().mouseDoubleClickEvent(event)  # type: ignore[arg-type]

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            selected = self.scene().selectedItems()
            semantic_id = selected[0].data(_SEMANTIC_ID_ROLE) if selected else None
            if isinstance(semantic_id, str):
                self.activated.emit(semantic_id)
                event.accept()
                return
        super().keyPressEvent(event)

    def fit_projection(self) -> None:
        bounds = self.scene().itemsBoundingRect()
        if not bounds.isEmpty():
            self.fitInView(bounds.adjusted(-32, -32, 32, 32), Qt.AspectRatioMode.KeepAspectRatio)
            self._zoom = self.transform().m11()


class SemanticVisualizerWidget(QWidget):
    """A first-class code visualizer using no document-specific dataclasses."""

    revealRequested = Signal(str)
    documentCreated = Signal(str)
    selectionArrived = Signal(object)
    kernelEventArrived = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("semanticVisualizer")
        self.setAccessibleName("Code visualizer")
        self._kernel: ProjectKernel | None = None
        self._client: CodeVisualizerClient | None = None
        self._selection_unsubscribe: Callable[[], None] | None = None
        self._kernel_unsubscribe: Callable[[], None] | None = None
        self._runtime_observer = QtRuntimeObserver(self)
        self._projection: SemanticProjection | None = None
        self._runtime_history_index: int | None = None
        self._refreshing_runtime_controls = False
        self._expanded_ids: set[str] = set()
        self._node_limit_overrides: dict[str, int] = {}
        self._items_by_semantic_id: dict[str, list[QGraphicsItem]] = defaultdict(list)
        self._publishing = False

        self.projection_choice = QComboBox()
        self.projection_choice.setObjectName("semanticProjectionKind")
        self.projection_choice.currentIndexChanged.connect(self.refresh)
        self._refresh_projection_choices()
        self.root_choice = QComboBox()
        self.root_choice.setObjectName("semanticProjectionRoot")
        self.root_choice.setAccessibleName("Projection root function")
        self.root_choice.currentIndexChanged.connect(self.refresh)
        self.fit_button = QPushButton("Fit")
        self.fit_button.setObjectName("fitSemanticProjection")
        self.fit_button.clicked.connect(self._fit)
        self.new_lens_button = QPushButton("New Lens...")
        self.new_lens_button.setObjectName("newSemanticLens")
        self.new_lens_button.clicked.connect(self._new_lens)
        self.edit_lens_button = QPushButton("Edit Lens...")
        self.edit_lens_button.setObjectName("editSemanticLens")
        self.edit_lens_button.clicked.connect(self._edit_lens)
        self.delete_lens_button = QPushButton("Delete Lens")
        self.delete_lens_button.setObjectName("deleteSemanticLens")
        self.delete_lens_button.clicked.connect(self._delete_lens)
        self.concept_button = QPushButton("Group as Concept...")
        self.concept_button.setObjectName("createSemanticConcept")
        self.concept_button.clicked.connect(self._create_concept)
        self.relate_button = QPushButton("Relate Selection...")
        self.relate_button.setObjectName("createSemanticRelationship")
        self.relate_button.clicked.connect(self._create_relationship)
        self.mind_map_button = QPushButton("Make Mind Map")
        self.mind_map_button.setObjectName("materializeMindMapProjection")
        self.mind_map_button.setToolTip(
            "Create an editable mind map whose topics remain linked to this semantic lens."
        )
        self.mind_map_button.clicked.connect(
            lambda: self._materialize_projection(ProjectionViewTarget.MIND_MAP)
        )
        self.canvas_button = QPushButton("Make Canvas")
        self.canvas_button.setObjectName("materializeFreeformProjection")
        self.canvas_button.setToolTip(
            "Create an editable canvas whose shapes and arrows retain semantic anchors."
        )
        self.canvas_button.clicked.connect(
            lambda: self._materialize_projection(ProjectionViewTarget.FREEFORM)
        )
        self.help_label = QLabel(
            "Drag to pan | wheel to scroll | Ctrl+wheel to zoom | Enter to open"
        )
        self.help_label.setObjectName("semanticProjectionHelp")

        self.runtime_controls = QWidget()
        self.runtime_controls.setObjectName("runtimeProjectionControls")
        runtime_layout = QHBoxLayout(self.runtime_controls)
        runtime_layout.setContentsMargins(0, 0, 0, 0)
        self.runtime_adapter_choice = QComboBox()
        self.runtime_adapter_choice.setObjectName("runtimeAdapterKind")
        for adapter in RuntimeAdapterKind:
            self.runtime_adapter_choice.addItem(
                adapter.value.replace("_", " ").title(), adapter.value
            )
        self.runtime_adapter_choice.currentIndexChanged.connect(self.refresh)
        self.runtime_binding_choice = QComboBox()
        self.runtime_binding_choice.setObjectName("runtimeBindingFocus")
        self.runtime_binding_choice.currentIndexChanged.connect(self.refresh)
        self.runtime_previous_button = QPushButton("Previous")
        self.runtime_previous_button.setObjectName("runtimeHistoryPrevious")
        self.runtime_previous_button.clicked.connect(self._runtime_previous)
        self.runtime_history_slider = QSlider(Qt.Orientation.Horizontal)
        self.runtime_history_slider.setObjectName("runtimeHistoryTimeline")
        self.runtime_history_slider.setAccessibleName("Execution history timeline")
        self.runtime_history_slider.valueChanged.connect(self._runtime_history_changed)
        self.runtime_history_label = QLabel("No execution history")
        self.runtime_history_label.setObjectName("runtimeHistoryPosition")
        self.runtime_next_button = QPushButton("Next")
        self.runtime_next_button.setObjectName("runtimeHistoryNext")
        self.runtime_next_button.clicked.connect(self._runtime_next)
        self.runtime_live_button = QPushButton("Live")
        self.runtime_live_button.setObjectName("runtimeHistoryLive")
        self.runtime_live_button.clicked.connect(self._runtime_live)
        runtime_layout.addWidget(QLabel("Inspect as:"))
        runtime_layout.addWidget(self.runtime_adapter_choice)
        runtime_layout.addWidget(QLabel("Focus:"))
        runtime_layout.addWidget(self.runtime_binding_choice)
        runtime_layout.addWidget(self.runtime_previous_button)
        runtime_layout.addWidget(self.runtime_history_slider, 1)
        runtime_layout.addWidget(self.runtime_history_label)
        runtime_layout.addWidget(self.runtime_next_button)
        runtime_layout.addWidget(self.runtime_live_button)
        self.runtime_controls.hide()

        controls = QHBoxLayout()
        controls.addWidget(QLabel("View:"))
        controls.addWidget(self.projection_choice)
        controls.addWidget(QLabel("Root:"))
        controls.addWidget(self.root_choice, 1)
        controls.addWidget(self.fit_button)

        authoring_controls = QHBoxLayout()
        authoring_controls.addWidget(self.new_lens_button)
        authoring_controls.addWidget(self.edit_lens_button)
        authoring_controls.addWidget(self.delete_lens_button)
        authoring_controls.addStretch(1)
        authoring_controls.addWidget(self.concept_button)
        authoring_controls.addWidget(self.relate_button)
        authoring_controls.addWidget(self.mind_map_button)
        authoring_controls.addWidget(self.canvas_button)

        self.scene = QGraphicsScene(self)
        self.scene.selectionChanged.connect(self._scene_selection_changed)
        self._scene_reconciler = SceneReconciler(
            self.scene,
            node_color=self._node_color,
            bounded_text=self._bounded_text,
        )
        self.view = _ProjectionView(self.scene)
        self.view.activated.connect(self.revealRequested)
        self.view.expandRequested.connect(self._toggle_expansion)
        self.semantic_text = SemanticTextWidget()
        self.projection_tabs = QTabWidget()
        self.projection_tabs.setObjectName("semanticProjectionModes")
        self.projection_tabs.addTab(self.view, "Graph")
        self.projection_tabs.addTab(self.semantic_text, "Semantic Text")
        self.status = QLabel("Open a project to visualize its semantic program.")
        self.status.setObjectName("semanticProjectionStatus")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addLayout(controls)
        layout.addLayout(authoring_controls)
        layout.addWidget(self.runtime_controls)
        layout.addWidget(self.help_label)
        layout.addWidget(self.projection_tabs, 1)
        layout.addWidget(self.status)

        self.selectionArrived.connect(self._apply_selection)
        self.kernelEventArrived.connect(self._kernel_changed)
        self._runtime_observer.runtimeChanged.connect(self._runtime_changed)

    def attach(
        self,
        kernel: ProjectKernel | None,
        client: CodeVisualizerClient | None = None,
    ) -> None:
        if self._selection_unsubscribe is not None:
            self._selection_unsubscribe()
            self._selection_unsubscribe = None
        if self._kernel_unsubscribe is not None:
            self._kernel_unsubscribe()
            self._kernel_unsubscribe = None
        self._runtime_observer.attach(None)
        self._kernel = kernel
        self._client = client
        self._runtime_history_index = None
        self.semantic_text.attach(kernel, client)
        if kernel is None:
            self.runtime_controls.hide()
            self._projection = None
            self._items_by_semantic_id.clear()
            self._scene_reconciler.clear()
            self.root_choice.clear()
            self.status.setText("Open a project to visualize its semantic program.")
            self._refresh_projection_choices()
            self._update_authoring_actions()
            return
        self._selection_unsubscribe = kernel.selection.subscribe(self.selectionArrived.emit)
        self._kernel_unsubscribe = kernel.subscribe(self.kernelEventArrived.emit)
        self._runtime_observer.attach(kernel)
        self._refresh_projection_choices()
        self._refresh_roots()
        self.refresh()

    def refresh(self, _index: int = -1) -> None:
        kernel = self._kernel
        if kernel is None:
            return
        self._refresh_roots()
        raw_kind = self.projection_choice.currentData()
        root = self.root_choice.currentData()
        raw_choice = str(raw_kind)
        runtime_state = self._runtime_state(kernel)
        self.runtime_controls.show()
        self._refresh_runtime_controls(kernel, runtime_state)
        runtime_context = self._runtime_context(kernel, runtime_state)
        if raw_choice.startswith("saved:"):
            definition_id = raw_choice.removeprefix("saved:")
            definition = kernel.queries.projection_definition(definition_id)
            if definition is None:
                self._select_projection(ProjectionKind.ARCHITECTURE.value)
                return
            self.root_choice.setEnabled(False)
            self._projection = kernel.compose_projection(
                self._with_expansion(definition),
                runtime_context=runtime_context,
            )
            self._render(self._projection)
            self._apply_selection(kernel.selection.state)
            self._update_authoring_actions()
            return
        try:
            kind = ProjectionKind(raw_choice)
        except ValueError:
            kind = ProjectionKind.ARCHITECTURE
        root_id = root if isinstance(root, str) and root else None
        self.root_choice.setEnabled(kind in {ProjectionKind.CONTROL, ProjectionKind.DATA})
        if kind in {
            ProjectionKind.ARCHITECTURE,
            ProjectionKind.CALLS,
            ProjectionKind.RUNTIME,
        }:
            root_id = None
        if kind in {
            ProjectionKind.ARCHITECTURE,
            ProjectionKind.CALLS,
            ProjectionKind.CONTROL,
            ProjectionKind.DATA,
            ProjectionKind.CONCEPTS,
        }:
            definition = builtin_projection_definition(kind, kernel.queries.program, root_id)
            self._projection = kernel.compose_projection(
                self._with_expansion(definition),
                kind=kind,
                runtime_context=runtime_context,
            )
        else:
            self._projection = kernel.project_projection(
                kind,
                root_id,
                runtime_context=runtime_context,
            )
        self._render(self._projection)
        if kind is ProjectionKind.RUNTIME:
            if runtime_state is None:
                self.status.setText("No execution session yet. Start Debug in a DRAKON document.")
            elif runtime_state.project_revision != kernel.revision:
                self.status.setText(
                    f"Runtime session {runtime_state.execution_session_id} is pinned to revision "
                    f"{runtime_state.project_revision}; the project is now revision "
                    f"{kernel.revision}."
                )
            elif self._runtime_history_index is not None:
                self.status.setText(
                    f"Historical runtime event {runtime_state.event_sequence} | "
                    f"project revision {runtime_state.project_revision}"
                )
        self._apply_selection(kernel.selection.state)
        self._update_authoring_actions()

    def _refresh_projection_choices(self) -> None:
        current = self.projection_choice.currentData()
        entries = [
            ("Architecture", ProjectionKind.ARCHITECTURE.value),
            ("Calls", ProjectionKind.CALLS.value),
            ("Control flow", ProjectionKind.CONTROL.value),
            ("Data flow", ProjectionKind.DATA.value),
            ("Concepts", ProjectionKind.CONCEPTS.value),
            ("Runtime values", ProjectionKind.RUNTIME.value),
        ]
        if self._kernel is not None:
            entries.extend(
                (f"My Lens | {item.title}", f"saved:{item.id}")
                for item in self._kernel.queries.projection_definitions()
            )
        existing = [
            (self.projection_choice.itemText(index), self.projection_choice.itemData(index))
            for index in range(self.projection_choice.count())
        ]
        if existing == entries:
            return
        self.projection_choice.blockSignals(True)
        self.projection_choice.clear()
        for label, value in entries:
            self.projection_choice.addItem(label, value)
        restored = self.projection_choice.findData(current)
        self.projection_choice.setCurrentIndex(max(0, restored))
        self.projection_choice.blockSignals(False)

    def _select_projection(self, value: str) -> None:
        index = self.projection_choice.findData(value)
        if index >= 0:
            self.projection_choice.setCurrentIndex(index)

    def select_projection(self, kind: ProjectionKind) -> None:
        self._select_projection(kind.value)

    def compose_lens(self) -> None:
        self._new_lens()

    def group_selection_as_concept(self) -> None:
        self._create_concept()

    def relate_selection(self) -> None:
        self._create_relationship()

    def make_mind_map(self) -> None:
        self._materialize_projection(ProjectionViewTarget.MIND_MAP)

    def make_canvas(self) -> None:
        self._materialize_projection(ProjectionViewTarget.FREEFORM)

    def _refresh_roots(self) -> None:
        kernel = self._kernel
        if kernel is None:
            return
        existing = self.root_choice.currentData()
        functions = tuple(
            item
            for item in kernel.queries.program.objects
            if item.kind is SemanticObjectKind.FUNCTION
        )
        labels = tuple((item.detail or item.label, item.id) for item in functions)
        current = tuple(
            (self.root_choice.itemText(index), self.root_choice.itemData(index))
            for index in range(self.root_choice.count())
        )
        if current == labels:
            return
        self.root_choice.blockSignals(True)
        self.root_choice.clear()
        for label, object_id in labels:
            self.root_choice.addItem(label, object_id)
        restored = self.root_choice.findData(existing)
        if restored >= 0:
            self.root_choice.setCurrentIndex(restored)
        self.root_choice.blockSignals(False)

    def _render(self, projection: SemanticProjection) -> None:
        self.scene.blockSignals(True)
        positions = self._positions(projection)
        self._scene_reconciler.reconcile(projection, positions)
        self._items_by_semantic_id = defaultdict(
            list,
            self._scene_reconciler.items_by_semantic_id(),
        )
        self.scene.blockSignals(False)
        self.status.setText(
            f"Revision {projection.revision} | {len(projection.nodes)} semantic objects | "
            f"{len(projection.edges)} relationships"
        )
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-40, -40, 40, 40))
        self.semantic_text.set_projection(projection)

    def _positions(self, projection: SemanticProjection) -> dict[str, tuple[float, float]]:
        return projection_positions(projection)

    @staticmethod
    def _bounded_text(value: str, maximum: int) -> str:
        normalized = " ".join(value.split())
        if len(normalized) <= maximum:
            return normalized
        return normalized[: maximum - 1].rstrip() + "…"

    @staticmethod
    def _node_color(kind: SemanticObjectKind) -> QColor:
        return {
            SemanticObjectKind.PROJECT: QColor("#d8e3ef"),
            SemanticObjectKind.NAMESPACE: QColor("#e5e7eb"),
            SemanticObjectKind.MODULE: QColor("#dde7d8"),
            SemanticObjectKind.CLASS: QColor("#e8dfcf"),
            SemanticObjectKind.FUNCTION: QColor("#d9e5f2"),
            SemanticObjectKind.OPERATION: QColor("#e8edf2"),
            SemanticObjectKind.EXPRESSION: QColor("#eee5d4"),
            SemanticObjectKind.SYMBOL: QColor("#dce9df"),
            SemanticObjectKind.CONCEPT: QColor("#eadff0"),
            SemanticObjectKind.GROUP: QColor("#e2e8f0"),
        }.get(kind, QColor("#e7e9ec"))

    def _scene_selection_changed(self) -> None:
        if self._publishing or self._kernel is None:
            return
        identifiers = tuple(
            dict.fromkeys(
                semantic_id
                for item in self.scene.selectedItems()
                if isinstance((semantic_id := item.data(_SEMANTIC_ID_ROLE)), str)
            )
        )
        self._kernel.selection.select(
            identifiers,
            revision=self._kernel.revision,
            source="ui.semantic_visualizer",
        )
        self._update_authoring_actions()

    def _apply_selection(self, raw_state: object) -> None:
        if not isinstance(raw_state, SelectionState):
            return
        selected = frozenset(raw_state.semantic_ids)
        self._publishing = True
        try:
            for semantic_id, items in self._items_by_semantic_id.items():
                for item in items:
                    item.setSelected(semantic_id in selected)
                    if isinstance(item, (QGraphicsRectItem, QGraphicsPathItem)):
                        active = bool(item.data(_RUNTIME_ACTIVE_ROLE))
                        item.setPen(
                            QPen(
                                QColor("#2b6cb0")
                                if semantic_id in selected
                                else (QColor("#b45309") if active else QColor("#64748b")),
                                2.8 if semantic_id in selected or active else 1.4,
                            )
                        )
        finally:
            self._publishing = False
        self.semantic_text.apply_selection(raw_state)

    def _kernel_changed(self, raw_event: object) -> None:
        if isinstance(raw_event, KernelEvent):
            self._refresh_projection_choices()
            self.refresh()

    def _runtime_changed(self, _raw_state: object) -> None:
        self.refresh()

    def _runtime_state(self, kernel: ProjectKernel) -> RuntimeSessionState | None:
        history = kernel.runtime.history()
        if not history:
            return kernel.runtime.active
        if self._runtime_history_index is None:
            return history[-1]
        self._runtime_history_index = min(
            max(0, self._runtime_history_index),
            len(history) - 1,
        )
        return history[self._runtime_history_index]

    def _runtime_context(
        self,
        kernel: ProjectKernel,
        state: RuntimeSessionState | None,
    ) -> RuntimeOverlayContext:
        history = kernel.runtime.history()
        if self._runtime_history_index is None:
            index = len(history) - 1
        else:
            index = min(max(0, self._runtime_history_index), len(history) - 1)
        previous = history[index - 1] if index > 0 else None
        raw_adapter = str(self.runtime_adapter_choice.currentData())
        try:
            adapter = RuntimeAdapterKind(raw_adapter)
        except ValueError:
            adapter = RuntimeAdapterKind.AUTO
        raw_binding = self.runtime_binding_choice.currentData()
        binding_name = raw_binding if isinstance(raw_binding, str) and raw_binding else None
        return RuntimeOverlayContext(
            state,
            previous,
            adapter,
            binding_name,
            include_values=True,
        )

    def _refresh_runtime_controls(
        self,
        kernel: ProjectKernel,
        state: RuntimeSessionState | None,
    ) -> None:
        history = kernel.runtime.history()
        self._refreshing_runtime_controls = True
        try:
            existing_binding = self.runtime_binding_choice.currentData()
            binding_entries: list[tuple[str, str | None]] = [("All bindings", None)]
            if state is not None and state.graph is not None:
                binding_entries.extend(
                    (binding.name, binding.name) for binding in state.graph.bindings
                )
            current_entries = [
                (
                    self.runtime_binding_choice.itemText(index),
                    self.runtime_binding_choice.itemData(index),
                )
                for index in range(self.runtime_binding_choice.count())
            ]
            if current_entries != binding_entries:
                self.runtime_binding_choice.blockSignals(True)
                self.runtime_binding_choice.clear()
                for label, value in binding_entries:
                    self.runtime_binding_choice.addItem(label, value)
                restored = self.runtime_binding_choice.findData(existing_binding)
                self.runtime_binding_choice.setCurrentIndex(max(0, restored))
                self.runtime_binding_choice.blockSignals(False)

            available = bool(history)
            effective_index = (
                len(history) - 1
                if self._runtime_history_index is None and history
                else min(self._runtime_history_index or 0, max(0, len(history) - 1))
            )
            self.runtime_history_slider.blockSignals(True)
            self.runtime_history_slider.setRange(0, max(0, len(history) - 1))
            self.runtime_history_slider.setValue(effective_index)
            self.runtime_history_slider.blockSignals(False)
            self.runtime_history_slider.setEnabled(available)
            self.runtime_previous_button.setEnabled(available and effective_index > 0)
            self.runtime_next_button.setEnabled(
                available and self._runtime_history_index is not None
            )
            self.runtime_live_button.setEnabled(
                available and self._runtime_history_index is not None
            )
            if state is None:
                self.runtime_history_label.setText("No execution history")
            else:
                mode = "Live" if self._runtime_history_index is None else "History"
                self.runtime_history_label.setText(
                    f"{mode} {effective_index + 1}/{len(history)} | event {state.event_sequence}"
                )
        finally:
            self._refreshing_runtime_controls = False

    def _runtime_history_changed(self, index: int) -> None:
        if self._refreshing_runtime_controls:
            return
        self._runtime_history_index = index
        self.refresh()

    def _runtime_previous(self) -> None:
        if self._kernel is None:
            return
        history = self._kernel.runtime.history()
        if not history:
            return
        if self._runtime_history_index is None:
            self._runtime_history_index = max(0, len(history) - 2)
        else:
            self._runtime_history_index = max(0, self._runtime_history_index - 1)
        self.refresh()

    def _runtime_next(self) -> None:
        if self._kernel is None or self._runtime_history_index is None:
            return
        history = self._kernel.runtime.history()
        if self._runtime_history_index >= len(history) - 1:
            self._runtime_history_index = None
        else:
            self._runtime_history_index += 1
        self.refresh()

    def _runtime_live(self) -> None:
        self._runtime_history_index = None
        self.refresh()

    def _fit(self) -> None:
        self.view.fit_projection()

    def _with_expansion(self, definition: ProjectionDefinition) -> ProjectionDefinition:
        expanded = tuple(dict.fromkeys((*definition.expanded_ids, *sorted(self._expanded_ids))))
        return replace(
            definition,
            expanded_ids=expanded,
            node_limit=self._node_limit_overrides.get(definition.id, definition.node_limit),
        )

    def _toggle_expansion(self, node_id: str) -> None:
        projection = self._projection
        node = (
            next((item for item in projection.nodes if item.id == node_id), None)
            if projection is not None
            else None
        )
        if node is None or not node.expandable:
            return
        if node_id.startswith("projection-summary:"):
            definition = self._current_projection_definition()
            if definition is None:
                return
            self._node_limit_overrides[definition.id] = min(
                1000,
                self._node_limit_overrides.get(definition.id, definition.node_limit) + 50,
            )
        elif node_id in self._expanded_ids:
            self._expanded_ids.remove(node_id)
        else:
            self._expanded_ids.add(node_id)
        self.refresh()

    def _update_authoring_actions(self) -> None:
        client_ready = self._kernel is not None and self._client is not None
        selected_objects = self._selected_semantic_objects()
        saved = str(self.projection_choice.currentData()).startswith("saved:")
        materializable = (
            client_ready
            and self._current_projection_definition() is not None
            and self._projection is not None
            and bool(self._projection.nodes)
        )
        self.new_lens_button.setEnabled(client_ready)
        self.edit_lens_button.setEnabled(client_ready and saved)
        self.delete_lens_button.setEnabled(client_ready and saved)
        self.concept_button.setEnabled(client_ready and bool(selected_objects))
        self.relate_button.setEnabled(client_ready and len(selected_objects) == 2)
        self.mind_map_button.setEnabled(materializable)
        self.canvas_button.setEnabled(materializable)

    def _current_projection_definition(self) -> ProjectionDefinition | None:
        if self._kernel is None:
            return None
        raw = str(self.projection_choice.currentData())
        if raw.startswith("saved:"):
            definition = self._kernel.queries.projection_definition(raw.removeprefix("saved:"))
            return None if definition is None else self._with_expansion(definition)
        try:
            kind = ProjectionKind(raw)
        except ValueError:
            return None
        if kind not in {
            ProjectionKind.ARCHITECTURE,
            ProjectionKind.CALLS,
            ProjectionKind.CONTROL,
            ProjectionKind.DATA,
            ProjectionKind.CONCEPTS,
        }:
            return None
        raw_root = self.root_choice.currentData()
        root = raw_root if isinstance(raw_root, str) and raw_root else None
        return self._with_expansion(
            builtin_projection_definition(kind, self._kernel.queries.program, root)
        )

    def _materialize_projection(self, target: ProjectionViewTarget) -> None:
        if self._client is None:
            return
        definition = self._current_projection_definition()
        if definition is None:
            return
        document_id = new_id("diagram")
        target_label = "Mind Map" if target is ProjectionViewTarget.MIND_MAP else "Canvas"
        result = self._client.materialize_projection(
            definition,
            target,
            f"{definition.title} - {target_label}",
            document_id=document_id,
        )
        if isinstance(result, CommandAccepted):
            self.status.setText(f"Created editable {target_label.lower()} from {definition.title}.")
            self.documentCreated.emit(document_id)
        else:
            self._show_command_failure(result)

    def _selected_semantic_objects(self) -> tuple[str, ...]:
        if self._kernel is None:
            return ()
        return tuple(
            semantic_id
            for semantic_id in self._kernel.selection.state.semantic_ids
            if self._kernel.queries.semantic_object(semantic_id) is not None
        )

    def _new_lens(self) -> None:
        self._edit_projection(None)

    def _edit_lens(self) -> None:
        if self._kernel is None:
            return
        raw = str(self.projection_choice.currentData())
        if not raw.startswith("saved:"):
            return
        self._edit_projection(
            self._kernel.queries.projection_definition(raw.removeprefix("saved:"))
        )

    def _edit_projection(self, existing: ProjectionDefinition | None) -> None:
        if self._kernel is None or self._client is None:
            return
        dialog = ProjectionComposerDialog(self._kernel.queries.program.objects, existing, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        definition = dialog.definition()
        result = self._client.put_projection_definition(definition)
        if isinstance(result, CommandAccepted):
            self._refresh_projection_choices()
            self._select_projection(f"saved:{definition.id}")
        else:
            self._show_command_failure(result)

    def _delete_lens(self) -> None:
        if self._client is None:
            return
        raw = str(self.projection_choice.currentData())
        if not raw.startswith("saved:"):
            return
        if (
            QMessageBox.question(
                self,
                "Delete semantic lens?",
                "Delete this presentation definition? The program is not changed.",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        result = self._client.delete_projection_definition(raw.removeprefix("saved:"))
        if isinstance(result, CommandAccepted):
            self._refresh_projection_choices()
            self._select_projection(ProjectionKind.ARCHITECTURE.value)
        else:
            self._show_command_failure(result)

    def _create_concept(self) -> None:
        if self._kernel is None or self._client is None:
            return
        members = self._selected_semantic_objects()
        if not members:
            return
        member_labels = tuple(
            value.label
            for member_id in members
            if (value := self._kernel.queries.semantic_object(member_id)) is not None
        )
        dialog = SemanticConceptDialog(member_labels, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        concept_id = new_id("concept")
        result = self._client.create_semantic_concept(
            dialog.concept_title,
            members,
            description=dialog.concept_description,
            tags=dialog.concept_tags,
            concept_id=concept_id,
        )
        if isinstance(result, CommandAccepted):
            self._select_projection(ProjectionKind.CONCEPTS.value)
            self._kernel.selection.select(
                (concept_id,),
                revision=result.revision,
                source="ui.semantic_visualizer",
            )
        else:
            self._show_command_failure(result)

    def _create_relationship(self) -> None:
        if self._kernel is None or self._client is None:
            return
        selected = self._selected_semantic_objects()
        if len(selected) != 2:
            return
        source = self._kernel.queries.semantic_object(selected[0])
        target = self._kernel.queries.semantic_object(selected[1])
        if source is None or target is None:
            return
        dialog = AuthoredRelationDialog(source.label, target.label, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if dialog.direction_reversed:
            source, target = target, source
        relation_id = new_id("semantic-relation")
        result = self._client.create_authored_semantic_relation(
            source.id,
            target.id,
            kind=dialog.relation_kind,
            label=dialog.relation_label,
            description=dialog.relation_description,
            relation_id=relation_id,
        )
        if isinstance(result, CommandAccepted):
            self._select_projection(ProjectionKind.CONCEPTS.value)
            self._kernel.selection.select(
                (relation_id,),
                revision=result.revision,
                source="ui.semantic_visualizer",
            )
        else:
            self._show_command_failure(result)

    def _show_command_failure(self, result: object) -> None:
        if isinstance(result, CommandRejected):
            self.status.setText(f"{result.code}: {result.message}")
        else:
            self.status.setText("The semantic command did not complete.")
