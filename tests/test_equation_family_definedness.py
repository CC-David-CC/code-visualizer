"""Domain conditions survive normalization, cancellation and repeated binding."""

from dataclasses import replace

import pytest
from test_equation_compiler import EquationCase, equation_project, quantity
from test_equation_family import case as resistance_case

from code_visualizer.domain.intentional_validation import validate_domain_workspace
from code_visualizer.extensions.foundations.equation_backend import solve_linear
from code_visualizer.extensions.foundations.equation_compiler import (
    EquationError,
    compile_equation_family,
    compile_equations,
)
from code_visualizer.extensions.foundations.math import identity
from code_visualizer.extensions.foundations.unit_algebra import UnitAlgebra
from code_visualizer.extensions.foundations.units import UnitCatalog
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.serialization import normalized_project_json


def checked_model(builder, rhs):
    builder.symbol("x", quantity(1))
    builder.equation("equality", builder.ref("x-ref", "x"), rhs)
    project = equation_project(builder.model(("x",)))
    assert not validate_domain_workspace(project.domain_workspace)
    serialized = normalized_project_json(project)
    loaded = project_from_json(serialized)
    assert normalized_project_json(loaded) == serialized
    model = loaded.domain_workspace.model("math-model")
    dependencies = tuple(m for m in loaded.domain_workspace.models if m.id != model.id)
    return model, dependencies


def replace_values(model, values):
    return replace(
        model,
        nodes=tuple(
            replace(
                node,
                properties=tuple(
                    replace(prop, value=values[node.id])
                    if prop.property_id == identity("QuantityLiteral", "value")
                    else prop
                    for prop in node.properties
                ),
            )
            if node.id in values
            else node
            for node in model.nodes
        ),
    )


def assert_rejected(operation, origin):
    with pytest.raises(EquationError) as error:
        operation()
    assert (error.value.code, error.value.semantic_id) == ("EQUATION_DIVISION_BY_ZERO", origin)


def canceled_ratio(builder, numerator, denominator, origin="division"):
    ratio = builder.op(origin, "divide", numerator, denominator)
    return builder.op("rhs", "add", builder.value("one", quantity(1)), ratio)


def test_unit_converted_compound_denominator_and_matrix_independent_coefficient():
    b = EquationCase()
    denominator = b.op(
        "difference",
        "subtract",
        b.value("a", quantity(2, "kiloohm")),
        b.value("b", quantity(1000, "ohm")),
    )
    model, deps = checked_model(
        b, canceled_ratio(b, b.value("zero", quantity(0, "ohm")), denominator)
    )
    original = normalized_project_json(equation_project(model))
    family = compile_equation_family(model, deps, ("b", "a"))
    assert family.coefficient_ids == ("a", "b")
    assert family.nominal == compile_equations(model, deps)
    for a, other in (
        (quantity(3000, "ohm"), quantity(2, "kiloohm")),
        (quantity(-1, "kiloohm"), quantity(1000, "ohm")),
    ):
        values = {"a": a, "b": other}
        assert family.bind(values) == compile_equations(replace_values(model, values), deps)
        assert solve_linear(family.bind(values)).values == (1.0,)
    singular = {"a": quantity(1000, "ohm"), "b": quantity(1, "kiloohm")}
    assert_rejected(lambda: compile_equations(replace_values(model, singular), deps), "division")
    assert_rejected(lambda: family.bind(singular), "division")
    # The matrix is constant; semantic dependency still requires both quantities.
    with pytest.raises(EquationError) as incomplete:
        family.bind({"a": quantity(2, "kiloohm")})
    assert (incomplete.value.code, incomplete.value.semantic_id) == (
        "EQUATION_COEFFICIENT_BINDING",
        "request",
    )
    assert family.bind({"a": quantity(2, "kiloohm"), "b": quantity(1, "kiloohm")}) == family.nominal
    assert normalized_project_json(equation_project(model)) == original


def test_difference_of_affine_points_checks_normalized_interval_at_division_origin():
    b = EquationCase()
    denominator = b.op(
        "temperature-difference",
        "subtract",
        b.value("point", quantity(20, "degree_celsius"), "point"),
        b.value("reference", quantity(273.15, "kelvin"), "point"),
    )
    model, deps = checked_model(
        b, canceled_ratio(b, b.value("zero", quantity(0, "kelvin"), "interval"), denominator)
    )
    family = compile_equation_family(model, deps, ("point",))
    assert family.nominal == compile_equations(model, deps)
    assert solve_linear(family.bind({"point": quantity(293.15, "kelvin")})).values == (1.0,)
    singular = {"point": quantity(273.15, "kelvin")}
    assert_rejected(lambda: compile_equations(replace_values(model, singular), deps), "division")
    assert_rejected(lambda: family.bind(singular), "division")
    assert_rejected(lambda: family.bind({"point": quantity(0, "degree_celsius")}), "division")


@pytest.mark.parametrize("binding", [0.1, 0.10000000000000002, 0.09999999999999999])
def test_decimal_compound_condition_uses_the_ordinary_exact_scalar_boundary(binding):
    b = EquationCase()
    denominator = b.op(
        "difference",
        "subtract",
        b.op("sum", "add", b.value("a", quantity(0.4)), b.value("b", quantity(0.2))),
        b.value("c", quantity(0.3)),
    )
    model, deps = checked_model(b, canceled_ratio(b, b.value("zero", quantity(0)), denominator))
    family = compile_equation_family(model, deps, ("a",))
    values = {"a": quantity(binding)}
    if binding == 0.1:
        assert_rejected(lambda: compile_equations(replace_values(model, values), deps), "division")
        assert_rejected(lambda: family.bind(values), "division")
    else:
        assert family.bind(values) == compile_equations(replace_values(model, values), deps)
        assert solve_linear(family.bind(values)).values == (1.0,)


@pytest.mark.parametrize(
    "a,b,c,origin", [(4, 0, 1, "inner"), (4, 2, 2, "outer"), (0, 0, 0, "inner")]
)
def test_nested_conditions_reject_in_authored_order_even_when_parent_cancels(a, b, c, origin):
    builder = EquationCase()
    inner = builder.op(
        "inner", "divide", builder.value("a", quantity(4)), builder.value("b", quantity(2))
    )
    denominator = builder.op("difference", "subtract", inner, builder.value("c", quantity(1)))
    model, deps = checked_model(
        builder, canceled_ratio(builder, builder.value("zero", quantity(0)), denominator, "outer")
    )
    family = compile_equation_family(model, deps, ("a", "b", "c"))
    valid = {"a": quantity(4), "b": quantity(2), "c": quantity(1)}
    assert solve_linear(family.bind(valid)).values == (1.0,)
    singular = {"a": quantity(a), "b": quantity(b), "c": quantity(c)}
    changed = replace_values(model, singular)
    assert_rejected(lambda: compile_equations(changed, deps), origin)
    assert_rejected(lambda: compile_equation_family(changed, deps, ("a", "b", "c")), origin)
    assert_rejected(lambda: family.bind(singular), origin)
    assert family.bind(valid) == family.nominal


@pytest.mark.parametrize("binding", [1e-320, -1e-320, 0.0, -0.0])
def test_nonzero_condition_is_not_a_solver_tolerance(binding):
    b = EquationCase()
    model, deps = checked_model(
        b, canceled_ratio(b, b.value("zero", quantity(0)), b.value("a", quantity(1)))
    )
    family = compile_equation_family(model, deps, ("a",))
    values = {"a": quantity(binding)}
    if binding == 0:
        assert_rejected(lambda: compile_equations(replace_values(model, values), deps), "division")
        assert_rejected(lambda: family.bind(values), "division")
    else:
        assert family.bind(values) == compile_equations(replace_values(model, values), deps)
        assert solve_linear(family.bind(values)).values == (1.0,)


def test_normalized_binding_is_checked_using_the_same_value_as_the_linear_system():
    b = EquationCase()
    quotient = b.op(
        "division",
        "divide",
        b.value("numerator", quantity(1, "ohm")),
        b.value("a", quantity(2, "kiloohm")),
    )
    model, deps = checked_model(b, quotient)
    family = compile_equation_family(model, deps, ("a",))
    algebra = UnitAlgebra(UnitCatalog.from_models(deps))
    for q in (quantity(2, "ohm"), quantity(0.003, "kiloohm"), quantity(-0.004, "kiloohm")):
        normalized = algebra.convert(q, quantity(1, "kiloohm").unit)
        ordinary = compile_equations(replace_values(model, {"a": normalized}), deps)
        assert family.bind({"a": q}) == ordinary
        assert solve_linear(family.bind({"a": q})).values == solve_linear(ordinary).values
    assert_rejected(lambda: family.bind({"a": quantity(0, "ohm")}), "division")


def test_existing_zero_resistance_control_reaches_the_specific_solver_diagnostic():
    model, deps = resistance_case()
    family = compile_equation_family(model, deps, ("resistance",))
    # A missing real unit adapter cannot satisfy this numerical-domain claim.
    assert solve_linear(family.bind({"resistance": quantity(10, "ohm")})).values == (0.5,)
    bound = family.bind({"resistance": quantity(0, "ohm")})
    with pytest.raises(EquationError) as error:
        solve_linear(bound)
    assert (error.value.code, error.value.semantic_id) == ("EQUATION_INCONSISTENT", "request")
