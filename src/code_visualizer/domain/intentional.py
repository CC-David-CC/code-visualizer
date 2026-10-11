"""Schema-owned, immutable intentions for domains using generic storage.

ProgramModel retains its specialized canonical representation. These values own
other domains; projections and transformed programs never enter this workspace.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from code_visualizer.domain.language import AuthoredDomainLanguage
from code_visualizer.domain.values import CanonicalValue, ValueConstraints, canonical_value_key

type DomainValue = CanonicalValue


class ValueKind(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    COMPLEX = "complex"
    QUANTITY = "quantity"
    TENSOR = "tensor"
    RESOURCE = "resource"


class ConstraintKind(StrEnum):
    NONEMPTY = "nonempty"
    UNIQUE_PROPERTY = "unique_property"


@dataclass(frozen=True, slots=True)
class BundleReference:
    id: str
    version: str


@dataclass(frozen=True, slots=True, eq=False)
class PropertyDefinition:
    id: str
    name: str
    value_kind: ValueKind = ValueKind.STRING
    required: bool = False
    default: DomainValue | None = None
    choices: tuple[DomainValue, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    value_constraints: ValueConstraints = field(default_factory=ValueConstraints)

    def _equality_key(self) -> tuple[object, ...]:
        return (
            self.id,
            self.name,
            self.value_kind,
            self.required,
            None if self.default is None else canonical_value_key(self.default),
            tuple(canonical_value_key(item) for item in self.choices),
            self.minimum,
            self.maximum,
            self.value_constraints,
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PropertyDefinition):
            return NotImplemented
        return self._equality_key() == other._equality_key()

    def __hash__(self) -> int:
        return hash(self._equality_key())


@dataclass(frozen=True, slots=True)
class RoleDefinition:
    id: str
    name: str
    allowed_concept_ids: tuple[str, ...]
    min_count: int = 0
    max_count: int | None = None
    ordered: bool = True


@dataclass(frozen=True, slots=True)
class ConstraintDefinition:
    id: str
    kind: ConstraintKind
    property_id: str
    role_id: str | None = None


@dataclass(frozen=True, slots=True)
class ConceptDefinition:
    id: str
    name: str
    properties: tuple[PropertyDefinition, ...] = ()
    containment_roles: tuple[RoleDefinition, ...] = ()
    reference_roles: tuple[RoleDefinition, ...] = ()
    constraints: tuple[ConstraintDefinition, ...] = ()
    display_property_id: str | None = None
    description: str = ""

    def property(self, property_id: str) -> PropertyDefinition | None:
        return next((item for item in self.properties if item.id == property_id), None)

    def role(self, role_id: str) -> RoleDefinition | None:
        return next(
            (
                item
                for item in (*self.containment_roles, *self.reference_roles)
                if item.id == role_id
            ),
            None,
        )


@dataclass(frozen=True, slots=True)
class DomainSchema:
    id: str
    namespace: str
    version: str
    concepts: tuple[ConceptDefinition, ...] = ()
    bundle: BundleReference | None = None
    description: str = ""

    def concept(self, concept_id: str) -> ConceptDefinition | None:
        return next((item for item in self.concepts if item.id == concept_id), None)


@dataclass(frozen=True, slots=True, eq=False)
class PropertyValue:
    property_id: str
    value: DomainValue

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PropertyValue):
            return NotImplemented
        return self.property_id == other.property_id and canonical_value_key(
            self.value
        ) == canonical_value_key(other.value)

    def __hash__(self) -> int:
        return hash((self.property_id, canonical_value_key(self.value)))


@dataclass(frozen=True, slots=True)
class RoleBinding:
    role_id: str
    node_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IntentionalNode:
    id: str
    concept_id: str
    properties: tuple[PropertyValue, ...] = ()
    children: tuple[RoleBinding, ...] = ()
    references: tuple[RoleBinding, ...] = ()

    def property(self, property_id: str) -> DomainValue | None:
        return next(
            (item.value for item in self.properties if item.property_id == property_id), None
        )

    def child_ids(self, role_id: str) -> tuple[str, ...]:
        return next((item.node_ids for item in self.children if item.role_id == role_id), ())

    def reference_ids(self, role_id: str) -> tuple[str, ...]:
        return next((item.node_ids for item in self.references if item.role_id == role_id), ())


@dataclass(frozen=True, slots=True)
class DomainModel:
    id: str
    schema_id: str
    schema_version: str
    roots: tuple[str, ...] = ()
    nodes: tuple[IntentionalNode, ...] = ()
    title: str = ""

    def node(self, node_id: str) -> IntentionalNode | None:
        return next((item for item in self.nodes if item.id == node_id), None)


@dataclass(frozen=True, slots=True)
class DomainWorkspace:
    schemas: tuple[DomainSchema, ...] = ()
    models: tuple[DomainModel, ...] = ()
    bundle_references: tuple[BundleReference, ...] = ()
    language_definitions: tuple[AuthoredDomainLanguage, ...] = ()

    def language(self, language_id: str) -> AuthoredDomainLanguage | None:
        return next((item for item in self.language_definitions if item.id == language_id), None)

    def schema(self, schema_id: str) -> DomainSchema | None:
        return next((item for item in self.schemas if item.id == schema_id), None)

    def model(self, model_id: str) -> DomainModel | None:
        return next((item for item in self.models if item.id == model_id), None)

    def node(self, node_id: str) -> IntentionalNode | None:
        return next(
            (node for model in self.models for node in model.nodes if node.id == node_id), None
        )


@dataclass(frozen=True, slots=True)
class DomainIssue:
    code: str
    message: str
    object_id: str
    field: str = ""
    incomplete: bool = False


def node_label(schema: DomainSchema, node: IntentionalNode) -> str:
    concept = schema.concept(node.concept_id)
    if concept is None:
        return node.id
    value = node.property(concept.display_property_id) if concept.display_property_id else None
    return str(value) if value is not None else concept.name
