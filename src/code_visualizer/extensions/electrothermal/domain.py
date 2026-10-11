"""Authored bodies, component law, exchanges and fixed-window policy."""

from functools import cache

from code_visualizer.domain.intentional import (
    BundleReference,
    ConceptDefinition,
    DomainSchema,
    PropertyDefinition,
    RoleDefinition,
    ValueKind,
)
from code_visualizer.domain.notation import NotationDefinition, NotationKind
from code_visualizer.domain.transformation import Representation
from code_visualizer.domain.values import CanonicalValue, ValueConstraints
from code_visualizer.extensions.dc import identity as dc_id
from code_visualizer.extensions.electrothermal.units import quantity
from code_visualizer.extensions.foundations.equations import UNIT_CONCEPTS

BUNDLE = BundleReference("org.codevisualizer.electrothermal", "1")
SCHEMA_ID = BUNDLE.id + ":schema"
REPRESENTATION = Representation(BUNDLE.id, "1")
BACKEND_ID = BUNDLE.id + ".backward_euler"
MAPPING_ID = BUNDLE.id + ".lumped_identity"
METHOD_ID = BUNDLE.id + ".partitioned_backward_euler"
CHECKPOINT_PARAMETER = "checkpoint"


def identity(concept: str, field: str | None = None) -> str:
    return BUNDLE.id + ":" + concept + (":" + field if field else "")


@cache
def electrothermal_schema() -> DomainSchema:
    def prop(c: str, key: str, default: CanonicalValue) -> PropertyDefinition:
        kinds = {str: ValueKind.STRING, int: ValueKind.INTEGER, float: ValueKind.NUMBER}
        kind = kinds.get(type(default), ValueKind.QUANTITY)
        return PropertyDefinition(
            identity(c, key), key.replace("_", " ").title(), kind, True, default
        )

    def amount(c: str, key: str, default: float, unit: str) -> PropertyDefinition:
        value = quantity(default, unit)
        return PropertyDefinition(
            identity(c, key),
            key.replace("_", " ").title(),
            ValueKind.QUANTITY,
            True,
            value,
            value_constraints=ValueConstraints(dimension=value.unit.dimension),
        )

    def role(c: str, key: str, target: str, count: int = 1) -> RoleDefinition:
        return RoleDefinition(identity(c, key), key.title(), (target,), count, count)

    def concept(
        c: str,
        properties: tuple[PropertyDefinition, ...] = (),
        children: tuple[RoleDefinition, ...] = (),
        references: tuple[RoleDefinition, ...] = (),
    ) -> ConceptDefinition:
        return ConceptDefinition(
            identity(c),
            c,
            (prop(c, "name", c), *properties),
            children,
            references,
            display_property_id=identity(c, "name"),
        )

    return DomainSchema(
        SCHEMA_ID,
        BUNDLE.id,
        "1",
        (
            concept(
                "Experiment",
                children=(
                    role("Experiment", "bodies", identity("ThermalBody"), 2),
                    role("Experiment", "law", identity("ResistanceLaw")),
                    role("Experiment", "contact", identity("ThermalContact")),
                    role("Experiment", "ambient", identity("AmbientSink")),
                    role("Experiment", "exchanges", identity("Exchange"), 2),
                    role("Experiment", "policy", identity("WindowPolicy")),
                ),
                references=(
                    role("Experiment", "circuit", dc_id("Circuit")),
                    RoleDefinition(
                        identity("Experiment", "unit_definitions"), "Unit vocabulary", UNIT_CONCEPTS
                    ),
                ),
            ),
            concept(
                "ThermalBody",
                (
                    amount("ThermalBody", "capacity", 10, "joule_per_kelvin"),
                    amount("ThermalBody", "initial_temperature", 293.15, "kelvin"),
                    prop("ThermalBody", "temperature_kind", "point"),
                ),
            ),
            concept(
                "ResistanceLaw",
                (
                    amount("ResistanceLaw", "alpha", 0.004, "per_kelvin"),
                    amount("ResistanceLaw", "reference_temperature", 293.15, "kelvin"),
                    prop("ResistanceLaw", "temperature_kind", "point"),
                ),
                references=(
                    role("ResistanceLaw", "resistor", dc_id("Resistor")),
                    role("ResistanceLaw", "body", identity("ThermalBody")),
                ),
            ),
            concept(
                "ThermalContact",
                (amount("ThermalContact", "conductance", 0.2, "watt_per_kelvin"),),
                references=(
                    role("ThermalContact", "source", identity("ThermalBody")),
                    role("ThermalContact", "target", identity("ThermalBody")),
                ),
            ),
            concept(
                "AmbientSink",
                (
                    amount("AmbientSink", "conductance", 0.1, "watt_per_kelvin"),
                    amount("AmbientSink", "temperature", 293.15, "kelvin"),
                    prop("AmbientSink", "temperature_kind", "point"),
                ),
                references=(role("AmbientSink", "body", identity("ThermalBody")),),
            ),
            concept(
                "Exchange",
                (
                    prop("Exchange", "source_port", "temperature"),
                    prop("Exchange", "target_port", "temperature"),
                    prop("Exchange", "source_kind", "point"),
                    prop("Exchange", "target_kind", "point"),
                    prop("Exchange", "source_scale", quantity(1, "kelvin")),
                    prop("Exchange", "target_scale", quantity(1, "kelvin")),
                    prop("Exchange", "mapping_id", MAPPING_ID),
                    prop("Exchange", "mapping_version", "1"),
                    prop("Exchange", "support_kind", "lumped_body"),
                    prop("Exchange", "time_policy", "same_endpoint"),
                    prop("Exchange", "sign", 1),
                ),
                references=(
                    *(
                        RoleDefinition(
                            identity("Exchange", key),
                            key.title(),
                            (identity("ThermalBody"), dc_id("Resistor")),
                            1,
                            1,
                        )
                        for key in ("source", "target")
                    ),
                    role("Exchange", "source_support", identity("ThermalBody")),
                    role("Exchange", "target_support", identity("ThermalBody")),
                ),
            ),
            concept(
                "WindowPolicy",
                (
                    amount("WindowPolicy", "duration", 100, "second"),
                    prop("WindowPolicy", "windows", 100),
                    prop("WindowPolicy", "max_iterations", 50),
                    prop("WindowPolicy", "evaluation_order", "electrical_first"),
                    prop("WindowPolicy", "method_id", METHOD_ID),
                    prop("WindowPolicy", "method_version", "1"),
                    prop("WindowPolicy", "sample_every", 5),
                    prop("WindowPolicy", "checkpoint_every", 25),
                    prop("WindowPolicy", "preview_every", 5),
                    prop("WindowPolicy", "chunk_rows", 64),
                    amount("WindowPolicy", "temperature_scale", 1, "kelvin"),
                    amount("WindowPolicy", "power_scale", 1, "watt"),
                    amount("WindowPolicy", "energy_scale", 1, "joule"),
                ),
            ),
        ),
        BUNDLE,
        "Two lumped thermal bodies coupled to an authored constant-voltage DC resistor.",
    )


def notations() -> tuple[NotationDefinition, ...]:
    return (
        NotationDefinition(
            BUNDLE.id + ":form",
            "Electrothermal experiment",
            NotationKind.TREE_FORM,
            schema_id=SCHEMA_ID,
        ),
    )
