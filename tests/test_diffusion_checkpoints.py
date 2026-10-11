"""Explicit numerical restart through fresh ordinary hosts and portable plans."""

from contextlib import contextmanager
from dataclasses import replace
from time import monotonic, sleep

import numpy as np
import pytest

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.computation import (
    execute_computation,
    export_computation_plan,
    run_computation_plan,
    start_computation,
)
from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.field_examples import diffusion_project
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.domain.computation import (
    CancelRequest,
    ComputationParameter,
    ComputationRequest,
)
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.extensions.diffusion.domain import BACKEND_ID, quantity
from code_visualizer.extensions.fields.codec import decode_record, encode_record
from code_visualizer.extensions.fields.history import FieldHistory
from code_visualizer.extensions.fields.records import (
    CHECKPOINT_TYPE,
    SERIES_TYPE,
    DiffusionCheckpoint,
)
from code_visualizer.persistence.computation_resources import resolve_computation_resource
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore


@contextmanager
def host(project, path):
    service = ComputationService()
    kernel = ProjectKernel(
        ProjectAuthority(project),
        computations=service,
        resource_store=ResourceStore(path),
        evidence_store=EvidenceStore(path),
    )
    try:
        yield kernel
    finally:
        kernel.close()
        service.close()


def request(project, checkpoint=None):
    return ComputationRequest(
        project.id,
        project.revision,
        BACKEND_ID,
        "1",
        model_id="diffusion:experiment",
        configuration=(ComputationParameter("checkpoint", checkpoint),) if checkpoint else (),
    )


def latest(evidence, store, kind):
    return [
        item.resource
        for item in evidence.artifacts
        if store.describe(item.resource).logical_type == kind
    ][-1]


def history(root, store):
    return FieldHistory(
        root, lambda ref: resolve_computation_resource(store, ref, file_backed=True)
    )


@pytest.fixture(scope="module")
def completed(tmp_path_factory):
    project = diffusion_project(nodes=33, steps=512, sample_every=16, checkpoint_every=256)
    with host(project, tmp_path_factory.mktemp("completed-diffusion")) as kernel:
        result = execute_computation(kernel, request(project))
        assert result.outcome is ComputationOutcome.SUCCEEDED, result.diagnostics
        checkpoint = next(item.resource for item in result.artifacts if item.id == "checkpoint:256")
        yield project, kernel, checkpoint


@pytest.mark.parametrize("corruption", ("shape", "values", "unit", "boundary"))
def test_portable_resume_rejects_state_that_does_not_match_accepted_prefix(completed, corruption):
    from code_visualizer.extensions.fields.arrays import array_resource, read_array

    project, kernel, reference = completed
    checkpoint = decode_record(kernel.resource_store.read(reference), DiffusionCheckpoint)
    state = read_array(
        resolve_computation_resource(kernel.resource_store, checkpoint.state), (33,)
    ).copy()
    unit = quantity(1.0, "kelvin").unit
    if corruption == "shape":
        state = state[:-1]
    elif corruption == "unit":
        unit = quantity(1.0, "second").unit
    elif corruption == "boundary":
        state[0] = 1.0
    else:
        state[16] += 1.0
    resource = array_resource("invalid-state", state, unit=unit)
    changed_state = kernel.resource_store.put(
        resource.data,
        resource.media_type,
        tensor=resource.tensor,
        logical_type=resource.logical_type,
    )
    changed = replace(checkpoint, state=changed_state.reference)
    bad = kernel.resource_store.put(
        encode_record(changed), "application/json", logical_type=CHECKPOINT_TYPE
    ).reference
    result = execute_computation(kernel, request(project, bad))
    assert result.outcome is ComputationOutcome.FAILED and not result.artifacts


@pytest.mark.parametrize(
    "field,value",
    (
        ("compatibility_digest", "0" * 64),
        ("policy_digest", "1" * 64),
        ("numerical_identity", "different-library"),
        ("next_sample_step", 900),
        ("next_checkpoint_step", 901),
        ("position", None),
    ),
)
def test_portable_resume_rejects_incompatible_numerical_checkpoint(completed, field, value):
    project, kernel, reference = completed
    checkpoint = decode_record(kernel.resource_store.read(reference), DiffusionCheckpoint)
    if field == "position":
        value = replace(checkpoint.position, time=quantity(0.6))
    changed = replace(checkpoint, **{field: value})
    bad = kernel.resource_store.put(
        encode_record(changed), "application/json", logical_type=CHECKPOINT_TYPE
    ).reference
    plan = export_computation_plan(kernel, request(project, bad))
    result = run_computation_plan(
        plan, kernel.extensions, kernel.resource_store, kernel.evidence_store
    )
    assert result.outcome is ComputationOutcome.FAILED
    assert "CHECKPOINT" in result.diagnostics[0].message
    assert not result.artifacts


@pytest.mark.parametrize("corruption", ("unscheduled", "omitted"))
def test_resume_requires_the_complete_authored_sample_schedule(completed, corruption):
    from code_visualizer.extensions.fields.arrays import array_resource, read_array
    from code_visualizer.extensions.fields.records import FieldSeries

    project, kernel, reference = completed
    store = kernel.resource_store
    checkpoint = decode_record(store.read(reference), DiffusionCheckpoint)
    prefix = decode_record(store.read(checkpoint.prefix), FieldSeries)
    assert prefix.prefix is None
    chunk = prefix.chunks[-1]
    assert chunk.rows > 3
    samples = read_array(
        resolve_computation_resource(store, chunk.resource), (chunk.rows, chunk.nodes + 2)
    ).copy()
    position = checkpoint.position
    if corruption == "unscheduled":
        samples[1, 0] += 1  # Ordered and physically consistent, but outside the policy.
        samples[1, 1] = samples[1, 0] / 512
    else:
        samples = np.delete(samples, 1, axis=0)
        position = replace(position, sample=position.sample - 1)
    descriptor = store.describe(chunk.resource)
    output = array_resource("changed-history", samples, unit=descriptor.tensor.unit)
    altered = store.put(
        output.data, output.media_type, tensor=output.tensor, logical_type=output.logical_type
    ).reference
    changed_prefix = replace(
        prefix,
        chunks=(
            *prefix.chunks[:-1],
            replace(chunk, resource=altered, rows=len(samples), last=position),
        ),
    )
    prefix_ref = store.put(
        encode_record(changed_prefix), "application/json", logical_type=SERIES_TYPE
    ).reference
    changed = replace(checkpoint, prefix=prefix_ref, position=position)
    bad = store.put(
        encode_record(changed), "application/json", logical_type=CHECKPOINT_TYPE
    ).reference
    plan = export_computation_plan(kernel, request(project, bad))
    result = run_computation_plan(plan, kernel.extensions, store, kernel.evidence_store)
    assert result.outcome is ComputationOutcome.FAILED
    assert "CHECKPOINT_HISTORY" in result.diagnostics[0].message
    assert not result.artifacts


def test_resume_keeps_noncoincident_sampling_checkpoint_and_final_steps(tmp_path):
    project = diffusion_project(nodes=17, steps=511, sample_every=30, checkpoint_every=128)
    with host(project, tmp_path) as kernel:
        original = execute_computation(kernel, request(project))
        assert original.outcome is ComputationOutcome.SUCCEEDED, original.diagnostics
        reference = next(a.resource for a in original.artifacts if a.id == "checkpoint:256")
        resumed = execute_computation(kernel, request(project, reference))
        assert resumed.outcome is ComputationOutcome.SUCCEEDED, resumed.diagnostics
        expected_steps = sorted({0, 511, *range(30, 512, 30), *range(128, 512, 128)})
        original_history = history(
            latest(original, kernel.resource_store, SERIES_TYPE), kernel.resource_store
        )
        resumed_history = history(
            latest(resumed, kernel.resource_store, SERIES_TYPE), kernel.resource_store
        )
        try:
            assert (
                original_history.sample_count == resumed_history.sample_count == len(expected_steps)
            )
            for index, step in enumerate(expected_steps):
                before, after = original_history.slice(index), resumed_history.slice(index)
                assert before.position == after.position
                assert after.position.step == step
                np.testing.assert_array_equal(before.values, after.values)
        finally:
            original_history.close()
            resumed_history.close()


def test_cancelled_prefix_resumes_in_fresh_host_with_exact_sample_coordinates(tmp_path):
    project = diffusion_project(
        nodes=65, steps=8192, sample_every=64, checkpoint_every=512, preview_every=7
    )
    producer_path, consumer_path = tmp_path / "producer", tmp_path / "fresh"
    with host(project, producer_path) as kernel:
        session = start_computation(kernel, request(project))
        deadline = monotonic() + 30
        while monotonic() < deadline:
            view = kernel.computations.job(session.id).view
            if (
                view.progress is not None
                and view.progress.completed
                >= project.domain_workspace.models[0]
                .node("diffusion:policy")
                .property("code_visualizer.diffusion:TimePolicy:final_time")
                .magnitude
                * 700
                / 8192
            ):
                break
            assert not kernel.computations.job(session.id).done.is_set()
            sleep(0.005)
        else:
            pytest.fail("The real solver did not report progress within 30 seconds")
        kernel.computations.cancel(CancelRequest(session.id))
        cancelled = kernel.computations.wait(session.id)
        assert cancelled.outcome is ComputationOutcome.CANCELLED, cancelled.diagnostics
        checkpoint = latest(cancelled, kernel.resource_store, CHECKPOINT_TYPE)
        record = decode_record(kernel.resource_store.read(checkpoint), DiffusionCheckpoint)
        assert 0 < record.position.step < 8192
        assert record.position.step % 64 == 0
        copied = ResourceStore(consumer_path)
        for reference in kernel.extensions.resource_closure((checkpoint,), kernel.resource_store):
            copied.import_reference(kernel.resource_store, reference)
        prefix = kernel.resource_store.read(record.prefix)
    # Only retained resource bytes cross this boundary; the producer host is closed.
    with host(project, consumer_path) as kernel:
        resumed = execute_computation(kernel, request(project, checkpoint))
        assert resumed.outcome is ComputationOutcome.SUCCEEDED, resumed.diagnostics
        assert kernel.resource_store.read(record.prefix) == prefix
        resumed_history = history(
            latest(resumed, kernel.resource_store, SERIES_TYPE), kernel.resource_store
        )
        actual = [resumed_history.slice(i) for i in range(resumed_history.sample_count)]
        resumed_history.close()
        uninterrupted = execute_computation(kernel, request(project))
        assert uninterrupted.outcome is ComputationOutcome.SUCCEEDED, uninterrupted.diagnostics
        complete = history(
            latest(uninterrupted, kernel.resource_store, SERIES_TYPE), kernel.resource_store
        )
        assert complete.sample_count == len(actual) == 129
        for sample in actual:
            expected = complete.slice(sample.position.sample)
            assert sample.position == expected.position
            np.testing.assert_allclose(sample.values, expected.values, rtol=0, atol=1e-9)
        complete.close()
