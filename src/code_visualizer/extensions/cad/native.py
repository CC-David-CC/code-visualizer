"""Trusted optional build123d adapter. Native shapes never cross a process boundary."""

from __future__ import annotations

import io
import math
from dataclasses import replace
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any

from code_visualizer.domain.values import ResourceReference
from code_visualizer.extensions.cad.resources import (
    BREP,
    MESH,
    CadError,
    CadHeader,
    TriangleMesh,
    read_envelope,
    write_envelope,
)

if TYPE_CHECKING:
    from build123d import Shape


def implementation_version() -> str:
    try:
        return f"build123d={version('build123d')};ocp={version('cadquery-ocp-novtk')}"
    except PackageNotFoundError as exc:
        raise CadError(
            "CAD_DEPENDENCY_MISSING", "Install the pinned 'cad' optional dependencies"
        ) from exc


def encode_solid(shape: Shape[Any], header: CadHeader) -> bytes:
    implementation_version()
    from build123d import export_brep

    if header.logical_type != BREP or not _valid_solid(shape):
        raise CadError("CAD_SOLID_INVALID", "Expected valid nonempty finite solid geometry")
    with TemporaryDirectory(prefix="cv-cad-encode-") as directory:
        path = Path(directory) / "solid.brep"
        if not export_brep(shape, path):
            raise CadError("CAD_EXPORT_FAILED", "Open Cascade could not serialize the solid")
        payload = path.read_bytes()
    output = io.BytesIO()
    write_envelope(
        output,
        replace(
            header, serializer="org.opencascade.brep", serializer_version=implementation_version()
        ),
        payload,
    )
    return output.getvalue()


def decode_solid(data: bytes) -> tuple[CadHeader, Shape[Any]]:
    implementation_version()
    from build123d import import_brep

    header, payload = read_envelope(io.BytesIO(data), BREP)
    if (
        header.serializer != "org.opencascade.brep"
        or header.serializer_version != implementation_version()
    ):
        raise CadError("CAD_DECODER_UNSUPPORTED", "This native serializer version is not qualified")
    if not payload.startswith(b"DBRep_DrawableShape"):
        raise CadError("CAD_BREP_INVALID", "Missing Open Cascade BREP signature")
    try:
        with TemporaryDirectory(prefix="cv-cad-decode-") as directory:
            path = Path(directory) / "solid.brep"
            path.write_bytes(payload)
            shape = import_brep(path)
        if not _valid_solid(shape):
            raise CadError("CAD_SOLID_INVALID", "Resource is not a valid solid")
    except Exception as exc:
        if isinstance(exc, CadError):
            raise
        raise CadError("CAD_BREP_INVALID", "Native BREP decoding failed") from exc
    return header, shape


def _valid_solid(shape: Shape[Any]) -> bool:
    if not shape.is_valid or not shape.solids():
        return False
    bounds = shape.bounding_box()
    values = (shape.volume, shape.area, *bounds.min, *bounds.max)
    return all(math.isfinite(float(value)) for value in values) and shape.volume > 0


def tessellate(
    data: bytes, parent: ResourceReference, *, chordal: float = 0.05, angular: float = 0.1
) -> TriangleMesh:
    from code_visualizer.extensions.cad.resources import positive

    positive(chordal)
    positive(angular)
    header, shape = decode_solid(data)
    vertices: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    groups: list[int] = []
    # Face identity is explicitly local to this exact BREP hash. No persistent
    # naming claim is inferred from native enumeration order.
    for face_id, face in enumerate(shape.faces()):
        points, facets = face.tessellate(chordal, angular)
        offset = len(vertices)
        vertices.extend((float(point.X), float(point.Y), float(point.Z)) for point in points)
        triangles.extend((offset + t[0], offset + t[1], offset + t[2]) for t in facets)
        groups.extend(face_id for _ in facets)
    return TriangleMesh(
        replace(
            header,
            logical_type=MESH,
            parent=parent,
            serializer="code_visualizer.cad.indexed_triangles",
            serializer_version=implementation_version(),
            tolerance=chordal,
            angular_tolerance=angular,
            vertex_count=len(vertices),
            triangle_count=len(triangles),
        ),
        tuple(vertices),
        tuple(triangles),
        tuple(groups),
    )


def encode_mesh(mesh: TriangleMesh) -> bytes:
    stream = io.BytesIO()
    write_envelope(stream, mesh.header, mesh.payload())
    return stream.getvalue()


def decode_mesh(data: bytes) -> TriangleMesh:
    header, payload = read_envelope(io.BytesIO(data), MESH)
    if header.serializer != "code_visualizer.cad.indexed_triangles":
        raise CadError("CAD_DECODER_UNSUPPORTED", "Unknown mesh layout")
    return TriangleMesh.decode(header, payload)
