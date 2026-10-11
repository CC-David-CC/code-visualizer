"""Bounded GUI observation of the existing host and runtime registries."""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from code_visualizer.application.computation_service import ComputationAttempt
from code_visualizer.application.kernel import ProjectKernel


class QtRuntimeObserver(QObject):
    """Sample immutable latest state without queuing one Qt event per worker update."""

    runtimeChanged = Signal(object)
    attemptsChanged = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._kernel: ProjectKernel | None = None
        self._runtime_key: tuple[object, ...] = ()
        self._attempts: tuple[ComputationAttempt, ...] = ()
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self.poll)

    def attach(self, kernel: ProjectKernel | None) -> None:
        self._timer.stop()
        self._kernel = kernel
        self._runtime_key = ()
        self._attempts = ()
        if kernel is not None:
            self._runtime_key = (None, None, None, None)
            self._timer.start()
            self.poll()

    def poll(self) -> None:
        kernel = self._kernel
        if kernel is None:
            return
        kernel.computations.deliver_selection(kernel.computation_attachment)
        state = kernel.runtime.active
        key = (
            kernel.revision if state else None,
            state.execution_session_id if state else None,
            state.event_sequence if state else None,
            state.status if state else None,
        )
        if key != self._runtime_key:
            self._runtime_key = key
            self.runtimeChanged.emit(state)
        attempts = kernel.computations.attempts()
        if attempts != self._attempts:
            self._attempts = attempts
            self.attemptsChanged.emit(attempts)
