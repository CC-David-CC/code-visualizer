"""Complete unified-document detachment; inner panes never become top-level windows."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QKeySequence, QMouseEvent
from PySide6.QtWidgets import QMainWindow, QTabBar

from code_visualizer.ui_qt.document import UnifiedDocumentWidget
from code_visualizer.ui_qt.workspace_layout import WindowBounds


class DetachableTabBar(QTabBar):
    """Request detachment after an outer tab is dragged clear of the tab strip."""

    detachRequested = Signal(int, object)

    def __init__(self) -> None:
        super().__init__()
        self._pressed_index = -1
        self._detach_sent = False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() is Qt.MouseButton.LeftButton:
            self._pressed_index = self.tabAt(event.position().toPoint())
            self._detach_sent = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        super().mouseMoveEvent(event)
        if (
            self._detach_sent
            or self._pressed_index < 0
            or not event.buttons() & Qt.MouseButton.LeftButton
        ):
            return
        local = self.mapFromGlobal(event.globalPosition().toPoint())
        safe_rect = self.rect().adjusted(-32, -32, 32, 32)
        if not safe_rect.contains(local):
            self._detach_sent = True
            self.detachRequested.emit(self._pressed_index, event.globalPosition().toPoint())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        super().mouseReleaseEvent(event)
        self._pressed_index = -1
        self._detach_sent = False


class DetachedDocumentWindow(QMainWindow):
    """A top-level shell around the exact live unified document widget."""

    dockRequested = Signal(str)
    exportRequested = Signal(str)

    def __init__(
        self,
        document: UnifiedDocumentWidget,
        title: str,
        *,
        position: QPoint | None = None,
    ) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.setObjectName("detachedUnifiedDocument")
        self.document = document
        self._bounds = WindowBounds(self)
        self._docked_code_scroll = (
            document.code.horizontalScrollBar().value(),
            document.code.verticalScrollBar().value(),
        )
        self._dock_on_close = True
        self.set_document_title(title)
        self.resize(1120, 760)
        if position is not None:
            self.move(position)
        self.setCentralWidget(document)
        self._create_actions()
        self._create_menus_and_toolbar()
        # QTabWidget.removeTab() deliberately hides its page. Reparenting that page
        # into a top-level window does not clear the explicit hidden flag, so the
        # detached shell otherwise contains a live but invisible document and its View
        # commands appear to do nothing.
        document.set_layout_mode(document.layout_mode)
        document.show()
        document.canvas.schedule_fit()

    def set_document_title(self, title: str) -> None:
        self.setWindowTitle(f"{title} — Detached Code Visualizer document")

    def _create_actions(self) -> None:
        self.action_dock = QAction("Dock Document Back", self)
        self.action_dock.setObjectName("actionDockDocument")
        self.action_dock.setShortcut(QKeySequence("Ctrl+Shift+D"))
        self.action_dock.triggered.connect(self.close)
        self.action_export = QAction("Export Document…", self)
        self.action_export.triggered.connect(
            lambda: self.exportRequested.emit(self.document.diagram_id)
        )

        self.action_run = self.document.action_run
        self.action_trace = self.document.action_trace
        self.action_debug = self.document.action_debug
        self.action_stop = self.document.action_stop
        self.action_run.setShortcut(QKeySequence("F6"))
        self.action_trace.setShortcut(QKeySequence("F7"))
        self.action_stop.setShortcut(QKeySequence("Shift+F6"))

        for action in (
            self.action_dock,
            self.action_export,
            self.action_run,
            self.action_trace,
            self.action_debug,
            self.action_stop,
        ):
            self.addAction(action)

    def _create_menus_and_toolbar(self) -> None:
        document_menu = self.menuBar().addMenu("&Document")
        document_menu.addAction(self.action_dock)
        document_menu.addAction(self.action_export)

        view_menu = self.menuBar().addMenu("&View")
        self.view_actions: dict[str, QAction] = {}
        self.view_action_group = QActionGroup(self)
        self.view_action_group.setExclusive(True)
        for label, mode in (
            ("Diagram only", "diagram"),
            ("Code only", "code"),
            ("Side by side", "side_by_side"),
            ("Stacked", "stacked"),
            ("Tabbed inner views", "tabbed"),
        ):
            action = view_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self.document.layout_mode == mode)
            action.triggered.connect(
                lambda _checked=False, selected=mode: self._set_layout_mode(selected)
            )
            self.view_action_group.addAction(action)
            self.view_actions[mode] = action
        self.action_fit = view_menu.addAction("Fit diagram (0)", self.document.canvas.fit_content)

        test_menu = self.menuBar().addMenu("&Test")
        test_menu.addAction(self.action_run)
        test_menu.addAction(self.action_trace)
        test_menu.addAction(self.action_debug)
        test_menu.addAction(self.action_stop)

        self.document.execution_toolbar.addAction(self.action_dock)

    def _set_layout_mode(self, mode: str) -> None:
        self.document.set_layout_mode(mode)
        self.document.show()
        action = self.view_actions.get(mode)
        if action is not None:
            action.setChecked(True)

    def code_scroll_for_docking(self) -> tuple[int, int]:
        """Retain the docked offset when a larger window temporarily fits all code."""
        horizontal = self.document.code.horizontalScrollBar()
        vertical = self.document.code.verticalScrollBar()
        return (
            horizontal.value() if horizontal.maximum() else self._docked_code_scroll[0],
            vertical.value() if vertical.maximum() else self._docked_code_scroll[1],
        )

    def release_document(self) -> UnifiedDocumentWidget:
        """Release without redocking while a project/session is being replaced."""

        self._dock_on_close = False
        self.document.execution_toolbar.removeAction(self.action_dock)
        for action in (self.action_run, self.action_trace, self.action_debug, self.action_stop):
            self.removeAction(action)
            action.setShortcut(QKeySequence())
        taken = self.takeCentralWidget()
        if not isinstance(taken, UnifiedDocumentWidget):
            raise RuntimeError("Detached window lost its unified document")
        return taken

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._dock_on_close:
            self.dockRequested.emit(self.document.diagram_id)
        event.accept()


def position_near(rect: QRect, requested: object) -> QPoint:
    """Choose a stable initial position for shortcut, double-click, or drag detachment."""

    if isinstance(requested, QPoint):
        return requested - QPoint(80, 18)
    return rect.topLeft() + QPoint(80, 80)
