"""Isolated JSON-lines worker for emitted projects and explicit source snapshots.

This worker and its sibling project bootstrap use only the standard library, so they
can start in Python's isolated mode. Protocol messages use the original stdio streams;
the debuggee receives bounded proxy streams instead.
"""

from __future__ import annotations

import builtins
import hashlib
import importlib
import json
import math
import os
import sys
import threading
import traceback
from pathlib import Path
from types import FrameType
from typing import Any, TextIO, cast

_FILENAME = "<code-visualizer-debug>"
_REPR_LIMIT = 480
_VALUE_PREVIEW_LIMIT = 240
_VALUE_MAX_DEPTH = 5
_VALUE_MAX_CHILDREN = 64
_VALUE_MAX_NODES = 1_000
_CHECKPOINT_INTERVAL = 20


def _breakpoints(raw: object, files: set[str], *, source_mode: bool) -> set[tuple[str, int]]:
    if not isinstance(raw, list):
        raise ValueError("Breakpoints must be an array")
    result = set()
    for item in raw:
        if source_mode and type(item) is int and item > 0:
            result.add((_FILENAME, item))
        elif isinstance(item, dict):
            path, line = item.get("file_path"), item.get("line")
            if not isinstance(path, str) or path not in files or type(line) is not int or line < 1:
                raise ValueError("Breakpoint must name an emitted file and positive line")
            result.add((path, line))
        else:
            raise ValueError("Project breakpoints require file-qualified positions")
    return result


def _breakpoint_data(values: set[tuple[str, int]]) -> list[dict[str, object]]:
    return [{"file_path": path, "line": line} for path, line in sorted(values)]


class _DebuggerStop(BaseException):
    """Escape user code even when it catches ordinary Exception values."""


class _Protocol:
    def __init__(self) -> None:
        self.sequence = 0
        output = sys.__stdout__
        input_stream = sys.__stdin__
        if output is None or input_stream is None:
            raise RuntimeError("Debugger protocol requires standard input and output")
        self._output: TextIO = os.fdopen(
            os.dup(output.fileno()), "w", encoding="utf-8", buffering=1
        )
        self._input: TextIO = os.fdopen(os.dup(input_stream.fileno()), "r", encoding="utf-8")
        # Native libraries may use os.write/printf instead of Python's proxies.
        # They receive stderr, never the private protocol descriptor.
        os.dup2(2, 1)
        with open(os.devnull, "rb") as empty_input:
            os.dup2(empty_input.fileno(), 0)
        self._send_lock = threading.Lock()
        self._metadata: dict[str, object] = {}

    def set_metadata(
        self,
        *,
        execution_session_id: str,
        project_revision: int,
        artifact_revision: int,
    ) -> None:
        self._metadata = {
            "execution_session_id": execution_session_id,
            "project_revision": project_revision,
            "artifact_revision": artifact_revision,
        }

    def send(self, event: str, **payload: object) -> None:
        with self._send_lock:
            self._send(event, **payload)

    def _send(self, event: str, **payload: object) -> None:
        message = {
            "event": event,
            "sequence": self.sequence,
            **self._metadata,
            **payload,
        }
        self.sequence += 1
        # The private pipe must not depend on the child interpreter's locale.
        # JSON escapes preserve all Unicode values, including runtime previews.
        self._output.write(json.dumps(message, ensure_ascii=True, sort_keys=True) + "\n")
        self._output.flush()

    def receive(self) -> dict[str, object]:
        line = self._input.readline()
        if not line:
            raise _DebuggerStop
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError("Debugger command must be a JSON object")
        return value


class _OutputProxy:
    def __init__(self, protocol: _Protocol, channel: str) -> None:
        self._protocol = protocol
        self._channel = channel

    def write(self, value: str) -> int:
        # One authored write can contain an arbitrarily large string. Keep the
        # private control lane bounded without altering the observable text.
        for start in range(0, len(value), 8192):
            self._protocol.send("output", channel=self._channel, text=value[start : start + 8192])
        return len(value)

    def flush(self) -> None:
        return

    def isatty(self) -> bool:
        return False


class _InputProxy:
    def __init__(self, protocol: _Protocol) -> None:
        self._protocol = protocol

    def readline(self, _size: int = -1) -> str:
        self._protocol.send("input_requested")
        while True:
            message = self._protocol.receive()
            command = message.get("command")
            if command == "stdin":
                value = str(message.get("text", ""))
                return value if value.endswith("\n") else value + "\n"
            if command == "stop":
                raise _DebuggerStop

    def isatty(self) -> bool:
        return False


def _short(value: object) -> str:
    try:
        text = repr(value)
    except Exception:
        text = "<unrepresentable>"
    if len(text) <= _REPR_LIMIT:
        return text
    return text[: _REPR_LIMIT - 1] + "…"


def _type_id(value: object) -> str:
    value_type = type(value)
    return f"{value_type.__module__}.{value_type.__qualname__}"


def _safe_preview(value: object) -> str:
    """Avoid invoking application-defined ``__repr__`` while paused."""

    value_type = type(value)
    if value is None or value_type in {bool, int, float, complex, str, bytes}:
        return _short(value)
    if value_type is list:
        return f"list({len(cast(list[object], value))})"
    if value_type is tuple:
        return f"tuple({len(cast(tuple[object, ...], value))})"
    if value_type is dict:
        return f"dict({len(cast(dict[object, object], value))})"
    if value_type is set:
        return f"set({len(cast(set[object], value))})"
    if value_type is frozenset:
        return f"frozenset({len(cast(frozenset[object], value))})"
    return f"<{_type_id(value)}>"


class _RuntimeGraphEncoder:
    """Encode checkpoint/delta graphs with stable object identities and hard bounds."""

    def __init__(self) -> None:
        self._identity_ids: dict[int, tuple[type[object], str]] = {}
        self._next_identity = 1
        self._previous_values: dict[str, dict[str, object]] = {}
        self._current_values: dict[str, dict[str, object]] = {}
        self._active_object_ids: set[int] = set()
        self._truncated = False

    def capture(
        self,
        values: dict[str, object],
        *,
        frame_id: str,
        history_index: int,
        changed_names: tuple[str, ...],
        semantic_symbol_ids: dict[str, str],
    ) -> dict[str, object]:
        self._current_values = {}
        self._active_object_ids = set()
        self._truncated = False
        changed = frozenset(changed_names)
        bindings = [
            {
                "name": name,
                "value_id": self._encode(value, 0),
                "changed": name in changed,
                "semantic_symbol_id": semantic_symbol_ids.get(name),
                "frame_id": frame_id,
            }
            for name, value in sorted(values.items())
            if not name.startswith("__")
        ]
        checkpoint = history_index == 0 or history_index % _CHECKPOINT_INTERVAL == 0
        if checkpoint:
            emitted_values = list(self._current_values.values())
            removed: list[str] = []
        else:
            emitted_values = [
                value
                for value_id, value in self._current_values.items()
                if self._previous_values.get(value_id) != value
            ]
            removed = sorted(self._previous_values.keys() - self._current_values.keys())
        self._previous_values = dict(self._current_values)
        self._identity_ids = {
            key: value
            for key, value in self._identity_ids.items()
            if key in self._active_object_ids
        }
        return {
            "kind": "checkpoint" if checkpoint else "delta",
            "frame_id": frame_id,
            "history_index": history_index,
            "bindings": bindings,
            "values": emitted_values,
            "removed_value_ids": removed,
            "truncated": self._truncated,
            "limits": {
                "max_children": _VALUE_MAX_CHILDREN,
                "max_depth": _VALUE_MAX_DEPTH,
                "max_nodes": _VALUE_MAX_NODES,
                "preview_characters": _VALUE_PREVIEW_LIMIT,
            },
        }

    def _encode(self, value: object, depth: int) -> str:
        if value is None or type(value) in {bool, int, float, str}:
            return self._encode_scalar(value)
        identity_key = id(value)
        self._active_object_ids.add(identity_key)
        identity = self._identity_ids.get(identity_key)
        if identity is None or identity[0] is not type(value):
            value_id = f"runtime_object_{self._next_identity}"
            self._next_identity += 1
            self._identity_ids[identity_key] = (type(value), value_id)
        else:
            value_id = identity[1]
        if value_id in self._current_values:
            return value_id
        if len(self._current_values) >= _VALUE_MAX_NODES:
            self._truncated = True
            return self._limit_node()
        kind, entries = self._entries(value)
        node: dict[str, object] = {
            "value_id": value_id,
            "type_id": _type_id(value),
            "kind": kind,
            "preview": _safe_preview(value)[:_VALUE_PREVIEW_LIMIT],
            "children": [],
            "truncated": False,
        }
        # Insert the placeholder before descending so cycles become references.
        self._current_values[value_id] = node
        if depth >= _VALUE_MAX_DEPTH:
            node["truncated"] = True
            self._truncated = True
            return value_id
        children: list[dict[str, object]] = []
        for index, (label, key, child) in enumerate(entries):
            if index >= _VALUE_MAX_CHILDREN:
                node["truncated"] = True
                self._truncated = True
                break
            child_data: dict[str, object] = {
                "label": label[:_VALUE_PREVIEW_LIMIT],
                "value_id": self._encode(child, depth + 1),
            }
            if key is not None:
                child_data["key_id"] = self._encode(key, depth + 1)
            children.append(child_data)
        node["children"] = children
        return value_id

    def _encode_scalar(self, value: object) -> str:
        if isinstance(value, float) and not math.isfinite(value):
            scalar: object = None
        elif isinstance(value, str) and len(value) > _VALUE_PREVIEW_LIMIT:
            scalar = value[:_VALUE_PREVIEW_LIMIT]
        else:
            scalar = value
        digest = hashlib.sha256(
            f"{_type_id(value)}\0{value!r}".encode("utf-8", errors="replace")
        ).hexdigest()[:20]
        value_id = f"runtime_scalar_{digest}"
        self._current_values.setdefault(
            value_id,
            {
                "value_id": value_id,
                "type_id": _type_id(value),
                "kind": "scalar",
                "preview": _safe_preview(value)[:_VALUE_PREVIEW_LIMIT],
                "scalar_value": scalar,
                "children": [],
                "truncated": isinstance(value, str) and len(value) > _VALUE_PREVIEW_LIMIT,
            },
        )
        return value_id

    def _limit_node(self) -> str:
        value_id = "runtime_truncated"
        self._current_values.setdefault(
            value_id,
            {
                "value_id": value_id,
                "type_id": "runtime.truncated",
                "kind": "truncated",
                "preview": "Additional runtime values were omitted",
                "children": [],
                "truncated": True,
            },
        )
        return value_id

    @staticmethod
    def _entries(value: object) -> tuple[str, list[tuple[str, object | None, object]]]:
        value_type = type(value)
        if value_type is dict:
            mapping = cast(dict[object, object], value)
            return (
                "mapping",
                [
                    (_safe_preview(key), key, child)
                    for key, child in list(mapping.items())[: _VALUE_MAX_CHILDREN + 1]
                ],
            )
        if value_type is list:
            sequence = cast(list[object], value)
            return (
                "sequence",
                [(f"[{index}]", None, child) for index, child in enumerate(sequence)],
            )
        if value_type is tuple:
            sequence_tuple = cast(tuple[object, ...], value)
            return (
                "sequence",
                [(f"[{index}]", None, child) for index, child in enumerate(sequence_tuple)],
            )
        if value_type is set:
            ordered = sorted(cast(set[object], value), key=_safe_preview)
            return (
                "set",
                [(f"[{index}]", None, child) for index, child in enumerate(ordered)],
            )
        if value_type is frozenset:
            frozen_ordered = sorted(cast(frozenset[object], value), key=_safe_preview)
            return (
                "set",
                [(f"[{index}]", None, child) for index, child in enumerate(frozen_ordered)],
            )
        try:
            attributes = object.__getattribute__(value, "__dict__")
        except (AttributeError, TypeError):
            attributes = None
        if type(attributes) is dict:
            attribute_map = cast(dict[object, object], attributes)
            return (
                "object",
                [
                    (str(name), None, child)
                    for name, child in sorted(attribute_map.items(), key=lambda item: str(item[0]))
                    if not str(name).startswith("__")
                ],
            )
        return "opaque", []


class _Tracer:
    def __init__(
        self,
        protocol: _Protocol,
        breakpoints: set[tuple[str, int]],
        *,
        pause_on_exception: bool,
        max_history: int,
        binding_specs: dict[tuple[str, str, str | None, str | None], str],
        record: bool,
        files: dict[str, str],
        source_mode: bool,
    ) -> None:
        self.protocol = protocol
        self.breakpoints = breakpoints
        self.pause_on_exception = pause_on_exception
        self.max_history = max_history
        self.mode = "continue" if not source_mode and breakpoints else "step_into"
        self.target_depth: int | None = None
        self.pause_count = 0
        self._previous_locals: dict[tuple[str, int], dict[str, str]] = {}
        self._runtime_encoder = _RuntimeGraphEncoder()
        self._frame_ids: dict[int, str] = {}
        self._next_frame_id = 1
        self._binding_specs = binding_specs
        self.record = record
        self.files = files
        self.source_mode = source_mode
        self._file_cache: dict[str, str | None] = {}
        self.history_truncated = False

    def _frame_id(self, frame: FrameType) -> str:
        key = id(frame)
        value = self._frame_ids.get(key)
        if value is None:
            value = f"runtime_frame_{self._next_frame_id}"
            self._next_frame_id += 1
            self._frame_ids[key] = value
        return value

    def _file_path(self, frame: FrameType) -> str | None:
        filename = frame.f_code.co_filename
        if filename not in self._file_cache:
            self._file_cache[filename] = self.files.get(
                filename if self.source_mode else os.path.normcase(os.path.abspath(filename))
            )
        return self._file_cache[filename]

    def _depth(self, frame: FrameType) -> int:
        depth = 0
        current: FrameType | None = frame
        while current is not None:
            if self._file_path(current) is not None:
                depth += 1
            current = current.f_back
        return depth

    @staticmethod
    def _visible_locals(frame: FrameType) -> dict[str, str]:
        return {
            name: _short(value)
            for name, value in sorted(frame.f_locals.items())
            if not name.startswith("__")
        }

    def _stack(self, frame: FrameType) -> list[dict[str, object]]:
        frames: list[dict[str, object]] = []
        current: FrameType | None = frame
        while current is not None:
            if self._file_path(current) is not None:
                frames.append(
                    {
                        "frame_id": self._frame_id(current),
                        "function": current.f_code.co_name,
                        "line": current.f_lineno,
                        "file_path": self._file_path(current),
                    }
                )
            current = current.f_back
        return frames

    def _should_pause(self, frame: FrameType, event: str) -> tuple[bool, str]:
        if event == "exception" and self.pause_on_exception:
            return True, "exception"
        if event != "line":
            return False, ""
        if (self._file_path(frame), frame.f_lineno) in self.breakpoints:
            return True, "breakpoint"
        depth = self._depth(frame)
        if self.mode == "step_into":
            return True, "step"
        if self.mode == "step_over" and self.target_depth is not None:
            return depth <= self.target_depth, "step"
        if self.mode == "step_out" and self.target_depth is not None:
            return depth <= self.target_depth, "step"
        return False, ""

    def _pause(self, frame: FrameType, reason: str, detail: str = "") -> None:
        key = (self._frame_id(frame), self._depth(frame))
        local_values = self._visible_locals(frame)
        previous = self._previous_locals.get(key, {})
        changed = tuple(
            name
            for name, value in local_values.items()
            if name not in previous or previous[name] != value
        )
        removed = tuple(name for name in previous if name not in local_values)
        self._previous_locals[key] = local_values
        self.pause_count += 1
        frame_id = self._frame_id(frame)
        runtime_snapshot = self._runtime_encoder.capture(
            frame.f_locals,
            frame_id=frame_id,
            history_index=self.pause_count - 1,
            changed_names=changed,
            semantic_symbol_ids={
                name: semantic_id
                for (function, name, module, qualname), semantic_id in self._binding_specs.items()
                if function == frame.f_code.co_name
                and (module is None or module == frame.f_globals.get("__name__"))
                and (qualname is None or qualname == frame.f_code.co_qualname)
            },
        )
        self.protocol.send(
            "paused",
            reason=reason,
            detail=detail,
            line=frame.f_lineno,
            file_path=self._file_path(frame),
            function=frame.f_code.co_name,
            locals=local_values,
            changed_locals=changed,
            removed_locals=removed,
            stack=self._stack(frame),
            history_index=self.pause_count - 1,
            history_truncated=self.pause_count > self.max_history,
            runtime_snapshot=runtime_snapshot,
        )
        while True:
            message = self.protocol.receive()
            command = message.get("command")
            if command == "set_breakpoints":
                self.breakpoints = _breakpoints(
                    message.get("lines", []), set(self.files.values()), source_mode=self.source_mode
                )
                self.protocol.send("breakpoints", lines=_breakpoint_data(self.breakpoints))
                continue
            if command == "continue":
                self.mode = "continue"
                self.target_depth = None
                return
            if command == "step_into":
                self.mode = "step_into"
                self.target_depth = None
                return
            if command == "step_over":
                self.mode = "step_over"
                self.target_depth = self._depth(frame)
                return
            if command == "step_out":
                self.mode = "step_out"
                self.target_depth = max(0, self._depth(frame) - 1)
                return
            if command == "stop":
                raise _DebuggerStop

    def _record(self, frame: FrameType, trace_event: str, argument: object) -> None:
        if self.pause_count >= self.max_history:
            self.history_truncated = True
            return
        key = (self._frame_id(frame), self._depth(frame))
        local_values = self._visible_locals(frame)
        previous = self._previous_locals.get(key, {})
        changed = tuple(
            name
            for name, value in local_values.items()
            if name not in previous or previous[name] != value
        )
        removed = tuple(name for name in previous if name not in local_values)
        self._previous_locals[key] = local_values
        frame_id = self._frame_id(frame)
        detail = ""
        if trace_event == "return":
            detail = _short(argument)
        elif trace_event == "exception" and isinstance(argument, tuple) and len(argument) > 1:
            detail = _short(argument[1])
        runtime_snapshot = self._runtime_encoder.capture(
            frame.f_locals,
            frame_id=frame_id,
            history_index=self.pause_count,
            changed_names=changed,
            semantic_symbol_ids={
                name: semantic_id
                for (function, name, module, qualname), semantic_id in self._binding_specs.items()
                if function == frame.f_code.co_name
                and (module is None or module == frame.f_globals.get("__name__"))
                and (qualname is None or qualname == frame.f_code.co_qualname)
            },
        )
        self.protocol.send(
            "trace",
            trace_event=trace_event,
            detail=detail,
            line=frame.f_lineno,
            file_path=self._file_path(frame),
            function=frame.f_code.co_name,
            locals=local_values,
            changed_locals=changed,
            removed_locals=removed,
            stack=self._stack(frame),
            history_index=self.pause_count,
            history_truncated=False,
            runtime_snapshot=runtime_snapshot,
        )
        self.pause_count += 1

    def trace(self, frame: FrameType, event: str, argument: object) -> Any:
        if self._file_path(frame) is None:
            return None
        if self.record:
            if event in {"call", "line", "return", "exception"}:
                self._record(frame, event, argument)
            return self.trace
        should_pause, reason = self._should_pause(frame, event)
        if should_pause:
            detail = ""
            if event == "exception" and isinstance(argument, tuple) and len(argument) > 1:
                detail = _short(argument[1])
            self._pause(frame, reason, detail)
        return self.trace


def _invoke(scope: dict[str, object], source: str, result_name: str) -> object:
    """Execute the parent's shared invocation rendering outside mapped user-source lines."""

    exec(compile(source, "<code-visualizer-invocation>", "exec"), scope, scope)
    return scope[result_name]


def main() -> int:
    protocol = _Protocol()
    try:
        configuration = protocol.receive()
        source = configuration.get("source")
        project = configuration.get("project")
        source_mode = project is None
        invocation_source = configuration.get("invocation_source")
        invocation_result_name = configuration.get("invocation_result_name")
        raw_breakpoints = configuration.get("breakpoints", [])
        execution_session_id = configuration.get("execution_session_id", "")
        project_revision = configuration.get("project_revision", 0)
        artifact_revision = configuration.get("artifact_revision", project_revision)
        if (
            "invocation_source" not in configuration
            or (source_mode and not isinstance(source, str))
            or (not source_mode and (source is not None or invocation_source is not None))
            or (invocation_source is not None and not isinstance(invocation_source, str))
        ):
            raise ValueError("Source must be text and invocation must be text or absent")
        if (
            not isinstance(invocation_result_name, str)
            or not invocation_result_name.isidentifier()
            or not isinstance(raw_breakpoints, list)
        ):
            raise ValueError("Invocation result name and breakpoints are invalid")
        if (
            not isinstance(execution_session_id, str)
            or not execution_session_id
            or isinstance(project_revision, bool)
            or not isinstance(project_revision, int)
            or isinstance(artifact_revision, bool)
            or not isinstance(artifact_revision, int)
        ):
            raise ValueError("execution identity and revisions are invalid")
        protocol.set_metadata(
            execution_session_id=execution_session_id,
            project_revision=project_revision,
            artifact_revision=artifact_revision,
        )
        files = {_FILENAME: _FILENAME}
        launcher = None
        if not source_mode:
            if not isinstance(project, dict) or not isinstance(project.get("files"), dict):
                raise ValueError("A project launch requires materialized files")
            root = Path(project["root"]).resolve()
            launcher = Path(project["launcher"]).resolve()
            files = {}
            for absolute, relative in project["files"].items():
                path = Path(absolute).resolve()
                if (
                    not path.is_relative_to(root)
                    or not path.is_file()
                    or path.relative_to(root).as_posix() != relative
                ):
                    raise ValueError("Project file mapping must stay within its emitted root")
                files[os.path.normcase(str(path))] = relative
            if os.path.normcase(str(launcher)) not in files:
                raise ValueError("Project launcher must be an emitted file")
        breakpoints = _breakpoints(raw_breakpoints, set(files.values()), source_mode=source_mode)
        pause_on_exception = bool(configuration.get("pause_on_exception", True))
        raw_history = configuration.get("max_history", 500)
        max_history = raw_history if isinstance(raw_history, int) else 500
        record = bool(configuration.get("record", False))
        raw_binding_specs = configuration.get("binding_specs", [])
        if not isinstance(raw_binding_specs, list):
            raise ValueError("binding_specs must be an array")
        binding_specs: dict[tuple[str, str, str | None, str | None], str] = {}
        for raw_spec in raw_binding_specs:
            if not isinstance(raw_spec, dict):
                continue
            function = raw_spec.get("function")
            name = raw_spec.get("name")
            semantic_symbol_id = raw_spec.get("semantic_symbol_id")
            module = raw_spec.get("module")
            qualname = raw_spec.get("qualname")
            if (
                isinstance(function, str)
                and isinstance(name, str)
                and isinstance(semantic_symbol_id, str)
                and (module is None or isinstance(module, str))
                and (qualname is None or isinstance(qualname, str))
            ):
                binding_specs[(function, name, module, qualname)] = semantic_symbol_id
        scope: dict[str, object] = {"__name__": "code_visualizer_live"}
        tracer = _Tracer(
            protocol,
            breakpoints,
            pause_on_exception=pause_on_exception,
            max_history=max(1, max_history),
            binding_specs=binding_specs,
            record=record,
            files=files,
            source_mode=source_mode,
        )
        sys.stdout = _OutputProxy(protocol, "stdout")
        sys.stderr = _OutputProxy(protocol, "stderr")
        sys.stdin = _InputProxy(protocol)
        original_input = builtins.input

        def debug_input(prompt: object = "") -> str:
            if prompt:
                print(prompt, end="")
            return sys.stdin.readline().rstrip("\n")

        builtins.input = debug_input
        try:
            computation = configuration.get("computation")
            if computation is not None:
                if not isinstance(computation, dict) or not isinstance(
                    computation.get("sdk_root"), str
                ):
                    raise ValueError("Invalid installed computation adapter")
                sys.path.insert(0, computation["sdk_root"])
                from code_visualizer.execution.python_api import _install

                def exchange(message: dict[str, Any]) -> dict[str, Any]:
                    protocol.send("computation", message=message)
                    while True:
                        response = protocol.receive()
                        if response.get("command") == "stop":
                            raise _DebuggerStop
                        if response.get("command") == "computation_ack":
                            return cast(dict[str, Any], response["response"])

                _install(computation, exchange)
            # Projects trace their real module initialization and launcher. Explicit
            # source invocations retain their separate initialization boundary.
            if launcher is not None:
                if __package__:
                    from ._project_imports import execute_project
                else:
                    sys.path.insert(0, str(Path(__file__).parent))
                    try:
                        execute_project = importlib.import_module(
                            "_project_imports"
                        ).execute_project
                    finally:
                        sys.path.pop(0)
                protocol.send("started", breakpoints=_breakpoint_data(breakpoints))
                execute_project(root, launcher, trace=tracer.trace)
                result = None
            elif invocation_source is None:
                assert isinstance(source, str)
                protocol.send("started", breakpoints=_breakpoint_data(breakpoints))
                sys.settrace(tracer.trace)
                exec(compile(source, _FILENAME, "exec"), scope, scope)
                result = None
            else:
                assert isinstance(source, str)
                exec(compile(source, _FILENAME, "exec"), scope, scope)
                protocol.send("started", breakpoints=_breakpoint_data(breakpoints))
                sys.settrace(tracer.trace)
                result = _invoke(scope, invocation_source, invocation_result_name)
        finally:
            sys.settrace(None)
            builtins.input = original_input
        protocol.send(
            "finished",
            return_code=0,
            result=_short(result),
            history_truncated=tracer.history_truncated,
        )
        return 0
    except _DebuggerStop:
        sys.settrace(None)
        protocol.send("stopped", return_code=-1)
        return 0
    except BaseException as exc:
        sys.settrace(None)
        protocol.send(
            "failed",
            return_code=1,
            exception_type=type(exc).__name__,
            detail=str(exc),
            traceback="".join(traceback.format_exception(exc)),
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
