"""Worker resource frames are bounded and must be claimed by their phase output."""

from types import SimpleNamespace

import pytest
from test_computation_publications import publication_context as publication_context

from code_visualizer.application import computation_process as process
from code_visualizer.domain.boundaries import MAX_PORTABLE_ENVELOPE_BYTES
from code_visualizer.domain.resource_transfer import (
    ResourceTransferAbort,
    ResourceTransferFinish,
    ResourceTransferStart,
)
from code_visualizer.domain.worker import WorkerPrepared, WorkerResourceEvent
from code_visualizer.execution.worker_process import WorkerExited
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.resource_transfer import resource_transfer_frames
from code_visualizer.protocol.worker import worker_event_to_bytes


def _ledger(path):
    return process._Resources(ResourceStore(path), SimpleNamespace(registry=builtin_registry()))


def _transfer(ledger, source, reference, transfer_id):
    for frame in resource_transfer_frames(source, reference, transfer_id):
        ledger.accept(WorkerResourceEvent("session", frame))


def test_complete_transfer_set_matches_observation_publication_and_terminal_claims(tmp_path):
    source = ResourceStore(tmp_path / "source")
    observation = source.put(b"observed", "application/octet-stream").reference
    publication = source.put(b"published", "application/octet-stream").reference
    terminal = source.put(b"terminal", "application/octet-stream").reference
    ledger = _ledger(tmp_path / "target")
    try:
        for index, reference in enumerate((observation, publication, terminal, publication)):
            _transfer(ledger, source, reference, f"transfer-{index}")
        ledger.claim((observation,))
        ledger.claim_transferred((publication,))
        ledger.complete((terminal, publication))
        assert ledger.transferred == {observation, publication, terminal}
        assert ledger.claimed == ledger.transferred
        assert ledger.transfer_count == 4  # Repeat transfers still consume admission budget.
        assert ledger.store.read(publication) == b"published"
    finally:
        ledger.close()


def test_unclaimed_and_omitted_resources_are_rejected(tmp_path):
    source = ResourceStore(tmp_path / "source")
    valid = source.put(b"valid", "text/plain").reference
    unrelated = source.put(b"", "application/x-unrelated").reference
    ledger = _ledger(tmp_path / "target")
    try:
        _transfer(ledger, source, valid, "valid")
        _transfer(ledger, source, unrelated, "unrelated")
        with pytest.raises(ValueError, match="not claimed"):
            ledger.complete((valid,))
    finally:
        ledger.close()
    empty = _ledger(tmp_path / "empty")
    try:
        with pytest.raises(ValueError, match="omitted"):
            empty.complete((valid,))
        with pytest.raises(ValueError, match="complete resource transfer"):
            empty.claim_transferred((valid,))
    finally:
        empty.close()


def test_partial_or_aborted_transfer_cannot_be_claimed(tmp_path):
    source = ResourceStore(tmp_path / "source")
    descriptor = source.put(b"payload", "application/octet-stream")
    ledger = _ledger(tmp_path / "target")
    try:
        ledger.accept(WorkerResourceEvent("session", ResourceTransferStart("partial", descriptor)))
        with pytest.raises(ValueError, match="completion"):
            ledger.claim((descriptor.reference,))
        with pytest.raises(ValueError, match="aborted"):
            ledger.accept(WorkerResourceEvent("session", ResourceTransferAbort("partial")))
        assert not ledger.transferred
    finally:
        ledger.close()
    assert not tuple((ledger.store.root / "staging" / "transport").glob("*"))


@pytest.mark.parametrize("boundary", ("metadata", "count"))
def test_zero_byte_repeated_transfers_consume_metadata_and_count_budgets(
    tmp_path, monkeypatch, boundary
):
    assert process.MAX_PHASE_TRANSFER_METADATA_BYTES == MAX_PORTABLE_ENVELOPE_BYTES
    assert process.MAX_PHASE_RESOURCE_TRANSFERS == 4096
    source = ResourceStore(tmp_path / "source")
    descriptor = source.put(b"", "application/octet-stream")
    ledger = _ledger(tmp_path / "target")
    start = WorkerResourceEvent("session", ResourceTransferStart("same", descriptor))
    if boundary == "metadata":
        monkeypatch.setattr(
            process, "MAX_PHASE_TRANSFER_METADATA_BYTES", len(worker_event_to_bytes(start))
        )
    else:
        monkeypatch.setattr(process, "MAX_PHASE_RESOURCE_TRANSFERS", 1)
    try:
        ledger.accept(start)
        ledger.accept(WorkerResourceEvent("session", ResourceTransferFinish("same")))
        assert ledger.remaining == process.MAX_PHASE_TRANSFER_BYTES
        with pytest.raises(ValueError, match=f"{boundary} budget"):
            ledger.accept(start)
        assert ledger.transfer_count == 1
    finally:
        ledger.close()


class _FakeWorker:
    forced_termination = False

    def __init__(self, events):
        self.events = iter(events)
        self.expected_exit = False
        self.closed = False

    def receive(self):
        try:
            return worker_event_to_bytes(next(self.events))
        except StopIteration:
            raise WorkerExited(0, "") from None

    def expect_exit(self):
        self.expected_exit = True

    def close(self):
        self.closed = True


@pytest.mark.parametrize("extra", (False, True))
def test_preparation_requires_exact_terminal_and_execution_resource_claims(
    publication_context, tmp_path, monkeypatch, extra
):
    snapshot, plan, source, _, registry, _ = publication_context
    execution = source.put(b"emitted files", "application/octet-stream").reference
    references = [plan.model, execution]
    if extra:
        references.append(source.put(b"", "application/x-unrelated").reference)
    events = [
        WorkerResourceEvent("session", frame)
        for index, reference in enumerate(references)
        for frame in resource_transfer_frames(source, reference, f"transfer-{index}")
    ]
    prepared = WorkerPrepared("session", plan, execution)
    worker = _FakeWorker((*events, prepared))
    monkeypatch.setattr(process, "_launch", lambda *args: worker)
    job = SimpleNamespace(
        project=snapshot.project,
        request=snapshot.request,
        registry=registry,
        view=SimpleNamespace(session=SimpleNamespace(id="session")),
        worker=worker,
    )
    service = SimpleNamespace(changed=lambda *args, **kwargs: None)
    target = ResourceStore(tmp_path / "prepared")
    if extra:
        with pytest.raises(ValueError, match="not claimed"):
            process._prepared(service, job, target, None, plan.model)
        assert not worker.expected_exit
    else:
        assert process._prepared(service, job, target, None, plan.model) == prepared
        assert worker.expected_exit
    assert worker.closed and job.worker is None
