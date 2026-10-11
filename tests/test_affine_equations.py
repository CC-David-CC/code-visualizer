"""Affine relations retain their meaning through the canonical equation compiler."""

from dataclasses import replace
from fractions import Fraction

import pytest
from test_equation_compiler import EquationCase, quantity, solve, system

from code_visualizer.domain.intentional import PropertyValue
from code_visualizer.domain.values import Dimension, QuantityValue, UnitReference
from code_visualizer.extensions.foundations.equation_compiler import EquationCompiler, EquationError
from code_visualizer.extensions.foundations.math import identity
from code_visualizer.extensions.foundations.unit_algebra import QuantityKind, dimension_product
from code_visualizer.extensions.foundations.unit_algebra_si import algebra_si_catalog
from code_visualizer.extensions.foundations.units import UnitDefinition


def translation_model(
    operator="multiply",
    *,
    reverse=False,
    factor=2,
    bound=False,
    output_unit="degree_celsius",
    residual_unit="kelvin",
):
    case = EquationCase()
    case.symbol("T", quantity(1, output_unit), "point")
    if bound:
        case.symbol("initial", quantity(1, "degree_celsius"), "point")
        case.symbol("delta", quantity(1, "degree_celsius"), "interval")
        case.symbol("factor", quantity(1))
        case.bind("initial", quantity(293.15, "kelvin"))
        case.bind("delta", quantity(10, "kelvin"))
        case.bind("factor", quantity(factor))
        initial = case.ref("initial-ref", "initial")
        delta = case.ref("delta-ref", "delta")
        scalar = case.ref("factor-ref", "factor")
    else:
        initial = case.value("initial", quantity(20, "degree_celsius"), "point")
        delta = case.value("delta", quantity(10, "kelvin"), "interval")
        scalar = case.value("factor", factor)
    operands = (scalar, delta) if reverse else (delta, scalar)
    changed = case.op("scaled-interval", operator, *operands)
    translated = case.op("translated", "add", initial, changed)
    case.equation("temperature", case.ref("out", "T"), translated, quantity(1, residual_unit))
    return case.model(("T",))


def mixed_relation_model(reverse=False):
    case = EquationCase()
    case.symbol("T", quantity(1, "degree_celsius"), "point")
    left = case.ref("out", "T")
    right = case.value("interval", quantity(10, "kelvin"), "interval")
    if reverse:
        left, right = right, left
    case.equation("bad-equality", left, right, quantity(1, "kelvin"))
    return case.model(("T",))


@pytest.mark.parametrize("left_kind", ("linear", "point", "interval"))
@pytest.mark.parametrize("right_kind", ("linear", "point", "interval"))
def test_compiled_equality_kind_matrix(left_kind, right_kind):
    case = EquationCase()
    case.symbol("x", quantity(1, "meter"), left_kind)
    case.equation(
        "relation",
        case.ref("left", "x"),
        case.value("right", quantity(10, "meter"), right_kind),
        quantity(1, "meter"),
    )
    model = case.model(("x",))
    if left_kind == right_kind:
        assert solve(model)[0]["x"] == pytest.approx(10)
    else:
        with pytest.raises(EquationError) as caught:
            system(model)
        assert caught.value.code == "UNIT_KIND_MISMATCH"
        assert caught.value.semantic_id == "relation"


@pytest.mark.parametrize("reverse", (False, True))
def test_mixed_equality_never_reaches_matrix_construction(reverse, monkeypatch):
    sympy = pytest.importorskip("sympy")

    def forbidden(*args, **kwargs):
        pytest.fail("An incompatible equality reached matrix construction")

    monkeypatch.setattr(sympy, "linear_eq_to_matrix", forbidden)
    with pytest.raises(EquationError) as caught:
        system(mixed_relation_model(reverse))
    assert caught.value.code == "UNIT_KIND_MISMATCH"
    assert caught.value.semantic_id == "bad-equality"


@pytest.mark.parametrize("bound", (False, True))
@pytest.mark.parametrize(
    "operator,reverse,factor,expected",
    (
        ("multiply", False, 2, 40),
        ("multiply", True, 2, 40),
        ("divide", False, 2, 25),
        ("multiply", False, 0, 20),
        ("multiply", True, -2, 0),
        ("divide", False, -2, 15),
    ),
)
def test_literal_and_bound_scalar_translation(operator, reverse, factor, expected, bound):
    values, compiled, result = solve(
        translation_model(operator, reverse=reverse, factor=factor, bound=bound)
    )
    assert values["T"] == pytest.approx(expected, abs=1e-12)
    assert compiled.variables[0].kind is QuantityKind.POINT
    assert result.normalized_residuals == pytest.approx((0,), abs=1e-12)


@pytest.mark.parametrize("output_unit", ("degree_celsius", "kelvin"))
@pytest.mark.parametrize("residual_unit", ("degree_celsius", "kelvin"))
def test_point_residual_scale_has_no_coordinate_offset(output_unit, residual_unit):
    values, compiled, result = solve(
        translation_model(output_unit=output_unit, residual_unit=residual_unit)
    )
    assert values["T"] == pytest.approx(40 if output_unit == "degree_celsius" else 313.15)
    assert compiled.residuals[0].base_scale == pytest.approx(1)
    assert compiled.residuals[0].unit_scale == pytest.approx(1)
    assert compiled.residuals[0].scale.unit == quantity(1, residual_unit).unit
    assert result.residuals == pytest.approx((0,), abs=1e-12)


@pytest.mark.parametrize("reverse", (False, True))
@pytest.mark.parametrize("failure", ("dimension", "conversion"))
def test_equality_still_requires_dimensions_and_declared_conversion(failure, reverse):
    case = EquationCase()
    case.symbol("x", quantity(1, "meter"), "interval")
    catalog = algebra_si_catalog()
    unit = quantity(1, "second").unit
    if failure == "conversion":
        unit = UnitReference(
            "org.example.units:unconnected_length", "1", quantity(1, "meter").unit.dimension
        )
        catalog = replace(
            catalog, units=(*catalog.units, UnitDefinition("custom", unit, "Other length", "u"))
        )
    left, right = case.ref("left", "x"), case.value("right", QuantityValue(10, unit), "interval")
    if reverse:
        left, right = right, left
    case.equation("relation", left, right, quantity(1, "meter"))
    with pytest.raises(EquationError) as caught:
        EquationCompiler(case.model(("x",)), catalog).compile()
    assert caught.value.code == (
        "EQUATION_DIMENSION_MISMATCH" if failure == "dimension" else "UNIT_CONVERSION_UNAVAILABLE"
    )
    assert caught.value.semantic_id == "relation"


def test_dimensionless_scaling_does_not_authorize_an_unrelated_unit():
    case = EquationCase()
    case.symbol("x", quantity(1, "kelvin"), "interval")
    scalar_unit = UnitReference("org.example.units:unconnected_scalar", "1", Dimension())
    catalog = algebra_si_catalog()
    catalog = replace(
        catalog, units=(*catalog.units, UnitDefinition("custom", scalar_unit, "Other scalar", "s"))
    )
    product = case.op(
        "product",
        "multiply",
        case.value("delta", quantity(10, "kelvin"), "interval"),
        case.value("scalar", QuantityValue(2, scalar_unit)),
    )
    case.equation("relation", case.ref("left", "x"), product, quantity(1, "kelvin"))
    with pytest.raises(EquationError) as caught:
        EquationCompiler(case.model(("x",)), catalog).compile()
    assert caught.value.code == "UNIT_CONVERSION_UNAVAILABLE"
    assert caught.value.semantic_id == "relation"


@pytest.mark.parametrize("operator", ("multiply", "divide"))
def test_interval_dimensional_products_compose_dimensions_and_lose_affine_kind(operator):
    case = EquationCase()
    node_id = case.op(
        "product",
        operator,
        case.value("delta", quantity(10, "kelvin"), "interval"),
        case.value("distance", quantity(2, "meter")),
    )
    model = case.model(())
    compiler = EquationCompiler(model, algebra_si_catalog())
    result = compiler.expression(model.node(node_id))
    assert result.kind is QuantityKind.LINEAR
    assert result.dimension == dimension_product(
        (
            (quantity(1, "kelvin").unit.dimension, Fraction(1)),
            (quantity(1, "meter").unit.dimension, Fraction(1 if operator == "multiply" else -1)),
        )
    )
    # The private coefficient uses catalog anchors (the length anchor need not
    # be a meter). Compare physical magnitudes in the stated input units.
    temperature_scale = compiler.algebra.form(
        quantity(1, "kelvin").unit, QuantityKind.INTERVAL
    ).scale
    length_scale = compiler.algebra.form(quantity(1, "meter").unit).scale
    output_scale = temperature_scale * (
        length_scale if operator == "multiply" else 1 / length_scale
    )
    assert float(result.number) / output_scale == pytest.approx(20 if operator == "multiply" else 5)


@pytest.mark.parametrize(
    "operator,left_kind,right_kind,code",
    (
        ("add", "point", "point", "UNIT_KIND_MISMATCH"),
        ("add", "point", "linear", "UNIT_KIND_MISMATCH"),
        ("subtract", "interval", "point", "UNIT_KIND_MISMATCH"),
        ("multiply", "point", "linear", "UNIT_POINT_OPERATION"),
        ("divide", "point", "linear", "UNIT_POINT_OPERATION"),
        ("divide", "linear", "point", "UNIT_POINT_OPERATION"),
        ("negate", "point", None, "UNIT_POINT_OPERATION"),
    ),
)
def test_illegal_nested_point_operations_report_the_innermost_origin(
    operator, left_kind, right_kind, code
):
    case = EquationCase()
    case.symbol("x", quantity(1, "degree_celsius"), "point")
    operands = [case.value("left", quantity(20, "degree_celsius"), left_kind)]
    if right_kind is not None:
        operands.append(case.value("right", quantity(2, "degree_celsius"), right_kind))
    invalid = case.op("invalid-operation", operator, *operands)
    outer = case.op("outer", "add", invalid, case.value("delta", quantity(1, "kelvin"), "interval"))
    case.equation("relation", case.ref("out", "x"), outer, quantity(1, "kelvin"))
    with pytest.raises(EquationError) as caught:
        system(case.model(("x",)))
    assert (caught.value.code, caught.value.semantic_id) == (code, "invalid-operation")


@pytest.mark.parametrize(
    "unit,value,code",
    (
        ("kelvin", 0, "EQUATION_SCALE"),
        ("kelvin", -1, "EQUATION_SCALE"),
        ("meter", 1, "EQUATION_DIMENSION_MISMATCH"),
    ),
)
def test_invalid_residual_scale_reports_relation_use(unit, value, code):
    model = translation_model()
    use = model.node("temperature:use")
    use = replace(
        use,
        properties=(
            PropertyValue(identity("RelationUse", "residual_scale"), quantity(value, unit)),
        ),
    )
    model = replace(model, nodes=tuple(use if node.id == use.id else node for node in model.nodes))
    with pytest.raises(EquationError) as caught:
        system(model)
    assert (caught.value.code, caught.value.semantic_id) == (code, use.id)


def test_interval_division_by_zero_is_not_reclassified_as_valid_scaling():
    with pytest.raises(EquationError) as caught:
        system(translation_model("divide", factor=0))
    assert (caught.value.code, caught.value.semantic_id) == (
        "EQUATION_DIVISION_BY_ZERO",
        "scaled-interval",
    )


@pytest.mark.parametrize("operator", ("multiply", "divide"))
def test_dimensionless_unknown_does_not_bypass_linear_fragment(operator):
    case = EquationCase()
    case.symbol("delta", quantity(1, "kelvin"), "interval")
    case.symbol("scalar", quantity(1))
    product = case.op(
        "nonlinear", operator, case.ref("delta-ref", "delta"), case.ref("scalar-ref", "scalar")
    )
    case.equation(
        "relation",
        product,
        case.value("known", quantity(10, "kelvin"), "interval"),
        quantity(1, "kelvin"),
    )
    with pytest.raises(EquationError) as caught:
        system(case.model(("delta", "scalar")))
    assert (caught.value.code, caught.value.semantic_id) == ("EQUATION_NONLINEAR", "nonlinear")
