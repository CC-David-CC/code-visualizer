"""Affine typing reaches the real worker, immutable resources and original views."""

import hashlib
import json

import pytest
from test_affine_equations import mixed_relation_model, translation_model
from test_equation_compiler import EquationCase, equation_project, quantity

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.computation import (
    execute_computation,
    export_computation_plan,
    run_computation_plan,
)
from code_visualizer.application.domain_workbench import project_notation
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.domain.notation import NotationKind
from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.foundations.equations import BACKEND_ID, RESULT_TYPE
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.serialization import normalized_project_json
from code_visualizer.persistence.store import ProjectStore
from code_visualizer.persistence.values import canonical_value_from_data
from code_visualizer.protocol.computation import (
    computation_plan_from_proto,
    computation_plan_to_proto,
)
from code_visualizer.protocol.evidence import evidence_from_proto, evidence_to_proto


@pytest.fixture(autouse=True)
def science_dependencies():
    for name in ("numpy", "sympy", "pint"):
        pytest.importorskip(name)


def point_equality_model():
    case = EquationCase()
    case.symbol("T", quantity(1, "degree_celsius"), "point")
    case.equation(
        "temperature",
        case.ref("out", "T"),
        case.value("known-point", quantity(10, "kelvin"), "point"),
        quantity(1, "degree_celsius"),
    )
    return case.model(("T",))


def tree_nodes(roots):
    for node in roots:
        yield node
        yield from tree_nodes(node.children)


def assert_original_symbol_is_active_in_every_notation(kernel, model):
    project = kernel.authority.snapshot()
    states = kernel.runtime.history(kernel.runtime.active.execution_session_id)
    state = next(state for state in states if "T" in state.active_ids)
    definitions = kernel.extensions.notations_for(model.schema_id, model.schema_version)
    assert {definition.kind for definition in definitions} == {
        NotationKind.GRAPH,
        NotationKind.TABLE,
        NotationKind.TREE_FORM,
    }
    for definition in definitions:
        projection = project_notation(
            project,
            model.id,
            definition.id,
            kernel.extensions,
            active_node_ids=state.active_ids,
            runtime_revision=state.project_revision,
        )
        if definition.kind is NotationKind.TABLE:
            assert next(row for row in projection.rows if row.node_id == "T").active
        elif definition.kind is NotationKind.TREE_FORM:
            assert next(node for node in tree_nodes(projection.roots) if node.node_id == "T").active
        else:
            node = next(node for node in projection.graph.nodes if node.semantic_id == "T")
            assert "active" in node.badges
        # Existing notations preserve historical activity with its revision and
        # an explicit stale badge, rather than relabeling it as current activity.
        stale = project_notation(
            project,
            model.id,
            definition.id,
            kernel.extensions,
            active_node_ids=state.active_ids,
            runtime_revision=state.project_revision + 1,
        )
        assert stale.runtime_revision != project.revision
        assert (
            "runtime stale"
            in next(node for node in stale.graph.nodes if node.semantic_id == "T").badges
        )
        assert not any("active" in node.badges for node in stale.graph.nodes)


@pytest.mark.parametrize(
    "case,expected,output_unit,residual_unit",
    (
        ("interval-times-scalar", 40, "degree_celsius", "kelvin"),
        ("scalar-times-interval", 313.15, "kelvin", "degree_celsius"),
        ("interval-divided-by-scalar", 25, "degree_celsius", "degree_celsius"),
        ("point-equality", -263.15, "degree_celsius", "degree_celsius"),
    ),
)
def test_affine_host_resource_replay_and_shared_runtime_origins(
    case, expected, output_unit, residual_unit, tmp_path
):
    if case == "point-equality":
        model = point_equality_model()
    else:
        model = translation_model(
            "divide" if case == "interval-divided-by-scalar" else "multiply",
            reverse=case == "scalar-times-interval",
            bound=case != "scalar-times-interval",
            output_unit=output_unit,
            residual_unit=residual_unit,
        )
    project = equation_project(model)
    store = ProjectStore(tmp_path)
    store.initialize(project)
    before = normalized_project_json(project)
    resources, evidence_store = ResourceStore(tmp_path), EvidenceStore(tmp_path)
    kernel = ProjectKernel(
        ProjectAuthority(project, store=store),
        resource_store=resources,
        evidence_store=evidence_store,
    )
    try:
        request = ComputationRequest(project.id, project.revision, BACKEND_ID, "1", model.id)
        plan = computation_plan_from_proto(
            computation_plan_to_proto(export_computation_plan(kernel, request))
        )
        evidence = execute_computation(kernel, request)
        assert evidence.outcome is ComputationOutcome.SUCCEEDED, evidence.diagnostics
        assert evidence.provenance.transformations == ()
        value = next(item for item in evidence.observations if item.id == "T:solution")
        assert value.value.unit == quantity(1, output_unit).unit
        assert value.value.magnitude == pytest.approx(expected, abs=1e-10)
        assert evidence.provenance.origins.sources(value.semantic_ids[0]) == ("T",)
        residual = next(
            item for item in evidence.observations if item.id == "temperature:use:residual"
        )
        assert "temperature" in residual.semantic_ids
        assert residual.value.unit == quantity(1, residual_unit).unit
        assert residual.value.magnitude == pytest.approx(0, abs=1e-10)
        assert len(evidence.artifacts) == 1
        resource = evidence.artifacts[0].resource
        descriptor = resources.describe(resource)
        assert descriptor.logical_type == ResourceLogicalTypeReference(RESULT_TYPE, "1")
        raw = resources.read(resource)
        assert hashlib.sha256(raw).hexdigest() == resource.content_hash
        report = json.loads(raw)
        variable = report["variables"][0]
        assert (variable["id"], variable["kind"]) == ("T", "point")
        assert canonical_value_from_data(variable["value"]) == value.value
        assert report["residuals"][0]["equation_id"] == "temperature"
        assert report["residuals"][0]["base_scale"] == pytest.approx(1)
        assert report["residuals"][0]["normalized"] == pytest.approx(0, abs=1e-10)
        assert_original_symbol_is_active_in_every_notation(kernel, model)
        assert evidence_from_proto(evidence_to_proto(evidence)) == evidence
        assert normalized_project_json(kernel.authority.snapshot()) == before
    finally:
        kernel.close()
    # A fresh store and no live editor/producer are sufficient for native reopening
    # and the real portable replay path; derived output never becomes authored state.
    reopened_resources = ResourceStore(tmp_path)
    assert EvidenceStore(tmp_path).get(evidence.id) == evidence
    assert reopened_resources.read(resource) == raw
    assert run_computation_plan(plan, builtin_registry(), reopened_resources) == evidence
    assert normalized_project_json(ProjectStore(tmp_path).recover()) == before


@pytest.mark.parametrize("reverse", (False, True))
def test_incompatible_equality_is_durable_failed_evidence_without_solution(reverse, tmp_path):
    model = mixed_relation_model(reverse)
    project = equation_project(model)
    resources, evidence_store = ResourceStore(tmp_path), EvidenceStore(tmp_path)
    kernel = ProjectKernel(
        ProjectAuthority(project), resource_store=resources, evidence_store=evidence_store
    )
    try:
        request = ComputationRequest(project.id, project.revision, BACKEND_ID, "1", model.id)
        plan = export_computation_plan(kernel, request)
        evidence = execute_computation(kernel, request)
        assert evidence.outcome is ComputationOutcome.FAILED
        assert [(d.code, d.semantic_ids) for d in evidence.diagnostics] == [
            ("UNIT_KIND_MISMATCH", ("bad-equality",))
        ]
        assert not evidence.artifacts and not evidence.observations
        assert kernel.authority.snapshot() == project
    finally:
        kernel.close()
    assert evidence_store.get(evidence.id) == evidence
    assert run_computation_plan(plan, builtin_registry(), ResourceStore(tmp_path)) == evidence


@pytest.mark.parametrize("reverse", (False, True))
def test_invalid_equality_cannot_call_the_numerical_solver(reverse, tmp_path, monkeypatch):
    from computation_fixtures import InProcessTestKernel

    model = mixed_relation_model(reverse)
    project = equation_project(model)
    kernel = InProcessTestKernel(
        ProjectAuthority(project),
        resource_store=ResourceStore(tmp_path),
        evidence_store=EvidenceStore(tmp_path),
    )

    def forbidden(*args, **kwargs):
        pytest.fail("An invalid affine relation reached the numerical solver")

    monkeypatch.setattr(
        "code_visualizer.extensions.foundations.equation_backend.solve_linear", forbidden
    )
    try:
        evidence = execute_computation(
            kernel, ComputationRequest(project.id, project.revision, BACKEND_ID, "1", model.id)
        )
        assert evidence.outcome is ComputationOutcome.FAILED
        assert evidence.diagnostics[0].code == "UNIT_KIND_MISMATCH"
        assert evidence.diagnostics[0].semantic_ids == ("bad-equality",)
        assert not evidence.artifacts
    finally:
        kernel.close()
