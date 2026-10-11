"""Independent regression for streaming file lifetime through evidence admission."""

from hashlib import sha256

import pytest
from test_backend_lifecycle import _setup

from code_visualizer.application.computation import (
    advance_computation,
    cancel_computation,
    execute_computation,
    start_computation,
)
from code_visualizer.domain.computation import BackendCapabilities, CancelRequest, ProgressEvent
from code_visualizer.domain.evidence import (
    ComputationOutcome,
    EvidenceObservation,
    ObservationEvent,
)
from code_visualizer.domain.values import ResourceReference
from code_visualizer.execution.backends import BackendResult, ProducedResource, ResourceFile
from code_visualizer.generation.transformation import TransformationError
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore


def test_streaming_output_file_is_admitted_before_backend_finalization(tmp_path):
    source = tmp_path / "streamed-output.bin"
    payload = b"large solver output belongs in a resource"
    cleanup = []

    def stream(snapshot, context):
        source.write_bytes(payload)
        try:
            yield ProgressEvent(context.session_id, 0, 0.0)
            yield BackendResult(
                produced_resources=(
                    ProducedResource(
                        "stream-result",
                        media_type="application/octet-stream",
                        semantic_ids=("node",),
                        file=ResourceFile(
                            source.resolve(), len(payload), sha256(payload).hexdigest()
                        ),
                    ),
                )
            )
        finally:
            source.unlink()
            cleanup.append(True)

    kernel, request, _, _ = _setup(stream)
    kernel.resource_store = ResourceStore(tmp_path / "store")
    try:
        evidence = execute_computation(kernel, request)
        assert evidence.outcome is ComputationOutcome.SUCCEEDED
        assert kernel.resource_store.read(evidence.artifacts[0].resource) == payload
        assert cleanup == [True]
        assert not source.exists()
    finally:
        kernel.close()


def test_trailing_update_after_file_output_cannot_publish_success_evidence(tmp_path):
    source = tmp_path / "trailing-output.bin"
    payload = b"terminal resource staged before checking generator termination"
    cleanup = []

    def stream(snapshot, context):
        source.write_bytes(payload)
        try:
            yield BackendResult(
                produced_resources=(
                    ProducedResource(
                        "stream-result",
                        media_type="application/octet-stream",
                        semantic_ids=("node",),
                        file=ResourceFile(
                            source.resolve(), len(payload), sha256(payload).hexdigest()
                        ),
                    ),
                )
            )
            yield ProgressEvent(context.session_id, 1, 1.0)
        finally:
            source.unlink()
            cleanup.append(True)

    kernel, request, _, _ = _setup(stream)
    kernel.resource_store = ResourceStore(tmp_path / "store")
    kernel.evidence_store = EvidenceStore(tmp_path / "store")
    try:
        with pytest.raises(TransformationError) as caught:
            execute_computation(kernel, request)
        assert caught.value.code == "COMPUTATION_BACKEND_PROTOCOL"
        assert kernel.evidence_store.identities() == ()
        assert kernel.runtime.evidence_records() == ()
        assert kernel.runtime.computations() == ()
        assert cleanup == [True]
        assert not source.exists()
    finally:
        kernel.close()


def test_cooperative_cancellation_releases_backend_files_after_acknowledgement(tmp_path):
    source = tmp_path / "cancelled-output.bin"
    cleanup = []

    def stream(snapshot, context):
        source.write_bytes(b"incomplete calculation")
        try:
            yield ProgressEvent(context.session_id, 0, 0.0)
            assert context.cancellation_requested
            yield BackendResult(ComputationOutcome.CANCELLED)
        finally:
            source.unlink()
            cleanup.append(True)

    kernel, request, _, _ = _setup(stream)
    try:
        session = start_computation(kernel, request)
        advance_computation(kernel, session.id)
        assert source.exists()
        cancel_computation(kernel, CancelRequest(session.id))
        evidence = advance_computation(kernel, session.id)
        assert evidence.outcome is ComputationOutcome.CANCELLED
        assert cleanup == [True]
        assert not source.exists()
    finally:
        kernel.close()


@pytest.mark.parametrize("streaming", (False, True))
@pytest.mark.parametrize("resource_state", ("missing", "corrupt", "valid"))
def test_resource_observations_require_verified_contents_before_publication(
    tmp_path, streaming, resource_state
):
    store = ResourceStore(tmp_path / "store")
    reference = ResourceReference("missing-result", "a" * 64)
    if resource_state != "missing":
        reference = store.put(b"measured samples", "application/octet-stream").reference
        if resource_state == "corrupt":
            store.verified_path(reference).write_bytes(b"altered samples!")
    observation = EvidenceObservation("waveform", ("node",), reference)

    def stream(snapshot, context):
        yield ObservationEvent(context.session_id, observation)
        yield BackendResult()

    if streaming:
        kernel, request, _, _ = _setup(stream)
    else:
        kernel, request, _, _ = _setup(
            None,
            BackendCapabilities(),
            execute=lambda _: BackendResult(observations=(observation,)),
        )
    kernel.resource_store = store
    kernel.evidence_store = EvidenceStore(tmp_path / "store")
    try:
        if resource_state == "valid":
            evidence = execute_computation(kernel, request)
            assert evidence.outcome is ComputationOutcome.SUCCEEDED
            assert store.read(evidence.observations[0].value) == b"measured samples"
        else:
            with pytest.raises((ValueError, OSError)):
                execute_computation(kernel, request)
            assert kernel.evidence_store.identities() == ()
            assert kernel.runtime.evidence_records() == ()
            assert kernel.runtime.computations() == ()
    finally:
        kernel.close()


def test_terminal_observation_can_reference_resource_produced_in_same_result(tmp_path):
    payload = b"newly computed waveform"
    reference = (
        ResourceStore(tmp_path / "reference").put(payload, "application/octet-stream").reference
    )
    result = BackendResult(
        observations=(EvidenceObservation("waveform-observation", ("node",), reference),),
        produced_resources=(
            ProducedResource(
                "waveform-artifact",
                data=payload,
                media_type="application/octet-stream",
                semantic_ids=("node",),
            ),
        ),
    )
    kernel, request, _, _ = _setup(None, BackendCapabilities(), execute=lambda _: result)
    kernel.resource_store = ResourceStore(tmp_path / "target")
    with pytest.raises(FileNotFoundError):
        kernel.resource_store.describe(reference)
    try:
        evidence = execute_computation(kernel, request)
        assert evidence.outcome == ComputationOutcome.SUCCEEDED
        assert evidence.observations[0].value == reference == evidence.artifacts[0].resource
        assert kernel.resource_store.read(reference) == payload
    finally:
        kernel.close()
