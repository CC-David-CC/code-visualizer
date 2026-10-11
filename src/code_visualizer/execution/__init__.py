"""Public execution exports, loaded only when the requested capability is used."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from code_visualizer.execution.debugger import (
        DebugEvent,
        DebugFrame,
        DebugLaunch,
        DebugSession,
        DebugState,
    )
    from code_visualizer.execution.runner import (
        RunResult,
        RunSession,
        TraceEvent,
        TraceResult,
        run_generated,
        run_project,
        run_source,
        trace_project,
        trace_source,
    )
    from code_visualizer.execution.runtime import (
        RuntimeBinding,
        RuntimeBindingSpec,
        RuntimeChild,
        RuntimeGraph,
        RuntimeGraphDelta,
        RuntimeTraceStore,
        RuntimeValue,
        RuntimeValueKind,
        SourceLocation,
    )

__all__ = [
    "DebugEvent",
    "DebugFrame",
    "DebugLaunch",
    "DebugSession",
    "DebugState",
    "RunResult",
    "RunSession",
    "RuntimeBinding",
    "RuntimeBindingSpec",
    "RuntimeChild",
    "RuntimeGraph",
    "RuntimeGraphDelta",
    "RuntimeTraceStore",
    "RuntimeValue",
    "RuntimeValueKind",
    "SourceLocation",
    "TraceEvent",
    "TraceResult",
    "run_generated",
    "run_project",
    "run_source",
    "trace_project",
    "trace_source",
]

_EXPORTS = {
    **dict.fromkeys(
        ("DebugEvent", "DebugFrame", "DebugLaunch", "DebugSession", "DebugState"),
        "code_visualizer.execution.debugger",
    ),
    **dict.fromkeys(
        (
            "RunResult",
            "RunSession",
            "TraceEvent",
            "TraceResult",
            "run_generated",
            "run_project",
            "run_source",
            "trace_project",
            "trace_source",
        ),
        "code_visualizer.execution.runner",
    ),
    **dict.fromkeys(
        (
            "RuntimeBinding",
            "RuntimeBindingSpec",
            "RuntimeChild",
            "RuntimeGraph",
            "RuntimeGraphDelta",
            "RuntimeTraceStore",
            "RuntimeValue",
            "RuntimeValueKind",
            "SourceLocation",
        ),
        "code_visualizer.execution.runtime",
    ),
}


def __getattr__(name: str) -> object:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value: object = getattr(import_module(module), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
