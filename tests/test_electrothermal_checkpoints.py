"""Real host checkpoints must reproduce complete channels and reject corrupt prefixes."""

from dataclasses import replace

import numpy as np
import pytest
from test_diffusion_checkpoints import host
from test_electrothermal_contracts import changed

from code_visualizer.application.computation import (
    _resolve_resources,
    execute_computation,
    export_computation_plan,
    run_computation_plan,
)
from code_visualizer.application.coupled_examples import MODEL_ID, electrothermal_project
from code_visualizer.domain.computation import ComputationParameter, ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.extensions.channels.codec import CODEC as CHANNEL_CODEC
from code_visualizer.extensions.channels.history import ChannelHistory
from code_visualizer.extensions.channels.records import SERIES_TYPE, ChannelSeries
from code_visualizer.extensions.electrothermal.checkpoint import (
    CHECKPOINT_TYPE,
    CODEC,
    CoupledCheckpoint,
    restore,
)
from code_visualizer.extensions.electrothermal.domain import BACKEND_ID
from code_visualizer.extensions.electrothermal.numerics import CoupledSolver
from code_visualizer.extensions.electrothermal.problem import (
    CouplingError,
    definition_digest,
    derive_problem,
)
from code_visualizer.extensions.electrothermal.units import quantity
from code_visualizer.extensions.fields.arrays import array_resource, read_array
from code_visualizer.extensions.fields.records import TemporalPosition
from code_visualizer.generation.computation import prepare_computation
from code_visualizer.persistence.computation_resources import resolve_computation_resource


def request(project, checkpoint=None):
    return ComputationRequest(
        project.id,
        project.revision,
        BACKEND_ID,
        "1",
        model_id=MODEL_ID,
        configuration=(ComputationParameter("checkpoint", checkpoint),) if checkpoint else (),
    )


def history(store, root):
    return ChannelHistory(
        root, lambda ref: resolve_computation_resource(store, ref, file_backed=True)
    )


def last_root(result, store):
    return [
        item.resource
        for item in result.artifacts
        if store.describe(item.resource).logical_type == SERIES_TYPE
    ][-1]


def rows(store, root):
    view = history(store, root)
    try:
        return np.concatenate([data.copy() for _, data in view.iter_chunks()])
    finally:
        view.close()


@pytest.fixture(scope="module")
def completed(tmp_path_factory):
    project = electrothermal_project(duration=4, windows=4, sample_every=1, checkpoint_every=2)
    with host(project, tmp_path_factory.mktemp("coupled-checkpoints")) as kernel:
        result = execute_computation(kernel, request(project))
        assert result.outcome == ComputationOutcome.SUCCEEDED, result.diagnostics
        checkpoint = next(item.resource for item in result.artifacts if item.id == "checkpoint:2")
        yield project, kernel, result, checkpoint


def restore_direct(project, kernel, checkpoint):
    snapshot = _resolve_resources(
        kernel.resource_store,
        prepare_computation(project, request(project, checkpoint), kernel.extensions),
        kernel.extensions,
    )
    problem = derive_problem(snapshot.project, snapshot.value)
    source = definition_digest(snapshot)
    solver = CoupledSolver(snapshot, problem, source)
    return restore(snapshot, checkpoint, problem, source, solver)


def test_real_resume_and_portable_plan_reproduce_every_channel(completed):
    project, kernel, original, checkpoint = completed
    expected = rows(kernel.resource_store, last_root(original, kernel.resource_store))
    restored, state = restore_direct(project, kernel, checkpoint)
    assert state.step == 2 and restored.sample_count == 3
    restored.close()
    result = execute_computation(kernel, request(project, checkpoint))
    assert result.outcome == ComputationOutcome.SUCCEEDED, result.diagnostics
    assert np.array_equal(
        rows(kernel.resource_store, last_root(result, kernel.resource_store)), expected
    )
    plan = export_computation_plan(kernel, request(project, checkpoint))
    replay = run_computation_plan(
        plan, kernel.extensions, kernel.resource_store, kernel.evidence_store
    )
    assert replay.outcome == ComputationOutcome.SUCCEEDED, replay.diagnostics
    assert np.array_equal(
        rows(kernel.resource_store, last_root(replay, kernel.resource_store)), expected
    )


@pytest.mark.parametrize("component", range(4))
def test_each_state_component_must_match_the_retained_prefix(completed, component):
    project, kernel, _, reference = completed
    store = kernel.resource_store
    record = CODEC.decode(store.read(reference), CoupledCheckpoint)
    vector = read_array(resolve_computation_resource(store, record.state), (4,)).copy()
    vector[component] += 1
    produced = array_resource("corrupt-state", vector)
    state = store.put(
        produced.data,
        produced.media_type,
        tensor=produced.tensor,
        logical_type=produced.logical_type,
    )
    corrupt = store.put(
        CODEC.encode(replace(record, state=state.reference)),
        "application/json",
        logical_type=CHECKPOINT_TYPE,
    ).reference
    with pytest.raises(CouplingError) as error:
        restore_direct(project, kernel, corrupt)
    assert error.value.code == "COUPLING_CHECKPOINT_STATE"


@pytest.mark.parametrize(
    "node,field,value",
    (
        ("et:supply", "voltage", quantity(6, "volt")),
        ("et:law", "alpha", quantity(0.005, "per_kelvin")),
        ("et:sink", "capacity", quantity(25, "joule_per_kelvin")),
        ("et:temperature", "source_scale", quantity(2, "kelvin")),
        ("et:policy", "evaluation_order", "thermal_first"),
        ("et:policy", "sample_every", 2),
    ),
)
def test_changed_scientific_or_output_policy_cannot_resume(completed, node, field, value):
    project, kernel, _, checkpoint = completed
    edited = changed(project, node, field, value)
    with pytest.raises(CouplingError) as error:
        restore_direct(edited, kernel, checkpoint)
    assert error.value.code == "COUPLING_CHECKPOINT_COMPATIBILITY"


def test_ordered_finite_history_is_not_sufficient_when_a_scheduled_sample_is_missing(completed):
    project, kernel, _, reference = completed
    store = kernel.resource_store
    checkpoint = CODEC.decode(store.read(reference), CoupledCheckpoint)
    prefix = CHANNEL_CODEC.decode(store.read(checkpoint.prefix), ChannelSeries)
    chunk = prefix.chunks[-1]
    data = read_array(
        resolve_computation_resource(store, chunk.resource), (chunk.rows, chunk.columns + 2)
    )
    produced = array_resource("only-endpoint", data[-1:].copy())
    reduced = store.put(
        produced.data,
        produced.media_type,
        tensor=produced.tensor,
        logical_type=produced.logical_type,
    ).reference
    position = TemporalPosition(quantity(2), 2, 1)
    reduced_chunk = replace(chunk, resource=reduced, first=position, last=position, rows=1)
    reduced_prefix = replace(prefix, chunks=(*prefix.chunks[:-1], reduced_chunk))
    root = store.put(
        CHANNEL_CODEC.encode(reduced_prefix), "application/json", logical_type=SERIES_TYPE
    ).reference
    corrupt = store.put(
        CODEC.encode(replace(checkpoint, prefix=root, position=position)),
        "application/json",
        logical_type=CHECKPOINT_TYPE,
    ).reference
    with pytest.raises(CouplingError) as error:
        restore_direct(project, kernel, corrupt)
    assert error.value.code == "COUPLING_CHECKPOINT_HISTORY"


@pytest.mark.parametrize(
    "field,value",
    (
        ("numerical_identity", "different-binary"),
        ("policy_digest", "b" * 64),
        ("next_sample_step", 99),
    ),
)
def test_method_and_cursor_compatibility(completed, field, value):
    project, kernel, _, reference = completed
    store = kernel.resource_store
    checkpoint = CODEC.decode(store.read(reference), CoupledCheckpoint)
    corrupt = store.put(
        CODEC.encode(replace(checkpoint, **{field: value})),
        "application/json",
        logical_type=CHECKPOINT_TYPE,
    ).reference
    with pytest.raises(CouplingError) as error:
        restore_direct(project, kernel, corrupt)
    assert error.value.code in ("COUPLING_CHECKPOINT_COMPATIBILITY", "COUPLING_CHECKPOINT_CURSOR")
