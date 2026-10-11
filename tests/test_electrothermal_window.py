"""P6 first vertical slice: real retry, immutable base and ordinary host publication."""

from dataclasses import replace
from math import sqrt
from threading import Event

import pytest

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.computation import _resolve_resources, execute_computation
from code_visualizer.application.coupled_examples import MODEL_ID, electrothermal_project
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.domain.intentional_validation import validate_domain_workspace
from code_visualizer.execution.backends import BackendContext
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.channels.codec import CODEC
from code_visualizer.extensions.channels.records import (
    SERIES_TYPE,
    ChannelInterpretation,
    ChannelSeries,
)
from code_visualizer.extensions.electrothermal.domain import BACKEND_ID
from code_visualizer.extensions.electrothermal.numerics import CoupledSolver, WindowCancelled
from code_visualizer.extensions.electrothermal.problem import (
    CouplingError,
    definition_digest,
    derive_problem,
)
from code_visualizer.extensions.fields.arrays import read_array
from code_visualizer.generation.computation import prepare_computation
from code_visualizer.persistence.computation_resources import resolve_computation_resource
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.serialization import normalized_project_json


def prepared(**kwargs):
    project = electrothermal_project(duration=1, windows=1, **kwargs)
    assert not validate_domain_workspace(project.domain_workspace)
    request = ComputationRequest(project.id, project.revision, BACKEND_ID, "1", model_id=MODEL_ID)
    snapshot = _resolve_resources(None, prepare_computation(project, request, builtin_registry()))
    problem = derive_problem(snapshot.project, snapshot.value)
    return project, request, snapshot, CoupledSolver(snapshot, problem, definition_digest(snapshot))


def implicit_reference(x0=0.0, y0=0.0, step=1.0, alpha=0.004):
    # Eliminate the sink equation; this independent scalar quadratic is not the
    # production partitioned matrix assembly or a call to its coefficient/RHS helper.
    cr, cs, g, h, p0 = 10.0, 20.0, 0.2, 0.1, 2.5
    q = cs / step + g + h
    a = cr / step + g - g * g / q
    b = cr * x0 / step + g * cs * y0 / (step * q)
    linear = a - b * alpha
    x = 2 * (b + p0) / (linear + sqrt(linear * linear + 4 * a * alpha * (b + p0)))
    y = (cs * y0 / step + g * x) / q
    return x, y


def test_real_rejected_window_restarts_full_base_and_converges():
    project, _, _, solver = prepared()
    source = normalized_project_json(project)
    base = solver.initial()
    trials = list(solver.trials(base, BackendContext("test", Event())))
    assert len(trials) > 1 and not trials[0].converged and trials[-1].converged
    assert all(trial.base is base for trial in trials)
    assert base.step == 0 and base.energy_in == base.energy_out == 0
    for rejected in trials[:-1]:
        with pytest.raises(CouplingError, match="rejected"):
            solver.accept(rejected)
    state = solver.accept(trials[-1])
    assert (state.resistor_rise, state.sink_rise) == pytest.approx(implicit_reference(), abs=1e-10)
    assert state.step == 1
    assert state.energy_in == pytest.approx(trials[-1].electrical.power)
    assert abs(trials[-1].energy_residual) < 1e-9
    assert trials[-1].normalized_residual < 1e-10
    assert normalized_project_json(project) == source


def test_reversed_real_component_order_has_same_endpoint():
    endpoints = []
    for order in ("electrical_first", "thermal_first"):
        _, _, _, solver = prepared(evaluation_order=order)
        trials = list(solver.trials(solver.initial(), BackendContext("test", Event())))
        endpoints.append(solver.accept(trials[-1]))
    assert endpoints[0] == endpoints[1]


@pytest.mark.parametrize("boundary", ["electrical", "thermal"])
def test_cancellation_during_component_does_not_advance_base(monkeypatch, boundary):
    _, _, _, solver = prepared()
    event = Event()
    original = getattr(solver, boundary)

    def cancel_after_real_component(*args):
        result = original(*args)
        event.set()
        return result

    monkeypatch.setattr(solver, boundary, cancel_after_real_component)
    base = solver.initial()
    with pytest.raises(WindowCancelled):
        list(solver.trials(base, BackendContext("cancel", event)))
    assert base == solver.initial()


def test_candidate_with_mixed_window_is_rejected(monkeypatch):
    _, _, _, solver = prepared()
    original = solver.thermal

    def stale(*args):
        result = original(*args)
        return replace(result, window=replace(result.window, time=0.0))

    monkeypatch.setattr(solver, "thermal", stale)
    with pytest.raises(CouplingError) as error:
        list(solver.trials(solver.initial(), BackendContext("test", Event())))
    assert error.value.code == "COUPLING_ENDPOINT"
    assert error.value.object_id in solver.problem.exchange_ids


def test_saved_source_real_host_publishes_only_coherent_accepted_samples(tmp_path):
    source = electrothermal_project(duration=1, windows=1)
    path = tmp_path / "project.json"
    path.write_text(normalized_project_json(source), encoding="utf-8")
    project = project_from_json(path.read_text(encoding="utf-8"))
    kernel = ProjectKernel(
        ProjectAuthority(project),
        resource_store=ResourceStore(tmp_path),
        evidence_store=EvidenceStore(tmp_path),
    )
    try:
        request = ComputationRequest(
            project.id, project.revision, BACKEND_ID, "1", model_id=MODEL_ID
        )
        evidence = execute_computation(kernel, request)
        assert evidence.outcome == ComputationOutcome.SUCCEEDED, evidence.diagnostics
        roots = [
            item.resource
            for item in evidence.artifacts
            if kernel.resource_store.describe(item.resource).logical_type == SERIES_TYPE
        ]
        assert len(roots) == 2  # Initial sample and converged endpoint; no rejected trial root.
        series = CODEC.decode(kernel.resource_store.read(roots[-1]), ChannelSeries)
        meaning = CODEC.decode(
            kernel.resource_store.read(series.interpretation), ChannelInterpretation
        )
        rows = []
        for chunk in series.chunks:
            rows.extend(
                read_array(
                    resolve_computation_resource(kernel.resource_store, chunk.resource),
                    (chunk.rows, chunk.columns + 2),
                )
            )
        assert len(rows) == 2 and rows[0][0] == 0 and rows[-1][0] == rows[-1][1] == 1
        final = dict(
            zip(
                (item.id.rsplit(":", 1)[-1] for item in meaning.channels), rows[-1][2:], strict=True
            )
        )
        x, y = implicit_reference()
        assert final["resistor_temperature"] == pytest.approx(293.15 + x, abs=1e-10)
        assert final["sink_temperature"] == pytest.approx(293.15 + y, abs=1e-10)
        assert final["power"] == pytest.approx(final["voltage"] * final["current"], abs=1e-12)
        assert final["power"] == pytest.approx(
            final["current"] ** 2 * final["resistance"], abs=1e-12
        )
        assert final["resistor_contact_out"] == -final["sink_contact_out"]
        assert abs(final["energy_imbalance"]) < 1e-9
        assert (
            next(item.value for item in evidence.observations if item.id == "rejected_trials") > 0
        )
        assert {item.quantity_kind.value for item in meaning.channels} == {"point", "linear"}
        assert normalized_project_json(project) == normalized_project_json(source)
    finally:
        kernel.close()
