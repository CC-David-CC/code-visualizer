"""Coordinate spaces and geometry expressed by ordinary schemas and references."""

from __future__ import annotations

from typing import TYPE_CHECKING

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
    NotationEdgeRule,
    NotationField,
    NotationKind,
    NotationNodeRule,
)
from code_visualizer.domain.project import Project
from code_visualizer.domain.values import TensorValue
from code_visualizer.extensions.foundations.math import identity as math_id

if TYPE_CHECKING:
    from code_visualizer.extensions.registry import DomainExtensionBundle

PREFIX = "foundation.space:"
SCHEMA_ID = PREFIX + "schema"
ALGEBRA_SCHEMA_ID = PREFIX + "algebra_schema"
BUNDLE = BundleReference("foundation.space", "1")


def identity(concept: str, field: str | None = None) -> str:
    return PREFIX + concept + (":" + field if field else "")


def space_schema() -> DomainSchema:
    def name(concept: str) -> PropertyDefinition:
        return PropertyDefinition(identity(concept, "name"), "Name", required=True)

    def ref(
        concept: str,
        role: str,
        targets: tuple[str, ...],
        minimum: int = 1,
        maximum: int | None = 1,
    ) -> RoleDefinition:
        return RoleDefinition(identity(concept, role), role.title(), targets, minimum, maximum)

    tensor_targets = (math_id("TensorSymbol"), math_id("TensorLiteral"))
    return DomainSchema(
        SCHEMA_ID,
        BUNDLE.id,
        BUNDLE.version,
        (
            ConceptDefinition(
                identity("Space"),
                "Space",
                (
                    name("Space"),
                    PropertyDefinition(
                        identity("Space", "dimension"),
                        "Dimension",
                        ValueKind.INTEGER,
                        required=True,
                        minimum=1,
                        maximum=16,
                    ),
                ),
                (RoleDefinition(identity("Space", "axes"), "Axes", (identity("Axis"),)),),
                display_property_id=identity("Space", "name"),
            ),
            ConceptDefinition(
                identity("Axis"),
                "Axis",
                (
                    name("Axis"),
                    PropertyDefinition(
                        identity("Axis", "ordinal"),
                        "Ordinal",
                        ValueKind.INTEGER,
                        required=True,
                        minimum=0,
                    ),
                ),
                display_property_id=identity("Axis", "name"),
            ),
            ConceptDefinition(
                identity("Frame"),
                "Frame",
                (name("Frame"),),
                reference_roles=(ref("Frame", "space", (identity("Space"),)),),
                display_property_id=identity("Frame", "name"),
            ),
            ConceptDefinition(
                identity("Transform"),
                "Affine transform",
                (name("Transform"),),
                reference_roles=(
                    ref("Transform", "source", (identity("Frame"),)),
                    ref("Transform", "target", (identity("Frame"),)),
                    ref("Transform", "matrix", tensor_targets),
                ),
                display_property_id=identity("Transform", "name"),
                description="One homogeneous matrix maps source coordinates to target coordinates.",
            ),
            ConceptDefinition(
                identity("Point"),
                "Point",
                (name("Point"),),
                reference_roles=(
                    ref("Point", "frame", (identity("Frame"),)),
                    ref("Point", "coordinates", tensor_targets),
                ),
                display_property_id=identity("Point", "name"),
            ),
            ConceptDefinition(
                identity("Region"),
                "Region",
                (
                    name("Region"),
                    PropertyDefinition(
                        identity("Region", "kind"),
                        "Kind",
                        required=True,
                        default="point_set",
                        choices=("point_set", "polyline", "polygon"),
                    ),
                ),
                reference_roles=(
                    ref("Region", "frame", (identity("Frame"),)),
                    ref("Region", "points", (identity("Point"),), 0, None),
                ),
                display_property_id=identity("Region", "name"),
            ),
        ),
        BUNDLE,
        "Frames, affine maps and geometry; spatial meaning is validated by this bundle.",
    )


def validate_space(project: Project, model: DomainModel) -> tuple[DomainIssue, ...]:
    from code_visualizer.extensions.foundations.math import tensor_shape

    nodes = {
        node.id: node for candidate in project.domain_workspace.models for node in candidate.nodes
    }
    issues: list[DomainIssue] = []

    def target(node: IntentionalNode, role: str) -> IntentionalNode | None:
        ids = node.reference_ids(role)
        return nodes.get(ids[0]) if len(ids) == 1 else None

    def dimension(frame: IntentionalNode | None) -> int | None:
        space = target(frame, identity("Frame", "space")) if frame else None
        value = space.property(identity("Space", "dimension")) if space else None
        return value if type(value) is int else None

    def tensor(node: IntentionalNode | None) -> TensorValue | None:
        if node and node.concept_id == math_id("TensorSymbol"):
            node = target(node, math_id("TensorSymbol", "binding"))
        value = node.property(math_id("TensorLiteral", "value")) if node else None
        return value if isinstance(value, TensorValue) else None

    def shape(node: IntentionalNode | None) -> tuple[int, ...] | None:
        value = tensor(node)
        return value.shape if value else tensor_shape(node) if node else None

    def issue(code: str, message: str, node: IntentionalNode) -> None:
        issues.append(DomainIssue(code, message, node.id, incomplete=True))

    for node in model.nodes:
        if node.concept_id == identity("Space"):
            axes = [
                nodes[item] for item in node.child_ids(identity("Space", "axes")) if item in nodes
            ]
            count = node.property(identity("Space", "dimension"))
            ordinals = [axis.property(identity("Axis", "ordinal")) for axis in axes]
            if axes and (
                type(count) is not int or sorted(ordinals, key=str) != sorted(range(count), key=str)
            ):
                issue(
                    "SPACE_AXIS_DIMENSION",
                    "Declared axes must cover each space dimension exactly once",
                    node,
                )
        elif node.concept_id == identity("Point"):
            frame = target(node, identity("Point", "frame"))
            coordinates = target(node, identity("Point", "coordinates"))
            rank = dimension(frame)
            actual = shape(coordinates)
            if rank is not None and actual is not None and actual != (rank,):
                issue(
                    "SPACE_POINT_DIMENSION",
                    "Point coordinates must match the frame's space dimension",
                    node,
                )
        elif node.concept_id == identity("Transform"):
            source = dimension(target(node, identity("Transform", "source")))
            destination = dimension(target(node, identity("Transform", "target")))
            matrix = target(node, identity("Transform", "matrix"))
            actual = shape(matrix)
            if source is not None and destination is not None and actual is not None:
                if actual != (destination + 1, source + 1):
                    issue(
                        "SPACE_TRANSFORM_DIMENSION",
                        "Homogeneous matrix shape must match both frames",
                        node,
                    )
                else:
                    value = tensor(matrix)
                    if value is not None:
                        last = value.elements[-(source + 1) :]
                        if last != (*([0] * source), 1):
                            issue(
                                "SPACE_TRANSFORM_AFFINE",
                                "An affine matrix ends in a row of zeros and one",
                                node,
                            )
        elif node.concept_id == identity("Region"):
            frames = node.reference_ids(identity("Region", "frame"))
            points = [
                nodes[item]
                for item in node.reference_ids(identity("Region", "points"))
                if item in nodes
            ]
            if any(point.reference_ids(identity("Point", "frame")) != frames for point in points):
                issue(
                    "SPACE_REGION_FRAME", "Region points must use the region's declared frame", node
                )
            kind = node.property(identity("Region", "kind"))
            minimum = {"polyline": 2, "polygon": 3}.get(kind, 0) if isinstance(kind, str) else 0
            if len(points) < minimum:
                issue(
                    "SPACE_REGION_CARDINALITY",
                    f"This region requires at least {minimum} points",
                    node,
                )
    return tuple(issues)


def space_notations() -> tuple[NotationDefinition, ...]:
    return (
        NotationDefinition(
            PREFIX + "notation:frames",
            "Frames and transforms",
            NotationKind.GRAPH,
            schema_id=SCHEMA_ID,
            node_rules=(NotationNodeRule(identity("Frame"), identity("Frame", "name")),),
            edge_rules=(
                NotationEdgeRule(
                    identity("Transform"),
                    identity("Transform", "source"),
                    identity("Transform", "target"),
                    (NotationField(identity("Transform", "name")),),
                ),
            ),
        ),
        NotationDefinition(
            PREFIX + "notation:points",
            "Points",
            NotationKind.TABLE,
            schema_id=SCHEMA_ID,
            concept_ids=(identity("Point"),),
            columns=(
                NotationColumn("name", "Point", NotationField(identity("Point", "name"))),
                NotationColumn(
                    "frame",
                    "Frame",
                    NotationField(reference_role_ids=(identity("Point", "frame"),)),
                ),
                NotationColumn(
                    "coordinates",
                    "Coordinates",
                    NotationField(reference_role_ids=(identity("Point", "coordinates"),)),
                ),
            ),
        ),
        NotationDefinition(
            PREFIX + "notation:hierarchy",
            "Space hierarchy and form",
            NotationKind.TREE_FORM,
            schema_id=SCHEMA_ID,
        ),
    )


def space_bundle() -> DomainExtensionBundle:
    from code_visualizer.extensions.publication import FIRST_PARTY_PUBLICATION
    from code_visualizer.extensions.registry import DomainExtensionBundle

    return DomainExtensionBundle(
        BUNDLE.id,
        BUNDLE.version,
        schemas=(space_schema(),),
        publication=FIRST_PARTY_PUBLICATION,
        required_bundles=(BundleReference("foundation.math", "1"),),
        validators=(validate_space,),
        notations=space_notations(),
    )


def space_v2_bundle() -> DomainExtensionBundle:
    """Explicit math@2 composition; existing space@1 data and contracts stay exact."""
    from dataclasses import replace

    bundle = space_bundle()
    return replace(
        bundle,
        version="2",
        schemas=(
            replace(
                space_schema(),
                id=ALGEBRA_SCHEMA_ID,
                version="2",
                bundle=BundleReference(BUNDLE.id, "2"),
            ),
        ),
        required_bundles=(BundleReference("foundation.math", "2"),),
        notations=tuple(
            replace(item, id=item.id + ":v2", schema_id=ALGEBRA_SCHEMA_ID)
            for item in bundle.notations
        ),
    )
