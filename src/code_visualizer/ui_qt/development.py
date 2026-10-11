"""Python Development workbench and Qt debounce scheduler adapter."""

from __future__ import annotations

import difflib
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Lock

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from code_visualizer.application.python_pipeline import (
    PipelineState,
    PipelineStatus,
    ScheduledCall,
)
from code_visualizer.domain.project import Project
from code_visualizer.generation import (
    ArtifactInspection,
    expected_artifact_contents,
    inspect_generation,
)
from code_visualizer.generation.artifacts import ArtifactGenerationError, read_artifact_text
from code_visualizer.validation import Diagnostic


class _QtScheduledCall:
    def __init__(self, timer: QTimer, executor: ThreadPoolExecutor) -> None:
        self._timer = timer
        self._executor = executor
        self._future: Future[object] | None = None
        self._cancelled = False
        self._lock = Lock()

    def start(self, callback: Callable[[], None]) -> None:
        with self._lock:
            if self._cancelled:
                return
            self._future = self._executor.submit(callback)

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            future = self._future
        self._timer.stop()
        self._timer.deleteLater()
        if future is not None:
            future.cancel()


class QtScheduler(QObject):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="code-visualizer-pipeline",
        )
        self.destroyed.connect(self._shutdown)

    def call_later(self, delay_ms: int, callback: Callable[[], None]) -> ScheduledCall:
        timer = QTimer(self)
        timer.setSingleShot(True)
        scheduled = _QtScheduledCall(timer, self._executor)

        def invoke() -> None:
            try:
                scheduled.start(callback)
            finally:
                timer.deleteLater()

        timer.timeout.connect(invoke)
        timer.start(delay_ms)
        return scheduled

    def _shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


class PythonDevelopmentWidget(QWidget):
    generateRequested = Signal()
    saveGenerateRequested = Signal()
    revealRequested = Signal()
    validateRequested = Signal()
    diagnosticActivated = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pythonDevelopmentWorkbench")
        self._artifact_root: Path | None = None
        self._expected_artifacts: dict[str, str] = {}
        self._artifact_inspection = ArtifactInspection(False)

        self.state_label = QLabel("No project open")
        self.state_label.setObjectName("generationState")
        self.state_label.setAccessibleName("Validation and generation state")
        self.detail_label = QLabel()
        self.detail_label.setObjectName("generationDetails")
        self.detail_label.setWordWrap(True)
        self.save_generate_button = QPushButton("Save and Generate…")
        self.save_generate_button.setObjectName("saveAndGenerate")
        self.generate_button = QPushButton("Generate Project")
        self.generate_button.setObjectName("generateProject")
        self.validate_button = QPushButton("Validate")
        self.validate_button.setObjectName("validateProject")
        self.reveal_button = QPushButton("Open Generated Folder")
        self.reveal_button.setObjectName("revealGeneratedFolder")
        self.reveal_button.setEnabled(False)
        self.save_generate_button.clicked.connect(self.saveGenerateRequested)
        self.generate_button.clicked.connect(self.generateRequested)
        self.validate_button.clicked.connect(self.validateRequested)
        self.reveal_button.clicked.connect(self.revealRequested)

        controls = QHBoxLayout()
        controls.addWidget(self.state_label, 1)
        controls.addWidget(self.validate_button)
        controls.addWidget(self.save_generate_button)
        controls.addWidget(self.generate_button)
        controls.addWidget(self.reveal_button)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("pythonDevelopmentTabs")
        self.diagnostics = QTreeWidget()
        self.diagnostics.setObjectName("diagnosticsList")
        self.diagnostics.setHeaderLabels(
            ["Severity", "Code", "Location", "Explanation", "Suggested repair"]
        )
        self.diagnostics.itemActivated.connect(self._activate_diagnostic)
        self.diagnostic_filter = QLineEdit()
        self.diagnostic_filter.setObjectName("diagnosticFilter")
        self.diagnostic_filter.setAccessibleName("Filter diagnostics")
        self.diagnostic_filter.setPlaceholderText(
            "Filter diagnostics by severity, code, location, explanation, or repair"
        )
        self.diagnostic_filter.textChanged.connect(self._filter_diagnostics)

        self.artifacts = QTreeWidget()
        self.artifacts.setObjectName("artifactTree")
        self.artifacts.setHeaderLabels(["Generated artifact", "State", "SHA-256"])
        self.artifacts.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.artifacts.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.artifacts.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.artifacts.itemActivated.connect(self._preview_item)
        self.artifact_preview = QPlainTextEdit()
        self.artifact_preview.setObjectName("artifactPreview")
        self.artifact_preview.setReadOnly(True)
        self.artifact_preview.setAccessibleName("Generated artifact preview")
        artifact_splitter = QSplitter(Qt.Orientation.Horizontal)
        artifact_splitter.addWidget(self.artifacts)
        artifact_splitter.addWidget(self.artifact_preview)
        artifact_splitter.setStretchFactor(0, 1)
        artifact_splitter.setStretchFactor(1, 2)

        self.artifact_diff = QPlainTextEdit()
        self.artifact_diff.setObjectName("artifactDiff")
        self.artifact_diff.setReadOnly(True)
        self.artifact_diff.setAccessibleName("Generated artifact difference")

        self.run_output = QPlainTextEdit()
        self.run_output.setObjectName("projectRunOutput")
        self.run_output.setReadOnly(True)
        self.run_output.setAccessibleName("Generated project run output")
        self.tabs.addTab(self.diagnostics, "Diagnostics")
        self.tabs.addTab(artifact_splitter, "Artifacts")
        self.tabs.addTab(self.artifact_diff, "Artifact Diff")
        self.tabs.addTab(self.run_output, "Run Output")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(controls)
        layout.addWidget(self.detail_label)
        layout.addWidget(self.diagnostic_filter)
        layout.addWidget(self.tabs, 1)

    def set_pipeline_status(self, status: PipelineStatus) -> None:
        labels = {
            PipelineState.UNSAVED: "Unsaved",
            PipelineState.PENDING: "Pending changes",
            PipelineState.VALIDATING: "Validating",
            PipelineState.VALIDATED: f"Validated revision {status.revision}",
            PipelineState.BLOCKED: "Blocked",
            PipelineState.GENERATING: f"Generating revision {status.revision}",
            PipelineState.UP_TO_DATE: f"Up to date at revision {status.revision}",
            PipelineState.FAILED: "Failed",
            PipelineState.STALE_OUTPUT: (f"Stale output from revision {status.artifact_revision}"),
        }
        self.state_label.setText(labels[status.state])
        self.detail_label.setText(status.message)
        self.set_diagnostics(status.diagnostics, status.revision)
        unsaved = status.state is PipelineState.UNSAVED
        self.save_generate_button.setVisible(unsaved)
        self.generate_button.setVisible(not unsaved)

    def set_diagnostics(
        self,
        diagnostics: tuple[Diagnostic, ...],
        revision: int,
    ) -> None:
        self.diagnostics.clear()
        if not diagnostics:
            item = QTreeWidgetItem(
                ["Info", "VALID", "Project", f"No problems at revision {revision}", ""]
            )
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.diagnostics.addTopLevelItem(item)
            self._filter_diagnostics(self.diagnostic_filter.text())
            return
        for diagnostic in diagnostics:
            location = " / ".join(
                item
                for item in (
                    diagnostic.diagram_id,
                    diagnostic.object_id,
                    diagnostic.field,
                )
                if item
            )
            item = QTreeWidgetItem(
                [
                    diagnostic.severity.value.title(),
                    diagnostic.code,
                    location or "Project",
                    diagnostic.message,
                    diagnostic.suggested_repair,
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, diagnostic)
            self.diagnostics.addTopLevelItem(item)
        for column in range(self.diagnostics.columnCount()):
            self.diagnostics.resizeColumnToContents(column)
        self._filter_diagnostics(self.diagnostic_filter.text())

    def _filter_diagnostics(self, query: str) -> None:
        needle = query.casefold().strip()
        for row in range(self.diagnostics.topLevelItemCount()):
            item = self.diagnostics.topLevelItem(row)
            if item is None:
                continue
            searchable = " ".join(
                item.text(column) for column in range(self.diagnostics.columnCount())
            ).casefold()
            item.setHidden(bool(needle and needle not in searchable))

    @property
    def artifact_inspection(self) -> ArtifactInspection:
        return self._artifact_inspection

    def refresh_artifacts(
        self,
        project_root: Path | None,
        project: Project | None = None,
    ) -> bool:
        self.artifacts.clear()
        self.artifact_preview.clear()
        self.artifact_diff.clear()
        self._artifact_root = None
        self._expected_artifacts = {}
        self._artifact_inspection = ArtifactInspection(False)
        if project_root is None:
            self.reveal_button.setEnabled(False)
            return False
        revision = project.revision if project is not None else None
        inspection = inspect_generation(project_root, current_revision=revision)
        self._artifact_inspection = inspection
        if not inspection.manifest_found:
            self.reveal_button.setEnabled(False)
            return False
        root = project_root.resolve() / "generated"
        self._artifact_root = root
        if project is not None:
            try:
                self._expected_artifacts = expected_artifact_contents(
                    project,
                    project_root=project_root,
                )
            except ArtifactGenerationError:
                self._expected_artifacts = {}
        manifest_state = "Invalid" if inspection.invalid_manifest else "Manifest"
        manifest_item = QTreeWidgetItem(["generation.json", manifest_state, ""])
        manifest_item.setData(0, Qt.ItemDataRole.UserRole, "generation.json")
        self.artifacts.addTopLevelItem(manifest_item)
        directories: dict[tuple[str, ...], QTreeWidgetItem] = {}

        def add_artifact(relative: str, state: str, digest: str) -> None:
            parts = tuple(relative.split("/"))
            parent: QTreeWidgetItem | None = None
            for depth, folder in enumerate(parts[:-1], start=1):
                key = parts[:depth]
                item = directories.get(key)
                if item is None:
                    item = QTreeWidgetItem([f"{folder}/", "Folder", ""])
                    if parent is None:
                        self.artifacts.addTopLevelItem(item)
                    else:
                        parent.addChild(item)
                    directories[key] = item
                parent = item
            leaf = QTreeWidgetItem([parts[-1], state, digest])
            leaf.setToolTip(0, relative)
            leaf.setData(0, Qt.ItemDataRole.UserRole, relative)
            if parent is None:
                self.artifacts.addTopLevelItem(leaf)
            else:
                parent.addChild(leaf)

        missing = set(inspection.missing)
        modified = set(inspection.modified)
        for relative, digest in inspection.files:
            state = (
                "Missing"
                if relative in missing
                else "Modified"
                if relative in modified
                else "Current"
            )
            add_artifact(relative, state, digest[:16])
        for relative in inspection.unexpected:
            add_artifact(relative, "Untracked", "")
        for item in directories.values():
            item.setExpanded(True)
        if inspection.externally_changed:
            changed = (
                len(inspection.missing) + len(inspection.modified) + len(inspection.unexpected)
            )
            self.detail_label.setText(
                f"{changed} generated artifact{'s' if changed != 1 else ''} changed outside "
                "Code Visualizer. Select a file to inspect its diff; explicit Generate Project "
                "is required before replacement."
            )
        self.reveal_button.setEnabled(self.artifacts.topLevelItemCount() > 0)
        return self.reveal_button.isEnabled()

    def show_diagnostics(self) -> None:
        self.tabs.setCurrentWidget(self.diagnostics)

    def show_artifacts(self) -> None:
        self.tabs.setCurrentIndex(1)

    def show_run_output(self) -> None:
        self.tabs.setCurrentWidget(self.run_output)

    def show_artifact_diff(self) -> None:
        self.tabs.setCurrentWidget(self.artifact_diff)

    def _preview_item(self, item: QTreeWidgetItem, _column: int) -> None:
        if self._artifact_root is None:
            return
        relative = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(relative, str):
            return
        try:
            actual = read_artifact_text(self._artifact_root.parent, relative)
            if actual is None:
                self.artifact_preview.setPlainText(
                    f"{relative}\n\nPreview omitted because this artifact exceeds 2 MB."
                )
                return
            self.artifact_preview.setPlainText(actual)
            expected = self._expected_artifacts.get(relative)
            if expected is None:
                self.artifact_diff.setPlainText(
                    f"{relative} is not in the proposed deterministic artifact set.\n"
                )
            elif expected == actual:
                self.artifact_diff.setPlainText(
                    f"{relative} matches the proposed artifact for the active project revision.\n"
                )
            else:
                difference = difflib.unified_diff(
                    actual.splitlines(),
                    expected.splitlines(),
                    fromfile=f"generated/{relative} (on disk)",
                    tofile=f"generated/{relative} (proposed regeneration)",
                    lineterm="",
                )
                self.artifact_diff.setPlainText("\n".join(difference) + "\n")
                self.show_artifact_diff()
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            self.artifact_preview.setPlainText(f"Cannot preview {relative}: {exc}")
            expected = self._expected_artifacts.get(relative)
            if expected is not None:
                self.artifact_diff.setPlainText(
                    f"--- generated/{relative} (missing or unreadable)\n"
                    f"+++ generated/{relative} (proposed regeneration)\n"
                    + "\n".join(f"+{line}" for line in expected.splitlines())
                    + "\n"
                )
                self.show_artifact_diff()

    def _activate_diagnostic(self, item: QTreeWidgetItem, _column: int) -> None:
        diagnostic = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(diagnostic, Diagnostic):
            self.diagnosticActivated.emit(diagnostic)
