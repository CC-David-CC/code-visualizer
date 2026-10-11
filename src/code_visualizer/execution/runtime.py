"""Revision-pinned, identity-preserving runtime value graph contracts."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from unicodedata import normalize

from code_visualizer.domain.common import JsonScalar
from code_visualizer.domain.module_paths import qualified_module_name
from code_visualizer.domain.program import ProgramModel, ProgramSymbolKind
from code_visualizer.domain.program_bindings import mangle_python_identifier
from code_visualizer.domain.program_index import program_function_locations


@dataclass(frozen=True, slots=True, order=True)
class SourceLocation:
    """A stable position in an emitted file, independent of its temporary root."""

    file_path: str
    line: int
    column: int = 0

    def __post_init__(self) -> None:
        if not self.file_path or "\0" in self.file_path:
            raise ValueError("A source location requires a file path")
        if type(self.line) is not int or self.line < 1:
            raise ValueError("A source line must be a positive integer")
        if type(self.column) is not int or self.column < 0:
            raise ValueError("A source column must be a nonnegative integer")


class RuntimeValueKind(StrEnum):
    SCALAR = "scalar"
    MAPPING = "mapping"
    SEQUENCE = "sequence"
    SET = "set"
    OBJECT = "object"
    OPAQUE = "opaque"
    TRUNCATED = "truncated"


@dataclass(frozen=True, slots=True)
class RuntimeChild:
    label: str
    value_id: str
    key_id: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeValue:
    value_id: str
    type_id: str
    kind: RuntimeValueKind
    preview: str
    scalar_value: JsonScalar = None
    children: tuple[RuntimeChild, ...] = ()
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class RuntimeBinding:
    name: str
    value_id: str
    changed: bool = False
    semantic_symbol_id: str | None = None
    frame_id: str = ""


@dataclass(frozen=True, slots=True)
class RuntimeBindingSpec:
    function: str
    name: str
    semantic_symbol_id: str
    module: str | None = None
    qualname: str | None = None


def program_binding_specs(program: ProgramModel) -> tuple[RuntimeBindingSpec, ...]:
    """Resolve Python frame ownership without confusing identically named functions."""
    result: list[RuntimeBindingSpec] = []
    functions = {item.id: item for item in program.functions}
    locations = program_function_locations(program)
    for symbol in program.symbols:
        function = functions.get(symbol.owner_id)
        if function is None or symbol.kind is ProgramSymbolKind.FUNCTION:
            continue
        location = locations.get(function.id)
        if location is None:
            continue
        owner = location.class_name
        lexical_owner = owner.rsplit(".", 1)[-1] if owner is not None else None
        result.append(
            RuntimeBindingSpec(
                normalize("NFKC", function.identifier),
                mangle_python_identifier(normalize("NFKC", symbol.name), lexical_owner),
                symbol.id,
                qualified_module_name(
                    program.package, location.module.path, kind=location.module.kind
                ),
                normalize(
                    "NFKC", f"{owner}.{function.identifier}" if owner else function.identifier
                ),
            )
        )
    return tuple(result)


@dataclass(frozen=True, slots=True)
class RuntimeGraph:
    execution_session_id: str
    project_revision: int
    artifact_revision: int
    sequence: int
    frame_id: str
    bindings: tuple[RuntimeBinding, ...]
    values: tuple[RuntimeValue, ...]
    history_index: int = 0
    checkpoint: bool = False
    truncated: bool = False

    def value(self, value_id: str) -> RuntimeValue | None:
        return next((item for item in self.values if item.value_id == value_id), None)


@dataclass(frozen=True, slots=True)
class RuntimeGraphDelta:
    """Compact worker update; checkpoints carry all values, deltas only changes."""

    execution_session_id: str
    project_revision: int
    artifact_revision: int
    sequence: int
    frame_id: str
    bindings: tuple[RuntimeBinding, ...]
    values: tuple[RuntimeValue, ...]
    removed_value_ids: tuple[str, ...] = ()
    history_index: int = 0
    checkpoint: bool = False
    truncated: bool = False


class RuntimeGraphAccumulator:
    """Reconstruct bounded checkpoints plus deltas emitted by the debug worker."""

    def __init__(self) -> None:
        self._values: dict[str, RuntimeValue] = {}
        self._bindings: dict[str, RuntimeBinding] = {}

    def reset(self) -> None:
        self._values.clear()
        self._bindings.clear()

    def decode_delta(
        self,
        raw: object,
        *,
        execution_session_id: str,
        project_revision: int,
        artifact_revision: int,
        sequence: int,
    ) -> RuntimeGraphDelta | None:
        """Reuse exact immutable bindings from this accumulator's latest snapshot."""
        return decode_runtime_delta(
            raw,
            execution_session_id=execution_session_id,
            project_revision=project_revision,
            artifact_revision=artifact_revision,
            sequence=sequence,
            previous_bindings=self._bindings,
        )

    def apply(
        self,
        raw: object,
        *,
        execution_session_id: str,
        project_revision: int,
        artifact_revision: int,
        sequence: int,
    ) -> RuntimeGraph | None:
        update = self.decode_delta(
            raw,
            execution_session_id=execution_session_id,
            project_revision=project_revision,
            artifact_revision=artifact_revision,
            sequence=sequence,
        )
        return None if update is None else self.apply_delta(update)

    def apply_delta(self, update: RuntimeGraphDelta) -> RuntimeGraph:
        if update.checkpoint:
            self._values.clear()
        for value in update.values:
            self._values[value.value_id] = value
        for value_id in update.removed_value_ids:
            self._values.pop(value_id, None)
        self._bindings = {binding.name: binding for binding in update.bindings}
        return RuntimeGraph(
            update.execution_session_id,
            update.project_revision,
            update.artifact_revision,
            update.sequence,
            update.frame_id,
            update.bindings,
            tuple(self._values.values()),
            update.history_index,
            update.checkpoint,
            update.truncated,
        )


def decode_runtime_delta(
    raw: object,
    *,
    execution_session_id: str,
    project_revision: int,
    artifact_revision: int,
    sequence: int,
    previous_bindings: Mapping[str, RuntimeBinding] | None = None,
) -> RuntimeGraphDelta | None:
    if not isinstance(raw, dict):
        return None
    kind = raw.get("kind")
    checkpoint = kind == "checkpoint"
    if kind not in {"checkpoint", "delta"}:
        return None
    values: list[RuntimeValue] = []
    raw_values = raw.get("values", [])
    if isinstance(raw_values, list):
        for raw_value in raw_values:
            value = _runtime_value(raw_value)
            if value is not None:
                values.append(value)
    removed = raw.get("removed_value_ids", [])
    removed_ids: list[str] = []
    if isinstance(removed, list):
        for value_id in removed:
            if isinstance(value_id, str):
                removed_ids.append(value_id)
    raw_bindings = raw.get("bindings", [])
    bindings: list[RuntimeBinding] = []
    if isinstance(raw_bindings, list):
        for raw_binding in raw_bindings:
            if not isinstance(raw_binding, dict):
                continue
            name = raw_binding.get("name")
            value_id = raw_binding.get("value_id")
            if isinstance(name, str) and isinstance(value_id, str):
                semantic_symbol_id = raw_binding.get("semantic_symbol_id")
                binding_frame_id = raw_binding.get("frame_id")
                symbol = semantic_symbol_id if isinstance(semantic_symbol_id, str) else None
                binding_frame = binding_frame_id if isinstance(binding_frame_id, str) else ""
                changed = bool(raw_binding.get("changed", False))
                previous = previous_bindings.get(name) if previous_bindings is not None else None
                if (
                    previous is not None
                    and previous.name == name
                    and previous.value_id == value_id
                    and previous.changed == changed
                    and previous.semantic_symbol_id == symbol
                    and previous.frame_id == binding_frame
                ):
                    bindings.append(previous)
                else:
                    bindings.append(RuntimeBinding(name, value_id, changed, symbol, binding_frame))
    frame_id = raw.get("frame_id")
    history_index = raw.get("history_index")
    return RuntimeGraphDelta(
        execution_session_id,
        project_revision,
        artifact_revision,
        sequence,
        frame_id if isinstance(frame_id, str) else "",
        tuple(bindings),
        tuple(values),
        tuple(removed_ids),
        history_index if isinstance(history_index, int) else 0,
        checkpoint,
        bool(raw.get("truncated", False)),
    )


class RuntimeTraceStore:
    """Bounded checkpoint/delta timeline with lazy graph reconstruction."""

    def __init__(self, *, history_limit: int = 500, cache_size: int = 8) -> None:
        if history_limit < 1 or cache_size < 1:
            raise ValueError("Runtime trace limits must be positive")
        self.history_limit = history_limit
        self.cache_size = cache_size
        self._updates: OrderedDict[int, RuntimeGraphDelta] = OrderedDict()
        self._cache: OrderedDict[int, RuntimeGraph] = OrderedDict()

    def clear(self) -> None:
        self._updates.clear()
        self._cache.clear()

    @property
    def indices(self) -> tuple[int, ...]:
        return tuple(self._updates)

    @property
    def updates(self) -> tuple[RuntimeGraphDelta, ...]:
        return tuple(self._updates.values())

    def append(self, update: RuntimeGraphDelta) -> None:
        if self._updates:
            latest = next(reversed(self._updates.values()))
            if (
                latest.execution_session_id != update.execution_session_id
                or latest.project_revision != update.project_revision
                or latest.artifact_revision != update.artifact_revision
            ):
                raise ValueError("A runtime trace cannot change session identity or revisions")
        self._updates[update.history_index] = update
        self._cache.pop(update.history_index, None)
        while len(self._updates) > self.history_limit:
            oldest = next(iter(self._updates))
            remaining = tuple(index for index in self._updates if index != oldest)
            if not remaining:
                self._updates.pop(oldest)
                break
            next_index = remaining[0]
            graph = self.graph_at(next_index)
            assert graph is not None
            replacement = RuntimeGraphDelta(
                graph.execution_session_id,
                graph.project_revision,
                graph.artifact_revision,
                graph.sequence,
                graph.frame_id,
                graph.bindings,
                graph.values,
                (),
                graph.history_index,
                True,
                graph.truncated,
            )
            rebuilt: OrderedDict[int, RuntimeGraphDelta] = OrderedDict()
            for index, item in self._updates.items():
                if index == oldest:
                    continue
                rebuilt[index] = replacement if index == next_index else item
            self._updates = rebuilt
            self._cache.clear()

    def graph_at(self, history_index: int) -> RuntimeGraph | None:
        cached = self._cache.get(history_index)
        if cached is not None:
            self._cache.move_to_end(history_index)
            return cached
        selected = [index for index in self._updates if index <= history_index]
        if not selected or history_index not in self._updates:
            return None
        checkpoint_index = next(
            (index for index in reversed(selected) if self._updates[index].checkpoint),
            selected[0],
        )
        accumulator = RuntimeGraphAccumulator()
        graph: RuntimeGraph | None = None
        for index in selected:
            if index < checkpoint_index:
                continue
            graph = accumulator.apply_delta(self._updates[index])
        if graph is None:
            return None
        # The requested index is the last selected value because it must exist.
        self._cache[history_index] = replace(
            graph, checkpoint=self._updates[history_index].checkpoint
        )
        self._cache.move_to_end(history_index)
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)
        return self._cache[history_index]

    @property
    def latest(self) -> RuntimeGraph | None:
        return self.graph_at(next(reversed(self._updates))) if self._updates else None


def _runtime_value(raw: object) -> RuntimeValue | None:
    if not isinstance(raw, dict):
        return None
    value_id = raw.get("value_id")
    type_id = raw.get("type_id")
    raw_kind = raw.get("kind")
    preview = raw.get("preview")
    if (
        not isinstance(value_id, str)
        or not isinstance(type_id, str)
        or not isinstance(raw_kind, str)
        or not isinstance(preview, str)
    ):
        return None
    try:
        kind = RuntimeValueKind(raw_kind)
    except ValueError:
        return None
    children: list[RuntimeChild] = []
    raw_children = raw.get("children", [])
    if isinstance(raw_children, list):
        for raw_child in raw_children:
            if not isinstance(raw_child, dict):
                continue
            label = raw_child.get("label")
            child_id = raw_child.get("value_id")
            key_id = raw_child.get("key_id")
            if (
                isinstance(label, str)
                and isinstance(child_id, str)
                and (key_id is None or isinstance(key_id, str))
            ):
                children.append(RuntimeChild(label, child_id, key_id))
    scalar = raw.get("scalar_value")
    scalar_value: JsonScalar = scalar if isinstance(scalar, (str, int, float, bool)) else None
    return RuntimeValue(
        value_id,
        type_id,
        kind,
        preview,
        scalar_value,
        tuple(children),
        bool(raw.get("truncated", False)),
    )
