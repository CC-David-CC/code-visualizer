"""Parent-side controller for the isolated interactive debugger protocol."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
from collections import deque
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from time import monotonic
from uuid import uuid4

from code_visualizer.domain.boundaries import MAX_PORTABLE_ENVELOPE_BYTES
from code_visualizer.domain.invocation import (
    INVOCATION_RESULT_NAME,
    InvocationResultPolicy,
    InvocationSpec,
    invocation_symbols,
    render_invocation,
)
from code_visualizer.domain.python_symbols import PythonSymbolAllocator, python_identifiers
from code_visualizer.execution.child_process import debug_worker_command
from code_visualizer.execution.project_files import MaterializedProject
from code_visualizer.execution.python_artifacts import PythonArtifactContext
from code_visualizer.execution.runtime import (
    RuntimeBindingSpec,
    RuntimeGraph,
    RuntimeGraphAccumulator,
    RuntimeGraphDelta,
    RuntimeTraceStore,
    SourceLocation,
)
from code_visualizer.execution.worker_process import OwnedProcessTree
from code_visualizer.generation.emitter import GeneratedProject


class DebugState(StrEnum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_INPUT = "waiting_input"
    FINISHED = "finished"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class DebugFrame:
    function: str
    line: int
    frame_id: str = ""
    file_path: str = "<code-visualizer-debug>"

    @property
    def location(self) -> SourceLocation | None:
        return SourceLocation(self.file_path, self.line) if self.line > 0 else None


@dataclass(frozen=True, slots=True)
class DebugEvent:
    sequence: int
    event: str
    state: DebugState
    line: int = 0
    function: str = ""
    reason: str = ""
    detail: str = ""
    channel: str = ""
    text: str = ""
    locals: tuple[tuple[str, str], ...] = ()
    changed_locals: tuple[str, ...] = ()
    removed_locals: tuple[str, ...] = ()
    stack: tuple[DebugFrame, ...] = ()
    return_code: int | None = None
    result: str = ""
    traceback: str = ""
    history_truncated: bool = False
    execution_session_id: str = ""
    project_revision: int = 0
    artifact_revision: int = 0
    runtime_graph: RuntimeGraph | None = None
    runtime_delta: RuntimeGraphDelta | None = None
    trace_event: str = ""
    file_path: str = "<code-visualizer-debug>"

    @property
    def location(self) -> SourceLocation | None:
        return SourceLocation(self.file_path, self.line) if self.line > 0 else None


@dataclass(frozen=True, slots=True)
class DebugLaunch:
    source: str | None = None
    invocation: InvocationSpec | None = None
    breakpoints: tuple[int | SourceLocation, ...] = ()
    pause_on_exception: bool = True
    max_history: int = 500
    execution_session_id: str = field(default_factory=lambda: f"execution_{uuid4().hex}")
    project_revision: int = 0
    artifact_revision: int = 0
    binding_specs: tuple[RuntimeBindingSpec, ...] = ()
    record: bool = False
    project: GeneratedProject | None = None
    interpreter: str = ""
    working_directory: Path | None = None
    environment: dict[str, str] | None = None
    computation: PythonArtifactContext | None = None

    def __post_init__(self) -> None:
        if (self.source is None) == (self.project is None):
            raise ValueError("Choose a generated project or an explicit source snapshot")
        if self.project is not None:
            if self.invocation is not None:
                raise ValueError("A generated project's launcher already owns its invocation")
            if any(not isinstance(item, SourceLocation) for item in self.breakpoints):
                raise ValueError("Project breakpoints require a file-qualified SourceLocation")
            emitted_paths = {item.path for item in self.project.files}
            if any(
                isinstance(item, SourceLocation) and item.file_path not in emitted_paths
                for item in self.breakpoints
            ):
                raise ValueError("A project breakpoint must name an emitted file")
        if not self.execution_session_id:
            raise ValueError("execution_session_id must not be empty")
        if self.project_revision < 0 or self.artifact_revision < 0:
            raise ValueError("debugger revisions must not be negative")


def _state_for_event(event: str, current: DebugState) -> DebugState:
    return {
        "started": DebugState.RUNNING,
        "paused": DebugState.PAUSED,
        "input_requested": DebugState.WAITING_INPUT,
        "finished": DebugState.FINISHED,
        "failed": DebugState.FAILED,
        "stopped": DebugState.STOPPED,
    }.get(event, current)


def _decode_locals(
    raw: object, previous: dict[str, tuple[str, str]] | None
) -> tuple[tuple[str, str], ...]:
    items: list[tuple[str, str]] = []
    if isinstance(raw, dict):
        for name, value in raw.items():
            name, value = str(name), str(value)
            pair = previous.get(name) if previous is not None else None
            items.append(pair if pair is not None and pair[1] == value else (name, value))
    items.sort()
    if previous is not None:
        previous.clear()
        previous.update((pair[0], pair) for pair in items)
    return tuple(items)


def _decode_event(
    value: object,
    current: DebugState,
    runtime: RuntimeGraphAccumulator,
    local_pairs: dict[str, tuple[str, str]] | None = None,
) -> DebugEvent | None:
    if not isinstance(value, dict):
        return None
    event = value.get("event")
    sequence = value.get("sequence")
    if not isinstance(event, str) or not isinstance(sequence, int):
        return None
    local_items = _decode_locals(value.get("locals", {}), local_pairs)
    raw_stack = value.get("stack", [])
    stack: list[DebugFrame] = []
    if isinstance(raw_stack, list):
        for raw_frame in raw_stack:
            if not isinstance(raw_frame, dict):
                continue
            function = raw_frame.get("function")
            line = raw_frame.get("line")
            frame_id = raw_frame.get("frame_id")
            if isinstance(function, str) and isinstance(line, int):
                stack.append(
                    DebugFrame(
                        function,
                        line,
                        frame_id if isinstance(frame_id, str) else "",
                        str(raw_frame.get("file_path", "<code-visualizer-debug>")),
                    )
                )
    return_code = value.get("return_code")
    execution_session_id = value.get("execution_session_id")
    project_revision = value.get("project_revision")
    artifact_revision = value.get("artifact_revision")
    typed_session_id = execution_session_id if isinstance(execution_session_id, str) else ""
    typed_project_revision = (
        project_revision
        if isinstance(project_revision, int) and not isinstance(project_revision, bool)
        else 0
    )
    typed_artifact_revision = (
        artifact_revision
        if isinstance(artifact_revision, int) and not isinstance(artifact_revision, bool)
        else typed_project_revision
    )
    runtime_delta = runtime.decode_delta(
        value.get("runtime_snapshot"),
        execution_session_id=typed_session_id,
        project_revision=typed_project_revision,
        artifact_revision=typed_artifact_revision,
        sequence=sequence,
    )
    runtime_graph = runtime.apply_delta(runtime_delta) if runtime_delta is not None else None
    return DebugEvent(
        sequence=sequence,
        event=event,
        state=_state_for_event(event, current),
        line=value.get("line", 0) if isinstance(value.get("line"), int) else 0,
        function=str(value.get("function", "")),
        reason=str(value.get("reason", "")),
        detail=str(value.get("detail", "")),
        channel=str(value.get("channel", "")),
        text=str(value.get("text", "")),
        locals=local_items,
        changed_locals=tuple(str(item) for item in value.get("changed_locals", ())),
        removed_locals=tuple(str(item) for item in value.get("removed_locals", ())),
        stack=tuple(stack),
        return_code=return_code if isinstance(return_code, int) else None,
        result=str(value.get("result", "")),
        traceback=str(value.get("traceback", "")),
        history_truncated=bool(value.get("history_truncated", False)),
        execution_session_id=typed_session_id,
        project_revision=typed_project_revision,
        artifact_revision=typed_artifact_revision,
        runtime_graph=runtime_graph,
        runtime_delta=runtime_delta,
        trace_event=str(value.get("trace_event", "")),
        file_path=str(value.get("file_path", "<code-visualizer-debug>")),
    )


class DebugSession:
    """Own one debugger child and expose a thread-safe event queue."""

    def __init__(self, *, history_limit: int = 500, event_capacity: int = 256) -> None:
        if history_limit < 1:
            raise ValueError("history_limit must be positive")
        if type(event_capacity) is not int or not 1 <= event_capacity <= 4096:
            raise ValueError("event_capacity must be between one and 4096")
        self.history_limit = history_limit
        self.event_capacity = event_capacity
        self.state = DebugState.IDLE
        self.history: deque[DebugEvent] = deque(maxlen=history_limit)
        self._events: queue.Queue[DebugEvent] = queue.Queue(maxsize=event_capacity)
        self._delivery_stopped = threading.Event()
        self._process: subprocess.Popen[str] | None = None
        self._owned_process: OwnedProcessTree | None = None
        self._tree: MaterializedProject | None = None
        self._launch: DebugLaunch | None = None
        self._lock = threading.RLock()
        self._stderr: list[str] = []
        self._stderr_length = 0
        self.forced_termination = False
        self._runtime = RuntimeGraphAccumulator()
        self._local_pairs: dict[str, tuple[str, str]] = {}
        self._runtime_trace = RuntimeTraceStore(history_limit=history_limit)
        self._received_state = DebugState.IDLE
        self._terminal_received = threading.Event()
        self._stderr_drained = threading.Event()

    @property
    def is_active(self) -> bool:
        return self.state in {
            DebugState.STARTING,
            DebugState.RUNNING,
            DebugState.PAUSED,
            DebugState.WAITING_INPUT,
        }

    @property
    def launch(self) -> DebugLaunch | None:
        return self._launch

    @property
    def runtime_trace(self) -> RuntimeTraceStore:
        return self._runtime_trace

    def start(self, launch: DebugLaunch) -> None:
        self.stop()
        tree = MaterializedProject(launch.project) if launch.project is not None else None
        try:
            computation = (
                launch.computation.configuration(tree.files if tree else {})
                if launch.computation
                else None
            )
        except BaseException:
            if tree is not None:
                tree.close()
            raise
        worker = Path(__file__).with_name("debug_worker.py")
        process_options = OwnedProcessTree.popen_options()
        environment = None
        if launch.environment is not None:
            environment = {**os.environ, **launch.environment}
        try:
            process = subprocess.Popen(
                debug_worker_command(worker, interpreter=launch.interpreter),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=int(process_options.get("creationflags", 0)),
                start_new_session=bool(process_options.get("start_new_session", False)),
                cwd=launch.working_directory or (tree.root if tree is not None else None),
                env=environment,
            )
        except BaseException:
            if tree is not None:
                tree.close()
            raise
        try:
            owned_process = OwnedProcessTree(process)
        except BaseException:
            process.kill()
            process.wait(timeout=5)
            if tree is not None:
                tree.close()
            raise
        with self._lock:
            self._process = process
            self._owned_process = owned_process
            self._tree = tree
            self._launch = launch
            self.state = DebugState.STARTING
            self._received_state = DebugState.STARTING
            self._terminal_received = threading.Event()
            self._stderr_drained = threading.Event()
            self.history.clear()
            self._stderr.clear()
            self._stderr_length = 0
            self.forced_termination = False
            self._events = queue.Queue(maxsize=self.event_capacity)
            self._delivery_stopped = threading.Event()
            self._runtime.reset()
            self._local_pairs.clear()
            self._runtime_trace.clear()
        threading.Thread(
            target=self._read_events,
            args=(
                process,
                tree,
                owned_process,
                self._stderr_drained,
                self._events,
                self._delivery_stopped,
            ),
            daemon=True,
        ).start()
        threading.Thread(
            target=self._read_stderr, args=(process, self._stderr_drained), daemon=True
        ).start()
        threading.Thread(
            target=self._watch_exit, args=(process, owned_process), daemon=True
        ).start()
        symbols = (
            invocation_symbols(
                launch.invocation,
                allocator=PythonSymbolAllocator(python_identifiers(launch.source or "")),
            )
            if launch.invocation is not None
            else None
        )
        self._send(
            {
                "source": launch.source,
                "project": (
                    {"root": str(tree.root), "launcher": str(tree.launcher), "files": tree.files}
                    if tree is not None
                    else None
                ),
                "invocation_source": (
                    render_invocation(
                        launch.invocation,
                        result_policy=InvocationResultPolicy.CAPTURE,
                        symbols=symbols,
                    )
                    if launch.invocation is not None
                    else None
                ),
                "invocation_result_name": (
                    symbols.result if symbols is not None else INVOCATION_RESULT_NAME
                ),
                "breakpoints": self._breakpoint_data(launch.breakpoints),
                "pause_on_exception": launch.pause_on_exception,
                "max_history": launch.max_history,
                "execution_session_id": launch.execution_session_id,
                "project_revision": launch.project_revision,
                "artifact_revision": launch.artifact_revision,
                "binding_specs": [
                    {
                        "function": item.function,
                        "name": item.name,
                        "semantic_symbol_id": item.semantic_symbol_id,
                        "module": item.module,
                        "qualname": item.qualname,
                    }
                    for item in launch.binding_specs
                ],
                "record": launch.record,
                "computation": computation,
            }
        )

    def restart(self) -> None:
        if self._launch is None:
            raise RuntimeError("No debugger launch is available to restart")
        self.start(self._launch)

    def continue_execution(self) -> None:
        self._command("continue")

    def step_into(self) -> None:
        self._command("step_into")

    def step_over(self) -> None:
        self._command("step_over")

    def step_out(self) -> None:
        self._command("step_out")

    def set_breakpoints(self, lines: tuple[int | SourceLocation, ...]) -> None:
        self._send({"command": "set_breakpoints", "lines": self._breakpoint_data(lines)})

    def _breakpoint_data(self, positions: tuple[int | SourceLocation, ...]) -> list[object]:
        project_mode = self._launch is not None and self._launch.project is not None
        result: list[object] = []
        for position in positions:
            if isinstance(position, SourceLocation):
                if (
                    project_mode
                    and self._launch is not None
                    and self._launch.project is not None
                    and position.file_path not in {item.path for item in self._launch.project.files}
                ):
                    raise ValueError("A project breakpoint must name an emitted file")
                result.append({"file_path": position.file_path, "line": position.line})
            elif not project_mode and type(position) is int and position > 0:
                result.append(position)
            else:
                raise ValueError("Project breakpoints require file-qualified source locations")
        return result

    def send_stdin(self, text: str) -> None:
        self._send({"command": "stdin", "text": text})

    def _command(self, command: str) -> None:
        if self.state is not DebugState.PAUSED:
            raise RuntimeError(f"Cannot {command.replace('_', ' ')} while debugger is {self.state}")
        self.state = DebugState.RUNNING
        self._received_state = DebugState.RUNNING
        self._send({"command": command})

    def poll_events(self, *, maximum: int = 100) -> tuple[DebugEvent, ...]:
        result: list[DebugEvent] = []
        for _ in range(maximum):
            try:
                result.append(self._deliver(self._events.get_nowait()))
            except queue.Empty:
                break
        return tuple(result)

    def wait_event(self, timeout: float = 5.0) -> DebugEvent:
        try:
            return self._deliver(self._events.get(timeout=timeout))
        except queue.Empty as exc:
            raise TimeoutError("Timed out waiting for debugger event") from exc

    def _deliver(self, event: DebugEvent) -> DebugEvent:
        # The consumer observes state in the same order as output and pauses.
        # A reader-thread FINISHED state must not stop a GUI's queue-drain timer.
        with self._lock:
            self.state = _state_for_event(event.event, self.state)
        return event

    def wait_for(self, event: str, timeout: float = 5.0) -> DebugEvent:
        deadline = monotonic() + timeout
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Timed out waiting for debugger event {event!r}")
            value = self.wait_event(remaining)
            if value.event == event:
                return value

    def stop(self) -> None:
        with self._lock:
            self._delivery_stopped.set()
            process = self._process
            tree = self._tree
            owned_process = self._owned_process
        if process is None:
            if owned_process is not None:
                owned_process.close()
            if tree is not None:
                tree.close()
            if self.state not in {DebugState.FINISHED, DebugState.FAILED}:
                self.state = DebugState.STOPPED
            return
        if process.poll() is None:
            try:
                if not self._terminal_received.is_set():
                    self._send({"command": "stop"})
                process.wait(timeout=1.0 if self._terminal_received.is_set() else 0.35)
            except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                if process.poll() is None:
                    self.forced_termination = True
                    if owned_process is not None:
                        owned_process.terminate()
                    else:
                        process.kill()
                        process.wait(timeout=1.0)
        if owned_process is not None:
            owned_process.close()
        with self._lock:
            self._process = None
            self._owned_process = None
            self._tree = None
            if self.state not in {DebugState.FINISHED, DebugState.FAILED}:
                self.state = DebugState.STOPPED
        if tree is not None:
            tree.close()

    def _send(self, payload: dict[str, object]) -> None:
        with self._lock:
            process = self._process
            if process is None or process.stdin is None or process.poll() is not None:
                raise RuntimeError("Debugger process is not running")
            process.stdin.write(json.dumps(payload, ensure_ascii=True) + "\n")
            process.stdin.flush()

    @staticmethod
    def _watch_exit(process: subprocess.Popen[str], owned_process: OwnedProcessTree) -> None:
        process.wait()
        owned_process.close()

    def _read_events(
        self,
        process: subprocess.Popen[str],
        tree: MaterializedProject | None,
        owned_process: OwnedProcessTree,
        stderr_drained: threading.Event,
        events: queue.Queue[DebugEvent],
        delivery_stopped: threading.Event,
    ) -> None:
        assert process.stdout is not None
        terminal: DebugEvent | None = None
        last_sequence = -1
        while line := process.stdout.readline(MAX_PORTABLE_ENVELOPE_BYTES + 1):
            if len(line.encode("utf-8")) > MAX_PORTABLE_ENVELOPE_BYTES:
                launch = self._launch
                terminal = DebugEvent(
                    last_sequence + 1,
                    "failed",
                    DebugState.FAILED,
                    reason="protocol_limit",
                    detail=(
                        "Debugger event exceeds the portable envelope; "
                        "use bounded previews or resources"
                    ),
                    return_code=-1,
                    execution_session_id=launch.execution_session_id if launch is not None else "",
                    project_revision=launch.project_revision if launch is not None else 0,
                    artifact_revision=launch.artifact_revision if launch is not None else 0,
                )
                self._terminal_received.set()
                self.forced_termination = process.poll() is None
                owned_process.terminate()
                break
            try:
                raw: object = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(raw, dict) and raw.get("event") == "computation":
                launch = self._launch
                try:
                    if launch is None or launch.computation is None:
                        raise ValueError("COMPUTATION_CONTEXT_REQUIRED: no publication context")
                    response = launch.computation.accept(raw.get("message"))
                except Exception as exc:
                    response = {"error": str(exc)[:4096]}
                self._send({"command": "computation_ack", "response": response})
                continue
            with self._lock:
                if self._process is not process:
                    continue
                event = _decode_event(raw, self._received_state, self._runtime, self._local_pairs)
                if event is None:
                    continue
                last_sequence = max(last_sequence, event.sequence)
                self._received_state = event.state
                if event.event in {"finished", "failed", "stopped"}:
                    terminal = event
                    self._terminal_received.set()
                    continue
                if event.event in {"paused", "trace"}:
                    if event.runtime_delta is not None:
                        self._runtime_trace.append(event.runtime_delta)
                    self.history.append(replace(event, runtime_graph=None))
            if not self._queue_event(event, events, delivery_stopped):
                break
        process.wait()
        owned_process.close()
        stderr_drained.wait()
        if tree is not None:
            tree.close()
        with self._lock:
            if self._process is process:
                self._process = None
                self._tree = None
            else:
                terminal = None
        if terminal is not None:
            # Native fd writes use a separate bounded pipe, never protocol text.
            # Preserve them as output even when the child completed successfully.
            native_output = "".join(self._stderr)
            if native_output:
                last_sequence += 1
                self._queue_event(
                    replace(
                        terminal,
                        sequence=last_sequence,
                        event="output",
                        channel="stderr",
                        text=native_output,
                        traceback="",
                        result="",
                    ),
                    events,
                    delivery_stopped,
                )
            if terminal.sequence < last_sequence:
                terminal = replace(terminal, sequence=last_sequence + 1)
            self._queue_event(terminal, events, delivery_stopped)

    @staticmethod
    def _queue_event(
        event: DebugEvent, events: queue.Queue[DebugEvent], stopped: threading.Event
    ) -> bool:
        # Backpressure never owns the command lock. Stop can always reach the
        # worker and release a reader whose consumer has gone away.
        while not stopped.is_set():
            try:
                events.put(event, timeout=0.05)
                return True
            except queue.Full:
                pass
        return False

    def _read_stderr(self, process: subprocess.Popen[str], drained: threading.Event) -> None:
        assert process.stderr is not None
        try:
            while chunk := process.stderr.read(8192):
                with self._lock:
                    if self._process is process:
                        remaining = 65536 - self._stderr_length
                        if remaining > 0:
                            self._stderr.append(chunk[:remaining])
                            self._stderr_length += min(len(chunk), remaining)
        finally:
            drained.set()

    def __enter__(self) -> DebugSession:
        return self

    def __exit__(self, *_args: object) -> None:
        self.stop()
