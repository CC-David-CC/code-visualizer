"""Preserve authored division domain across the NEW parameterized compilation path.

The nominal regressions and their positive controls use real canonical models,
validation, serialization, ordinary compiler, family compiler, and P3 solver.
They do not import Pint or monkeypatch production code. Binding regressions need
real Pint and are explicitly skipped when it is absent; they are not relabeled
as executed failures or passes.
"""

import pytest
from test_equation_compiler import EquationCase, equation_project, quantity

from code_visualizer.domain.intentional_validation import validate_domain_workspace
from code_visualizer.extensions.foundations.equation_backend import solve_linear
from code_visualizer.extensions.foundations.equation_compiler import (
    EquationError,
    compile_equation_family,
    compile_equations,
)
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.serialization import normalized_project_json

KINDS = ("zero_numerator", "zero_product", "shifted_denominator")


def authored(kind, nominal):
    b = EquationCase()
    b.symbol("x", quantity(1))
    parameter = b.value("a", quantity(nominal))
    zero = b.value("zero", quantity(0))
    if kind == "zero_numerator":
        term = b.op("authored-division", "divide", zero, parameter)
    elif kind == "zero_product":
        quotient = b.op(
            "authored-division", "divide", b.value("quotient-one", quantity(1)), parameter
        )
        term = b.op("zero-product", "multiply", zero, quotient)
    elif kind == "shifted_denominator":
        denominator = b.op(
            "shifted-denominator", "subtract", parameter, b.value("shift", quantity(1))
        )
        term = b.op("authored-division", "divide", zero, denominator)
    else:
        raise ValueError(kind)
    rhs = b.op("right", "add", b.value("offset", quantity(1)), term)
    b.equation("equality", b.ref("x-reference", "x"), rhs)
    model = b.model(("x",))
    project = equation_project(model)
    assert not validate_domain_workspace(project.domain_workspace)
    return project


def source_roundtrip(tmp_path, kind, nominal):
    project = authored(kind, nominal)
    path = tmp_path / "project.json"
    path.write_text(normalized_project_json(project), encoding="utf-8")
    loaded = project_from_json(path.read_text(encoding="utf-8"))
    assert not validate_domain_workspace(loaded.domain_workspace)
    model = loaded.domain_workspace.model("math-model")
    deps = tuple(m for m in loaded.domain_workspace.models if m.id != model.id)
    return model, deps


def invalid_value(kind):
    return 1 if kind == "shifted_denominator" else 0


@pytest.mark.parametrize("kind", KINDS)
def test_nominal_family_must_preserve_ordinary_division_rejection(tmp_path, kind):
    model, deps = source_roundtrip(tmp_path, kind, invalid_value(kind))
    with pytest.raises(EquationError) as ordinary:
        compile_equations(model, deps)
    assert (ordinary.value.code, ordinary.value.semantic_id) == (
        "EQUATION_DIVISION_BY_ZERO",
        "authored-division",
    )
    # Required invariant: parameterization cannot make undefined source valid.
    with pytest.raises(EquationError) as parameterized:
        compile_equation_family(model, deps, ("a",))
    assert (parameterized.value.code, parameterized.value.semantic_id) == (
        "EQUATION_DIVISION_BY_ZERO",
        "authored-division",
    )


@pytest.mark.parametrize("kind", KINDS)
def test_nonsingular_nominal_family_keeps_the_ordinary_answer(tmp_path, kind):
    model, deps = source_roundtrip(tmp_path, kind, 2)
    ordinary = compile_equations(model, deps)
    family = compile_equation_family(model, deps, ("a",))
    assert ordinary == family.nominal
    assert solve_linear(ordinary).values == pytest.approx((1.0,))
    assert solve_linear(family.nominal).values == pytest.approx((1.0,))


@pytest.mark.parametrize("kind", KINDS)
def test_rebinding_must_recheck_authored_denominator_domain(tmp_path, kind):
    pytest.importorskip(
        "pint", reason="Real unit normalization is required; production adapter is not replaced"
    )
    model, deps = source_roundtrip(tmp_path, kind, 2)
    family = compile_equation_family(model, deps, ("a",))
    assert solve_linear(family.bind({"a": quantity(2)})).values == pytest.approx((1.0,))
    with pytest.raises(EquationError) as bound:
        family.bind({"a": quantity(invalid_value(kind))})
    assert (bound.value.code, bound.value.semantic_id) == (
        "EQUATION_DIVISION_BY_ZERO",
        "authored-division",
    )
