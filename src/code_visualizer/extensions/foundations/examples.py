"""Small ordinary intention models used by the first-party foundation proofs."""

from code_visualizer.domain.intentional import (
    DomainModel,
    DomainWorkspace,
    IntentionalNode,
    PropertyValue,
    RoleBinding,
)
from code_visualizer.domain.project import Project
from code_visualizer.domain.values import TensorDType, TensorValue
from code_visualizer.extensions.foundations.math import BUNDLE, SCHEMA_ID, identity, math_schema


def matrix_product_project() -> Project:
    """C[i,j] = sum(k, A[i,k] * B[k,j]); labels never supply executable syntax."""
    nodes: list[IntentionalNode] = []
    roots: list[str] = []

    def root(node: IntentionalNode) -> None:
        nodes.append(node)
        roots.append(node.id)

    for name in ("i", "j", "k"):
        root(
            IntentionalNode(
                f"matrix:{name}",
                identity("Symbol"),
                (PropertyValue(identity("Symbol", "name"), name),),
            )
        )
    for name, values in (("A", (1.0, 2.0, 3.0, 4.0)), ("B", (5.0, 6.0, 7.0, 8.0)), ("C", None)):
        root(
            IntentionalNode(
                f"matrix:{name}",
                identity("TensorSymbol"),
                (
                    PropertyValue(identity("TensorSymbol", "name"), name),
                    PropertyValue(
                        identity("TensorSymbol", "shape"),
                        TensorValue(TensorDType.INT64, (2,), (2, 2)),
                    ),
                ),
                references=(
                    RoleBinding(identity("TensorSymbol", "binding"), (f"matrix:{name}:value",)),
                )
                if values is not None
                else (),
            )
        )
        if values is not None:
            root(
                IntentionalNode(
                    f"matrix:{name}:value",
                    identity("TensorLiteral"),
                    (
                        PropertyValue(
                            identity("TensorLiteral", "value"),
                            TensorValue(TensorDType.FLOAT64, (2, 2), values),
                        ),
                    ),
                )
            )

    def indexed(name: str, variables: tuple[str, ...]) -> str:
        node_id = f"matrix:expression:{name}"
        children = []
        for ordinal, variable in enumerate(variables):
            child_id = f"{node_id}:index:{ordinal}"
            children.append(child_id)
            nodes.append(
                IntentionalNode(
                    child_id,
                    identity("SymbolReference"),
                    references=(
                        RoleBinding(identity("SymbolReference", "symbol"), (f"matrix:{variable}",)),
                    ),
                )
            )
        nodes.append(
            IntentionalNode(
                node_id,
                identity("Index"),
                children=(RoleBinding(identity("Index", "indices"), tuple(children)),),
                references=(RoleBinding(identity("Index", "tensor"), (f"matrix:{name}",)),),
            )
        )
        return node_id

    left = indexed("C", ("i", "j"))
    right_a = indexed("A", ("i", "k"))
    right_b = indexed("B", ("k", "j"))
    multiply = IntentionalNode(
        "matrix:expression:multiply",
        identity("OperatorApplication"),
        (PropertyValue(identity("OperatorApplication", "operator"), "multiply"),),
        (RoleBinding(identity("OperatorApplication", "operands"), (right_a, right_b)),),
    )
    summation = IntentionalNode(
        "matrix:expression:sum",
        identity("OperatorApplication"),
        (PropertyValue(identity("OperatorApplication", "operator"), "sum"),),
        (RoleBinding(identity("OperatorApplication", "operands"), (multiply.id,)),),
        (RoleBinding(identity("OperatorApplication", "bound_symbols"), ("matrix:k",)),),
    )
    nodes.extend((multiply, summation))
    root(
        IntentionalNode(
            "matrix:equation",
            identity("Equation"),
            (PropertyValue(identity("Equation", "name"), "Matrix product by contraction"),),
            (
                RoleBinding(identity("Equation", "left"), (left,)),
                RoleBinding(identity("Equation", "right"), (summation.id,)),
            ),
        )
    )
    model = DomainModel(
        "matrix:model",
        SCHEMA_ID,
        "1",
        tuple(roots),
        tuple(nodes),
        "C[i,j] = sum(k, A[i,k] * B[k,j])",
    )
    return Project(
        "foundation:matrix-product",
        "Indexed matrix product",
        (),
        domain_workspace=DomainWorkspace((math_schema(),), (model,), (BUNDLE,)),
    )
