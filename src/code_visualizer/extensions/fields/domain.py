"""Authored fields/support and exact probes are ordinary domain intentions."""

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
from code_visualizer.extensions.foundations.space import identity as space_id

BUNDLE = BundleReference("foundation.fields", "1")
SCHEMA_ID = BUNDLE.id + ":schema"


def identity(concept: str, field: str | None = None) -> str:
    return BUNDLE.id + ":" + concept + (":" + field if field else "")


@cache
def field_schema() -> DomainSchema:
    def prop(concept: str, name: str, kind: ValueKind = ValueKind.STRING) -> PropertyDefinition:
        return PropertyDefinition(identity(concept, name), name.title(), kind, required=True)

    def role(concept: str, name: str, target: str) -> RoleDefinition:
        return RoleDefinition(identity(concept, name), name.title(), (target,), 1, 1)

    return DomainSchema(
        SCHEMA_ID,
        BUNDLE.id,
        "1",
        (
            ConceptDefinition(
                identity("Field"),
                "Scalar field",
                (
                    prop("Field", "name"),
                    prop("Field", "scale", ValueKind.QUANTITY),
                    PropertyDefinition(
                        identity("Field", "quantity_kind"),
                        "Quantity kind",
                        required=True,
                        default="interval",
                        choices=("linear", "interval", "point"),
                    ),
                ),
                reference_roles=(role("Field", "grid", identity("UniformGrid")),),
                display_property_id=identity("Field", "name"),
            ),
            ConceptDefinition(
                identity("UniformGrid"),
                "Uniform one-dimensional grid",
                (
                    prop("UniformGrid", "name"),
                    prop("UniformGrid", "length", ValueKind.QUANTITY),
                    PropertyDefinition(
                        identity("UniformGrid", "nodes"),
                        "Nodes",
                        ValueKind.INTEGER,
                        required=True,
                        default=65,
                        minimum=3,
                        maximum=262144,
                    ),
                ),
                reference_roles=(
                    role("UniformGrid", "frame", space_id("Frame")),
                    role("UniformGrid", "axis", space_id("Axis")),
                ),
                display_property_id=identity("UniformGrid", "name"),
            ),
            ConceptDefinition(
                identity("Probe"),
                "Exact retained field sample",
                (
                    prop("Probe", "name"),
                    prop("Probe", "series", ValueKind.RESOURCE),
                    prop("Probe", "frame_id"),
                    prop("Probe", "component_id"),
                    prop("Probe", "sample", ValueKind.INTEGER),
                    prop("Probe", "node", ValueKind.INTEGER),
                    prop("Probe", "time", ValueKind.QUANTITY),
                ),
                display_property_id=identity("Probe", "name"),
            ),
        ),
        BUNDLE,
        "Scalar field meaning, authored spatial support, and explicit immutable sample probes.",
    )


def notations() -> tuple[NotationDefinition, ...]:
    return (
        NotationDefinition(
            BUNDLE.id + ":form",
            "Fields, grids and probes",
            NotationKind.TREE_FORM,
            schema_id=SCHEMA_ID,
        ),
    )
