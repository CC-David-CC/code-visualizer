"""Exact domain diagnostics, stable authorship and a real failed-window outcome."""

from dataclasses import replace
from threading import Event

import pytest
from test_electrothermal_window import prepared

from code_visualizer.application.coupled_examples import MODEL_ID, electrothermal_project
from code_visualizer.domain.intentional import PropertyValue, RoleBinding
from code_visualizer.execution.backends import BackendContext
from code_visualizer.extensions.electrothermal.problem import CouplingError, derive_problem
from code_visualizer.extensions.electrothermal.units import quantity
from code_visualizer.extensions.foundations.unit_algebra import QuantityKind, UnitAlgebra


def changed(project, node_id, field, value, *, reference=False):
    workspace = project.domain_workspace
    model = next(item for item in workspace.models if item.node(node_id))
    node = model.node(node_id)
    key = node.concept_id + ":" + field
    if reference:
        updated = replace(
            node,
            references=(
                *(x for x in node.references if x.role_id != key),
                RoleBinding(key, (value,)),
            ),
        )
    else:
        updated = replace(
            node,
            properties=(
                *(x for x in node.properties if x.property_id != key),
                PropertyValue(key, value),
            ),
        )
    edited = replace(model, nodes=tuple(updated if x.id == node.id else x for x in model.nodes))
    return replace(
        project,
        domain_workspace=replace(
            workspace, models=tuple(edited if x.id == model.id else x for x in workspace.models)
        ),
    )


@pytest.mark.parametrize(
    "node,field,value,code",
    (
        ("et:temperature", "source_kind", "interval", "COUPLING_QUANTITY_KIND"),
        ("et:temperature", "target_kind", "interval", "COUPLING_QUANTITY_KIND"),
        ("et:heat", "source_kind", "point", "COUPLING_QUANTITY_KIND"),
        ("et:heat", "target_kind", "point", "COUPLING_QUANTITY_KIND"),
        ("et:heat", "source_scale", quantity(1, "watt_per_square_meter"), "COUPLING_UNIT"),
        ("et:heat", "target_scale", quantity(1, "watt_per_square_meter"), "COUPLING_UNIT"),
        ("et:heat", "sign", -1, "COUPLING_MAPPING"),
        ("et:heat", "mapping_version", "2", "COUPLING_MAPPING"),
        ("et:heat", "mapping_id", "org.other.mapping", "COUPLING_MAPPING"),
        ("et:heat", "time_policy", "latest_available", "COUPLING_MAPPING"),
        ("et:heat", "support_kind", "uniform_mesh", "COUPLING_SUPPORT"),
        ("et:resistor-body", "temperature_kind", "interval", "COUPLING_QUANTITY_KIND"),
        ("et:resistor-body", "capacity", quantity(0, "joule_per_kelvin"), "COUPLING_RANGE"),
        ("et:contact", "conductance", quantity(-1, "watt_per_kelvin"), "COUPLING_RANGE"),
        ("et:law", "alpha", quantity(-0.01, "per_kelvin"), "COUPLING_RANGE"),
        ("et:policy", "method_id", "undeclared_method", "COUPLING_METHOD"),
    ),
)
def test_precise_origin_for_unsupported_physics(node, field, value, code):
    project = changed(electrothermal_project(), node, field, value)
    with pytest.raises(CouplingError) as error:
        derive_problem(project, project.domain_workspace.model(MODEL_ID))
    assert error.value.code == code
    assert error.value.object_id == node


@pytest.mark.parametrize("field", ("source", "target", "source_support", "target_support"))
def test_exchange_cannot_bind_a_different_body(field):
    project = changed(electrothermal_project(), "et:heat", field, "et:sink", reference=True)
    with pytest.raises(CouplingError) as error:
        derive_problem(project, project.domain_workspace.model(MODEL_ID))
    assert error.value.code in ("COUPLING_PORT", "COUPLING_SUPPORT")
    assert error.value.object_id == "et:heat"


def test_insufficient_iteration_budget_preserves_actual_base():
    _, _, _, solver = prepared(max_iterations=1)
    base = solver.initial()
    trials = solver.trials(base, BackendContext("budget", Event()))
    assert not next(trials).converged
    with pytest.raises(CouplingError) as error:
        next(trials)
    assert error.value.code == "COUPLING_NOT_CONVERGED"
    assert error.value.object_id == solver.problem.policy_id
    assert base == solver.initial()


def test_affine_points_and_temperature_interval_coefficients_use_existing_units():
    from code_visualizer.extensions.electrothermal.units import thermal_catalog

    algebra = UnitAlgebra(thermal_catalog())
    assert algebra.convert(
        quantity(20, "degree_celsius"), quantity(1, "kelvin").unit, kind=QuantityKind.POINT
    ).magnitude == pytest.approx(293.15)
    project = electrothermal_project()
    for node, field in (
        ("et:resistor-body", "initial_temperature"),
        ("et:sink", "initial_temperature"),
        ("et:ambient", "temperature"),
        ("et:law", "reference_temperature"),
    ):
        project = changed(project, node, field, quantity(20, "degree_celsius"))
    converted = derive_problem(project, project.domain_workspace.model(MODEL_ID))
    baseline = electrothermal_project()
    assert converted == derive_problem(baseline, baseline.domain_workspace.model(MODEL_ID))
