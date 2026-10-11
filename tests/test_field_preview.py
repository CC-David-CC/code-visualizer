"""P5-05: physical preview frames use the existing bounded worker/runtime plane."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_backend_lifecycle import _setup
from test_field_contracts import q, ref

from code_visualizer.application.runtime_sessions import RuntimeSessionRegistry
from code_visualizer.domain.computation import ProgressEvent
from code_visualizer.domain.values import TensorDType, TensorValue
from code_visualizer.execution.backends import BackendResult, PreviewContract
from code_visualizer.execution.lifecycle import BackendExecution
from code_visualizer.extensions.fields.preview import FieldPreview, field_preview, validate_preview
from code_visualizer.extensions.fields.records import PREVIEW_TYPE, TemporalPosition
from code_visualizer.protocol.preview import preview_from_proto, preview_to_proto
from code_visualizer.protocol.worker import worker_event_from_bytes, worker_event_to_bytes


def preview():
    return FieldPreview(
        ref("interpretation"),
        TemporalPosition(q(0), 0, 0),
        TemporalPosition(q(0.01), 1, 1),
        TensorValue(TensorDType.INT64, (3,), (0, 5, 10)),
        TensorValue(TensorDType.FLOAT64, (3,), (0.0, 1.0, 0.0)),
        TensorValue(TensorDType.FLOAT64, (3,), (0.0, 0.99, 0.0)),
    )


def test_preview_wire_roundtrip_version_rejection_and_exact_frame():
    event = preview().event("run", 2, "a" * 64, "field")
    encoded = worker_event_to_bytes(event)
    fixture = json.loads((Path(__file__).parent / "fixtures/field_contracts_v1.json").read_text())
    assert encoded.hex() == fixture["preview_hex"]
    assert worker_event_from_bytes(encoded) == event
    assert worker_event_to_bytes(worker_event_from_bytes(encoded)) == encoded
    assert field_preview(event) == preview()
    wire = preview_to_proto(event)
    wire.schema_version = 2
    with pytest.raises(ValueError):
        preview_from_proto(wire)
    with pytest.raises(ValueError, match="missing/extra"):
        field_preview(replace(event, values=event.values[:-1]))
    with pytest.raises(ValueError, match="next step"):
        replace(preview(), candidate=TemporalPosition(q(0.01), 2, 1))
    with pytest.raises(ValueError, match="support"):
        replace(preview(), trial_values=TensorValue(TensorDType.FLOAT64, (1,), (1.0,)))


def test_preview_bursts_are_coalesced_and_never_become_observations_or_accepted_history():
    kernel, _, backend, snapshot = _setup()

    def stream(snapshot, context):
        yield ProgressEvent(context.session_id, 0, 0.0, 1.0)
        for sequence in range(1, 501):
            yield preview().event(context.session_id, sequence, snapshot.input_digest, "node")
        yield BackendResult()

    backend = replace(
        backend, stream=stream, preview=PreviewContract(PREVIEW_TYPE, validate_preview)
    )
    execution = BackendExecution("run", backend, snapshot)
    runtime = RuntimeSessionRegistry(project_id=snapshot.request.project_id)
    runtime.bind_computation(execution)
    runtime.record_computation_update(execution.advance())
    baseline = runtime.history("run")
    for _ in range(500):
        state = runtime.record_computation_update(execution.advance())
    assert state.preview.sequence == 500
    assert state.progress.sequence == 0
    assert state.active_ids == ()
    assert runtime.history("run") == baseline
    result = execution.advance()
    assert result.observations == result.artifacts == result.produced_resources == ()
    execution.verify_completion()
    kernel.computations.close()


@pytest.mark.parametrize(
    "changes", [{"input_digest": "b" * 64}, {"semantic_ids": ("foreign",)}, {"sequence": 0}]
)
def test_preview_rejects_other_sources_origins_and_stale_transport_sequences(changes):
    kernel, _, backend, snapshot = _setup()
    backend = replace(backend, preview=PreviewContract(PREVIEW_TYPE, validate_preview))
    execution = BackendExecution("run", backend, snapshot)
    execution.advance()
    event = preview().event("run", 1, snapshot.input_digest, "node")
    with pytest.raises(ValueError):
        execution.accept(replace(event, **changes))
    kernel.computations.close()
