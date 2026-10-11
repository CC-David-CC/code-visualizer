"""Independent spatial/temporal references for the bounded P5 physical fragment."""

from dataclasses import replace

import numpy as np
import pytest

from code_visualizer.application.field_examples import diffusion_project
from code_visualizer.domain.intentional import PropertyValue
from code_visualizer.extensions.diffusion.domain import quantity
from code_visualizer.extensions.diffusion.numerics import CrankNicolson
from code_visualizer.extensions.diffusion.problem import derive_problem


def change(project, node_id, name, value):
    models = []
    for model in project.domain_workspace.models:
        nodes = []
        for node in model.nodes:
            if node.id == node_id:
                key = node.concept_id + ":" + name
                node = replace(
                    node,
                    properties=(
                        *(item for item in node.properties if item.property_id != key),
                        PropertyValue(key, value),
                    ),
                )
            nodes.append(node)
        models.append(replace(model, nodes=tuple(nodes)))
    return replace(
        project, domain_workspace=replace(project.domain_workspace, models=tuple(models))
    )


def solve(project):
    problem = derive_problem(project, project.domain_workspace.models[0])
    solver = CrankNicolson(problem)
    x = np.arange(problem.nodes) * problem.dx
    u = problem.amplitude * np.sin(np.pi * x / problem.length)
    u[0] = u[-1] = 0.0
    residual = 0.0
    for _ in range(problem.steps):
        before = u.copy()
        predictor = solver.predictor(u)
        result = solver.correct(u, predictor)
        assert np.array_equal(u, before)
        residual = max(residual, result.dimensional_residual / result.residual_scale)
        u = result.accepted
    assert residual <= 1e-11
    return problem, x, u


def test_spatial_second_order_against_continuum_not_solver_formula():
    errors = []
    for nodes, steps in ((33, 512), (65, 2048), (129, 8192)):
        p, x, u = solve(diffusion_project(nodes=nodes, steps=steps))
        exact = 10.0 * np.exp(-0.1 * np.pi**2) * np.sin(np.pi * x)
        errors.append(float(np.max(np.abs(u - exact))))
        assert u[0] == u[-1] == 0 and np.min(u) >= 0
        assert p.quantity_kind.value == "interval"
    orders = np.log2(np.array(errors[:-1]) / errors[1:])
    assert np.all((orders >= 1.9) & (orders <= 2.1)), (errors, orders)
    assert errors[-1] <= 2e-4


def test_temporal_second_order_against_independent_semidiscrete_eigenvalue():
    errors = []
    for steps in (512, 1024, 2048):
        p, x, u = solve(diffusion_project(nodes=33, steps=steps))
        eigenvalue = -4 * p.diffusivity / p.dx**2 * np.sin(np.pi / (2 * (p.nodes - 1))) ** 2
        exact = p.amplitude * np.exp(eigenvalue * p.final_time) * np.sin(np.pi * x)
        errors.append(float(np.max(np.abs(u - exact))))
    orders = np.log2(np.array(errors[:-1]) / errors[1:])
    assert np.all((orders >= 1.8) & (orders <= 2.2)), (errors, orders)


def test_equivalent_units_derive_identical_numerical_problem():
    original = diffusion_project()
    altered = change(original, "diffusion:grid", "length", quantity(1000.0, "millimeter"))
    altered = change(altered, "diffusion:policy", "final_time", quantity(1000.0, "millisecond"))
    altered = change(
        altered,
        "diffusion:problem",
        "diffusivity",
        quantity(100.0, "square_millimeter_per_millisecond"),
    )
    original_problem, _, original_values = solve(original)
    altered_problem, _, altered_values = solve(altered)
    assert altered_problem.diffusivity == pytest.approx(original_problem.diffusivity, rel=1e-14)
    assert replace(altered_problem, diffusivity=original_problem.diffusivity) == original_problem
    np.testing.assert_allclose(altered_values, original_values, rtol=0, atol=1e-12)


@pytest.mark.parametrize(
    ("node", "property_name", "value"),
    (
        ("diffusion:field", "quantity_kind", "point"),
        ("diffusion:grid", "length", quantity(1.0, "second")),
        ("diffusion:problem", "diffusivity", quantity(1.0, "meter")),
        ("diffusion:policy", "steps", 2),
        ("diffusion:space", "dimension", 2),
        ("diffusion:x", "ordinal", 1),
        ("diffusion:initial", "amplitude", quantity(-1.0, "kelvin")),
    ),
)
def test_unsupported_physical_meaning_is_rejected(node, property_name, value):
    project = change(diffusion_project(), node, property_name, value)
    with pytest.raises(ValueError):
        derive_problem(project, project.domain_workspace.models[0])
