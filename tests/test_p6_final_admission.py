"""Remaining exact admission cases, including the original emitted perforated P4 solid."""

from dataclasses import replace

import pytest
from test_axial_computation import installed
from test_axial_computation import solid as solid
from test_diffusion_checkpoints import host
from test_electrothermal_checkpoints import request

from code_visualizer.application.axial_examples import MODEL_ID
from code_visualizer.application.cad_examples import recipe_request, spring_cad_project
from code_visualizer.application.computation import execute_computation
from code_visualizer.application.coupled_examples import electrothermal_project
from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.extensions.axial.authoring import create_models
from code_visualizer.extensions.axial.domain import identity
from code_visualizer.extensions.axial.geometry import certify_prism
from code_visualizer.extensions.axial.problem import AxialError, derive_problem
from code_visualizer.extensions.cad.native import decode_solid
from code_visualizer.extensions.cad.resources import BREP


@pytest.mark.parametrize("role", ("material", "support"))
@pytest.mark.parametrize("count", (0, 2))
def test_missing_or_multiple_axial_owners_diagnose_the_authored_problem(solid, role, count):
    project, _, resource = solid
    project = installed(project, resource)
    model = project.domain_workspace.model(MODEL_ID)
    root = model.node("axial:problem")
    original = model.node("axial:" + role)
    extra = replace(original, id=original.id + ":extra")
    bindings = tuple(
        replace(binding, node_ids=() if count == 0 else (original.id, extra.id))
        if binding.role_id == identity("AxialProblem", role)
        else binding
        for binding in root.children
    )
    updated = replace(root, children=bindings)
    model = replace(
        model,
        nodes=tuple(updated if n.id == root.id else n for n in model.nodes)
        + ((extra,) if count == 2 else ()),
    )
    with pytest.raises(AxialError) as error:
        derive_problem(project, model)
    assert (error.value.code, error.value.object_id) == ("AXIAL_OWNERSHIP", "axial:problem")


def test_missing_modulus_is_a_material_diagnostic(solid):
    project, _, resource = solid
    project = installed(project, resource)
    model = project.domain_workspace.model(MODEL_ID)
    material = replace(model.node("axial:material"), properties=())
    model = replace(model, nodes=tuple(material if n.id == material.id else n for n in model.nodes))
    with pytest.raises(AxialError) as error:
        derive_problem(project, model)
    assert (error.value.code, error.value.object_id) == ("AXIAL_QUANTITY", material.id)


def test_original_p4_perforated_recipe_is_not_a_solid_axial_bar(tmp_path):
    project = spring_cad_project()
    with host(project, tmp_path) as kernel:
        solved = execute_computation(
            kernel,
            ComputationRequest(
                project.id,
                project.revision,
                "foundation.math.linear_equations",
                "1",
                "spring:equations",
            ),
        )
        assert solved.outcome is ComputationOutcome.SUCCEEDED, solved.diagnostics
        geometry = execute_computation(
            kernel, recipe_request(project, solved.artifacts[0].resource)
        )
        assert geometry.outcome is ComputationOutcome.SUCCEEDED, geometry.diagnostics
        resource = next(
            a.resource
            for a in geometry.artifacts
            if kernel.resource_store.describe(a.resource).logical_type == BREP
        )
        header, shape = decode_solid(kernel.resource_store.read(resource))
    assert "cad:cut" in header.origins.semantic_ids
    model, regions = create_models(
        project, resource, frame_id=header.frame.frame_id, namespace="axial"
    )
    project = replace(
        project,
        domain_workspace=replace(
            project.domain_workspace, models=(*project.domain_workspace.models, model, regions)
        ),
    )
    problem = derive_problem(project, model)
    with pytest.raises(AxialError) as error:
        certify_prism(header, shape, problem)
    assert (error.value.code, error.value.object_id) == (
        "AXIAL_GEOMETRY_UNSUPPORTED",
        "axial:geometry",
    )


def test_output_budget_failure_has_policy_origin_and_publishes_no_prefix(tmp_path):
    project = electrothermal_project(
        duration=10000, windows=100000, sample_every=50, checkpoint_every=1000
    )
    with host(project, tmp_path) as kernel:
        evidence = execute_computation(kernel, request(project))
        assert evidence.outcome is ComputationOutcome.FAILED
        assert not evidence.artifacts
        assert not kernel.computations.attempts()[0].publications
        assert any(
            d.code == "COUPLING_OUTPUT_BUDGET"
            and d.semantic_ids == ("et:policy",)
            and "COMPUTATION_PUBLICATION_LIMIT" in d.message
            for d in evidence.diagnostics
        )
