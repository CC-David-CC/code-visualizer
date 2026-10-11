"""Closed, self-contained CAD resource envelopes, independent of native objects.

The envelope owns all bytes needed to interpret geometry. Parent resource
references identify provenance, not a decoder's hidden data dependencies.
"""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass
from typing import BinaryIO

from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.values import QuantityValue, ResourceReference, UnitReference
from code_visualizer.extensions.foundations.units_si import si_catalog
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.values import (
    array_data,
    canonical_value_from_data,
    canonical_value_to_data,
    integer_data,
    object_data,
    text_data,
    unit_from_data,
    unit_to_data,
)

BREP = ResourceLogicalTypeReference("code_visualizer.cad.brep", "1")
MESH = ResourceLogicalTypeReference("code_visualizer.cad.triangle_mesh", "1")
MEASUREMENT = ResourceLogicalTypeReference("code_visualizer.cad.measurement", "1")
REGION = ResourceLogicalTypeReference("code_visualizer.cad.region_resolution", "1")
MEDIA_TYPE = "application/vnd.codevisualizer.cad"
MAGIC = b"CVCAD\x00\x01\x00"
MAX_HEADER_BYTES = 64 * 1024
MAX_PAYLOAD_BYTES = 512 * 1024 * 1024
MAX_VERTICES = 2_000_000
MAX_TRIANGLES = 4_000_000


class CadError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def real(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise CadError("CAD_VALUE", "Expected a finite real measurement")
    return float(value)


def positive(value: object) -> float:
    result = real(value)
    if result <= 0:
        raise CadError("CAD_VALUE", "Expected a finite positive measurement")
    return result


def identity(value: str) -> None:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 1024:
        raise CadError("CAD_IDENTITY", "Expected a bounded nonempty identity")


@dataclass(frozen=True, slots=True)
class FrameSnapshot:
    space_id: str
    frame_id: str
    unit: UnitReference
    axes: tuple[str, ...] = ("x", "y", "z")
    convention: str = "cartesian-right-handed"

    def __post_init__(self) -> None:
        identity(self.space_id)
        identity(self.frame_id)
        if self.axes != ("x", "y", "z") or self.convention != "cartesian-right-handed":
            raise CadError("CAD_FRAME_UNSUPPORTED", "P4 requires Cartesian right-handed x/y/z")
        catalog = si_catalog()
        catalog.validate_reference(self.unit)
        if self.unit.dimension != catalog.unit("foundation.units.si:meter").dimension:
            raise CadError("CAD_UNIT_DIMENSION", "CAD coordinates require a length unit")
        catalog.convert(QuantityValue(1.0, self.unit), catalog.unit("foundation.units.si:meter"))


@dataclass(frozen=True, slots=True)
class CadOrigins:
    project_id: str
    revision: int
    input_digest: str
    semantic_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        identity(self.project_id)
        ResourceReference("input", self.input_digest)
        if type(self.revision) is not int or self.revision < 0:
            raise CadError("CAD_ORIGINS", "Expected a nonnegative source revision")
        if (
            type(self.semantic_ids) is not tuple
            or not 1 <= len(self.semantic_ids) <= 256
            or len(set(self.semantic_ids)) != len(self.semantic_ids)
        ):
            raise CadError("CAD_ORIGINS", "Expected 1..256 unique source identities")
        for item in self.semantic_ids:
            identity(item)


@dataclass(frozen=True, slots=True)
class CadHeader:
    logical_type: ResourceLogicalTypeReference
    frame: FrameSnapshot
    origins: CadOrigins
    serializer: str
    serializer_version: str
    tolerance: float
    parameters: tuple[tuple[str, QuantityValue], ...] = ()
    parent: ResourceReference | None = None
    angular_tolerance: float | None = None
    vertex_count: int = 0
    triangle_count: int = 0

    def __post_init__(self) -> None:
        if self.logical_type not in (BREP, MESH, MEASUREMENT, REGION):
            raise CadError("CAD_TYPE_UNSUPPORTED", "Unknown CAD logical type/version")
        if not isinstance(self.frame, FrameSnapshot) or not isinstance(self.origins, CadOrigins):
            raise CadError("CAD_METADATA", "Typed frame and source origins are required")
        identity(self.serializer)
        identity(self.serializer_version)
        positive(self.tolerance)
        if (
            type(self.parameters) is not tuple
            or len(self.parameters) > 128
            or len({name for name, _ in self.parameters}) != len(self.parameters)
        ):
            raise CadError("CAD_PARAMETERS", "Parameters require bounded unique names")
        for name, value in self.parameters:
            identity(name)
            if not isinstance(value, QuantityValue) or type(value.magnitude) not in (int, float):
                raise CadError("CAD_PARAMETERS", "Parameters require real quantities")
            si_catalog().validate_reference(value.unit)
        if self.parent is not None and not isinstance(self.parent, ResourceReference):
            raise CadError("CAD_PARENT", "A parent requires an exact resource reference")
        if self.logical_type == MESH:
            if self.parent is None or self.angular_tolerance is None:
                raise CadError("CAD_MESH", "A mesh requires its exact BREP parent and tolerances")
            positive(self.angular_tolerance)
            if (
                type(self.vertex_count) is not int
                or not 3 <= self.vertex_count <= MAX_VERTICES
                or type(self.triangle_count) is not int
                or not 1 <= self.triangle_count <= MAX_TRIANGLES
            ):
                raise CadError("CAD_MESH_BOUND", "Mesh counts exceed the format bounds")
        elif (
            self.vertex_count != 0 or self.triangle_count != 0 or self.angular_tolerance is not None
        ):
            raise CadError("CAD_METADATA", "Triangle layout belongs only to a mesh")


def header_to_data(value: CadHeader) -> dict[str, JsonValue]:
    return {
        "version": 1,
        "type": {"id": value.logical_type.id, "version": value.logical_type.version},
        "frame": {
            "space_id": value.frame.space_id,
            "frame_id": value.frame.frame_id,
            "unit": unit_to_data(value.frame.unit),
            "axes": list(value.frame.axes),
            "convention": value.frame.convention,
        },
        "origins": {
            "project_id": value.origins.project_id,
            "revision": value.origins.revision,
            "input_digest": value.origins.input_digest,
            "semantic_ids": list(value.origins.semantic_ids),
        },
        "serializer": value.serializer,
        "serializer_version": value.serializer_version,
        "tolerance": value.tolerance,
        "parameters": [
            {"name": name, "value": canonical_value_to_data(quantity)}
            for name, quantity in value.parameters
        ],
        "parent": canonical_value_to_data(value.parent) if value.parent else None,
        "angular_tolerance": value.angular_tolerance,
        "vertex_count": value.vertex_count,
        "triangle_count": value.triangle_count,
    }


def header_from_data(raw: object) -> CadHeader:
    data = object_data(
        raw,
        {
            "version",
            "type",
            "frame",
            "origins",
            "serializer",
            "serializer_version",
            "tolerance",
            "parameters",
            "parent",
            "angular_tolerance",
            "vertex_count",
            "triangle_count",
        },
    )
    if type(data.get("version")) is not int or data["version"] != 1:
        raise CadError("CAD_VERSION", "Unsupported CAD envelope version")
    kind = object_data(data.get("type"), {"id", "version"})
    frame = object_data(data.get("frame"), {"space_id", "frame_id", "unit", "axes", "convention"})
    origin = object_data(
        data.get("origins"), {"project_id", "revision", "input_digest", "semantic_ids"}
    )
    parameters = []
    for item in array_data(data.get("parameters")):
        pair = object_data(item, {"name", "value"})
        value = canonical_value_from_data(pair.get("value"))
        if not isinstance(value, QuantityValue):
            raise CadError("CAD_PARAMETERS", "Expected a parameter quantity")
        parameters.append((text_data(pair.get("name")), value))
    parent = canonical_value_from_data(data["parent"]) if data.get("parent") is not None else None
    if parent is not None and not isinstance(parent, ResourceReference):
        raise CadError("CAD_PARENT", "Expected an exact parent resource")
    result = CadHeader(
        ResourceLogicalTypeReference(text_data(kind.get("id")), text_data(kind.get("version"))),
        FrameSnapshot(
            text_data(frame.get("space_id")),
            text_data(frame.get("frame_id")),
            unit_from_data(frame.get("unit")),
            tuple(text_data(v) for v in array_data(frame.get("axes"))),
            text_data(frame.get("convention")),
        ),
        CadOrigins(
            text_data(origin.get("project_id")),
            integer_data(origin.get("revision")),
            text_data(origin.get("input_digest")),
            tuple(text_data(v) for v in array_data(origin.get("semantic_ids"))),
        ),
        text_data(data.get("serializer")),
        text_data(data.get("serializer_version")),
        positive(data.get("tolerance")),
        tuple(parameters),
        parent,
        positive(data["angular_tolerance"]) if data.get("angular_tolerance") is not None else None,
        integer_data(data.get("vertex_count")),
        integer_data(data.get("triangle_count")),
    )
    if header_to_data(result) != data:
        raise CadError("CAD_METADATA", "Incomplete or noncanonical CAD metadata")
    return result


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    if len({key for key, _ in pairs}) != len(pairs):
        raise CadError("CAD_METADATA", "Duplicate JSON member")
    return dict(pairs)


def write_envelope(stream: BinaryIO, header: CadHeader, payload: bytes) -> None:
    metadata = canonical_data_bytes(header_to_data(header))
    if not 0 < len(metadata) <= MAX_HEADER_BYTES or not 0 < len(payload) <= MAX_PAYLOAD_BYTES:
        raise CadError("CAD_SIZE", "CAD header/payload exceeds the format bounds")
    stream.write(MAGIC + struct.pack("!IQ", len(metadata), len(payload)))
    stream.write(metadata)
    stream.write(payload)


def read_envelope_header(
    stream: BinaryIO, expected: ResourceLogicalTypeReference
) -> tuple[CadHeader, int]:
    """Read bounded interpretation metadata; the caller must verify payload length."""
    if stream.read(len(MAGIC)) != MAGIC:
        raise CadError("CAD_FORMAT", "Expected a versioned CAD envelope")
    sizes = stream.read(12)
    if len(sizes) != 12:
        raise CadError("CAD_TRUNCATED", "Missing envelope lengths")
    metadata_size, payload_size = struct.unpack("!IQ", sizes)
    if not 0 < metadata_size <= MAX_HEADER_BYTES or not 0 < payload_size <= MAX_PAYLOAD_BYTES:
        raise CadError("CAD_SIZE", "CAD header/payload exceeds the format bounds")
    metadata = stream.read(metadata_size)
    if len(metadata) != metadata_size:
        raise CadError("CAD_TRUNCATED", "Truncated metadata")
    try:
        header = header_from_data(json.loads(metadata, object_pairs_hook=_unique_object))
    except (ValueError, TypeError, KeyError) as exc:
        raise CadError("CAD_METADATA", str(exc)) from exc
    if header.logical_type != expected:
        raise CadError("CAD_TYPE_MISMATCH", "Resource declaration differs from its envelope")
    return header, payload_size


def read_envelope(
    stream: BinaryIO, expected: ResourceLogicalTypeReference
) -> tuple[CadHeader, bytes]:
    header, payload_size = read_envelope_header(stream, expected)
    payload = stream.read(payload_size)
    if len(payload) != payload_size or stream.read(1):
        raise CadError("CAD_SIZE", "Truncated payload or trailing bytes")
    return header, payload


@dataclass(frozen=True, slots=True)
class TriangleMesh:
    header: CadHeader
    vertices: tuple[tuple[float, float, float], ...]
    triangles: tuple[tuple[int, int, int], ...]
    face_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        if self.header.logical_type != MESH or (
            len(self.vertices),
            len(self.triangles),
            len(self.face_ids),
        ) != (self.header.vertex_count, self.header.triangle_count, self.header.triangle_count):
            raise CadError("CAD_MESH_LAYOUT", "Mesh counts do not match its declared layout")
        if any(
            len(v) != 3 or any(type(x) is not float or not math.isfinite(x) for x in v)
            for v in self.vertices
        ):
            raise CadError("CAD_MESH_VERTEX", "Vertices require three finite coordinates")
        if any(
            len(t) != 3
            or len(set(t)) != 3
            or any(type(i) is not int or not 0 <= i < len(self.vertices) for i in t)
            for t in self.triangles
        ):
            raise CadError("CAD_MESH_INDEX", "Invalid indexed triangle")
        if any(type(i) is not int or not 0 <= i < 1 << 32 for i in self.face_ids):
            raise CadError("CAD_MESH_FACE", "Face groups require revision-local unsigned IDs")

    def payload(self) -> bytes:
        return b"".join(struct.pack("!3d", *v) for v in self.vertices) + b"".join(
            struct.pack("!4I", *t, face)
            for t, face in zip(self.triangles, self.face_ids, strict=True)
        )

    @classmethod
    def decode(cls, header: CadHeader, payload: bytes) -> TriangleMesh:
        split = header.vertex_count * 24
        if len(payload) != split + header.triangle_count * 16:
            raise CadError("CAD_MESH_LAYOUT", "Mesh payload does not match its bounded layout")
        vertices = tuple(struct.iter_unpack("!3d", payload[:split]))
        faces = tuple(struct.iter_unpack("!4I", payload[split:]))
        return cls(header, vertices, tuple(t[:3] for t in faces), tuple(t[3] for t in faces))
