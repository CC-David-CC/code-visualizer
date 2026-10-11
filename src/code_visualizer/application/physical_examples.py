"""Native authored P3 examples; execution consumes saved intentions, never these factories."""

from __future__ import annotations

from code_visualizer.domain.intentional import (
    BundleReference,
    DomainModel,
    DomainWorkspace,
    IntentionalNode,
    PropertyValue,
    RoleBinding,
)
from code_visualizer.domain.project import Project
from code_visualizer.domain.values import CanonicalValue, QuantityValue
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.dc import BUNDLE as DC_BUNDLE
from code_visualizer.extensions.dc import PREFIX as DC_PREFIX
from code_visualizer.extensions.dc import SCHEMA_ID as DC_SCHEMA
from code_visualizer.extensions.foundations.equations import BUNDLE as MATH_BUNDLE
from code_visualizer.extensions.foundations.math import PREFIX as MATH_PREFIX
from code_visualizer.extensions.foundations.math import SCHEMA_ID as MATH_SCHEMA
from code_visualizer.extensions.foundations.unit_algebra_si import (
    algebra_si_catalog,
    algebra_si_model,
)
from code_visualizer.extensions.foundations.units_si import si_model


def _node(
    prefix: str,
    node_id: str,
    concept: str,
    properties: tuple[tuple[str, CanonicalValue], ...] = (),
    children: tuple[tuple[str, tuple[str, ...]], ...] = (),
    references: tuple[tuple[str, tuple[str, ...]], ...] = (),
) -> IntentionalNode:
    concept_id = prefix + concept
    return IntentionalNode(
        node_id,
        concept_id,
        tuple(PropertyValue(concept_id + ":" + key, value) for key, value in properties),
        tuple(RoleBinding(concept_id + ":" + key, values) for key, values in children),
        tuple(RoleBinding(concept_id + ":" + key, values) for key, values in references),
    )


def _workspace(bundle: BundleReference, model: DomainModel) -> DomainWorkspace:
    closure = builtin_registry().bundle_closure(bundle)
    return DomainWorkspace(
        tuple(schema for item in closure for schema in item.schemas),
        (model, *(reference for item in closure for reference in item.reference_models)),
        tuple(BundleReference(item.id, item.version) for item in closure),
    )


def _quantity(value: float, name: str) -> QuantityValue:
    namespace = (
        "foundation.units.algebra.si" if name == "newton_per_meter" else "foundation.units.si"
    )
    return QuantityValue(value, algebra_si_catalog().unit(namespace + ":" + name))


def _unit_roots() -> tuple[str, ...]:
    return (*si_model().roots, *algebra_si_model().roots)


def dc_divider_project() -> Project:
    """A source-only unloaded divider, ready for an author to add a load and rerun."""
    nodes = []
    net_names = (("dc:input", "+5 V supply"), ("dc:middle", "Midpoint"), ("dc:ground", "Reference"))
    for node_id, name in net_names:
        nodes.append(_node(DC_PREFIX, node_id, "Net", (("name", name),)))
    components = (
        (
            "dc:source",
            "VoltageSource",
            "V1",
            "dc:input",
            "dc:ground",
            "voltage",
            _quantity(5, "volt"),
        ),
        (
            "dc:upper",
            "Resistor",
            "R1",
            "dc:input",
            "dc:middle",
            "resistance",
            _quantity(1000, "ohm"),
        ),
        (
            "dc:lower",
            "Resistor",
            "R2",
            "dc:middle",
            "dc:ground",
            "resistance",
            _quantity(1000, "ohm"),
        ),
    )
    for node_id, concept, name, source, target, field, value in components:
        positive, negative = node_id + ":positive", node_id + ":negative"
        nodes.append(
            _node(
                DC_PREFIX,
                positive,
                "Terminal",
                (("name", name + " +"),),
                references=(("net", (source,)),),
            )
        )
        nodes.append(
            _node(
                DC_PREFIX,
                negative,
                "Terminal",
                (("name", name + " -"),),
                references=(("net", (target,)),),
            )
        )
        nodes.append(
            _node(
                DC_PREFIX,
                node_id,
                concept,
                (("name", name), (field, value)),
                (("positive", (positive,)), ("negative", (negative,))),
            )
        )
    nodes.append(
        _node(
            DC_PREFIX,
            "dc:circuit",
            "Circuit",
            (
                ("name", "Voltage divider"),
                ("voltage_scale", _quantity(1, "volt")),
                ("current_scale", _quantity(0.001, "ampere")),
            ),
            (
                ("nets", tuple(item[0] for item in net_names)),
                ("components", tuple(item[0] for item in components)),
            ),
            (("reference", ("dc:ground",)), ("unit_definitions", _unit_roots())),
        )
    )
    model = DomainModel(
        "dc:network",
        DC_SCHEMA,
        "1",
        ("dc:circuit",),
        tuple(sorted(nodes, key=lambda item: item.id)),
        "DC voltage divider",
    )
    return Project(
        "physical:dc-divider",
        "DC voltage divider",
        (),
        description=(
            "Freeze and run: the midpoint is 2.5 V. Add a 1000 ohm load from Midpoint "
            "to Reference, then compare the new 5/3 V result with the retained run."
        ),
        domain_workspace=_workspace(DC_BUNDLE, model),
    )


def spring_equation_project() -> Project:
    """F=k*x is one relation; the selected unknown belongs to the authored request."""
    nodes = []
    for node_id, name, unit in (
        ("spring:F", "Force F", "newton"),
        ("spring:k", "Stiffness k", "newton_per_meter"),
        ("spring:x", "Displacement x", "meter"),
    ):
        nodes.append(
            _node(
                MATH_PREFIX,
                node_id,
                "Symbol",
                (("name", name), ("scale", _quantity(1, unit)), ("quantity_kind", "linear")),
            )
        )
        nodes.append(
            _node(
                MATH_PREFIX,
                node_id + ":occurrence",
                "SymbolReference",
                references=(("symbol", (node_id,)),),
            )
        )
    nodes.append(
        _node(
            MATH_PREFIX,
            "spring:product",
            "OperatorApplication",
            (("operator", "multiply"),),
            (("operands", ("spring:k:occurrence", "spring:x:occurrence")),),
        )
    )
    nodes.append(
        _node(
            MATH_PREFIX,
            "spring:relation",
            "Equation",
            (("name", "F = k \u00d7 x"),),
            (("left", ("spring:F:occurrence",)), ("right", ("spring:product",))),
        )
    )
    for symbol, value in (
        ("spring:F", _quantity(10, "newton")),
        ("spring:k", _quantity(200, "newton_per_meter")),
    ):
        nodes.append(
            _node(
                MATH_PREFIX,
                symbol + ":binding",
                "Binding",
                (("value", value),),
                references=(("symbol", (symbol,)),),
            )
        )
    nodes.append(
        _node(
            MATH_PREFIX,
            "spring:relation-use",
            "RelationUse",
            (("residual_scale", _quantity(1, "newton")),),
            references=(("equation", ("spring:relation",)),),
        )
    )
    nodes.append(
        _node(
            MATH_PREFIX,
            "spring:request",
            "SolveRequest",
            (("name", "Solve displacement"), ("problem_class", "linear")),
            (
                ("bindings", ("spring:F:binding", "spring:k:binding")),
                ("relations", ("spring:relation-use",)),
            ),
            (("unknowns", ("spring:x",)),),
        )
    )
    nodes.append(
        _node(
            MATH_PREFIX,
            "spring:problem",
            "Problem",
            (("name", "Force, stiffness and displacement"),),
            (
                ("symbols", ("spring:F", "spring:k", "spring:x")),
                ("equations", ("spring:relation",)),
                ("requests", ("spring:request",)),
            ),
            (("unit_definitions", _unit_roots()),),
        )
    )
    model = DomainModel(
        "spring:equations",
        MATH_SCHEMA,
        "2",
        ("spring:problem",),
        tuple(sorted(nodes, key=lambda item: item.id)),
        "Shared equation: F = k \u00d7 x",
    )
    return Project(
        "physical:shared-equation",
        "Force, stiffness and displacement",
        (),
        description=(
            "The same linear-equation backend used by the circuit solves x = 0.05 m "
            "for F = 10 N and k = 200 N/m. Edit the canonical request to choose another unknown."
        ),
        domain_workspace=_workspace(MATH_BUNDLE, model),
    )
