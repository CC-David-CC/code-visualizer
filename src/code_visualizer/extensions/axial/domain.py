"""Authored material, exact geometry, idealization, region-based support and load."""

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
from code_visualizer.domain.values import CanonicalValue, QuantityValue, ValueConstraints
from code_visualizer.extensions.cad.domain import identity as cad_id
from code_visualizer.extensions.cad.units import cad_catalog
from code_visualizer.extensions.foundations.equations import UNIT_CONCEPTS

BUNDLE = BundleReference("org.codevisualizer.axial", "1")
SCHEMA_ID = BUNDLE.id + ":schema"
REPRESENTATION = Representation(BUNDLE.id, "1")
BACKEND_ID = BUNDLE.id + ".linear_bar"
IDEALIZATION_ID = BUNDLE.id + ".solid_prism_to_axis"


def identity(concept: str, field: str | None = None) -> str:
    return BUNDLE.id + ":" + concept + (":" + field if field else "")


def quantity(value: float, unit: str = "meter") -> QuantityValue:
    namespace = (
        "code_visualizer.cad.units:"
        if unit in ("square_meter", "cubic_meter")
        else "foundation.units.algebra.si:"
        if unit == "newton_per_meter"
        else "foundation.units.si:"
    )
    return QuantityValue(value, cad_catalog().unit(namespace + unit))


@cache
def axial_schema() -> DomainSchema:
    def prop(
        concept: str, field: str, kind: ValueKind, default: CanonicalValue | None = None
    ) -> PropertyDefinition:
        return PropertyDefinition(
            identity(concept, field),
            field.replace("_", " ").title(),
            kind,
            True,
            default,
            value_constraints=ValueConstraints(dimension=default.unit.dimension)
            if isinstance(default, QuantityValue)
            else ValueConstraints(),
        )

    def role(concept: str, field: str, target: str) -> RoleDefinition:
        return RoleDefinition(identity(concept, field), field.title(), (target,), 1, 1)

    def concept(
        name: str,
        properties: tuple[PropertyDefinition, ...] = (),
        children: tuple[RoleDefinition, ...] = (),
        references: tuple[RoleDefinition, ...] = (),
    ) -> ConceptDefinition:
        return ConceptDefinition(
            identity(name),
            name,
            (prop(name, "name", ValueKind.STRING, name), *properties),
            children,
            references,
            display_property_id=identity(name, "name"),
        )

    return DomainSchema(
        SCHEMA_ID,
        BUNDLE.id,
        "1",
        (
            concept(
                "AxialProblem",
                (prop("AxialProblem", "nodes", ValueKind.INTEGER, 9),),
                tuple(
                    role("AxialProblem", key, identity(target))
                    for key, target in (
                        ("material", "Material"),
                        ("geometry", "GeometryIdealization"),
                        ("support", "AxialSupport"),
                        ("load", "AxialLoad"),
                    )
                ),
                (
                    RoleDefinition(
                        identity("AxialProblem", "unit_definitions"),
                        "Unit vocabulary",
                        UNIT_CONCEPTS,
                    ),
                ),
            ),
            concept(
                "Material",
                (prop("Material", "young_modulus", ValueKind.QUANTITY, quantity(2e11, "pascal")),),
            ),
            concept(
                "GeometryIdealization",
                (
                    prop("GeometryIdealization", "geometry", ValueKind.RESOURCE),
                    prop("GeometryIdealization", "frame_id", ValueKind.STRING),
                    prop("GeometryIdealization", "axis", ValueKind.STRING, "x"),
                    prop("GeometryIdealization", "method_id", ValueKind.STRING, IDEALIZATION_ID),
                    prop("GeometryIdealization", "method_version", ValueKind.STRING, "1"),
                ),
            ),
            concept(
                "AxialSupport",
                (prop("AxialSupport", "displacement", ValueKind.QUANTITY, quantity(0)),),
                references=(role("AxialSupport", "region", cad_id("RegionSelection")),),
            ),
            concept(
                "AxialLoad",
                (
                    prop("AxialLoad", "force", ValueKind.QUANTITY, quantity(1000, "newton")),
                    prop("AxialLoad", "axis", ValueKind.STRING, "x"),
                    prop("AxialLoad", "frame_id", ValueKind.STRING),
                ),
                references=(role("AxialLoad", "region", cad_id("RegionSelection")),),
            ),
        ),
        BUNDLE,
        "Verified solid rectangular prism; small-strain axial displacement, "
        "fixed end and signed resultant.",
    )


def notations() -> tuple[NotationDefinition, ...]:
    return (
        NotationDefinition(
            BUNDLE.id + ":form",
            "Axial material, geometry and boundary conditions",
            NotationKind.TREE_FORM,
            schema_id=SCHEMA_ID,
        ),
    )
