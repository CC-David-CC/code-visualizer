from code_visualizer.protocol.v1 import value_pb2 as _value_pb2
from code_visualizer.protocol.v1 import computation_pb2 as _computation_pb2
from code_visualizer.protocol.v1 import identity_pb2 as _identity_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ComputationOutcome(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    COMPUTATION_OUTCOME_UNSPECIFIED: _ClassVar[ComputationOutcome]
    COMPUTATION_SUCCEEDED: _ClassVar[ComputationOutcome]
    COMPUTATION_FAILED: _ClassVar[ComputationOutcome]
    COMPUTATION_CANCELLED: _ClassVar[ComputationOutcome]
COMPUTATION_OUTCOME_UNSPECIFIED: ComputationOutcome
COMPUTATION_SUCCEEDED: ComputationOutcome
COMPUTATION_FAILED: ComputationOutcome
COMPUTATION_CANCELLED: ComputationOutcome

class EvidenceObservation(_message.Message):
    __slots__ = ("id", "semantic_ids", "value", "label", "sequence")
    ID_FIELD_NUMBER: _ClassVar[int]
    SEMANTIC_IDS_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    LABEL_FIELD_NUMBER: _ClassVar[int]
    SEQUENCE_FIELD_NUMBER: _ClassVar[int]
    id: str
    semantic_ids: _containers.RepeatedScalarFieldContainer[str]
    value: _value_pb2.CanonicalValue
    label: str
    sequence: int
    def __init__(self, id: _Optional[str] = ..., semantic_ids: _Optional[_Iterable[str]] = ..., value: _Optional[_Union[_value_pb2.CanonicalValue, _Mapping]] = ..., label: _Optional[str] = ..., sequence: _Optional[int] = ...) -> None: ...

class EvidenceArtifact(_message.Message):
    __slots__ = ("id", "resource", "semantic_ids", "label")
    ID_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_FIELD_NUMBER: _ClassVar[int]
    SEMANTIC_IDS_FIELD_NUMBER: _ClassVar[int]
    LABEL_FIELD_NUMBER: _ClassVar[int]
    id: str
    resource: _value_pb2.ResourceReference
    semantic_ids: _containers.RepeatedScalarFieldContainer[str]
    label: str
    def __init__(self, id: _Optional[str] = ..., resource: _Optional[_Union[_value_pb2.ResourceReference, _Mapping]] = ..., semantic_ids: _Optional[_Iterable[str]] = ..., label: _Optional[str] = ...) -> None: ...

class EvidenceDiagnostic(_message.Message):
    __slots__ = ("code", "message", "semantic_ids")
    CODE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    SEMANTIC_IDS_FIELD_NUMBER: _ClassVar[int]
    code: str
    message: str
    semantic_ids: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, code: _Optional[str] = ..., message: _Optional[str] = ..., semantic_ids: _Optional[_Iterable[str]] = ...) -> None: ...

class EvidenceProvenance(_message.Message):
    __slots__ = ("project_id", "revision", "source_model_id", "backend_id", "backend_version", "input_digest", "configuration", "seed", "resources", "transformations", "origins", "terminal_resource")
    PROJECT_ID_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    SOURCE_MODEL_ID_FIELD_NUMBER: _ClassVar[int]
    BACKEND_ID_FIELD_NUMBER: _ClassVar[int]
    BACKEND_VERSION_FIELD_NUMBER: _ClassVar[int]
    INPUT_DIGEST_FIELD_NUMBER: _ClassVar[int]
    CONFIGURATION_FIELD_NUMBER: _ClassVar[int]
    SEED_FIELD_NUMBER: _ClassVar[int]
    RESOURCES_FIELD_NUMBER: _ClassVar[int]
    TRANSFORMATIONS_FIELD_NUMBER: _ClassVar[int]
    ORIGINS_FIELD_NUMBER: _ClassVar[int]
    TERMINAL_RESOURCE_FIELD_NUMBER: _ClassVar[int]
    project_id: str
    revision: int
    source_model_id: str
    backend_id: str
    backend_version: str
    input_digest: str
    configuration: _containers.RepeatedCompositeFieldContainer[_computation_pb2.ComputationParameter]
    seed: _value_pb2.IntegerValue
    resources: _containers.RepeatedCompositeFieldContainer[_value_pb2.ResourceReference]
    transformations: _containers.RepeatedScalarFieldContainer[str]
    origins: _identity_pb2.OriginMap
    terminal_resource: _value_pb2.ResourceReference
    def __init__(self, project_id: _Optional[str] = ..., revision: _Optional[int] = ..., source_model_id: _Optional[str] = ..., backend_id: _Optional[str] = ..., backend_version: _Optional[str] = ..., input_digest: _Optional[str] = ..., configuration: _Optional[_Iterable[_Union[_computation_pb2.ComputationParameter, _Mapping]]] = ..., seed: _Optional[_Union[_value_pb2.IntegerValue, _Mapping]] = ..., resources: _Optional[_Iterable[_Union[_value_pb2.ResourceReference, _Mapping]]] = ..., transformations: _Optional[_Iterable[str]] = ..., origins: _Optional[_Union[_identity_pb2.OriginMap, _Mapping]] = ..., terminal_resource: _Optional[_Union[_value_pb2.ResourceReference, _Mapping]] = ...) -> None: ...

class ComputationEvidence(_message.Message):
    __slots__ = ("schema_version", "id", "provenance", "outcome", "observations", "artifacts", "diagnostics")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    ID_FIELD_NUMBER: _ClassVar[int]
    PROVENANCE_FIELD_NUMBER: _ClassVar[int]
    OUTCOME_FIELD_NUMBER: _ClassVar[int]
    OBSERVATIONS_FIELD_NUMBER: _ClassVar[int]
    ARTIFACTS_FIELD_NUMBER: _ClassVar[int]
    DIAGNOSTICS_FIELD_NUMBER: _ClassVar[int]
    schema_version: int
    id: str
    provenance: EvidenceProvenance
    outcome: ComputationOutcome
    observations: _containers.RepeatedCompositeFieldContainer[EvidenceObservation]
    artifacts: _containers.RepeatedCompositeFieldContainer[EvidenceArtifact]
    diagnostics: _containers.RepeatedCompositeFieldContainer[EvidenceDiagnostic]
    def __init__(self, schema_version: _Optional[int] = ..., id: _Optional[str] = ..., provenance: _Optional[_Union[EvidenceProvenance, _Mapping]] = ..., outcome: _Optional[_Union[ComputationOutcome, str]] = ..., observations: _Optional[_Iterable[_Union[EvidenceObservation, _Mapping]]] = ..., artifacts: _Optional[_Iterable[_Union[EvidenceArtifact, _Mapping]]] = ..., diagnostics: _Optional[_Iterable[_Union[EvidenceDiagnostic, _Mapping]]] = ...) -> None: ...

class ObservationEvent(_message.Message):
    __slots__ = ("schema_version", "session_id", "observation")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    OBSERVATION_FIELD_NUMBER: _ClassVar[int]
    schema_version: int
    session_id: str
    observation: EvidenceObservation
    def __init__(self, schema_version: _Optional[int] = ..., session_id: _Optional[str] = ..., observation: _Optional[_Union[EvidenceObservation, _Mapping]] = ...) -> None: ...

class EvidencePublication(_message.Message):
    __slots__ = ("schema_version", "id", "provenance", "artifact")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    ID_FIELD_NUMBER: _ClassVar[int]
    PROVENANCE_FIELD_NUMBER: _ClassVar[int]
    ARTIFACT_FIELD_NUMBER: _ClassVar[int]
    schema_version: int
    id: str
    provenance: EvidenceProvenance
    artifact: EvidenceArtifact
    def __init__(self, schema_version: _Optional[int] = ..., id: _Optional[str] = ..., provenance: _Optional[_Union[EvidenceProvenance, _Mapping]] = ..., artifact: _Optional[_Union[EvidenceArtifact, _Mapping]] = ...) -> None: ...

class PublicationEvent(_message.Message):
    __slots__ = ("schema_version", "session_id", "sequence", "publication")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    SEQUENCE_FIELD_NUMBER: _ClassVar[int]
    PUBLICATION_FIELD_NUMBER: _ClassVar[int]
    schema_version: int
    session_id: str
    sequence: int
    publication: EvidencePublication
    def __init__(self, schema_version: _Optional[int] = ..., session_id: _Optional[str] = ..., sequence: _Optional[int] = ..., publication: _Optional[_Union[EvidencePublication, _Mapping]] = ...) -> None: ...
