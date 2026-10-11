"""CAD consumers and independently editable imported geometry use ordinary intentions."""

from functools import cache

from code_visualizer.domain.intentional import (
    BundleReference,
    ConceptDefinition,
    DomainModel,
    DomainSchema,
    IntentionalNode,
    PropertyDefinition,
    PropertyValue,
    ValueKind,
)
from code_visualizer.domain.notation import NotationDefinition, NotationKind
from code_visualizer.domain.transformation import Representation
from code_visualizer.domain.values import (
    CanonicalValue,
    QuantityValue,
    ResourceReference,
    ValueConstraints,
)
from code_visualizer.extensions.foundations.units_si import si_catalog

BUNDLE = BundleReference("code_visualizer.cad", "1")
SCHEMA_ID = BUNDLE.id + ":schema"
REPRESENTATION = Representation(BUNDLE.id, "1")


def identity(concept: str, field: str | None = None) -> str:
    return BUNDLE.id + ":" + concept + (":" + field if field else "")


def quantity(value: float, unit: str = "meter") -> QuantityValue:
    return QuantityValue(value, si_catalog().unit("foundation.units.si:" + unit))


@cache
def cad_schema() -> DomainSchema:
    def prop(
        concept: str,
        name: str,
        kind: ValueKind = ValueKind.STRING,
        default: CanonicalValue | None = None,
        choices: tuple[CanonicalValue, ...] = (),
    ) -> PropertyDefinition:
        return PropertyDefinition(
            identity(concept, name),
            name.replace("_", " ").title(),
            kind,
            required=True,
            default=default,
            choices=choices,
        )

    def length(concept: str, name: str, value: float) -> PropertyDefinition:
        return PropertyDefinition(
            identity(concept, name),
            name.title(),
            ValueKind.QUANTITY,
            True,
            quantity(value),
            value_constraints=ValueConstraints(dimension=quantity(1).unit.dimension),
        )

    definitions = []
    for concept in ("Measurement", "Tessellation", "RegionSelection", "GeometryInput"):
        properties = [prop(concept, "name"), prop(concept, "geometry", ValueKind.RESOURCE)]
        if concept == "Tessellation":
            properties += [
                length(concept, "chordal", 0.00005),
                prop(concept, "angular", ValueKind.NUMBER, 0.1),
            ]
        elif concept == "RegionSelection":
            properties += [
                prop(concept, "frame_id"),
                prop(concept, "axis", ValueKind.STRING, "x", ("x", "y", "z")),
                prop(concept, "side", ValueKind.STRING, "min", ("min", "max")),
                prop(concept, "assignment", ValueKind.STRING, "support", ("support", "load")),
                length(concept, "tolerance", 1e-7),
                prop(concept, "expected_count", ValueKind.INTEGER, 1),
            ]
        elif concept == "GeometryInput":
            properties += [
                length(concept, "translate_x", 0.0),
                length(concept, "translate_y", 0.0),
                length(concept, "translate_z", 0.0),
                prop(concept, "source_evidence"),
                prop(concept, "source_artifact"),
            ]
        definitions.append(
            ConceptDefinition(
                identity(concept),
                concept,
                tuple(properties),
                display_property_id=identity(concept, "name"),
            )
        )
    return DomainSchema(
        SCHEMA_ID,
        BUNDLE.id,
        "1",
        tuple(definitions),
        BUNDLE,
        "Exact resource consumers, geometric boundary rules, and independent imported-solid edits.",
    )


def consumer_model(
    model_id: str,
    node_id: str,
    concept: str,
    resource: ResourceReference,
    **properties: CanonicalValue,
) -> DomainModel:
    definition = cad_schema().concept(identity(concept))
    if definition is None:
        raise ValueError("Unknown CAD consumer concept")
    values = {p.id: p.default for p in definition.properties if p.default is not None}
    values.update({identity(concept, "name"): concept, identity(concept, "geometry"): resource})
    values.update({identity(concept, key): value for key, value in properties.items()})
    node = IntentionalNode(
        node_id, definition.id, tuple(PropertyValue(key, value) for key, value in values.items())
    )
    return DomainModel(model_id, SCHEMA_ID, "1", (node_id,), (node,), concept)


def notations() -> tuple[NotationDefinition, ...]:
    return (
        NotationDefinition(
            BUNDLE.id + ":form",
            "Geometry artifacts and operations",
            NotationKind.TREE_FORM,
            schema_id=SCHEMA_ID,
        ),
    )
