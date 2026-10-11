"""The equation/Python/CAD composition crosses actual child-process and resource boundaries."""

from dataclasses import replace
from math import hypot, pi

import pytest
from test_python_artifact_bindings import host

from code_visualizer.application.cad_artifacts import prepare_consumer
from code_visualizer.application.cad_examples import recipe_request, spring_cad_project
from code_visualizer.application.computation import execute_computation
from code_visualizer.application.domain_commands import SetDomainProperty
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.extensions.cad.domain import consumer_model, identity, quantity
from code_visualizer.extensions.cad.native import decode_mesh, decode_solid
from code_visualizer.extensions.cad.resources import BREP, MESH
from code_visualizer.persistence.decoding import project_from_data
from code_visualizer.persistence.serialization import project_to_data
from code_visualizer.sdk import CodeVisualizerClient


def consume(project, path, resource, concept, **properties):
    model = consumer_model("cad:consumer", "cad:operation", concept, resource, **properties)
    consumer = replace(
        project,
        domain_workspace=replace(
            project.domain_workspace, models=(*project.domain_workspace.models, model)
        ),
    )
    with host(consumer, path) as (_, kernel):
        result = execute_computation(
            kernel,
            ComputationRequest(
                consumer.id,
                consumer.revision,
                "code_visualizer.cad." + concept.lower(),
                "1",
                model_id=model.id,
            ),
        )
        assert result.outcome is ComputationOutcome.SUCCEEDED, result.diagnostics
        return result


def test_spring_python_solid_fresh_measurement_and_mesh(tmp_path):
    project = project_from_data(project_to_data(spring_cad_project()))
    before = project_to_data(project)
    with host(project, tmp_path) as (_, kernel):
        solved = execute_computation(
            kernel,
            ComputationRequest(
                project.id,
                project.revision,
                "foundation.math.linear_equations",
                "1",
                model_id="spring:equations",
            ),
        )
        assert solved.outcome is ComputationOutcome.SUCCEEDED, solved.diagnostics
        solution = solved.artifacts[0].resource
    with host(project, tmp_path) as (service, kernel):
        result = execute_computation(kernel, recipe_request(project, solution))
        assert result.outcome is ComputationOutcome.SUCCEEDED, result.diagnostics
        geometry = next(
            a
            for a in result.artifacts
            if kernel.resource_store.describe(a.resource).logical_type == BREP
        )
        data = kernel.resource_store.read(geometry.resource)
        header, solid = decode_solid(data)
        assert header.parent == solution
        assert header.origins.input_digest == result.provenance.input_digest
        assert {"cad:parameters", "cad:box", "cad:cut", "cad:publish"} <= set(geometry.semantic_ids)
        assert header.frame.unit.id == "foundation.units.si:millimeter"
        assert pytest.approx(50, abs=1e-5) == solid.bounding_box().size.X
        assert any("Real emitted module: True" in str(o.value) for o in result.observations)
        assert all(service.job(a.session.id).managed is None for a in service.attempts())
    assert project_to_data(project) == before
    measured = consume(project, tmp_path, geometry.resource, "Measurement")
    values = {o.label: o.value.magnitude for o in measured.observations}
    assert values["extent_x"] == pytest.approx(0.05, abs=1e-8)
    assert values["volume"] == pytest.approx(0.05 * 0.02 * 0.01 - pi * 0.002**2 * 0.01, abs=1e-12)
    assert geometry.resource in measured.provenance.resources
    meshed = consume(project, tmp_path, geometry.resource, "Tessellation")
    with host(project, tmp_path) as (_, kernel):
        mesh_ref = meshed.artifacts[0].resource
        assert kernel.resource_store.describe(mesh_ref).logical_type == MESH
        mesh = decode_mesh(kernel.resource_store.read(mesh_ref))
        assert mesh.header.parent == geometry.resource
        assert mesh.header.tolerance == pytest.approx(0.05)
        assert mesh.header.angular_tolerance == pytest.approx(0.1)
        assert mesh.triangles and len(mesh.face_ids) == len(mesh.triangles)
        wall_chords = []
        for indices in mesh.triangles:
            points = [mesh.vertices[i] for i in indices]
            if max(p[2] for p in points) - min(p[2] for p in points) < 1e-8:
                continue
            if all(abs(hypot(p[0] - 25, p[1] - 10) - 2) < 1e-8 for p in points):
                wall_chords.extend(
                    abs(hypot((a[0] + b[0]) / 2 - 25, (a[1] + b[1]) / 2 - 10) - 2)
                    for a, b in zip(points, points[1:] + points[:1], strict=True)
                )
        assert wall_chords and max(wall_chords) <= 0.05
        assert mesh_ref != geometry.resource
        assert kernel.resource_store.read(geometry.resource) == data
    with host(project, tmp_path) as (_, kernel):
        edit = prepare_consumer(
            project,
            kernel.extensions,
            result,
            geometry.id,
            kernel.resource_store,
            kernel.resource_store,
            "GeometryInput",
            model_id="cad:independent",
            node_id="cad:independent-solid",
        )
        client = CodeVisualizerClient(kernel.authority, actor_id="cad-author")
        accepted = client.transaction(edit.commands, expected_revision=edit.revision)
        assert isinstance(accepted, CommandAccepted), accepted
        assert client.snapshot().program_model == project.program_model
        assert isinstance(client.undo(), CommandAccepted)
        assert client.snapshot().domain_workspace.model(edit.model_id) is None
        assert kernel.resource_store.read(geometry.resource) == data
        assert isinstance(client.redo(), CommandAccepted)
        assert isinstance(
            client.submit(
                SetDomainProperty(
                    edit.model_id,
                    edit.node_id,
                    identity("GeometryInput", "translate_x"),
                    quantity(0.01),
                )
            ),
            CommandAccepted,
        )
        independent = execute_computation(kernel, edit.request(client.snapshot()))
        assert independent.outcome is ComputationOutcome.SUCCEEDED, independent.diagnostics
        moved = independent.artifacts[0].resource
        moved_header, moved_shape = decode_solid(kernel.resource_store.read(moved))
        assert moved_header.parent == geometry.resource
        assert moved_header.origins.semantic_ids == (edit.node_id,)
        assert pytest.approx(10, abs=1e-5) == moved_shape.bounding_box().min.X
        assert moved_shape.volume == pytest.approx(solid.volume, rel=1e-9)
        assert client.snapshot().program_model == project.program_model
        assert kernel.resource_store.read(geometry.resource) == data
        assert len(kernel.computations.attempts()) == 1  # Only the independent translation ran.
