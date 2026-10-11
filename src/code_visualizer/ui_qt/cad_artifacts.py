"""Artifact inspection and explicit CAD authoring actions in the existing workbench."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import Event
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainterPath, QPen, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QComboBox,
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsSceneMouseEvent,
    QGraphicsView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from code_visualizer.application.cad_artifacts import PreparedArtifactEdit, prepare_consumer
from code_visualizer.application.messages import CommandAccepted, CommandDeferred
from code_visualizer.domain.computation import (
    ComputationParameter,
    ComputationRequest,
    ResourceInput,
    ResourceOutput,
)
from code_visualizer.domain.evidence import ComputationEvidence
from code_visualizer.domain.program import program_statements
from code_visualizer.domain.resources import DataResource
from code_visualizer.domain.values import CanonicalValue
from code_visualizer.extensions.axial.presentation import AxialPresentation, prepare_result
from code_visualizer.extensions.axial.records import RESULT_TYPE as AXIAL_RESULT_TYPE
from code_visualizer.extensions.cad.native import decode_mesh
from code_visualizer.extensions.cad.presentation import MeshPreview, project_mesh
from code_visualizer.extensions.cad.regions import FaceSelection
from code_visualizer.extensions.cad.resources import BREP, MESH, CadHeader, read_envelope_header
from code_visualizer.persistence.computation_resources import resolve_computation_resource
from code_visualizer.persistence.resource_store import ResourceStore

if TYPE_CHECKING:
    from code_visualizer.application.kernel import ProjectKernel
    from code_visualizer.sdk import CodeVisualizerClient


@dataclass(frozen=True, slots=True)
class ArtifactInspection:
    descriptor: DataResource
    preview: MeshPreview | None
    header: CadHeader | None = None
    axial: AxialPresentation | None = None


def inspect_artifact(
    store: ResourceStore,
    evidence: ComputationEvidence,
    artifact_id: str,
    view: str,
    cancelled: Event | None = None,
) -> ArtifactInspection:
    artifact = next(a for a in evidence.artifacts if a.id == artifact_id)
    descriptor = store.describe(artifact.resource)
    store.verified_path(artifact.resource)
    preview = None
    header = None
    axial = None
    if descriptor.logical_type == AXIAL_RESULT_TYPE:
        axial = prepare_result(
            artifact.resource,
            lambda ref: resolve_computation_resource(store, ref, file_backed=True),
        )
    if descriptor.logical_type == BREP:
        with store.verified_path(artifact.resource).open("rb") as stream:
            header, size = read_envelope_header(stream, BREP)
            if stream.tell() + size != descriptor.byte_size:
                raise ValueError("CAD_SIZE: geometry payload differs from its descriptor")
    if descriptor.logical_type == MESH:
        # A bounded display representation is consumed; no BREP tessellation is
        # hidden in the viewer and no native decoder runs in a GUI handler.
        if descriptor.byte_size > 64 * 1024 * 1024:
            raise ValueError("CAD_PREVIEW_SIZE: display resource exceeds 64 MiB")
        preview = project_mesh(
            artifact.resource,
            decode_mesh(store.read(artifact.resource)),
            view,
            cancelled=cancelled.is_set if cancelled else None,
        )
    return ArtifactInspection(descriptor, preview, header, axial)


class _MeshItem(QGraphicsPixmapItem):
    def __init__(self, preview: MeshPreview, panel: CadArtifactPanel) -> None:
        image = QImage(
            preview.rgba,
            preview.width,
            preview.height,
            preview.width * 4,
            QImage.Format.Format_RGBA8888,
        )
        super().__init__(QPixmap.fromImage(image))
        self.preview, self._panel = preview, panel
        self.setData(0, preview.mesh.face_ids[0])
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        face = self.preview.face_at(int(event.pos().x()), int(event.pos().y()))
        if face is None:
            event.ignore()
            return
        self.setData(0, face)
        self.setToolTip(f"Face {face} on {self.preview.mesh.header.parent}")
        selected = self.isSelected()
        super().mousePressEvent(event)
        if selected:
            self._panel._picked()


class CadArtifactPanel(QWidget):
    freezeRequested = Signal(object)
    modelCreated = Signal(str)
    faceSelected = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("cadArtifactPanel")
        self._kernel: ProjectKernel | None = None
        self._client: CodeVisualizerClient | None = None
        self._evidence: ComputationEvidence | None = None
        self._artifact_id = ""
        self._store: ResourceStore | None = None
        self._current_source = False
        self._generation = 0
        self._future: Future[object] | None = None
        self._token: tuple[int, str, int] | None = None
        self._inspection: ArtifactInspection | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="artifact-view")
        self._cancel = Event()
        self.destroyed.connect(lambda: self._cancel.set())
        self.destroyed.connect(lambda: self._executor.shutdown(wait=False, cancel_futures=True))
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._poll)
        layout = QVBoxLayout(self)
        self.status = QLabel("Select an evidence artifact to inspect or use it as an input.")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.buttons: dict[str, QPushButton] = {}
        bar = QHBoxLayout()
        for concept, label in (
            ("Measurement", "Measure"),
            ("Tessellation", "Create display mesh"),
            ("RegionSelection", "Assign boundary"),
            ("GeometryInput", "Promote to editable input"),
        ):
            button = QPushButton(label)
            button.setObjectName("cad" + concept)
            button.clicked.connect(lambda _checked=False, c=concept: self.prepare(c))
            self.buttons[concept] = button
            bar.addWidget(button)
        self.bind_button = QPushButton("Freeze Python with this input…")
        self.bind_button.clicked.connect(self.bind_python)
        bar.addWidget(self.bind_button)
        self.axial_button = QPushButton("Create axial analysis…")
        self.axial_button.setObjectName("createAxialAnalysis")
        self.axial_button.clicked.connect(self.prepare_axial)
        bar.addWidget(self.axial_button)
        self.produce_button = QPushButton("Freeze Python CAD producer…")
        self.produce_button.setObjectName("freezePythonCadProducer")
        self.produce_button.clicked.connect(self.produce_python)
        bar.addWidget(self.produce_button)
        layout.addLayout(bar)
        self.orientation = QComboBox()
        self.orientation.addItems(["isometric", "front", "top"])
        self.orientation.currentTextChanged.connect(self._reload)
        layout.addWidget(self.orientation)
        self.scene = QGraphicsScene(self)
        self.scene.selectionChanged.connect(self._picked)
        self.view = QGraphicsView(self.scene)
        self.view.setObjectName("cadMeshView")
        self.view.setMinimumHeight(230)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.view, 1)
        self._enable(False)

    def _enable(self, enabled: bool) -> None:
        brep = bool(self._inspection and self._inspection.descriptor.logical_type == BREP)
        for button in self.buttons.values():
            button.setEnabled(enabled and brep)
        self.bind_button.setEnabled(enabled and self._inspection is not None)
        self.axial_button.setEnabled(enabled and brep and self._client is not None)
        self.produce_button.setEnabled(self._kernel is not None and self._client is not None)

    def attach(self, kernel: ProjectKernel | None, client: CodeVisualizerClient | None) -> None:
        self._cancel_pending()
        self._generation += 1
        self._kernel, self._client = kernel, client
        self._evidence, self._store, self._inspection = None, None, None
        self.scene.clear()
        self._enable(False)

    def inspect(
        self,
        evidence: ComputationEvidence,
        artifact_id: str,
        store: ResourceStore,
        *,
        current_source: bool = False,
    ) -> None:
        self._evidence, self._artifact_id, self._store = evidence, artifact_id, store
        self._current_source = current_source
        self._reload()

    def _reload(self, _view: str = "") -> None:
        if self._evidence is None or self._store is None or self._kernel is None:
            return
        self._cancel_pending()
        self._generation += 1
        self._enable(False)
        self.status.setText("Verifying the selected immutable artifact…")
        self._token = (
            self._generation,
            self._kernel.computation_attachment.id,
            self._kernel.revision,
        )
        self._future = self._executor.submit(
            inspect_artifact,
            self._store,
            self._evidence,
            self._artifact_id,
            self.orientation.currentText(),
            self._cancel,
        )
        self._timer.start()

    def _cancel_pending(self) -> None:
        self._cancel.set()
        if self._future is not None:
            self._future.cancel()
        self._cancel = Event()

    def prepare(self, concept: str) -> None:
        kernel, client, store, evidence = self._kernel, self._client, self._store, self._evidence
        if (
            kernel is None
            or client is None
            or store is None
            or evidence is None
            or kernel.resource_store is None
        ):
            return
        properties: tuple[tuple[str, CanonicalValue], ...] = ()
        if concept == "RegionSelection":
            choice, accepted = QInputDialog.getItem(
                self,
                "Boundary rule",
                "Planar end face",
                ["support: x minimum", "load: x maximum"],
                editable=False,
            )
            if not accepted:
                return
            properties = (
                ("assignment", "load" if choice.startswith("load") else "support"),
                ("side", "max" if choice.startswith("load") else "min"),
            )
        self._cancel_pending()
        self._generation += 1
        self._token = (self._generation, kernel.computation_attachment.id, kernel.revision)
        self._enable(False)
        self.status.setText("Verifying and retaining the selected input before authoring…")
        self._future = self._executor.submit(
            prepare_consumer,
            client.snapshot(),
            kernel.extensions,
            evidence,
            self._artifact_id,
            store,
            kernel.resource_store,
            concept,
            properties=properties,
        )
        self._timer.start()

    def _poll(self) -> None:
        future, kernel, token = self._future, self._kernel, self._token
        if future is None or not future.done():
            return
        self._future = None
        self._timer.stop()
        if kernel is None or token != (
            self._generation,
            kernel.computation_attachment.id,
            kernel.revision,
        ):
            self.status.setText("The editing context changed. Select the artifact again.")
            return
        try:
            result = future.result()
            if isinstance(result, ArtifactInspection):
                self._inspection = result
                self._draw(result)
            elif isinstance(result, PreparedArtifactEdit) and self._client is not None:
                accepted = self._client.transaction(
                    result.commands,
                    expected_revision=result.revision,
                    intent="Create an explicit consumer of the selected retained artifact",
                )
                if isinstance(accepted, CommandAccepted):
                    self.status.setText(
                        "Authored input created. Select its model and Freeze & Run."
                    )
                    self.modelCreated.emit(result.model_id)
                elif isinstance(accepted, CommandDeferred):
                    self.status.setText(
                        "Forking the frozen definition before accepting the new input."
                    )
                else:
                    self.status.setText(accepted.message)
            self._enable(True)
        except (ValueError, OSError, RuntimeError, StopIteration) as exc:
            self.status.setText(str(exc))
            self._enable(False)

    def prepare_axial(self) -> None:
        from code_visualizer.application.axial_artifacts import prepare_axial

        kernel, client, store, evidence = self._kernel, self._client, self._store, self._evidence
        if (
            kernel is None
            or client is None
            or store is None
            or evidence is None
            or kernel.resource_store is None
        ):
            return
        modulus, ok = QInputDialog.getDouble(
            self, "Axial material", "Young modulus (GPa)", 200, 1e-9, 1e6, 6
        )
        if not ok:
            return
        force, ok = QInputDialog.getDouble(
            self, "Axial load", "Signed axial force (N)", 1000, -1e9, 1e9, 6
        )
        if not ok:
            return
        nodes, ok = QInputDialog.getInt(self, "Axial discretization", "Nodes", 9, 3, 65)
        if not ok:
            return
        axis, ok = QInputDialog.getItem(
            self,
            "Axial idealization",
            "Fixed minimum end, loaded maximum end",
            ["x", "y", "z"],
            editable=False,
        )
        if not ok:
            return
        self._cancel_pending()
        self._generation += 1
        self._token = (self._generation, kernel.computation_attachment.id, kernel.revision)
        self._enable(False)
        self.status.setText(
            "Retaining geometry and preparing material, end predicates and axial idealization…"
        )
        self._future = self._executor.submit(
            prepare_axial,
            client.snapshot(),
            kernel.extensions,
            evidence,
            self._artifact_id,
            store,
            kernel.resource_store,
            young_modulus=modulus * 1e9,
            force=force,
            nodes=nodes,
            axis=axis,
        )
        self._timer.start()

    def _draw(self, inspection: ArtifactInspection) -> None:
        self.scene.clear()
        descriptor, preview = inspection.descriptor, inspection.preview
        kind = descriptor.logical_type
        evidence = self._evidence
        assert evidence is not None
        self.status.setText(
            f"{kind.id if kind else 'Untyped'} / {kind.version if kind else ''}\n"
            f"SHA-256: {descriptor.content_hash}\n"
            f"Evidence: {evidence.id} · source revision {evidence.provenance.revision}\n"
            f"Input digest: {evidence.provenance.input_digest}\n"
            + (
                "Current source"
                if self._current_source
                else "Historical source; current authoring is not highlighted"
            )
        )
        if preview is None:
            if inspection.axial is not None:
                self._draw_axial(inspection.axial)
            if inspection.header is not None:
                header = inspection.header
                self.status.setText(
                    self.status.text()
                    + f"\nSpace: {header.frame.space_id} · frame: {header.frame.frame_id}"
                    + f"\nCoordinate unit: {header.frame.unit.id} · tolerance: {header.tolerance}"
                    + f"\nProducer operations: {', '.join(header.origins.semantic_ids)}"
                    + "\nCreate a display mesh to view and pick faces. "
                    "Native topology is checked by the consumer backend."
                )
            return
        self.scene.addItem(_MeshItem(preview, self))
        self.scene.setSceneRect(0, 0, preview.width, preview.height)
        frame = preview.mesh.header.frame
        self.status.setText(
            self.status.text() + f"\n{frame.frame_id} · {frame.unit.id} · "
            f"chordal {preview.mesh.header.tolerance} · "
            f"angular {preview.mesh.header.angular_tolerance}"
        )
        QTimer.singleShot(0, self._fit_preview)

    def _draw_axial(self, value: AxialPresentation) -> None:
        x, u = value.coordinates, value.displacement
        minimum, maximum = min(u), max(u)
        path = QPainterPath()
        for i, (position, displacement) in enumerate(zip(x, u, strict=True)):
            px = 20 + 560 * (position - x[0]) / (x[-1] - x[0])
            py = 130 - 100 * (displacement - minimum) / (
                maximum - minimum if maximum > minimum else 1
            )
            if i:
                path.lineTo(px, py)
            else:
                path.moveTo(px, py)
        self.scene.addPath(path, QPen(QColor("#187ca1"), 2))
        self.scene.addText(
            "Axial displacement (m) versus coordinate (m); axes scaled independently"
        ).setPos(10, 150)
        self.scene.setSceneRect(0, 0, 610, 185)
        self.status.setText(
            self.status.text()
            + f"\nFrame {value.mapping.frame_id}; {value.mapping.axis} axis; {len(x)} nodes"
            + f"\nExtension {u[-1]:.9g} m; stress "
            + f"{min(value.stress):.9g} .. {max(value.stress):.9g} Pa"
            + f"\nReaction {value.result.reaction.magnitude:.9g} N; "
            + f"energy {value.result.strain_energy.magnitude:.9g} J"
            + "\nDerived equilibrium only; the retained CAD and authored definition are unchanged."
        )
        QTimer.singleShot(0, self._fit_preview)

    def _fit_preview(self) -> None:
        if self.scene.items():
            self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, self._fit_preview)

    def _picked(self) -> None:
        inspection, evidence, kernel = self._inspection, self._evidence, self._kernel
        selected = self.scene.selectedItems()
        if not selected or inspection is None or inspection.preview is None or evidence is None:
            return
        parent = inspection.preview.mesh.header.parent
        assert parent is not None
        self.faceSelected.emit(FaceSelection(parent, int(selected[0].data(0))))
        if kernel and self._current_source and kernel.revision == evidence.provenance.revision:
            artifact = next(a for a in evidence.artifacts if a.id == self._artifact_id)
            kernel.selection.select(artifact.semantic_ids, source="cad-artifact")

    def bind_python(self) -> None:
        kernel, inspection, evidence = self._kernel, self._inspection, self._evidence
        if (
            kernel is None
            or inspection is None
            or evidence is None
            or inspection.descriptor.logical_type is None
        ):
            return
        name, accepted = QInputDialog.getText(
            self, "Python resource input", "Declared input name", text="solution"
        )
        if not accepted:
            return
        output, accepted = QInputDialog.getText(
            self, "Python resource output", "Required BREP output name", text="solid"
        )
        if not accepted:
            return
        try:
            project = kernel.authority.snapshot()
            origins = tuple(s.id for s in program_statements(project.program_model))
            request = ComputationRequest(
                project.id,
                project.revision,
                "code_visualizer.python",
                "2",
                configuration=(ComputationParameter("timeout_seconds", 120),),
                inputs=(
                    ResourceInput(
                        name, inspection.descriptor.reference, inspection.descriptor.logical_type
                    ),
                ),
                outputs=(ResourceOutput(output, BREP, origins),),
            )
            self.freezeRequested.emit(request)
        except ValueError as exc:
            self.status.setText(str(exc))

    def produce_python(self) -> None:
        kernel = self._kernel
        if kernel is None:
            return
        name, accepted = QInputDialog.getText(
            self,
            "Python CAD producer",
            "Required BREP output name used by the recipe",
            text="solid",
        )
        if not accepted:
            return
        try:
            project = kernel.authority.snapshot()
            origins = tuple(item.id for item in program_statements(project.program_model))
            self.freezeRequested.emit(
                ComputationRequest(
                    project.id,
                    project.revision,
                    "code_visualizer.python",
                    "2",
                    configuration=(ComputationParameter("timeout_seconds", 120),),
                    outputs=(ResourceOutput(name, BREP, origins),),
                )
            )
        except ValueError as exc:
            self.status.setText(str(exc))
