"""Authoring fixtures only: executions consume saved intentions, never these functions."""

from dataclasses import replace

from code_visualizer.application.physical_examples import _node
from code_visualizer.domain.intentional import (
    BundleReference,
    DomainModel,
    DomainWorkspace,
    PropertyValue,
)
from code_visualizer.domain.project import Project
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.dc import PREFIX as DC
from code_visualizer.extensions.dc import SCHEMA_ID as DC_SCHEMA
from code_visualizer.extensions.electrothermal.domain import (
    BUNDLE,
    SCHEMA_ID,
    electrothermal_schema,
)
from code_visualizer.extensions.electrothermal.units import quantity, unit_model
from code_visualizer.extensions.foundations.unit_algebra_si import algebra_si_model
from code_visualizer.extensions.foundations.units_si import si_model

MODEL_ID = "electrothermal:experiment"


def electrothermal_project(
    *,
    duration: float = 100.0,
    windows: int = 100,
    alpha: float = 0.004,
    voltage: float = 5,
    sample_every: int = 5,
    checkpoint_every: int = 25,
    max_iterations: int = 50,
    evaluation_order: str = "electrical_first",
    chunk_rows: int = 64,
) -> Project:
    unit_roots = (*si_model().roots, *algebra_si_model().roots, *unit_model().roots)
    dc_nodes = [
        _node(DC, node, "Net", (("name", name),))
        for node, name in (("et:live", "Supply"), ("et:ground", "Reference"))
    ]
    for component, concept, field, value in (
        ("et:resistor", "Resistor", "resistance", quantity(10, "ohm")),
        ("et:supply", "VoltageSource", "voltage", quantity(voltage, "volt")),
    ):
        for side, net in (("positive", "et:live"), ("negative", "et:ground")):
            dc_nodes.append(
                _node(
                    DC,
                    component + ":" + side,
                    "Terminal",
                    (("name", side),),
                    references=(("net", (net,)),),
                )
            )
        dc_nodes.append(
            _node(
                DC,
                component,
                concept,
                (("name", concept), (field, value)),
                (
                    ("positive", (component + ":positive",)),
                    ("negative", (component + ":negative",)),
                ),
            )
        )
    dc_nodes.append(
        _node(
            DC,
            "et:circuit",
            "Circuit",
            (
                ("name", "Voltage source and temperature-dependent resistor"),
                ("voltage_scale", quantity(1, "volt")),
                ("current_scale", quantity(1, "ampere")),
            ),
            (("nets", ("et:live", "et:ground")), ("components", ("et:resistor", "et:supply"))),
            (("reference", ("et:ground",)), ("unit_definitions", unit_roots)),
        )
    )
    circuit = DomainModel(
        "electrothermal:circuit",
        DC_SCHEMA,
        "1",
        ("et:circuit",),
        tuple(dc_nodes),
        "Electrical participant",
    )
    prefix = BUNDLE.id + ":"
    nodes = [
        _node(
            prefix,
            "et:experiment",
            "Experiment",
            (("name", "Resistor and heat sink"),),
            (
                ("bodies", ("et:resistor-body", "et:sink")),
                ("law", ("et:law",)),
                ("contact", ("et:contact",)),
                ("ambient", ("et:ambient",)),
                ("policy", ("et:policy",)),
                ("exchanges", ("et:temperature", "et:heat")),
            ),
            (("circuit", ("et:circuit",)), ("unit_definitions", unit_roots)),
        ),
        _node(
            prefix,
            "et:resistor-body",
            "ThermalBody",
            (
                ("name", "Resistor body"),
                ("capacity", quantity(10, "joule_per_kelvin")),
                ("initial_temperature", quantity(293.15, "kelvin")),
            ),
        ),
        _node(
            prefix,
            "et:sink",
            "ThermalBody",
            (
                ("name", "Heat sink"),
                ("capacity", quantity(20, "joule_per_kelvin")),
                ("initial_temperature", quantity(293.15, "kelvin")),
            ),
        ),
        _node(
            prefix,
            "et:law",
            "ResistanceLaw",
            (
                ("name", "Linear temperature coefficient"),
                ("alpha", quantity(alpha, "per_kelvin")),
                ("reference_temperature", quantity(293.15, "kelvin")),
            ),
            references=(("resistor", ("et:resistor",)), ("body", ("et:resistor-body",))),
        ),
        _node(
            prefix,
            "et:contact",
            "ThermalContact",
            (("name", "Body to sink"), ("conductance", quantity(0.2, "watt_per_kelvin"))),
            references=(("source", ("et:resistor-body",)), ("target", ("et:sink",))),
        ),
        _node(
            prefix,
            "et:ambient",
            "AmbientSink",
            (
                ("name", "Fixed ambient"),
                ("temperature", quantity(293.15, "kelvin")),
                ("conductance", quantity(0.1, "watt_per_kelvin")),
            ),
            references=(("body", ("et:sink",)),),
        ),
        _node(
            prefix,
            "et:policy",
            "WindowPolicy",
            (
                ("name", "Fixed implicit windows"),
                ("duration", quantity(duration)),
                ("windows", windows),
                ("sample_every", sample_every),
                ("checkpoint_every", checkpoint_every),
                ("max_iterations", max_iterations),
                ("evaluation_order", evaluation_order),
                ("chunk_rows", chunk_rows),
            ),
        ),
    ]
    for key, source, target, source_port, target_port, kind, unit in (
        (
            "temperature",
            "et:resistor-body",
            "et:resistor",
            "temperature",
            "temperature",
            "point",
            "kelvin",
        ),
        ("heat", "et:resistor", "et:resistor-body", "dissipation", "heat_input", "linear", "watt"),
    ):
        nodes.append(
            _node(
                prefix,
                "et:" + key,
                "Exchange",
                (
                    ("name", key.title()),
                    ("source_port", source_port),
                    ("target_port", target_port),
                    ("source_kind", kind),
                    ("target_kind", kind),
                    ("source_scale", quantity(1, unit)),
                    ("target_scale", quantity(1, unit)),
                ),
                references=(
                    ("source", (source,)),
                    ("target", (target,)),
                    ("source_support", ("et:resistor-body",)),
                    ("target_support", ("et:resistor-body",)),
                ),
            )
        )
    # Normal node creation materializes schema defaults into the authored node.
    # This source fixture does the same; a saved solve never depends on a factory.
    schema = electrothermal_schema()
    nodes = [
        replace(
            node,
            properties=(
                *node.properties,
                *(
                    PropertyValue(prop.id, prop.default)
                    for concept in schema.concepts
                    if concept.id == node.concept_id
                    for prop in concept.properties
                    if prop.default is not None and node.property(prop.id) is None
                ),
            ),
        )
        for node in nodes
    ]
    model = DomainModel(
        MODEL_ID, SCHEMA_ID, "1", ("et:experiment",), tuple(nodes), "Electrothermal experiment"
    )
    closure = builtin_registry().bundle_closure(BUNDLE)
    return Project(
        "physical:electrothermal",
        "Electrothermal feedback: accepted windows",
        (),
        description="Two thermal bodies coupled to a 5 V / 10 ohm DC resistor. "
        "Fixed backward-Euler windows; accepted temperature, current, power and energy "
        "share one physical time. Canonical source remains independently editable.",
        domain_workspace=DomainWorkspace(
            tuple(schema for bundle in closure for schema in bundle.schemas),
            (model, circuit, *(ref for bundle in closure for ref in bundle.reference_models)),
            tuple(BundleReference(bundle.id, bundle.version) for bundle in closure),
        ),
    )
