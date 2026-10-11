"""Topology, units and origins of the first physical domain, using the shared solver."""

from dataclasses import replace
from fractions import Fraction

import pytest
from test_equation_compiler import quantity

from code_visualizer.application.computation import _resolve_resources
from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.domain.intentional import (
    BundleReference,
    DomainModel,
    DomainWorkspace,
    IntentionalNode,
    PropertyValue,
    RoleBinding,
)
from code_visualizer.domain.project import Project
from code_visualizer.domain.transformation import derived_id
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.dc import BUNDLE, SCHEMA_ID, TRANSFORMATION, identity
from code_visualizer.extensions.foundations.equation_backend import evaluate_equations
from code_visualizer.extensions.foundations.equations import BACKEND_ID
from code_visualizer.extensions.foundations.unit_algebra_si import algebra_si_model
from code_visualizer.extensions.foundations.units_si import si_model
from code_visualizer.generation.computation import prepare_computation
from code_visualizer.generation.transformation import TransformationError
from code_visualizer.persistence.serialization import normalized_project_json


def network(nets, components, *, reference="ground", current_scale=None):
    nodes = []

    def node(key, concept, properties=(), children=(), references=()):
        nodes.append(
            IntentionalNode(
                key,
                identity(concept),
                tuple(
                    PropertyValue(identity(concept, field), value) for field, value in properties
                ),
                tuple(
                    RoleBinding(identity(concept, field), tuple(values))
                    for field, values in children
                ),
                tuple(
                    RoleBinding(identity(concept, field), tuple(values))
                    for field, values in references
                ),
            )
        )

    for net in nets:
        node(net, "Net", (("name", net),))
    for key, concept, source, target, value in components:
        node(
            key + ":positive", "Terminal", (("name", key + " +"),), references=(("net", (source,)),)
        )
        node(
            key + ":negative", "Terminal", (("name", key + " -"),), references=(("net", (target,)),)
        )
        node(
            key,
            concept,
            (("name", key), ("resistance" if concept == "Resistor" else "voltage", value)),
            (("positive", (key + ":positive",)), ("negative", (key + ":negative",))),
        )
    node(
        "circuit",
        "Circuit",
        (
            ("name", "DC network"),
            ("voltage_scale", quantity(1, "volt")),
            ("current_scale", current_scale or quantity(0.001, "ampere")),
        ),
        (("nets", nets), ("components", tuple(item[0] for item in components))),
        (
            ("reference", (reference,)),
            ("unit_definitions", (*si_model().roots, *algebra_si_model().roots)),
        ),
    )
    model = DomainModel(
        "dc-model",
        SCHEMA_ID,
        "1",
        ("circuit",),
        tuple(sorted(nodes, key=lambda item: item.id)),
        "DC network",
    )
    closure = builtin_registry().bundle_closure(BUNDLE)
    return Project(
        "dc-project",
        "DC network",
        (),
        domain_workspace=DomainWorkspace(
            tuple(schema for bundle in closure for schema in bundle.schemas),
            (model, *(model for bundle in closure for model in bundle.reference_models)),
            tuple(BundleReference(bundle.id, bundle.version) for bundle in closure),
        ),
    )


def divider(loaded=False, *, alternate_units=False):
    resistance = quantity(1, "kiloohm") if alternate_units else quantity(1000, "ohm")
    components = [
        ("supply", "VoltageSource", "input", "ground", quantity(5, "volt")),
        ("upper", "Resistor", "input", "middle", resistance),
        ("lower", "Resistor", "middle", "ground", resistance),
    ]
    if loaded:
        components.append(("load", "Resistor", "middle", "ground", resistance))
    return network(
        ("input", "middle", "ground"),
        components,
        current_scale=quantity(1, "milliampere") if alternate_units else None,
    )


def execute(project):
    pytest.importorskip("pint")
    pytest.importorskip("sympy")
    pytest.importorskip("numpy")
    before = normalized_project_json(project)
    request = ComputationRequest(project.id, project.revision, BACKEND_ID, "1", "dc-model")
    prepared = _resolve_resources(None, prepare_computation(project, request))
    assert isinstance(prepared.value, DomainModel)
    assert prepared.transformations == (TRANSFORMATION.key,)
    result = evaluate_equations(prepared)
    assert result.outcome is ComputationOutcome.SUCCEEDED, result.diagnostics
    assert normalized_project_json(project) == before
    assert prepared.value.id not in {model.id for model in project.domain_workspace.models}
    observations = {item.id: item for item in result.observations}
    return prepared, observations, result


def value(observations, source, role):
    return observations[derived_id(TRANSFORMATION.key, source, role) + ":solution"].value.magnitude


@pytest.mark.parametrize("loaded", (False, True))
def test_divider_and_load_derive_values_currents_conservation_and_origins(loaded):
    prepared, observations, result = execute(divider(loaded))
    middle = Fraction(5, 3) if loaded else Fraction(5, 2)
    assert value(observations, "middle", "potential") == pytest.approx(float(middle))
    assert value(observations, "input", "potential") == pytest.approx(5)
    assert value(observations, "ground", "potential") == pytest.approx(0, abs=1e-14)
    upper_current = (5 - middle) / 1000
    assert value(observations, "upper", "current") == pytest.approx(float(upper_current))
    assert value(observations, "lower", "current") == pytest.approx(float(middle / 1000))
    assert value(observations, "supply", "current") == pytest.approx(float(-upper_current))
    if loaded:
        assert value(observations, "load", "current") == pytest.approx(float(middle / 1000))
    assert prepared.origins.sources(derived_id(TRANSFORMATION.key, "middle", "potential")) == (
        "middle",
    )
    assert "upper" in prepared.origins.sources(derived_id(TRANSFORMATION.key, "upper", "current"))
    for item in result.observations:
        if item.id.endswith(":normalized"):
            assert abs(item.value) < 1e-9
            assert all(prepared.origins.sources(node_id) for node_id in item.semantic_ids)


def test_kiloohm_and_milliampere_change_reporting_units_without_changing_physics():
    _prepared, original, _ = execute(divider(True))
    _prepared, alternate, _ = execute(divider(True, alternate_units=True))
    assert value(original, "middle", "potential") == pytest.approx(
        value(alternate, "middle", "potential")
    )
    for component in ("upper", "lower", "load", "supply"):
        assert value(original, component, "current") * 1000 == pytest.approx(
            value(alternate, component, "current")
        )


def test_bridge_network_proves_lowering_is_not_a_divider_formula():
    project = network(
        ("input", "left", "right", "ground"),
        (
            ("source", "VoltageSource", "input", "ground", quantity(10, "volt")),
            ("a", "Resistor", "input", "left", quantity(100, "ohm")),
            ("b", "Resistor", "left", "ground", quantity(200, "ohm")),
            ("c", "Resistor", "input", "right", quantity(300, "ohm")),
            ("d", "Resistor", "right", "ground", quantity(400, "ohm")),
            ("bridge", "Resistor", "left", "right", quantity(500, "ohm")),
        ),
    )
    _, observations, _ = execute(project)
    # Independent elimination of the two nodal equations: 17L-2R=100, -12L+47R=200.
    assert value(observations, "left", "potential") == pytest.approx(204 / 31)
    assert value(observations, "right", "potential") == pytest.approx(184 / 31)
    assert value(observations, "bridge", "current") == pytest.approx(1 / 775)
    assert value(observations, "source", "current") == pytest.approx(-37 / 775)


def test_topology_order_does_not_choose_equations_or_generated_identities():
    project = divider(True)
    original = execute(project)[0]
    model = project.domain_workspace.model("dc-model")
    reordered = replace(model, nodes=tuple(reversed(model.nodes)))
    project = replace(
        project,
        domain_workspace=replace(
            project.domain_workspace,
            models=tuple(
                reordered if candidate.id == model.id else candidate
                for candidate in project.domain_workspace.models
            ),
        ),
    )
    assert execute(project)[0].value == original.value
    assert execute(project)[0].origins == original.origins


def test_wrong_physical_unit_is_rejected_during_preparation():
    project = network(
        ("input", "ground"), (("bad", "Resistor", "input", "ground", quantity(5, "volt")),)
    )
    with pytest.raises(TransformationError) as error:
        prepare_computation(
            project, ComputationRequest(project.id, project.revision, BACKEND_ID, "1", "dc-model")
        )
    assert error.value.code == "DOMAIN_PROPERTY_TYPE"
    from code_visualizer.domain.intentional_validation import validate_domain_workspace

    assert any(
        issue.object_id == "bad" and issue.code == "DOMAIN_PROPERTY_TYPE"
        for issue in validate_domain_workspace(project.domain_workspace)
    )
