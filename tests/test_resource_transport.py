"""Portable resources stream independently of small evidence metadata envelopes."""

from dataclasses import replace

import pytest
from computation_fixtures import InProcessTestKernel

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.computation import execute_computation, export_computation_plan
from code_visualizer.application.worker_transport import (
    export_resource_stream,
    import_resource_stream,
    receive_plan_resources,
    run_streamed_computation_plan,
)
from code_visualizer.automation.websocket import MAX_RPC_MESSAGE_BYTES
from code_visualizer.domain.boundaries import (
    MAX_PORTABLE_ENVELOPE_BYTES,
    MAX_RESOURCE_CHUNK_BYTES,
)
from code_visualizer.domain.computation import BackendDefinition, ComputationRequest
from code_visualizer.domain.evidence import (
    ComputationEvidence,
    ComputationOutcome,
    EvidenceDiagnostic,
    EvidenceObservation,
    EvidenceProvenance,
)
from code_visualizer.domain.intentional import (
    ConceptDefinition,
    DomainModel,
    DomainSchema,
    DomainWorkspace,
    IntentionalNode,
)
from code_visualizer.domain.project import Project
from code_visualizer.domain.resource_transfer import (
    ResourceTransferAbort,
    ResourceTransferChunk,
    ResourceTransferFinish,
    ResourceTransferStart,
)
from code_visualizer.domain.transformation import OriginMap, Representation
from code_visualizer.domain.values import TensorDType, TensorValue
from code_visualizer.execution.backends import (
    BackendResult,
    ProducedResource,
    RegisteredBackend,
    ResourceFile,
)
from code_visualizer.extensions.builtin import (
    computation_bundle,
    intentional_bundle,
    program_bundle,
)
from code_visualizer.extensions.registry import DomainExtensionBundle, DomainExtensionRegistry
from code_visualizer.persistence import resource_store
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.evidence import evidence_content_hash, evidence_to_data
from code_visualizer.persistence.evidence_store import (
    MAX_EVIDENCE_BYTES,
    EvidenceStore,
    validate_portable_evidence,
)
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.resource_transfer import (
    ResourceTransferReceiver,
    resource_transfer_frames,
)
from code_visualizer.protocol.computation import computation_plan_to_proto
from code_visualizer.protocol.evidence import evidence_from_proto, evidence_to_proto
from code_visualizer.protocol.resource_transfer import resource_frame_to_proto
from code_visualizer.protocol.v1 import evidence_pb2
from code_visualizer.protocol.validation import MAX_MESSAGE_BYTES, ProtocolBoundaryError


def _identified(record):
    return replace(record, id="evidence:" + evidence_content_hash(record))


def _evidence(*, observations=(), diagnostics=()):
    return _identified(
        ComputationEvidence(
            "pending",
            EvidenceProvenance(
                "project",
                0,
                None,
                "org.example.transport.backend",
                "1",
                "a" * 64,
                (),
                None,
                (),
                (),
                OriginMap("project", 0),
            ),
            ComputationOutcome.SUCCEEDED,
            observations=observations,
            diagnostics=diagnostics,
        )
    )


def test_evidence_and_every_portable_envelope_share_exact_size_limit(tmp_path):
    assert (
        MAX_EVIDENCE_BYTES
        == MAX_MESSAGE_BYTES
        == MAX_RPC_MESSAGE_BYTES
        == (MAX_PORTABLE_ENVELOPE_BYTES)
        == 2 * 1024 * 1024
    )
    record = _evidence(diagnostics=(EvidenceDiagnostic("INFO", "x"),))
    overhead = len(canonical_data_bytes(evidence_to_data(record))) - 1
    record = _identified(
        replace(
            record, diagnostics=(EvidenceDiagnostic("INFO", "x" * (MAX_EVIDENCE_BYTES - overhead)),)
        )
    )
    assert len(validate_portable_evidence(record)) == MAX_EVIDENCE_BYTES
    assert evidence_to_proto(record).ByteSize() < MAX_EVIDENCE_BYTES
    store = EvidenceStore(tmp_path)
    store.put(record)
    assert store.get(record.id) == record
    oversized = _identified(
        replace(
            record, diagnostics=(EvidenceDiagnostic("INFO", record.diagnostics[0].message + "x"),)
        )
    )
    with pytest.raises(ValueError, match="resources"):
        store.put(oversized)
    assert store.identities() == (record.id,)


def test_evidence_json_can_fit_while_protobuf_does_not_and_durable_admission_rejects(tmp_path):
    # Per-element wire tags and doubles can exceed the textual encoding of 0.0.
    tensor = TensorValue(TensorDType.FLOAT64, (1024,), (0.0,) * 1024)
    record = _evidence(
        observations=tuple(
            EvidenceObservation(f"o:{index}", (), tensor, sequence=index) for index in range(256)
        )
    )
    data = canonical_data_bytes(evidence_to_data(record))
    assert len(data) < MAX_EVIDENCE_BYTES
    with pytest.raises(ProtocolBoundaryError, match="2 MiB"):
        EvidenceStore(tmp_path).put(record)
    assert EvidenceStore(tmp_path).identities() == ()
    # Loading a previously produced record cannot bypass the same portability rule.
    path = EvidenceStore(tmp_path)._path(record.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    with pytest.raises(ProtocolBoundaryError, match="2 MiB"):
        EvidenceStore(tmp_path).get(record.id)


def _bytes(frame):
    return resource_frame_to_proto(frame).SerializeToString(deterministic=True)


def _unpublished(store):
    assert store.descriptors() == ()
    assert all(path.is_dir() for path in store.root.glob("staging/**/*"))


def test_large_resource_stream_roundtrip_never_uses_whole_resource_read(tmp_path, monkeypatch):
    source, target = ResourceStore(tmp_path / "source"), ResourceStore(tmp_path / "target")
    payload = bytes(range(256)) * (12 * 1024)
    descriptor = source.put(payload, "application/octet-stream")
    monkeypatch.setattr(ResourceStore, "read", lambda *_: pytest.fail("Whole-resource read"))
    sizes = []

    def messages():
        for frame in export_resource_stream(source, descriptor.reference, "opaque/../transfer"):
            sizes.append(len(frame))
            assert len(frame) <= MAX_MESSAGE_BYTES
            yield frame

    assert import_resource_stream(
        target, descriptor.reference, messages(), max_resource_bytes=len(payload)
    ) == len(payload)
    assert len(sizes) > 10
    assert target.describe(descriptor.reference) == descriptor
    assert target.verified_path(descriptor.reference).read_bytes() == payload
    assert all(path.is_dir() for path in target.root.glob("staging/**/*"))


@pytest.mark.parametrize("payload", [b"", b"x", b"abc" * 100])
def test_empty_small_resource_and_repeated_content_are_valid(tmp_path, payload):
    source, target = ResourceStore(tmp_path / "source"), ResourceStore(tmp_path / "target")
    descriptor = source.put(payload, "application/octet-stream")
    for _ in range(2):
        frames = export_resource_stream(source, descriptor.reference, "transfer")
        import_resource_stream(
            target, descriptor.reference, frames, max_resource_bytes=len(payload)
        )
    assert target.descriptors() == (descriptor,)
    assert target.read(descriptor.reference) == payload


@pytest.mark.parametrize(
    "fault",
    [
        "truncated",
        "no-start",
        "duplicate-start",
        "wrong-transfer",
        "gap",
        "replay",
        "too-long",
        "corrupt",
        "abort",
        "trailing",
        "unknown-field",
        "future-version",
        "oversize-chunk",
    ],
)
def test_invalid_resource_streams_never_publish_and_always_clean_staging(tmp_path, fault):
    source, target = ResourceStore(tmp_path / "source"), ResourceStore(tmp_path / "target")
    descriptor = source.put(b"abcd", "application/octet-stream")
    start = ResourceTransferStart("transfer", descriptor)
    chunk = ResourceTransferChunk("transfer", 0, b"abcd")
    finish = ResourceTransferFinish("transfer")
    frames = [start, chunk, finish]
    if fault == "truncated":
        frames.pop()
    elif fault == "no-start":
        frames.pop(0)
    elif fault == "duplicate-start":
        frames.insert(1, start)
    elif fault == "wrong-transfer":
        frames[1] = replace(chunk, transfer_id="other")
    elif fault == "gap":
        frames[1] = replace(chunk, offset=1)
    elif fault == "replay":
        frames.insert(2, chunk)
    elif fault == "too-long":
        frames[1] = replace(chunk, data=b"abcde")
    elif fault == "corrupt":
        frames[1] = replace(chunk, data=b"wxyz")
    elif fault == "abort":
        frames[2] = ResourceTransferAbort("transfer", "cancelled by sender")
    elif fault == "trailing":
        frames.append(chunk)
    messages = [_bytes(frame) for frame in frames]
    if fault == "unknown-field":
        messages[1] += b"\xf8\x07\x01"
    elif fault == "future-version":
        modified = resource_frame_to_proto(chunk)
        modified.schema_version = 2
        messages[1] = modified.SerializeToString()
    elif fault == "oversize-chunk":
        modified = resource_frame_to_proto(chunk)
        modified.chunk.data = b"x" * (MAX_RESOURCE_CHUNK_BYTES + 1)
        messages[1] = modified.SerializeToString()
    with pytest.raises(ValueError):
        import_resource_stream(target, descriptor.reference, messages, max_resource_bytes=10)
    _unpublished(target)


def test_interrupted_iterator_and_explicit_receiver_close_remove_staging(tmp_path):
    source, target = ResourceStore(tmp_path / "source"), ResourceStore(tmp_path / "target")
    descriptor = source.put(b"abcd", "application/octet-stream")

    def interrupted():
        yield _bytes(ResourceTransferStart("transfer", descriptor))
        yield _bytes(ResourceTransferChunk("transfer", 0, b"ab"))
        raise OSError("connection lost")

    with pytest.raises(OSError, match="connection lost"):
        import_resource_stream(target, descriptor.reference, interrupted(), max_resource_bytes=4)
    _unpublished(target)
    with ResourceTransferReceiver(target, descriptor.reference, max_resource_bytes=4) as receiver:
        receiver.accept(ResourceTransferStart("transfer", descriptor))
        receiver.accept(ResourceTransferChunk("transfer", 0, b"ab"))
    _unpublished(target)


def test_transfer_descriptor_identity_and_budget_validated_before_any_staging(tmp_path):
    source, target = ResourceStore(tmp_path / "source"), ResourceStore(tmp_path / "target")
    descriptor = source.put(b"abcd", "application/octet-stream")
    for changed in (
        replace(descriptor, id="../../outside"),
        replace(descriptor, byte_size=5),
        replace(descriptor, content_hash="0" * 64),
    ):
        with pytest.raises(ValueError, match="identity or hash"):
            import_resource_stream(
                target,
                descriptor.reference,
                [_bytes(ResourceTransferStart("transfer", changed))],
                max_resource_bytes=10,
            )
    with pytest.raises(ValueError, match="budget"):
        import_resource_stream(
            target,
            descriptor.reference,
            export_resource_stream(source, descriptor.reference, "transfer"),
            max_resource_bytes=3,
        )
    _unpublished(target)


def test_sealed_file_is_reverified_before_commit(tmp_path):
    source, target = ResourceStore(tmp_path / "source"), ResourceStore(tmp_path / "target")
    descriptor = source.put(b"abcd", "application/octet-stream")
    with ResourceTransferReceiver(target, descriptor.reference, max_resource_bytes=4) as receiver:
        for frame in resource_transfer_frames(source, descriptor.reference, "transfer"):
            receiver.accept(frame)
        assert receiver._path is not None
        receiver._path.write_bytes(b"wxyz")
        with pytest.raises(ValueError, match="content hash"):
            receiver.commit()
    _unpublished(target)


def test_sender_detects_change_during_transfer(tmp_path):
    store = ResourceStore(tmp_path)
    descriptor = store.put(b"abcd", "application/octet-stream")
    frames = resource_transfer_frames(store, descriptor.reference, "transfer", chunk_bytes=2)
    assert isinstance(next(frames), ResourceTransferStart)
    store.verified_path(descriptor.reference).write_bytes(b"wxyz")
    with pytest.raises(ValueError, match="changed during transfer"):
        list(frames)


def test_portable_worker_executes_chunked_inputs_and_returns_chunked_artifacts(
    tmp_path, monkeypatch
):
    namespace = "org.example.resource_echo"
    schema = DomainSchema("echo:schema", namespace, "1", (ConceptDefinition("echo:node", "Echo"),))
    node = IntentionalNode("echo:instance", "echo:node")
    model = DomainModel("echo:model", schema.id, "1", (node.id,), (node,))
    project = Project(
        "echo:project", "Resource echo", (), domain_workspace=DomainWorkspace((schema,), (model,))
    )

    def implementation(snapshot):
        resource = snapshot.resources[0]
        assert resource.file is not None and resource.data is None
        return BackendResult(
            observations=(
                EvidenceObservation("echo:count", (node.id,), resource.descriptor.byte_size),
            ),
            produced_resources=(
                ProducedResource(
                    "echo:output",
                    media_type="application/octet-stream",
                    semantic_ids=(node.id,),
                    file=ResourceFile(
                        resource.file.path,
                        resource.descriptor.byte_size,
                        resource.descriptor.content_hash,
                    ),
                ),
            ),
        )

    backend = RegisteredBackend(
        BackendDefinition(
            namespace + ".backend", "1", "Echo", Representation(namespace), schema.id, "1"
        ),
        implementation,
    )
    registry = DomainExtensionRegistry(
        (
            computation_bundle(),
            program_bundle(),
            intentional_bundle(),
            DomainExtensionBundle(namespace, "1", backends=(backend,)),
        )
    )
    source, worker = ResourceStore(tmp_path / "editor"), ResourceStore(tmp_path / "worker")
    payload = source.put(b"waveform" * (512 * 1024), "application/octet-stream")
    monkeypatch.setattr(resource_store, "MAX_RESOURCE_READ_BYTES", 1024 * 1024)
    original_read = ResourceStore.read

    def bounded_read(self, reference):
        assert reference != payload.reference, "Bulk data reached whole-resource read"
        return original_read(self, reference)

    monkeypatch.setattr(ResourceStore, "read", bounded_read)
    with_kernel = InProcessTestKernel(
        ProjectAuthority(project), extensions=registry, resource_store=source
    )
    try:
        request = ComputationRequest(
            project.id, 0, backend.definition.id, "1", model.id, resources=(payload.reference,)
        )
        local = execute_computation(with_kernel, request)
        plan = export_computation_plan(with_kernel, request)
        refs = (*plan.request.resources, plan.model)
        response = run_streamed_computation_plan(
            computation_plan_to_proto(plan).SerializeToString(deterministic=True),
            (
                (ref, export_resource_stream(source, ref, f"input:{index}"))
                for index, ref in enumerate(refs)
            ),
            registry,
            worker,
            EvidenceStore(tmp_path / "worker"),
            max_total_bytes=16 * 1024 * 1024,
        )
        returned = evidence_from_proto(evidence_pb2.ComputationEvidence.FromString(response))
        assert returned == local
        assert returned.observations[0].semantic_ids == (node.id,)
        assert len(response) < MAX_MESSAGE_BYTES
        output = returned.artifacts[0].resource
        receiver = ResourceStore(tmp_path / "consumer")
        import_resource_stream(
            receiver,
            output,
            export_resource_stream(worker, output, "output"),
            max_resource_bytes=payload.byte_size,
        )
        assert receiver.describe(output).content_hash == payload.content_hash
        assert receiver.verified_path(output) != source.verified_path(payload.reference)
        assert with_kernel.authority.snapshot() == project
        # Cached inputs can be reused, but unsolicited/duplicate transfers and insufficient
        # aggregate storage budgets fail before another backend invocation is formed.
        receive_plan_resources(plan, (), worker, max_total_bytes=0, registry=registry)
        unsolicited = source.put(b"unrelated", "application/octet-stream").reference
        with pytest.raises(ValueError, match="unsolicited or duplicated"):
            receive_plan_resources(
                plan, ((unsolicited, ()),), worker, max_total_bytes=0, registry=registry
            )
        with pytest.raises(ValueError, match="unsolicited or duplicated"):
            receive_plan_resources(
                plan,
                (
                    (
                        payload.reference,
                        export_resource_stream(source, payload.reference, "cached"),
                    ),
                    (payload.reference, ()),
                ),
                worker,
                max_total_bytes=payload.byte_size,
                registry=registry,
            )
        with pytest.raises(ValueError, match="budget"):
            receive_plan_resources(
                plan,
                ((payload.reference, export_resource_stream(source, payload.reference, "budget")),),
                ResourceStore(tmp_path / "limited"),
                max_total_bytes=3,
                registry=registry,
            )
    finally:
        with_kernel.close()
