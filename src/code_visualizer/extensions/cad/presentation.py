"""Bounded immutable display/picking buffers; no Qt or native topology dependency."""

import struct
from collections.abc import Callable
from dataclasses import dataclass
from math import ceil, isfinite, sqrt

from code_visualizer.domain.values import ResourceReference
from code_visualizer.extensions.cad.resources import CadError, TriangleMesh

MAX_PREVIEW_TRIANGLES = 10000
MAX_PREVIEW_SIDE = 768
MAX_PREVIEW_FRAGMENTS = 16000000


@dataclass(frozen=True, slots=True)
class MeshPreview:
    resource: ResourceReference
    mesh: TriangleMesh
    width: int
    height: int
    rgba: bytes
    faces: bytes

    def face_at(self, x: int, y: int) -> int | None:
        if not 0 <= x < self.width or not 0 <= y < self.height:
            return None
        face: int = struct.unpack_from("<q", self.faces, 8 * (y * self.width + x))[0]
        return face if face >= 0 else None


def project_mesh(
    resource: ResourceReference,
    mesh: TriangleMesh,
    view: str = "isometric",
    *,
    cancelled: Callable[[], bool] | None = None,
) -> MeshPreview:
    if len(mesh.triangles) > MAX_PREVIEW_TRIANGLES:
        raise CadError("CAD_PREVIEW_SIZE", "Use a coarser display mesh (at most 10,000 triangles)")
    if view not in ("isometric", "front", "top"):
        raise CadError("CAD_PREVIEW_VIEW", "Unknown display orientation")
    try:
        import numpy as np
    except ImportError as exc:
        raise CadError(
            "CAD_DEPENDENCY_MISSING", "Install the pinned 'cad' optional dependencies"
        ) from exc

    coordinates = []
    for x, y, z in mesh.vertices:
        if view == "isometric":
            coordinates.append(((x - y) / sqrt(2), (x + y) / sqrt(6) - z * sqrt(2 / 3), x + y + z))
        elif view == "front":
            coordinates.append((x, -z, -y))
        else:
            coordinates.append((x, y, z))
    points = np.asarray(coordinates, dtype=np.float64)
    low = points[:, :2].min(axis=0)
    span = points[:, :2].max(axis=0) - low
    extent = float(max(span))
    if not isfinite(extent) or extent <= 0 or not np.isfinite(points).all():
        raise CadError("CAD_PREVIEW_EXTENT", "Mesh has no finite display extent")
    scale = (MAX_PREVIEW_SIDE - 17) / extent
    points[:, :2] = (points[:, :2] - low) * scale + 8
    width, height = (min(MAX_PREVIEW_SIDE, ceil(float(v) * scale) + 17) for v in span)
    depth = np.full((height, width), -np.inf)
    faces = np.full((height, width), -1, dtype="<i8")
    rgba = np.full((height, width, 4), 255, dtype=np.uint8)
    fragments = 0
    for indices, face in zip(mesh.triangles, mesh.face_ids, strict=True):
        if cancelled is not None and cancelled():
            raise CadError("CAD_PREVIEW_CANCELLED", "Display preparation was superseded")
        a, b, c = points[list(indices)]
        divisor = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(divisor) < 1e-12:
            continue
        x0, x1 = max(0, int(min(a[0], b[0], c[0]))), min(width - 1, ceil(max(a[0], b[0], c[0])))
        y0, y1 = max(0, int(min(a[1], b[1], c[1]))), min(height - 1, ceil(max(a[1], b[1], c[1])))
        fragments += (x1 - x0 + 1) * (y1 - y0 + 1)
        if fragments > MAX_PREVIEW_FRAGMENTS:
            raise CadError("CAD_PREVIEW_SIZE", "Display overlap exceeds the bounded preview budget")
        yy, xx = np.mgrid[y0 : y1 + 1, x0 : x1 + 1] + 0.5
        w1 = ((b[1] - c[1]) * (xx - c[0]) + (c[0] - b[0]) * (yy - c[1])) / divisor
        w2 = ((c[1] - a[1]) * (xx - c[0]) + (a[0] - c[0]) * (yy - c[1])) / divisor
        w3 = 1 - w1 - w2
        z = w1 * a[2] + w2 * b[2] + w3 * c[2]
        depths, ids = depth[y0 : y1 + 1, x0 : x1 + 1], faces[y0 : y1 + 1, x0 : x1 + 1]
        # Per-pixel depth is necessary: average triangle depth draws hidden faces
        # through holes and cannot select the visible face at an intersection.
        visible = (z > depths) | ((z == depths) & (face < ids))
        mask = (w1 >= -1e-9) & (w2 >= -1e-9) & (w3 >= -1e-9) & visible
        depths[mask], ids[mask] = z[mask], face
        native = np.asarray([mesh.vertices[i] for i in indices])
        normal = np.cross(native[1] - native[0], native[2] - native[0])
        length = float(np.linalg.norm(normal))
        light = (
            abs(float(np.dot(normal / length, (-0.3, -0.4, 0.866))))
            if length and isfinite(length)
            else 0.0
        )
        shade = min(205, 85 + int(120 * light))
        rgba[y0 : y1 + 1, x0 : x1 + 1][mask] = (shade, min(255, shade + 20), 230, 255)
    return MeshPreview(resource, mesh, width, height, rgba.tobytes(), faces.tobytes())
