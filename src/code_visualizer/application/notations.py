"""Compile editable notations and translate explicit cell intent to commands."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from code_visualizer.application.domain_commands import SetDomainProperty, SetDomainReference
from code_visualizer.application.domain_index import domain_relation_id
from code_visualizer.domain.intentional import (
    DomainModel,
    DomainSchema,
    DomainValue,
    DomainWorkspace,
    IntentionalNode,
    PropertyDefinition,
    RoleDefinition,
    node_label,
)
from code_visualizer.domain.notation import (
    NotationColumn,
    NotationDefinition,
    NotationField,
    NotationKind,
)
from code_visualizer.domain.semantic import (
    ProjectionEdge,
    ProjectionKind,
    ProjectionNode,
    SemanticObjectKind,
    SemanticProjection,
    SemanticRelationKind,
)

if TYPE_CHECKING:
    from code_visualizer.application.notation_canvas import NotationCanvas


class NotationEditKind(StrEnum):
    PROPERTY = "property"
    REFERENCE = "reference"


@dataclass(frozen=True, slots=True)
class NotationEditBinding:
    model_id: str
    node_id: str
    field_id: str
    kind: NotationEditKind
    revision: int
    property_definition: PropertyDefinition | None = None
    role_definition: RoleDefinition | None = None
    allowed_target_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NotationCell:
    id: str
    semantic_id: str
    text: str
    value: DomainValue | None = None
    target_ids: tuple[str, ...] = ()
    edit: NotationEditBinding | None = None


@dataclass(frozen=True, slots=True)
class NotationRow:
    node_id: str
    cells: tuple[NotationCell, ...]
    active: bool = False
    badges: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NotationTreeNode:
    node_id: str
    label: str
    children: tuple[NotationTreeNode, ...] = ()
    role_id: str | None = None
    active: bool = False
    badges: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NotationProjection:
    definition: NotationDefinition
    model_id: str
    revision: int
    graph: SemanticProjection
    columns: tuple[NotationColumn, ...]
    rows: tuple[NotationRow, ...]
    roots: tuple[NotationTreeNode, ...]
    runtime_revision: int | None = None
    canvas: NotationCanvas | None = None


def fallback_notations(schema: DomainSchema) -> tuple[NotationDefinition, ...]:
    """Every valid schema gets editable graph, property table, and tree/form views."""

    definitions = [
        NotationDefinition(
            f"notation:{schema.id}:graph",
            "Object graph",
            NotationKind.GRAPH,
            schema_id=schema.id,
        ),
        NotationDefinition(
            f"notation:{schema.id}:tree",
            "Hierarchy and form",
            NotationKind.TREE_FORM,
            schema_id=schema.id,
        ),
    ]
    for concept in schema.concepts:
        columns = [
            NotationColumn(prop.id, prop.name, NotationField(prop.id))
            for prop in concept.properties
        ]
        columns.extend(
            NotationColumn(role.id, role.name, NotationField(reference_role_ids=(role.id,)))
            for role in concept.reference_roles
        )
        definitions.append(
            NotationDefinition(
                f"notation:{schema.id}:table:{concept.id}",
                f"{concept.name} table",
                NotationKind.TABLE,
                concept_ids=(concept.id,),
                columns=tuple(columns),
                schema_id=schema.id,
            )
        )
    return tuple(definitions)


def field_cell(
    schema: DomainSchema,
    model: DomainModel,
    node: IntentionalNode,
    field: NotationField,
    *,
    cell_id: str,
    revision: int,
    editable: bool = True,
    workspace: DomainWorkspace | None = None,
) -> NotationCell:
    """Resolve a bounded reference path to one explicit semantic edit target.

    A property terminal edits the resolved object's property. A reference terminal
    edits the final role on its owner. Ambiguous property paths are read-only.
    """

    models = workspace.models if workspace is not None else (model,)
    indexed = {value.id: (owner, value) for owner in models for value in owner.nodes}

    def owner_schema(owner: DomainModel) -> DomainSchema:
        return (workspace.schema(owner.schema_id) if workspace is not None else None) or schema

    current: tuple[tuple[DomainModel, IntentionalNode], ...] = ((model, node),)
    reference_terminal = field.property_id is None and bool(field.reference_role_ids)
    traversed = field.reference_role_ids[:-1] if reference_terminal else field.reference_role_ids
    for role_id in traversed:
        current = tuple(
            target
            for _model, owner in current
            for target_id in owner.reference_ids(role_id)
            if (target := indexed.get(target_id)) is not None
        )
    if len(current) != 1:
        return NotationCell(
            cell_id,
            node.id,
            " / ".join(node_label(owner_schema(owner), item) for owner, item in current),
        )
    owning_model, owner = current[0]
    resolved_schema = owner_schema(owning_model)
    concept = resolved_schema.concept(owner.concept_id)
    if concept is None:
        return NotationCell(cell_id, owner.id, "Unknown concept")
    if reference_terminal:
        role_id = field.reference_role_ids[-1]
        role = next((item for item in concept.reference_roles if item.id == role_id), None)
        targets = owner.reference_ids(role_id)
        labels = tuple(
            node_label(owner_schema(target[0]), target[1])
            if (target := indexed.get(target_id)) is not None
            else f"Missing: {target_id}"
            for target_id in targets
        )
        binding = (
            None
            if role is None or not editable
            else NotationEditBinding(
                owning_model.id,
                owner.id,
                role.id,
                NotationEditKind.REFERENCE,
                revision,
                role_definition=role,
                allowed_target_ids=tuple(
                    item.id
                    for candidate in models
                    for item in candidate.nodes
                    if item.concept_id in role.allowed_concept_ids
                ),
            )
        )
        return NotationCell(cell_id, owner.id, ", ".join(labels), target_ids=targets, edit=binding)
    property_id = field.property_id or concept.display_property_id
    prop = concept.property(property_id) if property_id is not None else None
    if prop is None:
        return NotationCell(cell_id, owner.id, node_label(resolved_schema, owner))
    value = owner.property(prop.id)
    if value is None:
        value = prop.default
    binding = (
        None
        if not editable
        else NotationEditBinding(
            owning_model.id,
            owner.id,
            prop.id,
            NotationEditKind.PROPERTY,
            revision,
            property_definition=prop,
        )
    )
    return NotationCell(cell_id, owner.id, "" if value is None else str(value), value, edit=binding)


def notation_node_label(
    schema: DomainSchema,
    model: DomainModel,
    node: IntentionalNode,
    definition: NotationDefinition,
    revision: int,
    *,
    workspace: DomainWorkspace | None = None,
) -> str:
    rule = next(
        (item for item in definition.node_rules if item.concept_id == node.concept_id), None
    )
    label_fields = (
        rule.label_fields
        if rule and rule.label_fields
        else (NotationField(rule.label_property_id if rule else None),)
    )
    return " / ".join(
        filter(
            None,
            (
                field_cell(
                    schema,
                    model,
                    node,
                    field,
                    cell_id=node.id,
                    revision=revision,
                    editable=False,
                    workspace=workspace,
                ).text
                for field in label_fields
            ),
        )
    ) or node_label(schema, node)


def notation_edit_command(
    binding: NotationEditBinding,
    value: DomainValue | tuple[str, ...] | None,
    *,
    revision: int,
) -> SetDomainProperty | SetDomainReference:
    """Reject a stale displayed affordance instead of editing a newly resolved path."""

    if binding.revision != revision:
        raise ValueError("The model changed. Refresh this field before applying the edit.")
    if binding.kind is NotationEditKind.REFERENCE:
        if not isinstance(value, tuple):
            raise ValueError("Reference edits require explicit target identities")
        return SetDomainReference(binding.model_id, binding.node_id, binding.field_id, value)
    if isinstance(value, tuple):
        raise ValueError("A property needs a scalar value")
    return SetDomainProperty(binding.model_id, binding.node_id, binding.field_id, value)


def compile_notation(
    project_id: str,
    revision: int,
    schema: DomainSchema,
    model: DomainModel,
    definition: NotationDefinition,
    *,
    active_node_ids: tuple[str, ...] = (),
    runtime_revision: int | None = None,
    workspace: DomainWorkspace | None = None,
) -> NotationProjection:
    if model.schema_id != schema.id or definition.schema_id not in {None, schema.id}:
        raise ValueError("Notation, model, and schema must belong to the same domain")
    active = frozenset(active_node_ids)
    selected = tuple(
        item
        for item in model.nodes
        if not definition.concept_ids or item.concept_id in definition.concept_ids
    )
    rows = tuple(
        NotationRow(
            node.id,
            tuple(
                field_cell(
                    schema,
                    model,
                    node,
                    column.field,
                    cell_id=f"{definition.id}:{node.id}:{column.id}",
                    revision=revision,
                    editable=column.editable,
                    workspace=workspace,
                )
                for column in definition.columns
            ),
            node.id in active,
        )
        for node in selected
    )
    node_rules = {item.concept_id: item for item in definition.node_rules}
    graph_nodes = tuple(
        node for node in selected if not node_rules or node.concept_id in node_rules
    )
    nodes = []
    for node in graph_nodes:
        concept = schema.concept(node.concept_id)
        badge = "runtime stale" if runtime_revision not in {None, revision} else "active"
        nodes.append(
            ProjectionNode(
                node.id,
                node.id,
                SemanticObjectKind.INTENTION,
                notation_node_label(schema, model, node, definition, revision, workspace=workspace),
                "" if concept is None else concept.name,
                badges=(badge,) if node.id in active else (),
            )
        )
    visible = {item.id for item in nodes}
    edges = []
    if definition.edge_rules:
        for edge_rule in definition.edge_rules:
            for node in model.nodes:
                if node.concept_id != edge_rule.concept_id:
                    continue
                sources = node.reference_ids(edge_rule.source_role_id)
                targets = node.reference_ids(edge_rule.target_role_id)
                if len(sources) != 1 or len(targets) != 1:
                    continue
                if sources[0] not in visible or targets[0] not in visible:
                    continue
                label = " / ".join(
                    filter(
                        None,
                        (
                            field_cell(
                                schema,
                                model,
                                node,
                                field,
                                cell_id=node.id,
                                revision=revision,
                                editable=False,
                                workspace=workspace,
                            ).text
                            for field in edge_rule.label_fields
                        ),
                    )
                )
                edges.append(
                    ProjectionEdge(
                        node.id,
                        sources[0],
                        targets[0],
                        SemanticRelationKind.REFERENCES,
                        label,
                        node.id in active,
                    )
                )
    else:
        for node in graph_nodes:
            concept = schema.concept(node.concept_id)
            for bindings, kind in (
                (node.children, SemanticRelationKind.CONTAINS),
                (node.references, SemanticRelationKind.REFERENCES),
            ):
                for binding in bindings:
                    role = concept.role(binding.role_id) if concept else None
                    for target_id in binding.node_ids:
                        if target_id in visible:
                            edges.append(
                                ProjectionEdge(
                                    domain_relation_id(kind, node.id, target_id, binding.role_id),
                                    node.id,
                                    target_id,
                                    kind,
                                    role.name if role else binding.role_id,
                                )
                            )
    seen: set[str] = set()

    def tree(node_id: str, role_id: str | None = None) -> NotationTreeNode | None:
        node = model.node(node_id)
        if node is None or node_id in seen:
            return None
        seen.add(node_id)
        children = tuple(
            child
            for binding in node.children
            for target_id in binding.node_ids
            if (child := tree(target_id, binding.role_id)) is not None
        )
        return NotationTreeNode(
            node.id,
            notation_node_label(schema, model, node, definition, revision, workspace=workspace),
            children,
            role_id,
            node.id in active,
        )

    roots = tuple(item for root_id in model.roots if (item := tree(root_id)) is not None)
    # Incomplete imports remain inspectable even before their roots are repaired.
    roots += tuple(item for node in model.nodes if (item := tree(node.id)) is not None)
    graph = SemanticProjection(
        ProjectionKind.COMPOSED,
        project_id,
        revision,
        model.id,
        tuple(nodes),
        tuple(edges),
        definition.id,
        definition.title,
        definition.layout,
    )
    return NotationProjection(
        definition, model.id, revision, graph, definition.columns, rows, roots, runtime_revision
    )
