"""Bounded off-thread example installation; only session handoff occurs in Qt."""

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.examples import example_session
from code_visualizer.application.session import ProjectSession


@dataclass(frozen=True, slots=True)
class PreparedExample:
    session: ProjectSession
    context: object


class ResourceExampleLoader(QObject):
    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="example-inputs")
        self._future: Future[ProjectSession] | None = None
        self._context: object = None
        self._closed = False
        self._timer = QTimer(self)
        self._timer.setInterval(20)
        self._timer.timeout.connect(self._poll)
        self.destroyed.connect(self.close)

    @property
    def busy(self) -> bool:
        return self._future is not None

    def begin(
        self, example_id: str, destination: Path, computations: ComputationService, context: object
    ) -> bool:
        if self.busy or self._closed:
            return False
        self._context = context
        self._future = self._executor.submit(
            example_session, example_id, destination=destination, computations=computations
        )
        self._timer.start()
        return True

    def _poll(self) -> None:
        future = self._future
        if future is None or not future.done():
            return
        self._future = None
        self._timer.stop()
        error = future.exception()
        if error is not None:
            self.failed.emit(str(error))
        else:
            self.ready.emit(PreparedExample(future.result(), self._context))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._timer.stop()
        future, self._future = self._future, None
        if future is not None:

            def retire(result: Future[ProjectSession]) -> None:
                if not result.cancelled() and result.exception() is None:
                    result.result().close()

            future.add_done_callback(retire)
        self._executor.shutdown(wait=False)
