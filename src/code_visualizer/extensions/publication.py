"""Explicit public extension publication at the trusted composition boundary."""

from __future__ import annotations

from dataclasses import fields, is_dataclass

from code_visualizer.domain.identifiers import (
    BundlePublication,
    ContractDefinition,
    ContractKind,
    ContractReference,
    NamespaceGrant,
    NamespaceOwnership,
    PublicationManifest,
    validate_contract_version,
)
from code_visualizer.domain.intentional import (
    BundleReference,
    DomainSchema,
    PropertyDefinition,
    PropertyValue,
)
from code_visualizer.domain.transformation import Representation, TransformationDefinition
from code_visualizer.domain.value_contracts import value_contract_reference
from code_visualizer.domain.values import validate_canonical_value
from code_visualizer.extensions.registry import DomainExtensionBundle, DomainExtensionRegistry

FIRST_PARTY_OWNER = "org.codevisualizer"
FIRST_PARTY_OWNERSHIP = NamespaceOwnership(
    (
        NamespaceGrant("foundation", FIRST_PARTY_OWNER),
        NamespaceGrant("code_visualizer", FIRST_PARTY_OWNER),
        NamespaceGrant("org.codevisualizer", FIRST_PARTY_OWNER),
    )
)
FIRST_PARTY_PUBLICATION = BundlePublication(FIRST_PARTY_OWNER)


def derive_public_contract_references(
    bundle: DomainExtensionBundle,
    *,
    schemas: tuple[DomainSchema, ...] = (),
    require_schema_resolution: bool = False,
) -> tuple[ContractReference, ...]:
    """Inspect inert contributions, never implementations or callback closures.

    Opaque schema/concept/property/role IDs are resolved through their actual
    schema owners; their spelling is never interpreted as a namespace. Assembly
    validates syntax before all dependencies are present. Publication supplies
    its exact dependency schemas and requires every schema scope to resolve.
    """
    available_schemas = tuple(dict.fromkeys((*bundle.schemas, *schemas)))
    references: set[ContractReference] = set()
    visited: set[int] = set()
    owners: dict[str, list[DomainSchema]] = {}
    for schema in available_schemas:
        identities = (
            schema.id,
            *(concept.id for concept in schema.concepts),
            *(prop.id for concept in schema.concepts for prop in concept.properties),
            *(
                role.id
                for concept in schema.concepts
                for role in (*concept.containment_roles, *concept.reference_roles)
            ),
        )
        for identity in identities:
            owners.setdefault(identity, []).append(schema)

    def schema_reference(
        identity: str, version: str | None, scope: DomainSchema | None = None
    ) -> DomainSchema | None:
        if version is not None:
            validate_contract_version(version)
        candidates = [
            schema
            for schema in owners.get(identity, ())
            if version is None or schema.version == version
        ]
        if scope is not None and scope in candidates:
            candidates = [scope]
        if len(candidates) != 1:
            if require_schema_resolution:
                problem = "Ambiguous" if candidates else "Missing"
                raise ValueError(f"{problem} published schema scope {identity!r}@{version!r}")
            return None
        schema = candidates[0]
        references.add(
            ContractReference(ContractKind.SCHEMA_NAMESPACE, schema.namespace, schema.version)
        )
        return schema

    def visit(value: object, scope: DomainSchema | None = None) -> None:
        # Scalar leaves cannot contain a typed public reference. Avoid walking
        # their Python implementation for every label in the installed catalog.
        if value is None or type(value) in (str, int, float, bool, bytes):
            return
        if callable(value) or isinstance(value, (ContractDefinition, BundlePublication)):
            return
        if isinstance(value, ContractReference):
            references.add(value)
        elif isinstance(value, Representation):
            references.add(ContractReference(ContractKind.REPRESENTATION, value.id, value.version))
        elif isinstance(value, BundleReference):
            references.add(ContractReference(ContractKind.BUNDLE, value.id, value.version))
        elif (value_reference := value_contract_reference(value)) is not None:
            references.add(value_reference)
        elif isinstance(value, TransformationDefinition):
            for dependency in value.depends_on:
                identity, separator, version = dependency.rpartition("@")
                if not separator:
                    raise ValueError("Public transformation dependencies require an exact version")
                references.add(ContractReference(ContractKind.TRANSFORMATION, identity, version))
        if isinstance(value, PropertyDefinition):
            if value.default is not None:
                validate_canonical_value(value.default)
            for choice in value.choices:
                validate_canonical_value(choice)
        elif isinstance(value, PropertyValue):
            validate_canonical_value(value.value)
        if isinstance(value, tuple):
            for child in value:
                visit(child, scope)
        elif is_dataclass(value) and not isinstance(value, type):
            # Shared immutable values may occur in different schema scopes. Only
            # guard the current path; no reference use disappears through reuse.
            if id(value) in visited:
                raise ValueError("Published contribution data must be acyclic")
            visited.add(id(value))
            if isinstance(value, DomainSchema):
                scope = value
            data = {field.name: getattr(value, field.name) for field in fields(value)}
            for name, version_name in (
                ("schema_id", "schema_version"),
                ("target_schema_id", "target_schema_version"),
            ):
                schema_identity = data.get(name)
                schema_version = data.get(version_name)
                if schema_version is not None:
                    validate_contract_version(schema_version)
                if isinstance(schema_identity, str) and schema_identity:
                    resolved = schema_reference(schema_identity, schema_version, scope)
                    if name == "schema_id" and resolved is not None:
                        scope = resolved
            for name in (
                "concept_id",
                "property_id",
                "role_id",
                "source_role_id",
                "target_role_id",
                "label_property_id",
                "display_property_id",
            ):
                field_identity = data.get(name)
                if isinstance(field_identity, str) and field_identity:
                    schema_reference(field_identity, None, scope)
            for name in ("concept_ids", "allowed_concept_ids", "reference_role_ids"):
                identities = data.get(name)
                if isinstance(identities, tuple):
                    for identity in identities:
                        if isinstance(identity, str) and identity:
                            schema_reference(identity, None, scope)
            for child in data.values():
                visit(child, scope)
            visited.remove(id(value))

    visit(bundle)
    return tuple(sorted(references, key=lambda reference: reference.sort_key))


def publication_manifest(
    registry: DomainExtensionRegistry, bundle_id: str, version: str
) -> PublicationManifest:
    contracts = registry.publication_contracts(bundle_id, version)
    bundle = registry.get(bundle_id, version)
    assert bundle is not None and bundle.publication is not None
    references = registry.validate_publication_closure(BundleReference(bundle_id, version))
    return PublicationManifest(
        ContractDefinition(ContractKind.BUNDLE, bundle_id, version),
        bundle.publication,
        contracts,
        tuple(
            sorted(
                ContractDefinition(ContractKind.BUNDLE, item.id, item.version)
                for item in bundle.required_bundles
            )
        ),
        references,
    )
