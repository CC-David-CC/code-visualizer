"""Disposable validation contexts for explicit computation dependencies."""

from __future__ import annotations

from dataclasses import replace

from code_visualizer.domain.intentional import DomainModel, DomainWorkspace
from code_visualizer.domain.project import Project
from code_visualizer.generation.transformation import TransformationError


def computation_scope(
    project: Project, model_id: str | None, *, schema_ids: tuple[str, ...] = ()
) -> Project:
    """Retain selected objects/references and their schemas, never a copied author store.

    Global structural integrity must be checked on the original snapshot first.
    This derived context limits executable completeness/extension diagnostics.
    Programming contributions remain whole: Python's dynamic dependencies are not
    guessed by inspecting a few syntactic loads.
    """
    workspace = project.domain_workspace
    owners = {node.id: model for model in workspace.models for node in model.nodes}
    selected: set[str] = set()
    pending: list[str] = []
    if model_id is not None:
        root = workspace.model(model_id)
        if root is None:
            raise TransformationError("COMPUTATION_ROOT", "Requested domain model is absent")
        pending.extend(node.id for node in root.nodes)
    while pending:
        identity = pending.pop()
        if identity in selected:
            continue
        owner = owners.get(identity)
        if owner is None:
            raise TransformationError("COMPUTATION_REFERENCE", "An input reference is absent")
        node = owner.node(identity)
        assert node is not None
        selected.add(identity)
        pending.extend(
            target for role in (*node.children, *node.references) for target in role.node_ids
        )
    models: list[DomainModel] = []
    for model in workspace.models:
        nodes = tuple(node for node in model.nodes if node.id in selected)
        if nodes or model.id == model_id:
            if len(nodes) == len(model.nodes):
                models.append(model)
                continue
            owned = {target for node in nodes for role in node.children for target in role.node_ids}
            models.append(
                replace(
                    model,
                    nodes=nodes,
                    roots=tuple(node.id for node in nodes if node.id not in owned),
                )
            )
    required = {model.schema_id for model in models} | set(schema_ids)
    concept_owners = {
        concept.id: schema.id for schema in workspace.schemas for concept in schema.concepts
    }
    pending_schemas = sorted(required)
    while pending_schemas:
        schema = workspace.schema(pending_schemas.pop())
        if schema is None:
            raise TransformationError("COMPUTATION_SCHEMA", "A required schema is absent")
        for concept in schema.concepts:
            for role in (*concept.containment_roles, *concept.reference_roles):
                for identity in role.allowed_concept_ids:
                    owner_id = concept_owners.get(identity)
                    if owner_id is not None and owner_id not in required:
                        required.add(owner_id)
                        pending_schemas.append(owner_id)
    schemas = tuple(schema for schema in workspace.schemas if schema.id in required)
    languages = tuple(
        language for language in workspace.language_definitions if language.schema_id in required
    )
    bundles = tuple(
        sorted(
            {schema.bundle for schema in schemas if schema.bundle is not None},
            key=lambda item: (item.id, item.version),
        )
    )
    return replace(
        project, domain_workspace=DomainWorkspace(schemas, tuple(models), bundles, languages)
    )
