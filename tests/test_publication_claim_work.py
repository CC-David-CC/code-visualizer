"""Publication walks are bounded without caching away subsequent integrity checks."""

from types import SimpleNamespace

import pytest
from fixtures.field_worker_fixture import field_output
from test_computation_publications import publication_context as publication_context

from code_visualizer.application.computation_process import _Resources
from code_visualizer.application.computation_publications import seal_resource
from code_visualizer.domain.resource_transfer import ResourceTransferStart
from code_visualizer.domain.worker import WorkerResourceEvent
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.resource_transfer import resource_transfer_frames


def test_each_publication_checks_each_bulk_child_once_and_checks_again_next_time(
    publication_context, tmp_path, monkeypatch
):
    snapshot, _, source, _, _, _ = publication_context
    registry = builtin_registry()
    artifact = seal_resource(snapshot, field_output(), source, registry)
    closure = registry.resource_closure((artifact.resource,), source)
    destination = ResourceStore(tmp_path / "received")
    ledger = _Resources(destination, SimpleNamespace(registry=registry))
    try:
        for reference in closure:
            for frame in resource_transfer_frames(source, reference, reference.id):
                ledger.accept(WorkerResourceEvent("run", frame))
        verified = []
        verify = destination.verified_path

        def count(reference):
            verified.append(reference)
            return verify(reference)

        monkeypatch.setattr(destination, "verified_path", count)
        ledger.claim_transferred((artifact.resource,))
        assert ledger.claimed == set(closure)
        assert set(verified) == set(closure)
        assert len(verified) == len(closure)

        # This is a per-operation work bound, never a persistent trust cache.
        leaf = next(reference for reference in closure if destination.describe(reference).tensor)
        path = verify(leaf)
        damaged = bytearray(path.read_bytes())
        damaged[-1] ^= 1
        path.write_bytes(damaged)
        verified.clear()
        with pytest.raises(ValueError):
            ledger.claim_transferred((artifact.resource,))
        assert leaf in verified
        assert source.read(leaf) != path.read_bytes()
    finally:
        ledger.close()


def test_publication_cannot_claim_an_old_root_during_an_unfinished_new_transfer(tmp_path):
    source = ResourceStore(tmp_path / "source")
    first = source.put(b"complete", "application/octet-stream")
    second = source.put(b"unfinished", "application/octet-stream")
    ledger = _Resources(
        ResourceStore(tmp_path / "received"), SimpleNamespace(registry=builtin_registry())
    )
    try:
        for frame in resource_transfer_frames(source, first.reference, "first"):
            ledger.accept(WorkerResourceEvent("run", frame))
        ledger.accept(WorkerResourceEvent("run", ResourceTransferStart("second", second)))
        with pytest.raises(ValueError, match="completion"):
            ledger.claim_transferred((first.reference,))
        assert not ledger.claimed
    finally:
        ledger.close()
