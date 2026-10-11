"""Typed intentional edits submitted to the existing ProjectAuthority."""

from dataclasses import dataclass

from code_visualizer.application.commands import Operation
from code_visualizer.domain.evidence import ComputationEvidence
from code_visualizer.domain.intentional import (
    BundleReference,
    ConceptDefinition,
    DomainModel,
    DomainSchema,
    DomainValue,
    IntentionalNode,
    PropertyDefinition,
    RoleDefinition,
)
from code_visualizer.persistence.evidence import evidence_to_data
from code_visualizer.persistence.intentional import (
    bundle_to_data,
    concept_definition_to_data,
    domain_model_to_data,
    domain_schema_to_data,
    intentional_node_to_data,
    property_definition_to_data,
    role_definition_to_data,
)
from code_visualizer.persistence.values import canonical_value_to_data


@dataclass(frozen=True, slots=True)
class PutDomainSchema:
    schema: DomainSchema

    def to_operation(self) -> Operation:
        return Operation("domain.schema.put", {"schema": domain_schema_to_data(self.schema)})


@dataclass(frozen=True, slots=True)
class DeleteDomainSchema:
    schema_id: str

    def to_operation(self) -> Operation:
        return Operation("domain.schema.delete", {"schema_id": self.schema_id})


@dataclass(frozen=True, slots=True)
class PutDomainConcept:
    schema_id: str
    concept: ConceptDefinition

    def to_operation(self) -> Operation:
        return Operation(
            "domain.schema.concept.put",
            {"schema_id": self.schema_id, "concept": concept_definition_to_data(self.concept)},
        )


@dataclass(frozen=True, slots=True)
class DeleteDomainConcept:
    schema_id: str
    concept_id: str

    def to_operation(self) -> Operation:
        return Operation(
            "domain.schema.concept.delete",
            {"schema_id": self.schema_id, "concept_id": self.concept_id},
        )


@dataclass(frozen=True, slots=True)
class PutDomainPropertyDefinition:
    schema_id: str
    concept_id: str
    definition: PropertyDefinition

    def to_operation(self) -> Operation:
        return Operation(
            "domain.schema.property.put",
            {
                "schema_id": self.schema_id,
                "concept_id": self.concept_id,
                "definition": property_definition_to_data(self.definition),
            },
        )


@dataclass(frozen=True, slots=True)
class PutDomainRoleDefinition:
    schema_id: str
    concept_id: str
    definition: RoleDefinition
    containment: bool = True

    def to_operation(self) -> Operation:
        return Operation(
            "domain.schema.role.put",
            {
                "schema_id": self.schema_id,
                "concept_id": self.concept_id,
                "definition": role_definition_to_data(self.definition),
                "containment": self.containment,
            },
        )


@dataclass(frozen=True, slots=True)
class PutDomainModel:
    model: DomainModel

    def to_operation(self) -> Operation:
        return Operation("domain.model.put", {"model": domain_model_to_data(self.model)})


@dataclass(frozen=True, slots=True)
class DeleteDomainModel:
    model_id: str

    def to_operation(self) -> Operation:
        return Operation("domain.model.delete", {"model_id": self.model_id})


@dataclass(frozen=True, slots=True)
class CreateDomainNode:
    model_id: str
    node: IntentionalNode
    parent_id: str | None = None
    role_id: str | None = None
    index: int | None = None

    def to_operation(self) -> Operation:
        return Operation(
            "domain.node.create",
            {
                "model_id": self.model_id,
                "node": intentional_node_to_data(self.node),
                "parent_id": self.parent_id,
                "role_id": self.role_id,
                "index": self.index,
            },
        )


@dataclass(frozen=True, slots=True)
class DeleteDomainNode:
    model_id: str
    node_id: str

    def to_operation(self) -> Operation:
        return Operation("domain.node.delete", {"model_id": self.model_id, "node_id": self.node_id})


@dataclass(frozen=True, slots=True)
class SetDomainProperty:
    model_id: str
    node_id: str
    property_id: str
    value: DomainValue | None

    def to_operation(self) -> Operation:
        # Preserve native scalar command admission: malformed configured scalars
        # receive an authority rejection rather than raising in the client adapter.
        value = (
            self.value
            if self.value is None or isinstance(self.value, (str, bool, int, float))
            else canonical_value_to_data(self.value)
        )
        return Operation(
            "domain.node.set_property",
            {
                "model_id": self.model_id,
                "node_id": self.node_id,
                "property_id": self.property_id,
                "value": value,
            },
        )


@dataclass(frozen=True, slots=True)
class PromoteEvidenceObservation:
    model_id: str
    node_id: str
    property_id: str
    evidence: ComputationEvidence
    observation_id: str

    def to_operation(self) -> Operation:
        return Operation(
            "domain.node.promote_evidence",
            {
                "model_id": self.model_id,
                "node_id": self.node_id,
                "property_id": self.property_id,
                "evidence": evidence_to_data(self.evidence),
                "observation_id": self.observation_id,
            },
        )


@dataclass(frozen=True, slots=True)
class PromoteEvidenceArtifact:
    """Create independent authored meaning from one explicitly selected sealed artifact."""

    evidence: ComputationEvidence
    artifact_id: str
    model: DomainModel
    node_id: str
    property_id: str

    def to_operation(self) -> Operation:
        return Operation(
            "domain.model.promote_artifact",
            {
                "evidence": evidence_to_data(self.evidence),
                "artifact_id": self.artifact_id,
                "model": domain_model_to_data(self.model),
                "node_id": self.node_id,
                "property_id": self.property_id,
            },
        )


@dataclass(frozen=True, slots=True)
class MoveDomainChild:
    model_id: str
    node_id: str
    parent_id: str | None
    role_id: str | None
    index: int = 0

    def to_operation(self) -> Operation:
        return Operation(
            "domain.node.move_child",
            {
                "model_id": self.model_id,
                "node_id": self.node_id,
                "parent_id": self.parent_id,
                "role_id": self.role_id,
                "index": self.index,
            },
        )


@dataclass(frozen=True, slots=True)
class InsertDomainChild:
    model_id: str
    node_id: str
    parent_id: str
    role_id: str
    index: int = 0

    def to_operation(self) -> Operation:
        return Operation(
            "domain.node.insert_child",
            {
                "model_id": self.model_id,
                "node_id": self.node_id,
                "parent_id": self.parent_id,
                "role_id": self.role_id,
                "index": self.index,
            },
        )


@dataclass(frozen=True, slots=True)
class RemoveDomainChild:
    model_id: str
    node_id: str

    def to_operation(self) -> Operation:
        return Operation(
            "domain.node.remove_child", {"model_id": self.model_id, "node_id": self.node_id}
        )


@dataclass(frozen=True, slots=True)
class SetDomainReference:
    model_id: str
    node_id: str
    role_id: str
    target_ids: tuple[str, ...]

    def to_operation(self) -> Operation:
        return Operation(
            "domain.node.set_reference",
            {
                "model_id": self.model_id,
                "node_id": self.node_id,
                "role_id": self.role_id,
                "target_ids": list(self.target_ids),
            },
        )


@dataclass(frozen=True, slots=True)
class RemoveDomainReference:
    model_id: str
    node_id: str
    role_id: str
    target_id: str | None = None

    def to_operation(self) -> Operation:
        return Operation(
            "domain.node.remove_reference",
            {
                "model_id": self.model_id,
                "node_id": self.node_id,
                "role_id": self.role_id,
                "target_id": self.target_id,
            },
        )


@dataclass(frozen=True, slots=True)
class PutDomainBundleReference:
    reference: BundleReference

    def to_operation(self) -> Operation:
        return Operation("domain.bundle.put", {"reference": bundle_to_data(self.reference)})


@dataclass(frozen=True, slots=True)
class DeleteDomainBundleReference:
    bundle_id: str
    version: str

    def to_operation(self) -> Operation:
        return Operation(
            "domain.bundle.delete", {"bundle_id": self.bundle_id, "version": self.version}
        )
