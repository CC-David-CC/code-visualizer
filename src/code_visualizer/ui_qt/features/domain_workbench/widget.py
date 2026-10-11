"""Generic editable notations over the authority's intentional domain workspace."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from time import perf_counter
from typing import cast

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGraphicsScene,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from code_visualizer.application.commands import TypedCommand
from code_visualizer.application.computation_service import ComputationAttempt
from code_visualizer.application.domain_commands import (
    CreateDomainNode,
    DeleteDomainModel,
    DeleteDomainNode,
    DeleteDomainSchema,
    MoveDomainChild,
    PutDomainModel,
    PutDomainSchema,
    SetDomainProperty,
    SetDomainReference,
)
from code_visualizer.application.domain_installation import bundle_installation, schema_installation
from code_visualizer.application.editor_preparation import EditorPreparedSnapshot
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.messages import CommandAccepted, CommandRejected, CommandResult
from code_visualizer.application.notations import (
    NotationCell,
    NotationEditKind,
    NotationProjection,
    NotationTreeNode,
    fallback_notations,
    field_cell,
    notation_edit_command,
    notation_node_label,
)
from code_visualizer.application.projection_layout import projection_positions
from code_visualizer.application.selection import SelectionState
from code_visualizer.application.trace_presentation import (
    MappedTrace,
    SourceSpanPolicy,
    TraceOutputPage,
    map_trace,
    output_page_text,
)
from code_visualizer.domain.common import new_id
from code_visualizer.domain.computation import (
    BackendDefinition,
    CancelRequest,
    ComputationRequest,
    ComputationStatus,
)
from code_visualizer.domain.evidence import ComputationEvidence
from code_visualizer.domain.intentional import (
    DomainModel,
    DomainSchema,
    RoleBinding,
    node_label,
)
from code_visualizer.domain.language import AuthoredTransformation, ValidatorDefinition
from code_visualizer.domain.language_structure import language_records
from code_visualizer.domain.notation import NotationDefinition, NotationField, NotationKind
from code_visualizer.domain.resources import DataResource
from code_visualizer.domain.values import UnitReference
from code_visualizer.execution import RunSession, TraceResult
from code_visualizer.generation.emitter import GeneratedFile, GeneratedProject
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.ui_qt.editor_preparation import EditorAction, QtEditorPreparation
from code_visualizer.ui_qt.features.domain_workbench.composed_canvas import ComposedCanvasWidget
from code_visualizer.ui_qt.features.domain_workbench.editors import (
    RICH_VALUE_KINDS,
    NodeDialog,
    ReferenceEditor,
    ScalarEditor,
    SchemaDialog,
    ValueDialog,
    parse_scalar,
)
from code_visualizer.ui_qt.features.domain_workbench.graph import NotationGraphView
from code_visualizer.ui_qt.features.domain_workbench.language_editors import (
    LanguageEditorDialog,
    language_kind_label,
)
from code_visualizer.ui_qt.features.domain_workbench.value_editors import value_summary
from code_visualizer.ui_qt.features.semantic_visualizer.scene_reconciler import (
    SEMANTIC_ID_ROLE,
    SceneReconciler,
)
from code_visualizer.ui_qt.font_support import register_application_fonts
from code_visualizer.ui_qt.runtime_observer import QtRuntimeObserver


class DomainWorkbenchWidget(QWidget):
    """Schema-driven authoring; no bundle-specific concepts or gesture branches."""

    selectionArrived = Signal(object)
    revisionArrived = Signal(object)
    revealRequested = Signal(str)
    traceCompleted = Signal(object)
    freezeRequested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("domainWorkbench")
        self.setAccessibleName("Domain workbench")
        self._kernel: ProjectKernel | None = None
        self._client: CodeVisualizerClient | None = None
        self._unsubscribers: list[Callable[[], None]] = []
        self._refreshing = False
        self._selection_guard = False
        self._selected_id: str | None = None
        self._form_revision = 0
        self._evidence: dict[str, ComputationEvidence] = {}
        self._evidence_attachments: dict[str, set[str]] = {}
        self._backend_definitions: tuple[BackendDefinition, ...] = ()
        self._attempts: tuple[ComputationAttempt, ...] = ()
        self._active_computation_id: str | None = None
        self._inspecting_evidence = False
        self._runtime_ids: tuple[str, ...] = ()
        self._runtime_observer = QtRuntimeObserver(self)
        self._backend_model_id: str | None = None
        self._properties: dict[str, ScalarEditor] = {}
        self._references: dict[str, ReferenceEditor] = {}
        self._notations: tuple[NotationDefinition, ...] = ()
        self._chosen: dict[NotationKind, str] = {}
        self.projections: dict[NotationKind, NotationProjection] = {}
        self._debug_session: object | None = None
        self._editor_preparation: QtEditorPreparation | None = None
        self._python_run = RunSession()
        self._trace_snapshot: EditorPreparedSnapshot | None = None
        self._retained_trace: MappedTrace | None = None
        self._trace_delivery: MappedTrace | None = None
        self._trace_delivery_index = 0
        self._trace_timer = QTimer(self)
        self._trace_timer.setInterval(16)
        self._trace_timer.timeout.connect(self._deliver_trace_events)
        self.traceCompleted.connect(self._trace_completed)
        self._generated: GeneratedProject | None = None
        self._source_module: GeneratedFile | None = None
        self._generated_revision: int | None = None
        self._source_guard = False
        self._debug_timer = QTimer(self)
        self._debug_timer.setInterval(35)
        self._debug_timer.timeout.connect(self._poll_debug)

        self.schema_choice = QComboBox()
        self.schema_choice.setObjectName("domainSchemaChoice")
        self.schema_choice.setAccessibleName("Domain schema")
        self.model_choice = QComboBox()
        self.model_choice.setObjectName("domainModelChoice")
        self.model_choice.setAccessibleName("Domain model")
        self.notation_choice = QComboBox()
        self.notation_choice.setObjectName("domainNotationChoice")
        self.notation_choice.setAccessibleName("Notation definition")
        self.schema_choice.currentIndexChanged.connect(self.refresh)
        self.model_choice.currentIndexChanged.connect(self.refresh)
        self.notation_choice.currentIndexChanged.connect(self._notation_changed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        schema_bar = QHBoxLayout()
        schema_bar.addWidget(QLabel("Domain"))
        schema_bar.addWidget(self.schema_choice, 1)
        self.new_schema_button = self._button("New domain", "newDomainSchema", self.new_schema)
        schema_bar.addWidget(self.new_schema_button)
        schema_bar.addWidget(
            self._button("Add registered domain", "addRegisteredDomain", self.add_registered_schema)
        )
        schema_bar.addWidget(self._button("Edit schema", "editDomainSchema", self.edit_schema))
        schema_bar.addWidget(
            self._button("Delete domain", "deleteDomainSchema", self.delete_schema)
        )
        layout.addLayout(schema_bar)
        model_bar = QHBoxLayout()
        model_bar.addWidget(QLabel("Model"))
        model_bar.addWidget(self.model_choice, 1)
        model_bar.addWidget(self._button("New model", "newDomainModel", self.new_model))
        model_bar.addWidget(self._button("Delete model", "deleteDomainModel", self.delete_model))
        model_bar.addWidget(
            self._button("Add vocabulary", "addReferenceVocabulary", self.add_reference_vocabulary)
        )
        layout.addLayout(model_bar)
        notation_bar = QHBoxLayout()
        notation_bar.addWidget(QLabel("Notation"))
        notation_bar.addWidget(self.notation_choice, 1)
        notation_bar.addWidget(self._button("Fit view", "fitDomainGraph", self._fit))
        layout.addLayout(notation_bar)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("domainNotationTabs")
        self.tabs.currentChanged.connect(self._tab_changed)
        self.scene = QGraphicsScene(self)
        self.graph_view = NotationGraphView(self.scene)
        self.graph_view.setObjectName("domainGraphView")
        self.graph_view.setAccessibleName("Editable domain graph")
        self.reconciler = SceneReconciler(
            self.scene,
            node_color=lambda _kind: QColor("#e2ecf6"),
            bounded_text=lambda text, maximum: (
                text if len(text) <= maximum else text[: maximum - 1] + "…"
            ),
        )
        self.scene.selectionChanged.connect(self._graph_selection)
        self.graph_view.activated.connect(self.reveal)
        self.graph_view.connectRequested.connect(self.connect_nodes)
        self.table = QTableWidget()
        self.table.setObjectName("domainNotationTable")
        self.table.setAccessibleName("Editable domain table")
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemChanged.connect(self._table_edit)
        self.table.cellDoubleClicked.connect(self._table_open)
        self.table.currentCellChanged.connect(self._table_selection)
        self.tree = QTreeWidget()
        self.tree.setObjectName("domainNotationTree")
        self.tree.setAccessibleName("Domain containment hierarchy")
        self.tree.setHeaderLabels(["Object", "Concept"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tree.currentItemChanged.connect(self._tree_selection)
        self.composed = ComposedCanvasWidget()
        self.composed.selectionRequested.connect(self._composed_selection)
        self.definitions = QTreeWidget()
        self.definitions.setObjectName("domainDefinitions")
        self.definitions.setHeaderLabels(["Definition", "Kind", "Details"])
        self.definitions.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.definitions.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.definitions.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.definitions.itemActivated.connect(self._definition_selection)
        self.diagnostics = QTreeWidget()
        self.diagnostics.setObjectName("domainDiagnostics")
        self.diagnostics.setHeaderLabels(["Issue", "Location"])
        self.diagnostics.itemActivated.connect(self._diagnostic_selection)
        for title, widget in (
            ("Graph", self.graph_view),
            ("Table", self.table),
            ("Hierarchy", self.tree),
            ("Composed", self.composed),
            ("Schema and extensions", self.definitions),
            ("Diagnostics", self.diagnostics),
        ):
            self.tabs.addTab(widget, title)
        self.code = QPlainTextEdit()
        self.code.setObjectName("domainGeneratedCode")
        self.code.setAccessibleName("Generated Python from the domain model")
        self.code.setReadOnly(True)
        self.code.setFont(QFont(register_application_fonts().code, 10))
        self.code.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.code.cursorPositionChanged.connect(self._source_selection)
        self.tabs.addTab(self.code, "Generated Python")
        self.language_panel = QWidget()
        self.language_panel.setObjectName("domainLanguageAuthoring")
        language_layout = QVBoxLayout(self.language_panel)
        language_help = QLabel(
            "Author editable notations, validation rules, and program transformations here. "
            "Definitions are saved with this project and edited through typed forms."
        )
        language_help.setWordWrap(True)
        language_layout.addWidget(language_help)
        self.languages = QTreeWidget()
        self.languages.setObjectName("domainLanguageDefinitions")
        self.languages.setHeaderLabels(["Definition", "Kind", "Version / description"])
        self.languages.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.languages.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.languages.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.languages.itemActivated.connect(lambda _item, _column: self.edit_language())
        self.languages.currentItemChanged.connect(self._language_selection)
        language_layout.addWidget(self.languages, 1)
        language_toolbar = QHBoxLayout()
        for label, name, callback in (
            ("New language", "newDomainLanguage", self.new_language),
            ("Edit definition", "editDomainLanguage", self.edit_language),
            ("Delete language", "deleteDomainLanguage", self.delete_language),
            ("Preview notation", "previewDomainNotation", self.preview_language_notation),
            ("Build model", "buildLanguageModel", self.build_model),
        ):
            language_toolbar.addWidget(self._button(label, name, callback))
        language_layout.addLayout(language_toolbar)
        self.tabs.addTab(self.language_panel, "Language authoring")

        self.evidence_panel = QWidget()
        evidence_layout = QVBoxLayout(self.evidence_panel)
        backend_bar = QHBoxLayout()
        self.backend_choice = QComboBox()
        self.backend_choice.setObjectName("computationBackendChoice")
        self.backend_choice.setAccessibleName("Computation backend")
        backend_bar.addWidget(QLabel("Backend"))
        backend_bar.addWidget(self.backend_choice, 1)
        self.run_computation_button = self._button(
            "Run computation", "runDomainComputation", self.run_computation
        )
        backend_bar.addWidget(self.run_computation_button)
        self.freeze_computation_button = self._button(
            "Freeze & Run", "freezeDomainComputation", self.freeze_computation
        )
        backend_bar.addWidget(self.freeze_computation_button)
        self.cancel_computation_button = self._button(
            "Cancel computation", "cancelDomainComputation", self.cancel_computation
        )
        self.cancel_computation_button.setEnabled(False)
        backend_bar.addWidget(self.cancel_computation_button)
        backend_bar.addWidget(
            self._button("Load evidence", "loadDomainEvidence", self.load_evidence)
        )
        evidence_layout.addLayout(backend_bar)
        self.attempt_view = QTreeWidget()
        self.attempt_view.setObjectName("computationAttempts")
        self.attempt_view.setHeaderLabels(["Computation", "State / source"])
        self.attempt_view.setMaximumHeight(160)
        self.attempt_view.currentItemChanged.connect(self._attempt_selected)
        evidence_layout.addWidget(self.attempt_view)
        self.computation_status = QLabel("No computation submitted.")
        self.computation_status.setObjectName("computationStatus")
        self.computation_status.setWordWrap(True)
        evidence_layout.addWidget(self.computation_status)
        self.computation_preview = QLabel("No provisional observation.")
        self.computation_preview.setObjectName("computationPreview")
        self.computation_preview.setTextFormat(Qt.TextFormat.PlainText)
        self.computation_preview.setWordWrap(True)
        evidence_layout.addWidget(self.computation_preview)
        self.publication_view = QTreeWidget()
        self.publication_view.setObjectName("computationPublications")
        self.publication_view.setHeaderLabels(["Sealed artifact", "Resource / source"])
        self.publication_view.setMaximumHeight(130)
        self.publication_view.itemActivated.connect(self._publication_selected)
        evidence_layout.addWidget(self.publication_view)
        self.evidence_view = QTreeWidget()
        self.evidence_view.setObjectName("computationEvidence")
        self.evidence_view.setHeaderLabels(["Evidence", "Value / provenance"])
        self.evidence_view.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.evidence_view.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.evidence_view.itemActivated.connect(self._evidence_selected)
        evidence_layout.addWidget(self.evidence_view, 1)
        self.evidence_details = QPlainTextEdit()
        self.evidence_details.setObjectName("computationEvidenceDetails")
        self.evidence_details.setReadOnly(True)
        self.evidence_details.setMaximumHeight(160)
        evidence_layout.addWidget(self.evidence_details)
        from code_visualizer.ui_qt.field_history import FieldHistoryPanel

        self.field_history = FieldHistoryPanel(self)
        self.field_history.modelCreated.connect(self.reveal)
        self.field_outputs = QTabWidget()
        evidence_details_panel = QWidget()
        details_layout = QVBoxLayout(evidence_details_panel)
        for details_widget in (self.evidence_view, self.evidence_details):
            evidence_layout.removeWidget(details_widget)
            details_layout.addWidget(details_widget)
        self.field_outputs.addTab(evidence_details_panel, "Evidence")
        self.field_scroll = QScrollArea()
        self.field_scroll.setWidgetResizable(True)
        self.field_scroll.setWidget(self.field_history)
        self.field_outputs.addTab(self.field_scroll, "Field history and trials")
        evidence_layout.addWidget(self.field_outputs, 1)
        self._field_inspect_requested = False
        self.field_history.loaded.connect(self._field_loaded)
        self.field_history.failed.connect(self._field_failed)
        from code_visualizer.ui_qt.channel_history import ChannelHistoryPanel

        self.channel_history = ChannelHistoryPanel(self)
        self.channel_history.modelCreated.connect(self.reveal)
        self.channel_scroll = QScrollArea()
        self.channel_scroll.setWidgetResizable(True)
        self.channel_scroll.setWidget(self.channel_history)
        self.field_outputs.addTab(self.channel_scroll, "Channels, time and trials")
        self._channel_inspect_requested = False
        self.channel_history.loaded.connect(self._channel_loaded)
        self.channel_history.failed.connect(self._channel_failed)
        from code_visualizer.ui_qt.adaptive_history import CellHistoryPanel

        self.cell_history = CellHistoryPanel(self)
        self.cell_history.modelCreated.connect(self.reveal)
        self.cell_scroll = QScrollArea()
        self.cell_scroll.setWidgetResizable(True)
        self.cell_scroll.setWidget(self.cell_history)
        self.field_outputs.addTab(self.cell_scroll, "Cells and support history")
        self._cell_inspect_requested = False
        self.cell_history.loaded.connect(self._cell_loaded)
        self.cell_history.failed.connect(self._cell_failed)
        self.tabs.addTab(self.evidence_panel, "Computation and evidence")
        from code_visualizer.ui_qt.cad_artifacts import CadArtifactPanel

        self.artifact_panel = CadArtifactPanel(self)
        self.artifact_panel.freezeRequested.connect(self.freezeRequested)
        self.artifact_panel.modelCreated.connect(self.reveal)
        self.tabs.addTab(self.artifact_panel, "Artifact inputs and geometry")
        self.trace_panel = QWidget()
        trace_layout = QVBoxLayout(self.trace_panel)
        self.trace_event = QComboBox()
        self.trace_event.setObjectName("domainCapturedTraceEvent")
        self.trace_event.setAccessibleName("Captured domain trace event")
        self.trace_event.currentIndexChanged.connect(self._trace_event_selected)
        trace_layout.addWidget(self.trace_event)
        self.trace_details = QPlainTextEdit()
        self.trace_details.setObjectName("domainCapturedTraceDetails")
        self.trace_details.setReadOnly(True)
        trace_layout.addWidget(self.trace_details)
        self.tabs.addTab(self.trace_panel, "Captured trace")

        self.form = QFormLayout()
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.form_title = QLabel("Select an object to edit its properties and references.")
        self.form_title.setWordWrap(True)
        form_widget = QWidget()
        form_layout = QVBoxLayout(form_widget)
        form_layout.addWidget(self.form_title)
        form_layout.addLayout(self.form)
        self.apply_button = self._button("Apply fields", "applyDomainFields", self.apply_fields)
        form_layout.addWidget(self.apply_button)
        form_layout.addStretch(1)
        form_scroll = QScrollArea()
        form_scroll.setObjectName("domainPropertyForm")
        form_scroll.setMinimumWidth(360)
        form_scroll.setWidgetResizable(True)
        form_scroll.setWidget(form_widget)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.tabs)
        splitter.addWidget(form_scroll)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([820, 420])
        layout.addWidget(splitter, 1)
        object_bar = QHBoxLayout()
        self.add_root_button = self._button(
            "New object", "newDomainNode", lambda: self.create_node(False)
        )
        object_bar.addWidget(self.add_root_button)
        object_bar.addWidget(
            self._button("Add child", "addDomainChild", lambda: self.create_node(True))
        )
        object_bar.addWidget(self._button("Move…", "moveDomainNode", self.move_node))
        object_bar.addWidget(self._button("Up", "moveDomainNodeUp", lambda: self.move_order(-1)))
        object_bar.addWidget(self._button("Down", "moveDomainNodeDown", lambda: self.move_order(1)))
        object_bar.addWidget(self._button("Delete object", "deleteDomainNode", self.delete_node))
        object_bar.addWidget(self._button("Undo", "undoDomainEdit", self.undo))
        object_bar.addWidget(self._button("Redo", "redoDomainEdit", self.redo))
        layout.addLayout(object_bar)
        execution_bar = QHBoxLayout()
        for title, name, callback in (
            ("Build", "buildDomainModel", self.build_model),
            ("Trace", "traceDomainModel", self.trace_model),
            ("Debug", "debugDomainModel", self.debug_model),
            ("Step", "stepDomainModel", self.step_debug),
            ("Continue", "continueDomainModel", self.continue_debug),
            ("Stop", "stopDomainModel", self.stop_debug),
        ):
            execution_bar.addWidget(self._button(title, name, callback))
        layout.addLayout(execution_bar)
        self.status = QLabel("Open a project to define and edit domains.")
        self.status.setObjectName("domainWorkbenchStatus")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.selectionArrived.connect(self._apply_selection)
        self.revisionArrived.connect(self.refresh)
        self._runtime_observer.runtimeChanged.connect(self._runtime_changed)
        self._runtime_observer.attemptsChanged.connect(self._attempts_changed)
        self.apply_button.setEnabled(False)

    def _button(self, title: str, name: str, callback: Callable[[], None]) -> QPushButton:
        button = QPushButton(title)
        button.setObjectName(name)
        button.clicked.connect(callback)
        return button

    def attach(
        self, kernel: ProjectKernel | None, client: CodeVisualizerClient | None = None
    ) -> None:
        self.stop_debug()
        if self._editor_preparation is not None:
            self._editor_preparation.close()
            self._editor_preparation.deleteLater()
            self._editor_preparation = None
        if kernel is not None:
            self._editor_preparation = QtEditorPreparation(
                self,
                profiles=kernel.computations.profiles,
                resource_store=kernel.resource_store,
            )
            self._editor_preparation.changed.connect(self._editor_prepared)
        self._runtime_observer.attach(None)
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        self._kernel, self._client = kernel, client
        self.artifact_panel.attach(kernel, client)
        self.field_history.attach(kernel, client)
        self.channel_history.attach(kernel, client)
        self.cell_history.attach(kernel, client)
        self._cell_inspect_requested = False
        self._channel_inspect_requested = False
        self._field_inspect_requested = False
        self._evidence.clear()
        self._evidence_attachments.clear()
        self._attempts = ()
        self._active_computation_id = None
        self._inspecting_evidence = False
        self._runtime_ids = ()
        self.attempt_view.clear()
        self.publication_view.clear()
        self.computation_preview.setText("No provisional observation.")
        self.cancel_computation_button.setEnabled(False)
        self._backend_model_id = None
        self.composed.attach(kernel, client)
        self._selected_id = None
        self._chosen.clear()
        self._generated = None
        self._source_module = None
        self._generated_revision = None
        self._retained_trace = None
        self.trace_event.clear()
        self.trace_details.clear()
        self.code.clear()
        if kernel is not None:
            self._unsubscribers.extend(
                (
                    kernel.subscribe(self.revisionArrived.emit),
                    kernel.selection.subscribe(self.selectionArrived.emit, replay=False),
                )
            )
        self.refresh()
        self._runtime_observer.attach(kernel)

    @staticmethod
    def _choices(combo: QComboBox, values: tuple[tuple[str, str], ...]) -> None:
        current = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for label, identifier in values:
            combo.addItem(label, identifier)
        index = combo.findData(current)
        combo.setCurrentIndex(index if index >= 0 else (0 if values else -1))
        combo.blockSignals(False)

    def current_schema(self) -> DomainSchema | None:
        if self._kernel is None:
            return None
        return self._kernel.authority.snapshot().domain_workspace.schema(
            str(self.schema_choice.currentData())
        )

    def current_model(self) -> DomainModel | None:
        if self._kernel is None:
            return None
        return self._kernel.authority.snapshot().domain_workspace.model(
            str(self.model_choice.currentData())
        )

    def _definitions_for(self, schema: DomainSchema) -> tuple[NotationDefinition, ...]:
        model = self.current_model()
        if model and self._kernel:
            generic_ids = {item.id for item in fallback_notations(schema)}
            # Offer the domain's authored/registered notations before generic
            # fallbacks; public identifier spelling is not a UI preference.
            return tuple(
                sorted(
                    self._kernel.notations(model.id),
                    key=lambda item: (item.id in generic_ids, item.id),
                )
            )
        registered = self._kernel.extensions.notations_for(schema.id) if self._kernel else ()
        workspace = self._kernel.authority.snapshot().domain_workspace if self._kernel else None
        authored = (
            tuple(
                notation
                for language in workspace.language_definitions
                if language.schema_id == schema.id
                for notation in language.notations
            )
            if workspace
            else ()
        )
        return (*registered, *authored, *fallback_notations(schema))

    def refresh(self, _event: object = None) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        try:
            kernel = self._kernel
            workspace = kernel.authority.snapshot().domain_workspace if kernel else None
            previous_schema = self.schema_choice.currentData()
            self._choices(
                self.schema_choice,
                tuple((item.namespace, item.id) for item in workspace.schemas) if workspace else (),
            )
            if previous_schema is None and workspace and kernel:
                reference_ids = {item.id for item in kernel.extensions.reference_models()}
                preferred = next(
                    (item for item in workspace.models if item.id not in reference_ids), None
                )
                if preferred is not None:
                    self.schema_choice.setCurrentIndex(
                        self.schema_choice.findData(preferred.schema_id)
                    )
            schema = self.current_schema()
            self._choices(
                self.model_choice,
                tuple(
                    (item.title or item.id, item.id)
                    for item in workspace.models
                    if schema is not None and item.schema_id == schema.id
                )
                if workspace
                else (),
            )
            model = self.current_model()
            self._notations = self._definitions_for(schema) if schema else ()
            self._choices(
                self.notation_choice,
                tuple((f"{item.kind.value}: {item.title}", item.id) for item in self._notations),
            )
            self.projections.clear()
            notation_errors: list[tuple[str, str]] = []
            if kernel and schema and model:
                runtime = kernel.runtime.active
                active_ids = kernel.current_runtime_ids()
                self._runtime_ids = active_ids
                for kind in NotationKind:
                    candidates = tuple(item for item in self._notations if item.kind is kind)
                    if not candidates:
                        continue
                    definition = next(
                        (item for item in candidates if item.id == self._chosen.get(kind)),
                        candidates[0],
                    )
                    try:
                        self.projections[kind] = kernel.notation(model.id, definition.id)
                    except ValueError as exc:
                        notation_errors.append((definition.title, str(exc)))
                graph = self.projections.get(NotationKind.GRAPH)
                if graph:
                    self.reconciler.reconcile(graph.graph, projection_positions(graph.graph))
                self._render_table(schema, model, active_ids)
                self._render_tree(schema)
                composed = self.projections.get(NotationKind.COMPOSED)
                self.composed.set_canvas(composed.canvas if composed else None)
                if self._selected_id is not None and model.node(self._selected_id) is None:
                    self._selected_id = None
                self.status.setText(
                    f"Revision {kernel.revision} | {len(model.nodes)} objects | "
                    "Edits update the same canonical model in every notation."
                    + (
                        f" Runtime is pinned to revision {runtime.project_revision}."
                        if runtime and runtime.project_revision != kernel.revision
                        else ""
                    )
                )
            else:
                self.reconciler.clear()
                self.table.clear()
                self.table.setRowCount(0)
                self.tree.clear()
                self.composed.set_canvas(None)
                self.status.setText("Create a domain schema, then a model and its objects.")
            self._render_definitions(schema)
            self._render_languages(schema)
            self._render_computations()
            if self._attempts:
                self._attempts_changed(None)
            self.diagnostics.clear()
            for title, error in notation_errors:
                self.diagnostics.addTopLevelItem(QTreeWidgetItem([error, title]))
            if kernel:
                for issue in kernel.workbench().diagnostics:
                    message = (
                        f"Capability information: {issue.message}"
                        if issue.code == "COMPUTATION_NO_BACKEND"
                        else issue.message
                    )
                    item = QTreeWidgetItem([message, issue.field or issue.object_id])
                    item.setData(0, Qt.ItemDataRole.UserRole, issue.object_id)
                    item.setToolTip(0, issue.code)
                    self.diagnostics.addTopLevelItem(item)
            self._load_form()
            self._sync_notation_choice()
            self.new_schema_button.setEnabled(self._client is not None)
            self.add_root_button.setEnabled(
                model is not None and schema is not None and bool(schema.concepts)
            )
        finally:
            self._refreshing = False
        if self._kernel:
            model = self.current_model()
            if (
                self._editor_preparation is not None
                and self._editor_preparation.pending
                and (
                    model is None
                    or not self._editor_preparation.matches(
                        self._kernel.authority.snapshot(), model_id=model.id
                    )
                )
            ):
                self._editor_preparation.cancel()
            self._apply_selection(self._kernel.selection.state)

    def _render_table(
        self, schema: DomainSchema, model: DomainModel, active_ids: tuple[str, ...]
    ) -> None:
        projection = self.projections.get(NotationKind.TABLE)
        self.table.clear()
        if projection is None:
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            return
        self.table.setColumnCount(len(projection.columns) + 1)
        self.table.setHorizontalHeaderLabels(
            ["Object", *(item.title for item in projection.columns)]
        )
        self.table.setRowCount(len(projection.rows))
        for row_index, row in enumerate(projection.rows):
            node = model.node(row.node_id)
            assert node is not None
            leading = field_cell(
                schema,
                model,
                node,
                NotationField(),
                cell_id=f"{row.node_id}:label",
                revision=projection.revision,
                workspace=self._client.snapshot().domain_workspace if self._client else None,
            )
            for column_index, cell in enumerate((leading, *row.cells)):
                item = QTableWidgetItem(cell.text)
                item.setData(Qt.ItemDataRole.UserRole, cell)
                item.setToolTip(cell.semantic_id)
                if column_index == 0 and row.badges:
                    item.setToolTip(f"{cell.semantic_id}\n" + " | ".join(row.badges))
                if (
                    cell.edit is None
                    or cell.edit.kind is NotationEditKind.REFERENCE
                    or (
                        cell.edit.property_definition is not None
                        and cell.edit.property_definition.value_kind in RICH_VALUE_KINDS
                    )
                ):
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if row.active or cell.semantic_id in active_ids:
                    item.setBackground(QColor("#ffe4b5"))
                self.table.setItem(row_index, column_index, item)

    def _render_tree(self, schema: DomainSchema) -> None:
        self.tree.clear()
        projection = self.projections.get(NotationKind.TREE_FORM)
        model = self.current_model()
        if projection is None or model is None:
            return

        def add(node: NotationTreeNode, parent: QTreeWidgetItem | None = None) -> None:
            value = model.node(node.node_id)
            concept = schema.concept(value.concept_id) if value else None
            item = QTreeWidgetItem([node.label, concept.name if concept else "Unknown"])
            item.setData(0, Qt.ItemDataRole.UserRole, node.node_id)
            item.setToolTip(0, f"{node.node_id}\n" + " | ".join(node.badges))
            if node.active:
                item.setBackground(0, QColor("#ffe4b5"))
            if parent is None:
                self.tree.addTopLevelItem(item)
            else:
                parent.addChild(item)
            for child in node.children:
                add(child, item)
            item.setExpanded(True)

        for root in projection.roots:
            add(root)

    def _render_definitions(self, schema: DomainSchema | None) -> None:
        self.definitions.clear()
        if schema is None:
            return
        root = QTreeWidgetItem([schema.namespace, "Schema", f"Version {schema.version}"])
        root.setData(0, Qt.ItemDataRole.UserRole, schema.id)
        self.definitions.addTopLevelItem(root)
        for concept in schema.concepts:
            item = QTreeWidgetItem([concept.name, "Concept", concept.description])
            item.setData(0, Qt.ItemDataRole.UserRole, concept.id)
            root.addChild(item)
            for prop in concept.properties:
                child = QTreeWidgetItem(
                    [prop.name, prop.value_kind.value, "Required" if prop.required else "Optional"]
                )
                child.setData(0, Qt.ItemDataRole.UserRole, prop.id)
                item.addChild(child)
            for kind, roles in (
                ("Containment", concept.containment_roles),
                ("Reference", concept.reference_roles),
            ):
                for role in roles:
                    child = QTreeWidgetItem(
                        [
                            role.name,
                            kind,
                            f"{role.min_count}.."
                            f"{role.max_count if role.max_count is not None else '*'}",
                        ]
                    )
                    child.setData(0, Qt.ItemDataRole.UserRole, role.id)
                    item.addChild(child)
        notation_root = QTreeWidgetItem(
            ["Notations", "Presentation", "Declarations over stable object IDs"]
        )
        self.definitions.addTopLevelItem(notation_root)
        for definition in self._notations:
            notation_root.addChild(
                QTreeWidgetItem([definition.title, definition.kind.value, definition.id])
            )
        if self._kernel is None:
            return
        snapshot = self._kernel.workbench()
        for label, values in (
            ("Bundles", snapshot.bundles),
            ("Domains", snapshot.domains),
            ("Transformations", snapshot.transformations),
            ("Generators", snapshot.generators),
        ):
            group = QTreeWidgetItem([label, "Registered implementation", ""])
            self.definitions.addTopLevelItem(group)
            for value in values:
                group.addChild(
                    QTreeWidgetItem(
                        [
                            str(getattr(value, "title", getattr(value, "id", value))),
                            str(getattr(value, "version", "")),
                            str(getattr(value, "id", "")),
                        ]
                    )
                )
        self.definitions.expandToDepth(1)

    def _load_form(self) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        self._properties.clear()
        self._references.clear()
        schema, model = self.current_schema(), self.current_model()
        node = model.node(self._selected_id) if model and self._selected_id else None
        concept = schema.concept(node.concept_id) if schema and node else None
        self.apply_button.setEnabled(concept is not None and self._client is not None)
        if schema is None or model is None or node is None or concept is None:
            self.form_title.setText("Select an object to edit its properties and references.")
            return
        self._form_revision = self._kernel.revision if self._kernel else 0
        tree = self.projections.get(NotationKind.TREE_FORM)
        label = (
            notation_node_label(schema, model, node, tree.definition, self._form_revision)
            if tree
            else node_label(schema, node)
        )
        display_value = (
            node.property(concept.display_property_id) if concept.display_property_id else None
        )
        if display_value is not None:
            label = value_summary(display_value)
        self.form_title.setText(f"{label} — {concept.name}\n{node.id}")
        for prop in concept.properties:
            value = node.property(prop.id)
            editor = ScalarEditor(
                prop,
                value if value is not None else prop.default,
                resources=self._resource_descriptors(),
                resource_store=self._kernel.resource_store if self._kernel else None,
                unit_choices=self._unit_choices(),
            )
            self._properties[prop.id] = editor
            self.form.addRow(prop.name + (" *" if prop.required else ""), editor)
        for role in concept.reference_roles:
            reference_editor = ReferenceEditor(
                role,
                schema,
                model,
                node.reference_ids(role.id),
                workspace=self._client.snapshot().domain_workspace if self._client else None,
            )
            self._references[role.id] = reference_editor
            self.form.addRow(role.name, reference_editor)
        for role in concept.containment_roles:
            self.form.addRow(
                role.name,
                QLabel(f"{len(node.child_ids(role.id))} children; use Add child or Move."),
            )

    def _render_languages(self, schema: DomainSchema | None) -> None:
        selected = self.languages.currentItem()
        selected_data = selected.data(0, Qt.ItemDataRole.UserRole) if selected else None
        self.languages.clear()
        if self._kernel is None or schema is None:
            return
        for language in self._kernel.authority.snapshot().domain_workspace.language_definitions:
            if language.schema_id != schema.id:
                continue
            root = QTreeWidgetItem(
                [language.title or schema.namespace, "Domain language", language.version]
            )
            root.setData(0, Qt.ItemDataRole.UserRole, (language.id, "language", language.id))
            self.languages.addTopLevelItem(root)
            items_by_id = {language.id: root}
            for kind, values in (
                ("notation", language.notations),
                ("validator", language.validators),
                ("transformation", language.transformations),
            ):
                for definition in values:
                    if kind == "notation":
                        value = cast(NotationDefinition, definition)
                        label, identifier, detail = value.title, value.id, value.kind.value
                    elif kind == "validator":
                        value_rule = cast(ValidatorDefinition, definition)
                        label, identifier, detail = (
                            value_rule.message,
                            value_rule.id,
                            value_rule.code,
                        )
                    else:
                        value_transform = cast(AuthoredTransformation, definition)
                        label = value_transform.definition.description or "Program transformation"
                        identifier = value_transform.definition.id
                        detail = value_transform.definition.version
                    item = QTreeWidgetItem([label, kind.title(), detail])
                    item.setData(0, Qt.ItemDataRole.UserRole, (language.id, kind, identifier))
                    root.addChild(item)
                    items_by_id[identifier] = item
                    if item.data(0, Qt.ItemDataRole.UserRole) == selected_data:
                        self.languages.setCurrentItem(item)
            for identity, record, owner_id in language_records(language):
                if identity in items_by_id:
                    continue
                kind_label = language_kind_label(record)
                title = str(
                    getattr(record, "name", "") or getattr(record, "label", "") or kind_label
                )
                item = QTreeWidgetItem([title, kind_label, ""])
                item.setData(0, Qt.ItemDataRole.UserRole, (language.id, "template", identity))
                items_by_id.get(owner_id or language.id, root).addChild(item)
                items_by_id[identity] = item
                if item.data(0, Qt.ItemDataRole.UserRole) == selected_data:
                    self.languages.setCurrentItem(item)
            if root.data(0, Qt.ItemDataRole.UserRole) == selected_data:
                self.languages.setCurrentItem(root)
            root.setExpanded(True)
        if self.languages.currentItem() is None and self.languages.topLevelItemCount():
            first = self.languages.topLevelItem(0)
            assert first is not None
            self.languages.setCurrentItem(first)

    def _edit_language(self, *, create: bool) -> None:
        from code_visualizer.application.language_commands import PutDomainLanguage

        schema = self.current_schema()
        if schema is None or self._kernel is None or self._client is None:
            return
        selected = self.languages.currentItem()
        data = selected.data(0, Qt.ItemDataRole.UserRole) if selected else None
        workspace = self._kernel.authority.snapshot().domain_workspace
        existing = workspace.language(data[0]) if data and not create else None
        if not create and existing is None:
            self.status.setText("Select a saved domain language or create one first.")
            return
        revision = self._kernel.revision
        dialog = LanguageEditorDialog(
            schema,
            existing,
            self,
            workspace=workspace,
            project=self._kernel.authority.snapshot(),
            semantic_relations=self._kernel.queries.program.relations,
        )
        if existing and data and data[1] != "language":
            dialog.select_identity(data[2])
        if dialog.exec() == QDialog.DialogCode.Accepted and self._finish(
            self._client.submit(PutDomainLanguage(dialog.language()), expected_revision=revision)
        ):
            self.tabs.setCurrentWidget(self.language_panel)

    def new_language(self) -> None:
        self._edit_language(create=True)

    def edit_language(self) -> None:
        self._edit_language(create=False)

    def delete_language(self) -> None:
        from code_visualizer.application.language_commands import DeleteDomainLanguage

        selected = self.languages.currentItem()
        data = selected.data(0, Qt.ItemDataRole.UserRole) if selected else None
        if data and self._client:
            self._finish(self._client.submit(DeleteDomainLanguage(data[0])))

    def preview_language_notation(self) -> None:
        selected = self.languages.currentItem()
        data = selected.data(0, Qt.ItemDataRole.UserRole) if selected else None
        if not data or data[1] != "notation":
            self.status.setText(
                "Select a notation definition to preview it against the current model."
            )
            return
        self.notation_choice.setCurrentIndex(self.notation_choice.findData(data[2]))
        self._notation_changed()

    def _notation_changed(self, _index: int = -1) -> None:
        if self._refreshing:
            return
        definition = next(
            (item for item in self._notations if item.id == self.notation_choice.currentData()),
            None,
        )
        if definition is not None:
            self._chosen[definition.kind] = definition.id
            self.tabs.setCurrentIndex(
                {
                    NotationKind.GRAPH: 0,
                    NotationKind.TABLE: 1,
                    NotationKind.TREE_FORM: 2,
                    NotationKind.COMPOSED: 3,
                }[definition.kind]
            )
            self.refresh()

    def _tab_changed(self, _index: int = -1) -> None:
        if not self._refreshing:
            self._sync_notation_choice()

    def _sync_notation_choice(self) -> None:
        index = self.tabs.currentIndex()
        if not 0 <= index < 4:
            return
        kind = (
            NotationKind.GRAPH,
            NotationKind.TABLE,
            NotationKind.TREE_FORM,
            NotationKind.COMPOSED,
        )[index]
        projection = self.projections.get(kind)
        if projection is not None:
            self.notation_choice.blockSignals(True)
            self.notation_choice.setCurrentIndex(
                self.notation_choice.findData(projection.definition.id)
            )
            self.notation_choice.blockSignals(False)

    def _select(self, node_id: str) -> None:
        if self._selection_guard or self._refreshing or self._kernel is None:
            return
        self._kernel.selection.select(
            (node_id,), source="ui.domain_workbench", revision=self._kernel.revision
        )

    def _graph_selection(self) -> None:
        for item in self.scene.selectedItems():
            node_id = item.data(SEMANTIC_ID_ROLE)
            if isinstance(node_id, str):
                self._select(node_id)
                break

    def _composed_selection(self, identities: object) -> None:
        if isinstance(identities, tuple) and self._kernel and not self._selection_guard:
            self._kernel.selection.select(
                identities, source="ui.composed_notation", revision=self._kernel.revision
            )

    def _table_selection(self, row: int, column: int, _old_row: int, _old_column: int) -> None:
        item = self.table.item(row, column)
        cell = item.data(Qt.ItemDataRole.UserRole) if item else None
        if isinstance(cell, NotationCell):
            self._select(cell.semantic_id)

    def _tree_selection(
        self, item: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None
    ) -> None:
        if item:
            self._select(str(item.data(0, Qt.ItemDataRole.UserRole)))

    def _definition_selection(self, item: QTreeWidgetItem, _column: int) -> None:
        identifier = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(identifier, str):
            self._select(identifier)

    def _language_selection(
        self, item: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None
    ) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if data:
            self._select(data[2])

    def _diagnostic_selection(self, item: QTreeWidgetItem, _column: int) -> None:
        self.reveal(str(item.data(0, Qt.ItemDataRole.UserRole)))

    def _apply_selection(self, value: object) -> None:
        if not isinstance(value, SelectionState) or self._kernel is None or self._selection_guard:
            return
        self._selection_guard = True
        try:
            model = self.current_model()
            primary_node = next(
                (
                    identifier
                    for identifier in value.semantic_ids
                    if model and model.node(identifier)
                ),
                None,
            )
            if primary_node and value.source != "runtime.computation":
                changed = self._selected_id != primary_node
                self._selected_id = primary_node
                if changed:
                    self._load_form()
            for semantic_id, items in self.reconciler.items_by_semantic_id().items():
                for graphics_item in items:
                    graphics_item.setSelected(semantic_id in value.semantic_ids)
            for row in range(self.table.rowCount()):
                for column in range(self.table.columnCount()):
                    item = self.table.item(row, column)
                    cell = item.data(Qt.ItemDataRole.UserRole) if item else None
                    if item and isinstance(cell, NotationCell):
                        item.setSelected(cell.semantic_id in value.semantic_ids)

            def visit(item: QTreeWidgetItem | None) -> None:
                if item is None:
                    return
                item.setSelected(item.data(0, Qt.ItemDataRole.UserRole) in value.semantic_ids)
                for index in range(item.childCount()):
                    visit(item.child(index))

            for index in range(self.tree.topLevelItemCount()):
                visit(self.tree.topLevelItem(index))
            for index in range(self.definitions.topLevelItemCount()):
                visit(self.definitions.topLevelItem(index))
        finally:
            self._selection_guard = False
        self._highlight_source(value.semantic_ids)
        self.composed.select_semantic_ids(value.semantic_ids)

    def reveal(self, node_id: str) -> None:
        kernel = self._kernel
        if kernel is None:
            return
        workspace = kernel.authority.snapshot().domain_workspace
        model = next(
            (item for item in workspace.models if item.id == node_id or item.node(node_id)), None
        )
        if model:
            self.schema_choice.setCurrentIndex(self.schema_choice.findData(model.schema_id))
            self.model_choice.setCurrentIndex(self.model_choice.findData(model.id))
            self._selected_id = node_id if model.node(node_id) else None
            self.refresh()
            self._select(node_id)
            return
        value = kernel.queries.semantic_object(node_id)
        language_id = (
            next((item.value for item in value.properties if item.name == "language_id"), None)
            if value
            else None
        )
        language = workspace.language(language_id) if language_id else None
        if language:
            self.schema_choice.setCurrentIndex(self.schema_choice.findData(language.schema_id))
            self.refresh()
            self.tabs.setCurrentWidget(self.language_panel)
            pending = [
                self.languages.topLevelItem(index)
                for index in range(self.languages.topLevelItemCount())
            ]
            while pending:
                item = pending.pop()
                if item is None:
                    continue
                data = item.data(0, Qt.ItemDataRole.UserRole)
                if data and data[2] == node_id:
                    ancestor = item.parent()
                    while ancestor is not None:
                        ancestor.setExpanded(True)
                        ancestor = ancestor.parent()
                    self.languages.setCurrentItem(item)
                    self.languages.scrollToItem(item)
                    self._select(node_id)
                    return
                pending.extend(item.child(index) for index in range(item.childCount()))
            return
        visited: set[str] = set()
        while value is not None and workspace.schema(value.id) is None:
            if value.id in visited or value.parent_id is None:
                return
            visited.add(value.id)
            value = kernel.queries.semantic_object(value.parent_id)
        if value is None:
            return
        self.schema_choice.setCurrentIndex(self.schema_choice.findData(value.id))
        self.refresh()
        self.tabs.setCurrentWidget(self.definitions)
        remaining = [
            self.definitions.topLevelItem(index)
            for index in range(self.definitions.topLevelItemCount())
        ]
        while remaining:
            item = remaining.pop()
            if item is None:
                continue
            if item.data(0, Qt.ItemDataRole.UserRole) == node_id:
                ancestor = item.parent()
                while ancestor is not None:
                    ancestor.setExpanded(True)
                    ancestor = ancestor.parent()
                self.definitions.setCurrentItem(item)
                self.definitions.scrollToItem(item)
                self._select(node_id)
                return
            remaining.extend(item.child(index) for index in range(item.childCount()))

    def _table_edit(self, item: QTableWidgetItem) -> None:
        if self._refreshing or self._client is None or self._kernel is None:
            return
        cell = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(cell, NotationCell) or cell.edit is None:
            return
        try:
            prop = cell.edit.property_definition
            if prop is None:
                return
            value = parse_scalar(item.text(), prop.value_kind)
            command = notation_edit_command(cell.edit, value, revision=self._kernel.revision)
            self._finish(self._client.submit(command, expected_revision=cell.edit.revision))
        except ValueError as exc:
            self.refresh()
            self.status.setText(str(exc))

    def _resource_descriptors(self) -> tuple[DataResource, ...]:
        store = self._kernel.resource_store if self._kernel else None
        return store.descriptors() if store is not None else ()

    def _table_open(self, row: int, column: int) -> None:
        item = self.table.item(row, column)
        cell = item.data(Qt.ItemDataRole.UserRole) if item else None
        if (
            not isinstance(cell, NotationCell)
            or cell.edit is None
            or self._kernel is None
            or self._client is None
        ):
            return
        binding = cell.edit
        workspace = self._client.snapshot().domain_workspace
        model = workspace.model(binding.model_id)
        schema = workspace.schema(model.schema_id) if model else None
        node = model.node(binding.node_id) if model else None
        if node is None or model is None or schema is None:
            return
        try:
            if binding.kind is NotationEditKind.REFERENCE and binding.role_definition is not None:
                dialog = QDialog(self)
                dialog.setWindowTitle(binding.role_definition.name)
                layout = QVBoxLayout(dialog)
                editor = ReferenceEditor(
                    binding.role_definition,
                    schema,
                    model,
                    node.reference_ids(binding.field_id),
                    workspace=workspace,
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
                command = notation_edit_command(
                    binding, editor.target_ids(), revision=self._kernel.revision
                )
            else:
                prop = binding.property_definition
                if prop is None or prop.value_kind not in RICH_VALUE_KINDS:
                    return
                value_dialog = ValueDialog(
                    prop,
                    node.property(prop.id),
                    self,
                    resources=self._resource_descriptors(),
                    resource_store=self._kernel.resource_store,
                    unit_choices=self._unit_choices(),
                )
                if value_dialog.exec() != QDialog.DialogCode.Accepted:
                    return
                command = notation_edit_command(
                    binding, value_dialog.result_value, revision=self._kernel.revision
                )
            self._finish(self._client.submit(command, expected_revision=binding.revision))
        except ValueError as exc:
            self.status.setText(str(exc))

    def _unit_choices(self) -> tuple[tuple[str, UnitReference], ...]:
        from code_visualizer.application.domain_workbench import catalog_unit_choices

        return catalog_unit_choices(self._client.snapshot()) if self._client else ()

    def apply_fields(self) -> None:
        if self._client is None or self._selected_id is None:
            return
        model = self.current_model()
        node = model.node(self._selected_id) if model else None
        if model is None or node is None:
            return
        commands: list[TypedCommand] = []
        try:
            for property_id, editor in self._properties.items():
                value = editor.value()
                if value != node.property(property_id):
                    commands.append(SetDomainProperty(model.id, node.id, property_id, value))
            for role_id, reference_editor in self._references.items():
                targets = reference_editor.target_ids()
                if targets != node.reference_ids(role_id):
                    commands.append(SetDomainReference(model.id, node.id, role_id, targets))
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        if commands:
            self._finish(
                self._client.transaction(
                    commands,
                    expected_revision=self._form_revision,
                    intent="Edit domain object fields",
                )
            )

    def _finish(self, result: CommandResult) -> bool:
        self.refresh()
        if isinstance(result, CommandRejected):
            self.status.setText(f"{result.code}: {result.message}")
            return False
        return isinstance(result, CommandAccepted)

    def new_schema(self) -> None:
        if self._client is None:
            return
        dialog = SchemaDialog(parent=self, workspace=self._client.snapshot().domain_workspace)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            schema = dialog.schema()
            if self._finish(self._client.submit(PutDomainSchema(schema))):
                self.schema_choice.setCurrentIndex(self.schema_choice.findData(schema.id))

    def add_registered_schema(self) -> None:
        if self._kernel is None or self._client is None:
            return
        workspace = self._kernel.authority.snapshot().domain_workspace
        schemas = tuple(
            item
            for item in self._kernel.workbench().available_schemas
            if workspace.schema(item.id) is None
        )
        if not schemas:
            self.status.setText("All registered domain schemas are already in this project.")
            return
        names = [f"{item.namespace} ({item.version})" for item in schemas]
        name, accepted = QInputDialog.getItem(
            self, "Add registered domain", "Domain", names, editable=False
        )
        if accepted:
            schema = schemas[names.index(name)]
            try:
                required = schema_installation(
                    workspace,
                    self._kernel.workbench().available_schemas,
                    schema.id,
                    version=schema.version,
                    registry=self._kernel.extensions,
                )
                if self._finish(
                    self._client.transaction(
                        tuple(PutDomainSchema(item) for item in required),
                        intent="Install registered domain schemas and their referenced definitions",
                    )
                ):
                    self.schema_choice.setCurrentIndex(self.schema_choice.findData(schema.id))
            except ValueError as exc:
                self.status.setText(str(exc))

    def edit_schema(self) -> None:
        schema = self.current_schema()
        if schema is None or self._client is None:
            return
        dialog = SchemaDialog(schema, self, workspace=self._client.snapshot().domain_workspace)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._finish(self._client.submit(PutDomainSchema(dialog.schema())))

    def add_reference_vocabulary(self) -> None:
        if self._kernel is None or self._client is None:
            return
        from code_visualizer.domain.intentional import BundleReference

        workspace = self._client.snapshot().domain_workspace
        bundles = tuple(
            bundle
            for bundle in self._kernel.extensions.bundles()
            if bundle.reference_models
            and any(workspace.model(model.id) is None for model in bundle.reference_models)
        )
        if not bundles:
            self.status.setText("All registered reference vocabularies are already installed.")
            return
        names = [f"{bundle.id} ({bundle.version})" for bundle in bundles]
        name, accepted = QInputDialog.getItem(
            self, "Add reference vocabulary", "Vocabulary", names, editable=False
        )
        if accepted:
            bundle = bundles[names.index(name)]
            try:
                commands = bundle_installation(
                    workspace, self._kernel.extensions, BundleReference(bundle.id, bundle.version)
                )
                if self._finish(
                    self._client.transaction(
                        commands,
                        intent="Install reference vocabulary and exact schema dependencies",
                    )
                ):
                    model = bundle.reference_models[0]
                    self.schema_choice.setCurrentIndex(self.schema_choice.findData(model.schema_id))
                    self.model_choice.setCurrentIndex(self.model_choice.findData(model.id))
                    declared = self._kernel.extensions.notations_for(
                        model.schema_id, model.schema_version
                    )
                    if declared:
                        self.notation_choice.setCurrentIndex(
                            self.notation_choice.findData(declared[0].id)
                        )
            except ValueError as exc:
                self.status.setText(str(exc))

    def delete_schema(self) -> None:
        schema = self.current_schema()
        if schema and self._client:
            self._finish(self._client.submit(DeleteDomainSchema(schema.id)))

    def new_model(self) -> None:
        schema = self.current_schema()
        if schema is None or self._client is None:
            return
        title, accepted = QInputDialog.getText(self, "New model", "Model name")
        if accepted and title.strip():
            model = DomainModel(
                new_id("domain-model"), schema.id, schema.version, title=title.strip()
            )
            if self._finish(self._client.submit(PutDomainModel(model))):
                self.model_choice.setCurrentIndex(self.model_choice.findData(model.id))

    def delete_model(self) -> None:
        model = self.current_model()
        if model and self._client:
            self._finish(self._client.submit(DeleteDomainModel(model.id)))

    def create_node(self, child: bool) -> None:
        schema, model = self.current_schema(), self.current_model()
        if schema is None or model is None or self._client is None:
            return
        parent = model.node(self._selected_id) if child and self._selected_id else None
        role_id = None
        allowed: tuple[str, ...] = ()
        if child:
            concept = schema.concept(parent.concept_id) if parent else None
            if concept is None or not concept.containment_roles:
                self.status.setText("Select an object with a containment role first.")
                return
            names = [item.name for item in concept.containment_roles]
            name, accepted = QInputDialog.getItem(
                self, "Add child", "Containment role", names, editable=False
            )
            if not accepted:
                return
            role = concept.containment_roles[names.index(name)]
            role_id, allowed = role.id, role.allowed_concept_ids
        dialog = NodeDialog(
            schema,
            model,
            allowed,
            self,
            workspace=self._client.snapshot().domain_workspace,
            resources=self._resource_descriptors(),
            resource_store=self._kernel.resource_store if self._kernel else None,
            unit_choices=self._unit_choices(),
        )
        if (
            dialog.exec() == QDialog.DialogCode.Accepted
            and (node := dialog.node()) is not None
            and self._finish(
                self._client.submit(
                    CreateDomainNode(
                        model.id, node, parent_id=parent.id if parent else None, role_id=role_id
                    )
                )
            )
        ):
            self._select(node.id)

    def connect_nodes(self, source_id: str, target_id: str) -> None:
        schema, model = self.current_schema(), self.current_model()
        projection = self.projections.get(NotationKind.GRAPH)
        if schema is None or model is None or projection is None or self._client is None:
            return
        source, target = model.node(source_id), model.node(target_id)
        if source is None or target is None:
            self.status.setText("Connect two domain objects.")
            return
        rules = []
        for candidate in projection.definition.edge_rules:
            concept = schema.concept(candidate.concept_id)
            source_role = concept.role(candidate.source_role_id) if concept else None
            target_role = concept.role(candidate.target_role_id) if concept else None
            if (
                source_role
                and target_role
                and source.concept_id in source_role.allowed_concept_ids
                and target.concept_id in target_role.allowed_concept_ids
            ):
                rules.append(candidate)
        if not rules:
            concept = schema.concept(source.concept_id)
            roles = (
                tuple(
                    role
                    for role in concept.reference_roles
                    if target.concept_id in role.allowed_concept_ids
                )
                if concept
                else ()
            )
            if not roles:
                self.status.setText(
                    "This notation has no permitted relationship between those concepts."
                )
                return
            names = [role.name for role in roles]
            name, accepted = QInputDialog.getItem(
                self, "Connect objects", "Reference role", names, editable=False
            )
            if accepted:
                role = roles[names.index(name)]
                targets = (
                    (target.id,)
                    if role.max_count == 1
                    else tuple(dict.fromkeys((*source.reference_ids(role.id), target.id)))
                )
                self._finish(
                    self._client.submit(SetDomainReference(model.id, source.id, role.id, targets))
                )
            return
        rule = rules[0]
        if len(rules) > 1:
            names = [
                concept.name if (concept := schema.concept(item.concept_id)) else item.concept_id
                for item in rules
            ]
            name, accepted = QInputDialog.getItem(
                self, "Connect objects", "Relationship concept", names, editable=False
            )
            if not accepted:
                return
            rule = rules[names.index(name)]
        dialog = NodeDialog(
            schema,
            model,
            (rule.concept_id,),
            self,
            initial_references=(
                RoleBinding(rule.source_role_id, (source.id,)),
                RoleBinding(rule.target_role_id, (target.id,)),
            ),
            workspace=self._client.snapshot().domain_workspace,
            resources=self._resource_descriptors(),
            resource_store=self._kernel.resource_store if self._kernel else None,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or (node := dialog.node()) is None:
            return
        owners = {
            child_id: parent.id
            for parent in model.nodes
            for binding in parent.children
            for child_id in binding.node_ids
        }

        def ancestors(identity: str) -> set[str]:
            result: set[str] = set()
            while identity in owners and owners[identity] not in result:
                identity = owners[identity]
                result.add(identity)
            return result

        common_owners = ancestors(source.id) & ancestors(target.id)
        destinations = [
            (parent.id, role.id)
            for parent in model.nodes
            if parent.id in common_owners
            if (concept := schema.concept(parent.concept_id)) is not None
            for role in concept.containment_roles
            if node.concept_id in role.allowed_concept_ids
        ]
        parent_id, role_id = destinations[0] if len(destinations) == 1 else (None, None)
        if self._finish(
            self._client.submit(
                CreateDomainNode(model.id, node, parent_id=parent_id, role_id=role_id)
            )
        ):
            self._select(node.id)

    def delete_node(self) -> None:
        model = self.current_model()
        if model and self._selected_id and self._client:
            self._finish(self._client.submit(DeleteDomainNode(model.id, self._selected_id)))

    def move_node(self) -> None:
        schema, model = self.current_schema(), self.current_model()
        node = model.node(self._selected_id) if model and self._selected_id else None
        if schema is None or model is None or node is None or self._client is None:
            return
        destinations: list[tuple[str, str | None, str | None]] = [("Model root", None, None)]
        for parent in model.nodes:
            concept = schema.concept(parent.concept_id)
            if concept is None or parent.id == node.id:
                continue
            for role in concept.containment_roles:
                if node.concept_id in role.allowed_concept_ids:
                    destinations.append(
                        (f"{node_label(schema, parent)} / {role.name}", parent.id, role.id)
                    )
        names = [item[0] for item in destinations]
        name, accepted = QInputDialog.getItem(
            self, "Move object", "Destination", names, editable=False
        )
        if accepted:
            _, parent_id, role_id = destinations[names.index(name)]
            destination_parent = model.node(parent_id) if parent_id else None
            count = (
                len(destination_parent.child_ids(role_id))
                if destination_parent and role_id
                else len(model.roots)
            )
            self._finish(
                self._client.submit(MoveDomainChild(model.id, node.id, parent_id, role_id, count))
            )

    def move_order(self, delta: int) -> None:
        model = self.current_model()
        if model is None or self._selected_id is None or self._client is None:
            return
        parent_id, role_id, identifiers = None, None, model.roots
        for parent in model.nodes:
            for role in parent.children:
                if self._selected_id in role.node_ids:
                    parent_id, role_id, identifiers = parent.id, role.role_id, role.node_ids
        if self._selected_id in identifiers:
            target = max(0, min(len(identifiers) - 1, identifiers.index(self._selected_id) + delta))
            self._finish(
                self._client.submit(
                    MoveDomainChild(model.id, self._selected_id, parent_id, role_id, target)
                )
            )

    def undo(self) -> None:
        if self._client:
            self._finish(self._client.undo())

    def redo(self) -> None:
        if self._client:
            self._finish(self._client.redo())

    def _fit(self) -> None:
        if self.tabs.currentWidget() is self.composed:
            self.composed.view.fitInView(
                self.composed.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio
            )
        else:
            self.graph_view.fit_projection()

    def build_model(self) -> None:
        self._prepare_editor(EditorAction.PREVIEW)

    def _render_computations(self) -> None:
        kernel = self._kernel
        if kernel is None:
            self.backend_choice.clear()
            self.evidence_view.clear()
            return
        from code_visualizer.application.computation import available_backends

        previous = self.backend_choice.currentData()
        definitions = available_backends(kernel)
        self._backend_definitions = definitions
        model = self.current_model()
        schema = self.current_schema()
        self.backend_choice.blockSignals(True)
        self.backend_choice.clear()
        for backend in definitions:
            self.backend_choice.addItem(f"{backend.title} ({backend.version})", backend.key)
            self.backend_choice.setItemData(
                self.backend_choice.count() - 1, backend.description, Qt.ItemDataRole.ToolTipRole
            )
        selected = self.backend_choice.findData(previous)
        model_id = model.id if model else None
        if model_id != self._backend_model_id or selected < 0:
            selected = next(
                (
                    index
                    for index, backend in enumerate(definitions)
                    if schema is not None
                    and (backend.schema_id, backend.schema_version) == (schema.id, schema.version)
                ),
                0,
            )
        if definitions:
            self.backend_choice.setCurrentIndex(selected)
        self._backend_model_id = model_id
        self.backend_choice.blockSignals(False)
        for item in kernel.runtime.evidence_records():
            self._evidence[item.id] = item
            self._evidence_attachments.setdefault(item.id, set()).add(
                kernel.computation_attachment.id
            )
        self._render_evidence()

    def _render_evidence(self) -> None:
        kernel = self._kernel
        if kernel is None:
            return
        self.evidence_view.clear()
        for evidence in sorted(
            self._evidence.values(), key=lambda item: (item.provenance.revision, item.id)
        ):
            provenance = evidence.provenance
            current_source = (
                provenance.revision == kernel.revision
                and kernel.computation_attachment.id
                in self._evidence_attachments.get(evidence.id, set())
            )
            stale = "" if current_source else " · historical source"
            root = QTreeWidgetItem(
                [
                    f"{provenance.backend_id}@{provenance.backend_version}",
                    f"{evidence.outcome.value} · revision {provenance.revision}{stale}",
                ]
            )
            root.setData(0, Qt.ItemDataRole.UserRole, (evidence.id, ()))
            root.setToolTip(0, evidence.id)
            self.evidence_view.addTopLevelItem(root)
            for observation in evidence.observations:
                item = QTreeWidgetItem(
                    [observation.label or observation.id, value_summary(observation.value)]
                )
                item.setToolTip(1, str(observation.value))
                item.setData(0, Qt.ItemDataRole.UserRole, (evidence.id, observation.semantic_ids))
                root.addChild(item)
            for artifact in evidence.artifacts:
                item = QTreeWidgetItem([artifact.label or artifact.id, artifact.resource.id])
                item.setData(0, Qt.ItemDataRole.UserRole, (evidence.id, artifact.semantic_ids))
                item.setData(0, Qt.ItemDataRole.UserRole + 1, artifact.id)
                item.setToolTip(1, artifact.resource.content_hash)
                root.addChild(item)
            for diagnostic in evidence.diagnostics:
                item = QTreeWidgetItem([diagnostic.code, diagnostic.message])
                item.setData(0, Qt.ItemDataRole.UserRole, (evidence.id, diagnostic.semantic_ids))
                root.addChild(item)
            root.setExpanded(True)

    def freeze_computation(self) -> None:
        if self._kernel is None:
            return
        backend = next(
            (
                item
                for item in self._backend_definitions
                if item.key == self.backend_choice.currentData()
            ),
            None,
        )
        if backend is None:
            self.status.setText("Select an available computation backend.")
            return
        project = self._kernel.authority.snapshot()
        model = self.current_model()
        self.freezeRequested.emit(
            ComputationRequest(
                project.id,
                project.revision,
                backend.id,
                backend.version,
                model.id if model else None,
            )
        )

    def run_computation(self) -> None:
        if self._kernel is None:
            return
        from code_visualizer.application.computation import start_computation

        backend = next(
            (
                item
                for item in self._backend_definitions
                if item.key == self.backend_choice.currentData()
            ),
            None,
        )
        if backend is None:
            self.status.setText("Select an available computation backend.")
            return
        project = self._kernel.authority.snapshot()
        model = self.current_model()
        try:
            session = start_computation(
                self._kernel,
                ComputationRequest(
                    project.id,
                    project.revision,
                    backend.id,
                    backend.version,
                    model.id if model else None,
                ),
            )
            self._active_computation_id = session.id
            self.tabs.setCurrentWidget(self.evidence_panel)
            self.computation_status.setText(
                f"Queued {backend.title} at revision {project.revision}."
            )
            self.status.setText(self.computation_status.text())
            self._runtime_observer.poll()
        except (ValueError, RuntimeError, OSError) as exc:
            self.status.setText(str(exc))

    def cancel_computation(self) -> None:
        if self._kernel is None or self._active_computation_id is None:
            return
        self.computation_status.setText("Cancellation requested; waiting for the worker to stop.")
        self.cancel_computation_button.setEnabled(False)
        try:
            self._kernel.computations.cancel(CancelRequest(self._active_computation_id))
        except (ValueError, RuntimeError) as exc:
            self.computation_status.setText(str(exc))
        self._runtime_observer.poll()

    def select_computation(self, identity: str) -> None:
        """Reveal the submitted attempt after an asynchronous editor handoff."""
        if self._kernel is None or not any(
            attempt.session.id == identity for attempt in self._kernel.computations.attempts()
        ):
            return
        self._active_computation_id = identity
        self._attempts_changed(None)

    def _attempts_changed(self, _attempts: object) -> None:
        kernel = self._kernel
        if kernel is None:
            return
        self._attempts = kernel.computations.attempts()
        existing = {}
        for index in range(self.attempt_view.topLevelItemCount()):
            existing_item = self.attempt_view.topLevelItem(index)
            if existing_item is not None:
                existing[existing_item.data(0, Qt.ItemDataRole.UserRole)] = existing_item
        evidence_changed = False
        for attempt in self._attempts:
            session = attempt.session
            item = existing.pop(session.id, None)
            if item is None:
                item = QTreeWidgetItem()
                item.setData(0, Qt.ItemDataRole.UserRole, session.id)
                self.attempt_view.addTopLevelItem(item)
            historical = (
                attempt.attachment_id != kernel.computation_attachment.id
                or session.revision != kernel.revision
            )
            item.setText(0, f"{session.backend_id}@{session.backend_version}")
            item.setText(
                1,
                f"{session.status.value} / {attempt.phase} · revision {session.revision}"
                + (" · historical source" if historical else ""),
            )
            item.setToolTip(0, session.id)
            item.setToolTip(1, attempt.source_digest or "Source digest pending preparation")
            evidence = kernel.computations.evidence(session.id)
            if evidence is not None:
                evidence_changed |= evidence.id not in self._evidence
                self._evidence[evidence.id] = evidence
                self._evidence_attachments.setdefault(evidence.id, set()).add(attempt.attachment_id)
            if session.id == self._active_computation_id:
                self.attempt_view.setCurrentItem(item)
        for item in existing.values():
            self.attempt_view.takeTopLevelItem(self.attempt_view.indexOfTopLevelItem(item))
        if evidence_changed:
            self._render_evidence()
        self._update_attempt_status()

    def _attempt_selected(
        self, item: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None
    ) -> None:
        self._inspecting_evidence = False
        self._update_attempt_status()

    def _update_attempt_status(self) -> None:
        item = self.attempt_view.currentItem()
        identity = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        attempt = next((item for item in self._attempts if item.session.id == identity), None)
        if attempt is None:
            self.cancel_computation_button.setEnabled(False)
            return
        self._active_computation_id = attempt.session.id
        pending = attempt.session.status in {ComputationStatus.QUEUED, ComputationStatus.RUNNING}
        self.cancel_computation_button.setEnabled(pending and attempt.phase != "finalizing")
        detail = (
            f"{attempt.session.backend_id}: {attempt.session.status.value} / {attempt.phase}; "
            f"revision {attempt.session.revision}."
        )
        if attempt.progress is not None:
            detail += f" {attempt.progress.message[:1000]}"
        if attempt.diagnostic:
            detail += f" {attempt.diagnostic[:2000]}"
        if attempt.phase == "finalizing":
            detail += " Verifying terminal evidence; cancellation is closed."
        if self._kernel and (
            attempt.attachment_id != self._kernel.computation_attachment.id
            or attempt.session.revision != self._kernel.revision
        ):
            detail += " Historical source; current authoring is unchanged."
        self.computation_status.setText(detail)
        self.status.setText(detail)
        self._render_attempt_outputs(attempt)
        if not self._inspecting_evidence:
            self.evidence_details.setPlainText(
                f"Attempt: {attempt.session.id}\nSource revision: {attempt.session.revision}\n"
                f"Source digest: {attempt.source_digest or '(preparing)'}\n"
                f"Phase: {attempt.phase}\nSealed publications: {len(attempt.publications)}"
            )

    def _render_attempt_outputs(self, attempt: ComputationAttempt) -> None:
        kernel = self._kernel
        if kernel is None:
            return
        self.field_history.observe_attempt(attempt)
        self.channel_history.observe_attempt(attempt)
        self.cell_history.observe_attempt(attempt)
        state = kernel.computations.state(attempt.session.id)
        observation = state.observation if state is not None else None
        historical = (
            attempt.attachment_id != kernel.computation_attachment.id
            or attempt.session.revision != kernel.revision
        )
        if observation is None:
            self.computation_preview.setText("No provisional observation.")
        else:
            provenance = "historical source" if historical else "current source"
            provisional = attempt.session.status in {
                ComputationStatus.QUEUED,
                ComputationStatus.RUNNING,
            }
            observation_status = (
                "Provisional"
                if provisional
                else "Accepted"
                if attempt.session.status is ComputationStatus.SUCCEEDED
                else "Unaccepted"
            )
            self.computation_preview.setText(
                f"{observation_status} observation "
                f"from revision {attempt.session.revision} ({provenance}), "
                f"event {observation.sequence}:\n"
                f"{observation.label or observation.id}: "
                f"{value_summary(observation.value)[:2000]}"
            )
            self.computation_preview.setToolTip(
                f"Attempt: {attempt.session.id}\nSource: {attempt.source_digest or '(preparing)'}"
            )
        existing = {}
        for index in range(self.publication_view.topLevelItemCount()):
            item = self.publication_view.topLevelItem(index)
            if item is not None:
                existing[item.data(0, Qt.ItemDataRole.UserRole)] = item
        for identity in attempt.publications:
            publication = kernel.computations.publication(identity)
            if publication is None:
                continue
            item = existing.pop(identity, None)
            if item is None:
                item = QTreeWidgetItem()
                item.setData(0, Qt.ItemDataRole.UserRole, identity)
                self.publication_view.addTopLevelItem(item)
            artifact = publication.artifact
            item.setText(0, artifact.label or artifact.id)
            item.setText(
                1,
                f"{artifact.resource.id} · revision {attempt.session.revision}"
                + (" · historical source" if historical else ""),
            )
            item.setToolTip(1, artifact.resource.content_hash)
        for item in existing.values():
            self.publication_view.takeTopLevelItem(self.publication_view.indexOfTopLevelItem(item))

    def _publication_selected(self, item: QTreeWidgetItem, _column: int) -> None:
        kernel = self._kernel
        identity = item.data(0, Qt.ItemDataRole.UserRole)
        if kernel is None or not isinstance(identity, str):
            return
        publication = kernel.computations.publication(identity)
        if publication is None:
            return
        if kernel.resource_store is not None:
            from code_visualizer.ui_qt.field_history import FieldViewSource

            self._field_inspect_requested = True
            self.field_history.inspect(
                FieldViewSource(
                    publication.artifact.resource,
                    kernel.resource_store,
                    self._active_computation_id or publication.id,
                    publication.provenance.input_digest,
                    publication.provenance.revision,
                    False,
                    "Sealed publication",
                )
            )
            from code_visualizer.ui_qt.channel_history import ChannelViewSource

            self._channel_inspect_requested = True
            self.channel_history.inspect(
                ChannelViewSource(
                    publication.artifact.resource,
                    kernel.resource_store,
                    self._active_computation_id or publication.id,
                    publication.provenance.input_digest,
                    publication.provenance.revision,
                    False,
                    "Sealed publication",
                )
            )
        self._inspecting_evidence = True
        self.evidence_details.setPlainText(
            f"Sealed publication: {publication.id}\n"
            f"Revision: {publication.provenance.revision}\n"
            f"Input digest: {publication.provenance.input_digest}\n"
            f"Resource: {publication.artifact.resource.id}\n"
            f"Content hash: {publication.artifact.resource.content_hash}\n"
            "Verified immutable resource; cancellation cannot alter these published bytes."
        )
        if kernel.resource_store is not None:
            from code_visualizer.ui_qt.adaptive_history import CellViewSource

            self._cell_inspect_requested = True
            self.cell_history.inspect(
                CellViewSource(
                    publication.artifact.resource,
                    kernel.resource_store,
                    self._active_computation_id or publication.id,
                    publication.provenance.input_digest,
                    publication.provenance.revision,
                    False,
                    "Sealed publication",
                )
            )

    def _field_loaded(self) -> None:
        if self._field_inspect_requested:
            self._field_inspect_requested = False
            self.field_outputs.setCurrentWidget(self.field_scroll)
            self.tabs.setCurrentWidget(self.evidence_panel)

    def _field_failed(self, _message: str) -> None:
        self._field_inspect_requested = False

    def _channel_loaded(self) -> None:
        if self._channel_inspect_requested:
            self._channel_inspect_requested = False
            self.field_outputs.setCurrentWidget(self.channel_scroll)
            self.tabs.setCurrentWidget(self.evidence_panel)

    def _channel_failed(self, _message: str) -> None:
        self._channel_inspect_requested = False

    def _cell_loaded(self) -> None:
        if self._cell_inspect_requested:
            self._cell_inspect_requested = False
            self.field_outputs.setCurrentWidget(self.cell_scroll)
            self.tabs.setCurrentWidget(self.evidence_panel)

    def _cell_failed(self, _message: str) -> None:
        self._cell_inspect_requested = False

    def _runtime_changed(self, _state: object) -> None:
        """Refresh decorations only; running work must not reset an open authoring form."""
        kernel = self._kernel
        if kernel is None or self._refreshing:
            return
        active_ids = kernel.current_runtime_ids()
        if active_ids == self._runtime_ids:
            return
        self._runtime_ids = active_ids
        model = self.current_model()
        if model is None:
            return
        self._refreshing = True
        try:
            self._update_runtime_notations(model, active_ids)
        finally:
            self._refreshing = False

    def _update_runtime_notations(self, model: DomainModel, active_ids: tuple[str, ...]) -> None:
        kernel = self._kernel
        assert kernel is not None
        for kind, projection in tuple(self.projections.items()):
            self.projections[kind] = kernel.notation(model.id, projection.definition.id)
        graph = self.projections.get(NotationKind.GRAPH)
        if graph:
            self.reconciler.reconcile(graph.graph, projection_positions(graph.graph))
        active = set(active_ids)
        table_projection = self.projections.get(NotationKind.TABLE)
        for row in range(self.table.rowCount()):
            row_active = (
                table_projection is not None
                and row < len(table_projection.rows)
                and table_projection.rows[row].active
            )
            for column in range(self.table.columnCount()):
                item = self.table.item(row, column)
                if item is None:
                    continue
                cell = item.data(Qt.ItemDataRole.UserRole)
                enabled = row_active or (
                    isinstance(cell, NotationCell) and cell.semantic_id in active
                )
                item.setBackground(QColor("#ffe4b5") if enabled else QColor())
        pending = [self.tree.topLevelItem(index) for index in range(self.tree.topLevelItemCount())]
        while pending:
            tree_item = pending.pop()
            if tree_item is None:
                continue
            enabled = tree_item.data(0, Qt.ItemDataRole.UserRole) in active
            tree_item.setBackground(0, QColor("#ffe4b5") if enabled else QColor())
            pending.extend(tree_item.child(index) for index in range(tree_item.childCount()))
        composed = self.projections.get(NotationKind.COMPOSED)
        self.composed.update_runtime(composed.canvas if composed else None)

    def load_evidence(self) -> None:
        if self._kernel is None or self._kernel.evidence_store is None:
            self.status.setText("Save the project to browse its durable evidence store.")
            return
        from code_visualizer.application.computation import get_evidence

        try:
            for evidence_id in self._kernel.evidence_store.identities():
                evidence = get_evidence(self._kernel, evidence_id)
                if evidence is not None:
                    self._evidence[evidence.id] = evidence
            self._render_computations()
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))

    def _evidence_selected(self, item: QTreeWidgetItem, _column: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or self._kernel is None:
            return
        evidence = self._evidence.get(data[0])
        if evidence is None:
            return
        self._inspecting_evidence = True
        provenance = evidence.provenance
        self.evidence_details.setPlainText(
            f"{evidence.id}\nRevision: {provenance.revision}\n"
            f"Input hash: {provenance.input_digest}\n"
            f"Backend: {provenance.backend_id}@{provenance.backend_version}\n"
            "Transformations: "
            f"{', '.join(provenance.transformations) or '(direct interpretation)'}\n"
            f"{item.text(0)}\n{item.toolTip(1) or item.text(1)}"
        )
        semantic_ids = tuple(
            dict.fromkeys(
                origin for identity in data[1] for origin in provenance.origins.sources(identity)
            )
        )
        current_source = (
            self._kernel.computation_attachment.id
            in self._evidence_attachments.get(evidence.id, set())
            and provenance.revision == self._kernel.revision
        )
        artifact_id = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if isinstance(artifact_id, str) and self._kernel.resource_store is not None:
            from code_visualizer.ui_qt.field_history import FieldViewSource

            artifact = next(a for a in evidence.artifacts if a.id == artifact_id)
            self._field_inspect_requested = True
            self.field_history.inspect(
                FieldViewSource(
                    artifact.resource,
                    self._kernel.resource_store,
                    evidence.id,
                    provenance.input_digest,
                    provenance.revision,
                    current_source,
                    evidence.outcome.value,
                )
            )
            self.artifact_panel.inspect(
                evidence, artifact_id, self._kernel.resource_store, current_source=current_source
            )
            from code_visualizer.ui_qt.channel_history import ChannelViewSource

            self._channel_inspect_requested = True
            self.channel_history.inspect(
                ChannelViewSource(
                    artifact.resource,
                    self._kernel.resource_store,
                    evidence.id,
                    provenance.input_digest,
                    provenance.revision,
                    current_source,
                    evidence.outcome.value,
                )
            )
            self.tabs.setCurrentWidget(self.artifact_panel)
            from code_visualizer.ui_qt.adaptive_history import CellViewSource

            self._cell_inspect_requested = True
            self.cell_history.inspect(
                CellViewSource(
                    artifact.resource,
                    self._kernel.resource_store,
                    evidence.id,
                    provenance.input_digest,
                    provenance.revision,
                    current_source,
                    evidence.outcome.value,
                )
            )
        if semantic_ids and current_source:
            self._kernel.selection.select(
                semantic_ids, revision=provenance.revision, source="evidence.inspector"
            )
        elif semantic_ids:
            self.computation_status.setText(
                "Historical evidence; its origins are shown above "
                "without highlighting current authoring."
            )

    def trace_model(self) -> None:
        self._prepare_editor(EditorAction.TRACE)

    def debug_model(self) -> None:
        self._prepare_editor(EditorAction.DEBUG)

    def _prepare_editor(self, action: EditorAction) -> None:
        model = self.current_model()
        if self._kernel is None or model is None or self._editor_preparation is None:
            return
        self.stop_debug()
        self.status.setText(f"Preparing {action.value} from revision {self._kernel.revision}...")
        self._editor_preparation.request(
            self._kernel.authority.snapshot(),
            action,
            model_id=model.id,
        )

    def _editor_prepared(self, raw: object) -> None:
        kernel, preparation, model = self._kernel, self._editor_preparation, self.current_model()
        if (
            kernel is None
            or preparation is None
            or model is None
            or not isinstance(raw, EditorPreparedSnapshot)
        ):
            return
        if not preparation.matches(kernel.authority.snapshot(), model_id=model.id):
            preparation.cancel()
            return
        if raw.request_id != preparation.request_id or raw.revision != kernel.revision:
            return
        if raw.status == "failed":
            self.status.setText(raw.diagnostic)
            return
        if raw.status != "ready" or raw.generated is None:
            return
        self._set_generated(raw.generated, raw.revision)
        if preparation.action is EditorAction.PREVIEW:
            count = len(raw.generated.origins.links) if raw.generated.origins else 0
            self.status.setText(f"Built revision {raw.revision}; {count} origin mappings.")
            return
        try:
            if preparation.action is EditorAction.TRACE:
                self._trace_snapshot = raw
                self._python_run.start_project_trace(
                    raw.generated,
                    project_revision=raw.revision,
                    artifact_revision=raw.revision,
                    binding_specs=raw.binding_specs,
                    completed=partial(self._emit_trace, raw),
                )
            elif preparation.action is EditorAction.DEBUG:
                from code_visualizer.application.domain_execution import debug_prepared

                self._debug_session = debug_prepared(kernel, raw)
                self._debug_timer.start()
        except (ValueError, RuntimeError) as exc:
            self.status.setText(str(exc))

    def _emit_trace(self, snapshot: EditorPreparedSnapshot, result: TraceResult) -> None:
        self.traceCompleted.emit(map_trace(snapshot, result, policy=SourceSpanPolicy.NARROWEST))

    def _trace_completed(self, raw: object) -> None:
        kernel = self._kernel
        if (
            not isinstance(raw, MappedTrace)
            or raw.snapshot is not self._trace_snapshot
            or kernel is None
        ):
            return
        self._trace_snapshot = None
        self._retained_trace = raw
        self._trace_delivery = raw
        self._trace_delivery_index = 0
        generated = raw.snapshot.generated
        assert generated is not None
        first = next(iter(raw.result.runtime_events), raw.result.terminal_event)
        if first is not None and generated.origins is not None:
            kernel.runtime.register_origins(first.execution_session_id, generated.origins)
        self.trace_event.blockSignals(True)
        try:
            self.trace_event.clear()
            self.trace_event.addItem("Captured trace preview", -1)
            for page in raw.output_pages:
                self.trace_event.addItem(page.label, page)
            for position, event in enumerate(raw.result.events):
                self.trace_event.addItem(
                    f"{event.index:04d} {event.event} {event.file_path}:{event.line}", position
                )
        finally:
            self.trace_event.blockSignals(False)
        self.trace_details.setPlainText(raw.console)
        self.status.setText("Delivering captured trace events...")
        self._trace_timer.start()

    def _deliver_trace_events(self) -> None:
        from code_visualizer.application.domain_execution import record_mapped_trace_event

        mapped, kernel = self._trace_delivery, self._kernel
        if mapped is None or kernel is None:
            self._trace_timer.stop()
            return
        started = perf_counter()
        count = 0
        while self._trace_delivery_index < len(mapped.result.runtime_events):
            position = self._trace_delivery_index
            self._trace_delivery_index += 1
            record_mapped_trace_event(
                kernel,
                mapped.snapshot,
                mapped.result.runtime_events[position],
                mapped.spans[position],
            )
            if self._trace_delivery is not mapped:
                return
            count += 1
            if count >= 32 or perf_counter() - started >= 0.008:
                return
        if mapped.result.terminal_event is not None:
            record_mapped_trace_event(
                kernel, mapped.snapshot, mapped.result.terminal_event, mapped.terminal_span
            )
        self._trace_delivery = None
        self._trace_timer.stop()
        output = mapped.result.run.stdout or mapped.result.run.stderr or "Trace complete."
        self.status.setText(
            output[:1000]
            + (" [preview truncated; see Captured trace]" if len(output) > 1000 else "")
        )

    def _trace_event_selected(self, _index: int) -> None:
        mapped, kernel = self._retained_trace, self._kernel
        position = self.trace_event.currentData()
        if mapped is None or kernel is None:
            return
        if isinstance(position, TraceOutputPage):
            self.trace_details.setPlainText(output_page_text(mapped, position))
            return
        if not isinstance(position, int):
            return
        if position < 0:
            self.trace_details.setPlainText(mapped.console)
            return
        event = mapped.result.events[position]
        self.trace_details.setPlainText(
            f"Captured revision {mapped.snapshot.revision}; "
            f"{event.file_path}:{event.line}; {event.event}\n"
            + "\n".join(f"{name} = {value}" for name, value in event.locals)
        )
        span = mapped.spans[position]
        if span is not None and kernel.revision == mapped.snapshot.revision:
            generated = mapped.snapshot.generated
            assert generated is not None
            origins = generated.origins
            identities = origins.sources(span.semantic_id) if origins else (span.semantic_id,)
            kernel.selection.select(
                identities,
                revision=mapped.snapshot.revision,
                source="runtime.trace.inspector",
            )

    def _poll_debug(self) -> None:
        from code_visualizer.application.domain_execution import WorkbenchDebugSession

        if isinstance(self._debug_session, WorkbenchDebugSession):
            for event in self._debug_session.poll_events():
                self.status.setText(
                    event.text
                    or event.traceback
                    or event.detail
                    or f"Debugger {event.state.value} at {event.file_path}:{event.line}"
                )
                if event.state.value in {"finished", "failed", "stopped"}:
                    self._debug_timer.stop()

    def step_debug(self) -> None:
        from code_visualizer.application.domain_execution import WorkbenchDebugSession

        if isinstance(self._debug_session, WorkbenchDebugSession):
            try:
                self._debug_session.step_into()
            except RuntimeError as exc:
                self.status.setText(str(exc))

    def continue_debug(self) -> None:
        from code_visualizer.application.domain_execution import WorkbenchDebugSession

        if isinstance(self._debug_session, WorkbenchDebugSession):
            try:
                self._debug_session.continue_execution()
            except RuntimeError as exc:
                self.status.setText(str(exc))

    def stop_debug(self) -> None:
        self._trace_timer.stop()
        self._trace_delivery = None
        if self._editor_preparation is not None:
            self._editor_preparation.cancel()
        self._python_run.stop()
        self._trace_snapshot = None
        self._debug_timer.stop()
        if self._debug_session is not None:
            from code_visualizer.application.domain_execution import WorkbenchDebugSession

            if isinstance(self._debug_session, WorkbenchDebugSession):
                self._debug_session.stop()
            self._debug_session = None

    def _set_generated(self, generated: GeneratedProject, revision: int) -> None:
        self._generated, self._generated_revision = generated, revision
        self._source_module = None
        model = self.current_model()
        ids = self._generated_ids(tuple(node.id for node in model.nodes) if model else ())
        self._show_source_module(ids)

    def _generated_ids(self, semantic_ids: tuple[str, ...]) -> set[str]:
        ids = set(semantic_ids)
        origins = self._generated.origins if self._generated else None
        if origins:
            ids.update(
                link.generated_id for link in origins.links if ids.intersection(link.source_ids)
            )
        return ids

    def _show_source_module(self, semantic_ids: set[str]) -> None:
        generated = self._generated
        if generated is None:
            return
        modules = generated.files
        module = self._source_module
        if module is None or not any(span.semantic_id in semantic_ids for span in module.spans):
            module = next(
                (
                    item
                    for item in modules
                    if any(span.semantic_id in semantic_ids for span in item.spans)
                ),
                module
                or next((item for item in modules if item.spans), modules[0] if modules else None),
            )
        self._source_module = module
        self._source_guard = True
        try:
            source = module.source if module else ""
            if self.code.toPlainText() != source:
                self.code.setPlainText(source)
            self.code.setToolTip(
                f"{module.path if module else generated.launcher_path} from revision "
                f"{self._generated_revision}; edit the domain objects."
            )
        finally:
            self._source_guard = False

    def _highlight_source(self, semantic_ids: tuple[str, ...]) -> None:
        if self._generated is None or self._source_guard:
            return
        ids = self._generated_ids(semantic_ids)
        self._show_source_module(ids)
        source_spans = self._source_module.spans if self._source_module else self._generated.spans
        spans = tuple(span for span in source_spans if span.semantic_id in ids)
        selections: list[QTextEdit.ExtraSelection] = []
        self._source_guard = True
        try:
            for span in spans:
                cursor = QTextCursor(self.code.document().findBlockByNumber(span.start_line - 1))
                cursor.select(QTextCursor.SelectionType.LineUnderCursor)
                selection = QTextEdit.ExtraSelection()
                selection.cursor = cursor
                selection.format.setBackground(QColor("#ffe4b5"))
                selections.append(selection)
            self.code.setExtraSelections(selections)
            if spans:
                smallest = min(
                    spans, key=lambda span: (span.end_line - span.start_line, span.start_line)
                )
                self.code.setTextCursor(
                    QTextCursor(self.code.document().findBlockByNumber(smallest.start_line - 1))
                )
                self.code.centerCursor()
        finally:
            self._source_guard = False

    def _source_selection(self) -> None:
        if self._source_guard or self._generated is None or self._kernel is None:
            return
        line = self.code.textCursor().blockNumber() + 1
        source_spans = self._source_module.spans if self._source_module else self._generated.spans
        spans = tuple(span for span in source_spans if span.start_line <= line <= span.end_line)
        if not spans:
            return
        span = min(spans, key=lambda value: (value.end_line - value.start_line, value.start_line))
        ids = self._generated.origins.sources(span.semantic_id) if self._generated.origins else ()
        self._kernel.selection.select(
            ids or (span.semantic_id,),
            revision=self._generated_revision,
            source="ui.domain_generated_source",
        )
