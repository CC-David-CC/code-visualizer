from code_visualizer.protocol.v1 import identity_pb2 as _identity_pb2
from code_visualizer.protocol.v1 import value_pb2 as _value_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class PropertyDefinition(_message.Message):
    __slots__ = ("id", "name", "value_kind", "required", "default_value", "choices", "minimum", "maximum", "value_constraints")
    ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    VALUE_KIND_FIELD_NUMBER: _ClassVar[int]
    REQUIRED_FIELD_NUMBER: _ClassVar[int]
    DEFAULT_VALUE_FIELD_NUMBER: _ClassVar[int]
    CHOICES_FIELD_NUMBER: _ClassVar[int]
    MINIMUM_FIELD_NUMBER: _ClassVar[int]
    MAXIMUM_FIELD_NUMBER: _ClassVar[int]
    VALUE_CONSTRAINTS_FIELD_NUMBER: _ClassVar[int]
    id: str
    name: str
    value_kind: str
    required: bool
    default_value: _value_pb2.CanonicalValue
    choices: _containers.RepeatedCompositeFieldContainer[_value_pb2.CanonicalValue]
    minimum: float
    maximum: float
    value_constraints: _value_pb2.ValueConstraints
    def __init__(self, id: _Optional[str] = ..., name: _Optional[str] = ..., value_kind: _Optional[str] = ..., required: bool = ..., default_value: _Optional[_Union[_value_pb2.CanonicalValue, _Mapping]] = ..., choices: _Optional[_Iterable[_Union[_value_pb2.CanonicalValue, _Mapping]]] = ..., minimum: _Optional[float] = ..., maximum: _Optional[float] = ..., value_constraints: _Optional[_Union[_value_pb2.ValueConstraints, _Mapping]] = ...) -> None: ...

class RoleDefinition(_message.Message):
    __slots__ = ("id", "name", "allowed_concept_ids", "min_count", "max_count", "ordered")
    ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    ALLOWED_CONCEPT_IDS_FIELD_NUMBER: _ClassVar[int]
    MIN_COUNT_FIELD_NUMBER: _ClassVar[int]
    MAX_COUNT_FIELD_NUMBER: _ClassVar[int]
    ORDERED_FIELD_NUMBER: _ClassVar[int]
    id: str
    name: str
    allowed_concept_ids: _containers.RepeatedScalarFieldContainer[str]
    min_count: int
    max_count: int
    ordered: bool
    def __init__(self, id: _Optional[str] = ..., name: _Optional[str] = ..., allowed_concept_ids: _Optional[_Iterable[str]] = ..., min_count: _Optional[int] = ..., max_count: _Optional[int] = ..., ordered: bool = ...) -> None: ...

class ConstraintDefinition(_message.Message):
    __slots__ = ("id", "kind", "property_id", "role_id")
    ID_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    PROPERTY_ID_FIELD_NUMBER: _ClassVar[int]
    ROLE_ID_FIELD_NUMBER: _ClassVar[int]
    id: str
    kind: str
    property_id: str
    role_id: str
    def __init__(self, id: _Optional[str] = ..., kind: _Optional[str] = ..., property_id: _Optional[str] = ..., role_id: _Optional[str] = ...) -> None: ...

class ConceptDefinition(_message.Message):
    __slots__ = ("id", "name", "properties", "containment_roles", "reference_roles", "constraints", "display_property_id", "description")
    ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    PROPERTIES_FIELD_NUMBER: _ClassVar[int]
    CONTAINMENT_ROLES_FIELD_NUMBER: _ClassVar[int]
    REFERENCE_ROLES_FIELD_NUMBER: _ClassVar[int]
    CONSTRAINTS_FIELD_NUMBER: _ClassVar[int]
    DISPLAY_PROPERTY_ID_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    id: str
    name: str
    properties: _containers.RepeatedCompositeFieldContainer[PropertyDefinition]
    containment_roles: _containers.RepeatedCompositeFieldContainer[RoleDefinition]
    reference_roles: _containers.RepeatedCompositeFieldContainer[RoleDefinition]
    constraints: _containers.RepeatedCompositeFieldContainer[ConstraintDefinition]
    display_property_id: str
    description: str
    def __init__(self, id: _Optional[str] = ..., name: _Optional[str] = ..., properties: _Optional[_Iterable[_Union[PropertyDefinition, _Mapping]]] = ..., containment_roles: _Optional[_Iterable[_Union[RoleDefinition, _Mapping]]] = ..., reference_roles: _Optional[_Iterable[_Union[RoleDefinition, _Mapping]]] = ..., constraints: _Optional[_Iterable[_Union[ConstraintDefinition, _Mapping]]] = ..., display_property_id: _Optional[str] = ..., description: _Optional[str] = ...) -> None: ...

class DomainSchema(_message.Message):
    __slots__ = ("schema_version", "id", "namespace", "version", "concepts", "bundle", "description")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    ID_FIELD_NUMBER: _ClassVar[int]
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    CONCEPTS_FIELD_NUMBER: _ClassVar[int]
    BUNDLE_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    schema_version: int
    id: str
    namespace: str
    version: str
    concepts: _containers.RepeatedCompositeFieldContainer[ConceptDefinition]
    bundle: _identity_pb2.VersionedReference
    description: str
    def __init__(self, schema_version: _Optional[int] = ..., id: _Optional[str] = ..., namespace: _Optional[str] = ..., version: _Optional[str] = ..., concepts: _Optional[_Iterable[_Union[ConceptDefinition, _Mapping]]] = ..., bundle: _Optional[_Union[_identity_pb2.VersionedReference, _Mapping]] = ..., description: _Optional[str] = ...) -> None: ...

class PropertyValue(_message.Message):
    __slots__ = ("property_id", "value")
    PROPERTY_ID_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    property_id: str
    value: _value_pb2.CanonicalValue
    def __init__(self, property_id: _Optional[str] = ..., value: _Optional[_Union[_value_pb2.CanonicalValue, _Mapping]] = ...) -> None: ...

class RoleBinding(_message.Message):
    __slots__ = ("role_id", "node_ids")
    ROLE_ID_FIELD_NUMBER: _ClassVar[int]
    NODE_IDS_FIELD_NUMBER: _ClassVar[int]
    role_id: str
    node_ids: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, role_id: _Optional[str] = ..., node_ids: _Optional[_Iterable[str]] = ...) -> None: ...

class IntentionalNode(_message.Message):
    __slots__ = ("schema_version", "id", "concept_id", "properties", "children", "references")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    ID_FIELD_NUMBER: _ClassVar[int]
    CONCEPT_ID_FIELD_NUMBER: _ClassVar[int]
    PROPERTIES_FIELD_NUMBER: _ClassVar[int]
    CHILDREN_FIELD_NUMBER: _ClassVar[int]
    REFERENCES_FIELD_NUMBER: _ClassVar[int]
    schema_version: int
    id: str
    concept_id: str
    properties: _containers.RepeatedCompositeFieldContainer[PropertyValue]
    children: _containers.RepeatedCompositeFieldContainer[RoleBinding]
    references: _containers.RepeatedCompositeFieldContainer[RoleBinding]
    def __init__(self, schema_version: _Optional[int] = ..., id: _Optional[str] = ..., concept_id: _Optional[str] = ..., properties: _Optional[_Iterable[_Union[PropertyValue, _Mapping]]] = ..., children: _Optional[_Iterable[_Union[RoleBinding, _Mapping]]] = ..., references: _Optional[_Iterable[_Union[RoleBinding, _Mapping]]] = ...) -> None: ...

class DomainModel(_message.Message):
    __slots__ = ("schema_version", "id", "schema", "roots", "nodes", "title")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    ID_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_FIELD_NUMBER: _ClassVar[int]
    ROOTS_FIELD_NUMBER: _ClassVar[int]
    NODES_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    schema_version: int
    id: str
    schema: _identity_pb2.VersionedReference
    roots: _containers.RepeatedScalarFieldContainer[str]
    nodes: _containers.RepeatedCompositeFieldContainer[IntentionalNode]
    title: str
    def __init__(self, schema_version: _Optional[int] = ..., id: _Optional[str] = ..., schema: _Optional[_Union[_identity_pb2.VersionedReference, _Mapping]] = ..., roots: _Optional[_Iterable[str]] = ..., nodes: _Optional[_Iterable[_Union[IntentionalNode, _Mapping]]] = ..., title: _Optional[str] = ...) -> None: ...
