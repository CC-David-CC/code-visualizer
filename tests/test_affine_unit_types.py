"""Quantity-kind decisions distinguish scalar scaling, products and equality."""

import pytest

from code_visualizer.domain.values import Dimension, DimensionPower
from code_visualizer.extensions.foundations.unit_algebra import (
    QuantityKind,
    residual_kind,
    result_kind,
)
from code_visualizer.extensions.foundations.units import UnitError

LINEAR, POINT, INTERVAL = QuantityKind.LINEAR, QuantityKind.POINT, QuantityKind.INTERVAL
DIMENSIONLESS = Dimension()
LENGTH = Dimension((DimensionPower("foundation.units.si:basis.length", 1),))
TEMPERATURE = Dimension((DimensionPower("foundation.units.si:basis.temperature", 1),))


@pytest.mark.parametrize("left", (LINEAR, POINT, INTERVAL))
@pytest.mark.parametrize("right", (LINEAR, POINT, INTERVAL))
def test_equality_kind_matrix_is_symmetric(left, right):
    if left is right:
        assert residual_kind(left, right) is (INTERVAL if left is POINT else left)
    else:
        with pytest.raises(UnitError) as caught:
            residual_kind(left, right)
        assert caught.value.issue.code == "UNIT_KIND_MISMATCH"


@pytest.mark.parametrize(
    "operator,left,right,left_dimension,right_dimension,expected",
    (
        ("multiply", INTERVAL, LINEAR, TEMPERATURE, DIMENSIONLESS, INTERVAL),
        ("multiply", LINEAR, INTERVAL, DIMENSIONLESS, TEMPERATURE, INTERVAL),
        ("divide", INTERVAL, LINEAR, TEMPERATURE, DIMENSIONLESS, INTERVAL),
        ("multiply", INTERVAL, LINEAR, TEMPERATURE, LENGTH, LINEAR),
        ("multiply", LINEAR, INTERVAL, LENGTH, TEMPERATURE, LINEAR),
        ("divide", INTERVAL, LINEAR, TEMPERATURE, LENGTH, LINEAR),
        ("divide", LINEAR, INTERVAL, DIMENSIONLESS, TEMPERATURE, LINEAR),
        ("multiply", INTERVAL, INTERVAL, TEMPERATURE, TEMPERATURE, LINEAR),
        ("divide", INTERVAL, INTERVAL, TEMPERATURE, TEMPERATURE, LINEAR),
    ),
)
def test_interval_scaling_needs_the_actual_scalar_dimension(
    operator, left, right, left_dimension, right_dimension, expected
):
    assert (
        result_kind(
            operator, left, right, left_dimension=left_dimension, right_dimension=right_dimension
        )
        is expected
    )


@pytest.mark.parametrize(
    "operator,left,right",
    (("multiply", INTERVAL, LINEAR), ("multiply", LINEAR, INTERVAL), ("divide", INTERVAL, LINEAR)),
)
def test_missing_dimension_is_not_implicit_dimensionless_permission(operator, left, right):
    with pytest.raises(UnitError) as caught:
        result_kind(operator, left, right)
    assert caught.value.issue.code == "UNIT_DIMENSION_REQUIRED"


@pytest.mark.parametrize("unsupported", tuple(QuantityKind)[3:])
@pytest.mark.parametrize("reverse", (False, True))
def test_unsupported_kinds_cannot_enter_equality_or_scalar_scaling(unsupported, reverse):
    left, right = (LINEAR, unsupported) if reverse else (unsupported, LINEAR)
    for operation in (
        lambda: residual_kind(left, right),
        lambda: residual_kind(unsupported, unsupported),
        lambda: result_kind(
            "multiply", left, right, left_dimension=DIMENSIONLESS, right_dimension=DIMENSIONLESS
        ),
    ):
        with pytest.raises(UnitError) as caught:
            operation()
        assert caught.value.issue.code == "UNIT_KIND_UNSUPPORTED"
