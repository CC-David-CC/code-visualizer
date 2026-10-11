"""Visible surfaces and resource-local picks must agree, including occlusion."""

from dataclasses import replace

import pytest
from test_cad_resources import header

from code_visualizer.domain.values import ResourceReference
from code_visualizer.extensions.cad.presentation import project_mesh
from code_visualizer.extensions.cad.resources import MESH, CadError, TriangleMesh


def crossing_mesh():
    meta = replace(
        header(),
        logical_type=MESH,
        parent=ResourceReference("solid", "b" * 64),
        serializer="code_visualizer.cad.indexed_triangles",
        angular_tolerance=0.1,
        vertex_count=6,
        triangle_count=2,
    )
    return TriangleMesh(
        meta,
        (
            (0.0, 0.0, 3.0),
            (1.0, 0.0, -3.0),
            (0.0, 1.0, -3.0),
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
        ),
        ((0, 1, 2), (3, 4, 5)),
        (2**32 - 1, 17),
    )


def test_pixel_depth_selects_visible_face_independent_of_triangle_order():
    mesh = crossing_mesh()
    reference = ResourceReference("display", "d" * 64)
    image = project_mesh(reference, mesh, "top")
    reverse = project_mesh(
        reference,
        replace(mesh, triangles=mesh.triangles[::-1], face_ids=mesh.face_ids[::-1]),
        "top",
    )
    assert image.faces == reverse.faces and image.rgba == reverse.rgba
    assert image.face_at(80, 80) == 2**32 - 1
    assert image.face_at(600, 80) == 17
    assert image.face_at(0, 0) is None
    assert image.face_at(-1, 80) is None
    assert image.face_at(image.width, 80) is None
    assert image.mesh.header.parent == ResourceReference("solid", "b" * 64)


def test_superseded_preparation_cancels_before_rendering():
    with pytest.raises(CadError, match="CAD_PREVIEW_CANCELLED"):
        project_mesh(
            ResourceReference("display", "d" * 64), crossing_mesh(), cancelled=lambda: True
        )


def test_excessive_overlap_has_a_bounded_preview_diagnostic():
    mesh = crossing_mesh()
    many = replace(
        mesh,
        header=replace(mesh.header, triangle_count=100),
        triangles=mesh.triangles * 50,
        face_ids=mesh.face_ids * 50,
    )
    with pytest.raises(CadError, match="CAD_PREVIEW_SIZE"):
        project_mesh(ResourceReference("display", "d" * 64), many, "top")
