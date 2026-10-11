"""Explicit geometric predicates; native face enumeration is revision-scoped."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.intentional import IntentionalNode
from code_visualizer.domain.values import CanonicalValue, QuantityValue, ResourceReference
from code_visualizer.extensions.cad.resources import CadError, CadHeader, positive
from code_visualizer.extensions.cad.units import cad_catalog
from code_visualizer.persistence.values import canonical_value_to_data

if TYPE_CHECKING:
    from build123d import Shape


@dataclass(frozen=True, slots=True)
class FaceSelection:
    geometry: ResourceReference
    face_id: int

    def resolve(self, geometry: ResourceReference, face_count: int) -> int:
        if (
            geometry != self.geometry
            or type(self.face_id) is not int
            or not 0 <= self.face_id < face_count
        ):
            raise CadError(
                "CAD_BOUNDARY_UNRESOLVED", "The picked face belongs to another geometry revision"
            )
        return self.face_id


def resolve_region(
    node: IntentionalNode, resource: ResourceReference, header: CadHeader, shape: Shape[Any]
) -> dict[str, JsonValue]:
    from build123d import GeomType

    def prop(name: str) -> CanonicalValue | None:
        return node.property(node.concept_id + ":" + name)

    axis, side, frame_id = prop("axis"), prop("side"), prop("frame_id")
    assignment = prop("assignment")
    if (
        not isinstance(axis, str)
        or not isinstance(side, str)
        or assignment not in ("support", "load")
    ):
        raise CadError("CAD_BOUNDARY_UNRESOLVED", "Unsupported region predicate or assignment")
    assert isinstance(assignment, str)
    if (
        axis not in ("x", "y", "z")
        or side not in ("min", "max")
        or frame_id != header.frame.frame_id
    ):
        raise CadError(
            "CAD_BOUNDARY_UNRESOLVED", "Region axes/frame do not match the geometry interpretation"
        )
    tolerance, count = prop("tolerance"), prop("expected_count")
    if not isinstance(tolerance, QuantityValue) or type(tolerance.magnitude) not in (int, float):
        raise CadError("CAD_BOUNDARY_UNRESOLVED", "A region requires a real length tolerance")
    distance = positive(cad_catalog().convert(tolerance, header.frame.unit).magnitude)
    if type(count) is not int or not 1 <= count <= 256:
        raise CadError("CAD_BOUNDARY_UNRESOLVED", "Expected cardinality must be 1..256")
    index = ("x", "y", "z").index(axis)
    bounds = shape.bounding_box()
    coordinate = tuple(bounds.min if side == "min" else bounds.max)[index]
    sign = -1 if side == "min" else 1
    matches = []
    for face_id, face in enumerate(shape.faces()):
        if face.geom_type != GeomType.PLANE:
            continue
        box = face.bounding_box()
        if (
            max(abs(tuple(box.min)[index] - coordinate), abs(tuple(box.max)[index] - coordinate))
            > distance
        ):
            continue
        normal = tuple(face.normal_at())
        if normal[index] * sign < 1 - 1e-7:
            continue
        matches.append(face_id)
    if len(matches) != count:
        raise CadError(
            "CAD_BOUNDARY_UNRESOLVED",
            f"Region expected {count} planar end faces; found {len(matches)}",
        )
    return {
        "version": 1,
        "rule_id": node.id,
        "geometry": canonical_value_to_data(resource),
        "frame_id": header.frame.frame_id,
        "status": "resolved",
        "face_ids": list(matches),
        "assignment": assignment,
        "axis": axis,
        "side": side,
        "tolerance": canonical_value_to_data(tolerance),
    }
