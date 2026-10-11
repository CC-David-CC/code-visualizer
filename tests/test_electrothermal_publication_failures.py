"""Persistent real publication cuts plus unavailable error reporting, then fresh recovery."""

import json
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from test_electrothermal_git import experiment as experiment
from test_electrothermal_git import recover_fresh, request
from test_electrothermal_references import Parameters, assert_accounting, discrete
from test_git_experiments import untouched

from code_visualizer.domain.evidence import PublicationEvent
from code_visualizer.execution.worker_process import WorkerProcess
from code_visualizer.extensions.electrothermal.checkpoint import (
    CODEC,
    CoupledCheckpoint,
)
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.resources import resource_from_data
from code_visualizer.protocol.worker import worker_control_from_bytes


def target_parent(payload):
    try:
        return CODEC.decode(payload, CoupledCheckpoint).position.step == 4
    except (ValueError, KeyError, UnicodeError):
        return False


def target_child(payload):
    if not payload.startswith(b"\x93NUMPY"):
        return False
    values = np.load(BytesIO(payload), allow_pickle=False)
    # The actual checkpoint state at window four, after checkpoint two is retained.
    return values.shape == (4,) and 0.8 < values[0] < 1.1


@pytest.mark.parametrize(
    "boundary",
    (
        "child_bytes",
        "child_descriptor",
        "parent_bytes",
        "parent_descriptor",
        "receipt",
        "association",
        "ack",
        "report",
    ),
)
def test_persistent_cut_and_error_report_failure_recover_in_fresh_interpreter(
    experiment,
    monkeypatch,
    tmp_path,
    boundary,
):
    controller, original, host, root = experiment
    before = untouched(root)
    faults = []

    def reject(cut):
        faults.append(cut)
        raise OSError(f"{cut} destination remains unwritable")

    with monkeypatch.context() as patch:
        # A second failure while recording the first must not erase retention or
        # cause reopening to grant in-place semantic editing.
        patch.setattr(EvidenceStore, "put", lambda *_: reject("report"))
        if boundary.endswith("_bytes"):
            import code_visualizer.persistence.resource_store as resource_module

            link = resource_module.os.link

            def fail_bytes(source, destination, *args, **kwargs):
                if "sha256" in Path(destination).parts and Path(source).stat().st_size < 64 * 1024:
                    payload = Path(source).read_bytes()
                    if (target_child if boundary.startswith("child") else target_parent)(payload):
                        reject(boundary)
                return link(source, destination, *args, **kwargs)

            patch.setattr(resource_module.os, "link", fail_bytes)
        elif boundary.endswith("_descriptor"):
            write = ResourceStore._write_immutable

            def fail_descriptor(path, payload):
                if path.parent.name == "descriptors":
                    descriptor = resource_from_data(json.loads(payload))
                    if descriptor.byte_size < 64 * 1024:
                        digest = descriptor.content_hash
                        data = (path.parent.parent / "sha256" / digest[:2] / digest).read_bytes()
                        if (target_child if boundary.startswith("child") else target_parent)(data):
                            reject(boundary)
                return write(path, payload)

            patch.setattr(ResourceStore, "_write_immutable", staticmethod(fail_descriptor))
        elif boundary == "receipt":
            put = EvidenceStore.put_publication

            def fail_receipt(store, publication):
                if publication.artifact.id == "checkpoint:4":
                    reject(boundary)
                return put(store, publication)

            patch.setattr(EvidenceStore, "put_publication", fail_receipt)
        elif boundary == "association":
            retained_store = controller.experiments.store
            record = retained_store.record_publications

            def fail_association(identity, publications):
                evidence = EvidenceStore(retained_store.root)
                if any(
                    evidence.get_publication(item).artifact.id == "checkpoint:4"
                    for item in publications
                ):
                    reject(boundary)
                return record(identity, publications)

            patch.setattr(retained_store, "record_publications", fail_association)
        elif boundary == "ack":
            send = WorkerProcess.send

            def fail_ack(worker, payload):
                event = worker_control_from_bytes(payload)
                if (
                    isinstance(event, PublicationEvent)
                    and event.publication.artifact.id == "checkpoint:4"
                ):
                    reject(boundary)
                return send(worker, payload)

            patch.setattr(WorkerProcess, "send", fail_ack)

        frozen = controller.freeze_and_run(request(original))
        # The host preserves the original fault if writing failure evidence also
        # fails. The reporting fault is asserted independently below.
        with pytest.raises(OSError, match=boundary + " destination remains unwritable"):
            host.wait(frozen.computation.id)
        assert boundary in faults, f"The intended {boundary} boundary was not exercised: {faults}"
        assert "report" in faults
        job = host.job(frozen.computation.id)
        retained = controller.experiments.store.attempt(frozen.attempt.id)
        assert set(job.publications) == set(retained.publications)
        assert controller.session.experiment_context.attempt_id == frozen.attempt.id
        choices = controller.execute("experiment_checkpoints", {"attempt_id": frozen.attempt.id})[
            "checkpoints"
        ]
        choice = next(item for item in choices if "window 2" in item.label)
        if boundary not in ("ack", "report"):
            assert all("window 4" not in item.label for item in choices)
        # A lost worker ACK can leave a host-retained checkpoint. Host association
        # is authoritative; merely staged bytes/receipt at earlier cuts are not.
        store = ResourceStore(controller.experiments.store.root)
        prior = EvidenceStore(controller.experiments.store.root).get_publication(
            choice.publication_id
        )
        hashes = {
            ref: store.read(ref)
            for ref in controller.session.kernel.extensions.resource_closure(
                (prior.artifact.resource,), store
            )
        }
        active_root = controller.session.root
        controller.close_background(wait=True)
        controller.session.close()
        host.close()
    fresh = recover_fresh(
        active_root, frozen.attempt.id, choice.publication_id, tmp_path / "recovery.json"
    )
    assert fresh["frozen_before"] == frozen.attempt.id
    assert fresh["retained_commit"] == frozen.attempt.commit
    assert fresh["parent_attempt"] == frozen.attempt.id
    assert fresh["forked_after_resume"] and fresh["child_unrun"]
    assert_accounting(np.asarray(fresh["rows"]), Parameters(), discrete(Parameters(), 1, 6))
    assert all(store.read(ref) == payload for ref, payload in hashes.items())
    assert untouched(root) == before
