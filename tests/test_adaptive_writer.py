"""Private buffering and exact checkpoint boundaries before real process qualification."""

from dataclasses import replace

import numpy as np
import pytest
from test_adaptive_domain import change, problem

from code_visualizer.application.adaptive_examples import adaptive_diffusion_project
from code_visualizer.application.computation_publications import seal_resource
from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.transformation import OriginMap
from code_visualizer.execution.backends import PreparedComputation
from code_visualizer.extensions.adaptive_diffusion.checkpoint import (
    CHECKPOINT_TYPE,
    checkpoint_resource,
    decode_checkpoint,
    encode_checkpoint,
    numerical_identity,
    restore,
)
from code_visualizer.extensions.adaptive_diffusion.controller import advance, start
from code_visualizer.extensions.adaptive_diffusion.domain import BACKEND_ID, REPRESENTATION
from code_visualizer.extensions.adaptive_diffusion.history import AdaptiveWriter
from code_visualizer.extensions.adaptive_diffusion.problem import AdaptiveError, definition_digest
from code_visualizer.extensions.adaptive_fields.history import AdaptiveHistory
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.persistence.computation_resources import resolve_computation_resource
from code_visualizer.persistence.resource_store import ResourceStore


def snapshot(project):
    return PreparedComputation(
        project,
        ComputationRequest(
            project.id, project.revision, BACKEND_ID, "1", model_id="adaptive:experiment"
        ),
        REPRESENTATION,
        project.domain_workspace.models[0],
        OriginMap(project.id, project.revision),
        (),
        "b" * 64,
        dependency_models=project.domain_workspace.models[1:],
    )


def flush(writer, source, store):
    for resource in writer.flush():
        seal_resource(source, resource, store, builtin_registry())


def admitted(source, reference, store):
    closure = builtin_registry().resource_closure((reference,), store)
    return replace(
        source,
        resources=tuple(
            resolve_computation_resource(store, ref, file_backed=True) for ref in closure
        ),
    )


def read_history(writer, store):
    return AdaptiveHistory(
        writer.root, lambda ref: resolve_computation_resource(store, ref, file_backed=True)
    )


def test_ack_precedes_checkpoint_and_unsampled_counters_never_leak_into_cancelled_prefix(tmp_path):
    project = change(adaptive_diffusion_project(), "adaptive:policy", "decision_every", 3)
    source, p = snapshot(project), problem(project)
    digest = definition_digest(source)
    state = start(p)
    store = ResourceStore(tmp_path)
    writer = AdaptiveWriter(p, digest, state)
    writer.sample(state)
    pending = writer.flush()
    produced = next(pending)
    assert writer.root is None and writer.acknowledged is None
    with pytest.raises(ValueError, match="acknowledged"):
        checkpoint_resource(p, digest, numerical_identity(), writer, state)
    seal_resource(source, produced, store, builtin_registry())
    with pytest.raises(StopIteration):
        next(pending)
    while state.tick < p.policy.sample_ticks:
        transition = advance(p, state, p.policy.sample_ticks)
        writer.accept(transition)
        state = transition.state
    writer.sample(state)
    sampled = state
    transition = advance(p, state, 2 * p.policy.sample_ticks)
    writer.accept(transition)
    assert transition.state.step == 3 and transition.state.ages != sampled.ages
    with pytest.raises(ValueError, match="coherent"):
        next(writer.flush())
    state = writer.discard_unsampled()
    assert state is sampled
    flush(writer, source, store)
    produced = checkpoint_resource(p, digest, numerical_identity(), writer, state)
    checkpoint = seal_resource(source, produced, store, builtin_registry()).resource
    previous, restored = restore(
        admitted(source, checkpoint, store), checkpoint, p, digest, numerical_identity()
    )
    assert restored.quiet == sampled.quiet and restored.ages == sampled.ages
    assert restored.tick == sampled.tick and previous.sample_count == 2
    np.testing.assert_array_equal(restored.values, sampled.values)
    previous.close()


def test_changed_support_chunks_and_full_controller_restart_match_uninterrupted_bytes(tmp_path):
    project = adaptive_diffusion_project()
    source, p = snapshot(project), problem(project)
    digest, implementation = definition_digest(source), numerical_identity()
    state = start(p)
    store = ResourceStore(tmp_path)
    writer = AdaptiveWriter(p, digest, state)
    writer.sample(state)
    flush(writer, source, store)
    checkpoint = None
    for tick in range(p.policy.sample_ticks, p.policy.final_tick + 1, p.policy.sample_ticks):
        while state.tick < tick:
            transition = advance(p, state, tick)
            writer.accept(transition)
            state = transition.state
        writer.sample(state)
        if writer.full or tick % p.policy.checkpoint_ticks == 0 or tick == p.policy.final_tick:
            flush(writer, source, store)
        if tick == p.policy.checkpoint_ticks:
            checkpoint = seal_resource(
                source,
                checkpoint_resource(p, digest, implementation, writer, state),
                store,
                builtin_registry(),
            ).resource
    assert checkpoint is not None and state.epoch > 0
    original = read_history(writer, store)
    previous, resumed = restore(
        admitted(source, checkpoint, store), checkpoint, p, digest, implementation
    )
    continuation = AdaptiveWriter(p, digest, resumed, previous)
    previous.close()
    for tick in range(
        resumed.tick + p.policy.sample_ticks, p.policy.final_tick + 1, p.policy.sample_ticks
    ):
        while resumed.tick < tick:
            transition = advance(p, resumed, tick)
            continuation.accept(transition)
            resumed = transition.state
        continuation.sample(resumed)
        if (
            continuation.full
            or tick % p.policy.checkpoint_ticks == 0
            or tick == p.policy.final_tick
        ):
            flush(continuation, source, store)
    result = read_history(continuation, store)
    assert original.root == result.root
    assert (resumed.quiet, resumed.ages, resumed.work) == (state.quiet, state.ages, state.work)
    np.testing.assert_array_equal(resumed.values, state.values)
    original.close()
    result.close()


@pytest.mark.parametrize("fault", ("source", "method", "schedule", "counters", "state", "work"))
def test_checkpoint_rejects_incompatible_or_incomplete_accepted_state(tmp_path, fault):
    from code_visualizer.extensions.fields.arrays import array_resource

    project = adaptive_diffusion_project()
    source, p = snapshot(project), problem(project)
    digest, implementation = definition_digest(source), numerical_identity()
    state = start(p)
    writer = AdaptiveWriter(p, digest, state)
    store = ResourceStore(tmp_path)
    writer.sample(state)
    flush(writer, source, store)
    while state.tick < p.policy.sample_ticks:
        transition = advance(p, state, p.policy.sample_ticks)
        writer.accept(transition)
        state = transition.state
    writer.sample(state)
    flush(writer, source, store)
    resource = checkpoint_resource(p, digest, implementation, writer, state)
    good = seal_resource(source, resource, store, builtin_registry()).resource
    data = decode_checkpoint(store.read(good))
    expected_code = "ADAPTIVE_CHECKPOINT_COMPATIBILITY"
    if fault == "source":
        data = replace(data, source_digest="c" * 64)
    elif fault == "method":
        data = replace(data, numerical_identity="other-method")
    elif fault == "schedule":
        data = replace(data, next_sample_tick=data.next_sample_tick + 1)
        expected_code = "ADAPTIVE_CHECKPOINT_CURSOR"
    elif fault == "work":
        data = replace(data, indicator_visits=data.indicator_visits + 1)
        expected_code = "ADAPTIVE_CHECKPOINT_DECISIONS"
    else:
        values = (
            state.values + 0.1 if fault == "state" else np.ones((len(state.mesh.cells), 2)) * 1001
        )
        produced = array_resource("invalid", values)
        wrong = store.put(
            produced.data,
            produced.media_type,
            tensor=produced.tensor,
            logical_type=produced.logical_type,
        ).reference
        data = replace(data, **{fault: wrong})
        expected_code = "ADAPTIVE_CHECKPOINT_STATE"
    bad = store.put(
        encode_checkpoint(data), "application/json", logical_type=CHECKPOINT_TYPE
    ).reference
    with pytest.raises(AdaptiveError) as caught:
        restore(admitted(source, bad, store), bad, p, digest, implementation)
    assert caught.value.code == expected_code
    assert caught.value.object_id == p.policy_id
