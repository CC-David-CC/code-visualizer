"""Runtime history projections and data-structure-aware visual adapters.

The debugger owns observation and object identity.  This module only turns one
immutable runtime state into a disposable semantic projection; no Qt types or
project mutations are involved.
"""

from __future__ import annotations

from collections import defaultdict, deque
from enum import StrEnum
from itertools import pairwise

from code_visualizer.application.runtime_sessions import RuntimeSessionState
from code_visualizer.domain.projection import ProjectionLayout
from code_visualizer.domain.semantic import (
    ProjectionEdge,
    ProjectionKind,
    ProjectionNode,
    SemanticObjectKind,
    SemanticProjection,
    SemanticRelationKind,
)
from code_visualizer.execution import RuntimeBinding, RuntimeGraph, RuntimeValue, RuntimeValueKind


class RuntimeAdapterKind(StrEnum):
    AUTO = "auto"
    GENERIC = "generic"
    LIST = "list"
    QUEUE = "queue"
    HEAP = "heap"
    GRAPH = "graph"
    MATRIX = "matrix"
    TREE = "tree"
    MAPPING = "mapping"
    TENSOR = "tensor"
    DATAFRAME = "dataframe"


def infer_runtime_adapter(
    graph: RuntimeGraph | None,
    binding_name: str | None = None,
) -> RuntimeAdapterKind:
    """Infer a useful visual grammar without changing observed runtime values."""

    if graph is None:
        return RuntimeAdapterKind.GENERIC
    bindings = _selected_bindings(graph, binding_name)
    if not bindings:
        return RuntimeAdapterKind.GENERIC
    values = {item.value_id: item for item in graph.values}
    names = " ".join(item.name.casefold() for item in bindings)
    root_values = [values[item.value_id] for item in bindings if item.value_id in values]
    type_names = " ".join(item.type_id.casefold() for item in root_values)
    if (
        "dataframe" in names
        or names.strip() in {"df", "frame"}
        or "pandas.core.frame.dataframe" in type_names
    ):
        return RuntimeAdapterKind.DATAFRAME
    if any(token in names for token in ("tensor", "ndarray", "weights")) or any(
        token in type_names for token in ("numpy.ndarray", "torch.tensor", "tensorflow")
    ):
        return RuntimeAdapterKind.TENSOR
    if any(token in names for token in ("priority_queue", "priorityqueue", "heap", "pq")):
        return RuntimeAdapterKind.HEAP
    if any(token in names for token in ("queue", "frontier", "deque")):
        return RuntimeAdapterKind.QUEUE
    if any(token in names for token in ("matrix", "grid", "board", "tensor")):
        return RuntimeAdapterKind.MATRIX
    if any(token in names for token in ("graph", "adjacency", "neighbors", "edges")):
        return RuntimeAdapterKind.GRAPH
    if any(token in names for token in ("tree", "root", "trie")):
        return RuntimeAdapterKind.TREE
    if any(_looks_like_matrix(item, values) for item in root_values):
        return RuntimeAdapterKind.MATRIX
    if any(_looks_like_tree(item) for item in root_values):
        return RuntimeAdapterKind.TREE
    if any(item.kind is RuntimeValueKind.SEQUENCE for item in root_values):
        return RuntimeAdapterKind.LIST
    if any(item.kind is RuntimeValueKind.MAPPING for item in root_values):
        return RuntimeAdapterKind.MAPPING
    return RuntimeAdapterKind.GENERIC


def compile_runtime_projection(
    project_id: str,
    state: RuntimeSessionState | None,
    *,
    adapter: RuntimeAdapterKind = RuntimeAdapterKind.AUTO,
    binding_name: str | None = None,
) -> SemanticProjection:
    """Build one revision-pinned runtime lens from an execution-history state."""

    if state is None:
        return SemanticProjection(
            ProjectionKind.RUNTIME,
            project_id,
            0,
            None,
            (),
            (),
            "runtime:none",
            "Runtime values",
        )
    graph = state.graph
    resolved_adapter = (
        infer_runtime_adapter(graph, binding_name)
        if adapter is RuntimeAdapterKind.AUTO
        else adapter
    )
    session_node = f"runtime:session:{state.execution_session_id}"
    nodes: list[ProjectionNode] = [
        ProjectionNode(
            session_node,
            state.semantic_id or session_node,
            SemanticObjectKind.STRUCTURE,
            f"Execution | {state.status.value}",
            f"project r{state.project_revision} | artifact r{state.artifact_revision}",
            badges=(f"event {state.event_sequence}", resolved_adapter.value),
        )
    ]
    edges: list[ProjectionEdge] = []
    if state.semantic_id is not None:
        current_node = f"runtime:current:{state.execution_session_id}"
        nodes.append(
            ProjectionNode(
                current_node,
                state.semantic_id,
                SemanticObjectKind.OPERATION,
                "Current operation",
                state.semantic_id,
                badges=("semantic location",),
            )
        )
        edges.append(
            ProjectionEdge(
                f"runtime-edge:current:{state.execution_session_id}",
                session_node,
                current_node,
                SemanticRelationKind.CONTROL_FLOW,
                "paused at",
            )
        )
    if graph is not None:
        _append_runtime_graph(
            nodes,
            edges,
            session_node,
            graph,
            resolved_adapter,
            binding_name,
        )
    return SemanticProjection(
        ProjectionKind.RUNTIME,
        project_id,
        state.project_revision,
        session_node,
        tuple(nodes),
        tuple(edges),
        f"runtime:{resolved_adapter.value}",
        f"Runtime | {resolved_adapter.value.replace('_', ' ').title()}",
        _layout_for(resolved_adapter).value,
    )


def _append_runtime_graph(
    nodes: list[ProjectionNode],
    edges: list[ProjectionEdge],
    session_node: str,
    graph: RuntimeGraph,
    adapter: RuntimeAdapterKind,
    binding_name: str | None,
) -> None:
    values = {item.value_id: item for item in graph.values}
    bindings = _selected_bindings(graph, binding_name)
    included_ids = _reachable_value_ids(values, bindings)
    value_nodes = {
        value_id: f"runtime:value:{graph.execution_session_id}:{value_id}"
        for value_id in included_ids
    }
    roles = _adapter_roles(adapter, bindings, values)
    for value_id in sorted(included_ids):
        value = values.get(value_id)
        if value is None:
            continue
        badges = [value.kind.value, value.type_id]
        badges.extend(roles.get(value_id, ()))
        if value.truncated:
            badges.append("truncated")
        nodes.append(
            ProjectionNode(
                value_nodes[value_id],
                value.value_id,
                SemanticObjectKind.STRUCTURE,
                _value_label(value, roles.get(value_id, ())),
                value.preview,
                badges=tuple(dict.fromkeys(badges)),
            )
        )
    root_values: list[RuntimeValue] = []
    for binding in bindings:
        binding_node = (
            f"runtime:binding:{graph.execution_session_id}:{graph.frame_id}:{binding.name}"
        )
        nodes.append(
            ProjectionNode(
                binding_node,
                binding_node,
                SemanticObjectKind.SYMBOL,
                binding.name,
                "changed binding" if binding.changed else "local binding",
                badges=(adapter.value, "changed" if binding.changed else "observed"),
            )
        )
        edges.append(
            ProjectionEdge(
                f"runtime-edge:binding:{binding_node}",
                session_node,
                binding_node,
                SemanticRelationKind.CONTAINS,
            )
        )
        target = value_nodes.get(binding.value_id)
        if target is not None:
            edges.append(
                ProjectionEdge(
                    f"runtime-edge:value:{binding_node}",
                    binding_node,
                    target,
                    SemanticRelationKind.REFERENCES,
                    "binds",
                )
            )
        root = values.get(binding.value_id)
        if root is not None:
            root_values.append(root)

    adapted_sources = {
        item.value_id
        for item in root_values
        if item.kind is RuntimeValueKind.SEQUENCE
        and adapter in {RuntimeAdapterKind.LIST, RuntimeAdapterKind.QUEUE, RuntimeAdapterKind.HEAP}
    }
    for value_id in sorted(included_ids):
        value = values.get(value_id)
        if value is None or value_id in adapted_sources:
            continue
        source = value_nodes[value_id]
        for index, child in enumerate(value.children):
            target = value_nodes.get(child.value_id)
            if target is None:
                continue
            edges.append(
                ProjectionEdge(
                    f"runtime-edge:child:{value.value_id}:{index}",
                    source,
                    target,
                    SemanticRelationKind.CONTAINS,
                    child.label,
                )
            )
    for root in root_values:
        if root.value_id not in adapted_sources:
            continue
        if adapter is RuntimeAdapterKind.HEAP:
            _append_heap_edges(edges, root, value_nodes)
        else:
            _append_linear_edges(
                edges,
                root,
                value_nodes,
                queue=adapter is RuntimeAdapterKind.QUEUE,
            )


def _selected_bindings(
    graph: RuntimeGraph,
    binding_name: str | None,
) -> tuple[RuntimeBinding, ...]:
    if binding_name is None:
        return graph.bindings
    selected = tuple(item for item in graph.bindings if item.name == binding_name)
    return selected or graph.bindings


def _reachable_value_ids(
    values: dict[str, RuntimeValue],
    bindings: tuple[RuntimeBinding, ...],
) -> set[str]:
    result: set[str] = set()
    pending = deque(item.value_id for item in bindings)
    while pending:
        value_id = pending.popleft()
        if value_id in result or value_id not in values:
            continue
        result.add(value_id)
        value = values[value_id]
        for child in value.children:
            pending.append(child.value_id)
            if child.key_id is not None:
                pending.append(child.key_id)
    return result


def _append_linear_edges(
    edges: list[ProjectionEdge],
    root: RuntimeValue,
    value_nodes: dict[str, str],
    *,
    queue: bool,
) -> None:
    children = [child for child in root.children if child.value_id in value_nodes]
    if not children:
        return
    root_node = value_nodes[root.value_id]
    first = value_nodes[children[0].value_id]
    edges.append(
        ProjectionEdge(
            f"runtime-edge:linear:{root.value_id}:0",
            root_node,
            first,
            SemanticRelationKind.CONTAINS,
            "front" if queue else "item 0",
        )
    )
    for index, (left, right) in enumerate(pairwise(children), start=1):
        edges.append(
            ProjectionEdge(
                f"runtime-edge:linear:{root.value_id}:{index}",
                value_nodes[left.value_id],
                value_nodes[right.value_id],
                SemanticRelationKind.TRANSITION,
                "next",
            )
        )


def _append_heap_edges(
    edges: list[ProjectionEdge],
    root: RuntimeValue,
    value_nodes: dict[str, str],
) -> None:
    children = [child for child in root.children if child.value_id in value_nodes]
    if not children:
        return
    edges.append(
        ProjectionEdge(
            f"runtime-edge:heap:{root.value_id}:root",
            value_nodes[root.value_id],
            value_nodes[children[0].value_id],
            SemanticRelationKind.CONTAINS,
            "heap root",
        )
    )
    for index, child in enumerate(children[1:], start=1):
        parent_index = (index - 1) // 2
        edges.append(
            ProjectionEdge(
                f"runtime-edge:heap:{root.value_id}:{index}",
                value_nodes[children[parent_index].value_id],
                value_nodes[child.value_id],
                SemanticRelationKind.CONTAINS,
                f"index {index}",
            )
        )


def _adapter_roles(
    adapter: RuntimeAdapterKind,
    bindings: tuple[RuntimeBinding, ...],
    values: dict[str, RuntimeValue],
) -> dict[str, tuple[str, ...]]:
    roles: dict[str, list[str]] = defaultdict(list)
    for binding in bindings:
        root = values.get(binding.value_id)
        if root is None:
            continue
        roles[root.value_id].append(f"{adapter.value} root")
        for index, child in enumerate(root.children):
            if adapter is RuntimeAdapterKind.QUEUE:
                if index == 0:
                    roles[child.value_id].append("front")
                if index == len(root.children) - 1:
                    roles[child.value_id].append("back")
            elif adapter is RuntimeAdapterKind.HEAP:
                roles[child.value_id].append(f"heap index {index}")
            elif adapter in {
                RuntimeAdapterKind.LIST,
                RuntimeAdapterKind.MATRIX,
                RuntimeAdapterKind.TENSOR,
                RuntimeAdapterKind.DATAFRAME,
            }:
                roles[child.value_id].append(child.label or f"index {index}")
    return {key: tuple(value) for key, value in roles.items()}


def _value_label(value: RuntimeValue, roles: tuple[str, ...]) -> str:
    del roles
    return value.preview


def _looks_like_matrix(value: RuntimeValue, values: dict[str, RuntimeValue]) -> bool:
    if value.kind is not RuntimeValueKind.SEQUENCE or not value.children:
        return False
    children = [values.get(item.value_id) for item in value.children]
    return bool(children) and all(
        child is not None and child.kind is RuntimeValueKind.SEQUENCE for child in children
    )


def _looks_like_tree(value: RuntimeValue) -> bool:
    labels = {item.label.casefold() for item in value.children}
    return bool(labels & {"left", "right"}) or "children" in labels


def _layout_for(adapter: RuntimeAdapterKind) -> ProjectionLayout:
    return {
        RuntimeAdapterKind.LIST: ProjectionLayout.HORIZONTAL,
        RuntimeAdapterKind.QUEUE: ProjectionLayout.HORIZONTAL,
        RuntimeAdapterKind.HEAP: ProjectionLayout.HIERARCHICAL,
        RuntimeAdapterKind.GRAPH: ProjectionLayout.RADIAL,
        RuntimeAdapterKind.MATRIX: ProjectionLayout.GRID,
        RuntimeAdapterKind.TREE: ProjectionLayout.HIERARCHICAL,
        RuntimeAdapterKind.MAPPING: ProjectionLayout.HIERARCHICAL,
        RuntimeAdapterKind.TENSOR: ProjectionLayout.GRID,
        RuntimeAdapterKind.DATAFRAME: ProjectionLayout.GRID,
        RuntimeAdapterKind.GENERIC: ProjectionLayout.HIERARCHICAL,
        RuntimeAdapterKind.AUTO: ProjectionLayout.HIERARCHICAL,
    }[adapter]
