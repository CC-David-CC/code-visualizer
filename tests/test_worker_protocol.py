"""Workers exchange a closed bounded vocabulary, never Python callbacks or paths."""

from dataclasses import replace

import pytest
from test_computation_publications import PAYLOAD, _seal
from test_computation_publications import publication_context as publication_context

from code_visualizer.domain.boundaries import MAX_PORTABLE_ENVELOPE_BYTES
from code_visualizer.domain.computation import CancelRequest, ProgressEvent
from code_visualizer.domain.evidence import (
    ComputationEvidence,
    ComputationOutcome,
    EvidenceDiagnostic,
    EvidenceObservation,
    ObservationEvent,
)
from code_visualizer.domain.resource_transfer import (
    ResourceTransferAbort,
    ResourceTransferChunk,
    ResourceTransferFinish,
    ResourceTransferStart,
)
from code_visualizer.domain.worker import (
    WorkerCompletionVerified,
    WorkerEvidenceProposal,
    WorkerExecutionRequest,
    WorkerFailure,
    WorkerPreparationRequest,
    WorkerPrepared,
    WorkerPublicationOffer,
    WorkerResourceEvent,
    WorkerTerminalSecured,
)
from code_visualizer.protocol.v1 import worker_pb2 as wire
from code_visualizer.protocol.worker import (
    worker_control_from_bytes,
    worker_control_to_bytes,
    worker_event_from_bytes,
    worker_event_to_bytes,
    worker_request_from_proto,
    worker_request_to_proto,
)


def test_closed_worker_controls_roundtrip_expected_backend_contract(publication_context):
    snapshot, plan, _, _, _, backend = publication_context
    published = _seal(publication_context)
    controls = (
        WorkerPreparationRequest("session", plan.model, snapshot.request, backend.definition),
        WorkerExecutionRequest("session", plan, backend.definition),
        WorkerExecutionRequest("session", plan, backend.definition, plan.model),
        CancelRequest("session", "user request"),
        published,
        WorkerTerminalSecured("session", "evidence:proposal"),
    )
    for control in controls:
        encoded = worker_control_to_bytes(control)
        assert worker_control_from_bytes(encoded) == control
        assert worker_control_to_bytes(worker_control_from_bytes(encoded)) == encoded
    for request in controls[:3]:
        assert worker_request_from_proto(worker_request_to_proto(request)) == request


def test_closed_worker_events_roundtrip_resources_publications_and_terminal_handshake(
    publication_context,
):
    _, plan, resources, _, _, _ = publication_context
    published = _seal(publication_context)
    artifact = published.publication.artifact
    evidence = ComputationEvidence(
        "evidence:proposal",
        published.publication.provenance,
        ComputationOutcome.SUCCEEDED,
        artifacts=(artifact,),
    )
    events = (
        WorkerPrepared("session", plan),
        WorkerPrepared("session", plan, plan.model),
        ProgressEvent("session", 0, 0.5, 1.0, "Working"),
        ObservationEvent("session", EvidenceObservation("value", ("node",), 7, sequence=1)),
        WorkerPublicationOffer("session", 2, artifact),
        WorkerEvidenceProposal("session", evidence),
        WorkerCompletionVerified("session"),
        WorkerFailure("session", EvidenceDiagnostic("FAILED", "Failure", ("node",))),
        *(
            WorkerResourceEvent("session", frame)
            for frame in (
                ResourceTransferStart("transfer", resources.describe(artifact.resource)),
                ResourceTransferChunk("transfer", 0, PAYLOAD),
                ResourceTransferFinish("transfer"),
                ResourceTransferAbort("transfer", "cancelled"),
            )
        ),
    )
    for event in events:
        encoded = worker_event_to_bytes(event)
        assert worker_event_from_bytes(encoded) == event
        assert worker_event_to_bytes(worker_event_from_bytes(encoded)) == encoded


@pytest.mark.parametrize("family", ("control", "event"))
def test_worker_decoders_reject_empty_unknown_versions_and_fields(family):
    message, decode = (
        (wire.WorkerControl, worker_control_from_bytes)
        if family == "control"
        else (wire.WorkerEvent, worker_event_from_bytes)
    )
    with pytest.raises(ValueError, match="variant"):
        decode(message(schema_version=1).SerializeToString())
    with pytest.raises(ValueError, match="version"):
        decode(message(schema_version=2).SerializeToString())
    with pytest.raises(ValueError, match="fields"):
        decode(message(schema_version=1).SerializeToString() + b"\x98\x06\x01")
    with pytest.raises(ValueError, match="Malformed"):
        decode(b"\x80")
    with pytest.raises(ValueError, match="2 MiB"):
        decode(b"x" * (MAX_PORTABLE_ENVELOPE_BYTES + 1))


@pytest.mark.parametrize("name", ("project", "request", "backend"))
def test_worker_preparation_requires_all_explicit_fields(publication_context, name):
    snapshot, plan, _, _, _, backend = publication_context
    value = worker_request_to_proto(
        WorkerPreparationRequest("session", plan.model, snapshot.request, backend.definition)
    )
    value.prepare.ClearField(name)
    with pytest.raises(ValueError, match="present"):
        worker_request_from_proto(value)


def test_worker_refuses_untyped_payloads_wrong_contract_and_oversized_events(publication_context):
    snapshot, plan, _, _, _, backend = publication_context
    with pytest.raises(ValueError, match="closed"):
        worker_control_to_bytes({"callback": "os.system"})
    with pytest.raises(ValueError, match="closed"):
        worker_event_to_bytes(lambda: None)
    with pytest.raises(ValueError, match="expected backend"):
        WorkerPreparationRequest(
            "session", plan.model, snapshot.request, replace(backend.definition, version="99")
        )
    with pytest.raises(ValueError, match="representation"):
        WorkerExecutionRequest(
            "session",
            plan,
            replace(
                backend.definition, input_representation=replace(plan.representation, version="99")
            ),
        )
    with pytest.raises(ValueError, match="2 MiB"):
        worker_event_to_bytes(
            WorkerFailure(
                "session", EvidenceDiagnostic("FAILED", "x" * MAX_PORTABLE_ENVELOPE_BYTES)
            )
        )
