"""Background loopback host for desktop and synchronous embedding scenarios."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from threading import Event, Thread

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.git_service import GitProjectController
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.messages import EventEnvelope
from code_visualizer.automation.service import AutomationService
from code_visualizer.automation.websocket import AutomationWebSocketServer


class LocalAutomationHost:
    def __init__(
        self,
        authority: ProjectAuthority,
        *,
        project_root: Callable[[], Path | None] | None = None,
        event_listener: Callable[[EventEnvelope], None] | None = None,
        kernel: ProjectKernel | None = None,
        git: GitProjectController | None = None,
    ) -> None:
        self.service = AutomationService(
            authority,
            project_root=project_root,
            kernel=kernel,
            git=git,
        )
        self.server = AutomationWebSocketServer(
            self.service,
            event_listener=event_listener,
        )
        self._thread: Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._started = Event()
        self._error: BaseException | None = None

    @property
    def endpoint(self) -> str:
        return self.server.endpoint

    @property
    def token(self) -> str:
        return self.server.token

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, *, timeout: float = 10.0) -> LocalAutomationHost:
        if self.running:
            return self
        self._started.clear()
        self._error = None
        self._thread = Thread(
            target=self._run,
            name="code-visualizer-automation",
            daemon=True,
        )
        self._thread.start()
        if not self._started.wait(timeout):
            raise RuntimeError("Timed out starting the local automation endpoint")
        if self._error is not None:
            raise RuntimeError("Could not start the local automation endpoint") from self._error
        return self

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.server.start())
        except BaseException as exc:
            self._error = exc
            self._started.set()
            loop.close()
            self._loop = None
            return
        self._started.set()
        try:
            loop.run_forever()
        finally:
            if self.server.port:
                loop.run_until_complete(self.server.stop())
            loop.close()
            self._loop = None

    def stop(self, *, timeout: float = 10.0) -> None:
        loop = self._loop
        thread = self._thread
        if loop is None or thread is None:
            return
        future = asyncio.run_coroutine_threadsafe(self.server.stop(), loop)
        try:
            future.result(timeout=timeout)
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=timeout)
            self._thread = None
            self.service.close()
