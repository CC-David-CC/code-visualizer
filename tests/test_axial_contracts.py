"""Precise domain/geometry admission, including unsupported real native solids."""

from dataclasses import replace

import pytest
from test_axial_computation import installed
from test_axial_computation import solid as solid
from test_electrothermal_contracts import changed

from code_visualizer.application.axial_examples import MODEL_ID
from code_visualizer.domain.intentional import BundleReference
from code_visualizer.domain.values import ResourceReference
from code_visualizer.extensions.axial.domain import quantity
from code_visualizer.extensions.axial.geometry import certify_prism, derive_mapping
from code_visualizer.extensions.axial.problem import AxialError, derive_problem
from code_visualizer.extensions.axial.records import CODEC, MAPPING_TYPE, RESULT_TYPE
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.cad.native import decode_solid
from code_visualizer.extensions.cad.resources import CadError
from code_visualizer.extensions.publication import publication_manifest
from code_visualizer.persistence.computation_resources import resolve_computation_resource


@pytest.mark.parametrize(
    "node,field,value,code",
    (
        ("axial:material", "young_modulus", quantity(0, "pascal"), "AXIAL_MATERIAL"),
        ("axial:material", "young_modulus", quantity(1, "newton"), "AXIAL_UNIT"),
        ("axial:load", "axis", "y", "AXIAL_LOAD_DIRECTION"),
        ("axial:load", "frame_id", "different-frame", "AXIAL_LOAD_DIRECTION"),
        ("axial:support", "displacement", quantity(1), "AXIAL_SUPPORT"),
        ("axial:geometry", "method_id", "org.other.idealization", "AXIAL_IDEALIZATION"),
        ("axial:geometry", "method_version", "2", "AXIAL_IDEALIZATION"),
        ("axial:support-region", "side", "max", "AXIAL_REGION"),
        ("axial:load-region", "expected_count", 2, "AXIAL_REGION"),
        ("axial:load-region", "frame_id", "different-frame", "AXIAL_REGION"),
        (
            "axial:load-region",
            "geometry",
            ResourceReference("other-brep", "a" * 64),
            "AXIAL_STALE_REGION",
        ),
        ("axial:problem", "nodes", 66, "AXIAL_DISCRETIZATION"),
    ),
)
def test_authored_mismatches_fail_at_the_source_relationship(solid, node, field, value, code):
    project, _, resource = solid
    current = changed(installed(project, resource), node, field, value)
    with pytest.raises(AxialError) as error:
        derive_problem(current, current.domain_workspace.model(MODEL_ID))
    assert (error.value.code, error.value.object_id) == (code, node)


@pytest.mark.parametrize("kind", ("hole", "taper", "disconnected", "rotated"))
def test_real_native_geometry_cannot_be_certified_from_bounding_dimensions(solid, kind):
    from build123d import Align, Box, Cone, Cylinder, Pos, Rot

    project, store, resource = solid
    current = installed(project, resource)
    problem = derive_problem(current, current.domain_workspace.model(MODEL_ID))
    header, _ = decode_solid(store.read(resource))
    box = Box(100, 10, 10, align=(Align.MIN, Align.MIN, Align.MIN))
    shape = {
        "hole": lambda: (
            box - Pos(50, 5, 0) * Cylinder(2, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
        ),
        "taper": lambda: Cone(10, 5, 100),
        "disconnected": lambda: box + Pos(120, 0, 0) * box,
        "rotated": lambda: Rot(0, 0, 25) * box,
    }[kind]()
    with pytest.raises(AxialError) as error:
        certify_prism(header, shape, problem)
    assert error.value.code == "AXIAL_GEOMETRY_UNSUPPORTED"
    assert error.value.object_id == "axial:geometry"


def test_native_dependency_is_explicit_and_no_frame_inference_occurs(solid, monkeypatch):
    from code_visualizer.extensions.cad import native

    project, store, resource = solid
    current = installed(project, resource)
    problem = derive_problem(current, current.domain_workspace.model(MODEL_ID))
    header, shape = decode_solid(store.read(resource))
    with pytest.raises(AxialError) as error:
        certify_prism(header, shape, replace(problem, frame_id="same-numbers-different-frame"))
    assert error.value.code == "AXIAL_FRAME" and error.value.object_id == problem.geometry_id

    def missing():
        raise CadError("CAD_DEPENDENCY_MISSING", "Pinned CAD implementation unavailable")

    monkeypatch.setattr(native, "implementation_version", missing)
    with pytest.raises(AxialError) as error:
        derive_mapping(resolve_computation_resource(store, resource), problem, "b" * 64)
    assert (
        error.value.code == "CAD_DEPENDENCY_MISSING"
        and error.value.object_id == problem.geometry_id
    )


def test_mapping_contract_is_closed_and_publication_resolves_exact_dependencies(solid):
    project, store, resource = solid
    current = installed(project, resource)
    problem = derive_problem(current, current.domain_workspace.model(MODEL_ID))
    mapping = derive_mapping(resolve_computation_resource(store, resource), problem, "b" * 64)
    payload = CODEC.encode(mapping)
    assert CODEC.decode(payload, type(mapping)) == mapping
    with pytest.raises(ValueError):
        CODEC.decode(payload + b"\n", type(mapping))
    registry = builtin_registry()
    registry.validate_publication_closure(BundleReference("org.codevisualizer.axial", "1"))
    assert publication_manifest(registry, "org.codevisualizer.axial", "1").references
    for kind in (MAPPING_TYPE, RESULT_TYPE):
        assert registry.resource_interpretation(kind) is not None
