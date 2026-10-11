"""Authored scalar fields and physical intervals; adaptive cell partitions are derived."""

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
from code_visualizer.domain.values import ValueConstraints
from code_visualizer.extensions.adaptive_fields.units import quantity
from code_visualizer.extensions.foundations.space import identity as space_id

BUNDLE = BundleReference("foundation.adaptive_fields", "1")
SCHEMA_ID = BUNDLE.id + ":schema"


def identity(concept: str, name: str | None = None) -> str:
    return BUNDLE.id + ":" + concept + (":" + name if name else "")


@cache
def field_schema() -> DomainSchema:
    def name(concept: str) -> PropertyDefinition:
        return PropertyDefinition(identity(concept, "name"), "Name", required=True)

    def role(concept: str, field: str, target: str) -> RoleDefinition:
        return RoleDefinition(identity(concept, field), field.title(), (target,), 1, 1)

    def amount(concept: str, field: str, unit: str) -> PropertyDefinition:
        q = quantity(1, unit)
        return PropertyDefinition(
            identity(concept, field),
            field.title(),
            ValueKind.QUANTITY,
            True,
            q,
            value_constraints=ValueConstraints(dimension=q.unit.dimension),
        )

    return DomainSchema(
        SCHEMA_ID,
        BUNDLE.id,
        "1",
        (
            ConceptDefinition(
                identity("Interval"),
                "Physical Cartesian interval",
                (
                    name("Interval"),
                    amount("Interval", "length", "meter"),
                    amount("Interval", "area", "square_meter"),
                ),
                reference_roles=(
                    role("Interval", "frame", space_id("Frame")),
                    role("Interval", "axis", space_id("Axis")),
                ),
                display_property_id=identity("Interval", "name"),
            ),
            ConceptDefinition(
                identity("Field"),
                "Conserved scalar cell-average field",
                (
                    name("Field"),
                    amount("Field", "scale", "kilogram_per_cubic_meter"),
                    PropertyDefinition(
                        identity("Field", "quantity_kind"),
                        "Quantity kind",
                        required=True,
                        default="linear",
                        choices=("linear",),
                    ),
                ),
                reference_roles=(role("Field", "region", identity("Interval")),),
                display_property_id=identity("Field", "name"),
            ),
            ConceptDefinition(
                identity("Probe"),
                "Exact retained cell sample",
                (
                    name("Probe"),
                    *(
                        PropertyDefinition(identity("Probe", field), field.title(), kind, True)
                        for field, kind in (
                            ("history", ValueKind.RESOURCE),
                            ("sample", ValueKind.INTEGER),
                            ("epoch", ValueKind.INTEGER),
                            ("cell_id", ValueKind.STRING),
                            ("component_id", ValueKind.STRING),
                            ("time", ValueKind.QUANTITY),
                        )
                    ),
                ),
                display_property_id=identity("Probe", "name"),
            ),
        ),
        BUNDLE,
        "Field identity and physical support; meshes and samples remain resources.",
    )


def notations() -> tuple[NotationDefinition, ...]:
    return (
        NotationDefinition(
            BUNDLE.id + ":form",
            "Adaptive fields and exact probes",
            NotationKind.TREE_FORM,
            schema_id=SCHEMA_ID,
        ),
    )
