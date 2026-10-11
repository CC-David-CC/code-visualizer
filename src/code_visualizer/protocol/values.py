"""Lossless direct adapters between canonical values and generated protobuf messages."""

from __future__ import annotations

import re
from fractions import Fraction
from typing import cast

from code_visualizer.domain.values import (
    CanonicalValue,
    ComplexValue,
    Dimension,
    DimensionPower,
    QuantityValue,
    ResourceReference,
    TensorDType,
    TensorValue,
    UnitReference,
    ValueConstraints,
    validate_canonical_value,
)
from code_visualizer.protocol.v1 import value_pb2 as wire
from code_visualizer.protocol.validation import check_message, invalid, require_field

_DTYPES = tuple(TensorDType)


def dtype_to_proto(value: TensorDType) -> wire.TensorDType:
    return cast(wire.TensorDType, wire.TensorDType.Value("TENSOR_" + value.value.upper()))


def dtype_from_proto(value: int) -> TensorDType:
    try:
        return TensorDType(wire.TensorDType.Name(value).removeprefix("TENSOR_").lower())
    except ValueError as exc:
        raise invalid("Unknown tensor dtype") from exc


def integer_to_proto(value: int) -> wire.IntegerValue:
    validate_canonical_value(value)
    if type(value) is not int:
        raise invalid("Integer payload requires an integer")
    return (
        wire.IntegerValue(small=value)
        if -(1 << 63) <= value < 1 << 63
        else wire.IntegerValue(decimal=str(value))
    )


def integer_from_proto(value: wire.IntegerValue) -> int:
    check_message(value)
    kind = value.WhichOneof("representation")
    if kind == "small":
        return value.small
    if kind != "decimal" or re.fullmatch(r"-?[1-9][0-9]{0,1233}", value.decimal) is None:
        raise invalid("Integer requires sint64 or bounded canonical decimal representation")
    result = int(value.decimal)
    validate_canonical_value(result)
    if -(1 << 63) <= result < 1 << 63:
        raise invalid("Integers within sint64 range must use the small representation")
    return result


def dimension_to_proto(value: Dimension) -> wire.Dimension:
    if not value.integral:
        return wire.Dimension(
            schema_version=2,
            rational_powers=[
                wire.RationalDimensionPower(
                    basis_id=p.basis_id,
                    numerator=Fraction(p.exponent).numerator,
                    denominator=Fraction(p.exponent).denominator,
                )
                for p in value.powers
            ],
        )
    return wire.Dimension(
        powers=[
            wire.DimensionPower(basis_id=p.basis_id, exponent=int(p.exponent)) for p in value.powers
        ]
    )


def dimension_from_proto(value: wire.Dimension) -> Dimension:
    check_message(value)
    if value.schema_version == 2:
        if value.powers or len(value.rational_powers) > 16:
            raise invalid("Rational dimensions cannot contain legacy powers or exceed 16 bases")
        powers = []
        for power in value.rational_powers:
            if not -32768 <= power.numerator <= 32767 or not 1 <= power.denominator <= 32767:
                raise invalid("Rational dimension exceeds its bound")
            powers.append(
                DimensionPower(power.basis_id, Fraction(power.numerator, power.denominator))
            )
        result = Dimension(tuple(powers))
        if dimension_to_proto(result) != value:
            raise invalid("Rational dimension must use normalized version 2 encoding")
        return result
    if value.schema_version or value.rational_powers:
        raise invalid("Unsupported dimension version or mixed encoding")
    return Dimension(tuple(DimensionPower(p.basis_id, p.exponent) for p in value.powers))


def unit_to_proto(value: UnitReference) -> wire.UnitReference:
    return wire.UnitReference(
        id=value.id, version=value.version, dimension=dimension_to_proto(value.dimension)
    )


def unit_from_proto(value: wire.UnitReference) -> UnitReference:
    check_message(value)
    require_field(value, "dimension")
    return UnitReference(value.id, value.version, dimension_from_proto(value.dimension))


def resource_reference_to_proto(value: ResourceReference) -> wire.ResourceReference:
    return wire.ResourceReference(id=value.id, content_hash=value.content_hash)


def resource_reference_from_proto(value: wire.ResourceReference) -> ResourceReference:
    check_message(value)
    return ResourceReference(value.id, value.content_hash)


def numeric_to_proto(value: int | float | ComplexValue) -> wire.NumericValue:
    validate_canonical_value(value)
    if type(value) is int:
        return wire.NumericValue(integer=integer_to_proto(value))
    if type(value) is float:
        return wire.NumericValue(floating=value)
    if isinstance(value, ComplexValue):
        return wire.NumericValue(
            complex=wire.ComplexValue(real=value.real, imaginary=value.imaginary)
        )
    raise invalid("Quantity magnitude must be integer, floating or complex")


def numeric_from_proto(value: wire.NumericValue) -> int | float | ComplexValue:
    kind = value.WhichOneof("value")
    if kind == "integer":
        return integer_from_proto(value.integer)
    if kind == "floating":
        validate_canonical_value(value.floating)
        return value.floating
    if kind == "complex":
        return ComplexValue(value.complex.real, value.complex.imaginary)
    raise invalid("Numeric value must select a known variant")


def element_to_proto(value: bool | int | float | ComplexValue) -> wire.TensorElement:
    if type(value) is bool:
        return wire.TensorElement(boolean=value)
    if type(value) is int:
        return wire.TensorElement(integer=integer_to_proto(value))
    if type(value) is float:
        return wire.TensorElement(floating=value)
    if isinstance(value, ComplexValue):
        return wire.TensorElement(
            complex=wire.ComplexValue(real=value.real, imaginary=value.imaginary)
        )
    raise invalid("Unknown tensor element variant")


def element_from_proto(value: wire.TensorElement) -> bool | int | float | ComplexValue:
    kind = value.WhichOneof("value")
    if kind == "boolean":
        return value.boolean
    if kind == "integer":
        return integer_from_proto(value.integer)
    if kind == "floating":
        return value.floating
    if kind == "complex":
        return ComplexValue(value.complex.real, value.complex.imaginary)
    raise invalid("Tensor element must select a known variant")


def canonical_value_to_proto(value: CanonicalValue) -> wire.CanonicalValue:
    validate_canonical_value(value)
    result = wire.CanonicalValue(schema_version=1)
    if type(value) is str:
        result.text = value
    elif type(value) is bool:
        result.boolean = value
    elif type(value) is int:
        result.integer.CopyFrom(integer_to_proto(value))
    elif type(value) is float:
        result.floating = value
    elif isinstance(value, ComplexValue):
        result.complex.CopyFrom(wire.ComplexValue(real=value.real, imaginary=value.imaginary))
    elif isinstance(value, QuantityValue):
        result.schema_version = 1 if value.unit.dimension.integral else 2
        result.quantity.CopyFrom(
            wire.QuantityValue(
                magnitude=numeric_to_proto(value.magnitude), unit=unit_to_proto(value.unit)
            )
        )
    elif isinstance(value, TensorValue):
        result.tensor.CopyFrom(
            wire.TensorValue(
                dtype=dtype_to_proto(value.dtype),
                shape=value.shape,
                elements=[element_to_proto(e) for e in value.elements],
            )
        )
    elif isinstance(value, ResourceReference):
        result.resource.CopyFrom(resource_reference_to_proto(value))
    check_message(result)
    return result


def canonical_value_from_proto(value: wire.CanonicalValue) -> CanonicalValue:
    kind = value.WhichOneof("value")
    if kind == "quantity" and value.schema_version == 2:
        check_message(value)
    else:
        check_message(value, version=value.schema_version)
    result: CanonicalValue
    if kind == "text":
        result = value.text
    elif kind == "boolean":
        result = value.boolean
    elif kind == "integer":
        result = integer_from_proto(value.integer)
    elif kind == "floating":
        result = value.floating
    elif kind == "complex":
        result = ComplexValue(value.complex.real, value.complex.imaginary)
    elif kind == "quantity":
        require_field(value.quantity, "magnitude")
        require_field(value.quantity, "unit")
        result = QuantityValue(
            numeric_from_proto(value.quantity.magnitude), unit_from_proto(value.quantity.unit)
        )
        if value.schema_version != (1 if result.unit.dimension.integral else 2):
            raise invalid("Quantity version must match its dimension contract")
    elif kind == "tensor":
        result = TensorValue(
            dtype_from_proto(value.tensor.dtype),
            tuple(value.tensor.shape),
            tuple(element_from_proto(e) for e in value.tensor.elements),
        )
    elif kind == "resource":
        result = resource_reference_from_proto(value.resource)
    else:
        raise invalid("CanonicalValue must select a known variant; null is absence, not a value")
    validate_canonical_value(result)
    return result


def constraints_to_proto(value: ValueConstraints) -> wire.ValueConstraints:
    result = wire.ValueConstraints()
    if value.dimension is not None:
        result.dimension.CopyFrom(dimension_to_proto(value.dimension))
    if value.tensor_dtype is not None:
        result.tensor_dtype = dtype_to_proto(value.tensor_dtype)
    if value.tensor_shape is not None:
        result.tensor_shape.CopyFrom(
            wire.TensorShape(
                dimensions=[
                    wire.ShapeExtent() if n is None else wire.ShapeExtent(size=n)
                    for n in value.tensor_shape
                ]
            )
        )
    return result


def constraints_from_proto(value: wire.ValueConstraints) -> ValueConstraints:
    check_message(value)
    return ValueConstraints(
        dimension_from_proto(value.dimension) if value.HasField("dimension") else None,
        dtype_from_proto(value.tensor_dtype) if value.HasField("tensor_dtype") else None,
        tuple(n.size if n.HasField("size") else None for n in value.tensor_shape.dimensions)
        if value.HasField("tensor_shape")
        else None,
    )
