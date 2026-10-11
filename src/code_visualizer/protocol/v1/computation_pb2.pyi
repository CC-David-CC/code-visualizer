from code_visualizer.protocol.v1 import value_pb2 as _value_pb2
from code_visualizer.protocol.v1 import identity_pb2 as _identity_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class BackendExecutionMode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    BACKEND_EXECUTION_MODE_UNSPECIFIED: _ClassVar[BackendExecutionMode]
    MODE_BATCH: _ClassVar[BackendExecutionMode]
    MODE_STREAMING: _ClassVar[BackendExecutionMode]

class ComputationStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    COMPUTATION_STATUS_UNSPECIFIED: _ClassVar[ComputationStatus]
    STATUS_QUEUED: _ClassVar[ComputationStatus]
    STATUS_RUNNING: _ClassVar[ComputationStatus]
    STATUS_SUCCEEDED: _ClassVar[ComputationStatus]
    STATUS_FAILED: _ClassVar[ComputationStatus]
    STATUS_CANCELLED: _ClassVar[ComputationStatus]
BACKEND_EXECUTION_MODE_UNSPECIFIED: BackendExecutionMode
MODE_BATCH: BackendExecutionMode
MODE_STREAMING: BackendExecutionMode
COMPUTATION_STATUS_UNSPECIFIED: ComputationStatus
STATUS_QUEUED: ComputationStatus
STATUS_RUNNING: ComputationStatus
STATUS_SUCCEEDED: ComputationStatus
STATUS_FAILED: ComputationStatus
STATUS_CANCELLED: ComputationStatus

class ComputationParameter(_message.Message):
    __slots__ = ("name", "value")
    NAME_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    name: str
    value: _value_pb2.CanonicalValue
    def __init__(self, name: _Optional[str] = ..., value: _Optional[_Union[_value_pb2.CanonicalValue, _Mapping]] = ...) -> None: ...

class BackendCapabilities(_message.Message):
    __slots__ = ("execution_mode", "progress", "observations", "cancellation", "deterministic", "seeded", "external_worker", "publications")
    EXECUTION_MODE_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    OBSERVATIONS_FIELD_NUMBER: _ClassVar[int]
    CANCELLATION_FIELD_NUMBER: _ClassVar[int]
    DETERMINISTIC_FIELD_NUMBER: _ClassVar[int]
    SEEDED_FIELD_NUMBER: _ClassVar[int]
    EXTERNAL_WORKER_FIELD_NUMBER: _ClassVar[int]
    PUBLICATIONS_FIELD_NUMBER: _ClassVar[int]
    execution_mode: BackendExecutionMode
    progress: bool
    observations: bool
    cancellation: bool
    deterministic: bool
    seeded: bool
    external_worker: bool
    publications: bool
    def __init__(self, execution_mode: _Optional[_Union[BackendExecutionMode, str]] = ..., progress: bool = ..., observations: bool = ..., cancellation: bool = ..., deterministic: bool = ..., seeded: bool = ..., external_worker: bool = ..., publications: bool = ...) -> None: ...

class BackendDefinition(_message.Message):
    __slots__ = ("schema_version", "id", "version", "title", "input_representation", "input_schema_id", "input_schema_version", "description", "api_version", "capabilities")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    ID_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    INPUT_REPRESENTATION_FIELD_NUMBER: _ClassVar[int]
    INPUT_SCHEMA_ID_FIELD_NUMBER: _ClassVar[int]
    INPUT_SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    API_VERSION_FIELD_NUMBER: _ClassVar[int]
    CAPABILITIES_FIELD_NUMBER: _ClassVar[int]
    schema_version: int
    id: str
    version: str
    title: str
    input_representation: _identity_pb2.VersionedReference
    input_schema_id: str
    input_schema_version: str
    description: str
    api_version: int
    capabilities: BackendCapabilities
    def __init__(self, schema_version: _Optional[int] = ..., id: _Optional[str] = ..., version: _Optional[str] = ..., title: _Optional[str] = ..., input_representation: _Optional[_Union[_identity_pb2.VersionedReference, _Mapping]] = ..., input_schema_id: _Optional[str] = ..., input_schema_version: _Optional[str] = ..., description: _Optional[str] = ..., api_version: _Optional[int] = ..., capabilities: _Optional[_Union[BackendCapabilities, _Mapping]] = ...) -> None: ...

class ComputationRequest(_message.Message):
    __slots__ = ("schema_version", "project_id", "revision", "backend_id", "backend_version", "model_id", "configuration", "seed", "resources", "inputs", "outputs")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    PROJECT_ID_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    BACKEND_ID_FIELD_NUMBER: _ClassVar[int]
    BACKEND_VERSION_FIELD_NUMBER: _ClassVar[int]
    MODEL_ID_FIELD_NUMBER: _ClassVar[int]
    CONFIGURATION_FIELD_NUMBER: _ClassVar[int]
    SEED_FIELD_NUMBER: _ClassVar[int]
    RESOURCES_FIELD_NUMBER: _ClassVar[int]
    INPUTS_FIELD_NUMBER: _ClassVar[int]
    OUTPUTS_FIELD_NUMBER: _ClassVar[int]
    schema_version: int
    project_id: str
    revision: int
    backend_id: str
    backend_version: str
    model_id: str
    configuration: _containers.RepeatedCompositeFieldContainer[ComputationParameter]
    seed: _value_pb2.IntegerValue
    resources: _containers.RepeatedCompositeFieldContainer[_value_pb2.ResourceReference]
    inputs: _containers.RepeatedCompositeFieldContainer[ResourceInput]
    outputs: _containers.RepeatedCompositeFieldContainer[ResourceOutput]
    def __init__(self, schema_version: _Optional[int] = ..., project_id: _Optional[str] = ..., revision: _Optional[int] = ..., backend_id: _Optional[str] = ..., backend_version: _Optional[str] = ..., model_id: _Optional[str] = ..., configuration: _Optional[_Iterable[_Union[ComputationParameter, _Mapping]]] = ..., seed: _Optional[_Union[_value_pb2.IntegerValue, _Mapping]] = ..., resources: _Optional[_Iterable[_Union[_value_pb2.ResourceReference, _Mapping]]] = ..., inputs: _Optional[_Iterable[_Union[ResourceInput, _Mapping]]] = ..., outputs: _Optional[_Iterable[_Union[ResourceOutput, _Mapping]]] = ...) -> None: ...

class ResourceInput(_message.Message):
    __slots__ = ("name", "resource", "logical_type")
    NAME_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_FIELD_NUMBER: _ClassVar[int]
    LOGICAL_TYPE_FIELD_NUMBER: _ClassVar[int]
    name: str
    resource: _value_pb2.ResourceReference
    logical_type: _identity_pb2.VersionedReference
    def __init__(self, name: _Optional[str] = ..., resource: _Optional[_Union[_value_pb2.ResourceReference, _Mapping]] = ..., logical_type: _Optional[_Union[_identity_pb2.VersionedReference, _Mapping]] = ...) -> None: ...

class ResourceOutput(_message.Message):
    __slots__ = ("name", "logical_type", "semantic_ids", "required")
    NAME_FIELD_NUMBER: _ClassVar[int]
    LOGICAL_TYPE_FIELD_NUMBER: _ClassVar[int]
    SEMANTIC_IDS_FIELD_NUMBER: _ClassVar[int]
    REQUIRED_FIELD_NUMBER: _ClassVar[int]
    name: str
    logical_type: _identity_pb2.VersionedReference
    semantic_ids: _containers.RepeatedScalarFieldContainer[str]
    required: bool
    def __init__(self, name: _Optional[str] = ..., logical_type: _Optional[_Union[_identity_pb2.VersionedReference, _Mapping]] = ..., semantic_ids: _Optional[_Iterable[str]] = ..., required: bool = ...) -> None: ...

class ComputationPlan(_message.Message):
    __slots__ = ("schema_version", "request", "representation", "model", "transformations", "origins", "input_digest")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    REQUEST_FIELD_NUMBER: _ClassVar[int]
    REPRESENTATION_FIELD_NUMBER: _ClassVar[int]
    MODEL_FIELD_NUMBER: _ClassVar[int]
    TRANSFORMATIONS_FIELD_NUMBER: _ClassVar[int]
    ORIGINS_FIELD_NUMBER: _ClassVar[int]
    INPUT_DIGEST_FIELD_NUMBER: _ClassVar[int]
    schema_version: int
    request: ComputationRequest
    representation: _identity_pb2.VersionedReference
    model: _value_pb2.ResourceReference
    transformations: _containers.RepeatedScalarFieldContainer[str]
    origins: _identity_pb2.OriginMap
    input_digest: str
    def __init__(self, schema_version: _Optional[int] = ..., request: _Optional[_Union[ComputationRequest, _Mapping]] = ..., representation: _Optional[_Union[_identity_pb2.VersionedReference, _Mapping]] = ..., model: _Optional[_Union[_value_pb2.ResourceReference, _Mapping]] = ..., transformations: _Optional[_Iterable[str]] = ..., origins: _Optional[_Union[_identity_pb2.OriginMap, _Mapping]] = ..., input_digest: _Optional[str] = ...) -> None: ...

class ComputationSession(_message.Message):
    __slots__ = ("schema_version", "id", "project_id", "revision", "backend_id", "backend_version", "status", "cancellation_supported", "evidence_id")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    ID_FIELD_NUMBER: _ClassVar[int]
    PROJECT_ID_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    BACKEND_ID_FIELD_NUMBER: _ClassVar[int]
    BACKEND_VERSION_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    CANCELLATION_SUPPORTED_FIELD_NUMBER: _ClassVar[int]
    EVIDENCE_ID_FIELD_NUMBER: _ClassVar[int]
    schema_version: int
    id: str
    project_id: str
    revision: int
    backend_id: str
    backend_version: str
    status: ComputationStatus
    cancellation_supported: bool
    evidence_id: str
    def __init__(self, schema_version: _Optional[int] = ..., id: _Optional[str] = ..., project_id: _Optional[str] = ..., revision: _Optional[int] = ..., backend_id: _Optional[str] = ..., backend_version: _Optional[str] = ..., status: _Optional[_Union[ComputationStatus, str]] = ..., cancellation_supported: bool = ..., evidence_id: _Optional[str] = ...) -> None: ...

class ProgressEvent(_message.Message):
    __slots__ = ("schema_version", "session_id", "sequence", "completed", "total", "message")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    SEQUENCE_FIELD_NUMBER: _ClassVar[int]
    COMPLETED_FIELD_NUMBER: _ClassVar[int]
    TOTAL_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    schema_version: int
    session_id: str
    sequence: int
    completed: float
    total: float
    message: str
    def __init__(self, schema_version: _Optional[int] = ..., session_id: _Optional[str] = ..., sequence: _Optional[int] = ..., completed: _Optional[float] = ..., total: _Optional[float] = ..., message: _Optional[str] = ...) -> None: ...

class CancelRequest(_message.Message):
    __slots__ = ("schema_version", "session_id", "reason")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    schema_version: int
    session_id: str
    reason: str
    def __init__(self, schema_version: _Optional[int] = ..., session_id: _Optional[str] = ..., reason: _Optional[str] = ...) -> None: ...
