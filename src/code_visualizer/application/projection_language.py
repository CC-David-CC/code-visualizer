"""Compiler for composable semantic projection definitions."""

from __future__ import annotations

import heapq
from collections import Counter, deque

from code_visualizer.domain.projection import (
    ProjectionDecoration,
    ProjectionDefinition,
    ProjectionGrouping,
    ProjectionLabelStyle,
    ProjectionLayout,
    TraversalDirection,
)
from code_visualizer.domain.semantic import (
    ProjectionEdge,
    ProjectionKind,
    ProjectionNode,
    SemanticObject,
    SemanticObjectKind,
    SemanticProgram,
    SemanticProjection,
    SemanticRelation,
    SemanticRelationKind,
)


def builtin_projection_definition(
    kind: ProjectionKind,
    program: SemanticProgram,
    root: str | None = None,
) -> ProjectionDefinition:
    """Express every general-purpose built-in lens with the same vocabulary."""

    first_function = next(
        (item.id for item in program.objects if item.kind is SemanticObjectKind.FUNCTION),
        None,
    )
    if kind is ProjectionKind.ARCHITECTURE:
        return ProjectionDefinition(
            "builtin:architecture",
            "Architecture",
            scope_id=program.project_id,
            object_kinds=(
                SemanticObjectKind.PROJECT,
                SemanticObjectKind.NAMESPACE,
                SemanticObjectKind.DOMAIN,
                SemanticObjectKind.DOMAIN_SCHEMA,
                SemanticObjectKind.CONCEPT_DEFINITION,
                SemanticObjectKind.LANGUAGE_DEFINITION,
                SemanticObjectKind.NOTATION_DEFINITION,
                SemanticObjectKind.VALIDATION_RULE,
                SemanticObjectKind.TRANSFORMATION,
                SemanticObjectKind.MODULE,
                SemanticObjectKind.CLASS,
                SemanticObjectKind.FUNCTION,
            ),
            relation_kinds=(SemanticRelationKind.CONTAINS,),
            direction=TraversalDirection.OUTGOING,
            max_depth=32,
            grouping=ProjectionGrouping.OWNER,
            layout=ProjectionLayout.HIERARCHICAL,
            node_limit=100,
        )
    if kind is ProjectionKind.CALLS:
        return ProjectionDefinition(
            "builtin:calls",
            "Call graph",
            object_kinds=(SemanticObjectKind.FUNCTION,),
            relation_kinds=(SemanticRelationKind.CALLS,),
            max_depth=32,
            layout=ProjectionLayout.HORIZONTAL,
            node_limit=100,
        )
    if kind is ProjectionKind.CONTROL:
        return ProjectionDefinition(
            "builtin:control",
            "Control flow",
            scope_id=root or first_function,
            object_kinds=(
                SemanticObjectKind.FUNCTION,
                SemanticObjectKind.STRUCTURE,
                SemanticObjectKind.OPERATION,
            ),
            relation_kinds=(
                SemanticRelationKind.CONTAINS,
                SemanticRelationKind.CONTROL_FLOW,
                SemanticRelationKind.BRANCH,
                SemanticRelationKind.TRANSITION,
            ),
            direction=TraversalDirection.OUTGOING,
            max_depth=64,
            layout=ProjectionLayout.HIERARCHICAL,
            node_limit=100,
        )
    if kind is ProjectionKind.DATA:
        return ProjectionDefinition(
            "builtin:data",
            "Data flow",
            scope_id=root or first_function,
            object_kinds=(
                SemanticObjectKind.FUNCTION,
                SemanticObjectKind.STRUCTURE,
                SemanticObjectKind.OPERATION,
                SemanticObjectKind.EXPRESSION,
                SemanticObjectKind.SYMBOL,
            ),
            relation_kinds=(
                SemanticRelationKind.CONTAINS,
                SemanticRelationKind.DEFINES,
                SemanticRelationKind.EVALUATES,
                SemanticRelationKind.READS,
                SemanticRelationKind.WRITES,
                SemanticRelationKind.REFERENCES,
            ),
            direction=TraversalDirection.OUTGOING,
            max_depth=64,
            layout=ProjectionLayout.HORIZONTAL,
            node_limit=50,
        )
    if kind is ProjectionKind.CONCEPTS:
        return ProjectionDefinition(
            "builtin:concepts",
            "Authored concepts",
            object_kinds=(
                SemanticObjectKind.CONCEPT,
                SemanticObjectKind.INTENTION,
                SemanticObjectKind.DOMAIN,
                SemanticObjectKind.PROJECT,
                SemanticObjectKind.NAMESPACE,
                SemanticObjectKind.MODULE,
                SemanticObjectKind.CLASS,
                SemanticObjectKind.FUNCTION,
                SemanticObjectKind.OPERATION,
                SemanticObjectKind.SYMBOL,
            ),
            relation_kinds=(
                SemanticRelationKind.CONCEPTUALLY_CONTAINS,
                SemanticRelationKind.AUTHORED,
            ),
            max_depth=64,
            grouping=ProjectionGrouping.CONCEPT,
            layout=ProjectionLayout.RADIAL,
            include_isolated=False,
            node_limit=100,
        )
    raise ValueError(f"{kind.value!r} is not a composable built-in projection")


def compile_projection(
    program: SemanticProgram,
    definition: ProjectionDefinition,
    *,
    kind: ProjectionKind = ProjectionKind.COMPOSED,
) -> SemanticProjection:
    """Apply scope, traversal, filtering, grouping, decoration, and encoding."""

    objects = {item.id: item for item in program.objects}
    relation_kinds = frozenset(definition.relation_kinds)
    followed = tuple(
        relation
        for relation in program.relations
        if not relation_kinds or relation.kind in relation_kinds
    )
    candidate_ids = _scope_candidates(objects, followed, definition)
    accepted_kinds = frozenset(definition.object_kinds)
    node_ids = {
        object_id
        for object_id in candidate_ids
        if object_id in objects
        and (not accepted_kinds or objects[object_id].kind in accepted_kinds)
    }
    if definition.include_scope and definition.scope_id in objects:
        node_ids.add(definition.scope_id)

    selected_relations = tuple(
        relation
        for relation in followed
        if relation.source_id in node_ids and relation.target_id in node_ids
    )
    if definition.grouping is ProjectionGrouping.OWNER:
        node_ids, selected_relations = _with_owners(
            node_ids,
            selected_relations,
            objects,
            program.relations,
        )
    elif definition.grouping is ProjectionGrouping.CONCEPT:
        node_ids, selected_relations = _with_concepts(
            node_ids,
            selected_relations,
            objects,
            program.relations,
        )
    if not definition.include_isolated:
        connected_ids = {
            endpoint
            for relation in selected_relations
            for endpoint in (relation.source_id, relation.target_id)
        }
        if definition.include_scope and definition.scope_id is not None:
            connected_ids.add(definition.scope_id)
        node_ids.intersection_update(connected_ids)
        selected_relations = tuple(
            relation
            for relation in selected_relations
            if relation.source_id in node_ids and relation.target_id in node_ids
        )

    node_ids, hidden_by_node, omitted_count, omitted_by_kind = _compress_node_ids(
        node_ids,
        objects,
        definition,
        selected_relations,
    )
    selected_relations = tuple(
        relation
        for relation in selected_relations
        if relation.source_id in node_ids and relation.target_id in node_ids
    )

    nodes = [
        ProjectionNode(
            item.id,
            item.anchor_id or item.id,
            item.kind,
            _label(item, objects, definition.label_style),
            item.detail,
            item.document_id,
            item.field,
            _badges(item, definition.decorations),
            hidden_by_node.get(item.id, 0) > 0,
            hidden_by_node.get(item.id, 0),
        )
        for item in sorted(
            (objects[item_id] for item_id in node_ids if item_id in objects),
            key=lambda value: (value.kind.value, value.label.casefold(), value.id),
        )
    ]
    edges = [
        ProjectionEdge(
            relation.id,
            relation.source_id,
            relation.target_id,
            relation.kind,
            relation.label,
        )
        for relation in sorted(selected_relations, key=lambda value: value.id)
        if relation.source_id in node_ids and relation.target_id in node_ids
    ]
    if omitted_count:
        summary_id = f"projection-summary:{definition.id}"
        nodes.append(
            ProjectionNode(
                summary_id,
                summary_id,
                SemanticObjectKind.GROUP,
                f"{omitted_count} more semantic objects",
                "Compressed by graph relevance: "
                + ", ".join(
                    f"{count} {kind.replace('_', ' ')}"
                    for kind, count in sorted(omitted_by_kind.items())
                )
                + ". Increase the object limit or focus/expand a node to reveal them.",
                badges=("compressed",),
                expandable=True,
                hidden_count=omitted_count,
            )
        )
    if definition.grouping is ProjectionGrouping.KIND:
        _group_by_kind(definition, nodes, edges)
    return SemanticProjection(
        kind,
        program.project_id,
        program.revision,
        definition.scope_id,
        tuple(nodes),
        tuple(edges),
        definition.id,
        definition.title,
        definition.layout.value,
    )


def _compress_node_ids(
    candidate_ids: set[str],
    objects: dict[str, SemanticObject],
    definition: ProjectionDefinition,
    relations: tuple[SemanticRelation, ...],
) -> tuple[set[str], dict[str, int], int, dict[str, int]]:
    """Hide AST implementation depth by default, then enforce a useful view budget."""

    expanded = frozenset(definition.expanded_ids)
    visible = {
        object_id
        for object_id in candidate_ids
        if not (
            (item := objects.get(object_id)) is not None
            and item.kind is SemanticObjectKind.EXPRESSION
            and item.parent_id in candidate_ids
            and objects.get(item.parent_id) is not None
            and objects[item.parent_id].kind is SemanticObjectKind.EXPRESSION
        )
    }
    changed = True
    while changed:
        changed = False
        for object_id in candidate_ids - visible:
            item = objects.get(object_id)
            if item is not None and item.parent_id in visible and item.parent_id in expanded:
                visible.add(object_id)
                changed = True

    children: dict[str, list[str]] = {}
    for object_id in candidate_ids:
        item = objects.get(object_id)
        if item is not None and item.parent_id in candidate_ids:
            children.setdefault(item.parent_id, []).append(object_id)

    def hidden_descendants(parent_id: str) -> int:
        pending = list(children.get(parent_id, ()))
        count = 0
        while pending:
            child_id = pending.pop()
            if child_id not in visible:
                count += 1
            pending.extend(children.get(child_id, ()))
        return count

    hidden_by_node = {
        object_id: count
        for object_id in visible
        if objects[object_id].kind is SemanticObjectKind.EXPRESSION
        and (count := hidden_descendants(object_id)) > 0
    }

    limit = max(2, definition.node_limit)
    if len(visible) <= limit:
        return visible, hidden_by_node, 0, {}

    kind_rank = {
        SemanticObjectKind.OPERATION: 0,
        SemanticObjectKind.SYMBOL: 1,
        SemanticObjectKind.FUNCTION: 2,
        SemanticObjectKind.STRUCTURE: 3,
        SemanticObjectKind.EXPRESSION: 4,
        SemanticObjectKind.CLASS: 5,
        SemanticObjectKind.MODULE: 6,
        SemanticObjectKind.NAMESPACE: 7,
        SemanticObjectKind.PROJECT: 8,
        SemanticObjectKind.CONCEPT: 9,
    }
    relation_weight = {
        SemanticRelationKind.CONTROL_FLOW: 1,
        SemanticRelationKind.BRANCH: 1,
        SemanticRelationKind.CALLS: 1,
        SemanticRelationKind.READS: 1,
        SemanticRelationKind.WRITES: 1,
        SemanticRelationKind.TRANSITION: 1,
        SemanticRelationKind.DEFINES: 2,
        SemanticRelationKind.EVALUATES: 2,
        SemanticRelationKind.REFERENCES: 2,
        SemanticRelationKind.CONTAINS: 3,
    }
    adjacency: dict[str, list[tuple[str, int]]] = {}
    incident_importance: dict[str, int] = {}
    for relation in relations:
        if relation.source_id not in visible or relation.target_id not in visible:
            continue
        weight = relation_weight.get(relation.kind, 4)
        adjacency.setdefault(relation.source_id, []).append((relation.target_id, weight))
        adjacency.setdefault(relation.target_id, []).append((relation.source_id, weight))
        importance = 5 - min(weight, 4)
        incident_importance[relation.source_id] = max(
            incident_importance.get(relation.source_id, 0), importance
        )
        incident_importance[relation.target_id] = max(
            incident_importance.get(relation.target_id, 0), importance
        )

    focus = tuple(item for item in definition.focus_ids if item in visible)
    seeds = focus or (
        (definition.scope_id,)
        if definition.scope_id is not None and definition.scope_id in visible
        else tuple(
            sorted(
                (item for item in visible if objects[item].kind is SemanticObjectKind.FUNCTION),
            )[:1]
        )
    )
    if not seeds:
        seeds = (min(visible),)
    distance: dict[str, int] = {}
    predecessor: dict[str, str] = {}
    pending: list[tuple[int, str]] = []
    for seed in seeds:
        distance[seed] = 0
        heapq.heappush(pending, (0, seed))
    while pending:
        current_distance, current = heapq.heappop(pending)
        if current_distance != distance.get(current):
            continue
        for neighbor, weight in adjacency.get(current, ()):
            candidate_distance = current_distance + weight
            if candidate_distance >= distance.get(neighbor, 1_000_000_000):
                continue
            distance[neighbor] = candidate_distance
            predecessor[neighbor] = current
            heapq.heappush(pending, (candidate_distance, neighbor))

    def priority(object_id: str) -> tuple[int, int, int, str, str]:
        item = objects[object_id]
        return (
            distance.get(object_id, 1_000_000_000),
            -incident_importance.get(object_id, 0),
            kind_rank.get(item.kind, 20),
            item.label.casefold(),
            item.id,
        )

    budget = limit - 1
    kept: set[str] = set()

    def meaningful_path(object_id: str) -> set[str]:
        result = {object_id}
        current = object_id
        while current in predecessor:
            current = predecessor[current]
            result.add(current)
        current = object_id
        while (
            (parent := objects[current].parent_id) is not None
            and parent in visible
            and parent not in result
        ):
            result.add(parent)
            current = parent
        return result

    for object_id in (*seeds, *sorted(visible, key=priority)):
        if object_id in kept:
            continue
        bundle = meaningful_path(object_id) - kept
        if len(kept) + len(bundle) <= budget:
            kept.update(bundle)
        elif len(kept) < budget:
            kept.add(object_id)
        if len(kept) >= budget:
            break
    omitted = len(visible) - len(kept)
    omitted_by_kind = Counter(
        objects[item].kind.value for item in visible - kept if item in objects
    )
    return (
        kept,
        {key: value for key, value in hidden_by_node.items() if key in kept},
        omitted,
        dict(omitted_by_kind),
    )


def _scope_candidates(
    objects: dict[str, SemanticObject],
    relations: tuple[SemanticRelation, ...],
    definition: ProjectionDefinition,
) -> set[str]:
    scope_id = definition.scope_id
    if scope_id is None or scope_id not in objects:
        return set(objects)
    outgoing: dict[str, list[str]] = {}
    incoming: dict[str, list[str]] = {}
    for relation in relations:
        outgoing.setdefault(relation.source_id, []).append(relation.target_id)
        incoming.setdefault(relation.target_id, []).append(relation.source_id)
    result = {scope_id}
    pending = deque(((scope_id, 0),))
    while pending:
        current, depth = pending.popleft()
        if depth >= definition.max_depth:
            continue
        neighbors: list[str] = []
        if definition.direction in {TraversalDirection.OUTGOING, TraversalDirection.BOTH}:
            neighbors.extend(outgoing.get(current, ()))
        if definition.direction in {TraversalDirection.INCOMING, TraversalDirection.BOTH}:
            neighbors.extend(incoming.get(current, ()))
        for neighbor in sorted(set(neighbors)):
            if neighbor in result:
                continue
            result.add(neighbor)
            pending.append((neighbor, depth + 1))
    return result


def _with_owners(
    node_ids: set[str],
    selected: tuple[SemanticRelation, ...],
    objects: dict[str, SemanticObject],
    relations: tuple[SemanticRelation, ...],
) -> tuple[set[str], tuple[SemanticRelation, ...]]:
    expanded = set(node_ids)
    pending = list(node_ids)
    while pending:
        item = objects.get(pending.pop())
        if item is None or item.parent_id is None or item.parent_id in expanded:
            continue
        expanded.add(item.parent_id)
        pending.append(item.parent_id)
    relation_map = {item.id: item for item in selected}
    for relation in relations:
        if (
            relation.kind is SemanticRelationKind.CONTAINS
            and relation.source_id in expanded
            and relation.target_id in expanded
        ):
            relation_map[relation.id] = relation
    return expanded, tuple(relation_map.values())


def _with_concepts(
    node_ids: set[str],
    selected: tuple[SemanticRelation, ...],
    objects: dict[str, SemanticObject],
    relations: tuple[SemanticRelation, ...],
) -> tuple[set[str], tuple[SemanticRelation, ...]]:
    expanded = set(node_ids)
    relation_map = {item.id: item for item in selected}
    changed = True
    while changed:
        changed = False
        for relation in relations:
            if relation.kind is not SemanticRelationKind.CONCEPTUALLY_CONTAINS:
                continue
            if relation.target_id in expanded and relation.source_id in objects:
                if relation.source_id not in expanded:
                    expanded.add(relation.source_id)
                    changed = True
                relation_map[relation.id] = relation
    return expanded, tuple(relation_map.values())


def _label(
    item: SemanticObject,
    objects: dict[str, SemanticObject],
    style: ProjectionLabelStyle,
) -> str:
    if style is ProjectionLabelStyle.DETAIL and item.detail:
        return f"{item.label} - {item.detail}"
    if style is ProjectionLabelStyle.QUALIFIED:
        names = [item.label]
        parent_id = item.parent_id
        visited = {item.id}
        while parent_id is not None and parent_id not in visited:
            visited.add(parent_id)
            parent = objects.get(parent_id)
            if parent is None:
                break
            names.append(parent.label)
            parent_id = parent.parent_id
        return " :: ".join(reversed(names))
    return item.label


def _badges(
    item: SemanticObject,
    decorations: tuple[ProjectionDecoration, ...],
) -> tuple[str, ...]:
    result: list[str] = []
    if ProjectionDecoration.KIND in decorations:
        result.append(item.kind.value.replace("_", " "))
    if ProjectionDecoration.DETAIL in decorations and item.detail:
        result.append(item.detail[:80])
    if ProjectionDecoration.ANCHOR_STATE in decorations:
        result.append("semantic glyph" if item.anchor_id is not None else "canonical")
    return tuple(result)


def _group_by_kind(
    definition: ProjectionDefinition,
    nodes: list[ProjectionNode],
    edges: list[ProjectionEdge],
) -> None:
    for kind in sorted({node.kind for node in nodes}, key=lambda value: value.value):
        group_id = f"projection-group:{definition.id}:kind:{kind.value}"
        group_members = [node for node in nodes if node.kind is kind]
        nodes.append(
            ProjectionNode(
                group_id,
                group_id,
                SemanticObjectKind.GROUP,
                kind.value.replace("_", " ").title(),
                f"{len(group_members)} objects",
            )
        )
        for member in group_members:
            edges.append(
                ProjectionEdge(
                    f"projection-edge:{definition.id}:{kind.value}:{member.id}",
                    group_id,
                    member.id,
                    SemanticRelationKind.CONTAINS,
                    "groups",
                )
            )
