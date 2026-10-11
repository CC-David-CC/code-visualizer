"""A retained cell query is an authored intention, distinct from the producing field."""

from functools import cache

from code_visualizer.domain.intentional import (
    BundleReference,
    ConceptDefinition,
    DomainSchema,
    PropertyDefinition,
    ValueKind,
)
from code_visualizer.domain.notation import NotationDefinition, NotationKind
from code_visualizer.domain.transformation import Representation

BUNDLE = BundleReference("code_visualizer.hybrid_gas.observation", "1")
SCHEMA_ID = BUNDLE.id + ":schema"
REPRESENTATION = Representation(BUNDLE.id, "1")
BACKEND_ID = BUNDLE.id + ".probe"


def identity(name: str | None = None) -> str:
    return BUNDLE.id + ":Probe" + (":" + name if name else "")


@cache
def observation_schema() -> DomainSchema:
    return DomainSchema(
        SCHEMA_ID,
        BUNDLE.id,
        "1",
        (
            ConceptDefinition(
                identity(),
                "Exact retained gas cell",
                (
                    PropertyDefinition(identity("name"), "Name", required=True),
                    PropertyDefinition(
                        identity("history"), "Retained history", ValueKind.RESOURCE, True
                    ),
                    PropertyDefinition(
                        identity("sample"),
                        "Sample",
                        ValueKind.INTEGER,
                        True,
                        minimum=0,
                        maximum=255,
                    ),
                    PropertyDefinition(identity("cell_id"), "Exact cell identity", required=True),
                    PropertyDefinition(identity("component_id"), "Conserved field", required=True),
                    PropertyDefinition(identity("frame_id"), "Source frame", required=True),
                    PropertyDefinition(
                        identity("time"), "Exact physical time", ValueKind.QUANTITY, True
                    ),
                ),
                display_property_id=identity("name"),
            ),
        ),
        BUNDLE,
        "An exact retained resource/cell/component/time query. No interpolation or native solver.",
    )


def notations() -> tuple[NotationDefinition, ...]:
    return (
        NotationDefinition(
            BUNDLE.id + ":form",
            "Retained gas cell query",
            NotationKind.TREE_FORM,
            schema_id=SCHEMA_ID,
        ),
    )
