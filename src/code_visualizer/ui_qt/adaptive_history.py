"""Exact cell identities and retained epochs in the existing computation workbench."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import Event
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainterPath, QPen, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from code_visualizer.application.cell_artifacts import PreparedCellProbe
from code_visualizer.application.cell_presentations import (
    CellPresentationReader,
    prepare_probe,
    supports_preview,
)
from code_visualizer.application.messages import CommandAccepted, CommandDeferred
from code_visualizer.domain.preview import PreviewEvent
from code_visualizer.domain.values import ResourceReference
from code_visualizer.extensions.foundations.cell_presentation import CellPresentation

if TYPE_CHECKING:
    from code_visualizer.application.computation_service import ComputationAttempt
    from code_visualizer.application.kernel import ProjectKernel
    from code_visualizer.extensions.registry import DomainExtensionRegistry
    from code_visualizer.persistence.resource_store import ResourceStore
    from code_visualizer.sdk import CodeVisualizerClient


@dataclass(frozen=True, slots=True)
class CellViewSource:
    resource: ResourceReference
    store: ResourceStore
    session_id: str
    input_digest: str
    revision: int
    current_source: bool
    outcome: str
    alternatives: tuple[ResourceReference, ...] = ()


@dataclass(frozen=True, slots=True)
class _Request:
    generation: int
    attachment: str
    revision: int
    source: CellViewSource
    sample: int | None
    component: str | None
    preview: PreviewEvent | None


class _Rows(QStandardItemModel):
    """Bounded native storage; painting never calls Python once per cell/role."""

    def __init__(self, headers: tuple[str, ...], parent: QTableView):
        super().__init__(0, len(headers), parent)
        self.view = parent
        self.setHorizontalHeaderLabels(headers)
        self.rows: tuple[tuple[str, ...], ...] = ()

    def replace(self, rows: tuple[tuple[str, ...], ...]) -> None:
        if self.rows == rows:
            return
        self.view.setUpdatesEnabled(False)
        try:
            self.setRowCount(len(rows))
            for row, columns in enumerate(rows):
                for column, text in enumerate(columns):
                    # Qt returns null for a newly inserted empty cell; its
                    # Python stub omits that optional return.
                    item = cast("QStandardItem | None", self.item(row, column))
                    if item is None:
                        self.setItem(row, column, QStandardItem(text))
                    elif item.text() != text:
                        item.setText(text)
            self.rows = rows
        finally:
            self.view.setUpdatesEnabled(True)


def _prepare(
    reader: CellPresentationReader,
    request: _Request,
    registry: DomainExtensionRegistry,
    cancelled: Event,
) -> CellPresentation:
    source, root = request.source, request.source.resource
    return reader.prepare(
        root,
        source.store,
        registry,
        (source.store, source.session_id, source.input_digest, request.attachment),
        request.sample,
        request.component,
        preview=request.preview,
        session_id=source.session_id,
        input_digest=source.input_digest,
        cancelled=cancelled.is_set,
        alternatives=source.alternatives,
    )


class CellHistoryPanel(QWidget):
    """One active task and one replaceable request; no resource I/O in GUI handlers."""

    modelCreated = Signal(str)
    loaded = Signal()
    failed = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("cellHistoryPanel")
        self._kernel: ProjectKernel | None = None
        self._client: CodeVisualizerClient | None = None
        self._source: CellViewSource | None = None
        self._preview: PreviewEvent | None = None
        self._generation = 0
        self._active: _Request | None = None
        self._pending: _Request | None = None
        self._future: Future[object] | None = None
        self._editing = self._closed = False
        self._cancel = Event()
        self._reader = CellPresentationReader()
        self.presentation: CellPresentation | None = None
        self.selected_cell: str | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cell-history")
        self.destroyed.connect(self.shutdown)
        self._timer, self._playback = QTimer(self), QTimer(self)
        self._timer.setInterval(20)
        self._timer.timeout.connect(self._poll)
        self._playback.setInterval(100)
        self._playback.timeout.connect(self._play_next)
        layout = QVBoxLayout(self)
        self.status = QLabel("Select a retained cell history or checkpoint.")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        bar = QHBoxLayout()
        self.follow = QCheckBox("Follow published samples")
        self.follow.setChecked(True)
        self.follow.toggled.connect(self._request)
        bar.addWidget(self.follow)
        self.component = QComboBox()
        self.component.currentIndexChanged.connect(self._request)
        bar.addWidget(self.component, 1)
        self.play = QPushButton("Play retained samples")
        self.play.clicked.connect(self._toggle_play)
        bar.addWidget(self.play)
        self.speed = QSpinBox()
        self.speed.setRange(40, 2000)
        self.speed.setValue(100)
        self.speed.setSuffix(" ms/sample")
        self.speed.valueChanged.connect(self._playback.setInterval)
        bar.addWidget(self.speed)
        layout.addLayout(bar)
        self.time_cursor = QSlider(Qt.Orientation.Horizontal)
        self.time_cursor.setObjectName("cellHistoryCursor")
        self.time_cursor.setEnabled(False)
        self.time_cursor.valueChanged.connect(self._scrub)
        layout.addWidget(self.time_cursor)
        self.accepted_label = QLabel("No retained sample selected.")
        self.accepted_label.setWordWrap(True)
        layout.addWidget(self.accepted_label)
        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene)
        self.view.setMinimumHeight(170)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        layout.addWidget(self.view)
        self.table = QTableView()
        self._cells = _Rows(("Cell identity", "Left", "Right", "Level", "Average"), self.table)
        self.table.setModel(self._cells)
        self.table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.selectionModel().selectionChanged.connect(self._cell_selected)
        self.table.setMinimumHeight(190)
        layout.addWidget(self.table)
        self.selection_label = QLabel("Select an exact cell to create a probe.")
        self.selection_label.setWordWrap(True)
        layout.addWidget(self.selection_label)
        self.decisions = QLabel("No mesh changes in this retained prefix.")
        self.decisions.setWordWrap(True)
        layout.addWidget(self.decisions)
        self.trial_label = QLabel("No provisional candidate for this source.")
        self.trial_label.setWordWrap(True)
        layout.addWidget(self.trial_label)
        self.trial_table = QTableView()
        self._trials = _Rows(("State", "Cell identity", "Level", "Average"), self.trial_table)
        self.trial_table.setModel(self._trials)
        self.trial_table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.trial_table.setMaximumHeight(160)
        layout.addWidget(self.trial_table)
        actions = QHBoxLayout()
        self.select = QPushButton("Select field source")
        self.select.clicked.connect(self._select_source)
        actions.addWidget(self.select)
        self.probe = QPushButton("Create exact cell probe")
        self.probe.setEnabled(False)
        self.probe.clicked.connect(self._create_probe)
        actions.addWidget(self.probe)
        layout.addLayout(actions)

    @property
    def pending_tasks(self) -> int:
        return int(self._future is not None) + int(self._pending is not None)

    def attach(self, kernel: ProjectKernel | None, client: CodeVisualizerClient | None) -> None:
        self._generation += 1
        self._cancel.set()
        self._pending = None
        self._playback.stop()
        self.play.setText("Play retained samples")
        self._kernel, self._client = kernel, client
        self._source, self._preview, self.presentation = None, None, None
        self.selected_cell = None
        self.scene.clear()
        self.component.blockSignals(True)
        self.component.clear()
        self.component.blockSignals(False)
        self._cells.replace(())
        self._trials.replace(())
        self.time_cursor.setEnabled(False)
        self.probe.setEnabled(False)
        self.status.setText("Select a retained cell history or checkpoint.")
        self.accepted_label.setText("No retained sample selected.")
        self.trial_label.setText("No provisional candidate for this source.")
        self.selection_label.setText("Select an exact cell to create a probe.")
        self.decisions.setText("No mesh changes in this retained prefix.")

    def inspect(self, source: CellViewSource) -> None:
        if self._source == source:
            return
        if self._source is None or (self._source.session_id, self._source.input_digest) != (
            source.session_id,
            source.input_digest,
        ):
            self._preview, self.selected_cell = None, None
            self.component.blockSignals(True)
            self.component.clear()
            self.component.blockSignals(False)
            self.follow.blockSignals(True)
            self.follow.setChecked(True)
            self.follow.blockSignals(False)
        self._source = source
        self._request()

    def observe_attempt(self, attempt: ComputationAttempt) -> None:
        kernel = self._kernel
        if (
            kernel is None
            or attempt.preview is None
            or not supports_preview(attempt.preview)
            or not attempt.publications
        ):
            return
        publication = kernel.computations.publication(attempt.publications[-1])
        store = kernel.computations.job(attempt.session.id).resource_store
        if publication is None or store is None:
            return
        alternatives = tuple(
            prior.artifact.resource
            for identity in reversed(attempt.publications[:-1])
            if (prior := kernel.computations.publication(identity)) is not None
        )
        self.inspect(
            CellViewSource(
                publication.artifact.resource,
                store,
                attempt.session.id,
                publication.provenance.input_digest,
                attempt.session.revision,
                attempt.attachment_id == kernel.computation_attachment.id
                and attempt.session.revision == kernel.revision,
                attempt.session.status.value,
                alternatives,
            )
        )
        self.preview(attempt.preview)

    def preview(self, event: PreviewEvent) -> None:
        source = self._source
        if (
            source is None
            or not supports_preview(event)
            or event.session_id != source.session_id
            or event.input_digest != source.input_digest
            or (self._preview is not None and event.sequence <= self._preview.sequence)
        ):
            return
        self._preview = event
        self._request()

    def _scrub(self, _value: int) -> None:
        self.follow.blockSignals(True)
        self.follow.setChecked(False)
        self.follow.blockSignals(False)
        self._request()

    def _toggle_play(self) -> None:
        if self._playback.isActive():
            self._playback.stop()
            self.play.setText("Play retained samples")
        elif self.presentation is not None:
            if self.time_cursor.value() == self.time_cursor.maximum():
                self.time_cursor.setValue(0)
            self._playback.start()
            self.play.setText("Pause playback")

    def _play_next(self) -> None:
        if self.time_cursor.value() < self.time_cursor.maximum():
            self.time_cursor.setValue(self.time_cursor.value() + 1)
        else:
            self._playback.stop()
            self.play.setText("Play retained samples")

    def _request(self, _value: object = None) -> None:
        if self._source is None or self._kernel is None or self._closed or self._editing:
            return
        self._generation += 1
        self._pending = _Request(
            self._generation,
            self._kernel.computation_attachment.id,
            self._kernel.revision,
            self._source,
            None if self.follow.isChecked() else self.time_cursor.value(),
            self.component.currentData(),
            self._preview,
        )
        self._cancel.set()
        self._start_pending()

    def _start_pending(self) -> None:
        if self._future is not None or self._pending is None or self._kernel is None:
            return
        self._active, self._pending = self._pending, None
        self._cancel = Event()
        self._future = self._executor.submit(
            _prepare,
            self._reader,
            self._active,
            self._kernel.extensions,
            self._cancel,
        )
        self._timer.start()

    def _poll(self) -> None:
        future, active, kernel = self._future, self._active, self._kernel
        if future is None or not future.done():
            return
        self._future = None
        self._timer.stop()
        editing, self._editing = self._editing, False
        valid = bool(
            kernel
            and active
            and active.attachment == kernel.computation_attachment.id
            and active.revision == kernel.revision
            and active.generation == self._generation
        )
        error = future.exception()
        if error is not None:
            if valid and not isinstance(error, InterruptedError):
                self.status.setText(str(error))
                self.failed.emit(str(error))
        elif valid:
            result = future.result()
            if isinstance(result, CellPresentation):
                self.presentation = result
                self._draw(result)
                self.loaded.emit()
            elif isinstance(result, PreparedCellProbe) and self._client is not None:
                accepted = self._client.transaction(
                    result.commands,
                    expected_revision=result.revision,
                    intent="Author an exact retained cell consumer",
                )
                if isinstance(accepted, CommandAccepted):
                    self.status.setText(
                        "Exact cell probe authored. Select its model and Freeze & Run."
                    )
                    self.modelCreated.emit(result.model_id)
                elif isinstance(accepted, CommandDeferred):
                    self.status.setText("Forking the frozen definition before accepting the probe.")
                else:
                    self.status.setText(accepted.message)
        if editing:
            self._selection_status()
        self._start_pending()

    def _draw(self, value: CellPresentation) -> None:
        source = self._source
        assert source is not None
        self.component.blockSignals(True)
        self.component.clear()
        for item in value.components:
            self.component.addItem(item.id, item.id)
        self.component.setCurrentIndex(self.component.findData(value.component_id))
        self.component.blockSignals(False)
        self.time_cursor.blockSignals(True)
        self.time_cursor.setRange(0, value.sample_count - 1)
        self.time_cursor.setValue(value.selected.sample)
        self.time_cursor.setEnabled(True)
        self.time_cursor.blockSignals(False)
        component = next(c for c in value.components if c.id == value.component_id)
        self.status.setText(
            f"{source.outcome}; revision {source.revision}; "
            + ("current authoring" if source.current_source else "historical source")
            + f"\nAttempt {source.session_id}; input {source.input_digest}"
            + f"\nDefinition {value.definition_digest}; history {value.resource.content_hash}"
        )
        self.accepted_label.setText(
            f"Retained sample {value.selected.sample} of {value.sample_count}; "
            f"step {value.selected.step}; t={value.selected.time.magnitude:.9g} "
            f"{value.selected.time.unit.id}; mesh epoch {value.epoch}; {len(value.cells)} cells. "
            f"Cell averages in {component.unit.id} ({component.quantity_kind.value}); "
            f"positions in {value.support.length.unit.id}, frame {value.support.frame_id}. "
            f"{value.support.interpretation}. "
            "Playback uses exact samples and their own partitions. " + " ".join(value.annotations)
        )
        self.table.blockSignals(True)
        self._cells.replace(
            tuple(
                (
                    cell.id,
                    f"{cell.left:.9g}",
                    f"{cell.right:.9g}",
                    str(cell.level),
                    f"{cell.value:.10g}",
                )
                for cell in value.cells
            )
        )
        self.table.clearSelection()
        for row, cell in enumerate(value.cells):
            if cell.id == self.selected_cell:
                self.table.selectRow(row)
        self.table.blockSignals(False)
        self._selection_status()
        self.scene.clear()
        low = min(c.value for c in value.cells)
        high = max(c.value for c in value.cells)
        length = value.cells[-1].right
        path = QPainterPath()
        ticks = QPainterPath()
        for i, cell in enumerate(value.cells):
            left, right = 10 + 580 * cell.left / length, 10 + 580 * cell.right / length
            height = 120 - 100 * (cell.value - low) / (high - low if high > low else 1)
            if i:
                path.lineTo(left, height)
            else:
                path.moveTo(left, height)
            path.lineTo(right, height)
            ticks.moveTo(left, 126)
            ticks.lineTo(left, 130 + 4 * cell.level)
        self.scene.addPath(ticks, QPen(QColor("#777777")))
        self.scene.addPath(path, QPen(QColor("#187ca1"), 1.5))
        self.scene.addText(f"0 .. {length:g}; average {low:.7g} .. {high:.7g}").setPos(10, 145)
        self.scene.setSceneRect(0, 0, 610, 172)
        self.decisions.setText(
            "Retained mesh decisions: "
            + "; ".join(
                f"step {d.step}: epoch {d.epoch}, {d.cells} cells, "
                f"split {d.refined}, merged {d.coarsened}"
                for d in value.decisions
            )
            if value.decisions
            else "No mesh changes in this retained prefix."
        )
        trial = value.preview
        if trial is None:
            self._trials.replace(())
            self.trial_label.setText("No provisional candidate for this source.")
            return
        self.trial_label.setText(
            f"Provisional candidate pending publication: step {trial.base.step} "
            + ("(base retained)" if value.base_retained else "(base not in this retained prefix)")
            + f" to {trial.candidate.step}; epochs {trial.base.epoch} to {trial.candidate.epoch}. "
            "Numerical checks passed; host retention is not yet established. "
            "Base and candidate each show their own cell identities."
        )
        trial_rows = []
        for label, frame in (("Base", trial.base), ("Candidate", trial.candidate)):
            for cell in frame.cells:
                trial_rows.append((label, cell.id, str(cell.level), f"{cell.value:.10g}"))
        self._trials.replace(tuple(trial_rows))

    def _cell_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if rows and self.presentation:
            self.selected_cell = self.presentation.cells[rows[0].row()].id
        self._selection_status()

    def _selection_status(self) -> None:
        value = self.presentation
        available = bool(value and self.selected_cell in {c.id for c in value.cells})
        self.probe.setEnabled(available and self._client is not None and not self._editing)
        if self.selected_cell is None:
            self.selection_label.setText("Select an exact cell to create a probe.")
        elif not available:
            self.selection_label.setText(
                f"Selected cell {self.selected_cell} is absent in this mesh epoch. "
                "Select an existing cell explicitly; its array position is not a replacement."
            )
        else:
            self.selection_label.setText(f"Selected cell: {self.selected_cell}")

    def _select_source(self) -> None:
        kernel, source, value = self._kernel, self._source, self.presentation
        if (
            kernel
            and source
            and value
            and source.current_source
            and source.revision == kernel.revision
        ):
            component = next(c for c in value.components if c.id == value.component_id)
            kernel.selection.select(
                (component.field_id, value.support.region_id),
                revision=source.revision,
                source="cell-history",
            )

    def _create_probe(self) -> None:
        kernel, source, value = self._kernel, self._source, self.presentation
        if (
            kernel is None
            or source is None
            or value is None
            or self._client is None
            or self._future is not None
            or kernel.resource_store is None
            or self.selected_cell not in {c.id for c in value.cells}
        ):
            return
        self._generation += 1
        self._pending = None
        self._active = _Request(
            self._generation,
            kernel.computation_attachment.id,
            kernel.revision,
            source,
            value.selected.sample,
            value.component_id,
            None,
        )
        self._editing = True
        self.probe.setEnabled(False)
        self._future = self._executor.submit(
            prepare_probe,
            self._client.snapshot(),
            kernel.extensions,
            source.store,
            kernel.resource_store,
            value.resource,
            value.selected.sample,
            value.epoch,
            self.selected_cell,
            value.component_id,
        )
        self._timer.start()

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._cancel.set()
        self._timer.stop()
        self._playback.stop()
        self._pending = None
        self._executor.submit(self._reader.close)
        self._executor.shutdown(wait=False)
