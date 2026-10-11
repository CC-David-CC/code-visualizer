"""Real emitted CAD producer, checked geometry and P3 equilibrium; independent oracles."""

from dataclasses import replace

import numpy as np
import pytest
from test_diffusion_checkpoints import host

from code_visualizer.application.axial_examples import (
    MODEL_ID,
    axial_cad_project,
    axial_models,
    recipe_request,
)
from code_visualizer.application.computation import (
    execute_computation,
    export_computation_plan,
    run_computation_plan,
)
from code_visualizer.application.domain_commands import PutDomainModel
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.extensions.axial.assembly import BarElement, solve_bar
from code_visualizer.extensions.axial.domain import BACKEND_ID, quantity
from code_visualizer.extensions.axial.records import CODEC, AxialMapping, AxialResult
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.cad.resources import BREP
from code_visualizer.extensions.fields.arrays import read_array
from code_visualizer.persistence.computation_resources import resolve_computation_resource
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.serialization import normalized_project_json
from code_visualizer.sdk import CodeVisualizerClient


def produced(path, **kwargs):
    path.mkdir(parents=True, exist_ok=True)
    project = axial_cad_project(**kwargs)
    source = path / "authored.json"
    source.write_text(normalized_project_json(project), encoding="utf-8")
    project = project_from_json(source.read_text(encoding="utf-8"))
    with host(project, path) as kernel:
        result = execute_computation(kernel, recipe_request(project))
        assert result.outcome is ComputationOutcome.SUCCEEDED, result.diagnostics
        resource = next(
            item.resource
            for item in result.artifacts
            if kernel.resource_store.describe(item.resource).logical_type == BREP
        )
        assert all(
            kernel.computations.job(item.session.id).managed is None
            for item in kernel.computations.attempts()
        )
        assert normalized_project_json(project) == normalized_project_json(
            kernel.authority.snapshot()
        )
    return project, ResourceStore(path), resource


@pytest.fixture(scope="module")
def solid(tmp_path_factory):
    return produced(tmp_path_factory.mktemp("real-solid-producer"))


def installed(project, resource, **kwargs):
    models = axial_models(project, resource, **kwargs)
    return replace(
        project,
        domain_workspace=replace(
            project.domain_workspace, models=(*project.domain_workspace.models, *models)
        ),
    )


def request(project):
    return ComputationRequest(project.id, project.revision, BACKEND_ID, "1", model_id=MODEL_ID)


def decode(store, result):
    record = CODEC.decode(store.read(result.artifacts[0].resource), AxialResult)
    mapping = CODEC.decode(store.read(record.mapping), AxialMapping)
    arrays = {}
    for field, shape, unit in (
        ("coordinates", (record.nodes,), "meter"),
        ("displacement", (record.nodes,), "meter"),
        ("stress", (record.nodes - 1,), "pascal"),
        ("element_force", (record.nodes - 1,), "newton"),
        ("stiffness", (record.nodes, record.nodes), "newton_per_meter"),
        ("right", (record.nodes,), "newton"),
    ):
        resource = resolve_computation_resource(store, getattr(record, field))
        assert resource.descriptor.tensor.unit == quantity(1, unit).unit
        arrays[field] = read_array(resource, shape)
    return record, mapping, arrays


def oracle(store, evidence, *, length=0.1, area=1e-4, modulus=2e11, force=1000):
    record, mapping, arrays = decode(store, evidence)
    assert mapping.length.magnitude == pytest.approx(length, rel=1e-7, abs=1e-9)
    assert mapping.area.magnitude == pytest.approx(area, rel=1e-7, abs=1e-18)
    displacement = arrays["displacement"]
    expected = np.linspace(0, force * length / (modulus * area), record.nodes)
    np.testing.assert_allclose(displacement, expected, rtol=1e-8, atol=1e-12)
    np.testing.assert_allclose(arrays["stress"], force / area, rtol=1e-8, atol=1e-12)
    np.testing.assert_allclose(arrays["element_force"], force, rtol=1e-8, atol=1e-12)
    equilibrium = arrays["stiffness"] @ displacement - arrays["right"]
    np.testing.assert_allclose(equilibrium[1:], 0, rtol=0, atol=max(1, abs(force)) * 1e-10)
    assert record.reaction.magnitude == pytest.approx(-force, rel=1e-8, abs=1e-12)
    assert record.strain_energy.magnitude == pytest.approx(
        force**2 * length / (2 * modulus * area), rel=1e-8, abs=1e-12
    )
    assert {"axial:geometry", "axial:material", "axial:support", "axial:load"} <= set(
        record.semantic_ids
    )
    assert "bar:box" in mapping.geometry_origins
    assert mapping.support_face != mapping.load_face
    assert mapping.geometry in evidence.provenance.resources
    return arrays


@pytest.mark.parametrize("nodes", (3, 9, 17, 65))
def test_actual_element_assembly_matches_bar_oracles_on_all_declared_resolutions(
    solid, tmp_path, nodes
):
    project, source, resource = solid
    destination = ResourceStore(tmp_path)
    for ref in builtin_registry().resource_closure((resource,), source):
        destination.import_reference(source, ref)
    with host(project, tmp_path) as kernel:
        client = CodeVisualizerClient(kernel.authority, actor_id="axial-proof")
        models = axial_models(project, resource, nodes=nodes)
        assert isinstance(
            client.transaction(tuple(PutDomainModel(model) for model in models)), CommandAccepted
        )
        current = client.snapshot()
        before = normalized_project_json(current)
        evidence = execute_computation(kernel, request(current))
        assert evidence.outcome is ComputationOutcome.SUCCEEDED, evidence.diagnostics
        oracle(destination, evidence)
        assert normalized_project_json(client.snapshot()) == before


@pytest.mark.parametrize("force", (0, -1000, 250))
def test_zero_and_signed_load_use_the_same_equilibrium(solid, tmp_path, force):
    project, source, resource = solid
    destination = ResourceStore(tmp_path)
    destination.import_reference(source, resource)
    current = installed(project, resource, force=force)
    with host(current, tmp_path) as kernel:
        result = execute_computation(kernel, request(current))
        assert result.outcome is ComputationOutcome.SUCCEEDED, result.diagnostics
        oracle(destination, result, force=force)


@pytest.mark.parametrize(
    "native_unit,length,width,height",
    (
        ("meter", 0.1, 0.01, 0.01),
        ("millimeter", 0.2, 0.02, 0.01),
    ),
)
def test_native_coordinate_units_and_altered_valid_section(
    tmp_path, native_unit, length, width, height
):
    project, source, resource = produced(
        tmp_path / "producer", native_unit=native_unit, length=length, width=width, height=height
    )
    current = installed(project, resource)
    destination = ResourceStore(tmp_path / "consumer")
    destination.import_reference(source, resource)
    # The original process has exited and its entire source/resource directory is gone.
    (tmp_path / "producer").rename(tmp_path / "retired-producer")
    with host(current, tmp_path / "consumer") as kernel:
        result = execute_computation(kernel, request(current))
        assert result.outcome is ComputationOutcome.SUCCEEDED, result.diagnostics
        oracle(destination, result, length=length, area=width * height)
        plan = export_computation_plan(kernel, request(current))
        empty = ResourceStore(tmp_path / "portable")
        registry = kernel.extensions
        for ref in registry.resource_closure((plan.model, *plan.request.resources), destination):
            empty.import_reference(destination, ref)
    replay = run_computation_plan(plan, registry, empty, EvidenceStore(tmp_path / "portable"))
    assert replay.outcome is ComputationOutcome.SUCCEEDED, replay.diagnostics
    oracle(empty, replay, length=length, area=width * height)


def test_nonuniform_small_element_assembly_has_an_independent_series_compliance():
    elements = (BarElement(0.04, 1e-4, 2e11), BarElement(0.06, 2e-4, 1e11))
    solved = solve_bar(elements, 1000, "authored:bar", ("authored:bar",))
    compliance = [item.length / (item.area * item.young_modulus) for item in elements]
    assert solved.displacement == pytest.approx(
        (0, 1000 * compliance[0], 1000 * sum(compliance)), rel=1e-8, abs=1e-12
    )
    assert solved.stress == pytest.approx((1e7, 5e6), rel=1e-8, abs=1e-12)
    assert solved.reaction == pytest.approx(-1000, rel=1e-8, abs=1e-12)
    assert solved.energy == pytest.approx(0.5 * 1000**2 * sum(compliance), rel=1e-8, abs=1e-12)
