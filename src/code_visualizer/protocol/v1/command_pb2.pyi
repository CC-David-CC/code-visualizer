from code_visualizer.protocol.v1 import domain_pb2 as _domain_pb2
from code_visualizer.protocol.v1 import value_pb2 as _value_pb2
from code_visualizer.protocol.v1 import identity_pb2 as _identity_pb2
from code_visualizer.protocol.v1 import evidence_pb2 as _evidence_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class NodeAddress(_message.Message):
    __slots__ = ("model_id", "node_id")
    MODEL_ID_FIELD_NUMBER: _ClassVar[int]
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    model_id: str
    node_id: str
    def __init__(self, model_id: _Optional[str] = ..., node_id: _Optional[str] = ...) -> None: ...

class PropertyAddress(_message.Message):
    __slots__ = ("model_id", "node_id", "property_id")
    MODEL_ID_FIELD_NUMBER: _ClassVar[int]
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    PROPERTY_ID_FIELD_NUMBER: _ClassVar[int]
    model_id: str
    node_id: str
    property_id: str
    def __init__(self, model_id: _Optional[str] = ..., node_id: _Optional[str] = ..., property_id: _Optional[str] = ...) -> None: ...

class SetProperty(_message.Message):
    __slots__ = ("target", "value")
    TARGET_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    target: PropertyAddress
    value: _value_pb2.CanonicalValue
    def __init__(self, target: _Optional[_Union[PropertyAddress, _Mapping]] = ..., value: _Optional[_Union[_value_pb2.CanonicalValue, _Mapping]] = ...) -> None: ...

class CreateNode(_message.Message):
    __slots__ = ("model_id", "node", "parent_id", "role_id", "index")
    MODEL_ID_FIELD_NUMBER: _ClassVar[int]
    NODE_FIELD_NUMBER: _ClassVar[int]
    PARENT_ID_FIELD_NUMBER: _ClassVar[int]
    ROLE_ID_FIELD_NUMBER: _ClassVar[int]
    INDEX_FIELD_NUMBER: _ClassVar[int]
    model_id: str
    node: _domain_pb2.IntentionalNode
    parent_id: str
    role_id: str
    index: int
    def __init__(self, model_id: _Optional[str] = ..., node: _Optional[_Union[_domain_pb2.IntentionalNode, _Mapping]] = ..., parent_id: _Optional[str] = ..., role_id: _Optional[str] = ..., index: _Optional[int] = ...) -> None: ...

class MoveChild(_message.Message):
    __slots__ = ("target", "parent_id", "role_id", "index")
    TARGET_FIELD_NUMBER: _ClassVar[int]
    PARENT_ID_FIELD_NUMBER: _ClassVar[int]
    ROLE_ID_FIELD_NUMBER: _ClassVar[int]
    INDEX_FIELD_NUMBER: _ClassVar[int]
    target: NodeAddress
    parent_id: str
    role_id: str
    index: int
    def __init__(self, target: _Optional[_Union[NodeAddress, _Mapping]] = ..., parent_id: _Optional[str] = ..., role_id: _Optional[str] = ..., index: _Optional[int] = ...) -> None: ...

class SetReference(_message.Message):
    __slots__ = ("target", "role_id", "target_ids")
    TARGET_FIELD_NUMBER: _ClassVar[int]
    ROLE_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_IDS_FIELD_NUMBER: _ClassVar[int]
    target: NodeAddress
    role_id: str
    target_ids: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, target: _Optional[_Union[NodeAddress, _Mapping]] = ..., role_id: _Optional[str] = ..., target_ids: _Optional[_Iterable[str]] = ...) -> None: ...

class RemoveReference(_message.Message):
    __slots__ = ("target", "role_id", "target_id")
    TARGET_FIELD_NUMBER: _ClassVar[int]
    ROLE_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_ID_FIELD_NUMBER: _ClassVar[int]
    target: NodeAddress
    role_id: str
    target_id: str
    def __init__(self, target: _Optional[_Union[NodeAddress, _Mapping]] = ..., role_id: _Optional[str] = ..., target_id: _Optional[str] = ...) -> None: ...

class PutConcept(_message.Message):
    __slots__ = ("schema_id", "concept")
    SCHEMA_ID_FIELD_NUMBER: _ClassVar[int]
    CONCEPT_FIELD_NUMBER: _ClassVar[int]
    schema_id: str
    concept: _domain_pb2.ConceptDefinition
    def __init__(self, schema_id: _Optional[str] = ..., concept: _Optional[_Union[_domain_pb2.ConceptDefinition, _Mapping]] = ...) -> None: ...

class DeleteConcept(_message.Message):
    __slots__ = ("schema_id", "concept_id")
    SCHEMA_ID_FIELD_NUMBER: _ClassVar[int]
    CONCEPT_ID_FIELD_NUMBER: _ClassVar[int]
    schema_id: str
    concept_id: str
    def __init__(self, schema_id: _Optional[str] = ..., concept_id: _Optional[str] = ...) -> None: ...

class PutPropertyDefinition(_message.Message):
    __slots__ = ("schema_id", "concept_id", "definition")
    SCHEMA_ID_FIELD_NUMBER: _ClassVar[int]
    CONCEPT_ID_FIELD_NUMBER: _ClassVar[int]
    DEFINITION_FIELD_NUMBER: _ClassVar[int]
    schema_id: str
    concept_id: str
    definition: _domain_pb2.PropertyDefinition
    def __init__(self, schema_id: _Optional[str] = ..., concept_id: _Optional[str] = ..., definition: _Optional[_Union[_domain_pb2.PropertyDefinition, _Mapping]] = ...) -> None: ...

class PutRoleDefinition(_message.Message):
    __slots__ = ("schema_id", "concept_id", "definition", "containment")
    SCHEMA_ID_FIELD_NUMBER: _ClassVar[int]
    CONCEPT_ID_FIELD_NUMBER: _ClassVar[int]
    DEFINITION_FIELD_NUMBER: _ClassVar[int]
    CONTAINMENT_FIELD_NUMBER: _ClassVar[int]
    schema_id: str
    concept_id: str
    definition: _domain_pb2.RoleDefinition
    containment: bool
    def __init__(self, schema_id: _Optional[str] = ..., concept_id: _Optional[str] = ..., definition: _Optional[_Union[_domain_pb2.RoleDefinition, _Mapping]] = ..., containment: bool = ...) -> None: ...

class HistoryCommand(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class PromoteEvidence(_message.Message):
    __slots__ = ("target", "evidence", "observation_id")
    TARGET_FIELD_NUMBER: _ClassVar[int]
    EVIDENCE_FIELD_NUMBER: _ClassVar[int]
    OBSERVATION_ID_FIELD_NUMBER: _ClassVar[int]
    target: PropertyAddress
    evidence: _evidence_pb2.ComputationEvidence
    observation_id: str
    def __init__(self, target: _Optional[_Union[PropertyAddress, _Mapping]] = ..., evidence: _Optional[_Union[_evidence_pb2.ComputationEvidence, _Mapping]] = ..., observation_id: _Optional[str] = ...) -> None: ...

class CommandEnvelope(_message.Message):
    __slots__ = ("schema_version", "actor_id", "operation_id", "project_id", "expected_revision", "transaction_id", "intent", "put_schema", "delete_schema_id", "put_model", "delete_model_id", "create_node", "delete_node", "set_property", "unset_property", "move_child", "set_reference", "remove_reference", "put_concept", "delete_concept", "put_property_definition", "put_role_definition", "put_bundle", "delete_bundle", "undo", "redo", "insert_child", "remove_child", "promote_evidence")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    ACTOR_ID_FIELD_NUMBER: _ClassVar[int]
    OPERATION_ID_FIELD_NUMBER: _ClassVar[int]
    PROJECT_ID_FIELD_NUMBER: _ClassVar[int]
    EXPECTED_REVISION_FIELD_NUMBER: _ClassVar[int]
    TRANSACTION_ID_FIELD_NUMBER: _ClassVar[int]
    INTENT_FIELD_NUMBER: _ClassVar[int]
    PUT_SCHEMA_FIELD_NUMBER: _ClassVar[int]
    DELETE_SCHEMA_ID_FIELD_NUMBER: _ClassVar[int]
    PUT_MODEL_FIELD_NUMBER: _ClassVar[int]
    DELETE_MODEL_ID_FIELD_NUMBER: _ClassVar[int]
    CREATE_NODE_FIELD_NUMBER: _ClassVar[int]
    DELETE_NODE_FIELD_NUMBER: _ClassVar[int]
    SET_PROPERTY_FIELD_NUMBER: _ClassVar[int]
    UNSET_PROPERTY_FIELD_NUMBER: _ClassVar[int]
    MOVE_CHILD_FIELD_NUMBER: _ClassVar[int]
    SET_REFERENCE_FIELD_NUMBER: _ClassVar[int]
    REMOVE_REFERENCE_FIELD_NUMBER: _ClassVar[int]
    PUT_CONCEPT_FIELD_NUMBER: _ClassVar[int]
    DELETE_CONCEPT_FIELD_NUMBER: _ClassVar[int]
    PUT_PROPERTY_DEFINITION_FIELD_NUMBER: _ClassVar[int]
    PUT_ROLE_DEFINITION_FIELD_NUMBER: _ClassVar[int]
    PUT_BUNDLE_FIELD_NUMBER: _ClassVar[int]
    DELETE_BUNDLE_FIELD_NUMBER: _ClassVar[int]
    UNDO_FIELD_NUMBER: _ClassVar[int]
    REDO_FIELD_NUMBER: _ClassVar[int]
    INSERT_CHILD_FIELD_NUMBER: _ClassVar[int]
    REMOVE_CHILD_FIELD_NUMBER: _ClassVar[int]
    PROMOTE_EVIDENCE_FIELD_NUMBER: _ClassVar[int]
    schema_version: int
    actor_id: str
    operation_id: str
    project_id: str
    expected_revision: int
    transaction_id: str
    intent: str
    put_schema: _domain_pb2.DomainSchema
    delete_schema_id: str
    put_model: _domain_pb2.DomainModel
    delete_model_id: str
    create_node: CreateNode
    delete_node: NodeAddress
    set_property: SetProperty
    unset_property: PropertyAddress
    move_child: MoveChild
    set_reference: SetReference
    remove_reference: RemoveReference
    put_concept: PutConcept
    delete_concept: DeleteConcept
    put_property_definition: PutPropertyDefinition
    put_role_definition: PutRoleDefinition
    put_bundle: _identity_pb2.VersionedReference
    delete_bundle: _identity_pb2.VersionedReference
    undo: HistoryCommand
    redo: HistoryCommand
    insert_child: MoveChild
    remove_child: NodeAddress
    promote_evidence: PromoteEvidence
    def __init__(self, schema_version: _Optional[int] = ..., actor_id: _Optional[str] = ..., operation_id: _Optional[str] = ..., project_id: _Optional[str] = ..., expected_revision: _Optional[int] = ..., transaction_id: _Optional[str] = ..., intent: _Optional[str] = ..., put_schema: _Optional[_Union[_domain_pb2.DomainSchema, _Mapping]] = ..., delete_schema_id: _Optional[str] = ..., put_model: _Optional[_Union[_domain_pb2.DomainModel, _Mapping]] = ..., delete_model_id: _Optional[str] = ..., create_node: _Optional[_Union[CreateNode, _Mapping]] = ..., delete_node: _Optional[_Union[NodeAddress, _Mapping]] = ..., set_property: _Optional[_Union[SetProperty, _Mapping]] = ..., unset_property: _Optional[_Union[PropertyAddress, _Mapping]] = ..., move_child: _Optional[_Union[MoveChild, _Mapping]] = ..., set_reference: _Optional[_Union[SetReference, _Mapping]] = ..., remove_reference: _Optional[_Union[RemoveReference, _Mapping]] = ..., put_concept: _Optional[_Union[PutConcept, _Mapping]] = ..., delete_concept: _Optional[_Union[DeleteConcept, _Mapping]] = ..., put_property_definition: _Optional[_Union[PutPropertyDefinition, _Mapping]] = ..., put_role_definition: _Optional[_Union[PutRoleDefinition, _Mapping]] = ..., put_bundle: _Optional[_Union[_identity_pb2.VersionedReference, _Mapping]] = ..., delete_bundle: _Optional[_Union[_identity_pb2.VersionedReference, _Mapping]] = ..., undo: _Optional[_Union[HistoryCommand, _Mapping]] = ..., redo: _Optional[_Union[HistoryCommand, _Mapping]] = ..., insert_child: _Optional[_Union[MoveChild, _Mapping]] = ..., remove_child: _Optional[_Union[NodeAddress, _Mapping]] = ..., promote_evidence: _Optional[_Union[PromoteEvidence, _Mapping]] = ...) -> None: ...

class EventReceipt(_message.Message):
    __slots__ = ("schema_version", "event_type", "actor_id", "operation_id", "project_id", "revision", "affected_ids", "occurred_at")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    EVENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    ACTOR_ID_FIELD_NUMBER: _ClassVar[int]
    OPERATION_ID_FIELD_NUMBER: _ClassVar[int]
    PROJECT_ID_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    AFFECTED_IDS_FIELD_NUMBER: _ClassVar[int]
    OCCURRED_AT_FIELD_NUMBER: _ClassVar[int]
    schema_version: int
    event_type: str
    actor_id: str
    operation_id: str
    project_id: str
    revision: int
    affected_ids: _containers.RepeatedScalarFieldContainer[str]
    occurred_at: str
    def __init__(self, schema_version: _Optional[int] = ..., event_type: _Optional[str] = ..., actor_id: _Optional[str] = ..., operation_id: _Optional[str] = ..., project_id: _Optional[str] = ..., revision: _Optional[int] = ..., affected_ids: _Optional[_Iterable[str]] = ..., occurred_at: _Optional[str] = ...) -> None: ...

class CommandAccepted(_message.Message):
    __slots__ = ("revision", "affected_ids", "events", "undo_group_id")
    REVISION_FIELD_NUMBER: _ClassVar[int]
    AFFECTED_IDS_FIELD_NUMBER: _ClassVar[int]
    EVENTS_FIELD_NUMBER: _ClassVar[int]
    UNDO_GROUP_ID_FIELD_NUMBER: _ClassVar[int]
    revision: int
    affected_ids: _containers.RepeatedScalarFieldContainer[str]
    events: _containers.RepeatedCompositeFieldContainer[EventReceipt]
    undo_group_id: str
    def __init__(self, revision: _Optional[int] = ..., affected_ids: _Optional[_Iterable[str]] = ..., events: _Optional[_Iterable[_Union[EventReceipt, _Mapping]]] = ..., undo_group_id: _Optional[str] = ...) -> None: ...

class CommandRejected(_message.Message):
    __slots__ = ("code", "message", "current_revision")
    CODE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    CURRENT_REVISION_FIELD_NUMBER: _ClassVar[int]
    code: str
    message: str
    current_revision: int
    def __init__(self, code: _Optional[str] = ..., message: _Optional[str] = ..., current_revision: _Optional[int] = ...) -> None: ...

class CommandDeferred(_message.Message):
    __slots__ = ("code", "message", "current_revision", "host_operation_id")
    CODE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    CURRENT_REVISION_FIELD_NUMBER: _ClassVar[int]
    HOST_OPERATION_ID_FIELD_NUMBER: _ClassVar[int]
    code: str
    message: str
    current_revision: int
    host_operation_id: str
    def __init__(self, code: _Optional[str] = ..., message: _Optional[str] = ..., current_revision: _Optional[int] = ..., host_operation_id: _Optional[str] = ...) -> None: ...

class ProtocolError(_message.Message):
    __slots__ = ("code", "message")
    CODE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    code: int
    message: str
    def __init__(self, code: _Optional[int] = ..., message: _Optional[str] = ...) -> None: ...

class CommandResponse(_message.Message):
    __slots__ = ("schema_version", "operation_id", "accepted", "rejected", "error", "deferred")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    OPERATION_ID_FIELD_NUMBER: _ClassVar[int]
    ACCEPTED_FIELD_NUMBER: _ClassVar[int]
    REJECTED_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    DEFERRED_FIELD_NUMBER: _ClassVar[int]
    schema_version: int
    operation_id: str
    accepted: CommandAccepted
    rejected: CommandRejected
    error: ProtocolError
    deferred: CommandDeferred
    def __init__(self, schema_version: _Optional[int] = ..., operation_id: _Optional[str] = ..., accepted: _Optional[_Union[CommandAccepted, _Mapping]] = ..., rejected: _Optional[_Union[CommandRejected, _Mapping]] = ..., error: _Optional[_Union[ProtocolError, _Mapping]] = ..., deferred: _Optional[_Union[CommandDeferred, _Mapping]] = ...) -> None: ...
