"""Project runtime state onto any semantic lens as disposable overlay context."""

from __future__ import annotations

from dataclasses import dataclass, replace

from code_visualizer.application.runtime_projection import (
    RuntimeAdapterKind,
    compile_runtime_projection,
)
from code_visualizer.application.runtime_sessions import RuntimeSessionState
from code_visualizer.domain.semantic import (
    ProjectionEdge,
    ProjectionNode,
    SemanticObjectKind,
    SemanticProjection,
    SemanticRelationKind,
)


@dataclass(frozen=True, slots=True)
class RuntimeOverlayContext:
    """One timeline location plus display intent, independent of projection kind."""

    state: RuntimeSessionState | None
    previous: RuntimeSessionState | None = None
    adapter: RuntimeAdapterKind = RuntimeAdapterKind.AUTO
    binding_name: str | None = None
    include_values: bool = True
    value_limit: int = 40


def overlay_runtime_context(
    projection: SemanticProjection,
    context: RuntimeOverlayContext | None,
) -> SemanticProjection:
    """Decorate active semantics and optionally compose the runtime value graph."""

    if context is None or context.state is None:
        return projection
    state = context.state
    stale = state.project_revision != projection.revision
    active_ids = set(state.active_ids)
    previous_ids = set(context.previous.active_ids) if context.previous is not None else set()
    graph = state.graph
    values = {item.value_id: item for item in graph.values} if graph is not None else {}
    bindings = graph.bindings if graph is not None else ()

    nodes: list[ProjectionNode] = []
    active_node_ids: set[str] = set()
    previous_node_ids: set[str] = set()
    for node in projection.nodes:
        badges = list(node.badges)
        details = [node.detail] if node.detail else []
        if node.semantic_id in active_ids:
            active_node_ids.add(node.id)
            badges.append("runtime stale" if stale else "active")
            details.append(
                f"runtime event {state.event_sequence}"
                + (f" from project r{state.project_revision}" if stale else "")
            )
        if node.semantic_id in previous_ids:
            previous_node_ids.add(node.id)
        if node.kind is SemanticObjectKind.SYMBOL:
            for binding in bindings:
                matches = (
                    node.semantic_id == binding.semantic_symbol_id
                    if binding.semantic_symbol_id is not None
                    else binding.name == node.label
                )
                if not matches:
                    continue
                value = values.get(binding.value_id)
                if binding.changed:
                    badges.append("changed")
                else:
                    badges.append("observed")
                if value is not None:
                    details.append(f"runtime {binding.name} = {value.preview}")
        nodes.append(
            replace(
                node,
                detail="\n".join(dict.fromkeys(details)),
                badges=tuple(dict.fromkeys(badges)),
            )
        )

    edges = [
        replace(
            edge,
            active=(
                bool(previous_node_ids)
                and bool(active_node_ids)
                and edge.source_id in previous_node_ids
                and edge.target_id in active_node_ids
            ),
        )
        for edge in projection.edges
    ]
    if context.include_values:
        runtime = compile_runtime_projection(
            projection.project_id,
            state,
            adapter=context.adapter,
            binding_name=context.binding_name,
        )
        limit = max(1, context.value_limit)
        runtime_nodes = list(runtime.nodes[:limit])
        included = {item.id for item in runtime_nodes}
        runtime_edges = [
            item
            for item in runtime.edges
            if item.source_id in included and item.target_id in included
        ]
        nodes.extend(runtime_nodes)
        edges.extend(runtime_edges)
        session_id = f"runtime:session:{state.execution_session_id}"
        if session_id in included and active_node_ids:
            target = sorted(active_node_ids)[0]
            edges.append(
                ProjectionEdge(
                    f"runtime-edge:overlay:{state.execution_session_id}:{target}",
                    session_id,
                    target,
                    SemanticRelationKind.CONTROL_FLOW,
                    "active semantic node",
                    True,
                )
            )
        omitted = len(runtime.nodes) - len(runtime_nodes)
        if omitted:
            summary_id = f"runtime:compressed:{state.execution_session_id}"
            nodes.append(
                ProjectionNode(
                    summary_id,
                    summary_id,
                    SemanticObjectKind.GROUP,
                    f"{omitted} more runtime values",
                    "Increase the runtime overlay value limit to inspect them.",
                    badges=("runtime compressed",),
                    expandable=True,
                    hidden_count=omitted,
                )
            )
            if session_id in included:
                edges.append(
                    ProjectionEdge(
                        f"runtime-edge:compressed:{state.execution_session_id}",
                        session_id,
                        summary_id,
                        SemanticRelationKind.CONTAINS,
                        "more values",
                    )
                )

    return replace(
        projection,
        nodes=tuple(nodes),
        edges=tuple(edges),
        title=f"{projection.title} + Runtime" if projection.title else "Runtime overlay",
    )
