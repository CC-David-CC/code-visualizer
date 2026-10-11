"""Authored gas, geometry and policy are ordinary intentional domain contents."""

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
from code_visualizer.domain.values import ValueConstraints
from code_visualizer.extensions.foundations.space import identity as space_id
from code_visualizer.extensions.hybrid_gas.units import quantity

BUNDLE = BundleReference("code_visualizer.hybrid_gas", "1")
SCHEMA_ID = BUNDLE.id + ":schema"
REPRESENTATION = Representation(BUNDLE.id, "1")
BACKEND_ID = BUNDLE.id + ".state_flux"
COMPONENTS = ("density", "momentum_x", "momentum_y", "momentum_z", "energy")


def identity(concept: str, name: str | None = None) -> str:
    return BUNDLE.id + ":" + concept + (":" + name if name else "")


def named(concept: str) -> PropertyDefinition:
    return PropertyDefinition(identity(concept, "name"), "Name", required=True)


def amount(concept: str, name: str, default: float, unit: str) -> PropertyDefinition:
    q = quantity(default, unit)
    return PropertyDefinition(
        identity(concept, name),
        name.replace("_", " ").title(),
        ValueKind.QUANTITY,
        True,
        q,
        value_constraints=ValueConstraints(dimension=q.unit.dimension),
    )


def count(concept: str, name: str, default: int, low: int, high: int) -> PropertyDefinition:
    return PropertyDefinition(
        identity(concept, name),
        name.replace("_", " ").title(),
        ValueKind.INTEGER,
        True,
        default,
        minimum=low,
        maximum=high,
    )


def choice(concept: str, name: str, choices: tuple[str, ...]) -> PropertyDefinition:
    return PropertyDefinition(
        identity(concept, name),
        name.replace("_", " ").title(),
        required=True,
        default=choices[0],
        choices=choices,
    )


def role(concept: str, name: str, target: str, size: int = 1) -> RoleDefinition:
    return RoleDefinition(identity(concept, name), name.title(), (target,), size, size)


@cache
def gas_schema() -> DomainSchema:
    return DomainSchema(
        SCHEMA_ID,
        BUNDLE.id,
        "1",
        (
            ConceptDefinition(
                identity("Problem"),
                "Particle / continuum gas experiment",
                (named("Problem"),),
                containment_roles=(
                    *(
                        role("Problem", name, identity(kind))
                        for name, kind in (
                            ("gas", "Gas"),
                            ("channel", "Channel"),
                            ("slab", "Slab"),
                            ("initial", "Initial"),
                            ("policy", "Policy"),
                        )
                    ),
                    role("Problem", "walls", identity("Wall"), 2),
                    role("Problem", "interfaces", identity("Interface"), 2),
                    role("Problem", "fields", identity("Field"), 5),
                ),
                display_property_id=identity("Problem", "name"),
            ),
            ConceptDefinition(
                identity("Gas"),
                "Monatomic argon VSS / ideal-gas closure",
                (
                    named("Gas"),
                    choice("Gas", "species", ("argon_vss_0.81_1.4",)),
                    choice("Gas", "interpretation", ("mean_flow",)),
                    PropertyDefinition(
                        identity("Gas", "calibration"),
                        "Independent viscosity observations",
                        ValueKind.RESOURCE,
                        required=True,
                    ),
                ),
                display_property_id=identity("Gas", "name"),
            ),
            ConceptDefinition(
                identity("Channel"),
                "Planar channel",
                (
                    named("Channel"),
                    amount("Channel", "height", 0.002, "meter"),
                    amount("Channel", "area", 1e-10, "square_meter"),
                ),
                reference_roles=(
                    role("Channel", "frame", space_id("Frame")),
                    role("Channel", "axis", space_id("Axis")),
                ),
                display_property_id=identity("Channel", "name"),
            ),
            ConceptDefinition(
                identity("Slab"),
                "Disjoint particle-owned region",
                (
                    named("Slab"),
                    amount("Slab", "lower", 0.00075, "meter"),
                    amount("Slab", "upper", 0.00125, "meter"),
                ),
                display_property_id=identity("Slab", "name"),
            ),
            ConceptDefinition(
                identity("Wall"),
                "Fixed diffuse wall",
                (
                    named("Wall"),
                    choice("Wall", "side", ("lower", "upper")),
                    amount("Wall", "temperature", 273.15, "kelvin"),
                    amount("Wall", "velocity_x", 0, "meter_per_second"),
                    amount("Wall", "velocity_z", 0, "meter_per_second"),
                ),
                display_property_id=identity("Wall", "name"),
            ),
            ConceptDefinition(
                identity("Interface"),
                "Oriented state/flux interface",
                (named("Interface"), choice("Interface", "side", ("lower", "upper"))),
                display_property_id=identity("Interface", "name"),
            ),
            ConceptDefinition(
                identity("Field"),
                "Conserved gas field",
                (named("Field"), choice("Field", "component", COMPONENTS)),
                display_property_id=identity("Field", "name"),
            ),
            ConceptDefinition(
                identity("Initial"),
                "Uniform gas with optional sinusoidal shear",
                (
                    named("Initial"),
                    amount("Initial", "number_density", 7.07043e22, "per_cubic_meter"),
                    amount("Initial", "temperature", 273.15, "kelvin"),
                    *(
                        amount("Initial", "velocity_" + axis, 0, "meter_per_second")
                        for axis in "xyz"
                    ),
                    amount("Initial", "sine_amplitude", 0, "meter_per_second"),
                ),
                display_property_id=identity("Initial", "name"),
            ),
            ConceptDefinition(
                identity("Policy"),
                "Frozen computation and return policy",
                (
                    named("Policy"),
                    choice("Policy", "mode", ("fixed", "adaptive", "continuum", "particle")),
                    amount("Policy", "quantum", 7e-9, "second"),
                    count("Policy", "cells", 64, 16, 128),
                    count("Policy", "collision_cells", 200, 16, 512),
                    count("Policy", "particles_full_channel", 20000, 400, 20000),
                    count("Policy", "maximum_particles", 20000, 400, 20000),
                    count("Policy", "seed", 716149, 1, (1 << 31) - 1),
                    count("Policy", "window_ticks", 2, 1, 64),
                    count("Policy", "final_tick", 340000, 1, 400000),
                    count("Policy", "sample_ticks", 2000, 1, 400000),
                    count("Policy", "checkpoint_ticks", 40000, 1, 400000),
                    count("Policy", "statistics_ticks", 1000, 1, 400000),
                    count("Policy", "warmup_ticks", 100000, 0, 400000),
                    count("Policy", "block_ticks", 12000, 1, 400000),
                    count("Policy", "chunk_rows", 16, 1, 256),
                    count("Policy", "preview_windows", 1000, 1, 200000),
                    count("Policy", "low_opportunities", 3, 1, 64),
                    count("Policy", "minimum_dwell_ticks", 100000, 0, 400000),
                    count("Policy", "maximum_switches", 2, 1, 8),
                    PropertyDefinition(
                        identity("Policy", "activation_threshold"),
                        "Activation gradient Knudsen",
                        ValueKind.NUMBER,
                        True,
                        0.004,
                        minimum=0,
                        maximum=0.05,
                    ),
                    PropertyDefinition(
                        identity("Policy", "return_threshold"),
                        "Return gradient Knudsen",
                        ValueKind.NUMBER,
                        True,
                        0.001,
                        minimum=0,
                        maximum=0.05,
                    ),
                ),
                display_property_id=identity("Policy", "name"),
            ),
        ),
        BUNDLE,
        "Bounded mean-flow argon; state/flux coupling, explicit units, "
        "retained calibration and policy.",
    )


def notations() -> tuple[NotationDefinition, ...]:
    return (
        NotationDefinition(
            BUNDLE.id + ":form", "Gas experiment", NotationKind.TREE_FORM, schema_id=SCHEMA_ID
        ),
    )
