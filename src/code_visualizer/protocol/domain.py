"""Schema and object contracts, independent of ProgramModel's native syntax."""

from code_visualizer.domain.intentional import (
    BundleReference,
    ConceptDefinition,
    ConstraintDefinition,
    ConstraintKind,
    DomainModel,
    DomainSchema,
    IntentionalNode,
    PropertyDefinition,
    PropertyValue,
    RoleBinding,
    RoleDefinition,
    ValueKind,
)
from code_visualizer.protocol.v1 import domain_pb2 as wire
from code_visualizer.protocol.v1.identity_pb2 import VersionedReference
from code_visualizer.protocol.validation import check_message, require_field
from code_visualizer.protocol.values import (
    canonical_value_from_proto,
    canonical_value_to_proto,
    constraints_from_proto,
    constraints_to_proto,
)


def property_to_proto(value: PropertyDefinition) -> wire.PropertyDefinition:
    result = wire.PropertyDefinition(
        id=value.id,
        name=value.name,
        value_kind=value.value_kind.value,
        required=value.required,
        choices=[canonical_value_to_proto(item) for item in value.choices],
        value_constraints=constraints_to_proto(value.value_constraints),
    )
    if value.default is not None:
        result.default_value.CopyFrom(canonical_value_to_proto(value.default))
    if value.minimum is not None:
        result.minimum = value.minimum
    if value.maximum is not None:
        result.maximum = value.maximum
    return result


def property_from_proto(value: wire.PropertyDefinition) -> PropertyDefinition:
    check_message(value)
    return PropertyDefinition(
        value.id,
        value.name,
        ValueKind(value.value_kind),
        value.required,
        canonical_value_from_proto(value.default_value)
        if value.HasField("default_value")
        else None,
        tuple(canonical_value_from_proto(item) for item in value.choices),
        value.minimum if value.HasField("minimum") else None,
        value.maximum if value.HasField("maximum") else None,
        constraints_from_proto(value.value_constraints),
    )


def role_to_proto(value: RoleDefinition) -> wire.RoleDefinition:
    result = wire.RoleDefinition(
        id=value.id,
        name=value.name,
        allowed_concept_ids=value.allowed_concept_ids,
        min_count=value.min_count,
        ordered=value.ordered,
    )
    if value.max_count is not None:
        result.max_count = value.max_count
    return result


def role_from_proto(value: wire.RoleDefinition) -> RoleDefinition:
    check_message(value)
    return RoleDefinition(
        value.id,
        value.name,
        tuple(value.allowed_concept_ids),
        value.min_count,
        value.max_count if value.HasField("max_count") else None,
        value.ordered,
    )


def concept_to_proto(value: ConceptDefinition) -> wire.ConceptDefinition:
    result = wire.ConceptDefinition(
        id=value.id,
        name=value.name,
        properties=[property_to_proto(p) for p in value.properties],
        containment_roles=[role_to_proto(r) for r in value.containment_roles],
        reference_roles=[role_to_proto(r) for r in value.reference_roles],
        description=value.description,
    )
    if value.display_property_id is not None:
        result.display_property_id = value.display_property_id
    for constraint in value.constraints:
        item = result.constraints.add(
            id=constraint.id, kind=constraint.kind.value, property_id=constraint.property_id
        )
        if constraint.role_id is not None:
            item.role_id = constraint.role_id
    return result


def concept_from_proto(value: wire.ConceptDefinition) -> ConceptDefinition:
    check_message(value)
    return ConceptDefinition(
        value.id,
        value.name,
        tuple(property_from_proto(p) for p in value.properties),
        tuple(role_from_proto(r) for r in value.containment_roles),
        tuple(role_from_proto(r) for r in value.reference_roles),
        tuple(
            ConstraintDefinition(
                c.id,
                ConstraintKind(c.kind),
                c.property_id,
                c.role_id if c.HasField("role_id") else None,
            )
            for c in value.constraints
        ),
        value.display_property_id if value.HasField("display_property_id") else None,
        value.description,
    )


def schema_to_proto(value: DomainSchema) -> wire.DomainSchema:
    result = wire.DomainSchema(
        schema_version=1,
        id=value.id,
        namespace=value.namespace,
        version=value.version,
        concepts=[concept_to_proto(c) for c in value.concepts],
        description=value.description,
    )
    if value.bundle is not None:
        result.bundle.CopyFrom(VersionedReference(id=value.bundle.id, version=value.bundle.version))
    check_message(result, version=1)
    return result


def schema_from_proto(value: wire.DomainSchema) -> DomainSchema:
    check_message(value, version=value.schema_version)
    return DomainSchema(
        value.id,
        value.namespace,
        value.version,
        tuple(concept_from_proto(c) for c in value.concepts),
        BundleReference(value.bundle.id, value.bundle.version)
        if value.HasField("bundle")
        else None,
        value.description,
    )


def node_to_proto(value: IntentionalNode) -> wire.IntentionalNode:
    return wire.IntentionalNode(
        schema_version=1,
        id=value.id,
        concept_id=value.concept_id,
        properties=[
            wire.PropertyValue(property_id=p.property_id, value=canonical_value_to_proto(p.value))
            for p in value.properties
        ],
        children=[wire.RoleBinding(role_id=r.role_id, node_ids=r.node_ids) for r in value.children],
        references=[
            wire.RoleBinding(role_id=r.role_id, node_ids=r.node_ids) for r in value.references
        ],
    )


def node_from_proto(value: wire.IntentionalNode) -> IntentionalNode:
    check_message(value, version=value.schema_version)
    for prop in value.properties:
        require_field(prop, "value")
    return IntentionalNode(
        value.id,
        value.concept_id,
        tuple(
            PropertyValue(p.property_id, canonical_value_from_proto(p.value))
            for p in value.properties
        ),
        tuple(RoleBinding(r.role_id, tuple(r.node_ids)) for r in value.children),
        tuple(RoleBinding(r.role_id, tuple(r.node_ids)) for r in value.references),
    )


def model_to_proto(value: DomainModel) -> wire.DomainModel:
    result = wire.DomainModel(
        schema_version=1,
        id=value.id,
        schema=VersionedReference(id=value.schema_id, version=value.schema_version),
        roots=value.roots,
        nodes=[node_to_proto(n) for n in value.nodes],
        title=value.title,
    )
    check_message(result, version=1)
    return result


def model_from_proto(value: wire.DomainModel) -> DomainModel:
    check_message(value, version=value.schema_version)
    require_field(value, "schema")
    return DomainModel(
        value.id,
        value.schema.id,
        value.schema.version,
        tuple(value.roots),
        tuple(node_from_proto(n) for n in value.nodes),
        value.title,
    )
