import json
import math
import struct
from dataclasses import replace
from io import BytesIO

import pytest

from code_visualizer.domain.values import QuantityValue, ResourceReference
from code_visualizer.extensions.cad.resources import (
    BREP,
    MAGIC,
    MAX_HEADER_BYTES,
    MESH,
    CadError,
    CadHeader,
    CadOrigins,
    FrameSnapshot,
    TriangleMesh,
    header_to_data,
    read_envelope,
    write_envelope,
)
from code_visualizer.extensions.foundations.units_si import si_catalog


def header():
    return CadHeader(
        BREP,
        FrameSnapshot(
            "space:lab", "frame:lab", si_catalog().unit("foundation.units.si:millimeter")
        ),
        CadOrigins("project", 7, "a" * 64, ("operation:box", "parameter:length")),
        "org.opencascade.brep",
        "test",
        1e-7,
        (("length", QuantityValue(0.05, si_catalog().unit("foundation.units.si:meter"))),),
    )


def test_envelope_preserves_units_frame_origins_and_parameters():
    value = header()
    stream = BytesIO()
    write_envelope(stream, value, b"self-contained solid")
    assert read_envelope(BytesIO(stream.getvalue()), BREP) == (value, b"self-contained solid")
    with pytest.raises(CadError, match="TYPE_MISMATCH"):
        read_envelope(BytesIO(stream.getvalue()), MESH)


@pytest.mark.parametrize(
    "mutation",
    ["unknown", "version", "duplicate", "unit", "frame", "truncated", "trailing", "oversize"],
)
def test_invalid_envelopes_fail_before_native_decode(mutation):
    value = header_to_data(header())
    if mutation == "unknown":
        value["executable"] = "no"
    if mutation == "version":
        value["version"] = 2
    if mutation == "unit":
        value["frame"]["unit"]["id"] = "foundation.units.si:second"
    if mutation == "frame":
        value["frame"]["convention"] = "left-handed"
    raw = json.dumps(value).encode()
    if mutation == "duplicate":
        raw = raw.replace(b'"version": 1', b'"version": 1, "version": 1', 1)
    payload = MAGIC + struct.pack("!IQ", len(raw), 5) + raw + b"solid"
    if mutation == "truncated":
        payload = payload[:-1]
    if mutation == "trailing":
        payload += b"extra"
    if mutation == "oversize":
        payload = MAGIC + struct.pack("!IQ", MAX_HEADER_BYTES + 1, 5)
    with pytest.raises(CadError):
        read_envelope(BytesIO(payload), BREP)


def test_mesh_layout_has_exact_parent_and_revision_local_face_groups():
    meta = replace(
        header(),
        logical_type=MESH,
        parent=ResourceReference("brep", "b" * 64),
        angular_tolerance=0.1,
        vertex_count=3,
        triangle_count=1,
    )
    mesh = TriangleMesh(
        meta, ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), ((0, 1, 2),), (42,)
    )
    assert TriangleMesh.decode(meta, mesh.payload()) == mesh
    with pytest.raises(CadError, match="CAD_MESH_INDEX"):
        replace(mesh, triangles=((0, 1, 3),))
    with pytest.raises(CadError, match="CAD_MESH_VERTEX"):
        replace(mesh, vertices=((math.nan, 0.0, 0.0), *mesh.vertices[1:]))
    with pytest.raises(CadError, match="CAD_MESH_LAYOUT"):
        TriangleMesh.decode(meta, mesh.payload()[:-1])


def test_native_solid_roundtrip_and_separate_mesh():
    import hashlib

    from build123d import Align, Box, Cylinder, Pos

    from code_visualizer.extensions.cad.native import (
        decode_mesh,
        decode_solid,
        encode_mesh,
        encode_solid,
        tessellate,
    )

    shape = Box(50, 20, 10, align=(Align.MIN, Align.MIN, Align.MIN)) - Pos(25, 10, 0) * Cylinder(
        2, 10, align=(Align.CENTER, Align.CENTER, Align.MIN)
    )
    data = encode_solid(shape, header())
    meta, restored = decode_solid(data)
    assert restored.volume * 1e-9 == pytest.approx(
        0.05 * 0.02 * 0.01 - math.pi * 0.002**2 * 0.01, abs=1e-12
    )
    assert tuple(restored.bounding_box().size) == pytest.approx((50, 20, 10))
    parent = ResourceReference("brep", hashlib.sha256(data).hexdigest())
    mesh = tessellate(data, parent)
    assert mesh.header.parent == parent and mesh.header.origins == meta.origins
    assert len(mesh.triangles) > 100 and len(set(mesh.face_ids)) == len(restored.faces())
    assert decode_mesh(encode_mesh(mesh)) == mesh
