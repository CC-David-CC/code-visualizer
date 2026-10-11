"""Structured mathematical intentions; Python syntax is not their representation."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from code_visualizer.domain.intentional import (
    BundleReference,
    ConceptDefinition,
    DomainIssue,
    DomainModel,
    DomainSchema,
    IntentionalNode,
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
from code_visualizer.domain.project import Project
from code_visualizer.domain.transformation import Representation

if TYPE_CHECKING:
    from code_visualizer.extensions.registry import DomainExtensionBundle

PREFIX = "foundation.math:"
SCHEMA_ID = PREFIX + "schema"
BUNDLE = BundleReference("foundation.math", "1")
REPRESENTATION = Representation(BUNDLE.id, BUNDLE.version)
EXPRESSION_NAMES = (
    "Literal",
    "ComplexLiteral",
    "QuantityLiteral",
    "TensorLiteral",
    "ResourceLiteral",
    "SymbolReference",
    "OperatorApplication",
    "Index",
    "Derivative",
    "Integral",
)
EXPRESSION_IDS = tuple(PREFIX + name for name in EXPRESSION_NAMES)
SYMBOL_IDS = (PREFIX + "Symbol", PREFIX + "TensorSymbol")


def identity(concept: str, field: str | None = None) -> str:
    return PREFIX + concept + (":" + field if field else "")


def math_schema() -> DomainSchema:
    def name(concept: str) -> PropertyDefinition:
        return PropertyDefinition(identity(concept, "name"), "Name", required=True)

    def child(
        concept: str, role: str, *, minimum: int = 1, maximum: int | None = 1
    ) -> RoleDefinition:
        return RoleDefinition(
            identity(concept, role), role.title(), EXPRESSION_IDS, minimum, maximum
        )

    def reference(
        concept: str,
        role: str,
        targets: tuple[str, ...],
        minimum: int = 1,
        maximum: int | None = 1,
    ) -> RoleDefinition:
        return RoleDefinition(identity(concept, role), role.title(), targets, minimum, maximum)

    literal_kinds = (
        ("Literal", ValueKind.NUMBER),
        ("ComplexLiteral", ValueKind.COMPLEX),
        ("QuantityLiteral", ValueKind.QUANTITY),
        ("TensorLiteral", ValueKind.TENSOR),
        ("ResourceLiteral", ValueKind.RESOURCE),
    )
    literal_ids = tuple(identity(concept) for concept, _kind in literal_kinds)
    concepts = [
        ConceptDefinition(
            identity(concept),
            concept.replace("Literal", " literal").strip().title(),
            (PropertyDefinition(identity(concept, "value"), "Value", kind, required=True),),
            display_property_id=identity(concept, "value"),
        )
        for concept, kind in literal_kinds
    ]
    concepts.extend(
        (
            ConceptDefinition(
                identity("Symbol"),
                "Symbol",
                (name("Symbol"),),
                reference_roles=(reference("Symbol", "binding", literal_ids, 0),),
                display_property_id=identity("Symbol", "name"),
                description="A stable symbol declaration. Its name is presentation, not identity.",
            ),
            ConceptDefinition(
                identity("TensorSymbol"),
                "Tensor symbol",
                (
                    name("TensorSymbol"),
                    PropertyDefinition(
                        identity("TensorSymbol", "shape"), "Shape", ValueKind.TENSOR
                    ),
                ),
                reference_roles=(
                    reference(
                        "TensorSymbol",
                        "binding",
                        (identity("TensorLiteral"), identity("ResourceLiteral")),
                        0,
                    ),
                ),
                display_property_id=identity("TensorSymbol", "name"),
                description=(
                    "Tensor declaration; a rank-one integer value optionally declares its shape."
                ),
            ),
            ConceptDefinition(
                identity("SymbolReference"),
                "Symbol reference",
                reference_roles=(reference("SymbolReference", "symbol", SYMBOL_IDS),),
                description=(
                    "An occurrence points to one declaration; "
                    "repeated indices retain occurrence identity."
                ),
            ),
            ConceptDefinition(
                identity("OperatorApplication"),
                "Operator application",
                (
                    PropertyDefinition(
                        identity("OperatorApplication", "operator"), "Operator", required=True
                    ),
                ),
                (child("OperatorApplication", "operands", maximum=None),),
                (reference("OperatorApplication", "bound_symbols", SYMBOL_IDS, 0, None),),
                display_property_id=identity("OperatorApplication", "operator"),
            ),
            ConceptDefinition(
                identity("Equation"),
                "Equation",
                (name("Equation"),),
                (child("Equation", "left"), child("Equation", "right")),
                display_property_id=identity("Equation", "name"),
            ),
            ConceptDefinition(
                identity("Constraint"),
                "Constraint",
                (name("Constraint"),),
                (child("Constraint", "predicate"),),
                display_property_id=identity("Constraint", "name"),
            ),
            ConceptDefinition(
                identity("Index"),
                "Indexed expression",
                containment_roles=(child("Index", "indices", maximum=None),),
                reference_roles=(reference("Index", "tensor", (identity("TensorSymbol"),)),),
            ),
            ConceptDefinition(
                identity("Derivative"),
                "Derivative",
                (
                    PropertyDefinition(
                        identity("Derivative", "order"),
                        "Order",
                        ValueKind.INTEGER,
                        default=1,
                        minimum=1,
                    ),
                ),
                (child("Derivative", "operand"),),
                (reference("Derivative", "variable", (identity("Symbol"),)),),
            ),
            ConceptDefinition(
                identity("Integral"),
                "Integral",
                containment_roles=(
                    child("Integral", "integrand"),
                    child("Integral", "lower", minimum=0),
                    child("Integral", "upper", minimum=0),
                ),
                reference_roles=(reference("Integral", "variable", (identity("Symbol"),)),),
            ),
            ConceptDefinition(
                identity("Function"),
                "Mathematical function",
                (name("Function"),),
                (child("Function", "body"),),
                (reference("Function", "parameters", SYMBOL_IDS, 0, None),),
                display_property_id=identity("Function", "name"),
            ),
        )
    )
    return DomainSchema(
        SCHEMA_ID,
        BUNDLE.id,
        BUNDLE.version,
        tuple(concepts),
        BUNDLE,
        "Mathematical declarations, expression occurrences, relations and binders.",
    )


def tensor_shape(node: IntentionalNode) -> tuple[int, ...] | None:
    """Read a declared mathematical shape; container validation remains in domain.values."""
    from code_visualizer.domain.values import TensorValue

    value = node.property(identity("TensorSymbol", "shape"))
    if not isinstance(value, TensorValue) or len(value.shape) != 1:
        return None
    if any(type(item) is not int or item < 0 for item in value.elements):
        return None
    return tuple(cast(int, item) for item in value.elements)


def validate_math(project: Project, model: DomainModel) -> tuple[DomainIssue, ...]:
    from code_visualizer.domain.values import TensorValue

    issues: list[DomainIssue] = []
    nodes = {
        node.id: node for candidate in project.domain_workspace.models for node in candidate.nodes
    }

    def issue(code: str, message: str, node: IntentionalNode) -> None:
        issues.append(DomainIssue(code, message, node.id, incomplete=True))

    for node in model.nodes:
        if node.concept_id == identity("TensorSymbol"):
            declared = node.property(identity("TensorSymbol", "shape"))
            shape = tensor_shape(node)
            if declared is not None and shape is None:
                issue(
                    "MATH_TENSOR_SHAPE",
                    "A declared shape is a rank-one tensor of nonnegative integers",
                    node,
                )
            for binding_id in node.reference_ids(identity("TensorSymbol", "binding")):
                bound = nodes.get(binding_id)
                value = bound.property(identity("TensorLiteral", "value")) if bound else None
                if isinstance(value, TensorValue) and shape is not None and shape != value.shape:
                    issue(
                        "MATH_TENSOR_BINDING_SHAPE",
                        "The tensor binding differs from its declared shape",
                        node,
                    )
        elif node.concept_id == identity("Index"):
            targets = node.reference_ids(identity("Index", "tensor"))
            target = nodes.get(targets[0]) if len(targets) == 1 else None
            shape = tensor_shape(target) if target else None
            if shape is not None and len(node.child_ids(identity("Index", "indices"))) != len(
                shape
            ):
                issue(
                    "MATH_INDEX_RANK",
                    "An indexed tensor needs one index expression per dimension",
                    node,
                )
        elif node.concept_id == identity("OperatorApplication"):
            raw_operator = node.property(identity("OperatorApplication", "operator"))
            operator = raw_operator if isinstance(raw_operator, str) else ""
            operands = node.child_ids(identity("OperatorApplication", "operands"))
            binders = node.reference_ids(identity("OperatorApplication", "bound_symbols"))
            arity = {
                "add": 2,
                "subtract": 2,
                "multiply": 2,
                "divide": 2,
                "sum": 1,
                "negate": 1,
                "equal": 2,
                "less_equal": 2,
                "matmul": 2,
            }
            if operator in arity and len(operands) != arity[operator]:
                issue(
                    "MATH_OPERATOR_ARITY", f"{operator} requires {arity[operator]} operands", node
                )
            if operator == "sum" and not binders:
                issue(
                    "MATH_SUM_BINDER", "A sum explicitly identifies its bound index symbols", node
                )
            if operator in arity and operator != "sum" and binders:
                issue("MATH_UNEXPECTED_BINDER", "This operator does not bind symbols", node)
        elif node.concept_id == identity("Integral"):
            lower = node.child_ids(identity("Integral", "lower"))
            upper = node.child_ids(identity("Integral", "upper"))
            if bool(lower) != bool(upper):
                issue("MATH_INTEGRAL_LIMITS", "A definite integral requires both limits", node)
    return tuple(issues)


def math_notations() -> tuple[NotationDefinition, ...]:
    return (
        NotationDefinition(
            PREFIX + "notation:expressions",
            "Mathematical structure",
            NotationKind.GRAPH,
            schema_id=SCHEMA_ID,
        ),
        NotationDefinition(
            PREFIX + "notation:symbols",
            "Tensor symbols",
            NotationKind.TABLE,
            concept_ids=(identity("TensorSymbol"),),
            schema_id=SCHEMA_ID,
            columns=(
                NotationColumn("name", "Symbol", NotationField(identity("TensorSymbol", "name"))),
                NotationColumn("shape", "Shape", NotationField(identity("TensorSymbol", "shape"))),
                NotationColumn(
                    "binding",
                    "Binding",
                    NotationField(reference_role_ids=(identity("TensorSymbol", "binding"),)),
                ),
            ),
        ),
        NotationDefinition(
            PREFIX + "notation:hierarchy",
            "Equation hierarchy and form",
            NotationKind.TREE_FORM,
            schema_id=SCHEMA_ID,
        ),
    )


def math_bundle() -> DomainExtensionBundle:
    from code_visualizer.domain.identifiers import ContractDefinition, ContractKind
    from code_visualizer.extensions.foundations.backend import math_backend
    from code_visualizer.extensions.publication import FIRST_PARTY_PUBLICATION
    from code_visualizer.extensions.registry import DomainExtensionBundle

    return DomainExtensionBundle(
        BUNDLE.id,
        BUNDLE.version,
        schemas=(math_schema(),),
        publication=FIRST_PARTY_PUBLICATION,
        validators=(validate_math,),
        notations=math_notations(),
        backends=(math_backend(),),
        required_bundles=(BundleReference("code_visualizer.computation", "2"),),
        contracts=(
            ContractDefinition(ContractKind.RESOURCE_LOGICAL_TYPE, "foundation.math.tensor", "1"),
        ),
    )
