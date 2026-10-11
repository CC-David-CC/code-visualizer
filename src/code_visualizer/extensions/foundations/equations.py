"""Version two math intentions: relations and explicit, unit-aware solve requests."""

from __future__ import annotations

from dataclasses import replace
from functools import cache
from typing import TYPE_CHECKING

from code_visualizer.domain.intentional import (
    BundleReference,
    ConceptDefinition,
    DomainSchema,
    PropertyDefinition,
    RoleDefinition,
    ValueKind,
)
from code_visualizer.domain.notation import (
    NotationColumn,
    NotationDefinition,
    NotationField,
    NotationKind,
)
from code_visualizer.domain.transformation import Representation
from code_visualizer.extensions.foundations.math import (
    SCHEMA_ID,
    identity,
    math_schema,
    validate_math,
)
from code_visualizer.extensions.foundations.unit_algebra import QuantityKind

if TYPE_CHECKING:
    from code_visualizer.extensions.registry import DomainExtensionBundle

BUNDLE = BundleReference("foundation.math", "2")
REPRESENTATION = Representation(BUNDLE.id, BUNDLE.version)
BACKEND_ID = "foundation.math.linear_equations"
RESULT_TYPE = "foundation.math.equation_solution"
MAX_UNKNOWNS = 256
MAX_EQUATIONS = 512
UNIT_CONCEPTS = (
    "foundation.units:UnitSystem",
    "foundation.units.algebra:UnitEquation",
    "foundation.units.algebra:ProductUnit",
)


@cache
def equation_schema() -> DomainSchema:
    """Reuse expression identities and containment, without reinterpreting math@1."""

    def name(concept: str) -> PropertyDefinition:
        return PropertyDefinition(identity(concept, "name"), "Name", required=True)

    def quantity(concept: str, field: str, *, required: bool = True) -> PropertyDefinition:
        return PropertyDefinition(
            identity(concept, field), field.replace("_", " ").title(), ValueKind.QUANTITY, required
        )

    def kind(concept: str) -> PropertyDefinition:
        return PropertyDefinition(
            identity(concept, "quantity_kind"),
            "Quantity kind",
            default="linear",
            choices=tuple(item.value for item in QuantityKind),
        )

    def role(
        concept: str,
        field: str,
        targets: tuple[str, ...],
        minimum: int = 0,
        maximum: int | None = None,
    ) -> RoleDefinition:
        return RoleDefinition(
            identity(concept, field), field.replace("_", " ").title(), targets, minimum, maximum
        )

    concepts = []
    for concept in math_schema().concepts:
        if concept.id == identity("Symbol"):
            concept = replace(
                concept,
                properties=(
                    *concept.properties,
                    quantity("Symbol", "scale", required=False),
                    kind("Symbol"),
                ),
            )
        elif concept.id == identity("QuantityLiteral"):
            concept = replace(concept, properties=(*concept.properties, kind("QuantityLiteral")))
        concepts.append(concept)
    concepts.extend(
        (
            ConceptDefinition(
                identity("Binding"),
                "Known binding",
                (quantity("Binding", "value"),),
                reference_roles=(role("Binding", "symbol", (identity("Symbol"),), 1, 1),),
            ),
            ConceptDefinition(
                identity("RelationUse"),
                "Selected equation",
                (quantity("RelationUse", "residual_scale"),),
                reference_roles=(role("RelationUse", "equation", (identity("Equation"),), 1, 1),),
            ),
            ConceptDefinition(
                identity("SolveRequest"),
                "Solve request",
                (
                    name("SolveRequest"),
                    PropertyDefinition(
                        identity("SolveRequest", "problem_class"),
                        "Problem class",
                        default="linear",
                        choices=("linear", "nonlinear", "dae"),
                    ),
                    PropertyDefinition(
                        identity("SolveRequest", "rank_tolerance"),
                        "Relative rank tolerance",
                        ValueKind.NUMBER,
                        default=1e-12,
                        minimum=0,
                        maximum=1,
                    ),
                    PropertyDefinition(
                        identity("SolveRequest", "residual_tolerance"),
                        "Normalized residual tolerance",
                        ValueKind.NUMBER,
                        default=1e-9,
                        minimum=0,
                        maximum=1,
                    ),
                    PropertyDefinition(
                        identity("SolveRequest", "condition_limit"),
                        "Scaled condition limit",
                        ValueKind.NUMBER,
                        default=1e12,
                        minimum=1,
                    ),
                ),
                (
                    role("SolveRequest", "bindings", (identity("Binding"),), 0, MAX_UNKNOWNS * 4),
                    role("SolveRequest", "relations", (identity("RelationUse"),), 1, MAX_EQUATIONS),
                ),
                (role("SolveRequest", "unknowns", (identity("Symbol"),), 1, MAX_UNKNOWNS),),
                display_property_id=identity("SolveRequest", "name"),
            ),
            ConceptDefinition(
                identity("Problem"),
                "Equation problem",
                (name("Problem"),),
                (
                    role("Problem", "symbols", (identity("Symbol"),), 1, MAX_UNKNOWNS * 5),
                    role("Problem", "equations", (identity("Equation"),), 1, MAX_EQUATIONS),
                    role("Problem", "requests", (identity("SolveRequest"),), 1, 64),
                ),
                (role("Problem", "unit_definitions", UNIT_CONCEPTS),),
                display_property_id=identity("Problem", "name"),
            ),
        )
    )
    return DomainSchema(
        SCHEMA_ID,
        BUNDLE.id,
        BUNDLE.version,
        tuple(concepts),
        BUNDLE,
        "Relations with typed symbols, explicit bindings, unknowns and numerical policy.",
    )


def equation_notations() -> tuple[NotationDefinition, ...]:
    return (
        NotationDefinition(
            identity("notation:equations:v2"),
            "Equation graph",
            NotationKind.GRAPH,
            schema_id=SCHEMA_ID,
        ),
        NotationDefinition(
            identity("notation:symbols:v2"),
            "Symbols and characteristic scales",
            NotationKind.TABLE,
            schema_id=SCHEMA_ID,
            concept_ids=(identity("Symbol"),),
            columns=tuple(
                NotationColumn(field, label, NotationField(identity("Symbol", field)))
                for field, label in (
                    ("name", "Symbol"),
                    ("scale", "Scale / output unit"),
                    ("quantity_kind", "Quantity kind"),
                )
            ),
        ),
        NotationDefinition(
            identity("notation:requests:v2"),
            "Relations and solve request",
            NotationKind.TREE_FORM,
            schema_id=SCHEMA_ID,
        ),
    )


def equation_bundle() -> DomainExtensionBundle:
    from code_visualizer.domain.identifiers import ContractDefinition, ContractKind
    from code_visualizer.extensions.foundations.equation_backend import equation_backend
    from code_visualizer.extensions.publication import FIRST_PARTY_PUBLICATION
    from code_visualizer.extensions.registry import DomainExtensionBundle

    return DomainExtensionBundle(
        BUNDLE.id,
        BUNDLE.version,
        schemas=(equation_schema(),),
        validators=(validate_math,),
        notations=equation_notations(),
        backends=(equation_backend(),),
        publication=FIRST_PARTY_PUBLICATION,
        required_bundles=(
            BundleReference("code_visualizer.computation", "2"),
            BundleReference("foundation.units.algebra.si", "1"),
        ),
        contracts=(ContractDefinition(ContractKind.RESOURCE_LOGICAL_TYPE, RESULT_TYPE, "1"),),
    )
