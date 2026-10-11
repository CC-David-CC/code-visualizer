"""A damaged complete native checkpoint cannot be treated as a new random epoch."""

from dataclasses import replace
from math import ceil

import numpy as np
import pytest
from fixtures.gas_project import short_project
from test_hybrid_gas_computation import host, request, resources
from test_hybrid_gas_particle import WINDOWS

from code_visualizer.application.computation import _resolve_resources, execute_computation
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.domain.values import ResourceReference
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.fields.arrays import array_resource, read_array
from code_visualizer.extensions.hybrid_gas.calibration import transport
from code_visualizer.extensions.hybrid_gas.checkpoint import method_digest, restore
from code_visualizer.extensions.hybrid_gas.history import record
from code_visualizer.extensions.hybrid_gas.problem import (
    GasError,
    definition_digest,
    derive_problem,
)
from code_visualizer.extensions.hybrid_gas.records import (
    CHECKPOINT_TYPE,
    CODEC,
    TAPE_TYPE,
    GasCheckpoint,
    GasTape,
    TapeChunk,
)
from code_visualizer.generation.computation import prepare_computation
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.computation_resources import resolve_computation_resource
from code_visualizer.persistence.resource_store import ResourceStore


@pytest.fixture(scope="module")
def completed(tmp_path_factory):
    root = tmp_path_factory.mktemp("gas-recovery")
    project = short_project()
    with host(project, root) as kernel:
        evidence = execute_computation(kernel, request(project))
        assert evidence.outcome is ComputationOutcome.SUCCEEDED, evidence.diagnostics
        checkpoint = resources(evidence, kernel.resource_store, CHECKPOINT_TYPE)[1]
    return project, root, checkpoint


def save_array(store, values):
    output = array_resource("corrupt-input-test", values)
    return store.put(
        output.data, output.media_type, tensor=output.tensor, logical_type=output.logical_type
    ).reference


def save_record(store, value, kind):
    return store.put(CODEC.encode(value), "application/json", logical_type=kind).reference


@WINDOWS
@pytest.mark.parametrize(
    "corruption,code",
    [
        ("method", "GAS_CHECKPOINT_COMPATIBILITY"),
        ("state", "GAS_CHECKPOINT_HISTORY"),
        ("native", "GAS_CHECKPOINT_STATE"),
        ("tape", "GAS_CHECKPOINT_TAPE"),
        ("controller", "GAS_CHECKPOINT_CONTROLLER"),
    ],
)
def test_modified_checkpoint_fails_before_continuation(completed, corruption, code):
    from dataclasses import asdict
    from hashlib import sha256

    project, root, checkpoint = completed
    store, registry = ResourceStore(root), builtin_registry()

    def resolve(ref):
        return resolve_computation_resource(store, ref, file_backed=True)

    saved = record(resolve, checkpoint, GasCheckpoint, CHECKPOINT_TYPE)
    original = store.read(checkpoint)
    if corruption == "method":
        damaged = replace(saved, method_digest="e" * 64)
    elif corruption == "state":
        q = read_array(resolve(saved.state), (64, 5)).copy()
        q[0, 1] += 0.1
        damaged = replace(saved, state=save_array(store, q))
    elif corruption == "native":
        state = read_array(resolve(saved.native), (saved.native_length,)).copy()
        state[200] = np.nextafter(state[200], np.inf)
        damaged = replace(saved, native=save_array(store, state))
    elif corruption == "tape":
        tape = record(resolve, saved.tape, GasTape, TAPE_TYPE)
        chunk = tape.chunks[0]
        values = read_array(resolve(chunk.resource), (chunk.rows, 12)).copy()
        values[0, 2] *= 1.01
        tape = replace(
            tape, chunks=(replace(chunk, resource=save_array(store, values)), *tape.chunks[1:])
        )
        damaged = replace(saved, tape=save_record(store, tape, TAPE_TYPE))
    else:
        damaged = replace(saved, model=replace(saved.model, switches=saved.model.switches + 1))
    changed = save_record(store, damaged, CHECKPOINT_TYPE)
    snapshot = _resolve_resources(
        store, prepare_computation(project, request(project, changed), registry), registry
    )
    p = derive_problem(project, snapshot.value)
    law = transport(snapshot, p.calibration).law
    law_digest = sha256(canonical_data_bytes(asdict(law))).hexdigest()
    sequence = iter(range(10000))
    with pytest.raises(GasError) as caught:
        tuple(
            restore(
                snapshot,
                changed,
                p,
                law,
                definition_digest(snapshot),
                method_digest(),
                law_digest,
                "reconstruction-test",
                lambda: False,
                lambda: next(sequence),
            )
        )
    assert caught.value.code == code
    assert store.read(checkpoint) == original


def test_input_tape_covers_the_declared_one_tick_maximum_without_larger_resources():
    count = 400000
    ref = ResourceReference("bounded-tape", "a" * 64)
    chunks = tuple(TapeChunk(ref, min(4096, count - start)) for start in range(0, count, 4096))
    tape = GasTape("b" * 64, chunks)
    assert len(chunks) == ceil(count / 4096) <= 128
    assert max(chunk.rows for chunk in chunks) * 12 * 8 + 128 < 4 * 1024 * 1024
    assert CODEC.decode(CODEC.encode(tape), GasTape) == tape
    with pytest.raises(ValueError):
        replace(tape, chunks=(*chunks, TapeChunk(ref, 1)))
