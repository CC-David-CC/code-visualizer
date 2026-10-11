"""Bound top-level editor windows to their available monitor work area."""

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QApplication, QLayout, QWidget


class WindowBounds(QObject):
    """Coalesce geometry changes without doing layout work inside resize events."""

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self.window = window
        self._handle_connected = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self.constrain)
        window.installEventFilter(self)
        window.setMinimumSize(0, 0)
        layout = window.layout()
        if layout is not None:
            layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        application = QApplication.instance()
        if isinstance(application, QApplication):
            application.screenRemoved.connect(self.schedule)
            application.screenAdded.connect(self._screen_added)
            for screen in application.screens():
                screen.availableGeometryChanged.connect(self.schedule)

    def _screen_added(self, screen: object) -> None:
        from PySide6.QtGui import QScreen

        if isinstance(screen, QScreen):
            screen.availableGeometryChanged.connect(self.schedule)
        self.schedule()

    def schedule(self, *_args: object) -> None:
        self._timer.start()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in {
            QEvent.Type.Show,
            QEvent.Type.Move,
            QEvent.Type.Resize,
            QEvent.Type.WindowStateChange,
        }:
            self.schedule()
        return False

    def constrain(self) -> None:
        window = self.window
        if not window.isVisible():
            return
        handle = window.windowHandle()
        if handle is not None and not self._handle_connected:
            handle.screenChanged.connect(self.schedule)
            self._handle_connected = True
        screen = QApplication.screenAt(window.frameGeometry().center())
        screen = screen or window.screen()
        available = screen.availableGeometry()
        frame = window.frameGeometry()
        # Decorations are outside QWidget.size(), but inside the work-area limit.
        border_width = max(0, frame.width() - window.width())
        border_height = max(0, frame.height() - window.height())
        width = max(1, available.width() - border_width)
        height = max(1, available.height() - border_height)
        window.setMaximumSize(width, height)
        if window.isMaximized() or window.isFullScreen():
            return
        window.resize(min(window.width(), width), min(window.height(), height))
        frame = window.frameGeometry()
        x = min(max(frame.x(), available.left()), available.right() - frame.width() + 1)
        y = min(max(frame.y(), available.top()), available.bottom() - frame.height() + 1)
        if (x, y) != (frame.x(), frame.y()):
            window.move(x, y)
