from code_visualizer.protocol.v1 import value_pb2 as _value_pb2
from code_visualizer.protocol.v1 import resource_pb2 as _resource_pb2
from code_visualizer.protocol.v1 import computation_pb2 as _computation_pb2
from code_visualizer.protocol.v1 import evidence_pb2 as _evidence_pb2
from code_visualizer.protocol.v1 import identity_pb2 as _identity_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class WorkerPreparationRequest(_message.Message):
    __slots__ = ("session_id", "project", "request", "backend")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    PROJECT_FIELD_NUMBER: _ClassVar[int]
    REQUEST_FIELD_NUMBER: _ClassVar[int]
    BACKEND_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    project: _value_pb2.ResourceReference
    request: _computation_pb2.ComputationRequest
    backend: _computation_pb2.BackendDefinition
    def __init__(self, session_id: _Optional[str] = ..., project: _Optional[_Union[_value_pb2.ResourceReference, _Mapping]] = ..., request: _Optional[_Union[_computation_pb2.ComputationRequest, _Mapping]] = ..., backend: _Optional[_Union[_computation_pb2.BackendDefinition, _Mapping]] = ...) -> None: ...

class WorkerExecutionRequest(_message.Message):
    __slots__ = ("session_id", "plan", "backend", "execution_artifact")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    PLAN_FIELD_NUMBER: _ClassVar[int]
    BACKEND_FIELD_NUMBER: _ClassVar[int]
    EXECUTION_ARTIFACT_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    plan: _computation_pb2.ComputationPlan
    backend: _computation_pb2.BackendDefinition
    execution_artifact: _value_pb2.ResourceReference
    def __init__(self, session_id: _Optional[str] = ..., plan: _Optional[_Union[_computation_pb2.ComputationPlan, _Mapping]] = ..., backend: _Optional[_Union[_computation_pb2.BackendDefinition, _Mapping]] = ..., execution_artifact: _Optional[_Union[_value_pb2.ResourceReference, _Mapping]] = ...) -> None: ...

class InvocationLiteral(_message.Message):
    __slots__ = ("null", "text", "boolean", "integer_decimal", "real", "list", "tuple", "dictionary")
    NULL_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    BOOLEAN_FIELD_NUMBER: _ClassVar[int]
    INTEGER_DECIMAL_FIELD_NUMBER: _ClassVar[int]
    REAL_FIELD_NUMBER: _ClassVar[int]
    LIST_FIELD_NUMBER: _ClassVar[int]
    TUPLE_FIELD_NUMBER: _ClassVar[int]
    DICTIONARY_FIELD_NUMBER: _ClassVar[int]
    null: bool
    text: str
    boolean: bool
    integer_decimal: str
    real: float
    list: InvocationSequence
    tuple: InvocationSequence
    dictionary: InvocationDictionary
    def __init__(self, null: bool = ..., text: _Optional[str] = ..., boolean: bool = ..., integer_decimal: _Optional[str] = ..., real: _Optional[float] = ..., list: _Optional[_Union[InvocationSequence, _Mapping]] = ..., tuple: _Optional[_Union[InvocationSequence, _Mapping]] = ..., dictionary: _Optional[_Union[InvocationDictionary, _Mapping]] = ...) -> None: ...

class InvocationSequence(_message.Message):
    __slots__ = ("items",)
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    items: _containers.RepeatedCompositeFieldContainer[InvocationLiteral]
    def __init__(self, items: _Optional[_Iterable[_Union[InvocationLiteral, _Mapping]]] = ...) -> None: ...

class InvocationEntry(_message.Message):
    __slots__ = ("key", "value")
    KEY_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    key: str
    value: InvocationLiteral
    def __init__(self, key: _Optional[str] = ..., value: _Optional[_Union[InvocationLiteral, _Mapping]] = ...) -> None: ...

class InvocationDictionary(_message.Message):
    __slots__ = ("entries",)
    ENTRIES_FIELD_NUMBER: _ClassVar[int]
    entries: _containers.RepeatedCompositeFieldContainer[InvocationEntry]
    def __init__(self, entries: _Optional[_Iterable[_Union[InvocationEntry, _Mapping]]] = ...) -> None: ...

class InvocationArguments(_message.Message):
    __slots__ = ("positional", "keywords")
    POSITIONAL_FIELD_NUMBER: _ClassVar[int]
    KEYWORDS_FIELD_NUMBER: _ClassVar[int]
    positional: _containers.RepeatedCompositeFieldContainer[InvocationLiteral]
    keywords: _containers.RepeatedCompositeFieldContainer[InvocationEntry]
    def __init__(self, positional: _Optional[_Iterable[_Union[InvocationLiteral, _Mapping]]] = ..., keywords: _Optional[_Iterable[_Union[InvocationEntry, _Mapping]]] = ...) -> None: ...

class WorkerEditorPreparationRequest(_message.Message):
    __slots__ = ("session_id", "project", "project_id", "revision", "focus_diagram_id", "model_id", "arguments")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    PROJECT_FIELD_NUMBER: _ClassVar[int]
    PROJECT_ID_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    FOCUS_DIAGRAM_ID_FIELD_NUMBER: _ClassVar[int]
    MODEL_ID_FIELD_NUMBER: _ClassVar[int]
    ARGUMENTS_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    project: _value_pb2.ResourceReference
    project_id: str
    revision: int
    focus_diagram_id: str
    model_id: str
    arguments: InvocationArguments
    def __init__(self, session_id: _Optional[str] = ..., project: _Optional[_Union[_value_pb2.ResourceReference, _Mapping]] = ..., project_id: _Optional[str] = ..., revision: _Optional[int] = ..., focus_diagram_id: _Optional[str] = ..., model_id: _Optional[str] = ..., arguments: _Optional[_Union[InvocationArguments, _Mapping]] = ...) -> None: ...

class WorkerRequest(_message.Message):
    __slots__ = ("schema_version", "prepare", "execute", "prepare_editor")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    PREPARE_FIELD_NUMBER: _ClassVar[int]
    EXECUTE_FIELD_NUMBER: _ClassVar[int]
    PREPARE_EDITOR_FIELD_NUMBER: _ClassVar[int]
    schema_version: int
    prepare: WorkerPreparationRequest
    execute: WorkerExecutionRequest
    prepare_editor: WorkerEditorPreparationRequest
    def __init__(self, schema_version: _Optional[int] = ..., prepare: _Optional[_Union[WorkerPreparationRequest, _Mapping]] = ..., execute: _Optional[_Union[WorkerExecutionRequest, _Mapping]] = ..., prepare_editor: _Optional[_Union[WorkerEditorPreparationRequest, _Mapping]] = ...) -> None: ...

class WorkerPrepared(_message.Message):
    __slots__ = ("session_id", "plan", "execution_artifact")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    PLAN_FIELD_NUMBER: _ClassVar[int]
    EXECUTION_ARTIFACT_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    plan: _computation_pb2.ComputationPlan
    execution_artifact: _value_pb2.ResourceReference
    def __init__(self, session_id: _Optional[str] = ..., plan: _Optional[_Union[_computation_pb2.ComputationPlan, _Mapping]] = ..., execution_artifact: _Optional[_Union[_value_pb2.ResourceReference, _Mapping]] = ...) -> None: ...

class WorkerEditorPrepared(_message.Message):
    __slots__ = ("session_id", "source_digest", "execution_artifact")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    SOURCE_DIGEST_FIELD_NUMBER: _ClassVar[int]
    EXECUTION_ARTIFACT_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    source_digest: str
    execution_artifact: _value_pb2.ResourceReference
    def __init__(self, session_id: _Optional[str] = ..., source_digest: _Optional[str] = ..., execution_artifact: _Optional[_Union[_value_pb2.ResourceReference, _Mapping]] = ...) -> None: ...

class WorkerResourceEvent(_message.Message):
    __slots__ = ("session_id", "frame")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    FRAME_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    frame: _resource_pb2.ResourceTransferFrame
    def __init__(self, session_id: _Optional[str] = ..., frame: _Optional[_Union[_resource_pb2.ResourceTransferFrame, _Mapping]] = ...) -> None: ...

class WorkerPublicationOffer(_message.Message):
    __slots__ = ("session_id", "sequence", "artifact")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    SEQUENCE_FIELD_NUMBER: _ClassVar[int]
    ARTIFACT_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    sequence: int
    artifact: _evidence_pb2.EvidenceArtifact
    def __init__(self, session_id: _Optional[str] = ..., sequence: _Optional[int] = ..., artifact: _Optional[_Union[_evidence_pb2.EvidenceArtifact, _Mapping]] = ...) -> None: ...

class WorkerEvidenceProposal(_message.Message):
    __slots__ = ("session_id", "evidence")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    EVIDENCE_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    evidence: _evidence_pb2.ComputationEvidence
    def __init__(self, session_id: _Optional[str] = ..., evidence: _Optional[_Union[_evidence_pb2.ComputationEvidence, _Mapping]] = ...) -> None: ...

class WorkerCompletionVerified(_message.Message):
    __slots__ = ("session_id",)
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    def __init__(self, session_id: _Optional[str] = ...) -> None: ...

class WorkerFailure(_message.Message):
    __slots__ = ("session_id", "diagnostic")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    DIAGNOSTIC_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    diagnostic: _evidence_pb2.EvidenceDiagnostic
    def __init__(self, session_id: _Optional[str] = ..., diagnostic: _Optional[_Union[_evidence_pb2.EvidenceDiagnostic, _Mapping]] = ...) -> None: ...

class WorkerTerminalSecured(_message.Message):
    __slots__ = ("session_id", "evidence_id")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    EVIDENCE_ID_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    evidence_id: str
    def __init__(self, session_id: _Optional[str] = ..., evidence_id: _Optional[str] = ...) -> None: ...

class PreviewEvent(_message.Message):
    __slots__ = ("schema_version", "session_id", "sequence", "input_digest", "interpretation", "semantic_ids", "values")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    SEQUENCE_FIELD_NUMBER: _ClassVar[int]
    INPUT_DIGEST_FIELD_NUMBER: _ClassVar[int]
    INTERPRETATION_FIELD_NUMBER: _ClassVar[int]
    SEMANTIC_IDS_FIELD_NUMBER: _ClassVar[int]
    VALUES_FIELD_NUMBER: _ClassVar[int]
    schema_version: int
    session_id: str
    sequence: int
    input_digest: str
    interpretation: _identity_pb2.VersionedReference
    semantic_ids: _containers.RepeatedScalarFieldContainer[str]
    values: _containers.RepeatedCompositeFieldContainer[_computation_pb2.ComputationParameter]
    def __init__(self, schema_version: _Optional[int] = ..., session_id: _Optional[str] = ..., sequence: _Optional[int] = ..., input_digest: _Optional[str] = ..., interpretation: _Optional[_Union[_identity_pb2.VersionedReference, _Mapping]] = ..., semantic_ids: _Optional[_Iterable[str]] = ..., values: _Optional[_Iterable[_Union[_computation_pb2.ComputationParameter, _Mapping]]] = ...) -> None: ...

class WorkerEvent(_message.Message):
    __slots__ = ("schema_version", "prepared", "resource", "progress", "observation", "publication", "evidence", "verified", "failure", "editor_prepared", "preview")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    PREPARED_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    OBSERVATION_FIELD_NUMBER: _ClassVar[int]
    PUBLICATION_FIELD_NUMBER: _ClassVar[int]
    EVIDENCE_FIELD_NUMBER: _ClassVar[int]
    VERIFIED_FIELD_NUMBER: _ClassVar[int]
    FAILURE_FIELD_NUMBER: _ClassVar[int]
    EDITOR_PREPARED_FIELD_NUMBER: _ClassVar[int]
    PREVIEW_FIELD_NUMBER: _ClassVar[int]
    schema_version: int
    prepared: WorkerPrepared
    resource: WorkerResourceEvent
    progress: _computation_pb2.ProgressEvent
    observation: _evidence_pb2.ObservationEvent
    publication: WorkerPublicationOffer
    evidence: WorkerEvidenceProposal
    verified: WorkerCompletionVerified
    failure: WorkerFailure
    editor_prepared: WorkerEditorPrepared
    preview: PreviewEvent
    def __init__(self, schema_version: _Optional[int] = ..., prepared: _Optional[_Union[WorkerPrepared, _Mapping]] = ..., resource: _Optional[_Union[WorkerResourceEvent, _Mapping]] = ..., progress: _Optional[_Union[_computation_pb2.ProgressEvent, _Mapping]] = ..., observation: _Optional[_Union[_evidence_pb2.ObservationEvent, _Mapping]] = ..., publication: _Optional[_Union[WorkerPublicationOffer, _Mapping]] = ..., evidence: _Optional[_Union[WorkerEvidenceProposal, _Mapping]] = ..., verified: _Optional[_Union[WorkerCompletionVerified, _Mapping]] = ..., failure: _Optional[_Union[WorkerFailure, _Mapping]] = ..., editor_prepared: _Optional[_Union[WorkerEditorPrepared, _Mapping]] = ..., preview: _Optional[_Union[PreviewEvent, _Mapping]] = ...) -> None: ...

class WorkerControl(_message.Message):
    __slots__ = ("schema_version", "request", "cancel", "publication_ack", "terminal_ack")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    REQUEST_FIELD_NUMBER: _ClassVar[int]
    CANCEL_FIELD_NUMBER: _ClassVar[int]
    PUBLICATION_ACK_FIELD_NUMBER: _ClassVar[int]
    TERMINAL_ACK_FIELD_NUMBER: _ClassVar[int]
    schema_version: int
    request: WorkerRequest
    cancel: _computation_pb2.CancelRequest
    publication_ack: _evidence_pb2.PublicationEvent
    terminal_ack: WorkerTerminalSecured
    def __init__(self, schema_version: _Optional[int] = ..., request: _Optional[_Union[WorkerRequest, _Mapping]] = ..., cancel: _Optional[_Union[_computation_pb2.CancelRequest, _Mapping]] = ..., publication_ack: _Optional[_Union[_evidence_pb2.PublicationEvent, _Mapping]] = ..., terminal_ack: _Optional[_Union[WorkerTerminalSecured, _Mapping]] = ...) -> None: ...
