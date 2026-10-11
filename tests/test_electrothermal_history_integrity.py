"""Old samples are evidence too; cached bytes are not a worker transfer."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_electrothermal_checkpoints import completed as completed
from test_electrothermal_checkpoints import restore_direct

from code_visualizer.application.computation_process import _Resources
from code_visualizer.domain.worker import WorkerResourceEvent
from code_visualizer.extensions.channels.codec import CODEC as CHANNEL_CODEC
from code_visualizer.extensions.channels.records import SERIES_TYPE, ChannelSeries
from code_visualizer.extensions.electrothermal.checkpoint import (
    CHECKPOINT_TYPE,
    CODEC,
    CoupledCheckpoint,
)
from code_visualizer.extensions.electrothermal.problem import CouplingError
from code_visualizer.extensions.fields.arrays import array_resource, read_array
from code_visualizer.persistence.computation_resources import resolve_computation_resource
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.resource_transfer import resource_transfer_frames


@pytest.mark.parametrize("channel", range(17))
def test_contradictory_earlier_row_is_rejected_even_with_matching_restart_state(completed, channel):
    project, kernel, _, reference = completed
    store = kernel.resource_store
    checkpoint = CODEC.decode(store.read(reference), CoupledCheckpoint)
    prefix = CHANNEL_CODEC.decode(store.read(checkpoint.prefix), ChannelSeries)
    chunk = prefix.chunks[-1]
    data = read_array(
        resolve_computation_resource(store, chunk.resource), (chunk.rows, chunk.columns + 2)
    ).copy()
    assert data[0, 0] == 1 and data[-1, 0] == 2
    data[0, channel + 2] += 1
    output = array_resource("contradictory-prefix", data)
    array = store.put(
        output.data, output.media_type, tensor=output.tensor, logical_type=output.logical_type
    ).reference
    root = store.put(
        CHANNEL_CODEC.encode(
            replace(prefix, chunks=(*prefix.chunks[:-1], replace(chunk, resource=array)))
        ),
        "application/json",
        logical_type=SERIES_TYPE,
    ).reference
    corrupt = store.put(
        CODEC.encode(replace(checkpoint, prefix=root)),
        "application/json",
        logical_type=CHECKPOINT_TYPE,
    ).reference
    with pytest.raises(CouplingError) as error:
        restore_direct(project, kernel, corrupt)
    assert error.value.code == "COUPLING_CHECKPOINT_HISTORY"


@pytest.mark.parametrize("cached", (False, True))
def test_coupled_checkpoint_requires_its_complete_worker_transfer(completed, tmp_path, cached):
    _, kernel, _, root = completed
    source, registry = kernel.resource_store, kernel.extensions
    closure = registry.resource_closure((root,), source)
    assert closure[-1] == root and len(closure) > 4
    destination = ResourceStore(tmp_path / "destination")
    if cached:
        for reference in closure[:-1]:
            destination.import_reference(source, reference)
    transfers = _Resources(destination, SimpleNamespace(registry=registry))
    try:
        for frame in resource_transfer_frames(source, root, "root"):
            transfers.accept(WorkerResourceEvent("run", frame))
        with pytest.raises(ValueError, match="omitted a complete resource transfer"):
            transfers.claim_transferred((root,))
        assert not transfers.claimed
        for reference in closure[:-1]:
            for frame in resource_transfer_frames(source, reference, reference.id):
                transfers.accept(WorkerResourceEvent("run", frame))
        transfers.claim_transferred((root,))
        transfers.complete((root,))
        assert registry.resource_closure((root,), destination) == closure
    finally:
        transfers.close()
