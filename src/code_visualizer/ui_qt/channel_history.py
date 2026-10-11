"""Retained channel evidence and separately labelled trials in the existing workbench."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import Event
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainterPath, QPen
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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from code_visualizer.application.channel_artifacts import PreparedChannelProbe, prepare_probe
from code_visualizer.application.messages import CommandAccepted, CommandDeferred
from code_visualizer.domain.preview import PreviewEvent
from code_visualizer.domain.values import ResourceReference
from code_visualizer.extensions.channels.presentation import (
    ChannelPresentation,
    ChannelPresentationReader,
)
from code_visualizer.extensions.channels.preview import PREVIEW_TYPE
from code_visualizer.extensions.channels.records import SERIES_TYPE
from code_visualizer.persistence.computation_resources import resolve_computation_resource

if TYPE_CHECKING:
    from code_visualizer.application.computation_service import ComputationAttempt
    from code_visualizer.application.kernel import ProjectKernel
    from code_visualizer.extensions.registry import DomainExtensionRegistry
    from code_visualizer.persistence.resource_store import ResourceStore
    from code_visualizer.sdk import CodeVisualizerClient


@dataclass(frozen=True, slots=True)
class ChannelViewSource:
    resource: ResourceReference
    store: ResourceStore
    session_id: str
    input_digest: str
    revision: int
    current_source: bool
    outcome: str


@dataclass(frozen=True, slots=True)
class _Request:
    generation: int
    attachment: str
    revision: int
    source: ChannelViewSource
    sample: int | None
    channel: str | None
    preview: PreviewEvent | None


def _prepare(
    reader: ChannelPresentationReader,
    request: _Request,
    registry: DomainExtensionRegistry,
    cancelled: Event,
) -> ChannelPresentation:
    source, root = request.source, request.source.resource
    descriptor = source.store.describe(root)
    if descriptor.logical_type != SERIES_TYPE:
        interpreter = (
            registry.resource_interpretation(descriptor.logical_type)
            if descriptor.logical_type
            else None
        )
        if interpreter is None or descriptor.byte_size > interpreter.metadata_limit:
            raise ValueError("Select a retained channel series or checkpoint containing one")
        series = tuple(
            d.reference
            for d in interpreter.dependencies(source.store.read(root))
            if d.logical_type == SERIES_TYPE
        )
        if len(series) != 1:
            raise ValueError("This artifact does not contain one channel history")
        root = series[0]
    return reader.prepare(
        root,
        lambda ref: resolve_computation_resource(source.store, ref, file_backed=True),
        (source.store, source.session_id, request.attachment),
        request.sample,
        request.channel,
        preview=request.preview,
        session_id=source.session_id,
        input_digest=source.input_digest,
        cancelled=cancelled.is_set,
    )


class ChannelHistoryPanel(QWidget):
    """One active worker and one replaceable request; all resource work is off the GUI."""

    modelCreated = Signal(str)
    loaded = Signal()
    failed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("channelHistoryPanel")
        self._kernel: ProjectKernel | None = None
        self._client: CodeVisualizerClient | None = None
        self._source: ChannelViewSource | None = None
        self._preview: PreviewEvent | None = None
        self._generation = 0
        self._active: _Request | None = None
        self._pending: _Request | None = None
        self._future: Future[object] | None = None
        self._editing = self._closed = False
        self._cancel = Event()
        self._reader = ChannelPresentationReader()
        self.presentation: ChannelPresentation | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="channel-view")
        self.destroyed.connect(self.shutdown)
        self._timer, self._playback = QTimer(self), QTimer(self)
        self._timer.setInterval(20)
        self._timer.timeout.connect(self._poll)
        self._playback.setInterval(100)
        self._playback.timeout.connect(self._play_next)
        layout = QVBoxLayout(self)
        self.status = QLabel("Select a retained channel history or a coupled checkpoint.")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        bar = QHBoxLayout()
        self.follow = QCheckBox("Follow published samples")
        self.follow.setChecked(True)
        self.follow.toggled.connect(self._request)
        bar.addWidget(self.follow)
        self.channel = QComboBox()
        self.channel.setObjectName("historyChannel")
        self.channel.currentIndexChanged.connect(self._request)
        bar.addWidget(self.channel, 1)
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
        self.time_cursor.setObjectName("channelHistoryCursor")
        self.time_cursor.valueChanged.connect(self._scrub)
        self.time_cursor.setEnabled(False)
        layout.addWidget(self.time_cursor)
        self.accepted_label = QLabel("No retained sample selected.")
        self.accepted_label.setWordWrap(True)
        layout.addWidget(self.accepted_label)
        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene)
        self.view.setObjectName("channelTimePlot")
        self.view.setMinimumHeight(170)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        layout.addWidget(self.view)
        self.table = QTableWidget(0, 4)
        self.table.setObjectName("retainedChannelValues")
        self.table.setHorizontalHeaderLabels(
            ["Channel", "Retained value", "Unit / kind", "Support"]
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._table_selected)
        self.table.setMinimumHeight(190)
        layout.addWidget(self.table)
        self.trial_label = QLabel("No provisional trial for this source.")
        self.trial_label.setWordWrap(True)
        layout.addWidget(self.trial_label)
        self.trial_table = QTableWidget(0, 4)
        self.trial_table.setObjectName("provisionalChannelValues")
        self.trial_table.setHorizontalHeaderLabels(
            ["Channel", "Numerical base", "Trial", "Unit / kind"]
        )
        self.trial_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.trial_table.setMaximumHeight(160)
        layout.addWidget(self.trial_table)
        actions = QHBoxLayout()
        self.select = QPushButton("Select channel source")
        self.select.clicked.connect(self._select_source)
        actions.addWidget(self.select)
        self.probe = QPushButton("Create exact probe")
        self.probe.setObjectName("createChannelProbe")
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
        self.scene.clear()
        self.channel.blockSignals(True)
        self.channel.clear()
        self.channel.blockSignals(False)
        self.table.setRowCount(0)
        self.trial_table.setRowCount(0)
        self.time_cursor.setEnabled(False)
        self.probe.setEnabled(False)
        self.status.setText("Select a retained channel history or a coupled checkpoint.")
        self.accepted_label.setText("No retained sample selected.")
        self.trial_label.setText("No provisional trial for this source.")

    def inspect(self, source: ChannelViewSource) -> None:
        if self._source == source:
            return
        if self._source is None or (self._source.session_id, self._source.input_digest) != (
            source.session_id,
            source.input_digest,
        ):
            self._preview = None
            self.channel.blockSignals(True)
            self.channel.clear()
            self.channel.blockSignals(False)
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
            or attempt.preview.interpretation != PREVIEW_TYPE
        ):
            return
        if not attempt.publications:
            return
        publication = kernel.computations.publication(attempt.publications[-1])
        store = kernel.computations.job(attempt.session.id).resource_store
        if publication is None or store is None:
            return
        self.inspect(
            ChannelViewSource(
                publication.artifact.resource,
                store,
                attempt.session.id,
                publication.provenance.input_digest,
                attempt.session.revision,
                attempt.attachment_id == kernel.computation_attachment.id
                and attempt.session.revision == kernel.revision,
                attempt.session.status.value,
            )
        )
        self.preview(attempt.preview)

    def preview(self, event: PreviewEvent) -> None:
        source = self._source
        if (
            source is None
            or event.interpretation != PREVIEW_TYPE
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
            self.channel.currentData(),
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
            _prepare, self._reader, self._active, self._kernel.extensions, self._cancel
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
            if isinstance(result, ChannelPresentation):
                previous = self.presentation
                self.presentation = result
                self._draw(result, previous)
                self.loaded.emit()
            elif isinstance(result, PreparedChannelProbe) and self._client is not None:
                accepted = self._client.transaction(
                    result.commands,
                    expected_revision=result.revision,
                    intent="Author an exact retained channel consumer",
                )
                if isinstance(accepted, CommandAccepted):
                    self.status.setText("Exact probe authored. Select its model and Freeze & Run.")
                    self.modelCreated.emit(result.model_id)
                elif isinstance(accepted, CommandDeferred):
                    self.status.setText("Forking the frozen definition before accepting the probe.")
                else:
                    self.status.setText(accepted.message)
        if editing:
            self.probe.setEnabled(self.presentation is not None and self._client is not None)
        self._start_pending()

    @staticmethod
    def _cell(table: QTableWidget, row: int, column: int, text: str) -> None:
        item = table.item(row, column)
        if item is None:
            table.setItem(row, column, QTableWidgetItem(text))
        elif item.text() != text:
            item.setText(text)

    def _draw(
        self, value: ChannelPresentation, previous: ChannelPresentation | None = None
    ) -> None:
        source = self._source
        assert source is not None
        channels = value.interpretation.channels
        meaning_changed = previous is None or previous.interpretation != value.interpretation
        self.channel.blockSignals(True)
        if meaning_changed:
            self.channel.clear()
            for channel in channels:
                self.channel.addItem(channel.name, channel.id)
        self.channel.setCurrentIndex(self.channel.findData(value.channel_id))
        self.channel.blockSignals(False)
        self.time_cursor.blockSignals(True)
        self.time_cursor.setRange(0, value.sample_count - 1)
        self.time_cursor.setValue(value.selected.sample)
        self.time_cursor.setEnabled(True)
        self.time_cursor.blockSignals(False)
        self.probe.setEnabled(self._client is not None)
        self.status.setText(
            f"{source.outcome}; revision {source.revision}; "
            + ("current authoring" if source.current_source else "historical source")
            + f"\nAttempt {source.session_id}; input {source.input_digest}"
            + f"\nDefinition {value.definition_digest}; series {value.resource.content_hash}"
        )
        self.accepted_label.setText(
            f"Retained accepted sample {value.selected.sample} of {value.sample_count}; "
            f"window {value.selected.step}, t={value.selected.time.magnitude:.9g} "
            f"{value.selected.time.unit.id}. Playback selects exact samples. "
            "The curve preserves bin extrema; no temporal interpolation."
        )
        self.table.blockSignals(True)
        self.table.setRowCount(len(channels))
        for row, (channel, number) in enumerate(zip(channels, value.values, strict=True)):
            for col, text in enumerate(
                (
                    channel.name,
                    f"{number:.10g}",
                    channel.unit.id + " / " + channel.quantity_kind.value,
                    channel.support_id,
                )
            ):
                self._cell(self.table, row, col, text)
        self.table.selectRow(self.channel.currentIndex())
        if meaning_changed:
            self.table.resizeColumnsToContents()
        self.table.blockSignals(False)
        curve_changed = (
            meaning_changed
            or previous is None
            or previous.curve != value.curve
            or previous.channel_id != value.channel_id
        )
        if curve_changed:
            self.scene.clear()
        if curve_changed and value.curve:
            times, numbers = zip(*value.curve, strict=True)
            lo, hi, start, end = min(numbers), max(numbers), min(times), max(times)
            path = QPainterPath()
            for i, (time, number) in enumerate(value.curve):
                x = 10 + 580 * (time - start) / (end - start if end > start else 1)
                y = 120 - 100 * (number - lo) / (hi - lo if hi > lo else 1)
                if i:
                    path.lineTo(x, y)
                else:
                    path.moveTo(x, y)
            self.scene.addPath(path, QPen(QColor("#187ca1"), 1.5))
            self.scene.addText(
                f"{start:g} .. {end:g} {value.selected.time.unit.id}; {lo:.7g} .. {hi:.7g}"
            ).setPos(10, 130)
            self.scene.setSceneRect(0, 0, 610, 160)
        trial = value.preview
        if trial is None:
            self.trial_table.setRowCount(0)
            self.trial_label.setText("No provisional trial for this source.")
            return
        self.trial_label.setText(
            f"Provisional iteration {trial.iteration}: numerical base window {trial.base_step}, "
            f"t={trial.base_time.magnitude:.9g} "
            + ("(retained)" if value.base_retained else "(not in this retained prefix)")
            + f" → candidate window {trial.candidate_step}, t={trial.candidate_time.magnitude:.9g} "
            + f"{trial.candidate_time.unit.id}. "
            + "Trial values do not advance retained time or energy."
        )
        self.trial_table.setRowCount(len(trial.indices.elements))
        for row, (index, base, candidate) in enumerate(
            zip(
                trial.indices.elements,
                trial.base_values.elements,
                trial.trial_values.elements,
                strict=True,
            )
        ):
            channel = channels[cast(int, index)]
            for col, text in enumerate(
                (
                    channel.name,
                    f"{base:.10g}",
                    f"{candidate:.10g}",
                    channel.unit.id + " / " + channel.quantity_kind.value,
                )
            ):
                self._cell(self.trial_table, row, col, text)
        if (
            meaning_changed
            or previous is None
            or previous.preview is None
            or previous.preview.indices != trial.indices
        ):
            self.trial_table.resizeColumnsToContents()

    def _table_selected(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < self.channel.count():
            self.channel.setCurrentIndex(row)

    def _select_source(self) -> None:
        kernel, source, value = self._kernel, self._source, self.presentation
        if (
            kernel
            and source
            and value
            and source.current_source
            and source.revision == kernel.revision
        ):
            channel = next(c for c in value.interpretation.channels if c.id == value.channel_id)
            kernel.selection.select(
                channel.semantic_ids, revision=source.revision, source="channel-history"
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
            value.channel_id,
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
            value.channel_id,
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
