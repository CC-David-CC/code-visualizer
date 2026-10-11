"""Equation artifacts run through the existing host and portable terminal boundary."""

import builtins
import json

import pytest
from test_equation_compiler import equation_project, quantity, spring_case

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.computation import (
    execute_computation,
    export_computation_plan,
    run_computation_plan,
)
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.foundations.equations import BACKEND_ID, RESULT_TYPE
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.serialization import normalized_project_json
from code_visualizer.persistence.store import ProjectStore


def test_equation_worker_returns_durable_resource_without_program_lowering(tmp_path, monkeypatch):
    pytest.importorskip("numpy")
    pytest.importorskip("sympy")
    pytest.importorskip("pint")
    case = spring_case()
    case.bind("F", quantity(10, "newton"))
    case.bind("k", quantity(200, "newton_per_meter"))
    project = equation_project(case.model(("x",)))
    store = ProjectStore(tmp_path)
    store.initialize(project)
    resources, evidence_store = ResourceStore(tmp_path), EvidenceStore(tmp_path)
    before = normalized_project_json(project)
    kernel = ProjectKernel(
        ProjectAuthority(project, store=store),
        resource_store=resources,
        evidence_store=evidence_store,
    )
    monkeypatch.setattr(
        "code_visualizer.generation.lowering.lower_project",
        lambda *_args, **_kwargs: pytest.fail("Equation execution reached ProgramModel lowering"),
    )
    request = ComputationRequest(project.id, project.revision, BACKEND_ID, "1", "math-model")
    try:
        plan = export_computation_plan(kernel, request)
        evidence = execute_computation(kernel, request)
        assert evidence.outcome is ComputationOutcome.SUCCEEDED, evidence.diagnostics
        assert evidence.provenance.backend_id == BACKEND_ID
        assert evidence.provenance.transformations == ()
        value = next(item for item in evidence.observations if item.id == "x:solution")
        assert value.value.magnitude == pytest.approx(0.05)
        assert evidence.provenance.origins.sources(value.semantic_ids[0]) == ("x",)
        descriptor = resources.describe(evidence.artifacts[0].resource)
        assert descriptor.logical_type == ResourceLogicalTypeReference(RESULT_TYPE, "1")
        report = json.loads(resources.read(descriptor.reference))
        assert report["variables"][0]["id"] == "x"
        assert report["rank"] == 1
        assert report["residuals"][0]["normalized"] == pytest.approx(0, abs=1e-12)
        assert "numpy" in report["libraries"]
        assert normalized_project_json(kernel.authority.snapshot()) == before
    finally:
        kernel.close()
    # The process and editor are gone. Only a portable plan and immutable stores
    # are needed to reopen and repeat the same computation through the worker API.
    reopened = EvidenceStore(tmp_path).get(evidence.id)
    assert reopened == evidence
    assert run_computation_plan(plan, builtin_registry(), ResourceStore(tmp_path)) == reopened
    assert normalized_project_json(ProjectStore(tmp_path).recover()) == before


@pytest.mark.parametrize("missing", ("pint", "sympy", "numpy"))
def test_optional_solver_dependency_failure_keeps_canonical_inputs(missing, tmp_path, monkeypatch):
    from computation_fixtures import InProcessTestKernel

    from code_visualizer.application.physical_examples import spring_equation_project

    project = spring_equation_project()
    kernel = InProcessTestKernel(
        ProjectAuthority(project),
        resource_store=ResourceStore(tmp_path),
        evidence_store=EvidenceStore(tmp_path),
    )
    original_import = builtins.__import__

    def missing_library(name, *args, **kwargs):
        if name == missing:
            raise ImportError(f"Test environment has no {missing}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_library)
    try:
        evidence = execute_computation(
            kernel,
            ComputationRequest(project.id, project.revision, BACKEND_ID, "1", "spring:equations"),
        )
        assert evidence.outcome is ComputationOutcome.FAILED
        assert evidence.diagnostics[0].code == "SCIENCE_DEPENDENCY_MISSING"
        assert not evidence.artifacts
        assert kernel.authority.snapshot() == project
    finally:
        kernel.close()


def test_invalid_units_are_evidence_diagnostics_without_calling_numerical_solver(
    tmp_path, monkeypatch
):
    pytest.importorskip("sympy")
    pytest.importorskip("pint")
    from computation_fixtures import InProcessTestKernel

    case = spring_case()
    case.bind("F", quantity(10, "newton"))
    case.bind("k", quantity(200, "volt"))
    project = equation_project(case.model(("x",)))
    kernel = InProcessTestKernel(
        ProjectAuthority(project),
        resource_store=ResourceStore(tmp_path),
        evidence_store=EvidenceStore(tmp_path),
    )
    monkeypatch.setattr(
        "code_visualizer.extensions.foundations.equation_backend.solve_linear",
        lambda *_: pytest.fail("Invalid dimensions reached the numerical solver"),
    )
    try:
        evidence = execute_computation(
            kernel, ComputationRequest(project.id, project.revision, BACKEND_ID, "1", "math-model")
        )
        assert evidence.outcome is ComputationOutcome.FAILED
        assert evidence.diagnostics[0].code == "UNIT_DIMENSION_MISMATCH"
        assert not evidence.artifacts
    finally:
        kernel.close()
