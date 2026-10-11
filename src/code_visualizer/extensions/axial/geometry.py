"""Certify material occupancy/topology before deriving an explicit one-dimensional support."""

from __future__ import annotations

from math import isclose, prod
from typing import TYPE_CHECKING, Any

from code_visualizer.execution.backends import ResolvedResource
from code_visualizer.extensions.axial.domain import quantity
from code_visualizer.extensions.axial.problem import AxialError, AxialProblem
from code_visualizer.extensions.axial.records import AxialMapping
from code_visualizer.extensions.cad.native import decode_solid
from code_visualizer.extensions.cad.regions import resolve_region
from code_visualizer.extensions.cad.resources import BREP, MEDIA_TYPE, CadError, CadHeader, positive
from code_visualizer.extensions.cad.units import cad_catalog

if TYPE_CHECKING:
    from build123d import Shape

RELATIVE_TOLERANCE = 1e-7
ABSOLUTE_TOLERANCE_M = 1e-9
MAX_BREP_BYTES = 64 * 1024 * 1024


def certify_prism(
    header: CadHeader, shape: Shape[Any], problem: AxialProblem
) -> tuple[float, float, float]:
    from build123d import GeomType

    def reject(message: str) -> None:
        raise AxialError("AXIAL_GEOMETRY_UNSUPPORTED", message, problem.geometry_id)

    if header.frame.frame_id != problem.frame_id:
        raise AxialError(
            "AXIAL_FRAME",
            "Geometry frame differs from the authored idealization",
            problem.geometry_id,
        )
    faces, edges, vertices = tuple(shape.faces()), tuple(shape.edges()), tuple(shape.vertices())
    if (
        not shape.is_valid
        or len(shape.solids()) != 1
        or len(faces) != 6
        or len(edges) != 12
        or len(vertices) != 8
    ):
        reject(
            "Require one solid prism: six faces, twelve edges and eight corners; "
            "holes/disconnected shapes are unsupported"
        )
    scale = positive(cad_catalog().convert(quantity(1), header.frame.unit).magnitude)
    # scale is native coordinate units per meter; calculations below are SI.
    bounds = shape.bounding_box()
    low, high = (
        tuple(float(v) / scale for v in bounds.min),
        tuple(float(v) / scale for v in bounds.max),
    )
    spans = tuple(b - a for a, b in zip(low, high, strict=True))
    if min(spans) <= ABSOLUTE_TOLERANCE_M:
        reject("The material section and axial span must be resolvably positive")

    def near(a: float, b: float) -> bool:
        return isclose(
            a, b, rel_tol=0, abs_tol=max(ABSOLUTE_TOLERANCE_M, RELATIVE_TOLERANCE * max(spans))
        )

    corners = set()
    for vertex in vertices:
        coordinate = tuple(float(value) / scale for value in vertex)
        corner = []
        for i, value in enumerate(coordinate):
            if near(value, low[i]):
                corner.append(0)
            elif near(value, high[i]):
                corner.append(1)
            else:
                reject("Prism vertices must be the eight Cartesian rectangular corners")
        corners.add(tuple(corner))
    if len(corners) != 8 or any(edge.geom_type != GeomType.LINE for edge in edges):
        reject("Curved, tapered or duplicate corner geometry is unsupported")
    directions = set()
    for face in faces:
        if face.geom_type != GeomType.PLANE or len(face.wires()) != 1 or len(face.vertices()) != 4:
            reject("Each material boundary must be one filled planar rectangle")
        normal = tuple(float(value) for value in face.normal_at())
        direction = max(range(3), key=lambda i: abs(normal[i]))
        if abs(normal[direction]) < 1 - RELATIVE_TOLERANCE or any(
            abs(normal[i]) > RELATIVE_TOLERANCE for i in range(3) if i != direction
        ):
            reject("The supported solid must align with its declared Cartesian frame")
        sign = 1 if normal[direction] > 0 else -1
        directions.add((direction, sign))
        expected_area = prod(spans[i] for i in range(3) if i != direction)
        if not isclose(
            float(face.area) / scale**2,
            expected_area,
            rel_tol=RELATIVE_TOLERANCE,
            abs_tol=ABSOLUTE_TOLERANCE_M**2,
        ):
            reject("Boundary material area differs from a filled rectangular section")
    if len(directions) != 6 or not isclose(
        float(shape.volume) / scale**3,
        prod(spans),
        rel_tol=RELATIVE_TOLERANCE,
        abs_tol=ABSOLUTE_TOLERANCE_M**3,
    ):
        reject("Topology and occupied volume do not establish a full rectangular solid")
    axis = ("x", "y", "z").index(problem.axis)
    # The area comes from independently verified material faces, not the box alone.
    end = next(face for face in faces if tuple(face.normal_at())[axis] > 1 - RELATIVE_TOLERANCE)
    return low[axis], spans[axis], float(end.area) / scale**2


def derive_mapping(
    resource: ResolvedResource, problem: AxialProblem, source_digest: str
) -> AxialMapping:
    descriptor = resource.descriptor
    if (
        descriptor.reference != problem.geometry
        or descriptor.logical_type != BREP
        or descriptor.media_type != MEDIA_TYPE
        or descriptor.byte_size > MAX_BREP_BYTES
    ):
        raise AxialError(
            "AXIAL_GEOMETRY_RESOURCE",
            "An exact BREP of at most 64 MiB is required",
            problem.geometry_id,
        )
    try:
        with resource.open() as stream:
            header, shape = decode_solid(stream.read(MAX_BREP_BYTES + 1))
        origin, length, area = certify_prism(header, shape, problem)
    except CadError as exc:
        raise AxialError(exc.code, str(exc), problem.geometry_id) from exc
    selections = []
    for node in (problem.support_region, problem.load_region):
        try:
            resolution = resolve_region(node, problem.geometry, header, shape)
        except CadError as exc:
            raise AxialError("AXIAL_REGION", str(exc), node.id) from exc
        face_ids = resolution["face_ids"]
        assert isinstance(face_ids, list) and len(face_ids) == 1 and isinstance(face_ids[0], int)
        selections.append(face_ids[0])
    if abs(problem.force / (area * problem.young_modulus)) > 0.01:
        raise AxialError(
            "AXIAL_STRAIN_RANGE",
            "The small-strain fragment is bounded to 1% axial strain",
            problem.load_id,
        )
    return AxialMapping(
        source_digest,
        problem.geometry,
        header.origins.project_id,
        header.origins.revision,
        header.origins.input_digest,
        header.origins.semantic_ids,
        header.frame.space_id,
        header.frame.frame_id,
        problem.axis,
        quantity(origin),
        quantity(length),
        quantity(area, "square_meter"),
        problem.support_region.id,
        problem.load_region.id,
        selections[0],
        selections[1],
        problem.origins,
    )
