"""Indivisible diagram, generated-code, and live-test document surface."""

from __future__ import annotations

from functools import partial
from time import perf_counter

from PySide6.QtCore import QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QTextCursor, QTextFormat
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from code_visualizer.application.editor_preparation import EditorPreparedSnapshot
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.trace_presentation import (
    MappedTrace,
    TraceOutputPage,
    map_trace,
    output_page_text,
)
from code_visualizer.config import PRODUCT
from code_visualizer.domain.drakon import DrakonDiagram
from code_visualizer.domain.invocation_arguments import parse_invocation_arguments
from code_visualizer.domain.project import Project
from code_visualizer.domain.projection import DrakonViewDefinition
from code_visualizer.execution import (
    DebugEvent,
    DebugLaunch,
    DebugSession,
    DebugState,
    RunResult,
    RunSession,
    SourceLocation,
    TraceResult,
)
from code_visualizer.execution.worker_process import WorkerProfile
from code_visualizer.generation import SourceSpan
from code_visualizer.generation.emitter import GeneratedFile, GeneratedProject
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.ui_qt.canvas import DrakonCanvas
from code_visualizer.ui_qt.editor_preparation import EditorAction, QtEditorPreparation
from code_visualizer.ui_qt.function_signature import FunctionSignatureEditor
from code_visualizer.ui_qt.source_selection import SourceSelectionRange, source_selection_range


class UnifiedDocumentWidget(QWidget):
    projectChanged = Signal()
    atomSelected = Signal(str, str, str)
    semanticSelectionChanged = Signal(object)
    runCompleted = Signal(object)
    traceCompleted = Signal(object)
    executionSelection = Signal(str, str, int, str)
    executionEvent = Signal(object, str)

    def __init__(
        self,
        client: CodeVisualizerClient,
        diagram_id: str,
        parent: QWidget | None = None,
        *,
        preparation_profiles: tuple[WorkerProfile, ...] | None = None,
        resource_store: ResourceStore | None = None,
        settings: QSettings | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("unifiedDocument")
        self._client = client
        self._view_settings = (
            settings if settings is not None else QSettings(PRODUCT.application_id, PRODUCT.name)
        )
        self._output_hidden_by_user = False
        self._updating_output = False
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.diagram_id = diagram_id
        self.layout_mode = "side_by_side"
        self._generated: GeneratedFile | None = None
        self._execution_generated: GeneratedProject | None = None
        self._source_breakpoints: set[SourceLocation] = set()
        self._selected_span: SourceSpan | SourceSelectionRange | None = None
        self._view: DrakonViewDefinition | None = None
        self._debug_span: SourceSpan | None = None
        self._mapping_selection = False
        self._debugger = DebugSession(history_limit=500)
        self._run_session = RunSession()
        self._trace_snapshot: EditorPreparedSnapshot | None = None
        self._retained_trace: MappedTrace | None = None
        self._trace_delivery: MappedTrace | None = None
        self._trace_delivery_index = 0
        self._trace_timer = QTimer(self)
        self._trace_timer.setInterval(16)
        self._trace_timer.timeout.connect(self._deliver_trace_events)
        self._prepared_revision: int | None = None
        self._preparation = QtEditorPreparation(
            self,
            profiles=preparation_profiles,
            resource_store=resource_store,
            current_project=client.snapshot,
        )
        self._preparation.changed.connect(self._preparation_changed)
        self.runCompleted.connect(self._run_completed)
        self.traceCompleted.connect(self._trace_completed)
        self._debug_timer = QTimer(self)
        self._debug_timer.setInterval(30)
        self._debug_timer.timeout.connect(self._poll_debugger)
        self.destroyed.connect(lambda: self._stop_child_processes())

        self._diagram_pane = QWidget()
        self._diagram_pane.setObjectName("diagramPane")
        diagram_layout = QVBoxLayout(self._diagram_pane)
        self.header_label = QLabel()
        self.header_label.setObjectName("diagramHeader")
        self.header_label.setWordWrap(True)
        self.header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.canvas = DrakonCanvas()
        self.canvas.atomSelected.connect(self._canvas_selection_changed)
        self.canvas.objectClicked.connect(self._canvas_object_clicked)
        self.canvas.objectSelectionChanged.connect(self._canvas_objects_selected)
        self.canvas.insertRequested.connect(self._insert_at_boundary)
        self.canvas.moveRequested.connect(self._move_block)
        self.empty_hint = QLabel(
            "This algorithm is valid and currently emits pass.\n"
            "Drop on the visible route, use Shapes, or press Ctrl+Shift+P."
        )
        self.empty_hint.setObjectName("emptyAlgorithmHint")
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.insert_output_button = QPushButton("Insert Output")
        self.insert_output_button.setObjectName("insertOutputButton")
        self.insert_output_button.clicked.connect(self.insert_output)
        self.hello_button = QPushButton("Start with Hello World")
        self.hello_button.setObjectName("helloWorldButton")
        self.hello_button.clicked.connect(self.insert_hello_world)
        insertion_row = QHBoxLayout()
        insertion_row.addStretch(1)
        insertion_row.addWidget(self.insert_output_button)
        insertion_row.addWidget(self.hello_button)
        insertion_row.addStretch(1)
        self.starter_actions = QWidget()
        self.starter_actions.setObjectName("starterActions")
        self.starter_actions.setLayout(insertion_row)
        diagram_layout.addWidget(self.header_label)
        diagram_layout.addWidget(self.canvas, 1)
        diagram_layout.addWidget(self.empty_hint)
        diagram_layout.addWidget(self.starter_actions)

        self.code = QPlainTextEdit()
        self.code.setObjectName("generatedCodeView")
        self.code.setReadOnly(True)
        self.code.setAccessibleName("Generated Python")
        self.code.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.code.cursorPositionChanged.connect(self._source_cursor_changed)

        self._comparison = QSplitter(Qt.Orientation.Horizontal)
        self._comparison.setObjectName("documentComparison")
        self._comparison.addWidget(self._diagram_pane)
        self._comparison.addWidget(self.code)
        self._comparison.setStretchFactor(0, 3)
        self._comparison.setStretchFactor(1, 2)
        self._comparison.setHandleWidth(8)
        self._comparison.setSizes([600, 400])
        self._comparison.splitterMoved.connect(self._save_pane_sizes)
        self._comparison.splitterMoved.connect(lambda *_: self.canvas.schedule_fit())
        self._comparison.setStyleSheet(
            "QSplitter::handle { background: palette(mid); }"
            "QSplitter::handle:hover { background: palette(highlight); }"
        )
        for pane in (self._diagram_pane, self.code):
            pane.setMinimumSize(0, 0)
            pane.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

        self._view_container = QWidget()
        self._view_layout = QVBoxLayout(self._view_container)
        self._view_layout.setContentsMargins(0, 0, 0, 0)
        self.source_file = QComboBox()
        self.source_file.setObjectName("generatedSourceFile")
        self.source_file.setAccessibleName("Generated Python file")
        self.source_file.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.source_file.setMinimumContentsLength(12)
        self.source_file.currentIndexChanged.connect(self._source_file_changed)
        self._view_layout.addWidget(self.source_file)
        self._view_layout.addWidget(self._comparison)
        self._inner_tabs: QTabWidget | None = None

        self.signature = FunctionSignatureEditor(client, diagram_id)
        self.signature.applied.connect(self._signature_applied)

        self.arguments = QLineEdit()
        self.arguments.setObjectName("liveTestArguments")
        self.arguments.setPlaceholderText("Python call arguments")
        self.test_preset = QComboBox()
        self.test_preset.setObjectName("liveTestPreset")
        self.test_preset.setEditable(True)
        self.test_preset.addItem("Default")
        self.test_preset.setAccessibleName("Named live test preset")
        self.execution_toolbar = QToolBar("Function execution", self)
        self.execution_toolbar.setObjectName("functionExecutionToolbar")
        self.execution_toolbar.setMovable(False)
        self.execution_toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.action_run = QAction("Run Function", self)
        self.action_trace = QAction("Trace Function", self)
        self.action_debug = QAction("Debug Function", self)
        self.action_stop = QAction("Stop Function", self)
        self.action_run.triggered.connect(self.run_current)
        self.action_trace.triggered.connect(self.trace_current)
        self.action_debug.triggered.connect(self.debug_current)
        self.action_stop.triggered.connect(self.stop_current)
        self.action_stop.setEnabled(False)
        for action in (self.action_run, self.action_trace, self.action_debug, self.action_stop):
            self.execution_toolbar.addAction(action)
        self.run_button = self.execution_toolbar.widgetForAction(self.action_run)
        self.trace_button = self.execution_toolbar.widgetForAction(self.action_trace)
        self.debug_button = self.execution_toolbar.widgetForAction(self.action_debug)
        self.stop_button = self.execution_toolbar.widgetForAction(self.action_stop)
        for button, name in (
            (self.run_button, "runCurrentButton"),
            (self.trace_button, "traceCurrentButton"),
            (self.debug_button, "debugCurrentButton"),
            (self.stop_button, "stopCurrentButton"),
        ):
            assert button is not None
            button.setObjectName(name)

        self.auto_fit_toggle = QAction("Auto-fit", self)
        self.auto_fit_toggle.setCheckable(True)
        self.auto_fit_toggle.setChecked(True)
        self.auto_fit_toggle.setToolTip("Refit after resizing. Manual zoom or pan turns this off.")
        self.auto_fit_toggle.toggled.connect(self.canvas.set_auto_fit)
        self.canvas.autoFitChanged.connect(self.auto_fit_toggle.setChecked)
        self.wrap_code = QAction("Wrap Code", self)
        self.wrap_code.setCheckable(True)
        self.wrap_code.setObjectName("wrapGeneratedCode")
        self.wrap_code.setChecked(
            str(self._view_settings.value("workspace/wrap_code", "false")).lower()
            in {"true", "1", "yes"}
        )
        self.wrap_code.toggled.connect(self._set_code_wrapping)
        self._set_code_wrapping(self.wrap_code.isChecked())
        self.output_toggle = QAction("Output", self)
        self.output_toggle.setObjectName("toggleDocumentOutput")
        self.output_toggle.setText("Output")
        self.output_toggle.setCheckable(True)
        self.output_toggle.toggled.connect(self._toggle_output)
        self.execution_toolbar.addSeparator()
        self.execution_toolbar.addAction(self.auto_fit_toggle)
        self.execution_toolbar.addAction(self.wrap_code)
        self.execution_toolbar.addAction(self.output_toggle)
        test_row = QHBoxLayout()
        test_row.addWidget(QLabel("Preset:"))
        test_row.addWidget(self.test_preset)
        test_row.addWidget(QLabel("Test arguments:"))
        test_row.addWidget(self.arguments, 1)
        self.test_preset.setMinimumWidth(0)
        self.test_preset.setMaximumWidth(150)
        self.test_preset.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.arguments.setMinimumWidth(0)
        self.arguments.setToolTip("Arguments passed to this function, not the project entry point.")

        self.debug_state_label = QLabel("Debugger idle")
        self.debug_state_label.setObjectName("debugState")
        self.debug_state_label.setMaximumWidth(260)
        self.debug_state_label.setWordWrap(True)
        self.continue_button = QPushButton("Continue")
        self.continue_button.setObjectName("debugContinue")
        self.continue_button.clicked.connect(self.debug_continue)
        self.step_over_button = QPushButton("Step Over")
        self.step_over_button.setObjectName("debugStepOver")
        self.step_over_button.clicked.connect(self.debug_step_over)
        self.step_into_button = QPushButton("Step Into")
        self.step_into_button.setObjectName("debugStepInto")
        self.step_into_button.clicked.connect(self.debug_step_into)
        self.step_out_button = QPushButton("Step Out")
        self.step_out_button.setObjectName("debugStepOut")
        self.step_out_button.clicked.connect(self.debug_step_out)
        self.restart_button = QPushButton("Restart")
        self.restart_button.setObjectName("debugRestart")
        self.restart_button.clicked.connect(self.debug_restart)
        self.source_breakpoint_button = QPushButton("Toggle Line Breakpoint")
        self.source_breakpoint_button.setObjectName("toggleSourceBreakpoint")
        self.source_breakpoint_button.clicked.connect(self.toggle_source_breakpoint)
        self.node_breakpoint_button = QPushButton("Toggle Node Breakpoint")
        self.node_breakpoint_button.setObjectName("toggleNodeBreakpoint")
        self.node_breakpoint_button.clicked.connect(self.toggle_node_breakpoint)
        self.pause_exceptions = QCheckBox("Pause on exceptions")
        self.pause_exceptions.setObjectName("pauseOnExceptions")
        self.pause_exceptions.setChecked(True)
        debug_controls = QToolBar("Debug stepping")
        debug_controls.setMovable(False)
        debug_controls.addWidget(self.debug_state_label)
        debug_controls.addWidget(self.continue_button)
        debug_controls.addWidget(self.step_over_button)
        debug_controls.addWidget(self.step_into_button)
        debug_controls.addWidget(self.step_out_button)
        debug_controls.addWidget(self.restart_button)
        debug_controls.addWidget(self.source_breakpoint_button)
        debug_controls.addWidget(self.node_breakpoint_button)
        debug_controls.addWidget(self.pause_exceptions)

        self.call_stack = QTreeWidget()
        self.call_stack.setObjectName("debugCallStack")
        self.call_stack.setHeaderLabels(["Function", "File", "Line"])
        self.call_stack.itemActivated.connect(self._stack_frame_activated)
        self.locals = QTreeWidget()
        self.locals.setObjectName("debugLocals")
        self.locals.setHeaderLabels(["Binding / field", "Value", "Type / change"])
        self.debug_details = QWidget()
        self.debug_details.setObjectName("debugDetails")
        debug_grid = QGridLayout(self.debug_details)
        debug_grid.setContentsMargins(0, 0, 0, 0)
        debug_grid.addWidget(debug_controls, 0, 0, 1, 2)
        debug_grid.addWidget(self.call_stack, 1, 0)
        debug_grid.addWidget(self.locals, 1, 1)
        self.trace_event = QComboBox()
        self.trace_event.setObjectName("capturedTraceEvent")
        self.trace_event.setAccessibleName("Captured trace event")
        self.trace_event.currentIndexChanged.connect(self._trace_event_selected)
        self.trace_event.hide()
        debug_grid.addWidget(self.trace_event, 2, 0, 1, 2)
        self.debug_details.hide()
        self._set_debug_controls(False)

        self.console = QPlainTextEdit()
        self.console.setObjectName("liveTestConsole")
        self.console.setReadOnly(True)
        self.console.setAccessibleName("Live test output")
        self.console.setMaximumBlockCount(5000)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.signature_scroll = QScrollArea()
        self.signature_scroll.setObjectName("signatureScroll")
        self.signature_scroll.setWidgetResizable(True)
        self.signature_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.signature_scroll.setWidget(self.signature)
        self.signature_scroll.setMaximumHeight(72)
        self.signature_scroll.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum
        )
        self.signature.toggle_details.toggled.connect(
            lambda expanded: self.signature_scroll.setMaximumHeight(260 if expanded else 72)
        )
        self._output_pane = QWidget()
        output_layout = QVBoxLayout(self._output_pane)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.addWidget(self.debug_details, 1)
        output_layout.addWidget(self.console, 1)
        self._work_split = QSplitter(Qt.Orientation.Vertical)
        self._work_split.setObjectName("documentOutputSplitter")
        self._work_split.setHandleWidth(8)
        self._work_split.setStyleSheet(self._comparison.styleSheet())
        self._work_split.addWidget(self._view_container)
        self._work_split.addWidget(self._output_pane)
        self._work_split.setStretchFactor(0, 4)
        self._work_split.setStretchFactor(1, 1)
        self._work_split.setSizes([800, 180])
        self._work_split.splitterMoved.connect(self._save_output_sizes)
        self._output_pane.hide()
        self.console.textChanged.connect(self._output_changed)
        layout.addWidget(self.signature_scroll)
        layout.addWidget(self.execution_toolbar)
        layout.addLayout(test_row)
        layout.addWidget(self._work_split, 1)
        self.refresh(client.snapshot())
        self._restore_pane_sizes()

    def _set_code_wrapping(self, enabled: bool) -> None:
        self.code.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth
            if enabled
            else QPlainTextEdit.LineWrapMode.NoWrap
        )
        self._view_settings.setValue("workspace/wrap_code", enabled)

    def _save_pane_sizes(self, *_args: object) -> None:
        if self.layout_mode in {"side_by_side", "stacked"}:
            self._view_settings.setValue(
                f"document/{self.diagram_id}/{self.layout_mode}/split", self._comparison.sizes()
            )

    def _restore_pane_sizes(self) -> None:
        if self.layout_mode not in {"side_by_side", "stacked"}:
            return
        saved = self._view_settings.value(
            f"document/{self.diagram_id}/{self.layout_mode}/split", [600, 400]
        )
        try:
            sizes = (
                [int(value) for value in saved] if isinstance(saved, (list, tuple)) else [600, 400]
            )
        except (TypeError, ValueError):
            sizes = [600, 400]
        if len(sizes) != 2 or any(value <= 0 for value in sizes):
            sizes = [600, 400]
        self._comparison.setSizes(sizes)

    def _toggle_output(self, visible: bool) -> None:
        if not self._updating_output:
            self._output_hidden_by_user = not visible
        self._output_pane.setVisible(visible)
        self.output_toggle.setText("Output")
        if visible:
            saved = self._view_settings.value(f"document/{self.diagram_id}/output_height", 180)
            try:
                height = max(60, min(int(str(saved)), max(60, self.height() // 2)))
            except (TypeError, ValueError):
                height = 180
            self._work_split.setSizes([max(1, self.height() - height), height])
        self.canvas.schedule_fit()

    def _save_output_sizes(self, *_args: object) -> None:
        sizes = self._work_split.sizes()
        if len(sizes) == 2 and sizes[1] > 0:
            self._view_settings.setValue(f"document/{self.diagram_id}/output_height", sizes[1])

    def _show_output(self) -> None:
        self._updating_output = True
        try:
            self.output_toggle.setChecked(True)
        finally:
            self._updating_output = False

    def _output_changed(self) -> None:
        if self.console.document().isEmpty():
            if self.debug_details.isHidden():
                self._updating_output = True
                try:
                    self.output_toggle.setChecked(False)
                finally:
                    self._updating_output = False
            return
        if self._output_hidden_by_user:
            self.output_toggle.setText("Output (new)")
        else:
            self._show_output()

    def refresh(self, project: Project) -> None:
        self._view = next(
            (view for view in project.drakon_views if view.document_id == self.diagram_id), None
        )
        document = next(
            (
                item
                for item in project.documents
                if isinstance(item, DrakonDiagram) and item.id == self.diagram_id
            ),
            None,
        )
        if document is None:
            self._preparation.cancel()
            self.header_label.setText("Document unavailable")
            self.canvas.scene().clear()
            self.code.clear()
            return
        self.header_label.setText(f"{document.header.function.display_name}()")
        target = document.header.function.display_name
        for action, verb in (
            (self.action_run, "Run"),
            (self.action_trace, "Trace"),
            (self.action_debug, "Debug"),
        ):
            action.setToolTip(
                f"{verb} {target}() with the function arguments below. "
                "Run Project uses the configured entry point instead."
            )
        self.action_stop.setToolTip(f"Stop the run or debugger belonging to {target}().")
        self.signature.refresh(project)
        self.canvas.set_diagram(document)
        self.empty_hint.setVisible(not document.body.atoms)
        self.starter_actions.setVisible(not document.body.atoms)
        pending_execution = (
            self._preparation.pending
            and self._preparation.action is not EditorAction.PREVIEW
            and self._preparation.matches(project, focus_diagram_id=self.diagram_id)
        )
        if not (self._debugger.is_active or self._run_session.is_active or pending_execution):
            self._preparation.request(
                project, EditorAction.PREVIEW, focus_diagram_id=self.diagram_id
            )
        source = (
            self._generated.source
            if self._generated is not None
            else "# Preparing Python preview...\n"
        )
        cursor_line = self.code.textCursor().blockNumber()
        vertical_scroll = self.code.verticalScrollBar().value()
        if self.code.toPlainText() != source:
            self._mapping_selection = True
            self.code.setPlainText(source)
            cursor = self.code.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.movePosition(
                QTextCursor.MoveOperation.Down,
                QTextCursor.MoveMode.MoveAnchor,
                max(0, min(cursor_line, self.code.blockCount() - 1)),
            )
            self.code.setTextCursor(cursor)
            self.code.verticalScrollBar().setValue(vertical_scroll)
            self._mapping_selection = False
        if self._execution_generated is not None:
            lengths = {
                item.path: len(item.source.splitlines()) for item in self._execution_generated.files
            }
            self._source_breakpoints = {
                location
                for location in self._source_breakpoints
                if 1 <= location.line <= lengths.get(location.file_path, 0)
            }
        self._update_source_highlights()

    def _set_generated(self, generated: GeneratedProject) -> None:
        """Preview one file of the same generated tree that execution consumes."""
        self._execution_generated = generated
        lengths = {item.path: len(item.source.splitlines()) for item in generated.files}
        self._source_breakpoints = {
            location
            for location in self._source_breakpoints
            if 1 <= location.line <= lengths.get(location.file_path, 0)
        }
        module = next(
            (
                item
                for item in generated.files
                if any(span.presentation_id == self.diagram_id for span in item.spans)
            ),
            None,
        )
        self._mapping_selection = True
        try:
            self.source_file.clear()
            for item in generated.files:
                if item.path.endswith(".py"):
                    self.source_file.addItem(item.path, item.path)
        finally:
            self._mapping_selection = False
        self._show_source_file(module.path if module else generated.launcher_path)
        if selected := self.canvas.selected_object_ids():
            self._highlight_object(selected[0])

    def _show_source_file(self, file_path: str) -> bool:
        generated = self._execution_generated
        module = (
            next((item for item in generated.files if item.path == file_path), None)
            if generated
            else None
        )
        if module is None:
            return False
        changed = self._generated is None or self._generated.path != module.path
        self._generated = module
        self._mapping_selection = True
        try:
            self.source_file.setCurrentIndex(self.source_file.findData(module.path))
            if self.code.toPlainText() != module.source:
                self.code.setPlainText(module.source)
            if changed:
                self._selected_span = None
                self._debug_span = None
            self.code.setToolTip(module.path)
        finally:
            self._mapping_selection = False
        self._update_source_highlights()
        return True

    def _source_file_changed(self, _index: int) -> None:
        if not self._mapping_selection and isinstance(path := self.source_file.currentData(), str):
            self._show_source_file(path)

    def _execution_breakpoints(self) -> tuple[SourceLocation, ...]:
        return tuple(
            sorted(
                self._source_breakpoints, key=lambda item: (item.file_path, item.line, item.column)
            )
        )

    def _reveal_runtime_location(self, location: SourceLocation) -> None:
        if (
            self._show_source_file(location.file_path)
            and 1 <= location.line <= self.code.blockCount()
        ):
            self._reveal_source_line(location.line, debug=True)
        else:
            self._debug_span = None
            self._update_source_highlights()

    def _signature_applied(self) -> None:
        self.refresh(self._client.snapshot())
        self.projectChanged.emit()

    def insert_output(self) -> None:
        project = self._client.snapshot()
        document = self._document(project)
        self._insert(
            "output",
            document.body.id,
            len(document.body.atoms),
            source='"output"',
        )

    def insert_hello_world(self) -> None:
        project = self._client.snapshot()
        document = self._document(project)
        self._insert(
            "output",
            document.body.id,
            len(document.body.atoms),
            source='"Hello, world!"',
        )

    def _insert_at_boundary(self, kind: str, sequence_id: str, index: int) -> None:
        self._insert(kind, sequence_id, index, defer_projection=True)

    def _insert(
        self,
        kind: str,
        sequence_id: str,
        index: int,
        *,
        source: str | None = None,
        defer_projection: bool = False,
    ) -> None:
        if kind.startswith("macro:"):
            result = self._client.insert_drakon_macro(
                self.diagram_id,
                kind.removeprefix("macro:"),
                index,
                sequence_id=sequence_id,
            )
        else:
            result = self._client.insert_drakon_atom(
                self.diagram_id,
                kind,
                index,
                source=source,
                sequence_id=sequence_id,
            )
        if isinstance(result, CommandAccepted):
            selected = (result.affected_ids[0],)
            if defer_projection:
                QTimer.singleShot(0, lambda: self._refresh_after_command(selected))
            else:
                self._refresh_after_command(selected)

    def _move_block(
        self,
        source_sequence_id: str,
        atom_ids: object,
        destination_sequence_id: str,
        destination_index: int,
    ) -> None:
        if not isinstance(atom_ids, tuple) or not all(
            isinstance(atom_id, str) for atom_id in atom_ids
        ):
            return
        typed_ids = tuple(atom_id for atom_id in atom_ids if isinstance(atom_id, str))
        result = self._client.move_drakon_block(
            self.diagram_id,
            source_sequence_id,
            typed_ids,
            destination_sequence_id,
            destination_index,
        )
        if isinstance(result, CommandAccepted):
            QTimer.singleShot(0, lambda: self._refresh_after_command(typed_ids))

    def _refresh_after_command(self, selected: tuple[str, ...]) -> None:
        self.refresh(self._client.snapshot())
        self.canvas.select_atoms(selected)
        self.projectChanged.emit()

    def run_current(self) -> None:
        self._request_execution(EditorAction.RUN)

    def _request_execution(self, action: EditorAction) -> None:
        if (
            self._run_session.is_active
            or self._trace_delivery is not None
            or self._debugger.is_active
        ):
            self.debug_state_label.setText("A live run is already active")
            return
        project = self._client.snapshot()
        try:
            arguments = parse_invocation_arguments(self.arguments.text())
            self.console.setPlainText(
                f"Preparing {action.value} from revision {project.revision}...\n"
            )
            self.debug_state_label.setText("Preparing Python")
            self._execution_controls(True)
            self._preparation.request(
                project,
                action,
                focus_diagram_id=self.diagram_id,
                arguments=arguments,
            )
        except (ValueError, RuntimeError) as exc:
            self.console.setPlainText(f"{action.value.title()} blocked: {exc}\n")
            self._execution_controls(False)
            return

    def _execution_controls(self, active: bool) -> None:
        self.action_run.setEnabled(not active)
        self.action_trace.setEnabled(not active)
        self.action_debug.setEnabled(not active)
        self.action_stop.setEnabled(active)

    def _preparation_changed(self, raw: object) -> None:
        if not isinstance(raw, EditorPreparedSnapshot):
            return
        project = self._client.snapshot()
        if raw.request_id != self._preparation.request_id or (raw.project_id, raw.revision) != (
            project.id,
            project.revision,
        ):
            return
        action = self._preparation.action
        if raw.status == "failed":
            if action is EditorAction.PREVIEW:
                self._execution_controls(False)
                self.code.setToolTip(
                    f"Preview blocked for revision {raw.revision}: {raw.diagnostic}"
                )
                if self._generated is None:
                    self.code.setPlainText(f"# Python preview blocked\n# {raw.diagnostic}\n")
            else:
                self.console.setPlainText(f"{action.value.title()} blocked: {raw.diagnostic}\n")
                self._execution_controls(False)
            return
        if raw.status != "ready" or raw.generated is None:
            return
        if action is EditorAction.PREVIEW and (
            self._debugger.is_active or self._run_session.is_active
        ):
            return
        self._prepared_revision = raw.revision
        self._set_generated(raw.generated)
        self._update_source_highlights()
        if action is EditorAction.PREVIEW:
            self._execution_controls(False)
        elif action is EditorAction.RUN:
            self._start_run(raw)
        elif action is EditorAction.TRACE:
            self._trace_snapshot = raw
            self._run_session.start_project_trace(
                raw.generated,
                project_revision=raw.revision,
                artifact_revision=raw.revision,
                binding_specs=raw.binding_specs,
                completed=partial(self._emit_trace, raw),
            )
        elif action is EditorAction.DEBUG:
            self._start_debug(raw)

    def _start_run(self, snapshot: EditorPreparedSnapshot) -> None:
        assert snapshot.generated is not None
        self.console.setPlainText("Running in an isolated child process…\n")
        self.debug_state_label.setText("Live run active")
        self.action_run.setEnabled(False)
        self.action_trace.setEnabled(False)
        self.action_debug.setEnabled(False)
        self.action_stop.setEnabled(True)
        self._run_session.start_project(
            snapshot.generated,
            completed=self.runCompleted.emit,
        )

    def _run_completed(self, raw_result: object) -> None:
        if not isinstance(raw_result, RunResult):
            return
        result = raw_result
        output = result.stdout
        if result.stderr:
            output += result.stderr
        if result.timed_out:
            output += "\nRun stopped after the configured timeout.\n"
        elif result.termination_reason == "stopped":
            output += "\nRun stopped by the user.\n"
        self.console.setPlainText(output or f"Process exited {result.return_code}\n")
        self.debug_state_label.setText(
            f"Live run {result.termination_reason}; exit {result.return_code}"
        )
        self.action_run.setEnabled(True)
        self.action_trace.setEnabled(True)
        self.action_debug.setEnabled(True)
        self.action_stop.setEnabled(False)

    def trace_current(self) -> None:
        self._request_execution(EditorAction.TRACE)

    def _emit_trace(self, snapshot: EditorPreparedSnapshot, result: TraceResult) -> None:
        # This completion adapter runs on the existing RunSession supervisor.
        # Qt receives a bounded preview and precomputed source locations.
        self.traceCompleted.emit(map_trace(snapshot, result))

    def _trace_completed(self, raw: object) -> None:
        if not isinstance(raw, MappedTrace) or raw.snapshot is not self._trace_snapshot:
            return
        self._trace_snapshot = None
        self._retained_trace = raw
        self._trace_delivery = raw
        self._trace_delivery_index = 0
        self.console.setPlainText(raw.console)
        self.trace_event.blockSignals(True)
        try:
            self.trace_event.clear()
            self.trace_event.addItem(
                "Select a captured trace event to inspect its full details", -1
            )
            for page in raw.output_pages:
                self.trace_event.addItem(page.label, page)
            for position, event in enumerate(raw.result.events):
                self.trace_event.addItem(
                    f"{event.index:04d} {event.event} {event.file_path}:{event.line}", position
                )
        finally:
            self.trace_event.blockSignals(False)
        self.trace_event.show()
        self.debug_details.show()
        self._show_output()
        self._set_debug_controls(False)
        self.debug_state_label.setText("Delivering captured trace events")
        self._trace_timer.start()

    def _deliver_trace_events(self) -> None:
        mapped = self._trace_delivery
        if mapped is None:
            self._trace_timer.stop()
            return
        started = perf_counter()
        count = 0
        while self._trace_delivery_index < len(mapped.result.runtime_events):
            position = self._trace_delivery_index
            self._trace_delivery_index += 1
            event = mapped.result.runtime_events[position]
            span = mapped.spans[position]
            self.executionEvent.emit(event, span.semantic_id if span is not None else "")
            if self._trace_delivery is not mapped:
                return
            count += 1
            if count >= 32 or perf_counter() - started >= 0.008:
                return
        self._trace_delivery = None
        self._trace_timer.stop()
        self._execution_controls(False)
        self.debug_state_label.setText(
            f"Trace captured from revision {mapped.snapshot.revision}; "
            f"{len(mapped.result.events)} events"
        )
        current = self._client.snapshot()
        if (current.id, current.revision) == (mapped.snapshot.project_id, mapped.snapshot.revision):
            last = next(
                (
                    span
                    for span in reversed(mapped.spans)
                    if span is not None and span.presentation_id == self.diagram_id
                ),
                None,
            )
            if last is not None:
                self.canvas.select_atoms((last.semantic_id,))

    def _trace_event_selected(self, _index: int) -> None:
        mapped = self._retained_trace
        position = self.trace_event.currentData()
        if mapped is None:
            return
        if isinstance(position, TraceOutputPage):
            self.console.setPlainText(output_page_text(mapped, position))
            self.debug_state_label.setText(
                f"Captured {position.label}; revision {mapped.snapshot.revision}"
            )
            return
        if not isinstance(position, int):
            return
        if position < 0:
            self.console.setPlainText(mapped.console)
            return
        event = mapped.result.runtime_events[position]
        self._populate_debug_details(event)
        snapshot = mapped.snapshot
        if snapshot.generated is not self._execution_generated:
            assert snapshot.generated is not None
            self._set_generated(snapshot.generated)
        current = self._client.snapshot()
        current_source = (current.id, current.revision) == (snapshot.project_id, snapshot.revision)
        if event.location is not None and self._show_source_file(event.file_path):
            self._reveal_source_line(event.line, debug=True, reveal_canvas=current_source)
        label = f"Captured trace event {position + 1}; revision {snapshot.revision}"
        if not current_source:
            label += f"; current revision {current.revision}"
        self.debug_state_label.setText(label)

    def debug_current(self) -> None:
        self._request_execution(EditorAction.DEBUG)

    def _start_debug(self, snapshot: EditorPreparedSnapshot) -> None:
        assert snapshot.generated is not None
        self.console.clear()
        self.trace_event.hide()
        self.debug_details.show()
        self._show_output()
        self.debug_state_label.setText("Debugger starting…")
        self._debugger.start(
            DebugLaunch(
                project=snapshot.generated,
                breakpoints=self._execution_breakpoints(),
                pause_on_exception=self.pause_exceptions.isChecked(),
                max_history=self._debugger.history_limit,
                project_revision=snapshot.revision,
                artifact_revision=snapshot.revision,
                binding_specs=snapshot.binding_specs,
            )
        )
        self._debug_timer.start()
        self.action_stop.setEnabled(True)
        self.action_debug.setEnabled(False)
        self._set_debug_controls(False)

    def stop_current(self) -> None:
        preparing = self._preparation.action if self._preparation.pending else None
        self._trace_timer.stop()
        self._trace_delivery = None
        self._preparation.cancel()
        stopping_run = self._run_session.stop()
        self._debugger.stop()
        self._debug_timer.stop()
        self.debug_state_label.setText("Live run stopping…" if stopping_run else "Debugger stopped")
        if not stopping_run:
            if preparing in {EditorAction.RUN, EditorAction.TRACE, EditorAction.DEBUG}:
                label = f"{preparing.value.title()} preparation stopped"
                self.console.setPlainText(f"{label} by the user.\n")
                self.debug_state_label.setText(label)
            self.action_stop.setEnabled(False)
            self.action_run.setEnabled(True)
            self.action_trace.setEnabled(True)
            self.action_debug.setEnabled(True)
        self._set_debug_controls(False)

    def _stop_child_processes(self) -> None:
        self._trace_timer.stop()
        self._trace_delivery = None
        self._retained_trace = None
        self._preparation.close()
        self._trace_snapshot = None
        self._run_session.stop()
        self._debugger.stop()

    def debug_continue(self) -> None:
        self._resume_debugger(self._debugger.continue_execution)

    def debug_step_over(self) -> None:
        self._resume_debugger(self._debugger.step_over)

    def debug_step_into(self) -> None:
        self._resume_debugger(self._debugger.step_into)

    def debug_step_out(self) -> None:
        self._resume_debugger(self._debugger.step_out)

    def debug_restart(self) -> None:
        try:
            self._debugger.restart()
        except RuntimeError:
            self.debug_current()
            return
        self.console.clear()
        self.call_stack.clear()
        self.locals.clear()
        self._debug_span = None
        self._update_source_highlights()
        self.debug_state_label.setText("Debugger restarting…")
        self._debug_timer.start()
        self.action_stop.setEnabled(True)
        self.action_debug.setEnabled(False)
        self._set_debug_controls(False)

    def _resume_debugger(self, operation: object) -> None:
        if not callable(operation):
            return
        try:
            operation()
        except RuntimeError as exc:
            self.debug_state_label.setText(str(exc))
            return
        self.debug_state_label.setText("Debugger running")
        self._set_debug_controls(False)

    def toggle_source_breakpoint(self) -> None:
        if self._generated is None:
            return
        line = self.code.textCursor().blockNumber() + 1
        location = SourceLocation(self._generated.path, line)
        if location in self._source_breakpoints:
            self._source_breakpoints.remove(location)
        else:
            self._source_breakpoints.add(location)
        self._update_source_highlights()
        if self._debugger.state is DebugState.PAUSED:
            self._debugger.set_breakpoints(self._execution_breakpoints())

    def toggle_node_breakpoint(self) -> None:
        generated = self._execution_generated
        selected = self.canvas.selected_atom_ids()
        if generated is None or not selected:
            self.debug_state_label.setText("Select a diagram node before setting a node breakpoint")
            return
        lines = {
            SourceLocation(span.file_path, span.start_line)
            for span in generated.spans
            if span.presentation_id == self.diagram_id and span.semantic_id in selected
        }
        if not lines:
            self.debug_state_label.setText("The selected node has no executable source span")
            return
        if lines <= self._source_breakpoints:
            self._source_breakpoints.difference_update(lines)
        else:
            self._source_breakpoints.update(lines)
        self._update_source_highlights()
        if self._debugger.state is DebugState.PAUSED:
            self._debugger.set_breakpoints(self._execution_breakpoints())

    def _poll_debugger(self) -> None:
        for event in self._debugger.poll_events():
            self._apply_debug_event(event)
        if not self._debugger.is_active:
            self._debug_timer.stop()

    def _apply_debug_event(self, event: DebugEvent) -> None:
        semantic_id = ""
        if event.event == "started":
            self.debug_state_label.setText("Debugger running")
        elif event.event == "output":
            cursor = self.console.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText(event.text)
            self.console.setTextCursor(cursor)
        elif event.event == "input_requested":
            self.debug_state_label.setText("Program is waiting for stdin")
        elif event.event == "paused":
            label = f"Paused: {event.reason} at {event.file_path}:{event.line} ({event.function})"
            if event.detail:
                label += f" — {event.detail}"
            current_revision = self._client.snapshot().revision
            if event.project_revision != current_revision:
                label += (
                    f" · running revision {event.project_revision}; "
                    f"project is now {current_revision}"
                )
            self.debug_state_label.setText(label)
            self._set_debug_controls(True)
            self._populate_debug_details(event)
            if event.location is not None:
                self._reveal_runtime_location(event.location)
            if self._debug_span is not None:
                semantic_id = self._debug_span.semantic_id
                self.executionSelection.emit(
                    self._debug_span.presentation_id or self.diagram_id,
                    self._debug_span.semantic_id,
                    event.project_revision,
                    event.execution_session_id,
                )
        elif event.event in {"finished", "failed", "stopped"}:
            if event.event == "finished":
                self.debug_state_label.setText(f"Debugger finished; result {event.result}")
            elif event.event == "failed":
                self.debug_state_label.setText(f"Debugger failed: {event.detail}")
                if event.traceback:
                    self.console.appendPlainText(event.traceback.rstrip())
            else:
                self.debug_state_label.setText("Debugger stopped")
            self._set_debug_controls(False)
            self._execution_controls(False)
        self.executionEvent.emit(event, semantic_id)

    def _populate_debug_details(self, event: DebugEvent) -> None:
        self.call_stack.clear()
        for frame in event.stack:
            item = QTreeWidgetItem([frame.function, frame.file_path, str(frame.line)])
            item.setData(0, Qt.ItemDataRole.UserRole, frame.location)
            self.call_stack.addTopLevelItem(item)
        self.locals.clear()
        changed = set(event.changed_locals)
        runtime = event.runtime_graph
        if runtime is None:
            for name, value in event.locals:
                item = QTreeWidgetItem([name, value, "Changed" if name in changed else ""])
                if name in changed:
                    item.setBackground(0, QColor("#ffe59a"))
                    item.setBackground(1, QColor("#ffe59a"))
                self.locals.addTopLevelItem(item)
        else:
            values = {item.value_id: item for item in runtime.values}

            def add_value(
                parent: QTreeWidgetItem,
                label: str,
                value_id: str,
                path: frozenset[str],
            ) -> None:
                value = values.get(value_id)
                if value is None:
                    parent.addChild(QTreeWidgetItem([label, "<not captured>", value_id]))
                    return
                repeated = value_id in path
                suffix = " · shared/cycle" if repeated else ""
                child_item = QTreeWidgetItem([label, value.preview, f"{value.type_id}{suffix}"])
                child_item.setToolTip(1, value.value_id)
                parent.addChild(child_item)
                if repeated:
                    return
                next_path = path | {value_id}
                for child in value.children:
                    add_value(child_item, child.label, child.value_id, next_path)
                if value.truncated:
                    child_item.addChild(
                        QTreeWidgetItem(["…", "Bounded capture truncated here", "limit"])
                    )

            for binding in runtime.bindings:
                runtime_value = values.get(binding.value_id)
                preview = runtime_value.preview if runtime_value is not None else "<not captured>"
                type_id = runtime_value.type_id if runtime_value is not None else binding.value_id
                marker = "Changed" if binding.changed else type_id
                item = QTreeWidgetItem([binding.name, preview, marker])
                item.setToolTip(1, binding.value_id)
                if binding.changed:
                    item.setBackground(0, QColor("#ffe59a"))
                    item.setBackground(1, QColor("#ffe59a"))
                self.locals.addTopLevelItem(item)
                if runtime_value is not None:
                    for child in runtime_value.children:
                        add_value(
                            item,
                            child.label,
                            child.value_id,
                            frozenset({runtime_value.value_id}),
                        )
        for name in event.removed_locals:
            self.locals.addTopLevelItem(QTreeWidgetItem([name, "<removed>", "Changed"]))

    def _set_debug_controls(self, paused: bool) -> None:
        for button in (
            self.continue_button,
            self.step_over_button,
            self.step_into_button,
            self.step_out_button,
        ):
            button.setEnabled(paused)
        self.restart_button.setEnabled(self._debugger.launch is not None)

    def _stack_frame_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        location = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(location, SourceLocation):
            self._reveal_runtime_location(location)

    def _span_at_line(self, line: int) -> SourceSpan | None:
        if self._generated is None:
            return None
        matches = [
            span for span in self._generated.spans if span.start_line <= line <= span.end_line
        ]
        if not matches:
            return None
        return min(
            matches,
            key=lambda span: (span.end_line - span.start_line, span.end_column - span.start_column),
        )

    def _reveal_source_line(
        self,
        line: int,
        *,
        debug: bool = False,
        reveal_canvas: bool = True,
    ) -> None:
        cursor = self.code.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.movePosition(
            QTextCursor.MoveOperation.Down,
            QTextCursor.MoveMode.MoveAnchor,
            max(0, line - 1),
        )
        self._mapping_selection = True
        self.code.setTextCursor(cursor)
        self.code.centerCursor()
        self._mapping_selection = False
        span = self._span_at_line(line)
        if debug:
            self._debug_span = span
        if span is not None and reveal_canvas:
            if span.presentation_id == self.diagram_id:
                self._select_canvas_semantic(span.semantic_id)
            self.atomSelected.emit(
                span.presentation_id or self.diagram_id, span.semantic_id, span.field
            )
        self._update_source_highlights()

    def _source_cursor_changed(self) -> None:
        if self._mapping_selection:
            return
        line = self.code.textCursor().blockNumber() + 1
        span = self._span_at_line(line)
        self._selected_span = span
        if span is not None:
            if span.presentation_id == self.diagram_id:
                self._select_canvas_semantic(span.semantic_id)
                self._highlight_object(self._presentation_id(span.semantic_id), reveal_source=False)
            self.atomSelected.emit(
                span.presentation_id or self.diagram_id, span.semantic_id, span.field
            )
        self._update_source_highlights()

    def _update_source_highlights(self) -> None:
        selections: list[QTextEdit.ExtraSelection] = []
        for location in self._execution_breakpoints():
            if self._generated is None or location.file_path != self._generated.path:
                continue
            selection = self._line_selection(location.line, QColor("#f7b0b0"))
            selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            selections.append(selection)
        if self._selected_span is not None:
            selections.append(self._span_selection(self._selected_span, QColor("#dcecff")))
        if self._debug_span is not None:
            selection = self._span_selection(self._debug_span, QColor("#fff08a"))
            selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            selections.append(selection)
        self.code.setExtraSelections(selections)

    def _line_selection(self, line: int, color: QColor) -> QTextEdit.ExtraSelection:
        cursor = QTextCursor(self.code.document().findBlockByNumber(max(0, line - 1)))
        selection = QTextEdit.ExtraSelection()
        selection.cursor = cursor
        selection.format.setBackground(color)
        return selection

    def _span_selection(
        self,
        span: SourceSpan | SourceSelectionRange,
        color: QColor,
    ) -> QTextEdit.ExtraSelection:
        cursor = QTextCursor(self.code.document().findBlockByNumber(span.start_line - 1))
        cursor.setPosition(cursor.block().position() + span.start_column)
        end_block = self.code.document().findBlockByNumber(span.end_line - 1)
        end = end_block.position() + min(span.end_column, max(0, end_block.length() - 1))
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        selection = QTextEdit.ExtraSelection()
        selection.cursor = cursor
        selection.format.setBackground(color)
        return selection

    def set_layout_mode(self, mode: str) -> None:
        if mode == "tabbed":
            self._set_tabbed_layout()
            self.layout_mode = mode
            self.canvas.schedule_fit()
            return
        self._set_split_layout()
        if mode == "diagram":
            self._diagram_pane.show()
            self.code.hide()
        elif mode == "code":
            self._diagram_pane.hide()
            self.code.show()
        elif mode in {"side_by_side", "stacked"}:
            self._diagram_pane.show()
            self.code.show()
            self._comparison.setOrientation(
                Qt.Orientation.Horizontal if mode == "side_by_side" else Qt.Orientation.Vertical
            )
        else:
            raise ValueError(f"Unknown document layout mode {mode!r}")
        self.layout_mode = mode
        self._restore_pane_sizes()
        self.canvas.schedule_fit()

    def _set_tabbed_layout(self) -> None:
        if self._inner_tabs is None:
            self._inner_tabs = QTabWidget()
            self._inner_tabs.setObjectName("innerDocumentViews")
        if self._view_layout.indexOf(self._comparison) >= 0:
            self._view_layout.removeWidget(self._comparison)
        self._comparison.hide()
        for pane, label in ((self._diagram_pane, "Diagram"), (self.code, "Code")):
            pane.show()
            index = self._comparison.indexOf(pane)
            if index >= 0:
                pane.setParent(None)
            if self._inner_tabs.indexOf(pane) < 0:
                self._inner_tabs.addTab(pane, label)
        if self._view_layout.indexOf(self._inner_tabs) < 0:
            self._view_layout.addWidget(self._inner_tabs)
        self._inner_tabs.show()

    def _set_split_layout(self) -> None:
        if self._inner_tabs is not None:
            current = self._inner_tabs.currentWidget()
            for pane in (self._diagram_pane, self.code):
                index = self._inner_tabs.indexOf(pane)
                if index >= 0:
                    self._inner_tabs.removeTab(index)
                self._comparison.addWidget(pane)
            self._inner_tabs.hide()
            if current is self.code:
                self.code.setFocus()
        if self._view_layout.indexOf(self._comparison) < 0:
            self._view_layout.addWidget(self._comparison)
        self._comparison.show()

    def _document(self, project: Project) -> DrakonDiagram:
        for document in project.documents:
            if isinstance(document, DrakonDiagram) and document.id == self.diagram_id:
                return document
        raise RuntimeError("The DRAKON document no longer exists")

    def _canvas_selection_changed(self, atom_id: str, field: str) -> None:
        self._highlight_object(atom_id)
        self.atomSelected.emit(self.diagram_id, atom_id, field)

    def _canvas_object_clicked(self, object_id: str) -> None:
        self._highlight_object(object_id)

    def _canvas_objects_selected(self, raw_ids: object) -> None:
        if self._mapping_selection or not isinstance(raw_ids, tuple):
            return
        object_ids = tuple(item for item in raw_ids if isinstance(item, str))
        view = self._view
        if object_ids:
            self._highlight_object(object_ids[0])
        else:
            self._selected_span = None
            self._update_source_highlights()
        self.semanticSelectionChanged.emit(
            tuple(
                view.function_id if view is not None and identity == view.header_id else identity
                for identity in object_ids
            )
        )

    def _presentation_id(self, semantic_id: str) -> str:
        view = self._view
        return (
            view.header_id if view is not None and semantic_id == view.function_id else semantic_id
        )

    def _select_canvas_semantic(self, semantic_id: str) -> None:
        mapping = self._mapping_selection
        self._mapping_selection = True
        try:
            self.canvas.select_objects((self._presentation_id(semantic_id),))
        finally:
            self._mapping_selection = mapping

    def _highlight_object(self, object_id: str, *, reveal_source: bool = True) -> None:
        if self._execution_generated is None or self._view is None:
            return
        extent = source_selection_range(
            self._execution_generated, self._view, self.canvas.selection_ownership(object_id)
        )
        if extent is None:
            self._selected_span = None
            self._update_source_highlights()
            return
        self._show_source_file(extent.file_path)
        self._selected_span = extent
        if reveal_source:
            self._reveal_source_line(extent.start_line, reveal_canvas=False)
        else:
            self._update_source_highlights()

    def reveal_semantic(self, atom_id: str) -> None:
        """Highlight a canonical operation or callable through its presentation."""

        self._select_canvas_semantic(atom_id)
        self._highlight_object(self._presentation_id(atom_id))
