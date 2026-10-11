"""DC resistor networks are ordinary intentions; mathematics owns the solver."""

from __future__ import annotations

import math
from functools import cache
from typing import TYPE_CHECKING

from code_visualizer.domain.intentional import (
    BundleReference,
    ConceptDefinition,
    DomainIssue,
    DomainModel,
    DomainSchema,
    IntentionalNode,
    PropertyDefinition,
    RoleDefinition,
    ValueKind,
)
from code_visualizer.domain.notation import (
    NotationColumn,
    NotationDefinition,
    NotationField,
    NotationKind,
    NotationNodeRule,
)
from code_visualizer.domain.project import Project
from code_visualizer.domain.transformation import Representation, TransformationDefinition
from code_visualizer.domain.values import QuantityValue, ValueConstraints
from code_visualizer.extensions.foundations.equations import REPRESENTATION as MATH_REPRESENTATION
from code_visualizer.extensions.foundations.equations import UNIT_CONCEPTS
from code_visualizer.extensions.foundations.units_si import si_catalog

if TYPE_CHECKING:
    from code_visualizer.extensions.registry import DomainExtensionBundle

BUNDLE = BundleReference("org.codevisualizer.electrical.dc", "1")
PREFIX = BUNDLE.id + ":"
SCHEMA_ID = PREFIX + "schema"
REPRESENTATION = Representation(BUNDLE.id, BUNDLE.version)
TRANSFORMATION = TransformationDefinition(
    BUNDLE.id + ".equations",
    "1",
    REPRESENTATION,
    MATH_REPRESENTATION,
    description="Terminal topology to component relations, reference potential and conservation.",
)
COMPONENTS = (PREFIX + "Resistor", PREFIX + "VoltageSource")


def identity(concept: str, field: str | None = None) -> str:
    return PREFIX + concept + (":" + field if field else "")


def si_quantity(magnitude: float, unit: str) -> QuantityValue:
    return QuantityValue(magnitude, si_catalog().unit("foundation.units.si:" + unit))


@cache
def dc_schema() -> DomainSchema:
    def name(concept: str) -> PropertyDefinition:
        return PropertyDefinition(identity(concept, "name"), "Name", required=True)

    def quantity(concept: str, field: str, unit: str, default: float) -> PropertyDefinition:
        value = si_quantity(default, unit)
        return PropertyDefinition(
            identity(concept, field),
            field.replace("_", " ").title(),
            ValueKind.QUANTITY,
            True,
            value,
            value_constraints=ValueConstraints(dimension=value.unit.dimension),
        )

    def terminal(concept: str, side: str) -> RoleDefinition:
        return RoleDefinition(
            identity(concept, side),
            "+" if side == "positive" else "-",
            (identity("Terminal"),),
            1,
            1,
        )

    return DomainSchema(
        SCHEMA_ID,
        BUNDLE.id,
        BUNDLE.version,
        (
            ConceptDefinition(
                identity("Circuit"),
                "DC circuit",
                (
                    name("Circuit"),
                    quantity("Circuit", "voltage_scale", "volt", 1),
                    quantity("Circuit", "current_scale", "ampere", 0.001),
                ),
                (
                    RoleDefinition(identity("Circuit", "nets"), "Nets", (identity("Net"),), 2, 128),
                    RoleDefinition(
                        identity("Circuit", "components"), "Components", COMPONENTS, 1, 128
                    ),
                ),
                (
                    RoleDefinition(
                        identity("Circuit", "reference"), "Reference net", (identity("Net"),), 1, 1
                    ),
                    RoleDefinition(
                        identity("Circuit", "unit_definitions"), "Unit vocabulary", UNIT_CONCEPTS
                    ),
                ),
                display_property_id=identity("Circuit", "name"),
            ),
            ConceptDefinition(
                identity("Net"),
                "Electrical net",
                (name("Net"),),
                display_property_id=identity("Net", "name"),
            ),
            ConceptDefinition(
                identity("Terminal"),
                "Terminal",
                (name("Terminal"),),
                reference_roles=(
                    RoleDefinition(
                        identity("Terminal", "net"), "Connected net", (identity("Net"),), 1, 1
                    ),
                ),
                display_property_id=identity("Terminal", "name"),
            ),
            *(
                ConceptDefinition(
                    identity(concept),
                    title,
                    (name(concept), quantity(concept, field, unit, default)),
                    (terminal(concept, "positive"), terminal(concept, "negative")),
                    display_property_id=identity(concept, "name"),
                    description=(
                        "Reported current flows from the positive to the negative terminal."
                    ),
                )
                for concept, title, field, unit, default in (
                    ("Resistor", "Resistor", "resistance", "ohm", 1000),
                    ("VoltageSource", "Ideal DC voltage source", "voltage", "volt", 5),
                )
            ),
        ),
        BUNDLE,
        "Finite ideal DC networks with typed parameters and explicit terminal connectivity.",
    )


def parameter(node: IntentionalNode, field: str) -> QuantityValue:
    concept = dc_schema().concept(node.concept_id)
    assert concept is not None
    definition = next(
        item for item in concept.properties if item.id == node.concept_id + ":" + field
    )
    value = node.property(definition.id)
    value = definition.default if value is None else value
    if not isinstance(value, QuantityValue) or type(value.magnitude) not in (int, float):
        raise ValueError("DC parameters require finite real quantities")
    assert isinstance(value.magnitude, (int, float))
    try:
        finite = math.isfinite(float(value.magnitude))
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError("DC parameters must be within the finite numerical range")
    if value.unit.dimension != definition.value_constraints.dimension:
        raise ValueError("DC parameter has incompatible physical dimensions")
    if field in ("resistance", "voltage_scale", "current_scale") and value.magnitude <= 0:
        raise ValueError("Resistance and characteristic scales must be strictly positive")
    return value


def validate_dc(_project: Project, model: DomainModel) -> tuple[DomainIssue, ...]:
    issues = []
    circuits = [node for node in model.nodes if node.concept_id == identity("Circuit")]
    if len(circuits) != 1 or model.roots != (circuits[0].id,):
        return (
            DomainIssue(
                "DC_CIRCUIT_ROOT",
                "A computation model owns exactly one circuit root",
                model.id,
                incomplete=True,
            ),
        )
    circuit = circuits[0]
    nets = set(circuit.child_ids(identity("Circuit", "nets")))
    reference = circuit.reference_ids(identity("Circuit", "reference"))
    if len(reference) != 1 or reference[0] not in nets:
        issues.append(
            DomainIssue(
                "DC_REFERENCE_NET",
                "Select one reference net owned by this circuit",
                circuit.id,
                incomplete=True,
            )
        )
    for node in model.nodes:
        if node.concept_id == identity("Terminal"):
            targets = node.reference_ids(identity("Terminal", "net"))
            if len(targets) != 1 or targets[0] not in nets:
                issues.append(
                    DomainIssue(
                        "DC_TERMINAL_NET",
                        "A terminal connects to one net in this circuit",
                        node.id,
                        incomplete=True,
                    )
                )
        fields = {
            identity("Circuit"): ("voltage_scale", "current_scale"),
            identity("Resistor"): ("resistance",),
            identity("VoltageSource"): ("voltage",),
        }.get(node.concept_id, ())
        for field in fields:
            try:
                parameter(node, field)
            except ValueError as exc:
                issues.append(DomainIssue("DC_PARAMETER", str(exc), node.id, incomplete=True))
    return tuple(issues)


def dc_notations() -> tuple[NotationDefinition, ...]:
    return (
        NotationDefinition(
            PREFIX + "notation:topology",
            "DC connectivity",
            NotationKind.GRAPH,
            node_rules=tuple(
                NotationNodeRule(identity(concept), identity(concept, "name"))
                for concept in ("Net", "Terminal", "Resistor", "VoltageSource")
            ),
            schema_id=SCHEMA_ID,
        ),
        NotationDefinition(
            PREFIX + "notation:resistors",
            "Resistor parameters",
            NotationKind.TABLE,
            concept_ids=(identity("Resistor"),),
            schema_id=SCHEMA_ID,
            columns=(
                NotationColumn("name", "Resistor", NotationField(identity("Resistor", "name"))),
                NotationColumn(
                    "resistance", "Resistance", NotationField(identity("Resistor", "resistance"))
                ),
            ),
        ),
        NotationDefinition(
            PREFIX + "notation:terminals",
            "Terminal connections",
            NotationKind.TABLE,
            concept_ids=(identity("Terminal"),),
            schema_id=SCHEMA_ID,
            columns=(
                NotationColumn("name", "Terminal", NotationField(identity("Terminal", "name"))),
                NotationColumn(
                    "net", "Net", NotationField(reference_role_ids=(identity("Terminal", "net"),))
                ),
            ),
        ),
        NotationDefinition(
            PREFIX + "notation:hierarchy",
            "Circuit hierarchy and parameters",
            NotationKind.TREE_FORM,
            schema_id=SCHEMA_ID,
        ),
    )


def dc_bundle() -> DomainExtensionBundle:
    from code_visualizer.extensions.dc_equations import lower_dc
    from code_visualizer.extensions.foundations.equations import BUNDLE as MATH_BUNDLE
    from code_visualizer.extensions.foundations.math import SCHEMA_ID as MATH_SCHEMA_ID
    from code_visualizer.extensions.publication import FIRST_PARTY_PUBLICATION
    from code_visualizer.extensions.registry import DomainExtensionBundle
    from code_visualizer.generation.transformation import RegisteredTransformation

    return DomainExtensionBundle(
        BUNDLE.id,
        BUNDLE.version,
        schemas=(dc_schema(),),
        validators=(validate_dc,),
        notations=dc_notations(),
        required_bundles=(MATH_BUNDLE,),
        publication=FIRST_PARTY_PUBLICATION,
        transformations=(
            RegisteredTransformation(TRANSFORMATION, lower_dc, SCHEMA_ID, "1", MATH_SCHEMA_ID, "2"),
        ),
    )
