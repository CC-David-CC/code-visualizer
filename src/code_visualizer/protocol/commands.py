"""Explicit intentional commands translated to the existing authority envelope."""

from __future__ import annotations

from code_visualizer.application.commands import TypedCommand
from code_visualizer.application.domain_commands import (
    CreateDomainNode,
    DeleteDomainBundleReference,
    DeleteDomainConcept,
    DeleteDomainModel,
    DeleteDomainNode,
    DeleteDomainSchema,
    InsertDomainChild,
    MoveDomainChild,
    PromoteEvidenceObservation,
    PutDomainBundleReference,
    PutDomainConcept,
    PutDomainModel,
    PutDomainPropertyDefinition,
    PutDomainRoleDefinition,
    PutDomainSchema,
    RemoveDomainChild,
    RemoveDomainReference,
    SetDomainProperty,
    SetDomainReference,
)
from code_visualizer.application.messages import CommandEnvelope
from code_visualizer.domain.intentional import BundleReference
from code_visualizer.protocol.domain import (
    concept_from_proto,
    concept_to_proto,
    model_from_proto,
    model_to_proto,
    node_from_proto,
    node_to_proto,
    property_from_proto,
    property_to_proto,
    role_from_proto,
    role_to_proto,
    schema_from_proto,
    schema_to_proto,
)
from code_visualizer.protocol.evidence import evidence_from_proto, evidence_to_proto
from code_visualizer.protocol.v1 import command_pb2 as wire
from code_visualizer.protocol.v1.identity_pb2 import VersionedReference
from code_visualizer.protocol.validation import check_message, invalid, require_field
from code_visualizer.protocol.values import canonical_value_from_proto, canonical_value_to_proto


def command_to_proto(
    command: TypedCommand,
    *,
    actor_id: str,
    operation_id: str,
    project_id: str,
    expected_revision: int | None,
    transaction_id: str | None = None,
    intent: str = "",
) -> wire.CommandEnvelope:
    result = wire.CommandEnvelope(
        schema_version=1,
        actor_id=actor_id,
        operation_id=operation_id,
        project_id=project_id,
        intent=intent,
    )
    if expected_revision is not None:
        result.expected_revision = expected_revision
    if transaction_id is not None:
        result.transaction_id = transaction_id
    match command:
        case PutDomainSchema(schema):
            result.put_schema.CopyFrom(schema_to_proto(schema))
        case DeleteDomainSchema(schema_id):
            result.delete_schema_id = schema_id
        case PutDomainModel(model):
            result.put_model.CopyFrom(model_to_proto(model))
        case DeleteDomainModel(model_id):
            result.delete_model_id = model_id
        case PromoteEvidenceObservation(model_id, node_id, property_id, evidence, observation_id):
            result.promote_evidence.CopyFrom(
                wire.PromoteEvidence(
                    target=wire.PropertyAddress(
                        model_id=model_id, node_id=node_id, property_id=property_id
                    ),
                    evidence=evidence_to_proto(evidence),
                    observation_id=observation_id,
                )
            )
        case PutDomainConcept(schema_id, concept):
            result.put_concept.CopyFrom(
                wire.PutConcept(schema_id=schema_id, concept=concept_to_proto(concept))
            )
        case DeleteDomainConcept(schema_id, concept_id):
            result.delete_concept.CopyFrom(
                wire.DeleteConcept(schema_id=schema_id, concept_id=concept_id)
            )
        case PutDomainPropertyDefinition(schema_id, concept_id, definition):
            result.put_property_definition.CopyFrom(
                wire.PutPropertyDefinition(
                    schema_id=schema_id,
                    concept_id=concept_id,
                    definition=property_to_proto(definition),
                )
            )
        case PutDomainRoleDefinition(schema_id, concept_id, role_definition, containment):
            result.put_role_definition.CopyFrom(
                wire.PutRoleDefinition(
                    schema_id=schema_id,
                    concept_id=concept_id,
                    definition=role_to_proto(role_definition),
                    containment=containment,
                )
            )
        case CreateDomainNode(model_id, node, parent_id, role_id, index):
            result.create_node.CopyFrom(
                wire.CreateNode(model_id=model_id, node=node_to_proto(node))
            )
            if parent_id is not None:
                result.create_node.parent_id = parent_id
            if role_id is not None:
                result.create_node.role_id = role_id
            if index is not None:
                result.create_node.index = index
        case DeleteDomainNode(model_id, node_id):
            result.delete_node.CopyFrom(wire.NodeAddress(model_id=model_id, node_id=node_id))
        case SetDomainProperty(model_id, node_id, property_id, value):
            address = wire.PropertyAddress(
                model_id=model_id, node_id=node_id, property_id=property_id
            )
            if value is None:
                result.unset_property.CopyFrom(address)
            else:
                result.set_property.CopyFrom(
                    wire.SetProperty(target=address, value=canonical_value_to_proto(value))
                )
        case MoveDomainChild(model_id, node_id, parent_id, role_id, index):
            result.move_child.CopyFrom(
                wire.MoveChild(
                    target=wire.NodeAddress(model_id=model_id, node_id=node_id), index=index
                )
            )
            if parent_id is not None:
                result.move_child.parent_id = parent_id
            if role_id is not None:
                result.move_child.role_id = role_id
        case InsertDomainChild(model_id, node_id, parent_id, role_id, index):
            result.insert_child.CopyFrom(
                wire.MoveChild(
                    target=wire.NodeAddress(model_id=model_id, node_id=node_id),
                    parent_id=parent_id,
                    role_id=role_id,
                    index=index,
                )
            )
        case RemoveDomainChild(model_id, node_id):
            result.remove_child.CopyFrom(wire.NodeAddress(model_id=model_id, node_id=node_id))
        case SetDomainReference(model_id, node_id, role_id, target_ids):
            result.set_reference.CopyFrom(
                wire.SetReference(
                    target=wire.NodeAddress(model_id=model_id, node_id=node_id),
                    role_id=role_id,
                    target_ids=target_ids,
                )
            )
        case RemoveDomainReference(model_id, node_id, role_id, target_id):
            result.remove_reference.CopyFrom(
                wire.RemoveReference(
                    target=wire.NodeAddress(model_id=model_id, node_id=node_id), role_id=role_id
                )
            )
            if target_id is not None:
                result.remove_reference.target_id = target_id
        case PutDomainBundleReference(reference):
            result.put_bundle.CopyFrom(
                VersionedReference(id=reference.id, version=reference.version)
            )
        case DeleteDomainBundleReference(bundle_id, version):
            result.delete_bundle.CopyFrom(VersionedReference(id=bundle_id, version=version))
        case _:
            raise invalid("This command family has no version 1 protobuf representation")
    check_message(result, version=1)
    return result


def command_from_proto(value: wire.CommandEnvelope) -> CommandEnvelope:
    check_message(value, version=value.schema_version)
    if not value.actor_id or not value.operation_id or not value.project_id:
        raise invalid("Command actor, operation and project identities are required")
    kind = value.WhichOneof("command")
    command: TypedCommand
    if kind == "put_schema":
        command = PutDomainSchema(schema_from_proto(value.put_schema))
    elif kind == "delete_schema_id":
        command = DeleteDomainSchema(value.delete_schema_id)
    elif kind == "put_model":
        command = PutDomainModel(model_from_proto(value.put_model))
    elif kind == "delete_model_id":
        command = DeleteDomainModel(value.delete_model_id)
    elif kind == "promote_evidence":
        promotion = value.promote_evidence
        require_field(promotion, "target")
        require_field(promotion, "evidence")
        command = PromoteEvidenceObservation(
            promotion.target.model_id,
            promotion.target.node_id,
            promotion.target.property_id,
            evidence_from_proto(promotion.evidence),
            promotion.observation_id,
        )
    elif kind == "put_concept":
        require_field(value.put_concept, "concept")
        command = PutDomainConcept(
            value.put_concept.schema_id, concept_from_proto(value.put_concept.concept)
        )
    elif kind == "delete_concept":
        command = DeleteDomainConcept(
            value.delete_concept.schema_id, value.delete_concept.concept_id
        )
    elif kind == "put_property_definition":
        p = value.put_property_definition
        require_field(p, "definition")
        command = PutDomainPropertyDefinition(
            p.schema_id, p.concept_id, property_from_proto(p.definition)
        )
    elif kind == "put_role_definition":
        r = value.put_role_definition
        require_field(r, "definition")
        command = PutDomainRoleDefinition(
            r.schema_id, r.concept_id, role_from_proto(r.definition), r.containment
        )
    elif kind == "create_node":
        c = value.create_node
        require_field(c, "node")
        command = CreateDomainNode(
            c.model_id,
            node_from_proto(c.node),
            c.parent_id if c.HasField("parent_id") else None,
            c.role_id if c.HasField("role_id") else None,
            c.index if c.HasField("index") else None,
        )
    elif kind == "delete_node":
        command = DeleteDomainNode(value.delete_node.model_id, value.delete_node.node_id)
    elif kind == "set_property":
        s = value.set_property
        require_field(s, "target")
        require_field(s, "value")
        command = SetDomainProperty(
            s.target.model_id,
            s.target.node_id,
            s.target.property_id,
            canonical_value_from_proto(s.value),
        )
    elif kind == "unset_property":
        u = value.unset_property
        command = SetDomainProperty(u.model_id, u.node_id, u.property_id, None)
    elif kind == "move_child":
        m = value.move_child
        require_field(m, "target")
        command = MoveDomainChild(
            m.target.model_id,
            m.target.node_id,
            m.parent_id if m.HasField("parent_id") else None,
            m.role_id if m.HasField("role_id") else None,
            m.index,
        )
    elif kind == "insert_child":
        m = value.insert_child
        require_field(m, "target")
        require_field(m, "parent_id")
        require_field(m, "role_id")
        command = InsertDomainChild(
            m.target.model_id, m.target.node_id, m.parent_id, m.role_id, m.index
        )
    elif kind == "remove_child":
        command = RemoveDomainChild(value.remove_child.model_id, value.remove_child.node_id)
    elif kind == "set_reference":
        ref = value.set_reference
        require_field(ref, "target")
        command = SetDomainReference(
            ref.target.model_id, ref.target.node_id, ref.role_id, tuple(ref.target_ids)
        )
    elif kind == "remove_reference":
        rem = value.remove_reference
        require_field(rem, "target")
        command = RemoveDomainReference(
            rem.target.model_id,
            rem.target.node_id,
            rem.role_id,
            rem.target_id if rem.HasField("target_id") else None,
        )
    elif kind == "put_bundle":
        command = PutDomainBundleReference(
            BundleReference(value.put_bundle.id, value.put_bundle.version)
        )
    elif kind == "delete_bundle":
        command = DeleteDomainBundleReference(value.delete_bundle.id, value.delete_bundle.version)
    elif kind in {"undo", "redo"}:
        return CommandEnvelope(
            f"history.{kind}",
            value.actor_id,
            value.operation_id,
            value.project_id,
            value.expected_revision if value.HasField("expected_revision") else None,
            {},
            transaction_id=value.transaction_id if value.HasField("transaction_id") else None,
            intent=value.intent,
        )
    else:
        raise invalid("Command must select a supported version 1 command variant")
    operation = command.to_operation()
    return CommandEnvelope(
        operation.command_type,
        value.actor_id,
        value.operation_id,
        value.project_id,
        value.expected_revision if value.HasField("expected_revision") else None,
        operation.payload,
        transaction_id=value.transaction_id if value.HasField("transaction_id") else None,
        intent=value.intent,
    )
