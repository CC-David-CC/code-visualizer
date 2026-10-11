"""Bounded, explicit local Python child-process execution and tracing."""

from __future__ import annotations

import os
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from io import TextIOBase
from pathlib import Path
from time import perf_counter

from code_visualizer.domain.invocation import (
    InvocationResultPolicy,
    InvocationSpec,
    invocation_symbols,
    render_invocation,
)
from code_visualizer.domain.python_symbols import PythonSymbolAllocator, python_identifiers
from code_visualizer.execution.child_process import project_child_command, python_child_command
from code_visualizer.execution.debugger import DebugEvent, DebugLaunch, DebugSession
from code_visualizer.execution.project_files import MaterializedProject
from code_visualizer.execution.python_artifacts import PythonArtifactContext
from code_visualizer.execution.runtime import RuntimeBindingSpec, SourceLocation
from code_visualizer.execution.worker_process import OwnedProcessTree
from code_visualizer.generation.emitter import GeneratedProject

TRACE_PREFIX = "@@CODE_VISUALIZER_TRACE@@"


@dataclass(frozen=True, slots=True)
class RunResult:
    return_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    duration_seconds: float = 0.0
    termination_reason: str = "exited"
    output_truncated: bool = False


@dataclass(frozen=True, slots=True)
class TraceEvent:
    index: int
    event: str
    line: int
    function: str
    locals: tuple[tuple[str, str], ...] = ()
    detail: str = ""
    file_path: str = "<code-visualizer-debug>"

    @property
    def location(self) -> SourceLocation | None:
        return SourceLocation(self.file_path, self.line) if self.line > 0 else None


@dataclass(frozen=True, slots=True)
class TraceResult:
    run: RunResult
    events: tuple[TraceEvent, ...]
    events_truncated: bool = False
    runtime_events: tuple[DebugEvent, ...] = ()
    terminal_event: DebugEvent | None = None


def _bounded(value: str, limit: int) -> tuple[str, bool]:
    if len(value) <= limit:
        return value, False
    return value[:limit] + "\n… output truncated …\n", True


@dataclass(slots=True)
class _BoundedCapture:
    limit: int
    parts: list[str]
    length: int = 0
    truncated: bool = False

    def read(self, stream: TextIOBase) -> None:
        while chunk := stream.read(8192):
            self.append(chunk)

    def append(self, chunk: str) -> None:
        remaining = self.limit - self.length
        if remaining > 0:
            kept = chunk[:remaining]
            self.parts.append(kept)
            self.length += len(kept)
        if len(chunk) > max(0, remaining):
            self.truncated = True

    def text(self) -> str:
        value = "".join(self.parts)
        if self.truncated:
            value += "\n… output truncated …\n"
        return value


def _run(
    arguments: list[str],
    *,
    timeout: float,
    cwd: Path | None = None,
    environment: dict[str, str] | None = None,
    output_limit: int = 1_000_000,
    session: RunSession | None = None,
) -> RunResult:
    started = perf_counter()
    child_environment = None
    if environment is not None:
        child_environment = os.environ.copy()
        child_environment.update(environment)
    if output_limit < 1:
        raise ValueError("output_limit must be positive")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if session is not None and session.stop_requested:
        return RunResult(-1, "", "", termination_reason="stopped")
    options = OwnedProcessTree.popen_options()
    process = subprocess.Popen(
        arguments,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
        env=child_environment,
        creationflags=int(options.get("creationflags", 0)),
        start_new_session=bool(options.get("start_new_session", False)),
    )
    try:
        tree = OwnedProcessTree(process)
    except BaseException:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        raise
    assert process.stdout is not None
    assert process.stderr is not None
    stdout_capture = _BoundedCapture(output_limit, [])
    stderr_capture = _BoundedCapture(output_limit, [])
    readers = (
        threading.Thread(target=stdout_capture.read, args=(process.stdout,), daemon=True),
        threading.Thread(target=stderr_capture.read, args=(process.stderr,), daemon=True),
    )
    for reader in readers:
        reader.start()
    timed_out = False
    deadline = started + timeout
    try:
        while process.poll() is None:
            if session is not None and session.stop_requested:
                session._record_forced_termination(True)
                tree.terminate()
                break
            remaining = deadline - perf_counter()
            if remaining <= 0:
                timed_out = True
                if session is not None:
                    session._record_forced_termination(True)
                tree.terminate()
                break
            try:
                process.wait(timeout=min(0.05, remaining))
            except subprocess.TimeoutExpired:
                continue
    finally:
        # A naturally exited parent may leave descendants holding stdout or the
        # generated working directory. Reap the entire owned tree before output
        # delivery and the caller's temporary-project cleanup boundary.
        tree.close()
        for reader in readers:
            reader.join(timeout=5.0)
            if reader.is_alive():
                raise TimeoutError("Python output did not finish after its process tree exited")
        process.stdout.close()
        process.stderr.close()
    stopped = session.stop_requested if session is not None else False
    return_code = process.returncode if process.returncode is not None else -1
    reason = (
        "stopped"
        if stopped
        else "timeout"
        if timed_out
        else "exited"
        if return_code == 0
        else "error"
    )
    return RunResult(
        -1 if timed_out else return_code,
        stdout_capture.text(),
        stderr_capture.text(),
        timed_out=timed_out,
        duration_seconds=perf_counter() - started,
        termination_reason=reason,
        output_truncated=stdout_capture.truncated or stderr_capture.truncated,
    )


class RunSession:
    """One cancellable, bounded child run suitable for a GUI adapter."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop_requested = False
        self._forced_termination = False

    @property
    def is_active(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    @property
    def stop_requested(self) -> bool:
        with self._lock:
            return self._stop_requested

    @property
    def forced_termination(self) -> bool:
        with self._lock:
            return self._forced_termination

    def _record_forced_termination(self, forced: bool) -> None:
        with self._lock:
            self._forced_termination = forced

    def start_source(
        self,
        source: str,
        *,
        invocation: InvocationSpec | None,
        timeout: float = 30.0,
        completed: Callable[[RunResult], None],
    ) -> None:
        with self._lock:
            if self.is_active:
                raise RuntimeError("A child run is already active")
            self._stop_requested = False
            self._forced_termination = False
            invocation_source = (
                render_invocation(
                    invocation,
                    result_policy=InvocationResultPolicy.PRINT,
                    symbols=invocation_symbols(
                        invocation, allocator=PythonSymbolAllocator(python_identifiers(source))
                    ),
                )
                if invocation is not None
                else ""
            )
            command = python_child_command(["-I", "-c", source + "\n" + invocation_source])
            thread = threading.Thread(
                target=self._work,
                args=(command, timeout, completed),
                name="code-visualizer-run",
                daemon=True,
            )
            self._thread = thread
            thread.start()

    def _start_task[T](
        self,
        operation: Callable[[], T],
        completed: Callable[[T], None],
        *,
        name: str,
        failed: Callable[[Exception], T],
    ) -> None:
        def work() -> None:
            try:
                try:
                    result = operation()
                except Exception as exc:
                    result = failed(exc)
                completed(result)
            finally:
                with self._lock:
                    self._thread = None

        with self._lock:
            if self.is_active:
                raise RuntimeError("A child run is already active")
            self._stop_requested = False
            self._forced_termination = False
            self._thread = threading.Thread(target=work, name=name, daemon=True)
            self._thread.start()

    def start_project(
        self,
        project: GeneratedProject,
        *,
        timeout: float = 30.0,
        interpreter: str = "",
        working_directory: Path | None = None,
        environment: dict[str, str] | None = None,
        output_limit: int = 1_000_000,
        completed: Callable[[RunResult], None],
    ) -> None:
        self._start_task(
            lambda: run_project(
                project,
                timeout=timeout,
                interpreter=interpreter,
                working_directory=working_directory,
                environment=environment,
                session=self,
                output_limit=output_limit,
            ),
            completed,
            name="code-visualizer-project-run",
            failed=lambda exc: RunResult(
                -1, "", f"{type(exc).__name__}: {exc}\n", termination_reason="error"
            ),
        )

    def start_project_trace(
        self,
        project: GeneratedProject,
        *,
        timeout: float = 30.0,
        max_events: int = 2_000,
        project_revision: int = 0,
        artifact_revision: int | None = None,
        binding_specs: tuple[RuntimeBindingSpec, ...] = (),
        interpreter: str = "",
        working_directory: Path | None = None,
        environment: dict[str, str] | None = None,
        output_limit: int = 1_000_000,
        completed: Callable[[TraceResult], None],
        computation: PythonArtifactContext | None = None,
    ) -> None:
        self._start_task(
            lambda: trace_project(
                project,
                timeout=timeout,
                max_events=max_events,
                project_revision=project_revision,
                artifact_revision=artifact_revision,
                binding_specs=binding_specs,
                interpreter=interpreter,
                working_directory=working_directory,
                environment=environment,
                session=self,
                output_limit=output_limit,
                computation=computation,
            ),
            completed,
            name="code-visualizer-project-trace",
            failed=lambda exc: TraceResult(
                RunResult(-1, "", f"{type(exc).__name__}: {exc}\n", termination_reason="error"), ()
            ),
        )

    def start_trace(
        self,
        source: str,
        *,
        invocation: InvocationSpec | None,
        timeout: float = 30.0,
        max_events: int = 2_000,
        project_revision: int = 0,
        artifact_revision: int | None = None,
        binding_specs: tuple[RuntimeBindingSpec, ...] = (),
        completed: Callable[[TraceResult], None],
    ) -> None:
        with self._lock:
            if self.is_active:
                raise RuntimeError("A child run is already active")
            self._stop_requested = False
            self._forced_termination = False
            thread = threading.Thread(
                target=self._trace_work,
                args=(
                    source,
                    invocation,
                    timeout,
                    max_events,
                    project_revision,
                    artifact_revision,
                    binding_specs,
                    completed,
                ),
                name="code-visualizer-trace",
                daemon=True,
            )
            self._thread = thread
            thread.start()

    def start_generated(
        self,
        project_file: Path,
        *,
        timeout: float = 30.0,
        interpreter: str = "",
        working_directory: Path | None = None,
        environment: dict[str, str] | None = None,
        completed: Callable[[RunResult], None],
    ) -> None:
        resolved = project_file.resolve()
        command = project_child_command(resolved.parent, resolved, interpreter=interpreter)
        with self._lock:
            if self.is_active:
                raise RuntimeError("A child run is already active")
            self._stop_requested = False
            self._forced_termination = False
            thread = threading.Thread(
                target=self._work,
                args=(command, timeout, completed, working_directory, environment),
                name="code-visualizer-project-run",
                daemon=True,
            )
            self._thread = thread
            thread.start()

    def stop(self) -> bool:
        with self._lock:
            active = self._thread is not None and self._thread.is_alive()
            self._stop_requested = True
        return active

    def wait(self, timeout: float = 5.0) -> bool:
        """Join a requested shutdown without changing the nonblocking stop API."""
        if timeout <= 0:
            raise ValueError("Runner completion requires a positive timeout")
        with self._lock:
            thread = self._thread
        if thread is None:
            return True
        if thread is threading.current_thread():
            return False
        thread.join(timeout)
        return not thread.is_alive()

    def _work(
        self,
        command: list[str],
        timeout: float,
        completed: Callable[[RunResult], None],
        cwd: Path | None = None,
        environment: dict[str, str] | None = None,
    ) -> None:
        result = _run(
            command,
            timeout=timeout,
            cwd=cwd,
            environment=environment,
            session=self,
        )
        try:
            completed(result)
        finally:
            with self._lock:
                self._thread = None

    def _trace_work(
        self,
        source: str,
        invocation: InvocationSpec | None,
        timeout: float,
        max_events: int,
        project_revision: int,
        artifact_revision: int | None,
        binding_specs: tuple[RuntimeBindingSpec, ...],
        completed: Callable[[TraceResult], None],
    ) -> None:
        result = trace_source(
            source,
            invocation=invocation,
            timeout=timeout,
            max_events=max_events,
            project_revision=project_revision,
            artifact_revision=artifact_revision,
            binding_specs=binding_specs,
            session=self,
        )
        try:
            completed(result)
        finally:
            with self._lock:
                self._thread = None


def run_source(
    source: str,
    *,
    invocation: InvocationSpec | None,
    timeout: float = 5.0,
    output_limit: int = 1_000_000,
) -> RunResult:
    invocation_source = (
        render_invocation(
            invocation,
            result_policy=InvocationResultPolicy.PRINT,
            symbols=invocation_symbols(
                invocation, allocator=PythonSymbolAllocator(python_identifiers(source))
            ),
        )
        if invocation is not None
        else ""
    )
    return _run(
        python_child_command(["-I", "-c", source + "\n" + invocation_source]),
        timeout=timeout,
        output_limit=output_limit,
    )


def trace_source(
    source: str,
    *,
    invocation: InvocationSpec | None,
    timeout: float = 5.0,
    max_events: int = 2_000,
    output_limit: int = 1_000_000,
    session: RunSession | None = None,
    project_revision: int = 0,
    artifact_revision: int | None = None,
    binding_specs: tuple[RuntimeBindingSpec, ...] = (),
) -> TraceResult:
    return _trace_launch(
        DebugLaunch(
            source,
            invocation,
            max_history=max_events,
            project_revision=project_revision,
            artifact_revision=project_revision if artifact_revision is None else artifact_revision,
            binding_specs=binding_specs,
            record=True,
        ),
        timeout=timeout,
        max_events=max_events,
        output_limit=output_limit,
        session=session,
    )


def trace_project(
    project: GeneratedProject,
    *,
    timeout: float = 5.0,
    max_events: int = 2_000,
    output_limit: int = 1_000_000,
    session: RunSession | None = None,
    project_revision: int = 0,
    artifact_revision: int | None = None,
    binding_specs: tuple[RuntimeBindingSpec, ...] = (),
    interpreter: str = "",
    working_directory: Path | None = None,
    environment: dict[str, str] | None = None,
    computation: PythonArtifactContext | None = None,
) -> TraceResult:
    return _trace_launch(
        DebugLaunch(
            project=project,
            max_history=max_events,
            project_revision=project_revision,
            artifact_revision=project_revision if artifact_revision is None else artifact_revision,
            binding_specs=binding_specs,
            record=True,
            interpreter=interpreter,
            working_directory=working_directory,
            environment=environment,
            computation=computation,
        ),
        timeout=timeout,
        max_events=max_events,
        output_limit=output_limit,
        session=session,
    )


def _trace_launch(
    launch: DebugLaunch,
    *,
    timeout: float,
    max_events: int,
    output_limit: int,
    session: RunSession | None,
) -> TraceResult:
    if max_events < 1:
        raise ValueError("max_events must be positive")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if output_limit < 1:
        raise ValueError("output_limit must be positive")
    started = perf_counter()
    events: list[TraceEvent] = []
    runtime_events: list[DebugEvent] = []
    stdout = _BoundedCapture(output_limit, [])
    stderr = _BoundedCapture(output_limit, [])
    terminal = None
    events_truncated = False
    debugger = DebugSession(history_limit=max_events)
    debugger.start(launch)
    deadline = started + timeout
    while terminal is None:
        if session is not None and session.stop_requested:
            debugger.stop()
            break
        remaining = deadline - perf_counter()
        if remaining <= 0:
            debugger.stop()
            break
        try:
            event = debugger.wait_event(min(0.1, remaining))
        except TimeoutError:
            continue
        if event.event == "trace":
            runtime_events.append(event)
            events.append(
                TraceEvent(
                    len(events),
                    event.trace_event,
                    event.line,
                    event.function,
                    event.locals,
                    event.detail,
                    event.file_path,
                )
            )
        elif event.event == "output":
            (stdout if event.channel == "stdout" else stderr).append(event.text)
        elif event.event in {"finished", "failed", "stopped"}:
            terminal = event
            events_truncated = event.history_truncated
    timed_out = terminal is None and not (session is not None and session.stop_requested)
    stopped = terminal is None and session is not None and session.stop_requested
    debugger.stop()
    if session is not None:
        session._record_forced_termination(debugger.forced_termination)
    if (
        terminal is not None
        and terminal.event == "finished"
        and terminal.result not in {"", "None"}
    ):
        stdout.append(f"{terminal.result}\n")
    if terminal is not None and terminal.event == "failed" and terminal.traceback:
        stderr.append(terminal.traceback)
    stdout_text, stdout_truncated = stdout.text(), stdout.truncated
    stderr_text, stderr_truncated = stderr.text(), stderr.truncated
    return_code = (
        terminal.return_code if terminal is not None and terminal.return_code is not None else -1
    )
    termination_reason = (
        "timeout"
        if timed_out
        else "stopped"
        if stopped or (terminal is not None and terminal.event == "stopped")
        else "error"
        if terminal is not None and terminal.event == "failed"
        else "exited"
    )
    return TraceResult(
        RunResult(
            return_code,
            stdout_text,
            stderr_text,
            timed_out,
            perf_counter() - started,
            termination_reason,
            stdout_truncated or stderr_truncated,
        ),
        tuple(events),
        events_truncated,
        tuple(runtime_events),
        terminal,
    )


def run_generated(
    project_file: Path,
    *,
    timeout: float = 10.0,
    interpreter: str = "",
    working_directory: Path | None = None,
    environment: dict[str, str] | None = None,
    output_limit: int = 1_000_000,
) -> RunResult:
    resolved = project_file.resolve()
    return _run(
        project_child_command(resolved.parent, resolved, interpreter=interpreter),
        timeout=timeout,
        cwd=working_directory,
        environment=environment,
        output_limit=output_limit,
    )


def run_project(
    project: GeneratedProject,
    *,
    timeout: float = 10.0,
    interpreter: str = "",
    working_directory: Path | None = None,
    environment: dict[str, str] | None = None,
    output_limit: int = 1_000_000,
    session: RunSession | None = None,
) -> RunResult:
    with MaterializedProject(project) as tree:
        return _run(
            project_child_command(tree.root, tree.launcher, interpreter=interpreter),
            timeout=timeout,
            cwd=working_directory or tree.root,
            environment=environment,
            output_limit=output_limit,
            session=session,
        )
