"""P6 trial coefficients bind the existing checked P3 equations without edits."""

from dataclasses import replace

import pytest
from test_equation_compiler import EquationCase, equation_project, quantity

from code_visualizer.domain.intentional import PropertyValue
from code_visualizer.extensions.foundations.equation_backend import solve_linear
from code_visualizer.extensions.foundations.equation_compiler import (
    EquationError,
    compile_equation_family,
    compile_equations,
)
from code_visualizer.extensions.foundations.math import identity


def case():
    builder = EquationCase()
    current = builder.symbol("current", quantity(1, "ampere"))
    rhs = builder.op(
        "drop",
        "multiply",
        builder.value("resistance", quantity(10, "ohm")),
        builder.ref("i", current),
    )
    builder.equation(
        "ohms-law", rhs, builder.value("voltage", quantity(5, "volt")), quantity(1, "volt")
    )
    model = builder.model((current,))
    project = equation_project(model)
    dependencies = tuple(item for item in project.domain_workspace.models if item.id != model.id)
    return model, dependencies


def test_prepared_family_binds_repeated_trials_without_changing_source():
    model, dependencies = case()
    original = repr(model)
    family = compile_equation_family(model, dependencies, ("resistance",))
    assert family.nominal == compile_equations(model, dependencies)
    for resistance, expected in ((10, 0.5), (20, 0.25), (10, 0.5), (40, 0.125)):
        system = family.bind({"resistance": quantity(resistance, "ohm")})
        assert solve_linear(system).values == pytest.approx((expected,))
        assert system.variables == family.nominal.variables
        assert system.residuals == family.nominal.residuals
    assert repr(model) == original
    assert family.bind({"resistance": quantity(0.02, "kiloohm")}) == family.bind(
        {"resistance": quantity(20, "ohm")}
    )


@pytest.mark.parametrize(
    "bindings",
    [
        {},
        {"missing": quantity(10, "ohm")},
        {"resistance": quantity(10, "ohm"), "other": quantity(1)},
    ],
)
def test_exact_coefficient_set(bindings):
    model, dependencies = case()
    family = compile_equation_family(model, dependencies, ("resistance",))
    with pytest.raises(EquationError, match="exactly one"):
        family.bind(bindings)


def test_incompatible_coefficient_keeps_its_origin():
    model, dependencies = case()
    family = compile_equation_family(model, dependencies, ("resistance",))
    with pytest.raises(EquationError) as error:
        family.bind({"resistance": quantity(10, "kelvin")})
    assert error.value.semantic_id == "resistance"
    assert "UNIT" in error.value.code


@pytest.mark.parametrize("ids", [("resistance", "resistance"), ("current",), ("missing",)])
def test_only_distinct_known_quantities_may_be_bound(ids):
    model, dependencies = case()
    with pytest.raises(EquationError):
        compile_equation_family(model, dependencies, ids)


def test_affine_point_coefficient_has_native_unit_context():
    builder = EquationCase()
    temperature = builder.symbol("temperature", quantity(1, "kelvin"), "point")
    builder.equation(
        "point-equality",
        builder.ref("T", temperature),
        builder.value("point", quantity(20, "degree_celsius"), "point"),
        quantity(1, "kelvin"),
    )
    model = builder.model((temperature,))
    dependencies = tuple(x for x in equation_project(model).domain_workspace.models if x != model)
    family = compile_equation_family(model, dependencies, ("point",))
    assert solve_linear(family.bind({"point": quantity(303.15, "kelvin")})).values == pytest.approx(
        (303.15,)
    )


def test_division_by_zero_binding_and_unused_coefficient_are_rejected():
    model, dependencies = case()
    # A nominated quantity outside the selected equations is not an implicit input.
    node = replace(
        model.node("resistance"),
        id="unused",
        properties=(PropertyValue(identity("QuantityLiteral", "value"), quantity(2, "ohm")),),
    )
    with pytest.raises(EquationError, match="outside"):
        compile_equation_family(
            replace(model, nodes=(*model.nodes, node)), dependencies, ("unused",)
        )
    # A real numerical singularity still reaches the mature solver's diagnostics.
    family = compile_equation_family(model, dependencies, ("resistance",))
    with pytest.raises(EquationError):
        solve_linear(family.bind({"resistance": quantity(0, "ohm")}))
