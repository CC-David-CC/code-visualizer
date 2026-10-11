"""Closed, bounded canonical value contract. Domain meaning belongs to schemas."""

from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction

CANONICAL_VALUE_VERSION = 1
MAX_INLINE_ELEMENTS = 1024
MAX_TENSOR_RANK = 16
MAX_INLINE_BYTES = 65536
MAX_INTEGER_BITS = 4096


def _identity(value: str) -> None:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 1024:
        raise ValueError("A value identity must be nonempty text of at most 1024 bytes")


def _real(value: float) -> None:
    if type(value) is not float or not math.isfinite(value):
        raise ValueError("Real components must be finite floating-point numbers")


@dataclass(frozen=True, slots=True)
class ComplexValue:
    real: float
    imaginary: float

    def __post_init__(self) -> None:
        _real(self.real)
        _real(self.imaginary)


@dataclass(frozen=True, slots=True)
class DimensionPower:
    basis_id: str
    exponent: int | Fraction

    def __post_init__(self) -> None:
        _identity(self.basis_id)
        if type(self.exponent) not in (int, Fraction):
            raise ValueError("Dimension exponents require exact integers or rational powers")
        power = Fraction(self.exponent)
        if not power or not -32768 <= power.numerator <= 32767 or power.denominator > 32767:
            raise ValueError("Dimension exponents require bounded nonzero rational powers")
        # One normalized value; integral powers retain their released representation.
        object.__setattr__(self, "exponent", power.numerator if power.denominator == 1 else power)


@dataclass(frozen=True, slots=True)
class Dimension:
    powers: tuple[DimensionPower, ...] = ()

    def __post_init__(self) -> None:
        if type(self.powers) is not tuple or len(self.powers) > MAX_TENSOR_RANK:
            raise ValueError("Dimension powers must be a bounded immutable tuple")
        if any(not isinstance(power, DimensionPower) for power in self.powers):
            raise ValueError("Expected dimension powers")
        ids = tuple(power.basis_id for power in self.powers)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("Dimension bases must be unique and sorted by identity")

    @property
    def integral(self) -> bool:
        return all(type(power.exponent) is int for power in self.powers)


@dataclass(frozen=True, slots=True)
class UnitReference:
    id: str
    version: str
    dimension: Dimension

    def __post_init__(self) -> None:
        _identity(self.id)
        _identity(self.version)
        if not isinstance(self.dimension, Dimension):
            raise ValueError("Unit references require a dimension contract")


@dataclass(frozen=True, slots=True)
class QuantityValue:
    magnitude: int | float | ComplexValue
    unit: UnitReference

    def __post_init__(self) -> None:
        if type(self.magnitude) not in (int, float, ComplexValue):
            raise ValueError("A quantity magnitude must be integer, real or complex")
        validate_canonical_value(self.magnitude)
        if not isinstance(self.unit, UnitReference):
            raise ValueError("A quantity requires a versioned unit reference")


class TensorDType(StrEnum):
    BOOL = "bool"
    INT8 = "int8"
    UINT8 = "uint8"
    INT16 = "int16"
    UINT16 = "uint16"
    INT32 = "int32"
    UINT32 = "uint32"
    INT64 = "int64"
    UINT64 = "uint64"
    FLOAT32 = "float32"
    FLOAT64 = "float64"
    COMPLEX64 = "complex64"
    COMPLEX128 = "complex128"


def validate_shape(shape: tuple[int, ...], *, inline: bool = False) -> None:
    if type(shape) is not tuple or len(shape) > MAX_TENSOR_RANK:
        raise ValueError("Tensor shape must be an immutable tuple with at most 16 axes")
    if any(type(size) is not int or not 0 <= size <= (1 << 63) - 1 for size in shape):
        raise ValueError("Tensor dimensions must be nonnegative signed 64-bit integers")
    if math.prod(shape) > (MAX_INLINE_ELEMENTS if inline else (1 << 63) - 1):
        raise ValueError("Tensor shape exceeds the inline or resource element bound")


def _tensor_element(dtype: TensorDType, value: bool | int | float | ComplexValue) -> None:
    kind = dtype.value
    if dtype is TensorDType.BOOL:
        if type(value) is not bool:
            raise ValueError("Boolean tensors require boolean elements")
    elif kind.startswith(("int", "uint")):
        bits = int(kind.removeprefix("uint").removeprefix("int"))
        signed = kind.startswith("int")
        low, high = (-(1 << (bits - 1)), (1 << (bits - 1)) - 1) if signed else (0, (1 << bits) - 1)
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"Tensor element outside {kind} range")
    elif kind.startswith("float"):
        if type(value) is not float:
            raise ValueError("Real tensors require real elements")
        _real(value)
        if dtype is TensorDType.FLOAT32:
            try:
                rounded = struct.unpack("f", struct.pack("f", value))[0]
            except OverflowError as exc:
                raise ValueError("Tensor element outside float32 range") from exc
            if rounded != value:
                raise ValueError("float32 elements must be exactly representable; round explicitly")
    else:
        if not isinstance(value, ComplexValue):
            raise ValueError("Complex tensors require complex elements")
        if dtype is TensorDType.COMPLEX64:
            _tensor_element(TensorDType.FLOAT32, value.real)
            _tensor_element(TensorDType.FLOAT32, value.imaginary)


@dataclass(frozen=True, slots=True)
class TensorValue:
    dtype: TensorDType
    shape: tuple[int, ...]
    elements: tuple[bool | int | float | ComplexValue, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.dtype, TensorDType):
            raise ValueError("Unknown tensor dtype")
        validate_shape(self.shape, inline=True)
        if type(self.elements) is not tuple or len(self.elements) != math.prod(self.shape):
            raise ValueError("Tensor elements must be immutable and match the shape")
        for element in self.elements:
            _tensor_element(self.dtype, element)


@dataclass(frozen=True, slots=True)
class ResourceReference:
    id: str
    content_hash: str

    def __post_init__(self) -> None:
        _identity(self.id)
        if (
            not isinstance(self.content_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.content_hash) is None
        ):
            raise ValueError("Resources require a lowercase SHA-256 content hash")


type CanonicalValue = (
    str | bool | int | float | ComplexValue | QuantityValue | TensorValue | ResourceReference
)


def canonical_value_key(value: CanonicalValue) -> tuple[object, ...]:
    """Storage equality preserves variants and floating bits; domain operators
    may separately define mathematical equality. No serialization dependency.
    """
    if type(value) is str:
        return ("text", value)
    if type(value) is bool:
        return ("boolean", value)
    if type(value) is int:
        return ("integer", value)
    if type(value) is float:
        return ("real", value.hex())
    if isinstance(value, ComplexValue):
        return ("complex", value.real.hex(), value.imaginary.hex())
    if isinstance(value, QuantityValue):
        return ("quantity", canonical_value_key(value.magnitude), value.unit)
    if isinstance(value, TensorValue):
        return (
            "tensor",
            value.dtype,
            value.shape,
            tuple(canonical_value_key(item) for item in value.elements),
        )
    if isinstance(value, ResourceReference):
        return ("resource", value.id, value.content_hash)
    raise ValueError("Unknown canonical value variant")


@dataclass(frozen=True, slots=True)
class ValueConstraints:
    dimension: Dimension | None = None
    tensor_dtype: TensorDType | None = None
    tensor_shape: tuple[int | None, ...] | None = None

    def __post_init__(self) -> None:
        if self.dimension is not None and not isinstance(self.dimension, Dimension):
            raise ValueError("Expected dimension constraint")
        if self.tensor_dtype is not None and not isinstance(self.tensor_dtype, TensorDType):
            raise ValueError("Expected tensor dtype constraint")
        if self.tensor_shape is not None:
            if type(self.tensor_shape) is not tuple or len(self.tensor_shape) > MAX_TENSOR_RANK:
                raise ValueError("Expected bounded immutable tensor shape constraint")
            if any(
                size is not None and (type(size) is not int or not 0 <= size < 1 << 63)
                for size in self.tensor_shape
            ):
                raise ValueError(
                    "Shape constraints contain nonnegative dimensions or unconstrained axes"
                )


def validate_canonical_value(value: object) -> None:
    """Reject unbounded or untyped data at every canonical admission boundary."""
    if type(value) is str:
        if len(value.encode("utf-8")) > MAX_INLINE_BYTES:
            raise ValueError("Inline text exceeds 64 KiB; use a resource")
    elif type(value) is bool:
        return
    elif type(value) is int:
        if value.bit_length() > MAX_INTEGER_BITS:
            raise ValueError("Canonical integers exceed the 4096-bit bound")
    elif type(value) is float:
        _real(value)
    elif type(value) not in (ComplexValue, QuantityValue, TensorValue, ResourceReference):
        raise ValueError("Unknown canonical value variant")


def value_satisfies(value: CanonicalValue, constraints: ValueConstraints) -> bool:
    if constraints.dimension is not None and (
        not isinstance(value, QuantityValue) or value.unit.dimension != constraints.dimension
    ):
        return False
    if constraints.tensor_dtype is not None and (
        not isinstance(value, TensorValue) or value.dtype != constraints.tensor_dtype
    ):
        return False
    if constraints.tensor_shape is not None:
        if not isinstance(value, TensorValue) or len(value.shape) != len(constraints.tensor_shape):
            return False
        if any(
            expected is not None and actual != expected
            for actual, expected in zip(value.shape, constraints.tensor_shape, strict=True)
        ):
            return False
    return True
