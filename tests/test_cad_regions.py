"""Rules re-evaluate geometry; direct picks never silently cross resource revisions."""

from dataclasses import replace

import pytest
from test_cad_resources import header

from code_visualizer.domain.values import ResourceReference
from code_visualizer.extensions.cad.domain import consumer_model, quantity
from code_visualizer.extensions.cad.regions import FaceSelection, resolve_region
from code_visualizer.extensions.cad.resources import CadError


@pytest.mark.parametrize("length", [50, 60])
@pytest.mark.parametrize("side,assignment", [("min", "support"), ("max", "load")])
def test_authored_boundary_rule_remaps_by_geometry(length, side, assignment):
    from build123d import Align, Box

    shape = Box(length, 20, 10, align=(Align.MIN, Align.MIN, Align.MIN))
    resource = ResourceReference("geometry:" + str(length), str(length // 10) * 64)
    rule = consumer_model(
        "rule",
        "boundary",
        "RegionSelection",
        resource,
        frame_id="frame:lab",
        side=side,
        assignment=assignment,
    ).nodes[0]
    result = resolve_region(rule, resource, header(), shape)
    assert result["assignment"] == assignment
    assert len(result["face_ids"]) == 1
    selected = FaceSelection(resource, result["face_ids"][0])
    face = shape.faces()[selected.resolve(resource, len(shape.faces()))]
    assert pytest.approx(0 if side == "min" else length) == face.bounding_box().min.X
    with pytest.raises(CadError, match="CAD_BOUNDARY_UNRESOLVED"):
        selected.resolve(ResourceReference("different", "f" * 64), len(shape.faces()))


@pytest.mark.parametrize("problem", ["ambiguous", "frame", "curved"])
def test_unresolved_boundary_is_not_guessed(problem):
    from build123d import Box, Sphere

    resource = ResourceReference("geometry", "a" * 64)
    options = {"frame_id": "wrong" if problem == "frame" else "frame:lab"}
    if problem == "ambiguous":
        options.update(expected_count=2, tolerance=quantity(1e-7))
    rule = consumer_model("rule", "boundary", "RegionSelection", resource, **options).nodes[0]
    with pytest.raises(CadError):
        resolve_region(
            rule,
            resource,
            replace(header(), parameters=()),
            Sphere(5) if problem == "curved" else Box(50, 20, 10),
        )
