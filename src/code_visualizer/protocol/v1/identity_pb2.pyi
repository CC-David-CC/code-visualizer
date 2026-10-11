from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class VersionedReference(_message.Message):
    __slots__ = ("id", "version")
    ID_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    id: str
    version: str
    def __init__(self, id: _Optional[str] = ..., version: _Optional[str] = ...) -> None: ...

class SemanticReference(_message.Message):
    __slots__ = ("semantic_id", "model_id", "project_id")
    SEMANTIC_ID_FIELD_NUMBER: _ClassVar[int]
    MODEL_ID_FIELD_NUMBER: _ClassVar[int]
    PROJECT_ID_FIELD_NUMBER: _ClassVar[int]
    semantic_id: str
    model_id: str
    project_id: str
    def __init__(self, semantic_id: _Optional[str] = ..., model_id: _Optional[str] = ..., project_id: _Optional[str] = ...) -> None: ...

class OriginLink(_message.Message):
    __slots__ = ("generated_id", "source_ids")
    GENERATED_ID_FIELD_NUMBER: _ClassVar[int]
    SOURCE_IDS_FIELD_NUMBER: _ClassVar[int]
    generated_id: str
    source_ids: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, generated_id: _Optional[str] = ..., source_ids: _Optional[_Iterable[str]] = ...) -> None: ...

class OriginMap(_message.Message):
    __slots__ = ("project_id", "revision", "links")
    PROJECT_ID_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    LINKS_FIELD_NUMBER: _ClassVar[int]
    project_id: str
    revision: int
    links: _containers.RepeatedCompositeFieldContainer[OriginLink]
    def __init__(self, project_id: _Optional[str] = ..., revision: _Optional[int] = ..., links: _Optional[_Iterable[_Union[OriginLink, _Mapping]]] = ...) -> None: ...

class ContractDefinition(_message.Message):
    __slots__ = ("kind", "id", "version")
    KIND_FIELD_NUMBER: _ClassVar[int]
    ID_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    kind: str
    id: str
    version: str
    def __init__(self, kind: _Optional[str] = ..., id: _Optional[str] = ..., version: _Optional[str] = ...) -> None: ...

class PublicationManifest(_message.Message):
    __slots__ = ("naming_version", "owner_id", "bundle", "contracts", "dependencies", "references")
    NAMING_VERSION_FIELD_NUMBER: _ClassVar[int]
    OWNER_ID_FIELD_NUMBER: _ClassVar[int]
    BUNDLE_FIELD_NUMBER: _ClassVar[int]
    CONTRACTS_FIELD_NUMBER: _ClassVar[int]
    DEPENDENCIES_FIELD_NUMBER: _ClassVar[int]
    REFERENCES_FIELD_NUMBER: _ClassVar[int]
    naming_version: int
    owner_id: str
    bundle: ContractDefinition
    contracts: _containers.RepeatedCompositeFieldContainer[ContractDefinition]
    dependencies: _containers.RepeatedCompositeFieldContainer[ContractDefinition]
    references: _containers.RepeatedCompositeFieldContainer[ContractDefinition]
    def __init__(self, naming_version: _Optional[int] = ..., owner_id: _Optional[str] = ..., bundle: _Optional[_Union[ContractDefinition, _Mapping]] = ..., contracts: _Optional[_Iterable[_Union[ContractDefinition, _Mapping]]] = ..., dependencies: _Optional[_Iterable[_Union[ContractDefinition, _Mapping]]] = ..., references: _Optional[_Iterable[_Union[ContractDefinition, _Mapping]]] = ...) -> None: ...
