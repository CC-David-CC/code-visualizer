"""Bounded Fourier diffusion and adaptive policy are ordinary canonical intentions."""

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
from code_visualizer.extensions.adaptive_fields.domain import identity as field_id
from code_visualizer.extensions.adaptive_fields.units import quantity

BUNDLE = BundleReference("code_visualizer.adaptive_diffusion", "1")
SCHEMA_ID = BUNDLE.id + ":schema"
REPRESENTATION = Representation(BUNDLE.id, "1")
BACKEND_ID = BUNDLE.id + ".finite_volume"
CHECKPOINT_PARAMETER = "checkpoint"


def identity(concept: str, name: str | None = None) -> str:
    return BUNDLE.id + ":" + concept + (":" + name if name else "")


@cache
def adaptive_schema() -> DomainSchema:
    def name(concept: str) -> PropertyDefinition:
        return PropertyDefinition(identity(concept, "name"), "Name", required=True)

    def amount(concept: str, field: str, default: float, unit: str) -> PropertyDefinition:
        q = quantity(default, unit)
        return PropertyDefinition(
            identity(concept, field),
            field.replace("_", " ").title(),
            ValueKind.QUANTITY,
            True,
            q,
            value_constraints=ValueConstraints(dimension=q.unit.dimension),
        )

    def count(field: str, default: int, minimum: int, maximum: int) -> PropertyDefinition:
        return PropertyDefinition(
            identity("Policy", field),
            field.replace("_", " ").title(),
            ValueKind.INTEGER,
            True,
            default,
            minimum=minimum,
            maximum=maximum,
        )

    def ratio(field: str, default: float) -> PropertyDefinition:
        return PropertyDefinition(
            identity("Policy", field),
            field.replace("_", " ").title(),
            ValueKind.NUMBER,
            True,
            default,
            minimum=0.0,
            maximum=1.0,
        )

    def role(concept: str, field: str, target: str) -> RoleDefinition:
        return RoleDefinition(identity(concept, field), field.title(), (target,), 1, 1)

    return DomainSchema(
        SCHEMA_ID,
        BUNDLE.id,
        "1",
        (
            ConceptDefinition(
                identity("Problem"),
                "Adaptive periodic diffusion",
                (
                    name("Problem"),
                    amount("Problem", "diffusivity", 0.001, "square_meter_per_second"),
                    PropertyDefinition(
                        identity("Problem", "boundary"),
                        "Boundary",
                        required=True,
                        default="periodic",
                        choices=("periodic",),
                    ),
                ),
                containment_roles=(
                    role("Problem", "initial", identity("FourierInitial")),
                    role("Problem", "policy", identity("Policy")),
                ),
                reference_roles=(role("Problem", "field", field_id("Field")),),
                display_property_id=identity("Problem", "name"),
            ),
            ConceptDefinition(
                identity("FourierInitial"),
                "Finite Fourier initial concentration",
                (
                    name("FourierInitial"),
                    amount("FourierInitial", "mean", 1, "kilogram_per_cubic_meter"),
                    amount("FourierInitial", "center", 0.5, "meter"),
                ),
                containment_roles=(
                    RoleDefinition(
                        identity("FourierInitial", "modes"), "Modes", (identity("Mode"),), 0, 8
                    ),
                ),
                display_property_id=identity("FourierInitial", "name"),
            ),
            ConceptDefinition(
                identity("Mode"),
                "Cosine mode",
                (
                    name("Mode"),
                    PropertyDefinition(
                        identity("Mode", "mode"),
                        "Mode",
                        ValueKind.INTEGER,
                        True,
                        minimum=1,
                        maximum=8,
                    ),
                    amount("Mode", "amplitude", 0.1, "kilogram_per_cubic_meter"),
                ),
                display_property_id=identity("Mode", "name"),
            ),
            ConceptDefinition(
                identity("Policy"),
                "Frozen adaptive computation policy",
                (
                    name("Policy"),
                    PropertyDefinition(
                        identity("Policy", "mesh_mode"),
                        "Mesh policy",
                        required=True,
                        default="adaptive",
                        choices=("adaptive", "uniform"),
                    ),
                    amount("Policy", "final_time", 20, "second"),
                    amount("Policy", "maximum_dt", 0.05, "second"),
                    amount("Policy", "sample_interval", 0.1, "second"),
                    amount("Policy", "checkpoint_interval", 2, "second"),
                    amount("Policy", "spatial_atol", 0.004, "kilogram_per_cubic_meter"),
                    amount("Policy", "temporal_atol", 0.0001, "kilogram_per_cubic_meter"),
                    ratio("spatial_rtol", 0.008),
                    ratio("temporal_rtol", 0.0002),
                    ratio("coarsen_threshold", 0.25),
                    ratio("parent_threshold", 0.5),
                    count("base_cells", 16, 16, 512),
                    count("maximum_cells", 512, 16, 512),
                    count("maximum_level", 5, 0, 5),
                    count("subdivisions", 10, 0, 20),
                    count("coarsen_after", 3, 1, 1000),
                    count("dwell", 2, 1, 1000),
                    count("decision_every", 4, 1, 64),
                    count("maximum_steps", 8192, 1, 8192),
                    count("maximum_rejections", 64, 1, 1024),
                    count("maximum_epochs", 32, 1, 32),
                    count("chunk_rows", 16, 1, 256),
                    count("preview_every", 4, 1, 8192),
                ),
                display_property_id=identity("Policy", "name"),
            ),
        ),
        BUNDLE,
        "Explicit conserved concentration, Fourier initial meaning, and finite adaptive policy.",
    )


def notations() -> tuple[NotationDefinition, ...]:
    return (
        NotationDefinition(
            BUNDLE.id + ":form",
            "Adaptive diffusion policy",
            NotationKind.TREE_FORM,
            schema_id=SCHEMA_ID,
        ),
    )
