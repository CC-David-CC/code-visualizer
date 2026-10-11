"""Diffusion problems, initial/boundary conditions and time policy are intentions."""

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
from code_visualizer.domain.values import QuantityValue, ValueConstraints
from code_visualizer.extensions.fields.domain import identity as field_id
from code_visualizer.extensions.fields.units import field_catalog

BUNDLE = BundleReference("code_visualizer.diffusion", "1")
SCHEMA_ID = BUNDLE.id + ":schema"
REPRESENTATION = Representation(BUNDLE.id, "1")
BACKEND_ID = BUNDLE.id + ".crank_nicolson"
CHECKPOINT_PARAMETER = "checkpoint"


def identity(concept: str, name: str | None = None) -> str:
    return BUNDLE.id + ":" + concept + (":" + name if name else "")


def quantity(value: float, unit: str = "second") -> QuantityValue:
    namespace = "foundation.fields.units" if unit.startswith("square_") else "foundation.units.si"
    return QuantityValue(value, field_catalog().unit(namespace + ":" + unit))


@cache
def diffusion_schema() -> DomainSchema:
    def name(concept: str) -> PropertyDefinition:
        return PropertyDefinition(identity(concept, "name"), "Name", required=True)

    def amount(concept: str, field: str, value: float, unit: str) -> PropertyDefinition:
        default = quantity(value, unit)
        return PropertyDefinition(
            identity(concept, field),
            field.replace("_", " ").title(),
            ValueKind.QUANTITY,
            True,
            default,
            value_constraints=ValueConstraints(dimension=default.unit.dimension),
        )

    def count(field: str, default: int, maximum: int = 1000000) -> PropertyDefinition:
        return PropertyDefinition(
            identity("TimePolicy", field),
            field.replace("_", " ").title(),
            ValueKind.INTEGER,
            True,
            default,
            minimum=1,
            maximum=maximum,
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
                "Constant one-dimensional diffusion",
                (
                    name("Problem"),
                    amount("Problem", "diffusivity", 0.1, "square_meter_per_second"),
                ),
                containment_roles=(
                    role("Problem", "initial", identity("SineInitial")),
                    role("Problem", "boundary", identity("ZeroBoundary")),
                    role("Problem", "policy", identity("TimePolicy")),
                ),
                reference_roles=(role("Problem", "field", field_id("Field")),),
                display_property_id=identity("Problem", "name"),
                description="du/dt = D d²u/dx² on one fixed uniform Cartesian grid.",
            ),
            ConceptDefinition(
                identity("SineInitial"),
                "First sine mode",
                (
                    name("SineInitial"),
                    PropertyDefinition(
                        identity("SineInitial", "amplitude"),
                        "Amplitude",
                        ValueKind.QUANTITY,
                        True,
                        quantity(10.0, "kelvin"),
                    ),
                ),
                display_property_id=identity("SineInitial", "name"),
                description="u(x,0)=amplitude sin(pi x/L); only this declared mode is supported.",
            ),
            ConceptDefinition(
                identity("ZeroBoundary"),
                "Zero Dirichlet endpoints",
                (name("ZeroBoundary"),),
                display_property_id=identity("ZeroBoundary", "name"),
            ),
            ConceptDefinition(
                identity("TimePolicy"),
                "Fixed integration and publication policy",
                (
                    name("TimePolicy"),
                    amount("TimePolicy", "final_time", 1.0, "second"),
                    count("steps", 2048),
                    count("sample_every", 16),
                    count("checkpoint_every", 512),
                    count("preview_every", 16),
                    count("chunk_rows", 256, 262144),
                ),
                display_property_id=identity("TimePolicy", "name"),
            ),
        ),
        BUNDLE,
        "A finite scalar interval experiment, with explicit numerical and publication policy.",
    )


def notations() -> tuple[NotationDefinition, ...]:
    return (
        NotationDefinition(
            BUNDLE.id + ":form", "Diffusion experiment", NotationKind.TREE_FORM, schema_id=SCHEMA_ID
        ),
    )
