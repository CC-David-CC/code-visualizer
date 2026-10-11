"""Resolve registered schema dependencies before one ordinary authority transaction."""

from code_visualizer.application.commands import TypedCommand
from code_visualizer.application.domain_commands import (
    PutDomainBundleReference,
    PutDomainModel,
    PutDomainSchema,
)
from code_visualizer.domain.intentional import BundleReference, DomainSchema, DomainWorkspace
from code_visualizer.extensions.registry import DomainExtensionRegistry


def schema_installation(
    workspace: DomainWorkspace,
    available: tuple[DomainSchema, ...],
    schema_id: str,
    *,
    version: str | None = None,
    registry: DomainExtensionRegistry | None = None,
) -> tuple[DomainSchema, ...]:
    candidates = tuple(
        schema
        for schema in available
        if schema.id == schema_id and (version is None or schema.version == version)
    )
    if len(candidates) != 1:
        raise ValueError("Select one explicit available schema version")
    root = candidates[0]
    if root.bundle is not None:
        if registry is None:
            from code_visualizer.extensions.builtin import builtin_registry

            registry = builtin_registry()
        bundle_owner = registry.get(root.bundle.id, root.bundle.version)
        if bundle_owner is not None and root in bundle_owner.schemas:
            # Dependencies are declared by the exact owning bundle. In particular,
            # a released foundation must not acquire a newer math schema because
            # another version happened to be registered later.
            closure = registry.bundle_closure(root.bundle)
            available = tuple(schema for bundle in closure for schema in bundle.schemas)
    versions: dict[str, str] = {}
    for available_schema in available:
        if (
            versions.setdefault(available_schema.id, available_schema.version)
            != available_schema.version
        ):
            raise ValueError("Schema dependency versions are ambiguous")
        previous = workspace.schema(available_schema.id)
        if previous is not None and previous != available_schema:
            raise ValueError("Installed schema differs from its required definition")
    schemas = {schema.id: schema for schema in available}
    owners = {concept.id: schema.id for schema in available for concept in schema.concepts}
    existing = {concept.id for schema in workspace.schemas for concept in schema.concepts}
    pending = [schema_id]
    selected: dict[str, DomainSchema] = {}
    while pending:
        requested = pending.pop()
        if workspace.schema(requested) is not None or requested in selected:
            continue
        schema = schemas.get(requested)
        if schema is None:
            raise ValueError(f"Required registered schema {requested!r} is unavailable")
        selected[requested] = schema
        local = {concept.id for concept in schema.concepts}
        for concept in schema.concepts:
            for role in concept.reference_roles:
                for target in role.allowed_concept_ids:
                    if target in local or target in existing:
                        continue
                    owner = owners.get(target)
                    if owner is None:
                        raise ValueError(f"Required concept {target!r} has no registered schema")
                    pending.append(owner)
    return tuple(selected[key] for key in sorted(selected))


def bundle_installation(
    workspace: DomainWorkspace, registry: DomainExtensionRegistry, reference: BundleReference
) -> tuple[TypedCommand, ...]:
    """Install schemas and immutable reference data through the existing transaction API."""
    closure = registry.bundle_closure(reference)
    available = tuple(schema for bundle in closure for schema in bundle.schemas)
    versions: dict[str, str] = {}
    for schema in available:
        if versions.setdefault(schema.id, schema.version) != schema.version:
            raise ValueError("A bundle closure cannot install two versions of one schema")
    schemas: dict[str, DomainSchema] = {}
    for bundle in closure:
        for schema in bundle.schemas:
            previous = workspace.schema(schema.id)
            if previous is not None and previous != schema:
                raise ValueError("Installed schema differs from its exact bundle definition")
            for needed in schema_installation(
                workspace, available, schema.id, version=schema.version, registry=registry
            ):
                schemas[needed.id] = needed
    operations: list[TypedCommand] = [PutDomainSchema(schemas[key]) for key in sorted(schemas)]
    for bundle in closure:
        for model in sorted(bundle.reference_models, key=lambda item: item.id):
            previous_model = workspace.model(model.id)
            if previous_model is not None and previous_model != model:
                raise ValueError("Installed reference model differs from its bundle definition")
            if previous_model is None:
                operations.append(PutDomainModel(model))
        required = BundleReference(bundle.id, bundle.version)
        if required not in workspace.bundle_references:
            operations.append(PutDomainBundleReference(required))
    return tuple(operations)
