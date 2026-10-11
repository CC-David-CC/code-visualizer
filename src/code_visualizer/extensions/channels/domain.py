"""Authored exact consumers of immutable lumped history are ordinary domain objects."""

from functools import cache

from code_visualizer.domain.intentional import (
    BundleReference,
    ConceptDefinition,
    DomainSchema,
    PropertyDefinition,
    ValueKind,
)
from code_visualizer.domain.notation import NotationDefinition, NotationKind

BUNDLE = BundleReference("foundation.channels", "1")
SCHEMA_ID = BUNDLE.id + ":schema"


def identity(name: str, field: str | None = None) -> str:
    return BUNDLE.id + ":" + name + (":" + field if field else "")


@cache
def channel_schema() -> DomainSchema:
    properties = (
        ("name", ValueKind.STRING),
        ("series", ValueKind.RESOURCE),
        ("channel_id", ValueKind.STRING),
        ("support_id", ValueKind.STRING),
        ("quantity_kind", ValueKind.STRING),
        ("sample", ValueKind.INTEGER),
        ("time", ValueKind.QUANTITY),
    )
    return DomainSchema(
        SCHEMA_ID,
        BUNDLE.id,
        "1",
        (
            ConceptDefinition(
                identity("Probe"),
                "Exact retained channel sample",
                tuple(
                    PropertyDefinition(
                        identity("Probe", name), name.replace("_", " ").title(), kind, required=True
                    )
                    for name, kind in properties
                ),
                display_property_id=identity("Probe", "name"),
            ),
        ),
        BUNDLE,
        "Explicit, exact consumers of retained time/channel meaning.",
    )


def notations() -> tuple[NotationDefinition, ...]:
    return (
        NotationDefinition(
            BUNDLE.id + ":form",
            "Retained channel probes",
            NotationKind.TREE_FORM,
            schema_id=SCHEMA_ID,
        ),
    )
