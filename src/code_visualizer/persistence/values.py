"""Lossless versioned native codecs for the closed canonical value algebra."""

from __future__ import annotations

from fractions import Fraction

from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.values import (
    CANONICAL_VALUE_VERSION,
    MAX_INLINE_ELEMENTS,
    MAX_TENSOR_RANK,
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


def object_data(value: object, fields: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("Expected a typed value object")
    if set(value) - fields:
        raise ValueError(f"Unknown fields in typed value: {sorted(set(value) - fields)}")
    return dict(value)


def text_data(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected text")
    return value


def integer_data(value: object) -> int:
    if type(value) is not int:
        raise ValueError("Expected integer")
    return value


def array_data(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("Expected array")
    return value


def dimension_to_data(value: Dimension) -> dict[str, JsonValue]:
    if not value.integral:
        return {
            "version": 2,
            "powers": [
                {
                    "basis_id": power.basis_id,
                    "numerator": Fraction(power.exponent).numerator,
                    "denominator": Fraction(power.exponent).denominator,
                }
                for power in value.powers
            ],
        }
    return {
        "powers": [
            {"basis_id": power.basis_id, "exponent": int(power.exponent)} for power in value.powers
        ]
    }


def dimension_from_data(value: object) -> Dimension:
    data = object_data(value, {"powers", "version"})
    raw_powers = array_data(data.get("powers"))
    if len(raw_powers) > MAX_TENSOR_RANK:
        raise ValueError("Dimension exceeds the 16-basis bound")
    if "version" in data:
        if type(data["version"]) is not int or data["version"] != 2:
            raise ValueError("Unsupported dimension version")
        result = []
        for raw in raw_powers:
            power = object_data(raw, {"basis_id", "numerator", "denominator"})
            numerator = integer_data(power.get("numerator"))
            denominator = integer_data(power.get("denominator"))
            if not -32768 <= numerator <= 32767 or not 1 <= denominator <= 32767:
                raise ValueError("Rational dimension exceeds its bound")
            result.append(
                DimensionPower(text_data(power.get("basis_id")), Fraction(numerator, denominator))
            )
        dimension = Dimension(tuple(result))
        if dimension_to_data(dimension) != data:
            raise ValueError("Rational dimension must use normalized version 2 encoding")
        return dimension
    powers = [object_data(power, {"basis_id", "exponent"}) for power in raw_powers]
    return Dimension(
        tuple(
            DimensionPower(text_data(power.get("basis_id")), integer_data(power.get("exponent")))
            for power in powers
        )
    )


def unit_to_data(value: UnitReference) -> dict[str, JsonValue]:
    return {
        "id": value.id,
        "version": value.version,
        "dimension": dimension_to_data(value.dimension),
    }


def unit_from_data(value: object) -> UnitReference:
    data = object_data(value, {"id", "version", "dimension"})
    return UnitReference(
        text_data(data.get("id")),
        text_data(data.get("version")),
        dimension_from_data(data.get("dimension")),
    )


def canonical_value_to_data(value: CanonicalValue) -> JsonValue:
    validate_canonical_value(value)
    if isinstance(value, (str, bool, int, float)):
        return value
    fields: dict[str, JsonValue]
    if isinstance(value, ComplexValue):
        kind, fields = "complex", {"real": value.real, "imaginary": value.imaginary}
    elif isinstance(value, QuantityValue):
        kind, fields = (
            "quantity",
            {
                "magnitude": canonical_value_to_data(value.magnitude),
                "unit": unit_to_data(value.unit),
            },
        )
    elif isinstance(value, TensorValue):
        kind, fields = (
            "tensor",
            {
                "dtype": value.dtype.value,
                "shape": list(value.shape),
                "elements": [canonical_value_to_data(item) for item in value.elements],
            },
        )
    else:
        kind, fields = "resource", {"id": value.id, "content_hash": value.content_hash}
    version = (
        2
        if isinstance(value, QuantityValue) and not value.unit.dimension.integral
        else CANONICAL_VALUE_VERSION
    )
    return {"$value": kind, "version": version, **fields}


def canonical_value_from_data(value: object) -> CanonicalValue:
    if type(value) in (str, bool, int, float):
        validate_canonical_value(value)
        assert isinstance(value, (str, bool, int, float))
        return value
    if not isinstance(value, dict):
        raise ValueError("Unknown canonical value variant")
    kind = value.get("$value")
    if type(value.get("version")) is not int or value.get("version") not in (
        (1, 2) if kind == "quantity" else (CANONICAL_VALUE_VERSION,)
    ):
        raise ValueError("Unsupported canonical value version")
    fields = {"$value", "version"}
    if kind == "complex":
        data = object_data(value, fields | {"real", "imaginary"})
        real, imaginary = data.get("real"), data.get("imaginary")
        if type(real) is not float or type(imaginary) is not float:
            raise ValueError("Complex components must be real values")
        return ComplexValue(real, imaginary)
    if kind == "quantity":
        data = object_data(value, fields | {"magnitude", "unit"})
        magnitude = numeric_value_from_data(data.get("magnitude"))
        quantity = QuantityValue(magnitude, unit_from_data(data.get("unit")))
        if data.get("version") != (1 if quantity.unit.dimension.integral else 2):
            raise ValueError("Quantity version must match its dimension contract")
        return quantity
    if kind == "tensor":
        data = object_data(value, fields | {"dtype", "shape", "elements"})
        raw_elements = array_data(data.get("elements"))
        if len(raw_elements) > MAX_INLINE_ELEMENTS:
            raise ValueError("Inline tensor exceeds 1024 elements; use a resource")
        raw_shape = array_data(data.get("shape"))
        if len(raw_shape) > MAX_TENSOR_RANK:
            raise ValueError("Tensor exceeds the 16-axis bound")
        elements = tuple(
            item if type(item) is bool else numeric_value_from_data(item) for item in raw_elements
        )
        return TensorValue(
            TensorDType(text_data(data.get("dtype"))),
            tuple(integer_data(item) for item in raw_shape),
            elements,
        )
    if kind == "resource":
        data = object_data(value, fields | {"id", "content_hash"})
        return ResourceReference(text_data(data.get("id")), text_data(data.get("content_hash")))
    raise ValueError(f"Unknown canonical value variant: {kind!r}")


def numeric_value_from_data(value: object) -> int | float | ComplexValue:
    # Validate the slot before delegation: recursively nested compounds are not
    # numeric magnitudes/elements and must fail without traversing their contents.
    if type(value) not in (int, float) and not (
        isinstance(value, dict) and value.get("$value") == "complex"
    ):
        raise ValueError("Numeric slots require an integer, real or complex value")
    result = canonical_value_from_data(value)
    assert not isinstance(result, bool) and isinstance(result, (int, float, ComplexValue))
    return result


def value_constraints_to_data(value: ValueConstraints) -> dict[str, JsonValue]:
    return {
        "dimension": None if value.dimension is None else dimension_to_data(value.dimension),
        "tensor_dtype": None if value.tensor_dtype is None else value.tensor_dtype.value,
        "tensor_shape": None if value.tensor_shape is None else list(value.tensor_shape),
    }


def value_constraints_from_data(value: object) -> ValueConstraints:
    data = object_data(value, {"dimension", "tensor_dtype", "tensor_shape"})
    dimension, dtype, shape = (
        data.get("dimension"),
        data.get("tensor_dtype"),
        data.get("tensor_shape"),
    )
    return ValueConstraints(
        None if dimension is None else dimension_from_data(dimension),
        None if dtype is None else TensorDType(text_data(dtype)),
        None
        if shape is None
        else tuple(None if size is None else integer_data(size) for size in array_data(shape)),
    )
