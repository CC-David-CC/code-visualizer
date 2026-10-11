from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class TensorDType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    TENSOR_DTYPE_UNSPECIFIED: _ClassVar[TensorDType]
    TENSOR_BOOL: _ClassVar[TensorDType]
    TENSOR_INT8: _ClassVar[TensorDType]
    TENSOR_UINT8: _ClassVar[TensorDType]
    TENSOR_INT16: _ClassVar[TensorDType]
    TENSOR_UINT16: _ClassVar[TensorDType]
    TENSOR_INT32: _ClassVar[TensorDType]
    TENSOR_UINT32: _ClassVar[TensorDType]
    TENSOR_INT64: _ClassVar[TensorDType]
    TENSOR_UINT64: _ClassVar[TensorDType]
    TENSOR_FLOAT32: _ClassVar[TensorDType]
    TENSOR_FLOAT64: _ClassVar[TensorDType]
    TENSOR_COMPLEX64: _ClassVar[TensorDType]
    TENSOR_COMPLEX128: _ClassVar[TensorDType]
TENSOR_DTYPE_UNSPECIFIED: TensorDType
TENSOR_BOOL: TensorDType
TENSOR_INT8: TensorDType
TENSOR_UINT8: TensorDType
TENSOR_INT16: TensorDType
TENSOR_UINT16: TensorDType
TENSOR_INT32: TensorDType
TENSOR_UINT32: TensorDType
TENSOR_INT64: TensorDType
TENSOR_UINT64: TensorDType
TENSOR_FLOAT32: TensorDType
TENSOR_FLOAT64: TensorDType
TENSOR_COMPLEX64: TensorDType
TENSOR_COMPLEX128: TensorDType

class IntegerValue(_message.Message):
    __slots__ = ("small", "decimal")
    SMALL_FIELD_NUMBER: _ClassVar[int]
    DECIMAL_FIELD_NUMBER: _ClassVar[int]
    small: int
    decimal: str
    def __init__(self, small: _Optional[int] = ..., decimal: _Optional[str] = ...) -> None: ...

class ComplexValue(_message.Message):
    __slots__ = ("real", "imaginary")
    REAL_FIELD_NUMBER: _ClassVar[int]
    IMAGINARY_FIELD_NUMBER: _ClassVar[int]
    real: float
    imaginary: float
    def __init__(self, real: _Optional[float] = ..., imaginary: _Optional[float] = ...) -> None: ...

class DimensionPower(_message.Message):
    __slots__ = ("basis_id", "exponent")
    BASIS_ID_FIELD_NUMBER: _ClassVar[int]
    EXPONENT_FIELD_NUMBER: _ClassVar[int]
    basis_id: str
    exponent: int
    def __init__(self, basis_id: _Optional[str] = ..., exponent: _Optional[int] = ...) -> None: ...

class RationalDimensionPower(_message.Message):
    __slots__ = ("basis_id", "numerator", "denominator")
    BASIS_ID_FIELD_NUMBER: _ClassVar[int]
    NUMERATOR_FIELD_NUMBER: _ClassVar[int]
    DENOMINATOR_FIELD_NUMBER: _ClassVar[int]
    basis_id: str
    numerator: int
    denominator: int
    def __init__(self, basis_id: _Optional[str] = ..., numerator: _Optional[int] = ..., denominator: _Optional[int] = ...) -> None: ...

class Dimension(_message.Message):
    __slots__ = ("powers", "schema_version", "rational_powers")
    POWERS_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    RATIONAL_POWERS_FIELD_NUMBER: _ClassVar[int]
    powers: _containers.RepeatedCompositeFieldContainer[DimensionPower]
    schema_version: int
    rational_powers: _containers.RepeatedCompositeFieldContainer[RationalDimensionPower]
    def __init__(self, powers: _Optional[_Iterable[_Union[DimensionPower, _Mapping]]] = ..., schema_version: _Optional[int] = ..., rational_powers: _Optional[_Iterable[_Union[RationalDimensionPower, _Mapping]]] = ...) -> None: ...

class UnitReference(_message.Message):
    __slots__ = ("id", "version", "dimension")
    ID_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    DIMENSION_FIELD_NUMBER: _ClassVar[int]
    id: str
    version: str
    dimension: Dimension
    def __init__(self, id: _Optional[str] = ..., version: _Optional[str] = ..., dimension: _Optional[_Union[Dimension, _Mapping]] = ...) -> None: ...

class NumericValue(_message.Message):
    __slots__ = ("integer", "floating", "complex")
    INTEGER_FIELD_NUMBER: _ClassVar[int]
    FLOATING_FIELD_NUMBER: _ClassVar[int]
    COMPLEX_FIELD_NUMBER: _ClassVar[int]
    integer: IntegerValue
    floating: float
    complex: ComplexValue
    def __init__(self, integer: _Optional[_Union[IntegerValue, _Mapping]] = ..., floating: _Optional[float] = ..., complex: _Optional[_Union[ComplexValue, _Mapping]] = ...) -> None: ...

class QuantityValue(_message.Message):
    __slots__ = ("magnitude", "unit")
    MAGNITUDE_FIELD_NUMBER: _ClassVar[int]
    UNIT_FIELD_NUMBER: _ClassVar[int]
    magnitude: NumericValue
    unit: UnitReference
    def __init__(self, magnitude: _Optional[_Union[NumericValue, _Mapping]] = ..., unit: _Optional[_Union[UnitReference, _Mapping]] = ...) -> None: ...

class TensorElement(_message.Message):
    __slots__ = ("boolean", "integer", "floating", "complex")
    BOOLEAN_FIELD_NUMBER: _ClassVar[int]
    INTEGER_FIELD_NUMBER: _ClassVar[int]
    FLOATING_FIELD_NUMBER: _ClassVar[int]
    COMPLEX_FIELD_NUMBER: _ClassVar[int]
    boolean: bool
    integer: IntegerValue
    floating: float
    complex: ComplexValue
    def __init__(self, boolean: bool = ..., integer: _Optional[_Union[IntegerValue, _Mapping]] = ..., floating: _Optional[float] = ..., complex: _Optional[_Union[ComplexValue, _Mapping]] = ...) -> None: ...

class TensorValue(_message.Message):
    __slots__ = ("dtype", "shape", "elements")
    DTYPE_FIELD_NUMBER: _ClassVar[int]
    SHAPE_FIELD_NUMBER: _ClassVar[int]
    ELEMENTS_FIELD_NUMBER: _ClassVar[int]
    dtype: TensorDType
    shape: _containers.RepeatedScalarFieldContainer[int]
    elements: _containers.RepeatedCompositeFieldContainer[TensorElement]
    def __init__(self, dtype: _Optional[_Union[TensorDType, str]] = ..., shape: _Optional[_Iterable[int]] = ..., elements: _Optional[_Iterable[_Union[TensorElement, _Mapping]]] = ...) -> None: ...

class ResourceReference(_message.Message):
    __slots__ = ("id", "content_hash")
    ID_FIELD_NUMBER: _ClassVar[int]
    CONTENT_HASH_FIELD_NUMBER: _ClassVar[int]
    id: str
    content_hash: str
    def __init__(self, id: _Optional[str] = ..., content_hash: _Optional[str] = ...) -> None: ...

class CanonicalValue(_message.Message):
    __slots__ = ("schema_version", "text", "boolean", "integer", "floating", "complex", "quantity", "tensor", "resource")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    BOOLEAN_FIELD_NUMBER: _ClassVar[int]
    INTEGER_FIELD_NUMBER: _ClassVar[int]
    FLOATING_FIELD_NUMBER: _ClassVar[int]
    COMPLEX_FIELD_NUMBER: _ClassVar[int]
    QUANTITY_FIELD_NUMBER: _ClassVar[int]
    TENSOR_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_FIELD_NUMBER: _ClassVar[int]
    schema_version: int
    text: str
    boolean: bool
    integer: IntegerValue
    floating: float
    complex: ComplexValue
    quantity: QuantityValue
    tensor: TensorValue
    resource: ResourceReference
    def __init__(self, schema_version: _Optional[int] = ..., text: _Optional[str] = ..., boolean: bool = ..., integer: _Optional[_Union[IntegerValue, _Mapping]] = ..., floating: _Optional[float] = ..., complex: _Optional[_Union[ComplexValue, _Mapping]] = ..., quantity: _Optional[_Union[QuantityValue, _Mapping]] = ..., tensor: _Optional[_Union[TensorValue, _Mapping]] = ..., resource: _Optional[_Union[ResourceReference, _Mapping]] = ...) -> None: ...

class ShapeExtent(_message.Message):
    __slots__ = ("size",)
    SIZE_FIELD_NUMBER: _ClassVar[int]
    size: int
    def __init__(self, size: _Optional[int] = ...) -> None: ...

class TensorShape(_message.Message):
    __slots__ = ("dimensions",)
    DIMENSIONS_FIELD_NUMBER: _ClassVar[int]
    dimensions: _containers.RepeatedCompositeFieldContainer[ShapeExtent]
    def __init__(self, dimensions: _Optional[_Iterable[_Union[ShapeExtent, _Mapping]]] = ...) -> None: ...

class ValueConstraints(_message.Message):
    __slots__ = ("dimension", "tensor_dtype", "tensor_shape")
    DIMENSION_FIELD_NUMBER: _ClassVar[int]
    TENSOR_DTYPE_FIELD_NUMBER: _ClassVar[int]
    TENSOR_SHAPE_FIELD_NUMBER: _ClassVar[int]
    dimension: Dimension
    tensor_dtype: TensorDType
    tensor_shape: TensorShape
    def __init__(self, dimension: _Optional[_Union[Dimension, _Mapping]] = ..., tensor_dtype: _Optional[_Union[TensorDType, str]] = ..., tensor_shape: _Optional[_Union[TensorShape, _Mapping]] = ...) -> None: ...
