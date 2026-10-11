"""Qt samples the typed editor preparation mailbox without worker callbacks."""

from collections.abc import Callable
from enum import StrEnum

from PySide6.QtCore import QObject, QTimer, Signal

from code_visualizer.application.editor_preparation import EditorPreparation, EditorPreparedSnapshot
from code_visualizer.domain.invocation_arguments import InvocationArguments
from code_visualizer.domain.project import Project
from code_visualizer.execution.worker_process import WorkerProfile
from code_visualizer.persistence.resource_store import ResourceStore


class EditorAction(StrEnum):
    PREVIEW = "preview"
    RUN = "run"
    TRACE = "trace"
    DEBUG = "debug"


class QtEditorPreparation(QObject):
    changed = Signal(object)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        profiles: tuple[WorkerProfile, ...] | None = None,
        resource_store: ResourceStore | None = None,
        current_project: Callable[[], Project] | None = None,
    ) -> None:
        super().__init__(parent)
        self._preparation = EditorPreparation(profiles=profiles, resource_store=resource_store)
        self._current_project = current_project
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self.poll)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(100)
        self._debounce.timeout.connect(self._submit)
        self._project: Project | None = None
        self._focus: str | None = None
        self._model: str | None = None
        self._arguments: InvocationArguments | None = None
        self._last: EditorPreparedSnapshot | None = None
        self.action = EditorAction.PREVIEW
        self.request_id: str | None = None
        self.destroyed.connect(self._preparation.close)

    def request(
        self,
        project: Project,
        action: EditorAction,
        *,
        focus_diagram_id: str | None = None,
        model_id: str | None = None,
        arguments: InvocationArguments | None = None,
    ) -> None:
        if (
            action is EditorAction.PREVIEW
            and self.action is action
            and self._project is project
            and self._focus == focus_diagram_id
            and self._model == model_id
        ):
            return
        self.cancel()
        self._project, self._focus, self._model, self._arguments = (
            project,
            focus_diagram_id,
            model_id,
            arguments,
        )
        self.action = action
        if action is EditorAction.PREVIEW:
            self._debounce.start()
        else:
            self._submit()

    def _submit(self) -> None:
        project = self._project
        if project is None:
            return
        # An authority edit can precede its queued Qt notification. Coalesce
        # previews at dispatch, before starting an already obsolete worker.
        # Explicit execution requests retain their selected immutable snapshot.
        if self.action is EditorAction.PREVIEW and self._current_project is not None:
            project = self._project = self._current_project()
        self.request_id = self._preparation.submit(
            project,
            focus_diagram_id=self._focus,
            model_id=self._model,
            arguments=self._arguments,
        )
        self._timer.start()
        self.poll()

    def poll(self) -> None:
        view = self._preparation.snapshot()
        if view is not None and view.request_id == self.request_id and view != self._last:
            self._last = view
            self.changed.emit(view)
            if view.request_id == self.request_id and view.status in {
                "ready",
                "failed",
                "cancelled",
            }:
                self._timer.stop()

    def matches(
        self, project: Project, *, focus_diagram_id: str | None = None, model_id: str | None = None
    ) -> bool:
        return (
            self._project is project and self._focus == focus_diagram_id and self._model == model_id
        )

    @property
    def pending(self) -> bool:
        return self._debounce.isActive() or self._timer.isActive()

    def cancel(self) -> None:
        self._debounce.stop()
        self._timer.stop()
        self._preparation.cancel()
        self.request_id, self._last = None, None
        self._project = None

    def close(self) -> None:
        self.cancel()
        self._preparation.close()
