from code_visualizer.protocol.v1 import value_pb2 as _value_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ResourceAxis(_message.Message):
    __slots__ = ("name", "semantic_id")
    NAME_FIELD_NUMBER: _ClassVar[int]
    SEMANTIC_ID_FIELD_NUMBER: _ClassVar[int]
    name: str
    semantic_id: str
    def __init__(self, name: _Optional[str] = ..., semantic_id: _Optional[str] = ...) -> None: ...

class TensorDescriptor(_message.Message):
    __slots__ = ("dtype", "shape", "axes", "unit")
    DTYPE_FIELD_NUMBER: _ClassVar[int]
    SHAPE_FIELD_NUMBER: _ClassVar[int]
    AXES_FIELD_NUMBER: _ClassVar[int]
    UNIT_FIELD_NUMBER: _ClassVar[int]
    dtype: _value_pb2.TensorDType
    shape: _containers.RepeatedScalarFieldContainer[int]
    axes: _containers.RepeatedCompositeFieldContainer[ResourceAxis]
    unit: _value_pb2.UnitReference
    def __init__(self, dtype: _Optional[_Union[_value_pb2.TensorDType, str]] = ..., shape: _Optional[_Iterable[int]] = ..., axes: _Optional[_Iterable[_Union[ResourceAxis, _Mapping]]] = ..., unit: _Optional[_Union[_value_pb2.UnitReference, _Mapping]] = ...) -> None: ...

class ResourceLogicalTypeReference(_message.Message):
    __slots__ = ("id", "version")
    ID_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    id: str
    version: str
    def __init__(self, id: _Optional[str] = ..., version: _Optional[str] = ...) -> None: ...

class DataResource(_message.Message):
    __slots__ = ("schema_version", "id", "content_hash", "byte_size", "media_type", "tensor", "logical_type_reference")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    ID_FIELD_NUMBER: _ClassVar[int]
    CONTENT_HASH_FIELD_NUMBER: _ClassVar[int]
    BYTE_SIZE_FIELD_NUMBER: _ClassVar[int]
    MEDIA_TYPE_FIELD_NUMBER: _ClassVar[int]
    TENSOR_FIELD_NUMBER: _ClassVar[int]
    LOGICAL_TYPE_REFERENCE_FIELD_NUMBER: _ClassVar[int]
    schema_version: int
    id: str
    content_hash: str
    byte_size: int
    media_type: str
    tensor: TensorDescriptor
    logical_type_reference: ResourceLogicalTypeReference
    def __init__(self, schema_version: _Optional[int] = ..., id: _Optional[str] = ..., content_hash: _Optional[str] = ..., byte_size: _Optional[int] = ..., media_type: _Optional[str] = ..., tensor: _Optional[_Union[TensorDescriptor, _Mapping]] = ..., logical_type_reference: _Optional[_Union[ResourceLogicalTypeReference, _Mapping]] = ...) -> None: ...

class ResourceChunk(_message.Message):
    __slots__ = ("offset", "data")
    OFFSET_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    offset: int
    data: bytes
    def __init__(self, offset: _Optional[int] = ..., data: _Optional[bytes] = ...) -> None: ...

class ResourceTransferFinish(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ResourceTransferAbort(_message.Message):
    __slots__ = ("reason",)
    REASON_FIELD_NUMBER: _ClassVar[int]
    reason: str
    def __init__(self, reason: _Optional[str] = ...) -> None: ...

class ResourceTransferFrame(_message.Message):
    __slots__ = ("schema_version", "transfer_id", "start", "chunk", "finish", "abort")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    TRANSFER_ID_FIELD_NUMBER: _ClassVar[int]
    START_FIELD_NUMBER: _ClassVar[int]
    CHUNK_FIELD_NUMBER: _ClassVar[int]
    FINISH_FIELD_NUMBER: _ClassVar[int]
    ABORT_FIELD_NUMBER: _ClassVar[int]
    schema_version: int
    transfer_id: str
    start: DataResource
    chunk: ResourceChunk
    finish: ResourceTransferFinish
    abort: ResourceTransferAbort
    def __init__(self, schema_version: _Optional[int] = ..., transfer_id: _Optional[str] = ..., start: _Optional[_Union[DataResource, _Mapping]] = ..., chunk: _Optional[_Union[ResourceChunk, _Mapping]] = ..., finish: _Optional[_Union[ResourceTransferFinish, _Mapping]] = ..., abort: _Optional[_Union[ResourceTransferAbort, _Mapping]] = ...) -> None: ...
