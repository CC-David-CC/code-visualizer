"""Coherent accepted history and provisional trials in the existing computation UI."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import Event
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from code_visualizer.application.field_artifacts import PreparedFieldProbe, prepare_probe
from code_visualizer.application.messages import CommandAccepted, CommandDeferred
from code_visualizer.domain.preview import PreviewEvent
from code_visualizer.domain.values import ResourceReference
from code_visualizer.extensions.fields.presentation import (
    FieldPresentation,
    FieldPresentationReader,
)
from code_visualizer.extensions.fields.records import PREVIEW_TYPE, SERIES_TYPE
from code_visualizer.persistence.computation_resources import resolve_computation_resource

if TYPE_CHECKING:
    from code_visualizer.application.computation_service import ComputationAttempt
    from code_visualizer.application.kernel import ProjectKernel
    from code_visualizer.extensions.registry import DomainExtensionRegistry
    from code_visualizer.persistence.resource_store import ResourceStore
    from code_visualizer.sdk import CodeVisualizerClient


@dataclass(frozen=True, slots=True)
class FieldViewSource:
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
    source: FieldViewSource
    sample: int | None
    overview: bool
    preview: PreviewEvent | None


def _prepare(
    reader: FieldPresentationReader,
    request: _Request,
    registry: DomainExtensionRegistry,
    cancelled: Event,
) -> FieldPresentation:
    source, root = request.source, request.source.resource
    descriptor = source.store.describe(root)
    if descriptor.logical_type != SERIES_TYPE:
        interpretation = (
            registry.resource_interpretation(descriptor.logical_type)
            if descriptor.logical_type
            else None
        )
        if interpretation is None or descriptor.byte_size > interpretation.metadata_limit:
            raise ValueError(
                "Select an immutable field-series artifact or a checkpoint containing one"
            )
        dependencies = interpretation.dependencies(source.store.read(root))
        series = [item.reference for item in dependencies if item.logical_type == SERIES_TYPE]
        if len(series) != 1:
            raise ValueError("This artifact does not identify one field history")
        root = series[0]
    return reader.prepare(
        root,
        lambda ref: resolve_computation_resource(source.store, ref, file_backed=True),
        source.store,
        request.sample,
        overview=request.overview,
        preview=request.preview,
        session_id=source.session_id,
        input_digest=source.input_digest,
        cancelled=cancelled.is_set,
    )


class FieldHistoryPanel(QWidget):
    """At most one active task and one replaceable pending view request."""

    modelCreated = Signal(str)
    loaded = Signal()
    failed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("fieldHistoryPanel")
        self._kernel: ProjectKernel | None = None
        self._client: CodeVisualizerClient | None = None
        self._source: FieldViewSource | None = None
        self._preview: PreviewEvent | None = None
        self._generation = 0
        self._pending: _Request | None = None
        self._active: _Request | None = None
        self._future: Future[object] | None = None
        self._cancel = Event()
        self._reader = FieldPresentationReader()
        self.presentation: FieldPresentation | None = None
        self._editing = False
        self._closed = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="field-view")
        self.destroyed.connect(self.shutdown)
        self._timer = QTimer(self)
        self._timer.setInterval(20)
        self._timer.timeout.connect(self._poll)
        self._playback = QTimer(self)
        self._playback.setInterval(100)
        self._playback.timeout.connect(self._play_next)
        layout = QVBoxLayout(self)
        self.status = QLabel("Select a sealed field history to inspect accepted samples.")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setObjectName("fieldHistoryStatus")
        layout.addWidget(self.status)
        bar = QHBoxLayout()
        self.follow = QCheckBox("Follow published history")
        self.follow.setChecked(True)
        self.follow.toggled.connect(self._request)
        bar.addWidget(self.follow)
        self.overview = QCheckBox("Load time overview")
        self.overview.toggled.connect(self._request)
        bar.addWidget(self.overview)
        self.play = QPushButton("Play retained samples")
        self.play.clicked.connect(self._toggle_play)
        bar.addWidget(self.play)
        self.node = QSpinBox()
        self.node.setObjectName("fieldProbeNode")
        bar.addWidget(QLabel("Probe node"))
        bar.addWidget(self.node)
        self.probe = QPushButton("Create exact probe")
        self.probe.setObjectName("createFieldProbe")
        self.probe.clicked.connect(self._create_probe)
        self.probe.setEnabled(False)
        bar.addWidget(self.probe)
        self.select = QPushButton("Select source field")
        self.select.clicked.connect(self._select_field)
        bar.addWidget(self.select)
        layout.addLayout(bar)
        self.time_cursor = QSlider(Qt.Orientation.Horizontal)
        self.time_cursor.setObjectName("fieldHistoryCursor")
        self.time_cursor.setEnabled(False)
        self.time_cursor.valueChanged.connect(self._scrub)
        layout.addWidget(self.time_cursor)
        self.accepted_label = QLabel("No selected accepted sample.")
        self.accepted_label.setObjectName("fieldAcceptedState")
        self.accepted_label.setWordWrap(True)
        layout.addWidget(self.accepted_label)
        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene)
        self.view.setObjectName("fieldProfileView")
        self.view.setMinimumHeight(180)
        layout.addWidget(self.view)
        self.trial_label = QLabel("No provisional trial.")
        self.trial_label.setObjectName("fieldTrialState")
        self.trial_label.setWordWrap(True)
        layout.addWidget(self.trial_label)
        self.trial_scene = QGraphicsScene(self)
        self.trial_view = QGraphicsView(self.trial_scene)
        self.trial_view.setMinimumHeight(120)
        layout.addWidget(self.trial_view)
        self.heatmap = QLabel()
        self.heatmap.setObjectName("fieldTimeOverview")
        layout.addWidget(self.heatmap)

    @property
    def pending_tasks(self) -> int:
        return int(self._future is not None) + int(self._pending is not None)

    def attach(self, kernel: ProjectKernel | None, client: CodeVisualizerClient | None) -> None:
        self._playback.stop()
        self.play.setText("Play retained samples")
        self._generation += 1
        self._cancel.set()
        self._pending = None
        self._kernel, self._client = kernel, client
        self._source, self._preview, self.presentation = None, None, None
        self.scene.clear()
        self.trial_scene.clear()
        self.heatmap.clear()
        self.probe.setEnabled(False)
        self.time_cursor.setEnabled(False)
        self.accepted_label.setText("No selected accepted sample.")
        self.trial_label.setText("No provisional trial.")

    def inspect(self, source: FieldViewSource) -> None:
        if self._source == source:
            return
        if self._source is None or (self._source.session_id, self._source.input_digest) != (
            source.session_id,
            source.input_digest,
        ):
            self._preview = None
            self.follow.setChecked(True)
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
        publications = attempt.publications
        if not publications:
            return
        publication = kernel.computations.publication(publications[-1])
        store = kernel.computations.job(attempt.session.id).resource_store
        if publication is None or store is None:
            return
        self.inspect(
            FieldViewSource(
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

    def preview(self, event: PreviewEvent | None) -> None:
        if event is None or self._source is None or event.interpretation != PREVIEW_TYPE:
            return
        source = self._source
        if (
            event.session_id != source.session_id
            or event.input_digest != source.input_digest
            or (self._preview is not None and event.sequence <= self._preview.sequence)
        ):
            return
        self._preview = event  # one slot, never history or a semantic command
        if not self._editing:
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

    def _request(self, _checked: bool = False) -> None:
        if self._source is None or self._kernel is None or self._closed or self._editing:
            return
        self._generation += 1
        self._pending = _Request(
            self._generation,
            self._kernel.computation_attachment.id,
            self._kernel.revision,
            self._source,
            None if self.follow.isChecked() else self.time_cursor.value(),
            self.overview.isChecked(),
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
        try:
            # Re-raising a routine worker failure here makes a cycle from the
            # Future through its traceback to this GUI frame and back to the
            # Future. Inspect completed failures so replaced requests release
            # their captured editor/view state immediately.
            error = future.exception()
            if error is not None:
                self._report_failure(error, valid)
            else:
                result = future.result()
                if valid and isinstance(result, FieldPresentation):
                    self.presentation = result
                    self._draw(result)
                    self.loaded.emit()
                elif valid and isinstance(result, PreparedFieldProbe) and self._client is not None:
                    accepted = self._client.transaction(
                        result.commands,
                        expected_revision=result.revision,
                        intent="Author an exact consumer of a retained field sample",
                    )
                    if isinstance(accepted, CommandAccepted):
                        self.status.setText(
                            "Exact probe authored. Select its model and Freeze & Run."
                        )
                        self.modelCreated.emit(result.model_id)
                    elif isinstance(accepted, CommandDeferred):
                        self.status.setText(
                            "Forking the frozen definition before accepting the probe."
                        )
                    else:
                        self.status.setText(accepted.message)
        except (ValueError, OSError, RuntimeError, KeyError) as exc:
            self._report_failure(exc, valid)
        if editing:
            self.probe.setEnabled(self.presentation is not None)
        self._start_pending()

    def _report_failure(self, error: BaseException, current: bool) -> None:
        if isinstance(error, InterruptedError):
            return
        if not isinstance(error, (ValueError, OSError, RuntimeError, KeyError)):
            raise error
        if current:
            self.status.setText(str(error))
            self.failed.emit(str(error))

    @staticmethod
    def _curve(
        scene: QGraphicsScene,
        points: tuple[tuple[float, float], ...],
        color: str,
        lower: float,
        upper: float,
    ) -> None:
        path = QPainterPath()
        for ordinal, (x, value) in enumerate(points):
            y = 115 - 100 * (value - lower) / (upper - lower if upper > lower else 1.0)
            if ordinal == 0:
                path.moveTo(10 + 580 * x, y)
            else:
                path.lineTo(10 + 580 * x, y)
        scene.addPath(path, QPen(QColor(color), 1.5))
        scene.setSceneRect(0, 0, 600, 135)

    def _draw(self, value: FieldPresentation) -> None:
        source = self._source
        assert source is not None
        self.time_cursor.blockSignals(True)
        self.time_cursor.setRange(0, value.sample_count - 1)
        self.time_cursor.setValue(value.selected.sample)
        self.time_cursor.setEnabled(True)
        self.time_cursor.blockSignals(False)
        self.node.setMaximum(value.support.nodes - 1)
        self.probe.setEnabled(self._client is not None)
        self.status.setText(
            f"{source.outcome}; source revision {source.revision}; "
            + ("current authoring" if source.current_source else "historical source")
            + f"\nField {value.interpretation.field_id}; {value.interpretation.unit.id} "
            + f"({value.interpretation.quantity_kind.value}), node-associated scalar"
            + f"\nFrame {value.support.frame_id}; axis {value.support.axis_name}; "
            + f"{value.sample_count} retained samples"
            + f"\nSupport {value.interpretation.support.content_hash}; "
            + f"spacing {value.support.spacing.magnitude:g} {value.support.spacing.unit.id}"
            + f"\nInput {source.input_digest}; series {value.resource.content_hash}"
        )
        self.accepted_label.setText(
            f"Selected retained accepted sample {value.selected.sample}, "
            f"step {value.selected.step}, t={value.selected.time.magnitude:.9g} "
            f"{value.selected.time.unit.id}; "
            f"range [{value.value_range[0]:.7g}, {value.value_range[1]:.7g}]"
        )
        self.scene.clear()
        self._curve(self.scene, value.profile, "#187ca1", *value.value_range)
        self.trial_scene.clear()
        if value.preview is None:
            self.trial_label.setText("No provisional trial for this source.")
        else:
            trial = value.preview
            retained = trial.accepted.sample < value.sample_count
            self.trial_label.setText(
                f"Provisional trial: base accepted step {trial.accepted.step}, "
                f"t={trial.accepted.time.magnitude:.9g} {trial.accepted.time.unit.id} "
                + ("(retained)" if retained else "(not yet retained in this prefix)")
                + f" -> candidate step {trial.candidate.step}, "
                + f"t={trial.candidate.time.magnitude:.9g} {trial.candidate.time.unit.id}. "
                + "Blue: accepted base. Orange: trial. The history cursor is independent."
            )
            base = tuple(
                (cast(int, i) / (value.support.nodes - 1), cast(float, v))
                for i, v in zip(trial.indices.elements, trial.accepted_values.elements, strict=True)
            )
            candidate = tuple(
                (cast(int, i) / (value.support.nodes - 1), cast(float, v))
                for i, v in zip(trial.indices.elements, trial.trial_values.elements, strict=True)
            )
            lower = min(v for _, v in (*base, *candidate))
            upper = max(v for _, v in (*base, *candidate))
            self._curve(self.trial_scene, base, "#187ca1", lower, upper)
            self._curve(self.trial_scene, candidate, "#d96c17", lower, upper)
        if value.rgba:
            image = QImage(
                value.rgba,
                value.image_width,
                value.image_height,
                value.image_width * 4,
                QImage.Format.Format_RGBA8888,
            )
            self.heatmap.setPixmap(QPixmap.fromImage(image).scaled(600, 128))
            self.heatmap.setToolTip(
                "Bounded overview of exact sampled times; no temporal interpolation. "
                f"First {value.image_times[0].time.magnitude:g}; "
                f"last {value.image_times[-1].time.magnitude:g} {value.selected.time.unit.id}"
            )
        else:
            self.heatmap.clear()

    def _select_field(self) -> None:
        if (
            self._kernel
            and self._source
            and self._source.current_source
            and self.presentation
            and self._source.revision == self._kernel.revision
        ):
            self._kernel.selection.select(
                (self.presentation.interpretation.field_id,),
                revision=self._source.revision,
                source="field-history",
            )

    def _create_probe(self) -> None:
        kernel, source, presentation = self._kernel, self._source, self.presentation
        if (
            kernel is None
            or source is None
            or presentation is None
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
            presentation.selected.sample,
            False,
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
            presentation.resource,
            presentation.selected.sample,
            self.node.value(),
        )
        self._timer.start()

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._timer.stop()
        self._playback.stop()
        self._cancel.set()
        self._pending = None
        # The same worker releases mappings after its current bounded read.
        # Closing a view never waits on resource work in the GUI thread.
        self._executor.submit(self._reader.close)
        self._executor.shutdown(wait=False)
