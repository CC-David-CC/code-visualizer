"""Main PySide6 shell projected from the application authority."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import cast

from PySide6.QtCore import QByteArray, QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QHeaderView,
    QLineEdit,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from code_visualizer.application.clipboard import (
    SEMANTIC_FRAGMENT_MIME,
    ClipboardFormatError,
    SemanticFragment,
    drakon_atoms_from_fragment,
    drakon_fragment,
    freeform_fragment,
    mindmap_fragment,
    paste_freeform_fragment,
    paste_mindmap_fragment,
    semantic_fragment_from_json,
    unresolved_references,
)
from code_visualizer.application.commands import ReplaceDiagramSnapshot, ReplaceDrakonAtom
from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.drakon_structure import clone_atoms_with_fresh_ids
from code_visualizer.application.examples import (
    EXAMPLE_CATALOG,
    PHYSICAL_EXAMPLE_CATALOG,
    ExampleBuildError,
    example_session,
)
from code_visualizer.application.git import GitError, GitOperationResult
from code_visualizer.application.git_service import GitProjectController
from code_visualizer.application.messages import (
    CommandAccepted,
    CommandDeferred,
    CommandRejected,
    EventEnvelope,
)
from code_visualizer.application.navigation import (
    NavigationHistory,
    NavigationLocation,
    build_call_hierarchy,
    find_address_transitions,
    find_callers,
)
from code_visualizer.application.python_pipeline import (
    DebouncedPythonPipeline,
    PipelineState,
    PipelineStatus,
)
from code_visualizer.application.search import SearchMatch
from code_visualizer.application.selection import SelectionState
from code_visualizer.application.session import ProjectSession
from code_visualizer.asset_management import AssetSafetyError, install_shape_pack
from code_visualizer.automation.host import LocalAutomationHost
from code_visualizer.automation.service import (
    AccessMode,
    AutomationCapability,
    AutomationContext,
)
from code_visualizer.config import PRODUCT
from code_visualizer.domain.common import DocumentKind
from code_visualizer.domain.drakon import (
    Action,
    DrakonAtom,
    DrakonDiagram,
    If,
    Loop,
    Sequence,
    SimpleStatement,
    find_atom_location,
    find_sequence,
    nested_sequences,
)
from code_visualizer.domain.drakon_defaults import ATOM_KIND_INVENTORY, MACROICON_INVENTORY
from code_visualizer.domain.freeform import FreeformDiagram
from code_visualizer.domain.mindmap import find_topic_parent
from code_visualizer.domain.module_paths import PythonPathError, python_module_file_path
from code_visualizer.domain.program import (
    ProgramClass,
    ProgramDeclaration,
    ProgramFunctionReference,
)
from code_visualizer.domain.program_kinds import CallableKind, SimpleKind
from code_visualizer.domain.project import Project
from code_visualizer.domain.semantic import ProjectionKind, SemanticObjectKind
from code_visualizer.execution import DebugEvent, RunResult, RunSession
from code_visualizer.generation import (
    GenerationResult,
    inspect_generation,
    load_generation_manifest,
)
from code_visualizer.persistence import ProjectLeaseConflict
from code_visualizer.rendering import ExportOptions, export_document
from code_visualizer.ui_qt.atom_inspector import AtomInspector
from code_visualizer.ui_qt.clipboard import set_semantic_clipboard
from code_visualizer.ui_qt.collaboration import CollaborationWidget
from code_visualizer.ui_qt.command_palette import CommandPalette
from code_visualizer.ui_qt.commands import CommandRegistry, CommandSpec
from code_visualizer.ui_qt.detached_document import (
    DetachableTabBar,
    DetachedDocumentWindow,
    position_near,
)
from code_visualizer.ui_qt.development import PythonDevelopmentWidget, QtScheduler
from code_visualizer.ui_qt.document import UnifiedDocumentWidget
from code_visualizer.ui_qt.features.domain_workbench.widget import DomainWorkbenchWidget
from code_visualizer.ui_qt.features.semantic_visualizer import SemanticVisualizerWidget
from code_visualizer.ui_qt.freeform_document import FreeformDocumentWidget
from code_visualizer.ui_qt.function_signature import FunctionSignatureEditor
from code_visualizer.ui_qt.git_workbench import GitWorkbenchWidget
from code_visualizer.ui_qt.mindmap_document import MindMapDocumentWidget
from code_visualizer.ui_qt.navigation import SemanticNavigationWidget
from code_visualizer.ui_qt.python_project import PythonProjectWidget
from code_visualizer.ui_qt.resource_examples import PreparedExample, ResourceExampleLoader
from code_visualizer.ui_qt.search import ProjectSearchWidget
from code_visualizer.ui_qt.shape_library import ShapeLibrary
from code_visualizer.ui_qt.theme import ThemeName, apply_theme
from code_visualizer.ui_qt.welcome import WelcomePage
from code_visualizer.ui_qt.workbench import place_workbench_dock, view_menu_docks
from code_visualizer.ui_qt.workspace_layout import WindowBounds
from code_visualizer.validation import assess_project

PathChooser = Callable[[], Path | None]
FolderRevealer = Callable[[Path], bool]
type EditorDocument = UnifiedDocumentWidget | MindMapDocumentWidget | FreeformDocumentWidget
SHAPE_TOOLTIP_ROLE = Qt.ItemDataRole.UserRole + 1


class CloseDecision(StrEnum):
    SAVE = "save"
    DISCARD = "discard"
    CANCEL = "cancel"


CloseDecisionProvider = Callable[[ProjectSession], CloseDecision]


class SaveFailureDecision(StrEnum):
    RETRY = "retry"
    RECOVERY_COPY = "recovery_copy"
    CANCEL_CLOSE = "cancel_close"


SaveFailureDecisionProvider = Callable[[ProjectSession, Exception], SaveFailureDecision]


class DrakonDeleteChoice(StrEnum):
    DELETE = "delete"
    UNWRAP = "unwrap"
    CANCEL = "cancel"


class MainWindow(QMainWindow):
    authorityEvent = Signal(object)
    automationEvent = Signal(object)
    pipelineEvent = Signal(object)
    projectRunCompleted = Signal(object)
    semanticSelection = Signal(object)
    gitEvent = Signal(object)

    _APPEARANCE_REVISION = 1

    def __init__(
        self,
        *,
        path_chooser: PathChooser | None = None,
        recovery_path_chooser: PathChooser | None = None,
        close_decision: CloseDecisionProvider | None = None,
        save_failure_decision: SaveFailureDecisionProvider | None = None,
        folder_revealer: FolderRevealer | None = None,
        settings: QSettings | None = None,
        computations: ComputationService | None = None,
    ) -> None:
        super().__init__()
        self._owns_computations = computations is None
        self._computations = computations if computations is not None else ComputationService()
        self.setObjectName("mainWindow")
        self.setWindowTitle(PRODUCT.name)
        self.resize(1440, 900)
        self._path_chooser = path_chooser or self._choose_project_directory
        self._recovery_path_chooser = recovery_path_chooser or self._choose_recovery_directory
        self._close_decision = close_decision or self._ask_close_decision
        self._save_failure_decision = save_failure_decision or self._ask_save_failure_decision
        self._folder_revealer = folder_revealer or self._open_folder
        self._settings = settings or QSettings(PRODUCT.application_id, PRODUCT.name)
        try:
            appearance_revision = int(str(self._settings.value("appearance/revision", 0)))
        except (TypeError, ValueError):
            appearance_revision = 0
        if appearance_revision < self._APPEARANCE_REVISION:
            # Reset the accidentally persisted first-release high-contrast selection
            # once. Theme choices made after this low-glare palette migration remain
            # user-owned.
            self._theme = ThemeName.CLASSIC
            self._settings.setValue("appearance/theme", self._theme.value)
            self._settings.setValue("appearance/revision", self._APPEARANCE_REVISION)
        else:
            try:
                self._theme = ThemeName(
                    str(self._settings.value("appearance/theme", ThemeName.CLASSIC.value))
                )
            except ValueError:
                self._theme = ThemeName.CLASSIC
        self._reduced_motion = str(
            self._settings.value("appearance/reduced_motion", "false")
        ).casefold() in {"1", "true", "yes"}
        application = QApplication.instance()
        if isinstance(application, QApplication):
            apply_theme(application, self._theme, reduced_motion=self._reduced_motion)
        self._session: ProjectSession | None = None
        self._resource_examples = ResourceExampleLoader(self)
        self._resource_examples.ready.connect(self._resource_example_ready)
        self._resource_examples.failed.connect(
            lambda message: self.statusBar().showMessage(message)
        )
        self._authority_unsubscribe: Callable[[], None] | None = None
        self._selection_unsubscribe: Callable[[], None] | None = None
        self._automation_host: LocalAutomationHost | None = None
        self._git_controller: GitProjectController | None = None
        self._documents: dict[str, EditorDocument] = {}
        self._document_order: list[QWidget] = []
        self._detached_documents: dict[str, DetachedDocumentWindow] = {}
        self._python_project_widget: PythonProjectWidget | None = None
        self._inspected_diagram_id: str | None = None
        self._refresh_pending = False
        self._applying_semantic_selection = False
        self._registry = CommandRegistry()
        self._navigation_history = NavigationHistory()
        self._project_run_session = RunSession()
        self._pending_project_run = False
        self.projectRunCompleted.connect(self._project_run_completed)
        self.semanticSelection.connect(self._on_semantic_selection)
        self.gitEvent.connect(self._git_changed)

        self._stack = QStackedWidget()
        self.welcome = WelcomePage()
        self.documents = QTabWidget()
        self.documents.setObjectName("outerDocumentTabs")
        outer_tab_bar = DetachableTabBar()
        outer_tab_bar.detachRequested.connect(self._detach_tab_from_drag)
        self.documents.setTabBar(outer_tab_bar)
        self.documents.setTabsClosable(True)
        self.documents.setMovable(True)
        outer_tab_bar.tabMoved.connect(self._remember_tab_order)
        self.documents.currentChanged.connect(self._document_tabs_changed)
        self.documents.tabCloseRequested.connect(self._close_document_tab)
        self.documents.tabBarDoubleClicked.connect(self._detach_tab)
        self._stack.addWidget(self.welcome)
        self._stack.addWidget(self.documents)
        self.setCentralWidget(self._stack)

        self._create_docks()
        self.authorityEvent.connect(self._on_event)
        self.automationEvent.connect(self._on_automation_event)
        self.pipelineEvent.connect(self._on_pipeline_status)
        self._pipeline = DebouncedPythonPipeline(
            QtScheduler(self),
            listener=self.pipelineEvent.emit,
        )
        self._create_actions()
        self._create_menus_and_toolbar()
        self._register_commands()
        self._connect_welcome()
        self._load_recents()
        self._show_welcome()
        self._bounds = WindowBounds(self)
        geometry = self._settings.value("workspace/geometry")
        if isinstance(geometry, QByteArray):
            self.restoreGeometry(geometry)
        self.statusBar().showMessage("Ready")

    @property
    def session(self) -> ProjectSession | None:
        return self._session

    @property
    def command_registry(self) -> CommandRegistry:
        """The same command surface used by menus, palette, and automation tests."""

        return self._registry

    def _create_docks(self) -> None:
        self.project_dock = QDockWidget("Project", self)
        self.project_dock.setObjectName("projectDock")
        self.project_tree = QTreeWidget()
        self.project_tree.setObjectName("projectTree")
        self.project_tree.setAccessibleName("Project explorer")
        self.project_tree.setMinimumWidth(0)
        self.project_tree.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.project_tree.setHeaderLabels(["Project item", "Kind"])
        self.project_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.project_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.project_tree.itemActivated.connect(self._activate_project_item)
        self.project_dock.setWidget(self.project_tree)
        place_workbench_dock(self, "project", self.project_dock)

        self.shapes_dock = QDockWidget("Shapes", self)
        self.shapes_dock.setObjectName("shapesDock")
        shapes_widget = QWidget()
        shapes_layout = QVBoxLayout(shapes_widget)
        self.shape_search = QLineEdit()
        self.shape_search.setObjectName("shapeSearch")
        self.shape_search.setAccessibleName("Search visual constructs")
        self.shape_search.setPlaceholderText("Search constructs")
        self.shape_list = ShapeLibrary()
        self.shape_list.setObjectName("shapeLibrary")
        self.shape_list.setAccessibleName("Semantic shape library")
        for info in ATOM_KIND_INVENTORY:
            item = QListWidgetItem(info.label)
            item.setData(Qt.ItemDataRole.UserRole, info.kind)
            item.setIcon(self.shape_list.icon_for_kind(info.kind))
            tooltip = f"{info.category} · {info.description}"
            item.setData(SHAPE_TOOLTIP_ROLE, tooltip)
            item.setToolTip(tooltip)
            self.shape_list.addItem(item)
        for macro in MACROICON_INVENTORY:
            item = QListWidgetItem(f"Macro · {macro.label}")
            item.setData(Qt.ItemDataRole.UserRole, f"macro:{macro.id}")
            item.setIcon(self.shape_list.icon_for_kind(f"macro:{macro.id}"))
            tooltip = f"Macroicon · {macro.description} · inserted as one undoable command"
            item.setData(SHAPE_TOOLTIP_ROLE, tooltip)
            item.setToolTip(tooltip)
            self.shape_list.addItem(item)
        self.shape_search.textChanged.connect(self._filter_shapes)
        self.shape_list.itemClicked.connect(self._shape_clicked)
        shapes_layout.addWidget(self.shape_search)
        shapes_layout.addWidget(self.shape_list, 1)
        self.shapes_dock.setWidget(shapes_widget)
        place_workbench_dock(self, "shapes", self.shapes_dock)
        self.splitDockWidget(self.project_dock, self.shapes_dock, Qt.Orientation.Vertical)

        self.inspector_dock = QDockWidget("Inspector", self)
        self.inspector_dock.setObjectName("inspectorDock")
        self.inspector = AtomInspector()
        self.inspector.setAccessibleName("Semantic inspector")
        self.inspector.replacementRequested.connect(self._apply_atom_replacement)
        self.inspector_dock.setWidget(self.inspector)
        place_workbench_dock(self, "inspector", self.inspector_dock)
        self.tabifyDockWidget(self.project_dock, self.inspector_dock)

        self.development_dock = QDockWidget("Python Development", self)
        self.development_dock.setObjectName("pythonDevelopmentDock")
        self.development = PythonDevelopmentWidget()
        self.development.setAccessibleName("Python development and diagnostics")
        self.development.generateRequested.connect(self.generate_project)
        self.development.saveGenerateRequested.connect(self.generate_project)
        self.development.validateRequested.connect(self.validate_project_action)
        self.development.revealRequested.connect(self.reveal_generated_folder)
        self.development.diagnosticActivated.connect(self._activate_diagnostic)
        self.development_tabs = self.development.tabs
        self.diagnostics = self.development.diagnostics
        self.artifacts = self.development.artifacts
        self.run_output = self.development.run_output
        self.development_dock.setWidget(self.development)
        place_workbench_dock(self, "development", self.development_dock)

        self.collaboration_dock = QDockWidget("Automation & Collaboration", self)
        self.collaboration_dock.setObjectName("collaborationDock")
        self.collaboration = CollaborationWidget()
        self.collaboration.acceptProposalRequested.connect(self._accept_proposal)
        self.collaboration.rejectProposalRequested.connect(self._reject_proposal)
        self.collaboration_dock.setWidget(self.collaboration)
        place_workbench_dock(self, "collaboration", self.collaboration_dock)

        self.search_dock = QDockWidget("Search & Replace", self)
        self.search_dock.setObjectName("searchDock")
        self.search_widget = ProjectSearchWidget()
        self.search_widget.revealRequested.connect(self._reveal_search_match)
        self.search_widget.projectChanged.connect(self._refresh_project)
        self.search_dock.setWidget(self.search_widget)
        place_workbench_dock(self, "search", self.search_dock)
        self.tabifyDockWidget(self.collaboration_dock, self.search_dock)
        self.search_dock.hide()

        self.navigation_dock = QDockWidget("Semantic Navigation", self)
        self.navigation_dock.setObjectName("semanticNavigationDock")
        self.navigation = SemanticNavigationWidget()
        self.navigation.revealRequested.connect(self._activate_navigation_location)
        self.navigation_dock.setWidget(self.navigation)
        place_workbench_dock(self, "navigation", self.navigation_dock)
        self.tabifyDockWidget(self.search_dock, self.navigation_dock)
        self.navigation_dock.hide()

        self.visualizer_dock = QDockWidget("Code Visualizer", self)
        self.visualizer_dock.setObjectName("codeVisualizerDock")
        self.semantic_visualizer = SemanticVisualizerWidget()
        self.semantic_visualizer.revealRequested.connect(self._reveal_semantic_id)
        self.semantic_visualizer.documentCreated.connect(self._open_created_document)
        self.visualizer_dock.setWidget(self.semantic_visualizer)
        place_workbench_dock(self, "visualizer", self.visualizer_dock)
        self.tabifyDockWidget(self.collaboration_dock, self.visualizer_dock)
        self.visualizer_dock.raise_()
        self.domain_dock = QDockWidget("Domain Workbench", self)
        self.domain_dock.setObjectName("domainWorkbenchDock")
        self.domain_workbench = DomainWorkbenchWidget()
        self.domain_workbench.freezeRequested.connect(self._freeze_computation)
        self.domain_dock.setWidget(self.domain_workbench)
        place_workbench_dock(self, "domains", self.domain_dock)
        self.tabifyDockWidget(self.visualizer_dock, self.domain_dock)
        self.domain_dock.hide()
        self.git_dock = QDockWidget("Git", self)
        self.git_dock.setObjectName("gitWorkbenchDock")
        self.git_workbench = GitWorkbenchWidget()
        self.git_dock.setWidget(self.git_workbench)
        place_workbench_dock(self, "git", self.git_dock)
        self.tabifyDockWidget(self.domain_dock, self.git_dock)
        self.git_dock.hide()
        self.setCorner(Qt.Corner.BottomLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setCorner(Qt.Corner.BottomRightCorner, Qt.DockWidgetArea.RightDockWidgetArea)

    def _create_actions(self) -> None:
        self.action_new = QAction("New Project", self)
        self.action_new.setObjectName("actionNewProject")
        self.action_new.setShortcut(QKeySequence.StandardKey.New)
        self.action_new.triggered.connect(self.new_project)

        self.action_open = QAction("Open Project", self)
        self.action_open.setObjectName("actionOpenProject")
        self.action_open.setShortcut(QKeySequence.StandardKey.Open)
        self.action_open.triggered.connect(self.open_project)

        self.action_save = QAction("Save", self)
        self.action_save.setObjectName("actionSave")
        self.action_save.setShortcut(QKeySequence.StandardKey.Save)
        self.action_save.triggered.connect(self.save_project)

        self.action_save_as = QAction("Save As…", self)
        self.action_save_as.setObjectName("actionSaveAs")
        self.action_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.action_save_as.triggered.connect(self.save_project_as)

        self.action_new_algorithm = QAction("New DRAKON Algorithm", self)
        self.action_new_algorithm.setObjectName("actionNewAlgorithm")
        self.action_new_algorithm.triggered.connect(
            lambda: self.create_document(DocumentKind.DRAKON)
        )
        self.action_new_mind_map = QAction("New Mind Map", self)
        self.action_new_mind_map.setObjectName("actionNewMindMap")
        self.action_new_mind_map.triggered.connect(
            lambda: self.create_document(DocumentKind.MIND_MAP)
        )
        self.action_new_freeform = QAction("New Free-form Canvas", self)
        self.action_new_freeform.setObjectName("actionNewFreeform")
        self.action_new_freeform.triggered.connect(
            lambda: self.create_document(DocumentKind.FREEFORM)
        )
        self.action_export_document = QAction("Export Document…", self)
        self.action_export_document.setObjectName("actionExportDocument")
        self.action_export_document.triggered.connect(self.export_current_document)
        self.action_install_shape_pack = QAction("Install Shape Pack…", self)
        self.action_install_shape_pack.setObjectName("actionInstallShapePack")
        self.action_install_shape_pack.triggered.connect(self.install_shape_pack)

        self.action_undo = QAction("Undo", self)
        self.action_undo.setObjectName("actionUndo")
        self.action_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self.action_undo.triggered.connect(self._undo)

        self.action_redo = QAction("Redo", self)
        self.action_redo.setObjectName("actionRedo")
        self.action_redo.setShortcut(QKeySequence.StandardKey.Redo)
        self.action_redo.triggered.connect(self._redo)

        self.action_cut = QAction("Cut", self)
        self.action_cut.setObjectName("actionCut")
        self.action_cut.setShortcut(QKeySequence.StandardKey.Cut)
        self.action_cut.triggered.connect(self._cut_selection)

        self.action_copy = QAction("Copy", self)
        self.action_copy.setObjectName("actionCopy")
        self.action_copy.setShortcut(QKeySequence.StandardKey.Copy)
        self.action_copy.triggered.connect(self._copy_selection)

        self.action_paste = QAction("Paste", self)
        self.action_paste.setObjectName("actionPaste")
        self.action_paste.setShortcut(QKeySequence.StandardKey.Paste)
        self.action_paste.triggered.connect(self._paste_selection)

        self.action_delete = QAction("Delete Selection", self)
        self.action_delete.setObjectName("actionDeleteSelection")
        self.action_delete.setShortcut(QKeySequence.StandardKey.Delete)
        self.action_delete.triggered.connect(self._remove_selection)

        self.action_duplicate = QAction("Duplicate Selection", self)
        self.action_duplicate.setObjectName("actionDuplicateSelection")
        self.action_duplicate.setShortcut(QKeySequence("Ctrl+D"))
        self.action_duplicate.triggered.connect(self._duplicate_selection)

        self.action_convert_statement = QAction("Convert Python Statement to Typed Icon", self)
        self.action_convert_statement.setObjectName("actionConvertStatement")
        self.action_convert_statement.triggered.connect(self._convert_selected_statement)

        self.action_move_up = QAction("Move Selection Up", self)
        self.action_move_up.setObjectName("actionMoveSelectionUp")
        self.action_move_up.setShortcut(QKeySequence("Alt+Up"))
        self.action_move_up.triggered.connect(lambda: self._move_selection_by(-1))
        self.action_move_down = QAction("Move Selection Down", self)
        self.action_move_down.setObjectName("actionMoveSelectionDown")
        self.action_move_down.setShortcut(QKeySequence("Alt+Down"))
        self.action_move_down.triggered.connect(lambda: self._move_selection_by(1))
        self.action_previous_insertion = QAction("Previous Insertion Target", self)
        self.action_previous_insertion.setObjectName("actionPreviousInsertionTarget")
        self.action_previous_insertion.setShortcut(QKeySequence("Ctrl+Alt+["))
        self.action_previous_insertion.triggered.connect(
            lambda: self._cycle_insertion_target(False)
        )
        self.action_next_insertion = QAction("Next Insertion Target", self)
        self.action_next_insertion.setObjectName("actionNextInsertionTarget")
        self.action_next_insertion.setShortcut(QKeySequence("Ctrl+Alt+]"))
        self.action_next_insertion.triggered.connect(lambda: self._cycle_insertion_target(True))

        self.action_palette = QAction("Command Palette", self)
        self.action_palette.setObjectName("actionCommandPalette")
        self.action_palette.setShortcut(QKeySequence("Ctrl+Shift+P"))
        self.action_palette.triggered.connect(self.show_command_palette)

        self.action_find = QAction("Find in Project", self)
        self.action_find.setObjectName("actionFindInProject")
        self.action_find.setShortcut(QKeySequence.StandardKey.Find)
        self.action_find.triggered.connect(self.show_project_search)
        self.action_replace = QAction("Replace in Project", self)
        self.action_replace.setObjectName("actionReplaceInProject")
        self.action_replace.setShortcut(QKeySequence("Ctrl+H"))
        self.action_replace.triggered.connect(
            lambda _checked=False: self.show_project_search(replace=True)
        )

        self.action_navigation_back = QAction("Navigation Back", self)
        self.action_navigation_back.setObjectName("actionNavigationBack")
        self.action_navigation_back.setShortcut(QKeySequence("Alt+Left"))
        self.action_navigation_back.triggered.connect(self.navigate_back)
        self.action_navigation_forward = QAction("Navigation Forward", self)
        self.action_navigation_forward.setObjectName("actionNavigationForward")
        self.action_navigation_forward.setShortcut(QKeySequence("Alt+Right"))
        self.action_navigation_forward.triggered.connect(self.navigate_forward)
        self.action_find_callers = QAction("Find Callers", self)
        self.action_find_callers.setObjectName("actionFindCallers")
        self.action_find_callers.triggered.connect(self.show_find_callers)
        self.action_find_addresses = QAction("Find Address Transitions", self)
        self.action_find_addresses.setObjectName("actionFindAddressTransitions")
        self.action_find_addresses.triggered.connect(self.show_find_address_transitions)
        self.action_call_hierarchy = QAction("Call Hierarchy", self)
        self.action_call_hierarchy.setObjectName("actionCallHierarchy")
        self.action_call_hierarchy.triggered.connect(self.show_call_hierarchy)
        self._update_navigation_actions()

        self.action_generate = QAction("Generate Project", self)
        self.action_generate.setObjectName("actionGenerate")
        self.action_generate.setShortcut(QKeySequence("Ctrl+G"))
        self.action_generate.triggered.connect(self.generate_project)

        self.action_run = QAction("Run Project", self)
        self.action_run.setObjectName("actionRunProject")
        self.action_run.setShortcut(QKeySequence("F5"))
        self.action_run.triggered.connect(self.run_project)
        self.action_stop_project = QAction("Stop Project", self)
        self.action_stop_project.setShortcut(QKeySequence("Shift+F5"))
        self.action_stop_project.setEnabled(False)
        self.action_stop_project.triggered.connect(self.stop_project)
        self.action_entrypoint = QAction("Project Entry Point...", self)
        self.action_entrypoint.triggered.connect(self.show_entrypoint)
        self.action_close_project = QAction("Close Project / Return to Examples", self)
        self.action_close_project.setObjectName("actionCloseProject")
        self.action_close_project.triggered.connect(self.close_project)

        self.action_run_current = QAction("Run Function", self)
        self.action_run_current.setObjectName("actionRunCurrent")
        self.action_run_current.setShortcut(QKeySequence("F6"))
        self.action_run_current.triggered.connect(self.run_current_document)

        self.action_trace_current = QAction("Trace Function", self)
        self.action_trace_current.setObjectName("actionTraceCurrent")
        self.action_trace_current.setShortcut(QKeySequence("F7"))
        self.action_trace_current.triggered.connect(self.trace_current_document)

        self.action_debug_current = QAction("Debug Function", self)
        self.action_debug_current.setObjectName("actionDebugCurrent")
        self.action_debug_current.triggered.connect(self.debug_current_document)

        self.action_stop_current = QAction("Stop Function", self)
        self.action_stop_current.setObjectName("actionStopCurrent")
        self.action_stop_current.setShortcut(QKeySequence("Shift+F6"))
        self.action_stop_current.triggered.connect(self.stop_current_document)

        self.action_validate = QAction("Validate Project", self)
        self.action_validate.setObjectName("actionValidateProject")
        self.action_validate.setShortcut(QKeySequence("Ctrl+Shift+V"))
        self.action_validate.triggered.connect(self.validate_project_action)

        self.action_python_project = QAction("Python Project", self)
        self.action_python_project.setObjectName("actionPythonProject")
        self.action_python_project.setShortcut(QKeySequence("Ctrl+Shift+M"))
        self.action_python_project.triggered.connect(self.open_python_project)

        self.action_reveal_artifacts = QAction("Open Generated Folder", self)
        self.action_reveal_artifacts.setObjectName("actionRevealArtifacts")
        self.action_reveal_artifacts.setEnabled(False)
        self.action_reveal_artifacts.triggered.connect(self.reveal_generated_folder)

        self.action_detach_document = QAction("Detach Document", self)
        self.action_detach_document.setObjectName("actionDetachDocument")
        self.action_detach_document.setShortcut(QKeySequence("Ctrl+Shift+D"))
        self.action_detach_document.triggered.connect(self.detach_current_document)

        self.action_insert = QAction("Insert…", self)
        self.action_insert.setObjectName("actionInsert")
        self.action_insert.triggered.connect(self._focus_shapes)

        self.action_automation_access = self.collaboration_dock.toggleViewAction()
        self.action_automation_access.setText("Automation Access")
        self.action_automation_access.setObjectName("actionAutomationAccess")

        self.action_reset_workspace = QAction("Reset Workspace Layout", self)
        self.action_reset_workspace.setObjectName("actionResetWorkspace")
        self.action_reset_workspace.triggered.connect(self.reset_workspace)

        self.action_tidy_diagram = QAction("Tidy and Fit Diagram", self)
        self.action_tidy_diagram.setObjectName("actionTidyDiagram")
        self.action_tidy_diagram.setShortcut(QKeySequence("Ctrl+Shift+L"))
        self.action_tidy_diagram.triggered.connect(self._tidy_document)

        self.theme_actions: dict[ThemeName, QAction] = {}
        self.theme_action_group = QActionGroup(self)
        self.theme_action_group.setExclusive(True)
        for theme, label in (
            (ThemeName.CLASSIC, "Classic IDE / DRAKON"),
            (ThemeName.LIGHT, "Light"),
            (ThemeName.DARK, "Dark"),
            (ThemeName.HIGH_CONTRAST, "High Contrast"),
        ):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(theme is self._theme)
            action.triggered.connect(
                lambda _checked=False, selected=theme: self._select_theme(selected)
            )
            self.theme_action_group.addAction(action)
            self.theme_actions[theme] = action
        self.action_reduced_motion = QAction("Reduced Motion", self)
        self.action_reduced_motion.setCheckable(True)
        self.action_reduced_motion.setChecked(self._reduced_motion)
        self.action_reduced_motion.toggled.connect(self._set_reduced_motion)

        for action in (
            self.action_new,
            self.action_open,
            self.action_save,
            self.action_save_as,
            self.action_new_algorithm,
            self.action_new_mind_map,
            self.action_new_freeform,
            self.action_export_document,
            self.action_install_shape_pack,
            self.action_undo,
            self.action_redo,
            self.action_cut,
            self.action_copy,
            self.action_paste,
            self.action_delete,
            self.action_duplicate,
            self.action_convert_statement,
            self.action_move_up,
            self.action_move_down,
            self.action_previous_insertion,
            self.action_next_insertion,
            self.action_palette,
            self.action_find,
            self.action_replace,
            self.action_navigation_back,
            self.action_navigation_forward,
            self.action_find_callers,
            self.action_find_addresses,
            self.action_call_hierarchy,
            self.action_generate,
            self.action_run,
            self.action_run_current,
            self.action_trace_current,
            self.action_debug_current,
            self.action_stop_current,
            self.action_validate,
            self.action_python_project,
            self.action_reveal_artifacts,
            self.action_detach_document,
            self.action_insert,
            self.action_automation_access,
            self.action_reset_workspace,
            self.action_tidy_diagram,
            self.action_reduced_motion,
            *self.theme_actions.values(),
        ):
            self.addAction(action)

    def _create_menus_and_toolbar(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(self.action_new)
        file_menu.addAction(self.action_open)
        file_menu.addAction(self.action_save)
        file_menu.addAction(self.action_save_as)
        file_menu.addAction(self.action_close_project)
        physical_menu = file_menu.addMenu("Physical examples")
        from code_visualizer.application.examples import PHYSICAL_EXAMPLE_CATALOG

        for definition in PHYSICAL_EXAMPLE_CATALOG:
            action = physical_menu.addAction(definition.label)
            action.triggered.connect(partial(self._open_example, definition.id))

        document_menu = self.menuBar().addMenu("&Document")
        document_menu.addAction(self.action_new_algorithm)
        document_menu.addAction(self.action_new_mind_map)
        document_menu.addAction(self.action_new_freeform)
        document_menu.addSeparator()
        document_menu.addAction(self.action_export_document)
        document_menu.addAction(self.action_install_shape_pack)

        edit_menu = self.menuBar().addMenu("&Edit")
        edit_menu.addAction(self.action_undo)
        edit_menu.addAction(self.action_redo)
        edit_menu.addSeparator()
        edit_menu.addAction(self.action_cut)
        edit_menu.addAction(self.action_copy)
        edit_menu.addAction(self.action_paste)
        edit_menu.addSeparator()
        edit_menu.addAction(self.action_delete)
        edit_menu.addAction(self.action_duplicate)
        edit_menu.addAction(self.action_convert_statement)
        edit_menu.addAction(self.action_move_up)
        edit_menu.addAction(self.action_move_down)
        edit_menu.addAction(self.action_previous_insertion)
        edit_menu.addAction(self.action_next_insertion)
        edit_menu.addSeparator()
        edit_menu.addAction(self.action_palette)
        edit_menu.addAction(self.action_insert)
        edit_menu.addSeparator()
        edit_menu.addAction(self.action_find)
        edit_menu.addAction(self.action_replace)

        navigate_menu = self.menuBar().addMenu("&Navigate")
        navigate_menu.addAction(self.action_navigation_back)
        navigate_menu.addAction(self.action_navigation_forward)
        navigate_menu.addSeparator()
        navigate_menu.addAction(self.action_find_callers)
        navigate_menu.addAction(self.action_find_addresses)
        navigate_menu.addAction(self.action_call_hierarchy)

        python_menu = self.menuBar().addMenu("&Python")
        python_menu.addAction(self.action_python_project)
        python_menu.addAction(self.action_entrypoint)
        python_menu.addAction(self.action_validate)
        python_menu.addAction(self.action_generate)
        python_menu.addAction(self.action_reveal_artifacts)

        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction(self.action_detach_document)
        view_menu.addAction(self.action_automation_access)
        view_menu.addAction(self.action_reset_workspace)
        view_menu.addAction(self.action_tidy_diagram)
        theme_menu = view_menu.addMenu("Theme")
        theme_menu.addActions(self.theme_action_group.actions())
        view_menu.addAction(self.action_reduced_motion)
        view_menu.addSeparator()
        for dock in view_menu_docks(self):
            view_menu.addAction(dock.toggleViewAction())
        view_menu.addSeparator()
        for label, mode in (
            ("Diagram only", "diagram"),
            ("Code only", "code"),
            ("Side by side", "side_by_side"),
            ("Stacked", "stacked"),
            ("Tabbed inner views", "tabbed"),
        ):
            action = view_menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, selected=mode: self._set_document_layout(selected)
            )
        view_menu.addAction("Fit diagram (0)", self._fit_document)

        test_menu = self.menuBar().addMenu("&Test")
        test_menu.addAction(self.action_run_current)
        test_menu.addAction(self.action_trace_current)
        test_menu.addAction(self.action_debug_current)
        test_menu.addAction(self.action_stop_current)
        test_menu.addAction(self.action_generate)
        test_menu.addAction(self.action_run)
        test_menu.addAction(self.action_stop_project)

        toolbar = QToolBar("Main", self)
        toolbar.setObjectName("mainToolbar")
        toolbar.setAccessibleName("Main project and development actions")
        toolbar.addAction(self.action_new)
        toolbar.addAction(self.action_open)
        toolbar.addAction(self.action_save)
        toolbar.addSeparator()
        toolbar.addAction(self.action_undo)
        toolbar.addAction(self.action_redo)
        toolbar.addSeparator()
        toolbar.addAction(self.action_palette)
        toolbar.addAction(self.action_insert)
        toolbar.addSeparator()
        toolbar.addAction(self.action_generate)
        toolbar.addAction(self.action_validate)
        toolbar.addAction(self.action_run)
        toolbar.addAction(self.action_stop_project)

        self.addToolBar(toolbar)

    def _register_commands(self) -> None:
        specs = (
            CommandSpec(
                "git.show_workbench",
                "Open Git",
                "Git",
                "Review changes, commit, browse history and collaborate through Git branches",
                self._show_git_workbench,
                is_enabled=lambda: self._session is not None,
                disabled_reason=lambda: "Open a project first",
            ),
            CommandSpec(
                "domain.show_workbench",
                "Open Domain Workbench",
                "Domains",
                "Define concepts, properties and roles; edit objects through graph, table and form",
                self._show_domain_workbench,
                is_enabled=lambda: self._session is not None,
                disabled_reason=lambda: "Open a project first",
            ),
            CommandSpec(
                "domain.new_schema",
                "Define New Domain",
                "Domains",
                "Create a schema with typed properties, containment and reference roles",
                self.domain_workbench.new_schema,
                is_enabled=lambda: self._session is not None,
                disabled_reason=lambda: "Open a project first",
            ),
            CommandSpec(
                "project.new",
                "New Project",
                "Project",
                "Create a blank project with an editable main algorithm",
                self.new_project,
                "Ctrl+N",
            ),
            CommandSpec(
                "project.open",
                "Open Project",
                "Project",
                "Open a saved native project directory",
                self.open_project,
                "Ctrl+O",
            ),
            CommandSpec(
                "diagram.create_drakon",
                "New DRAKON Algorithm",
                "Document",
                "Create an empty typed Python algorithm",
                lambda: self.create_document(DocumentKind.DRAKON),
                is_enabled=lambda: self._session is not None,
                disabled_reason=lambda: "Open a project first",
            ),
            CommandSpec(
                "diagram.create_mind_map",
                "New Mind Map",
                "Document",
                "Create an ordered rooted knowledge map",
                lambda: self.create_document(DocumentKind.MIND_MAP),
                is_enabled=lambda: self._session is not None,
                disabled_reason=lambda: "Open a project first",
            ),
            CommandSpec(
                "diagram.create_freeform",
                "New Free-form Canvas",
                "Document",
                "Create a conventional vector drawing document",
                lambda: self.create_document(DocumentKind.FREEFORM),
                is_enabled=lambda: self._session is not None,
                disabled_reason=lambda: "Open a project first",
            ),
            *(
                CommandSpec(
                    f"visualizer.show_{projection.value}",
                    f"Show {projection.value.replace('_', ' ').title()} Lens",
                    "Code Visualizer",
                    "Open a disposable semantic projection over the current canonical revision",
                    partial(self._show_semantic_projection, projection),
                    is_enabled=lambda: self._session is not None,
                    disabled_reason=lambda: "Open a project first",
                )
                for projection in (
                    ProjectionKind.ARCHITECTURE,
                    ProjectionKind.CALLS,
                    ProjectionKind.CONTROL,
                    ProjectionKind.DATA,
                    ProjectionKind.CONCEPTS,
                    ProjectionKind.RUNTIME,
                )
            ),
            CommandSpec(
                "visualizer.compose_lens",
                "Compose Semantic Lens",
                "Code Visualizer",
                "Choose scope, relations, grouping, decoration, labels, and layout without code",
                self.semantic_visualizer.compose_lens,
                is_enabled=lambda: self._session is not None,
                disabled_reason=lambda: "Open a project first",
            ),
            CommandSpec(
                "visualizer.show_semantic_text",
                "Show Semantic Text Editor",
                "Code Visualizer",
                "Read the current lens as text and edit selected canonical fields by command",
                self._show_semantic_text,
                is_enabled=lambda: self._session is not None,
                disabled_reason=lambda: "Open a project first",
            ),
            CommandSpec(
                "visualizer.group_concept",
                "Group Selection as Semantic Concept",
                "Code Visualizer",
                "Record why selected program elements belong together without moving modules",
                self.semantic_visualizer.group_selection_as_concept,
                is_enabled=lambda: self.semantic_visualizer.concept_button.isEnabled(),
                disabled_reason=lambda: "Select one or more semantic objects in the visualizer",
            ),
            CommandSpec(
                "visualizer.relate_selection",
                "Relate Semantic Selection",
                "Code Visualizer",
                "Describe a typed author-owned relationship between two selected objects",
                self.semantic_visualizer.relate_selection,
                is_enabled=lambda: self.semantic_visualizer.relate_button.isEnabled(),
                disabled_reason=lambda: "Select exactly two semantic objects in the visualizer",
            ),
            CommandSpec(
                "visualizer.make_mind_map",
                "Make Mind Map from Current Lens",
                "Code Visualizer",
                "Create an editable mind map with semantic topic and relationship anchors",
                self.semantic_visualizer.make_mind_map,
                is_enabled=lambda: self.semantic_visualizer.mind_map_button.isEnabled(),
                disabled_reason=lambda: "Choose a non-empty static semantic lens",
            ),
            CommandSpec(
                "visualizer.make_canvas",
                "Make Canvas from Current Lens",
                "Code Visualizer",
                "Create an editable freeform composition with semantic shape and arrow anchors",
                self.semantic_visualizer.make_canvas,
                is_enabled=lambda: self.semantic_visualizer.canvas_button.isEnabled(),
                disabled_reason=lambda: "Choose a non-empty static semantic lens",
            ),
            CommandSpec(
                "diagram.export",
                "Export Current Document",
                "Document",
                "Export the complete off-screen scene as SVG, PNG, or PDF",
                self.export_current_document,
                is_enabled=lambda: self._current_editor() is not None,
                disabled_reason=lambda: "Open a project document first",
            ),
            CommandSpec(
                "assets.install_shape_pack",
                "Install Visual Shape Pack",
                "Assets",
                "Install a versioned manifest after sanitizing every SVG as passive visual content",
                self.install_shape_pack,
                is_enabled=lambda: self._session is not None,
                disabled_reason=lambda: "Open a project first",
            ),
            CommandSpec(
                "project.save",
                "Save Project",
                "Project",
                "Save or choose the canonical project directory",
                self._save_from_command,
                "Ctrl+S",
                lambda: self._session is not None,
                lambda: "No project is open",
            ),
            CommandSpec(
                "project.save_as",
                "Save Project As",
                "Project",
                "Fork the current snapshot into a new editable native project directory",
                self._save_as_from_command,
                "Ctrl+Shift+S",
                lambda: self._session is not None,
                lambda: "No project is open",
            ),
            CommandSpec(
                "history.undo",
                "Undo",
                "Edit",
                "Undo the latest compatible command by this actor",
                self._undo,
                "Ctrl+Z",
                lambda: self._session is not None,
                lambda: "No project is open",
            ),
            CommandSpec(
                "history.redo",
                "Redo",
                "Edit",
                "Redo the latest command undone by this actor",
                self._redo,
                "Ctrl+Shift+Z",
                lambda: self._session is not None,
                lambda: "No project is open",
            ),
            CommandSpec(
                "edit.copy_semantic",
                "Copy Semantic Selection",
                "Edit",
                "Copy a versioned semantic fragment and a readable text summary",
                self._copy_selection,
                "Ctrl+C",
                self._has_semantic_selection,
                lambda: "Select a diagram object or contiguous DRAKON block",
            ),
            CommandSpec(
                "edit.cut_semantic",
                "Cut Semantic Selection",
                "Edit",
                "Copy a semantic fragment, then perform one structural deletion",
                self._cut_selection,
                "Ctrl+X",
                self._has_semantic_selection,
                lambda: "Select a non-root diagram object or contiguous block",
            ),
            CommandSpec(
                "edit.paste_semantic",
                "Paste Semantic Fragment",
                "Edit",
                "Paste with fresh IDs at a compatible boundary and report unresolved references",
                self._paste_selection,
                "Ctrl+V",
                lambda: self._session is not None,
                lambda: "Open a project first",
            ),
            CommandSpec(
                "search.find_project",
                "Find in Project",
                "Search",
                "Search names, Python fields, topics, Python runtime settings, and canvas text",
                self.show_project_search,
                "Ctrl+F",
                lambda: self._session is not None,
                lambda: "No project is open",
            ),
            CommandSpec(
                "search.replace_project",
                "Replace in Project",
                "Search",
                "Preview semantic fields and commit Replace All as one transaction",
                partial(self.show_project_search, replace=True),
                "Ctrl+H",
                lambda: self._session is not None,
                lambda: "No project is open",
            ),
            CommandSpec(
                "navigation.back",
                "Navigation Back",
                "Navigation",
                "Return to the previous revealed semantic object without changing history",
                self.navigate_back,
                "Alt+Left",
                lambda: self._navigation_history.can_go_back,
                lambda: "No earlier navigation location",
            ),
            CommandSpec(
                "navigation.forward",
                "Navigation Forward",
                "Navigation",
                "Move forward through semantic reveal history without changing the project",
                self.navigate_forward,
                "Alt+Right",
                lambda: self._navigation_history.can_go_forward,
                lambda: "No later navigation location",
            ),
            CommandSpec(
                "navigation.find_callers",
                "Find Callers",
                "Navigation",
                "Find linked Call icons by stable target diagram ID",
                self.show_find_callers,
                is_enabled=self._has_active_drakon,
                disabled_reason=lambda: "Open a DRAKON document first",
            ),
            CommandSpec(
                "navigation.find_addresses",
                "Find Address Transitions",
                "Navigation",
                "List silhouette Address transitions by stable branch IDs",
                self.show_find_address_transitions,
                is_enabled=self._has_active_drakon,
                disabled_reason=lambda: "Open a DRAKON document first",
            ),
            CommandSpec(
                "navigation.call_hierarchy",
                "Call Hierarchy",
                "Navigation",
                "Show stable linked calls and finite recursion cycle markers",
                self.show_call_hierarchy,
                is_enabled=self._has_active_drakon,
                disabled_reason=lambda: "Open a DRAKON document first",
            ),
            CommandSpec(
                "drakon.delete_selection",
                "Delete Selected Block",
                "DRAKON Structure",
                "Splice one contiguous selected block without losing hidden bodies",
                self._remove_selection,
                "Delete",
                self._has_structural_selection,
                lambda: "Select one contiguous DRAKON block",
            ),
            CommandSpec(
                "drakon.duplicate_selection",
                "Duplicate Selected Block",
                "DRAKON Structure",
                "Clone the complete selected structure with fresh stable IDs",
                self._duplicate_selection,
                "Ctrl+D",
                self._has_structural_selection,
                lambda: "Select one contiguous DRAKON block",
            ),
            CommandSpec(
                "drakon.edit_primary",
                "Edit Selected Primary Field",
                "DRAKON Structure",
                "Open the typed Inspector directly on the selected operation's primary field",
                lambda: self._edit_selected_field(False),
                "F2",
                self._has_single_structural_selection,
                lambda: "Select one DRAKON operation",
            ),
            CommandSpec(
                "drakon.edit_secondary",
                "Edit Selected Secondary Field",
                "DRAKON Structure",
                "Open the typed Inspector directly on the selected operation's secondary field",
                lambda: self._edit_selected_field(True),
                "F3",
                self._has_single_structural_selection,
                lambda: "Select one operation with a secondary semantic field",
            ),
            CommandSpec(
                "drakon.convert_statement",
                "Convert Python Statement to Typed Icon",
                "DRAKON Structure",
                "Parse one Action or Expression and preserve its stable ID as a typed icon",
                self._convert_selected_statement,
                is_enabled=self._has_convertible_statement,
                disabled_reason=lambda: "Select one Action or Expression icon",
            ),
            CommandSpec(
                "drakon.move_selection_up",
                "Move Selected Block Up",
                "DRAKON Structure",
                "Move the contiguous block one semantic position earlier as one revision",
                lambda: self._move_selection_by(-1),
                "Alt+Up",
                self._has_structural_selection,
                lambda: "Select one contiguous DRAKON block",
            ),
            CommandSpec(
                "drakon.move_selection_down",
                "Move Selected Block Down",
                "DRAKON Structure",
                "Move the contiguous block one semantic position later as one revision",
                lambda: self._move_selection_by(1),
                "Alt+Down",
                self._has_structural_selection,
                lambda: "Select one contiguous DRAKON block",
            ),
            CommandSpec(
                "drakon.previous_insertion_target",
                "Previous Insertion Target",
                "DRAKON Structure",
                "Cycle backward through visible typed connector boundaries",
                lambda: self._cycle_insertion_target(False),
                "Ctrl+Alt+[",
                self._has_active_drakon,
                lambda: "Open a DRAKON document first",
            ),
            CommandSpec(
                "drakon.next_insertion_target",
                "Next Insertion Target",
                "DRAKON Structure",
                "Cycle forward through visible typed connector boundaries",
                lambda: self._cycle_insertion_target(True),
                "Ctrl+Alt+]",
                self._has_active_drakon,
                lambda: "Open a DRAKON document first",
            ),
            CommandSpec(
                "drakon.wrap_if",
                "Wrap Selection in If",
                "DRAKON Structure",
                "Move the selected block into the preferred body of a new If",
                partial(self._wrap_selection, "if"),
                is_enabled=self._has_structural_selection,
                disabled_reason=lambda: "Select one contiguous DRAKON block",
            ),
            CommandSpec(
                "drakon.wrap_loop",
                "Wrap Selection in For Loop",
                "DRAKON Structure",
                "Move the selected block into a new iterable For body",
                partial(self._wrap_selection, "for_loop"),
                is_enabled=self._has_structural_selection,
                disabled_reason=lambda: "Select one contiguous DRAKON block",
            ),
            CommandSpec(
                "drakon.wrap_select",
                "Wrap Selection in Select",
                "DRAKON Structure",
                "Move the selected block into the preferred Case of a new Select",
                partial(self._wrap_selection, "select"),
                is_enabled=self._has_structural_selection,
                disabled_reason=lambda: "Select one contiguous DRAKON block",
            ),
            CommandSpec(
                "drakon.wrap_try",
                "Wrap Selection in Try",
                "DRAKON Structure",
                "Move the selected block into a structured Try body",
                partial(self._wrap_selection, "try"),
                is_enabled=self._has_structural_selection,
                disabled_reason=lambda: "Select one contiguous DRAKON block",
            ),
            CommandSpec(
                "drakon.wrap_with",
                "Wrap Selection in With",
                "DRAKON Structure",
                "Move the selected block into a context-manager body",
                partial(self._wrap_selection, "with"),
                is_enabled=self._has_structural_selection,
                disabled_reason=lambda: "Select one contiguous DRAKON block",
            ),
            CommandSpec(
                "drakon.wrap_parallel",
                "Wrap Selection in Parallel",
                "DRAKON Structure",
                "Move the selected block into the first named process",
                partial(self._wrap_selection, "parallel"),
                is_enabled=self._has_structural_selection,
                disabled_reason=lambda: "Select one contiguous DRAKON block",
            ),
            CommandSpec(
                "drakon.wrap_timed",
                "Wrap Selection in Timed Synchronizer",
                "DRAKON Structure",
                "Move the selected block into the preferred on-time route of a Synchronizer",
                partial(self._wrap_selection, "synchronizer"),
                is_enabled=self._has_structural_selection,
                disabled_reason=lambda: "Select one contiguous DRAKON block",
            ),
            CommandSpec(
                "drakon.unwrap_selection",
                "Unwrap Selected Construct",
                "DRAKON Structure",
                "Splice one owned body into the parent and explicitly guard other content",
                self._unwrap_selection,
                is_enabled=self._has_single_structural_selection,
                disabled_reason=lambda: "Select one composite DRAKON construct",
            ),
            CommandSpec(
                "drakon.toggle_preferred_route",
                "Toggle If Preferred Route",
                "DRAKON Structure",
                "Change which truth route stays on the downward happy path",
                self._toggle_if_preferred,
                is_enabled=self._selected_if_exists,
                disabled_reason=lambda: "Select one If construct",
            ),
            CommandSpec(
                "drakon.swap_outcomes",
                "Swap If Outcomes",
                "DRAKON Structure",
                "Swap truth bindings while keeping the visible preferred body downward",
                self._swap_if_outcomes,
                is_enabled=self._selected_if_exists,
                disabled_reason=lambda: "Select one If construct",
            ),
            CommandSpec(
                "drakon.insert_output",
                "Insert Output",
                "DRAKON",
                "Insert a typed Output operation at the current sequence boundary",
                lambda: self._insert_atom("output"),
                is_enabled=self._has_active_drakon,
                disabled_reason=lambda: "Open a DRAKON document first",
            ),
            CommandSpec(
                "drakon.insert_action",
                "Insert Action",
                "DRAKON",
                "Insert a Python action without opening a modal",
                lambda: self._insert_atom("action"),
                is_enabled=self._has_active_drakon,
                disabled_reason=lambda: "Open a DRAKON document first",
            ),
            CommandSpec(
                "drakon.insert_assignment",
                "Insert Assignment Shelf",
                "DRAKON",
                "Insert a typed target/value assignment",
                lambda: self._insert_atom("assignment"),
                is_enabled=self._has_active_drakon,
                disabled_reason=lambda: "Open a DRAKON document first",
            ),
            CommandSpec(
                "drakon.insert_if",
                "Insert If",
                "DRAKON",
                "Insert a structured If with valid branch actions",
                lambda: self._insert_atom("if"),
                is_enabled=self._has_active_drakon,
                disabled_reason=lambda: "Open a DRAKON document first",
            ),
            CommandSpec(
                "python.project",
                "Python Project",
                "Python",
                "Edit modules, imports, constants, helpers, entry point, and run profile",
                self.open_python_project,
                "Ctrl+Shift+M",
                lambda: self._session is not None,
                lambda: "No project is open",
            ),
            CommandSpec(
                "python.validate",
                "Validate Project",
                "Python",
                "Refresh actionable project and Python diagnostics",
                self.validate_project_action,
                "Ctrl+Shift+V",
                lambda: self._session is not None,
                lambda: "No project is open",
            ),
            CommandSpec(
                "python.generate",
                "Generate Project",
                "Python",
                "Atomically generate the complete saved project",
                self._generate_from_command,
                "Ctrl+G",
                lambda: self._session is not None,
                lambda: "No project is open",
            ),
            CommandSpec(
                "python.run_current",
                "Run Function",
                "Python",
                "Run the selected in-memory callable",
                self.run_current_document,
                "F6",
                self._has_active_drakon,
                lambda: "Open a DRAKON document first",
            ),
            CommandSpec(
                "python.trace_current",
                "Trace Function",
                "Python",
                "Run the selected callable and map bounded trace events back to nodes",
                self.trace_current_document,
                "F7",
                self._has_active_drakon,
                lambda: "Open a DRAKON document first",
            ),
            CommandSpec(
                "python.debug_current",
                "Debug Function",
                "Python",
                "Start interactive source-mapped debugging for the selected callable",
                self.debug_current_document,
                is_enabled=self._has_active_drakon,
                disabled_reason=lambda: "Open a DRAKON document first",
            ),
            CommandSpec(
                "python.stop_current",
                "Stop Function Run or Debug Session",
                "Python",
                "Stop the active per-document child process",
                self.stop_current_document,
                "Shift+F6",
                self._has_active_drakon,
                lambda: "Open a DRAKON document first",
            ),
            CommandSpec(
                "document.detach",
                "Detach Document",
                "Document",
                "Move the complete diagram, code, and test surface into its own window",
                self.detach_current_document,
                "Ctrl+Shift+D",
                self._has_active_drakon,
                lambda: "Open a DRAKON document first",
            ),
            CommandSpec(
                "document.layout_diagram",
                "Show Diagram Only",
                "Document",
                "Use the complete document with its diagram comparison pane visible",
                partial(self._set_document_layout, "diagram"),
                is_enabled=self._has_active_drakon,
                disabled_reason=lambda: "Open a DRAKON document first",
            ),
            CommandSpec(
                "document.layout_code",
                "Show Code Only",
                "Document",
                "Use the complete document with generated Python visible",
                partial(self._set_document_layout, "code"),
                is_enabled=self._has_active_drakon,
                disabled_reason=lambda: "Open a DRAKON document first",
            ),
            CommandSpec(
                "document.layout_side_by_side",
                "Compare Diagram and Code Side by Side",
                "Document",
                "Keep diagram, generated code, and live test in one horizontal comparison",
                partial(self._set_document_layout, "side_by_side"),
                is_enabled=self._has_active_drakon,
                disabled_reason=lambda: "Open a DRAKON document first",
            ),
            CommandSpec(
                "document.layout_stacked",
                "Compare Diagram and Code Stacked",
                "Document",
                "Keep diagram, generated code, and live test in one vertical comparison",
                partial(self._set_document_layout, "stacked"),
                is_enabled=self._has_active_drakon,
                disabled_reason=lambda: "Open a DRAKON document first",
            ),
            CommandSpec(
                "document.layout_tabbed",
                "Compare Diagram and Code in Inner Tabs",
                "Document",
                "Keep non-detachable diagram and code panes as tabs in the complete document",
                partial(self._set_document_layout, "tabbed"),
                is_enabled=self._has_active_drakon,
                disabled_reason=lambda: "Open a DRAKON document first",
            ),
            CommandSpec(
                "python.run_project",
                "Run Generated Project",
                "Python",
                "Run the current manifest-backed generated entry point",
                self.run_project,
                "F5",
                lambda: self._session is not None,
                lambda: "No project is open",
            ),
            CommandSpec(
                "python.reveal_artifacts",
                "Open Generated Folder",
                "Python",
                "Reveal the last complete generated artifact set",
                self.reveal_generated_folder,
                is_enabled=self._has_generated_manifest,
                disabled_reason=lambda: "Generate a complete valid revision first",
            ),
            CommandSpec(
                "automation.show_access",
                "Show Automation Access",
                "Collaboration",
                "Reveal endpoint access, live actors, conflicts, and pending proposals",
                self.show_automation_access,
                is_enabled=lambda: self._automation_host is not None,
                disabled_reason=lambda: "Open a project first",
            ),
            CommandSpec(
                "workspace.reset",
                "Reset Workspace",
                "View",
                "Restore Project, Shapes, lower-left Inspector, development, and side docks",
                self.reset_workspace,
            ),
            CommandSpec(
                "drakon.tidy",
                "Tidy and Fit Diagram",
                "View",
                "Recompute the deterministic derived layout and fit every route and label",
                self._tidy_document,
                "Ctrl+Shift+L",
                self._has_active_drakon,
                lambda: "Open a DRAKON document first",
            ),
        )
        for spec in specs:
            self._registry.register(spec)
        for theme, label in (
            (ThemeName.CLASSIC, "Classic IDE / DRAKON"),
            (ThemeName.LIGHT, "Light"),
            (ThemeName.DARK, "Dark"),
            (ThemeName.HIGH_CONTRAST, "High Contrast"),
        ):
            self._registry.register(
                CommandSpec(
                    f"appearance.theme_{theme.value}",
                    f"Use {label} Theme",
                    "Accessibility",
                    "Change color tokens without changing semantic geometry",
                    partial(self._select_theme, theme),
                )
            )
        self._registry.register(
            CommandSpec(
                "appearance.toggle_reduced_motion",
                "Toggle Reduced Motion",
                "Accessibility",
                "Suppress nonessential motion and animated transitions",
                lambda: self.action_reduced_motion.toggle(),
            )
        )
        core_kinds = {"action", "assignment", "if", "output"}
        for info in ATOM_KIND_INVENTORY:
            if info.kind in core_kinds:
                continue
            self._registry.register(
                CommandSpec(
                    f"drakon.insert_{info.kind}",
                    f"Insert {info.label}",
                    "DRAKON",
                    info.description,
                    partial(self._insert_atom, info.kind),
                    is_enabled=partial(self._atom_kind_available, info.kind),
                    disabled_reason=partial(self._atom_kind_disabled_reason, info.kind),
                )
            )
        for macro in MACROICON_INVENTORY:
            self._registry.register(
                CommandSpec(
                    f"drakon.macro_{macro.id}",
                    f"Insert Macro · {macro.label}",
                    "DRAKON Macroicons",
                    macro.description,
                    partial(self._insert_atom, f"macro:{macro.id}"),
                    is_enabled=self._has_active_drakon,
                    disabled_reason=lambda: "Open a DRAKON document first",
                )
            )

    def _connect_welcome(self) -> None:
        self.welcome.newRequested.connect(self.new_project)
        self.welcome.helloRequested.connect(lambda: self.new_project(hello_world=True))
        self.welcome.openRequested.connect(self.open_project)
        self.welcome.recentRequested.connect(lambda value: self.open_project(Path(value)))
        self.welcome.exampleRequested.connect(self._open_example)
        self.welcome.documentRequested.connect(
            lambda identity: self._reveal_authority_target(identity, None)
        )

    def _open_example(self, example_id: str) -> None:
        if self._resource_examples.busy:
            self.statusBar().showMessage("An example is already being prepared.")
            return
        if not self._replace_current_allowed():
            return
        definition = next((d for d in PHYSICAL_EXAMPLE_CATALOG if d.id == example_id), None)
        if definition is not None and definition.resource_directory is not None:
            destination = self._path_chooser()
            if destination is None:
                return
            context = (self._session, self._session.authority.revision if self._session else None)
            self._resource_examples.begin(example_id, destination, self._computations, context)
            self.statusBar().showMessage(
                "Copying the example's declared inputs into the chosen project folder."
            )
            return
        try:
            session = example_session(example_id, computations=self._computations)
            label = next(
                (item.label for item in EXAMPLE_CATALOG if item.id == example_id),
                example_id,
            )
        except ExampleBuildError as exc:
            QMessageBox.critical(self, "Example failed", str(exc))
            return
        self._install_session(session)
        self.statusBar().showMessage(f"Opened an editable unsaved copy of {label}")
        if definition is not None:
            self._show_domain_workbench()

    def _resource_example_ready(self, prepared: object) -> None:
        if not isinstance(prepared, PreparedExample):
            return
        context = (self._session, self._session.authority.revision if self._session else None)
        session = prepared.session
        if prepared.context != context:
            session.close()
            self.statusBar().showMessage(
                f"Example saved at {session.root}; "
                "the current editor changed, so it remains active."
            )
            return
        self._install_session(session)
        assert session.root is not None
        self._remember_recent(session.root)
        self._show_domain_workbench()
        self.statusBar().showMessage(
            f"Opened the example and its retained inputs at {session.root}"
        )

    def new_project(self, _checked: bool = False, *, hello_world: bool = False) -> None:
        if not self._replace_current_allowed():
            return
        self._install_session(ProjectSession.new(computations=self._computations))
        if hello_world:
            document = self._current_document()
            if document is not None:
                document.insert_hello_world()
        self.statusBar().showMessage("New project ready")

    def create_document(self, kind: DocumentKind) -> None:
        if self._session is None:
            return
        project = self._session.authority.snapshot()
        same_kind = sum(document.kind is kind for document in project.documents)
        number = same_kind + 1
        if kind is DocumentKind.DRAKON:
            title = f"Algorithm {number}"
            identifier = f"algorithm_{number}"
            module = self._selected_python_module(project)
        elif kind is DocumentKind.MIND_MAP:
            title = f"Mind Map {number}"
            identifier = None
            module = None
        else:
            title = f"Free-form Canvas {number}"
            identifier = None
            module = None
        result = self._session.client.create_diagram(
            kind,
            title,
            identifier=identifier,
            module=module,
        )
        if not isinstance(result, CommandAccepted):
            self.statusBar().showMessage(f"Could not create document: {result.message}")
            return
        self._refresh_project()
        diagram_id = result.affected_ids[0]
        editor = self._ensure_document_widget(diagram_id)
        if editor is not None:
            index = self.documents.indexOf(editor)
            if index >= 0:
                self.documents.setCurrentIndex(index)
        location = f" in {module}" if module is not None else ""
        self.statusBar().showMessage(f"Created {title}{location}")

    def _selected_python_module(self, project: Project) -> str:
        item = self.project_tree.currentItem()
        while item is not None:
            value = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(value, str) and value.startswith("__python_module__:"):
                selected = project.program_model.module(value.partition(":")[2])
                if selected is not None:
                    return selected.path
            if isinstance(value, str):
                document = next(
                    (
                        candidate
                        for candidate in project.documents
                        if isinstance(candidate, DrakonDiagram) and candidate.id == value
                    ),
                    None,
                )
                if document is not None:
                    return document.header.function.module
            item = item.parent()
        current = self._current_document()
        if current is not None:
            document = next(
                (
                    candidate
                    for candidate in project.documents
                    if isinstance(candidate, DrakonDiagram) and candidate.id == current.diagram_id
                ),
                None,
            )
            if document is not None:
                return document.header.function.module
        return project.program_model.modules[0].path if project.program_model.modules else "main"

    def export_current_document(self, _checked: bool = False) -> None:
        editor = self._current_editor()
        if editor is not None:
            self._export_document_id(editor.diagram_id)

    def _export_document_id(self, diagram_id: str) -> None:
        if self._session is None:
            return
        project = self._session.authority.snapshot()
        document = next(
            (item for item in project.documents if item.id == diagram_id),
            None,
        )
        if document is None:
            return
        value, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Document",
            f"{document.title}.svg",
            "SVG vector (*.svg);;PNG image (*.png);;PDF document (*.pdf)",
        )
        if not value:
            return
        path = Path(value)
        if path.suffix.lower() not in {".svg", ".png", ".pdf"}:
            path = path.with_suffix(".svg")
        try:
            result = export_document(
                document,
                path,
                options=ExportOptions(
                    asset_root=self._session.root,
                    managed_assets=project.managed_assets,
                ),
            )
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self.statusBar().showMessage(
            f"Exported {result.format.value.upper()} {result.width}x{result.height} "
            f"to {result.path}"
        )

    def install_shape_pack(self, _checked: bool = False) -> None:
        if self._session is None:
            return
        value, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Install visual shape pack",
            "",
            "Shape-pack manifest (manifest.json *.shape-pack.json);;JSON files (*.json)",
        )
        if not value:
            return
        if self._session.root is None and not self.save_project():
            self.statusBar().showMessage("Save the project before installing a shape pack")
            return
        assert self._session.root is not None
        try:
            installed = install_shape_pack(self._session.root, Path(value))
        except AssetSafetyError as exc:
            QMessageBox.warning(
                self,
                "Shape pack rejected",
                f"{exc.code}: {exc}",
            )
            return
        existing = next(
            (
                item
                for item in self._session.authority.snapshot().shape_packs
                if item.id == installed.reference.id
            ),
            None,
        )
        if existing is None:
            result = self._session.client.register_shape_pack(installed.reference)
            if not isinstance(result, CommandAccepted):
                QMessageBox.warning(self, "Shape pack rejected", result.message)
                return
        elif existing.sha256 != installed.reference.sha256:
            QMessageBox.warning(
                self,
                "Shape pack conflict",
                "This pack ID and version are already registered with different content.",
            )
            return
        self._refresh_project()
        self.statusBar().showMessage(
            f"Installed visual-only shape pack {installed.reference.name} "
            f"{installed.reference.version} ({len(installed.shapes)} shapes)"
        )

    def open_project(
        self,
        path: Path | bool | None = None,
    ) -> None:
        if isinstance(path, bool) or path is None:
            path = self._path_chooser()
        if path is None or not self._replace_current_allowed():
            return
        try:
            session = ProjectSession.open(path, computations=self._computations)
        except ProjectLeaseConflict as exc:
            answer = QMessageBox.question(
                self,
                "Project already open",
                f"{exc}\n\nOpen a non-editable view for navigation, search, "
                "validation, and export?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            try:
                session = ProjectSession.open(path, read_only=True, computations=self._computations)
            except Exception as read_error:
                QMessageBox.critical(self, "Read-only open failed", str(read_error))
                return
        except Exception as exc:
            QMessageBox.critical(self, "Open failed", str(exc))
            return
        self._install_session(session)
        self._remember_recent(path)
        qualifier = " read-only" if session.read_only else ""
        self.statusBar().showMessage(f"Opened{qualifier} {path}")

    def save_project(self, _checked: bool = False) -> bool:
        saved, error = self._attempt_save_project()
        if error is not None:
            QMessageBox.critical(self, "Save failed", str(error))
        return saved

    def save_project_as(self, _checked: bool = False) -> bool:
        """Fork the exact open snapshot and continue in the new editable project."""

        if self._session is None:
            return False
        root = self._path_chooser()
        if root is None:
            return False
        resolved = root.resolve()
        if self._session.root == resolved and not self._session.read_only:
            return self.save_project()
        try:
            saved_root = self._session.save_recovery_copy(resolved)
            replacement = ProjectSession.open(saved_root, computations=self._computations)
            if replacement.authority.snapshot().title == "Untitled Project":
                result = replacement.client.rename_project(saved_root.name)
                if not isinstance(result, CommandAccepted):
                    replacement.close()
                    raise RuntimeError("The copy was saved but could not adopt its folder name")
        except Exception as exc:
            QMessageBox.critical(self, "Save As failed", str(exc))
            return False
        self._install_session(replacement)
        self._remember_recent(saved_root)
        self.statusBar().showMessage(f"Saved and opened editable copy at {saved_root}")
        return True

    def _attempt_save_project(self) -> tuple[bool, Exception | None]:
        if self._session is None:
            return False, None
        root = self._session.root or self._path_chooser()
        if root is None:
            return False, None
        try:
            self._session.save_as(root)
        except Exception as exc:
            return False, exc
        self._remember_recent(root)
        self._refresh_project()
        self._pipeline.attach(self._session)
        self.statusBar().showMessage(f"Saved revision {self._session.authority.revision}")
        return True, None

    def _save_from_command(self) -> None:
        self.save_project()

    def _save_as_from_command(self) -> None:
        self.save_project_as()

    def _generate_from_command(self) -> None:
        self.generate_project()

    def generate_project(self, _checked: bool = False) -> GenerationResult | None:
        if self._session is None:
            return None
        if self._session.root is None and not self.save_project():
            return None
        if not self._pipeline.generate_in_background():
            self.development.show_diagnostics()
            return None
        self.statusBar().showMessage(
            f"Generation queued for revision {self._session.authority.revision}"
        )
        return None

    def run_project(self, _checked: bool = False) -> None:
        if self._session is None:
            return
        if self._session.root is None and not self.save_project():
            return
        assert self._session.root is not None
        self.development_dock.show()
        self.resizeDocks([self.development_dock], [180], Qt.Orientation.Vertical)
        project = self._session.authority.snapshot()
        assessment = assess_project(project)
        if not assessment.buildable:
            first = assessment.blocking_diagnostics[0]
            self.development.show_diagnostics()
            self.statusBar().showMessage(f"Run blocked by {first.code}: {first.message}")
            return
        inspection = inspect_generation(
            self._session.root,
            current_revision=project.revision,
        )
        if inspection.externally_changed:
            self.development.refresh_artifacts(self._session.root, project)
            self.development.show_artifacts()
            self.statusBar().showMessage(
                "Run blocked — generated files changed externally; inspect the diff and "
                "explicitly Generate Project"
            )
            return
        manifest = load_generation_manifest(self._session.root)
        revision = self._session.authority.revision
        manifest_revision = manifest.get("revision") if manifest else None
        if manifest_revision != revision:
            self._pending_project_run = True
            self.action_stop_project.setEnabled(True)
            if not self._pipeline.generate_in_background():
                self._pending_project_run = False
                self.action_stop_project.setEnabled(False)
                self.development.show_diagnostics()
                self.statusBar().showMessage("Run blocked: generation could not start")
            else:
                self.statusBar().showMessage(
                    f"Generating revision {revision}; project run will start when ready"
                )
            return
        if manifest is None:
            self.development.show_diagnostics()
            return
        project_file = self._session.root / "generated" / "run_project.py"
        if not project_file.is_file():
            self.development.show_diagnostics()
            self.statusBar().showMessage(
                "Run blocked: generate the current Python project launcher first"
            )
            return
        setup = self._session.authority.snapshot().runtime_settings
        profile = next(
            (item for item in setup.run_profiles if item.name == setup.active_run_profile),
            setup.run_profiles[0] if setup.run_profiles else None,
        )
        working_directory = self._session.root
        environment: dict[str, str] | None = None
        interpreter = ""
        if profile is not None:
            interpreter = profile.interpreter
            configured_working_directory = Path(profile.working_directory)
            working_directory = (
                configured_working_directory
                if configured_working_directory.is_absolute()
                else self._session.root / configured_working_directory
            )
            environment = {item.name: item.value for item in profile.environment}
        if self._project_run_session.is_active:
            self.statusBar().showMessage("A project run is already active")
            return
        try:
            self._project_run_session.start_generated(
                project_file,
                interpreter=interpreter,
                working_directory=working_directory,
                environment=environment,
                completed=self.projectRunCompleted.emit,
            )
        except (OSError, RuntimeError) as exc:
            self.run_output.setPlainText(f"Could not start generated project: {exc}\n")
            self.development.show_run_output()
            return
        self.run_output.setPlainText("Running generated project in an isolated child process...\n")
        self.action_stop_project.setEnabled(True)
        self.development.detail_label.setText("Project run active; use Stop Project to terminate")
        self.development.show_run_output()
        self.statusBar().showMessage("Project run started")

    def _project_run_completed(self, raw_result: object) -> None:
        if not isinstance(raw_result, RunResult):
            return
        result = raw_result
        self.action_stop_project.setEnabled(False)
        self.run_output.setPlainText(result.stdout + result.stderr)
        if result.termination_reason == "stopped":
            self.run_output.appendPlainText("Project run stopped by the user.")
        self.development.detail_label.setText(
            f"Run finished: exit {result.return_code}; {result.termination_reason}; "
            f"{result.duration_seconds:.3f}s"
        )
        self.development.show_run_output()
        self.statusBar().showMessage(
            f"Project exited {result.return_code} in {result.duration_seconds:.3f}s"
        )

    def run_current_document(self, _checked: bool = False) -> None:
        document = self._current_document()
        if document is not None:
            document.run_current()

    def trace_current_document(self, _checked: bool = False) -> None:
        document = self._current_document()
        if document is not None:
            document.trace_current()

    def debug_current_document(self, _checked: bool = False) -> None:
        document = self._current_document()
        if document is not None:
            document.debug_current()

    def stop_current_document(self, _checked: bool = False) -> None:
        document = self._current_document()
        if document is not None:
            document.stop_current()

    def stop_project(self, _checked: bool = False) -> None:
        self._pending_project_run = False
        if self._project_run_session.stop():
            self.statusBar().showMessage("Stopping project run...")
        self.action_stop_project.setEnabled(False)

    def open_python_project(
        self,
        _checked: bool = False,
        *,
        module_id: str | None = None,
    ) -> None:
        if self._session is None:
            return
        if self._python_project_widget is None:
            self._python_project_widget = PythonProjectWidget(self._session.client)
            self._python_project_widget.projectChanged.connect(self._refresh_project)
        else:
            self._python_project_widget.refresh(self._session.authority.snapshot())
        index = self.documents.indexOf(self._python_project_widget)
        if index < 0:
            index = self._insert_document_tab(self._python_project_widget, "Python Project")
        self.documents.setCurrentIndex(index)
        if module_id is not None:
            self._python_project_widget.select_module(module_id)

    def validate_project_action(self, _checked: bool = False) -> None:
        if self._session is None:
            return
        self.development.show_diagnostics()
        if self._pipeline.validate_in_background():
            self.statusBar().showMessage(
                f"Validating revision {self._session.authority.revision} in the background"
            )

    def reveal_generated_folder(self, _checked: bool = False) -> None:
        if self._session is None or self._session.root is None:
            self.development.show_diagnostics()
            return
        if self._pipeline.status.state in {PipelineState.BLOCKED, PipelineState.FAILED}:
            self.development.show_diagnostics()
            self.statusBar().showMessage(
                "Generation is blocked — diagnostics explain what must be repaired"
            )
            return
        manifest = load_generation_manifest(self._session.root)
        if manifest is None:
            self.development.show_diagnostics()
            self.statusBar().showMessage(
                "No complete artifact manifest — validate and generate first"
            )
            return
        generated = self._session.root / "generated"
        if not self._folder_revealer(generated):
            self.statusBar().showMessage(f"Could not open {generated}")

    def _has_generated_manifest(self) -> bool:
        return (
            self._session is not None
            and self._session.root is not None
            and load_generation_manifest(self._session.root) is not None
        )

    @staticmethod
    def _open_folder(path: Path) -> bool:
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    def _on_pipeline_status(self, status: PipelineStatus) -> None:
        self.development.set_pipeline_status(status)
        if self._session is not None:
            self.development.refresh_artifacts(
                self._session.root,
                self._session.authority.snapshot(),
            )
        self.action_reveal_artifacts.setEnabled(self._has_generated_manifest())
        if status.result is not None:
            self.development.show_artifacts()
            self.statusBar().showMessage(f"Generated revision {status.result.revision}")
            if self._pending_project_run:
                self._pending_project_run = False
                QTimer.singleShot(0, self.run_project)
        elif status.state in {PipelineState.BLOCKED, PipelineState.FAILED}:
            self.development.show_diagnostics()
            if self._pending_project_run:
                self._pending_project_run = False
                self.statusBar().showMessage(f"Run blocked: {status.message}")
        elif status.state is PipelineState.VALIDATED:
            self.development.show_diagnostics()
            self.statusBar().showMessage(status.message)

    def _activate_diagnostic(self, diagnostic: object) -> None:
        diagram_id = getattr(diagnostic, "diagram_id", None)
        object_id = getattr(diagnostic, "object_id", None)
        field = getattr(diagnostic, "field", None)
        if not isinstance(diagram_id, str):
            if field in {
                "package",
                "modules",
                "post_source",
                "run_profiles",
                "active_run_profile",
            }:
                self.open_python_project()
            return
        self._navigate_to(
            NavigationLocation(
                diagram_id,
                object_id if isinstance(object_id, str) else None,
                field if isinstance(field, str) else None,
            )
        )

    def _diagram_title(self, diagram_id: str) -> str:
        if self._session is None:
            return "Algorithm"
        for document in self._session.authority.snapshot().documents:
            if document.id == diagram_id:
                return document.title
        return "Algorithm"

    def show_command_palette(self, _checked: bool = False) -> None:
        palette = CommandPalette(self._registry, self)
        palette.exec()

    def show_project_search(
        self,
        _checked: bool = False,
        *,
        replace: bool = False,
    ) -> None:
        if self._session is None:
            return
        self.search_widget.refresh_results()
        self.search_dock.show()
        self.search_dock.raise_()
        target = self.search_widget.replacement if replace else self.search_widget.query
        target.setFocus()
        target.selectAll()

    def _reveal_search_match(self, raw_match: object) -> None:
        if not isinstance(raw_match, SearchMatch):
            return
        if raw_match.diagram_id is None:
            if raw_match.kind == "runtime_settings":
                self.open_python_project()
            return
        self._refresh_project()
        self._navigate_to(
            NavigationLocation(
                raw_match.diagram_id,
                raw_match.object_id,
                raw_match.field,
            )
        )

    def show_find_callers(self, _checked: bool = False) -> None:
        diagram = self._current_document()
        if self._session is None or diagram is None:
            return
        project = self._session.authority.snapshot()
        references = find_callers(project, diagram.diagram_id)
        self.navigation.show_references(
            f"Callers of {self._diagram_title(diagram.diagram_id)}",
            references,
        )
        self._show_navigation_dock()

    def show_find_address_transitions(self, _checked: bool = False) -> None:
        diagram = self._current_document()
        if self._session is None or diagram is None:
            return
        references = find_address_transitions(
            self._session.authority.snapshot(),
            diagram_id=diagram.diagram_id,
        )
        self.navigation.show_references(
            f"Address transitions in {self._diagram_title(diagram.diagram_id)}",
            references,
        )
        self._show_navigation_dock()

    def show_call_hierarchy(self, _checked: bool = False) -> None:
        diagram = self._current_document()
        if self._session is None or diagram is None:
            return
        hierarchy = build_call_hierarchy(
            self._session.authority.snapshot(),
            diagram.diagram_id,
        )
        self.navigation.show_hierarchy(hierarchy)
        self._show_navigation_dock()

    def _show_navigation_dock(self) -> None:
        self.navigation_dock.show()
        self.navigation_dock.raise_()
        self.navigation.results.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _activate_navigation_location(self, raw_location: object) -> None:
        if isinstance(raw_location, NavigationLocation):
            self._navigate_to(raw_location)

    def _navigate_to(
        self,
        location: NavigationLocation,
        *,
        record: bool = True,
    ) -> None:
        if record:
            self._navigation_history.visit(location)
        self._reveal_authority_target(location.diagram_id, location.object_id)
        if location.object_id is not None and location.field is not None:
            widget = self._ensure_document_widget(location.diagram_id)
            if isinstance(widget, UnifiedDocumentWidget):
                self._inspect_atom(location.diagram_id, location.object_id, location.field)
        self._update_navigation_actions()

    def navigate_back(self, _checked: bool = False) -> None:
        location = self._navigation_history.back()
        if location is not None:
            self._navigate_to(location, record=False)

    def navigate_forward(self, _checked: bool = False) -> None:
        location = self._navigation_history.forward()
        if location is not None:
            self._navigate_to(location, record=False)

    def _update_navigation_actions(self) -> None:
        self.action_navigation_back.setEnabled(self._navigation_history.can_go_back)
        self.action_navigation_forward.setEnabled(self._navigation_history.can_go_forward)

    def show_automation_access(self, _checked: bool = False) -> None:
        self.collaboration_dock.show()
        self.collaboration_dock.raise_()
        self.collaboration.endpoint.setFocus()

    def close_project(self, _checked: bool = False) -> None:
        if not self._replace_current_allowed():
            return
        self._release_session()
        self.welcome.set_project_documents("", ())
        self._show_welcome()
        self.setWindowTitle(PRODUCT.name)
        self.statusBar().showMessage("Choose an example or open a project.")

    def show_entrypoint(self, _checked: bool = False) -> None:
        self.open_python_project()
        if self._python_project_widget is not None:
            self._python_project_widget.project_tabs.setCurrentIndex(1)
            self._python_project_widget.entrypoint.setFocus()

    def _document_tabs_changed(self, _index: int = -1) -> None:
        self._stack.setCurrentWidget(self.documents if self.documents.count() else self.welcome)
        if hasattr(self, "action_run_current"):
            self._sync_function_actions()

    def _sync_function_actions(self) -> None:
        document = self._current_document()
        for proxy, name in (
            (self.action_run_current, "action_run"),
            (self.action_trace_current, "action_trace"),
            (self.action_debug_current, "action_debug"),
            (self.action_stop_current, "action_stop"),
        ):
            action = getattr(document, name, None)
            proxy.setEnabled(action is not None and action.isEnabled())
            proxy.setToolTip(
                action.toolTip() if action is not None else "Open a function document first."
            )

    def _insert_document_tab(self, widget: QWidget, title: str) -> int:
        if widget not in self._document_order:
            self._document_order.append(widget)
        preceding = self._document_order[: self._document_order.index(widget)]
        index = sum(self.documents.indexOf(item) >= 0 for item in preceding)
        return self.documents.insertTab(index, widget, title)

    def _remember_tab_order(self, _old: int, _new: int) -> None:
        visible = [
            widget
            for i in range(self.documents.count())
            if (widget := self.documents.widget(i)) is not None
        ]
        reordered = iter(visible)
        self._document_order = [
            next(reordered) if item in visible else item for item in self._document_order
        ]

    def _save_workspace_layout(self) -> None:
        self._settings.setValue("workspace/geometry", self.saveGeometry())
        if self._session is not None:
            self._settings.setValue("workspace/docks", self.saveState(1))

    def _restore_workspace_layout(self) -> None:
        if self._session is None:
            return
        state = self._settings.value("workspace/docks")
        if isinstance(state, QByteArray):
            self.restoreState(state, 1)
        else:
            self.reset_workspace()
        self._bounds.schedule()

    def reset_workspace(self, _checked: bool = False) -> None:
        """Restore the documented dock topology without replacing live widgets."""

        self.setCorner(Qt.Corner.BottomLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setCorner(Qt.Corner.BottomRightCorner, Qt.DockWidgetArea.RightDockWidgetArea)
        for dock, area in (
            (self.project_dock, Qt.DockWidgetArea.LeftDockWidgetArea),
            (self.shapes_dock, Qt.DockWidgetArea.LeftDockWidgetArea),
            (self.inspector_dock, Qt.DockWidgetArea.LeftDockWidgetArea),
            (self.development_dock, Qt.DockWidgetArea.BottomDockWidgetArea),
            (self.collaboration_dock, Qt.DockWidgetArea.RightDockWidgetArea),
            (self.search_dock, Qt.DockWidgetArea.RightDockWidgetArea),
            (self.navigation_dock, Qt.DockWidgetArea.RightDockWidgetArea),
        ):
            dock.setFloating(False)
            self.addDockWidget(area, dock)
        self.splitDockWidget(self.project_dock, self.shapes_dock, Qt.Orientation.Vertical)
        self.tabifyDockWidget(self.project_dock, self.inspector_dock)
        self.tabifyDockWidget(self.collaboration_dock, self.search_dock)
        self.tabifyDockWidget(self.search_dock, self.navigation_dock)
        active = self._session is not None
        for dock in (
            self.project_dock,
            self.shapes_dock,
            self.inspector_dock,
        ):
            dock.setVisible(active)
        for dock in (
            self.development_dock,
            self.collaboration_dock,
            self.visualizer_dock,
            self.domain_dock,
            self.git_dock,
        ):
            dock.hide()
        self.project_dock.raise_()
        self.search_dock.hide()
        self.navigation_dock.hide()
        if active:
            self.project_dock.raise_()
            self.resizeDocks(
                [self.project_dock, self.shapes_dock],
                [180, 400],
                Qt.Orientation.Vertical,
            )
            self.resizeDocks(
                [self.project_dock, self.shapes_dock],
                [250, 250],
                Qt.Orientation.Horizontal,
            )
        self._settings.remove("workspace/docks")
        if hasattr(self, "_bounds"):
            self._bounds.schedule()
        self.statusBar().showMessage("Workspace layout restored")

    def _select_theme(self, theme: ThemeName) -> None:
        self._theme = theme
        self._settings.setValue("appearance/theme", theme.value)
        self._settings.setValue("appearance/revision", self._APPEARANCE_REVISION)
        self._apply_appearance()

    def _set_reduced_motion(self, enabled: bool) -> None:
        self._reduced_motion = enabled
        self._settings.setValue("appearance/reduced_motion", enabled)
        self._apply_appearance()

    def _apply_appearance(self) -> None:
        application = QApplication.instance()
        if isinstance(application, QApplication):
            apply_theme(
                application,
                self._theme,
                reduced_motion=self._reduced_motion,
            )

    @staticmethod
    def _desktop_automation_context() -> AutomationContext:
        return AutomationContext(
            actor_id="desktop-human",
            connection_id="desktop-ui",
            mode=AccessMode.COMMIT,
            capabilities=frozenset(AutomationCapability),
        )

    def _refresh_proposals(self) -> None:
        host = self._automation_host
        if host is None:
            self.collaboration.set_proposals([])
            return
        raw = host.service.dispatch(
            "proposal.list",
            {},
            self._desktop_automation_context(),
        )
        proposals = raw if isinstance(raw, list) else []
        self.collaboration.set_proposals(proposals)

    def _accept_proposal(self, proposal_id: str) -> None:
        self._review_proposal("proposal.accept", proposal_id)

    def _reject_proposal(self, proposal_id: str) -> None:
        self._review_proposal("proposal.reject", proposal_id)

    def _review_proposal(self, method: str, proposal_id: str) -> None:
        host = self._automation_host
        if host is None:
            return
        try:
            result = host.service.dispatch(
                method,
                {"proposal_id": proposal_id},
                self._desktop_automation_context(),
            )
        except Exception as exc:
            self.collaboration.status.setText(f"Proposal review failed: {exc}")
        else:
            status = result.get("status") if isinstance(result, dict) else None
            self.collaboration.status.setText(f"Proposal {proposal_id}: {status or 'reviewed'}")
        self._refresh_proposals()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._replace_current_allowed():
            event.ignore()
            return
        self._save_workspace_layout()
        self._release_session()
        self._resource_examples.close()
        if self._owns_computations:
            self._computations.close()
        event.accept()

    def _replace_current_allowed(self) -> bool:
        if self._session is None or not self._session.is_dirty:
            return True
        decision = self._close_decision(self._session)
        if decision is CloseDecision.CANCEL:
            return False
        if decision is CloseDecision.SAVE:
            return self._save_before_close()
        return True

    def _save_before_close(self) -> bool:
        if self._session is None:
            return True
        while True:
            saved, error = self._attempt_save_project()
            if saved:
                return True
            if error is None:
                return False
            decision = self._save_failure_decision(self._session, error)
            if decision is SaveFailureDecision.RETRY:
                continue
            if decision is SaveFailureDecision.CANCEL_CLOSE:
                return False
            recovery_root = self._recovery_path_chooser()
            if recovery_root is None:
                return False
            try:
                saved_root = self._session.save_recovery_copy(recovery_root)
            except Exception as recovery_error:
                error = recovery_error
                decision = self._save_failure_decision(self._session, error)
                if decision is SaveFailureDecision.RETRY:
                    continue
                return False
            self.statusBar().showMessage(f"Recovery copy saved to {saved_root}")
            return True

    def _ask_close_decision(self, _session: ProjectSession) -> CloseDecision:
        result = QMessageBox.question(
            self,
            "Unsaved project",
            "Save changes before closing this project?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if result == QMessageBox.StandardButton.Save:
            return CloseDecision.SAVE
        if result == QMessageBox.StandardButton.Discard:
            return CloseDecision.DISCARD
        return CloseDecision.CANCEL

    def _ask_save_failure_decision(
        self,
        _session: ProjectSession,
        error: Exception,
    ) -> SaveFailureDecision:
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Critical)
        message.setWindowTitle("Save failed")
        message.setText("The project could not be saved.")
        message.setInformativeText(str(error))
        retry = message.addButton("Retry", QMessageBox.ButtonRole.AcceptRole)
        recovery = message.addButton(
            "Save Recovery Copy",
            QMessageBox.ButtonRole.ActionRole,
        )
        message.addButton("Cancel Close", QMessageBox.ButtonRole.RejectRole)
        message.setDefaultButton(retry)
        message.exec()
        clicked = message.clickedButton()
        if clicked is retry:
            return SaveFailureDecision.RETRY
        if clicked is recovery:
            return SaveFailureDecision.RECOVERY_COPY
        return SaveFailureDecision.CANCEL_CLOSE

    def _choose_project_directory(self) -> Path | None:
        value = QFileDialog.getExistingDirectory(self, "Choose Project Directory")
        return Path(value) if value else None

    def _choose_recovery_directory(self) -> Path | None:
        value = QFileDialog.getExistingDirectory(self, "Choose Recovery Copy Directory")
        return Path(value) if value else None

    def _install_session(
        self, session: ProjectSession, *, controller: GitProjectController | None = None
    ) -> None:
        self._release_session(retain_controller=controller)
        self._session = session
        controller = controller or GitProjectController(session)
        controller.changed = lambda result: self.gitEvent.emit((controller, result))
        self._git_controller = controller
        self.git_workbench.attach(controller, review=controller.prepared_review)
        self._authority_unsubscribe = session.authority.subscribe(self.authorityEvent.emit)
        self._selection_unsubscribe = session.kernel.selection.subscribe(
            self.semanticSelection.emit
        )
        self.semantic_visualizer.attach(session.kernel, session.client)
        self.domain_workbench.attach(session.kernel, session.client)
        try:
            self._automation_host = LocalAutomationHost(
                session.authority,
                project_root=lambda: self._session.root if self._session is not None else None,
                event_listener=self.automationEvent.emit,
                kernel=session.kernel,
                git=controller,
            ).start()
        except RuntimeError as exc:
            self._automation_host = None
            self.collaboration.status.setText(f"Local automation endpoint failed: {exc}")
        else:
            self.collaboration.set_access(
                self._automation_host.endpoint,
                self._automation_host.token,
            )
            session.update_authority_endpoint(self._automation_host.endpoint)
        self._refresh_project()
        self._navigation_history.clear()
        documents = session.authority.snapshot().documents
        if documents:
            self._navigation_history.visit(NavigationLocation(documents[0].id))
        self._update_navigation_actions()
        self._refresh_proposals()
        self.search_widget.attach(session.client)
        self._pipeline.attach(session)
        self._document_tabs_changed()
        QTimer.singleShot(0, self._restore_workspace_layout)
        if session.authority.snapshot().domain_workspace.models:
            QTimer.singleShot(0, self._show_domain_workbench)

    def _release_session(self, *, retain_controller: GitProjectController | None = None) -> None:
        if self._session is not None:
            self._save_workspace_layout()
        self._project_run_session.stop()
        self.action_stop_project.setEnabled(False)
        self._pending_project_run = False
        self._pipeline.attach(None)
        if self._automation_host is not None:
            self._automation_host.stop()
            self._automation_host = None
        self.collaboration.clear_access()
        self.search_widget.attach(None)
        self.semantic_visualizer.attach(None)
        self.domain_workbench.attach(None)
        self.git_workbench.attach(None)
        if self._git_controller is not None and self._git_controller is not retain_controller:
            self._git_controller.close_background()
        self._git_controller = None
        if self._selection_unsubscribe is not None:
            self._selection_unsubscribe()
            self._selection_unsubscribe = None
        if self._authority_unsubscribe is not None:
            self._authority_unsubscribe()
            self._authority_unsubscribe = None
        if self._session is not None:
            self._session.update_authority_endpoint(None)
            self._session.close()
            self._session = None
        for window in tuple(self._detached_documents.values()):
            window.release_document()
            window.close()
            window.deleteLater()
        self._detached_documents.clear()
        # Removing tabs leaves their QWidgets parented to the tab stack. Dispose
        # every retired view, including detached or previously hidden documents,
        # so a new session cannot retain the old authority or preparation worker.
        retired: set[QWidget] = set(self._documents.values())
        for index in range(self.documents.count()):
            widget = self.documents.widget(index)
            if widget is not None:
                retired.add(widget)
        for document in retired:
            if isinstance(document, UnifiedDocumentWidget):
                document._stop_child_processes()
        self.action_reveal_artifacts.setEnabled(False)
        self.documents.clear()
        self._documents.clear()
        self._document_order.clear()
        self.welcome.set_project_documents("", ())
        for document in retired:
            document.deleteLater()
        self._python_project_widget = None
        self._inspected_diagram_id = None
        self._navigation_history.clear()
        self._update_navigation_actions()

    def _show_welcome(self) -> None:
        self._stack.setCurrentWidget(self.welcome)
        self.action_run.setEnabled(False)
        self.action_close_project.setEnabled(False)
        self.action_entrypoint.setEnabled(False)
        self._sync_function_actions()
        for dock in (
            self.project_dock,
            self.shapes_dock,
            self.inspector_dock,
            self.development_dock,
            self.collaboration_dock,
            self.search_dock,
            self.navigation_dock,
            self.visualizer_dock,
            self.domain_dock,
            self.git_dock,
        ):
            dock.hide()

    def _ensure_document_widget(
        self,
        diagram_id: str,
        project: Project | None = None,
    ) -> EditorDocument | None:
        """Materialize one document on demand; the project tree remains complete."""

        existing = self._documents.get(diagram_id)
        if existing is not None:
            return existing
        if self._session is None:
            return None
        snapshot = project or self._session.authority.snapshot()
        document = next((item for item in snapshot.documents if item.id == diagram_id), None)
        if document is None:
            return None
        if isinstance(document, DrakonDiagram):
            drakon_editor = UnifiedDocumentWidget(
                self._session.client,
                document.id,
                preparation_profiles=self._computations.profiles,
                resource_store=self._session.kernel.resource_store,
                settings=self._settings,
            )
            for action in (
                drakon_editor.action_run,
                drakon_editor.action_trace,
                drakon_editor.action_debug,
                drakon_editor.action_stop,
            ):
                action.changed.connect(self._sync_function_actions)
            drakon_editor.projectChanged.connect(self._refresh_project)
            drakon_editor.atomSelected.connect(self._inspect_atom)
            drakon_editor.executionSelection.connect(self._publish_execution_selection)
            drakon_editor.executionEvent.connect(self._record_execution_event)
            drakon_editor.semanticSelectionChanged.connect(
                partial(self._inspect_atoms, document.id)
            )
            drakon_editor.canvas.insertionTargetChanged.connect(
                lambda _boundary: self._refresh_shape_availability()
            )
            editor: EditorDocument = drakon_editor
        elif document.kind is DocumentKind.MIND_MAP:
            editor = MindMapDocumentWidget(
                self._session.client,
                document.id,
                kernel=self._session.kernel,
            )
            editor.canvas.objectSelected.connect(
                partial(self._publish_view_object_selection, document.id)
            )
        else:
            editor = FreeformDocumentWidget(
                self._session.client,
                document.id,
                project_root=lambda: self._session.root if self._session else None,
                ensure_saved=self.save_project,
                kernel=self._session.kernel,
            )
            editor.canvas.objectSelected.connect(
                partial(self._publish_view_object_selection, document.id)
            )
        editor.projectChanged.connect(self._refresh_project)
        self._documents[document.id] = editor
        self._insert_document_tab(editor, document.title)
        return editor

    def _refresh_project(self) -> None:
        if self._session is None:
            return
        project = self._session.authority.snapshot()
        self.semantic_visualizer.refresh()
        self.setWindowTitle(f"{project.title} — {PRODUCT.name}")
        self.project_tree.clear()
        root = QTreeWidgetItem([project.title, "Project"])
        root.setToolTip(0, project.title)
        root.setData(0, Qt.ItemDataRole.UserRole, project.id)
        self.project_tree.addTopLevelItem(root)
        python_project_item = QTreeWidgetItem(["Python Project", "Python"])
        python_project_item.setToolTip(0, "Python Project")
        python_project_item.setData(0, Qt.ItemDataRole.UserRole, "__python_project__")
        root.addChild(python_project_item)
        self._add_python_layout_tree(root, project)
        assets_item = QTreeWidgetItem(["Managed Assets", "Assets"])
        assets_item.setData(0, Qt.ItemDataRole.UserRole, "__managed_assets__")
        for asset in project.managed_assets:
            child = QTreeWidgetItem(
                [asset.original_name or asset.id, f"{asset.media_type} · {asset.byte_size} bytes"]
            )
            child.setToolTip(0, f"{asset.relative_path}\nSHA-256 {asset.sha256}")
            child.setData(0, Qt.ItemDataRole.UserRole, asset.id)
            assets_item.addChild(child)
        for pack in project.shape_packs:
            child = QTreeWidgetItem([pack.name, f"Shape pack {pack.version} · visual only"])
            child.setToolTip(0, f"{pack.manifest_path}\nSHA-256 {pack.sha256}")
            child.setData(0, Qt.ItemDataRole.UserRole, pack.id)
            assets_item.addChild(child)
        root.addChild(assets_item)
        existing = set(self._documents)
        eager = len(project.documents) <= 5
        for document_index, document in enumerate(project.documents):
            editor = self._documents.get(document.id)
            if editor is None and (eager or (document_index == 0 and not self._documents)):
                editor = self._ensure_document_widget(document.id, project)
            elif editor is not None:
                editor.refresh(project)
            if editor is None:
                continue
            tab_index = self.documents.indexOf(editor)
            if tab_index >= 0:
                self.documents.setTabText(tab_index, document.title)
            detached = self._detached_documents.get(document.id)
            if detached is not None:
                detached.set_document_title(document.title)
            existing.discard(document.id)
        for stale in existing:
            stale_widget = self._documents.pop(stale)
            detached = self._detached_documents.pop(stale, None)
            if detached is not None:
                detached.release_document()
                detached.close()
                detached.deleteLater()
            index = self.documents.indexOf(stale_widget)
            if index >= 0:
                self.documents.removeTab(index)
            if stale_widget in self._document_order:
                self._document_order.remove(stale_widget)
            stale_widget.deleteLater()
        self.welcome.set_project_documents(
            project.title, tuple((item.id, item.title) for item in project.documents)
        )
        self.action_close_project.setEnabled(True)
        self.action_entrypoint.setEnabled(True)
        entry_id = project.program_model.entrypoint_callable_id
        entry = project.program_model.function(entry_id) if entry_id else None
        self.action_run.setToolTip(
            f"Run Project starts at {entry.identifier}(). Other open tabs are not separate runs."
            if entry
            else "No project entry point. Choose Python > Project Entry Point."
        )
        self.action_run.setEnabled(entry is not None)
        self._document_tabs_changed()
        root.setExpanded(True)
        if self._python_project_widget is not None:
            self._python_project_widget.refresh(project)
        if self.documents.count() and self.documents.currentIndex() < 0:
            self.documents.setCurrentIndex(0)
        self._refresh_shape_availability()

    def _add_python_layout_tree(self, root: QTreeWidgetItem, project: Project) -> None:
        """Project a filesystem-shaped code tree while retaining diagram identity."""

        output_root = QTreeWidgetItem(["generated/", "Output"])
        output_root.setToolTip(
            0,
            "Generated Python packages and graph-owned modules. Generate Project writes this "
            "same hierarchy to disk.",
        )
        root.addChild(output_root)
        directory_items: dict[tuple[str, ...], QTreeWidgetItem] = {(): output_root}
        module_items: dict[str, QTreeWidgetItem] = {}

        def directory(parts: tuple[str, ...]) -> QTreeWidgetItem:
            existing = directory_items.get(parts)
            if existing is not None:
                return existing
            parent = directory(parts[:-1])
            item = QTreeWidgetItem([f"{parts[-1]}/", "Package"])
            item.setToolTip(0, f"generated/{'/'.join(parts)}/ (includes __init__.py)")
            parent.addChild(item)
            directory_items[parts] = item
            return item

        invalid_root: QTreeWidgetItem | None = None
        for module in sorted(project.program_model.modules, key=lambda item: item.path.casefold()):
            try:
                relative = python_module_file_path(
                    project.program_model.package, module.path, kind=module.kind
                )
            except PythonPathError as exc:
                if invalid_root is None:
                    invalid_root = QTreeWidgetItem(["Invalid module paths", "Needs repair"])
                    output_root.addChild(invalid_root)
                item = QTreeWidgetItem([module.path or "(empty)", "Invalid"])
                item.setToolTip(0, str(exc))
                invalid_root.addChild(item)
            else:
                parts = tuple(relative.split("/"))
                parent = directory(parts[:-1])
                item = QTreeWidgetItem([parts[-1], "Module"])
                item.setToolTip(
                    0,
                    f"generated/{relative}\nActivate to edit imports, constants, and ownership.",
                )
                item.setData(
                    0,
                    Qt.ItemDataRole.UserRole,
                    f"__python_module__:{module.id}",
                )
                parent.addChild(item)
            module_items.setdefault(module.id, item)

        views = {item.function_id: item for item in project.drakon_views}
        documents = {item.id: item for item in project.documents}

        def declarations(parent: QTreeWidgetItem, body: tuple[ProgramDeclaration, ...]) -> None:
            for declaration in body:
                if isinstance(declaration, ProgramClass):
                    child = QTreeWidgetItem([declaration.identifier, "Class"])
                    child.setData(
                        0, Qt.ItemDataRole.UserRole, f"__program_class__:{declaration.id}"
                    )
                    child.setToolTip(0, f"Canonical class: {declaration.id}")
                    parent.addChild(child)
                    declarations(child, declaration.body)
                elif isinstance(declaration, ProgramFunctionReference):
                    function = project.program_model.function(declaration.function_id)
                    if function is None:
                        continue
                    view = views.get(function.id)
                    document = documents.get(view.document_id) if view is not None else None
                    child = QTreeWidgetItem(
                        [
                            document.title if document is not None else function.display_name,
                            "Function",
                        ]
                    )
                    child.setToolTip(
                        0, f"{function.identifier}()\nCanonical function: {function.id}"
                    )
                    child.setData(
                        0,
                        Qt.ItemDataRole.UserRole,
                        document.id
                        if document is not None
                        else f"__program_function__:{function.id}",
                    )
                    parent.addChild(child)

        for module in project.program_model.modules:
            declarations(module_items[module.id], module.body)

        design_documents = tuple(
            document for document in project.documents if not isinstance(document, DrakonDiagram)
        )
        design_root: QTreeWidgetItem | None = None
        if design_documents:
            design_root = QTreeWidgetItem(["Design documents", "Visual"])
            root.addChild(design_root)
            for document in design_documents:
                child = QTreeWidgetItem([document.title, document.kind.value])
                child.setToolTip(0, document.title)
                child.setData(0, Qt.ItemDataRole.UserRole, document.id)
                design_root.addChild(child)

        output_root.setExpanded(True)
        for item in directory_items.values():
            item.setExpanded(True)
        if len(project.documents) <= 50:
            for item in module_items.values():
                item.setExpanded(True)
            if invalid_root is not None:
                invalid_root.setExpanded(True)
            if design_root is not None:
                design_root.setExpanded(True)

    def _on_event(self, event: EventEnvelope) -> None:
        if self._session is None or event.project_id != self._session.authority.snapshot().id:
            return
        self.collaboration.observe_event(event)
        self._pipeline.project_changed()
        if self._refresh_pending:
            return
        self._refresh_pending = True
        QTimer.singleShot(0, self._flush_authority_refresh)

    def _on_automation_event(self, raw_event: object) -> None:
        if not isinstance(raw_event, EventEnvelope) or self._session is None:
            return
        if raw_event.project_id != self._session.authority.snapshot().id:
            return
        self.collaboration.observe_event(raw_event)
        if raw_event.event_type.startswith("proposal."):
            self._refresh_proposals()
        if raw_event.event_type == "navigation.requested":
            diagram_id = raw_event.payload.get("diagram_id")
            object_id = raw_event.payload.get("object_id")
            if isinstance(diagram_id, str):
                self._navigate_to(
                    NavigationLocation(
                        diagram_id,
                        object_id if isinstance(object_id, str) else None,
                    )
                )

    def _reveal_authority_target(
        self,
        diagram_id: str | None,
        object_id: str | None,
    ) -> None:
        if diagram_id is None:
            return
        widget = self._ensure_document_widget(diagram_id)
        if widget is None:
            return
        detached = self._detached_documents.get(diagram_id)
        if detached is not None:
            detached.showNormal()
            detached.raise_()
            detached.activateWindow()
        else:
            index = self.documents.indexOf(widget)
            if index < 0:
                index = self._insert_document_tab(widget, self._diagram_title(diagram_id))
            self.documents.setCurrentIndex(index)
        if object_id is None:
            return
        if isinstance(widget, UnifiedDocumentWidget):
            widget.reveal_semantic(object_id)
        else:
            widget.canvas.select_objects((object_id,))

    def _open_created_document(self, document_id: str) -> None:
        self._reveal_authority_target(document_id, None)

    def _show_semantic_projection(self, kind: ProjectionKind) -> None:
        self.visualizer_dock.show()
        self.visualizer_dock.raise_()
        self.semantic_visualizer.select_projection(kind)
        self.semantic_visualizer.projection_tabs.setCurrentWidget(self.semantic_visualizer.view)

    def _show_semantic_text(self) -> None:
        self.visualizer_dock.show()
        self.visualizer_dock.raise_()
        self.semantic_visualizer.projection_tabs.setCurrentWidget(
            self.semantic_visualizer.semantic_text
        )

    def _show_domain_workbench(self) -> None:
        self.domain_dock.show()
        self.domain_dock.raise_()

    def _show_git_workbench(self) -> None:
        self.git_workbench.refresh()
        self.git_dock.show()
        self.git_dock.raise_()

    def _git_changed(self, payload: object) -> None:
        if not isinstance(payload, tuple) or len(payload) != 2:
            return
        controller, result = payload
        if (
            not isinstance(controller, GitProjectController)
            or controller is not self._git_controller
            or not isinstance(result, GitOperationResult)
        ):
            return
        if result.operation == "experiment.error":
            self.git_workbench.status_label.setText(result.message)
            self.domain_workbench.status.setText(result.message)
            return
        if result.operation.startswith("experiment.") and result.reload_required:
            QTimer.singleShot(150, lambda: self._install_experiment(controller))
            return
        if result.reload_required:
            self._project_run_session.stop()
            self._pipeline.attach(None)
            # Let the initiating RPC return before retiring its local endpoint.
            QTimer.singleShot(150, lambda: self._reload_git_controller(controller))
        else:
            self.git_workbench.refresh()

    def _freeze_computation(self, request: object) -> None:
        from code_visualizer.domain.computation import ComputationRequest

        controller = self._git_controller
        if controller is None or not isinstance(request, ComputationRequest):
            return
        try:
            sources = self.git_workbench.declared_sources()
            controller.submit_freeze_and_run(request, sources=sources)
            self.domain_workbench.status.setText(
                "Capturing declared Git inputs; execution has not started."
            )
        except (ValueError, RuntimeError, OSError) as exc:
            self.domain_workbench.status.setText(str(exc))

    def _install_experiment(self, controller: GitProjectController) -> None:
        if controller is not self._git_controller:
            # Its independent attempt stays retained, even if the editor was replaced.
            controller.session.close()
            return
        session = controller.session
        if session is not self._session:
            self._install_session(session, controller=controller)
        context = session.experiment_context
        if context is not None and context.attempt_id is not None:
            self.domain_workbench.select_computation(context.attempt_id)
        self.statusBar().showMessage(f"Experiment workspace: {session.root}")
        self.git_dock.show()

    def _reload_git_controller(self, controller: GitProjectController) -> None:
        if controller is not self._git_controller:
            return
        try:
            session = controller.reload_session()
        except (GitError, OSError, RuntimeError) as exc:
            self.git_workbench.refresh()
            self.git_workbench.status_label.setText(str(exc))
            self._show_git_workbench()
            return
        self._install_session(session)
        self._show_git_workbench()

    def _reveal_semantic_id(self, semantic_id: str) -> None:
        if self._session is None:
            return
        queries = self._session.kernel.queries
        value = queries.semantic_object(semantic_id)
        if value is None:
            relation = queries.semantic_relation(semantic_id)
            if relation is not None:
                value = queries.semantic_object(relation.owner_id or relation.source_id)
        if value is not None and value.kind in {
            SemanticObjectKind.INTENTION,
            SemanticObjectKind.DOMAIN,
            SemanticObjectKind.DOMAIN_SCHEMA,
            SemanticObjectKind.CONCEPT_DEFINITION,
            SemanticObjectKind.PROPERTY_DEFINITION,
            SemanticObjectKind.ROLE_DEFINITION,
            SemanticObjectKind.LANGUAGE_DEFINITION,
            SemanticObjectKind.NOTATION_DEFINITION,
            SemanticObjectKind.VALIDATION_RULE,
            SemanticObjectKind.TRANSFORMATION,
            SemanticObjectKind.TEMPLATE,
        }:
            self._show_domain_workbench()
            self.domain_workbench.reveal(value.id)
            return
        visited: set[str] = set()
        while value is not None and value.document_id is None and value.parent_id is not None:
            if value.id in visited:
                break
            visited.add(value.id)
            value = queries.semantic_object(value.parent_id)
        if value is None or value.document_id is None:
            return
        target_id = value.id if value.kind.value in {"operation", "structure"} else None
        self._reveal_authority_target(value.document_id, target_id)

    def _publish_view_object_selection(self, diagram_id: str, object_id: str) -> None:
        if self._session is None or self._applying_semantic_selection:
            return
        semantic_id = self._session.kernel.queries.semantic_id_for_view_object(
            diagram_id,
            object_id,
        )
        if semantic_id is None:
            return
        self._session.kernel.selection.select(
            (semantic_id,),
            revision=self._session.authority.revision,
            source="ui.view",
        )

    def _publish_execution_selection(
        self,
        _diagram_id: str,
        semantic_id: str,
        project_revision: int,
        execution_session_id: str,
    ) -> None:
        if self._session is None:
            return
        self._session.kernel.selection.select(
            (semantic_id,),
            revision=project_revision,
            source="runtime.debugger",
            execution_session_id=execution_session_id,
        )

    def _record_execution_event(self, raw_event: object, semantic_id: str) -> None:
        if self._session is None or not isinstance(raw_event, DebugEvent):
            return
        self._session.kernel.runtime.record(raw_event, semantic_id or None)

    def _on_semantic_selection(self, raw_state: object) -> None:
        if not isinstance(raw_state, SelectionState) or self._session is None:
            return
        if raw_state.project_id != self._session.authority.snapshot().id:
            return
        for widget in self._documents.values():
            if isinstance(widget, (MindMapDocumentWidget, FreeformDocumentWidget)):
                widget.update_shared_selection(raw_state)
        primary = raw_state.primary
        if primary is None:
            return
        queries = self._session.kernel.queries
        self._applying_semantic_selection = True
        try:
            semantic = queries.semantic_object(primary)
            if (
                raw_state.source != "ui.drakon"
                and semantic is not None
                and semantic.document_id is not None
            ):
                target_widget = self._documents.get(semantic.document_id)
                if isinstance(target_widget, UnifiedDocumentWidget):
                    target_widget.reveal_semantic(semantic.id)
            for glyph in queries.views_for(primary):
                if glyph.document_id is None:
                    continue
                view_object_id = next(
                    (item.value for item in glyph.properties if item.name == "view_object_id"),
                    None,
                )
                if view_object_id is None:
                    continue
                view_widget = self._documents.get(glyph.document_id)
                if isinstance(view_widget, MindMapDocumentWidget):
                    view_widget.select_topic(view_object_id)
                elif isinstance(view_widget, FreeformDocumentWidget):
                    view_widget.canvas.select_objects((view_object_id,))
        finally:
            self._applying_semantic_selection = False

    def _flush_authority_refresh(self) -> None:
        self._refresh_pending = False
        self._refresh_project()

    def _activate_project_item(
        self,
        item: QTreeWidgetItem,
        _column: int,
    ) -> None:
        value = item.data(0, Qt.ItemDataRole.UserRole)
        if value == "__python_project__":
            self.open_python_project()
            return
        if isinstance(value, str) and value.startswith("__python_module__:"):
            module_id = value.partition(":")[2]
            self.open_python_project(module_id=module_id)
            if self._session is not None:
                self._session.kernel.selection.select((module_id,), source="project_explorer")
            return
        if (
            isinstance(value, str)
            and value.startswith("__program_class__:")
            and self._session is not None
        ):
            class_id = value.partition(":")[2]
            module = self._session.authority.snapshot().program_model.module_for(class_id)
            if module is not None:
                self.open_python_project(module_id=module.id)
                if self._python_project_widget is not None:
                    self._python_project_widget.classes.setCurrentIndex(
                        self._python_project_widget.classes.findData(class_id)
                    )
                self._session.kernel.selection.select((class_id,), source="project_explorer")
            return
        if (
            isinstance(value, str)
            and value.startswith("__program_function__:")
            and self._session is not None
        ):
            function_id = value.partition(":")[2]
            widget = next(
                (
                    self.documents.widget(index)
                    for index in range(self.documents.count())
                    if (candidate := self.documents.widget(index)) is not None
                    and candidate.property("programFunctionId") == function_id
                ),
                None,
            )
            if widget is None:
                widget = FunctionSignatureEditor(self._session.client, function_id)
                widget.setProperty("programFunctionId", function_id)
                widget.refresh(self._session.authority.snapshot())
                widget.applied.connect(self._refresh_project)
                self.documents.addTab(widget, "Python function")
            self.documents.setCurrentWidget(widget)
            self._session.kernel.selection.select((function_id,), source="project_explorer")
            return
        if not isinstance(value, str):
            return
        widget = self._ensure_document_widget(value)
        if widget is None:
            return
        self._navigation_history.visit(NavigationLocation(value))
        self._update_navigation_actions()
        detached = self._detached_documents.get(value)
        if detached is not None:
            detached.showNormal()
            detached.raise_()
            detached.activateWindow()
            return
        index = self.documents.indexOf(widget)
        if index < 0:
            index = self._insert_document_tab(widget, self._diagram_title(value))
        self.documents.setCurrentIndex(index)

    def _close_document_tab(self, index: int) -> None:
        widget = self.documents.widget(index)
        self.documents.removeTab(index)
        if widget in self._document_order:
            self._document_order.remove(widget)
        self._document_tabs_changed()
        if widget is self._python_project_widget:
            self._python_project_widget = None
            if widget is not None:
                widget.deleteLater()

    def detach_current_document(self, _checked: bool = False) -> None:
        self._detach_tab(self.documents.currentIndex())

    def _detach_tab_from_drag(self, index: int, position: object) -> None:
        self._detach_tab(index, position)

    def _detach_tab(self, index: int, position: object = None) -> None:
        if index < 0:
            return
        widget = self.documents.widget(index)
        if not isinstance(widget, UnifiedDocumentWidget):
            return
        if widget.diagram_id in self._detached_documents:
            return
        title = self.documents.tabText(index) or self._diagram_title(widget.diagram_id)
        self.documents.removeTab(index)
        detached = DetachedDocumentWindow(
            widget,
            title,
            position=position_near(self.frameGeometry(), position),
        )
        detached.dockRequested.connect(self._dock_document)
        detached.exportRequested.connect(self._export_document_id)
        self._detached_documents[widget.diagram_id] = detached
        detached.show()
        detached.raise_()
        detached.activateWindow()

    def _dock_document(self, diagram_id: str) -> None:
        detached = self._detached_documents.pop(diagram_id, None)
        if detached is None:
            return
        horizontal_scroll, vertical_scroll = detached.code_scroll_for_docking()
        document = detached.release_document()
        index = self.documents.indexOf(document)
        if index < 0:
            index = self._insert_document_tab(document, self._diagram_title(diagram_id))
        self.documents.setCurrentIndex(index)
        document.code.horizontalScrollBar().setValue(horizontal_scroll)
        document.code.verticalScrollBar().setValue(vertical_scroll)
        detached.deleteLater()

    def _current_document(self) -> UnifiedDocumentWidget | None:
        current = self.documents.currentWidget()
        return current if isinstance(current, UnifiedDocumentWidget) else None

    def _current_editor(self) -> EditorDocument | None:
        current = self.documents.currentWidget()
        if isinstance(
            current,
            (UnifiedDocumentWidget, MindMapDocumentWidget, FreeformDocumentWidget),
        ):
            return current
        return None

    def _has_active_drakon(self) -> bool:
        return self._session is not None and self._current_document() is not None

    def _current_insertion_context(self) -> tuple[DrakonDiagram, str] | None:
        if self._session is None:
            return None
        widget = self._current_document()
        if widget is None:
            return None
        diagram = next(
            (
                item
                for item in self._session.authority.snapshot().documents
                if isinstance(item, DrakonDiagram) and item.id == widget.diagram_id
            ),
            None,
        )
        if diagram is None:
            return None
        boundary = widget.canvas.active_insertion_boundary
        if boundary is not None:
            return diagram, boundary.sequence_id
        selected = widget.canvas.selected_atom_ids()
        if selected:
            location = find_atom_location(diagram.body, selected[0])
            if location is not None:
                return diagram, location[0].id
        return diagram, diagram.body.id

    @staticmethod
    def _loop_depth_for_sequence(
        root: Sequence,
        sequence_id: str,
        loop_depth: int = 0,
    ) -> int | None:
        if root.id == sequence_id:
            return loop_depth
        for atom in root.atoms:
            if isinstance(atom, Loop):
                found = MainWindow._loop_depth_for_sequence(
                    atom.body,
                    sequence_id,
                    loop_depth + 1,
                )
                if found is not None:
                    return found
                found = MainWindow._loop_depth_for_sequence(
                    atom.else_body,
                    sequence_id,
                    loop_depth,
                )
                if found is not None:
                    return found
                continue
            for nested in nested_sequences(atom):
                found = MainWindow._loop_depth_for_sequence(
                    nested,
                    sequence_id,
                    loop_depth,
                )
                if found is not None:
                    return found
        return None

    def _atom_kind_unavailable_reason(self, atom_kind: str) -> str | None:
        context = self._current_insertion_context()
        if context is None:
            return "Open a DRAKON document first"
        diagram, sequence_id = context
        function_kind = diagram.header.function.kind
        if atom_kind in {"break", "continue"}:
            depth = self._loop_depth_for_sequence(diagram.body, sequence_id)
            if depth is None or depth < 1:
                return "Choose an insertion target inside a loop body first"
        if atom_kind in {
            "await_call",
            "async_for_loop",
            "async_with",
            "async_delay",
            "async_period",
            "async_parallel",
        } and function_kind not in {CallableKind.ASYNC, CallableKind.ASYNC_GENERATOR}:
            return "The active function must be Async or Async Generator"
        if atom_kind == "yield" and function_kind not in {
            CallableKind.GENERATOR,
            CallableKind.ASYNC_GENERATOR,
        }:
            return "The active function must be Generator or Async Generator"
        if atom_kind == "yield_from" and function_kind is not CallableKind.GENERATOR:
            return "Yield From requires a synchronous Generator function"
        if atom_kind == "nonlocal":
            return "Nonlocal requires a nested-function scope not represented by this diagram"
        return None

    def _atom_kind_available(self, atom_kind: str) -> bool:
        return self._atom_kind_unavailable_reason(atom_kind) is None

    def _atom_kind_disabled_reason(self, atom_kind: str) -> str:
        return self._atom_kind_unavailable_reason(atom_kind) or "Available"

    def _refresh_shape_availability(self) -> None:
        for row in range(self.shape_list.count()):
            item = self.shape_list.item(row)
            value = item.data(Qt.ItemDataRole.UserRole)
            reason = (
                self._atom_kind_unavailable_reason(value)
                if isinstance(value, str) and not value.startswith("macro:")
                else None
            )
            flags = item.flags()
            item.setFlags(
                flags | Qt.ItemFlag.ItemIsEnabled
                if reason is None
                else flags & ~Qt.ItemFlag.ItemIsEnabled
            )
            base = item.data(SHAPE_TOOLTIP_ROLE)
            tooltip = str(base) if isinstance(base, str) else item.text()
            item.setToolTip(tooltip if reason is None else f"{tooltip}\nUnavailable: {reason}")

    def _has_semantic_selection(self) -> bool:
        if self._session is None:
            return False
        current = self._current_editor()
        if isinstance(current, UnifiedDocumentWidget):
            return self._structural_selection() is not None
        if isinstance(current, MindMapDocumentWidget):
            return current.selected_topic() is not None
        if isinstance(current, FreeformDocumentWidget):
            return bool(current.canvas.selected_object_ids())
        return False

    def _structural_selection(self) -> tuple[DrakonDiagram, str, tuple[str, ...], int] | None:
        if self._session is None:
            return None
        widget = self._current_document()
        if widget is None:
            return None
        diagram = next(
            (
                item
                for item in self._session.authority.snapshot().documents
                if isinstance(item, DrakonDiagram) and item.id == widget.diagram_id
            ),
            None,
        )
        if diagram is None:
            return None
        atom_ids = widget.canvas.selected_atom_ids()
        if not atom_ids:
            return None
        locations = [find_atom_location(diagram.body, atom_id) for atom_id in atom_ids]
        if any(location is None for location in locations):
            return None
        resolved = [location for location in locations if location is not None]
        sequence_ids = {location[0].id for location in resolved}
        if len(sequence_ids) != 1:
            return None
        sequence = resolved[0][0]
        indexes = [location[1] for location in resolved]
        if indexes != list(range(indexes[0], indexes[0] + len(indexes))):
            return None
        return diagram, sequence.id, atom_ids, indexes[0]

    def _has_structural_selection(self) -> bool:
        return self._structural_selection() is not None

    def _has_single_structural_selection(self) -> bool:
        selected = self._structural_selection()
        return selected is not None and len(selected[2]) == 1

    def _has_convertible_statement(self) -> bool:
        selected = self._structural_selection()
        if selected is None or len(selected[2]) != 1:
            return False
        diagram, _sequence_id, atom_ids, _index = selected
        location = find_atom_location(diagram.body, atom_ids[0])
        if location is None:
            return False
        atom = location[0].atoms[location[1]]
        return isinstance(atom, Action) or (
            isinstance(atom, SimpleStatement) and atom.statement_kind is SimpleKind.EXPRESSION
        )

    def _selected_if(self) -> tuple[DrakonDiagram, If] | None:
        selected = self._structural_selection()
        if selected is None or len(selected[2]) != 1:
            return None
        diagram, _sequence_id, atom_ids, _index = selected
        location = find_atom_location(diagram.body, atom_ids[0])
        if location is None:
            return None
        atom = location[0].atoms[location[1]]
        return (diagram, atom) if isinstance(atom, If) else None

    def _selected_if_exists(self) -> bool:
        return self._selected_if() is not None

    def _show_command_result(self, result: object, action: str) -> None:
        if isinstance(result, CommandAccepted):
            self.statusBar().showMessage(f"{action} · revision {result.revision}")
            self._refresh_project()
        elif isinstance(result, CommandRejected):
            self.statusBar().showMessage(f"{action} blocked: {result.message}")
        elif isinstance(result, CommandDeferred):
            self.statusBar().showMessage(f"{action}: {result.message}")

    def _undo(self, _checked: bool = False) -> None:
        if self._session is not None:
            self._show_command_result(self._session.client.undo(), "Undo")

    def _redo(self, _checked: bool = False) -> None:
        if self._session is not None:
            self._show_command_result(self._session.client.redo(), "Redo")

    def _selection_fragment(self) -> SemanticFragment | None:
        if self._session is None:
            return None
        project = self._session.authority.snapshot()
        current = self._current_editor()
        if isinstance(current, UnifiedDocumentWidget):
            selected = self._structural_selection()
            if selected is None:
                return None
            drakon_diagram, sequence_id, atom_ids, _index = selected
            sequence = find_sequence(drakon_diagram.body, sequence_id)
            if sequence is None:
                return None
            drakon_selected_ids = set(atom_ids)
            atoms = tuple(atom for atom in sequence.atoms if atom.id in drakon_selected_ids)
            return drakon_fragment(project.id, atoms)
        if isinstance(current, MindMapDocumentWidget):
            selected_topic = current.selected_topic()
            if selected_topic is None:
                return None
            mindmap_diagram, topic = selected_topic
            return mindmap_fragment(project.id, mindmap_diagram, topic)
        if isinstance(current, FreeformDocumentWidget):
            freeform_diagram = next(
                (
                    item
                    for item in project.documents
                    if isinstance(item, FreeformDiagram) and item.id == current.diagram_id
                ),
                None,
            )
            freeform_selected_ids = current.canvas.selected_object_ids()
            if freeform_diagram is None or not freeform_selected_ids:
                return None
            return freeform_fragment(project.id, freeform_diagram, freeform_selected_ids)
        return None

    def _copy_selection(self, _checked: bool = False) -> None:
        try:
            fragment = self._selection_fragment()
        except ClipboardFormatError as exc:
            self.statusBar().showMessage(f"Copy blocked ({exc.code}): {exc}")
            return
        if fragment is None:
            self.statusBar().showMessage("Select a semantic diagram object to copy.")
            return
        set_semantic_clipboard(fragment)
        self.statusBar().showMessage(f"Copied {fragment.summary}.")

    def _cut_selection(self, _checked: bool = False) -> None:
        if self._session is None:
            return
        current = self._current_editor()
        if isinstance(current, MindMapDocumentWidget):
            mindmap_selection = current.selected_topic()
            if mindmap_selection is None:
                return
            mindmap_diagram, topic = mindmap_selection
            if topic.id == mindmap_diagram.root.id:
                self.statusBar().showMessage("The required mind-map root cannot be cut.")
                return
        try:
            fragment = self._selection_fragment()
        except ClipboardFormatError as exc:
            self.statusBar().showMessage(f"Cut blocked ({exc.code}): {exc}")
            return
        if fragment is None:
            self.statusBar().showMessage("Select a semantic diagram object to cut.")
            return
        set_semantic_clipboard(fragment)
        if isinstance(current, UnifiedDocumentWidget):
            drakon_selection = self._structural_selection()
            if drakon_selection is None:
                return
            drakon_diagram, sequence_id, atom_ids, _index = drakon_selection
            result = self._session.client.remove_drakon_block(
                drakon_diagram.id, sequence_id, atom_ids
            )
        elif isinstance(current, MindMapDocumentWidget):
            selected_topic = current.selected_topic()
            if selected_topic is None:
                return
            mindmap_diagram, topic = selected_topic
            result = self._session.client.remove_mindmap_topic(
                mindmap_diagram.id, topic.id, promote_children=False
            )
        elif isinstance(current, FreeformDocumentWidget):
            object_ids = current.canvas.selected_object_ids()
            result = self._session.client.remove_freeform_objects(current.diagram_id, object_ids)
        else:
            return
        self._show_command_result(result, f"Cut {fragment.summary}")

    def _clipboard_fragment(self) -> SemanticFragment | None:
        mime = QApplication.clipboard().mimeData()
        if mime is None or not mime.hasFormat(SEMANTIC_FRAGMENT_MIME):
            self.statusBar().showMessage("The clipboard has no Code Visualizer semantic fragment.")
            return None
        try:
            return semantic_fragment_from_json(
                cast(bytes, mime.data(SEMANTIC_FRAGMENT_MIME).data())
            )
        except ClipboardFormatError as exc:
            self.statusBar().showMessage(f"Paste blocked ({exc.code}): {exc}")
            return None

    def _paste_selection(self, _checked: bool = False) -> None:
        if self._session is None:
            return
        fragment = self._clipboard_fragment()
        if fragment is None:
            return
        project = self._session.authority.snapshot()
        current = self._current_editor()
        expected_mode = (
            DocumentKind.DRAKON
            if isinstance(current, UnifiedDocumentWidget)
            else DocumentKind.MIND_MAP
            if isinstance(current, MindMapDocumentWidget)
            else DocumentKind.FREEFORM
            if isinstance(current, FreeformDocumentWidget)
            else None
        )
        if expected_mode is None or fragment.mode is not expected_mode:
            destination = expected_mode.value if expected_mode is not None else "no document"
            self.statusBar().showMessage(
                f"Cross-mode paste is not implicit: {fragment.mode.value} data cannot be "
                f"inserted into {destination}. Choose or create a compatible document."
            )
            return
        try:
            if isinstance(current, UnifiedDocumentWidget):
                selected = self._structural_selection()
                boundary = current.canvas.active_insertion_boundary
                if boundary is not None:
                    sequence_id, index = boundary.sequence_id, boundary.index
                elif selected is not None:
                    _diagram, sequence_id, atom_ids, index = selected
                    index += len(atom_ids)
                else:
                    drakon_diagram = next(
                        item
                        for item in project.documents
                        if isinstance(item, DrakonDiagram) and item.id == current.diagram_id
                    )
                    sequence_id, index = (
                        drakon_diagram.body.id,
                        len(drakon_diagram.body.atoms),
                    )
                atoms = clone_atoms_with_fresh_ids(drakon_atoms_from_fragment(fragment))
                unresolved = unresolved_references(fragment, project)
                result = self._session.client.insert_drakon_block(
                    current.diagram_id, sequence_id, index, atoms
                )
                selected_ids = tuple(atom.id for atom in atoms)
            elif isinstance(current, MindMapDocumentWidget):
                selected_topic = current.selected_topic()
                if selected_topic is None:
                    raise ClipboardFormatError(
                        "CLIPBOARD_INCOMPATIBLE_TARGET", "Select a destination topic"
                    )
                mindmap_diagram, parent = selected_topic
                updated_mindmap, selected_ids, unresolved = paste_mindmap_fragment(
                    fragment,
                    project,
                    mindmap_diagram,
                    parent.id,
                    len(parent.children),
                )
                result = self._session.client.submit(
                    ReplaceDiagramSnapshot(updated_mindmap),
                    intent="Paste mind-map subtree",
                )
            else:
                assert isinstance(current, FreeformDocumentWidget)
                freeform_diagram = next(
                    item
                    for item in project.documents
                    if isinstance(item, FreeformDiagram) and item.id == current.diagram_id
                )
                updated_freeform, selected_ids, unresolved = paste_freeform_fragment(
                    fragment, project, freeform_diagram
                )
                result = self._session.client.submit(
                    ReplaceDiagramSnapshot(updated_freeform),
                    intent="Paste free-form selection",
                )
        except (ClipboardFormatError, StopIteration, ValueError) as exc:
            code = exc.code if isinstance(exc, ClipboardFormatError) else "CLIPBOARD_INVALID"
            self.statusBar().showMessage(f"Paste blocked ({code}): {exc}")
            return
        self._show_command_result(result, "Paste semantic fragment")
        if not isinstance(result, CommandAccepted):
            return
        refreshed = self._current_editor()
        if isinstance(refreshed, UnifiedDocumentWidget):
            refreshed.canvas.select_atoms(selected_ids)
        elif isinstance(refreshed, MindMapDocumentWidget) and selected_ids:
            refreshed.select_topic(selected_ids[0])
        elif isinstance(refreshed, FreeformDocumentWidget):
            refreshed.canvas.select_objects(selected_ids)
        if unresolved:
            self.statusBar().showMessage(
                "Pasted with unresolved references for explicit rebinding: " + "; ".join(unresolved)
            )

    def _remove_selection(self, _checked: bool = False) -> None:
        current = self._current_editor()
        if isinstance(current, MindMapDocumentWidget):
            current.preview_delete()
            return
        if isinstance(current, FreeformDocumentWidget):
            current.delete_selected()
            return
        selected = self._structural_selection()
        if selected is None or self._session is None:
            return
        diagram, sequence_id, atom_ids, _index = selected
        sequence = find_sequence(diagram.body, sequence_id)
        if sequence is None:
            return
        selected_ids = set(atom_ids)
        atoms = tuple(atom for atom in sequence.atoms if atom.id in selected_ids)
        decision = self._preview_drakon_delete(atoms)
        if decision is DrakonDeleteChoice.CANCEL:
            self.statusBar().showMessage("Delete cancelled; the diagram was not changed")
            return
        if decision is DrakonDeleteChoice.UNWRAP:
            self._unwrap_selection()
            return
        result = self._session.client.remove_drakon_block(
            diagram.id,
            sequence_id,
            atom_ids,
        )
        self._show_command_result(result, "Delete block")

    @staticmethod
    def _drakon_delete_preview(atoms: tuple[DrakonAtom, ...]) -> tuple[str, bool]:
        def descendant_count(atom: DrakonAtom) -> int:
            total = 0
            for sequence in nested_sequences(atom):
                total += len(sequence.atoms)
                total += sum(descendant_count(child) for child in sequence.atoms)
            return total

        owned = sum(descendant_count(atom) for atom in atoms)
        count = len(atoms)
        summary = (
            f"Delete {count} selected operation{'s' if count != 1 else ''}?\n\n"
            "The unique compatible predecessor and successor will be spliced into one "
            "orthogonal route."
        )
        if owned:
            summary += (
                f"\n\nThis whole-structure delete also removes {owned} owned operation"
                f"{'s' if owned != 1 else ''}. Choose Unwrap to preserve the selected "
                "construct's preferred body instead."
            )
        return summary, count == 1 and owned > 0

    def _preview_drakon_delete(self, atoms: tuple[DrakonAtom, ...]) -> DrakonDeleteChoice:
        summary, can_unwrap = self._drakon_delete_preview(atoms)
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Warning)
        message.setWindowTitle("Preview structural deletion")
        message.setText(summary)
        delete_button = message.addButton(
            "Delete Whole Selection",
            QMessageBox.ButtonRole.DestructiveRole,
        )
        unwrap_button = (
            message.addButton("Unwrap Preferred Body", QMessageBox.ButtonRole.ActionRole)
            if can_unwrap
            else None
        )
        cancel_button = message.addButton(QMessageBox.StandardButton.Cancel)
        message.setDefaultButton(cancel_button)
        message.exec()
        clicked = message.clickedButton()
        if clicked is delete_button:
            return DrakonDeleteChoice.DELETE
        if unwrap_button is not None and clicked is unwrap_button:
            return DrakonDeleteChoice.UNWRAP
        return DrakonDeleteChoice.CANCEL

    def _duplicate_selection(self, _checked: bool = False) -> None:
        current = self._current_editor()
        if isinstance(current, FreeformDocumentWidget):
            current.duplicate_selected()
            return
        if isinstance(current, MindMapDocumentWidget) and self._session is not None:
            selected_topic = current.selected_topic()
            if selected_topic is None:
                return
            mindmap_diagram, topic = selected_topic
            parent = find_topic_parent(mindmap_diagram.root, topic.id)
            if parent is None:
                self.statusBar().showMessage("The required mind-map root cannot be duplicated.")
                return
            index = next(
                position for position, child in enumerate(parent.children) if child.id == topic.id
            )
            project = self._session.authority.snapshot()
            fragment = mindmap_fragment(project.id, mindmap_diagram, topic)
            updated, selected_ids, _unresolved = paste_mindmap_fragment(
                fragment, project, mindmap_diagram, parent.id, index + 1
            )
            result = self._session.client.submit(
                ReplaceDiagramSnapshot(updated), intent="Duplicate mind-map subtree"
            )
            self._show_command_result(result, "Duplicate mind-map subtree")
            refreshed = self._current_editor()
            if (
                isinstance(result, CommandAccepted)
                and isinstance(refreshed, MindMapDocumentWidget)
                and selected_ids
            ):
                refreshed.select_topic(selected_ids[0])
            return
        selected = self._structural_selection()
        if selected is None or self._session is None:
            return
        drakon_diagram, sequence_id, atom_ids, index = selected
        result = self._session.client.duplicate_drakon_block(
            drakon_diagram.id,
            sequence_id,
            atom_ids,
            index + len(atom_ids),
        )
        self._show_command_result(result, "Duplicate block")

    def _edit_selected_field(self, secondary: bool) -> None:
        document = self._current_document()
        if document is None:
            return
        if not document.canvas.request_selected_field_edit(secondary=secondary):
            label = "secondary" if secondary else "primary"
            self.statusBar().showMessage(
                f"Select one operation with an editable {label} semantic field"
            )

    def _convert_selected_statement(self, _checked: bool = False) -> None:
        selected = self._structural_selection()
        if selected is None or self._session is None or len(selected[2]) != 1:
            return
        diagram, _sequence_id, atom_ids, _index = selected
        try:
            result = self._session.client.convert_drakon_statement(diagram.id, atom_ids[0])
        except ValueError as exc:
            self.statusBar().showMessage(f"Statement conversion unavailable: {exc}")
            return
        self._show_command_result(result, "Convert statement to typed icon")

    def _cycle_insertion_target(self, forward: bool) -> None:
        document = self._current_document()
        if document is None:
            return
        boundary = document.canvas.cycle_insertion_target(forward=forward)
        if boundary is None:
            self.statusBar().showMessage("This diagram has no compatible insertion boundary")
            return
        direction = "Next" if forward else "Previous"
        self.statusBar().showMessage(
            f"{direction} insertion target · sequence {boundary.sequence_id} · "
            f"position {boundary.index}"
        )

    def _move_selection_by(self, delta: int) -> None:
        selected = self._structural_selection()
        if selected is None or self._session is None:
            return
        diagram, sequence_id, atom_ids, index = selected
        sequence = find_sequence(diagram.body, sequence_id)
        if sequence is None:
            return
        if delta < 0:
            if index == 0:
                self.statusBar().showMessage("The selected block is already first")
                return
            destination_index = index - 1
        else:
            block_end = index + len(atom_ids)
            if block_end >= len(sequence.atoms):
                self.statusBar().showMessage("The selected block is already last")
                return
            destination_index = block_end + 1
        result = self._session.client.move_drakon_block(
            diagram.id,
            sequence_id,
            atom_ids,
            sequence_id,
            destination_index,
        )
        self._show_command_result(result, "Move selected block")

    def _wrap_selection(self, wrapper_kind: str, _checked: bool = False) -> None:
        selected = self._structural_selection()
        if selected is None or self._session is None:
            return
        diagram, sequence_id, atom_ids, _index = selected
        result = self._session.client.wrap_drakon_block(
            diagram.id,
            sequence_id,
            atom_ids,
            wrapper_kind,
        )
        self._show_command_result(result, f"Wrap in {wrapper_kind}")

    def _unwrap_selection(self, _checked: bool = False) -> None:
        selected = self._structural_selection()
        if selected is None or self._session is None or len(selected[2]) != 1:
            return
        diagram, _sequence_id, atom_ids, _index = selected
        result = self._session.client.unwrap_drakon_atom(diagram.id, atom_ids[0])
        if isinstance(result, CommandRejected) and result.code == "DRAKON_UNWRAP_CONTENT_LOSS":
            answer = QMessageBox.question(
                self,
                "Unwrap construct",
                "Other owned bodies contain operations. Discard those bodies and keep the "
                "preferred body?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Yes:
                result = self._session.client.unwrap_drakon_atom(
                    diagram.id,
                    atom_ids[0],
                    discard_other_bodies=True,
                )
        self._show_command_result(result, "Unwrap construct")

    def _toggle_if_preferred(self, _checked: bool = False) -> None:
        selected = self._selected_if()
        if selected is None or self._session is None:
            return
        diagram, decision = selected
        result = self._session.client.set_if_preferred_truth(
            diagram.id,
            decision.id,
            not decision.preferred_truth,
        )
        self._show_command_result(result, "Toggle preferred route")

    def _swap_if_outcomes(self, _checked: bool = False) -> None:
        selected = self._selected_if()
        if selected is None or self._session is None:
            return
        diagram, decision = selected
        result = self._session.client.swap_if_outcomes(diagram.id, decision.id)
        self._show_command_result(result, "Swap If outcomes")

    def _insert_atom(self, kind: str) -> None:
        document_widget = self._current_document()
        if document_widget is None or self._session is None:
            return
        if not kind.startswith("macro:"):
            reason = self._atom_kind_unavailable_reason(kind)
            if reason is not None:
                self.statusBar().showMessage(f"Insert {kind} unavailable: {reason}")
                return
        document = next(
            (
                item
                for item in self._session.authority.snapshot().documents
                if isinstance(item, DrakonDiagram) and item.id == document_widget.diagram_id
            ),
            None,
        )
        if document is None:
            return
        boundary = document_widget.canvas.active_insertion_boundary
        selected = self._structural_selection()
        if boundary is not None:
            sequence_id = boundary.sequence_id
            insertion_index = boundary.index
        elif selected is not None and selected[0].id == document.id:
            _diagram, sequence_id, atom_ids, insertion_index = selected
            insertion_index += len(atom_ids)
        else:
            sequence_id = document.body.id
            insertion_index = len(document.body.atoms)
        if kind.startswith("macro:"):
            result = self._session.client.insert_drakon_macro(
                document.id,
                kind.removeprefix("macro:"),
                insertion_index,
                sequence_id=sequence_id,
            )
        else:
            source = (
                ""
                if kind == "return"
                and document.header.function.kind
                in {CallableKind.GENERATOR, CallableKind.ASYNC_GENERATOR}
                else None
            )
            result = self._session.client.insert_drakon_atom(
                document.id,
                kind,
                insertion_index,
                source=source,
                sequence_id=sequence_id,
            )
        self._show_command_result(result, f"Insert {kind.removeprefix('macro:')}")
        if not isinstance(result, CommandAccepted):
            return
        refreshed = self._current_document()
        if refreshed is None:
            return
        snapshot = self._session.authority.snapshot()
        inserted_ids = [
            identifier
            for identifier in result.affected_ids
            if any(
                isinstance(item, DrakonDiagram)
                and item.id == document.id
                and find_atom_location(item.body, identifier) is not None
                for item in snapshot.documents
            )
        ]
        if inserted_ids:
            refreshed.canvas.select_atom(inserted_ids[0])

    def _shape_clicked(self, item: QListWidgetItem) -> None:
        kind = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(kind, str):
            self._insert_atom(kind)

    def _filter_shapes(self, query: str) -> None:
        needle = query.casefold().strip()
        for row in range(self.shape_list.count()):
            item = self.shape_list.item(row)
            item.setHidden(bool(needle and needle not in item.text().casefold()))

    def _focus_shapes(self, _checked: bool = False) -> None:
        self.shapes_dock.show()
        self.shapes_dock.raise_()
        self.shape_search.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _inspect_atom(self, diagram_id: str, atom_id: str, field: str) -> None:
        if self._session is None:
            return
        if not self._applying_semantic_selection:
            self._session.kernel.selection.select(
                (atom_id,),
                revision=self._session.authority.revision,
                source="ui.drakon",
            )
        widget = self._documents.get(diagram_id)
        if isinstance(widget, UnifiedDocumentWidget):
            selected = widget.canvas.selected_atom_ids()
            if len(selected) > 1:
                self._inspect_atoms(diagram_id, selected)
                return
        for document in self._session.authority.snapshot().documents:
            if not isinstance(document, DrakonDiagram) or document.id != diagram_id:
                continue
            location = find_atom_location(document.body, atom_id)
            if location is None:
                continue
            atom = location[0].atoms[location[1]]
            self._inspected_diagram_id = diagram_id
            self.inspector.set_atom(atom)
            self.inspector.focus_field(field)
            self.inspector_dock.show()
            self.inspector_dock.raise_()
            return

    def _inspect_atoms(self, diagram_id: str, raw_atom_ids: object) -> None:
        self._refresh_shape_availability()
        if self._session is None or not isinstance(raw_atom_ids, tuple):
            return
        atom_ids = tuple(item for item in raw_atom_ids if isinstance(item, str))
        if not atom_ids:
            return
        if not self._applying_semantic_selection:
            self._session.kernel.selection.select(
                atom_ids,
                revision=self._session.authority.revision,
                source="ui.drakon",
            )
        document = next(
            (
                item
                for item in self._session.authority.snapshot().documents
                if isinstance(item, DrakonDiagram) and item.id == diagram_id
            ),
            None,
        )
        if document is None:
            return
        atoms: list[DrakonAtom] = []
        for atom_id in atom_ids:
            location = find_atom_location(document.body, atom_id)
            if location is not None:
                atoms.append(location[0].atoms[location[1]])
        if not atoms:
            return
        self._inspected_diagram_id = diagram_id
        self.inspector.set_atoms(tuple(atoms))
        self.inspector_dock.show()

    def _apply_atom_replacement(self, value: object) -> None:
        if self._session is None or self._inspected_diagram_id is None:
            return
        if isinstance(value, tuple) and value and all(hasattr(item, "id") for item in value):
            atoms = cast(tuple[DrakonAtom, ...], value)
            result = self._session.client.transaction(
                tuple(
                    ReplaceDrakonAtom(self._inspected_diagram_id, atom.id, atom) for atom in atoms
                ),
                intent="Apply common typed Inspector properties",
            )
            self._show_command_result(result, f"Update {len(atoms)} selected operations")
            return
        if not hasattr(value, "id"):
            return
        atom = cast(DrakonAtom, value)
        result = self._session.client.replace_drakon_atom(
            self._inspected_diagram_id,
            atom,
            intent="Apply typed Inspector properties",
        )
        self._show_command_result(result, "Update inspected operation")

    def _set_document_layout(self, mode: str) -> None:
        document = self._current_document()
        if document is not None:
            document.set_layout_mode(mode)

    def _tidy_document(self, _checked: bool = False) -> None:
        document = self._current_document()
        if document is None or self._session is None:
            return
        document.refresh(self._session.authority.snapshot())
        document.canvas.fit_content()
        self.statusBar().showMessage(
            "Recomputed deterministic DRAKON layout and fitted routes, labels, and icons"
        )

    def _fit_document(self) -> None:
        document = self._current_document()
        if document is not None:
            document.canvas.fit_content()

    def _remember_recent(self, root: Path) -> None:
        paths = [root.resolve(), *self._recent_paths()]
        unique: list[Path] = []
        for path in paths:
            if path not in unique:
                unique.append(path)
        values = [str(path) for path in unique[:12]]
        self._settings.setValue("recentProjects", values)
        self.welcome.set_recent_paths(tuple(unique[:12]))

    def _load_recents(self) -> None:
        self.welcome.set_recent_paths(self._recent_paths())

    def _recent_paths(self) -> tuple[Path, ...]:
        raw = self._settings.value("recentProjects", [])
        if isinstance(raw, str):
            values = [raw]
        elif isinstance(raw, list):
            values = [str(item) for item in raw]
        else:
            values = []
        return tuple(Path(value) for value in values if Path(value).exists())
