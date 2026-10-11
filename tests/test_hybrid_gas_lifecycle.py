"""Real gas workers keep complete acknowledged native state across host failures."""

import json
from pathlib import Path
from time import monotonic, sleep

import numpy as np
import pytest
from fixtures.gas_project import change, short_project
from test_hybrid_gas_computation import host, reader, request, resources
from test_hybrid_gas_particle import WINDOWS

from code_visualizer.application.computation import execute_computation, start_computation
from code_visualizer.domain.computation import CancelRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.extensions.hybrid_gas.records import (
    CHECKPOINT_TYPE,
    CODEC,
    HISTORY_TYPE,
    GasCheckpoint,
)
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.resources import resource_from_data

pytestmark = WINDOWS


def complete(host, session_id):
    assert host.job(session_id).done.wait(180), host.job(session_id).view
    return host.wait(session_id)


def copy_checkpoint(kernel, reference, destination):
    for item in kernel.extensions.resource_closure((reference,), kernel.resource_store):
        destination.import_reference(kernel.resource_store, item)


def samples(root, store):
    history = reader(root, store)
    try:
        return tuple(
            (
                history.gas_slice(i).position,
                history.gas_slice(i).particle,
                history.gas_slice(i).conserved.copy(),
            )
            for i in range(history.sample_count)
        )
    finally:
        history.close()


@pytest.fixture(scope="module")
def uninterrupted(tmp_path_factory):
    project = short_project()
    with host(project, tmp_path_factory.mktemp("gas-lifecycle-reference")) as kernel:
        evidence = execute_computation(kernel, request(project))
        assert evidence.outcome is ComputationOutcome.SUCCEEDED, evidence.diagnostics
        root = resources(evidence, kernel.resource_store, HISTORY_TYPE)[-1]
        return root, samples(root, kernel.resource_store)


@pytest.mark.parametrize("boundary", ("bytes", "descriptor", "receipt", "report"))
def test_persistent_publication_failure_retains_native_checkpoint_and_exact_fresh_resume(
    tmp_path, monkeypatch, uninterrupted, boundary
):
    project = short_project()
    faults = []

    def reject():
        faults.append(boundary)
        raise OSError(f"{boundary} destination remains unwritable")

    def target(payload):
        try:
            return CODEC.decode(payload, GasCheckpoint).tick == 1000
        except (ValueError, KeyError, UnicodeError):
            return False

    destination = ResourceStore(tmp_path / "consumer")
    with host(project, tmp_path / "producer") as kernel:
        with monkeypatch.context() as patch:
            if boundary == "bytes":
                import code_visualizer.persistence.resource_store as module

                link = module.os.link

                def fail_bytes(source, destination, *args, **kwargs):
                    if (
                        "sha256" in Path(destination).parts
                        and Path(source).stat().st_size < 64 * 1024
                        and target(Path(source).read_bytes())
                    ):
                        reject()
                    return link(source, destination, *args, **kwargs)

                patch.setattr(module.os, "link", fail_bytes)
            elif boundary == "descriptor":
                write = ResourceStore._write_immutable

                def fail_descriptor(path, payload):
                    if path.parent.name == "descriptors":
                        descriptor = resource_from_data(json.loads(payload))
                        if descriptor.logical_type == CHECKPOINT_TYPE:
                            digest = descriptor.content_hash
                            stored = path.parent.parent / "sha256" / digest[:2] / digest
                            if target(stored.read_bytes()):
                                reject()
                    return write(path, payload)

                patch.setattr(ResourceStore, "_write_immutable", staticmethod(fail_descriptor))
            elif boundary == "receipt":
                put = EvidenceStore.put_publication

                def fail_receipt(store, publication):
                    if publication.artifact.id == "checkpoint:1000":
                        reject()
                    return put(store, publication)

                patch.setattr(EvidenceStore, "put_publication", fail_receipt)
            else:
                patch.setattr(EvidenceStore, "put", lambda *_: reject())
            session = start_computation(kernel, request(project))
            if boundary == "report":
                with pytest.raises(OSError, match="remains unwritable"):
                    complete(kernel.computations, session.id)
            else:
                result = complete(kernel.computations, session.id)
                assert result.outcome is ComputationOutcome.FAILED, result.diagnostics
                assert all(a.id != "checkpoint:1000" for a in result.artifacts)
            assert faults, "Failure injection must reach the ordinary host publication path"
            checkpoints = {
                item.artifact.id: item.artifact.resource
                for item in kernel.computations.job(session.id).publications.values()
                if kernel.resource_store.describe(item.artifact.resource).logical_type
                == CHECKPOINT_TYPE
            }
            assert "checkpoint:500" in checkpoints
            if boundary != "report":
                assert "checkpoint:1000" not in checkpoints
            selected = checkpoints["checkpoint:500"]
            saved = CODEC.decode(kernel.resource_store.read(selected), GasCheckpoint)
            assert saved.tick == 500 and saved.model.particle
            assert saved.native is not None and saved.native_length > 0
        copy_checkpoint(kernel, selected, destination)
    # The producing process has exited. Only the complete retained closure and
    # the same authored calibration input are supplied to the new ordinary host.
    with host(project, tmp_path / "consumer") as fresh:
        resumed = execute_computation(fresh, request(project, selected))
        assert resumed.outcome is ComputationOutcome.SUCCEEDED, resumed.diagnostics
        root = resources(resumed, fresh.resource_store, HISTORY_TYPE)[-1]
        assert root == uninterrupted[0]
        actual = samples(root, fresh.resource_store)
        assert len(actual) == len(uninterrupted[1]) == 3
        for a, b in zip(actual, uninterrupted[1], strict=True):
            assert a[:2] == b[:2]
            np.testing.assert_array_equal(a[2], b[2])


def test_native_cooperative_cancel_finishes_at_sample_and_reconstructs_exactly(
    tmp_path, monkeypatch
):
    project = change(short_project(), "gas:policy", "final_tick", 4000)
    destination = ResourceStore(tmp_path / "consumer")
    with host(project, tmp_path / "producer") as kernel:
        updates = []
        publish = kernel.computations.publish

        def observed(job, update):
            publication = getattr(update, "publication", None)
            updates.append(
                {
                    "time": monotonic(),
                    "kind": type(update).__name__,
                    "artifact": publication.artifact.id if publication else None,
                    "completed": getattr(update, "completed", None),
                }
            )
            return publish(job, update)

        monkeypatch.setattr(kernel.computations, "publish", observed)
        session = start_computation(kernel, request(project))
        deadline = monotonic() + 90
        while monotonic() < deadline:
            job = kernel.computations.job(session.id)
            assert not job.done.is_set(), job.view
            if job.view.progress is not None and job.view.progress.completed >= 600:
                break
            sleep(0.005)
        else:
            pytest.fail("Real gas worker did not pass its first checkpoint in 90 seconds")
        started = monotonic()
        kernel.computations.cancel(CancelRequest(session.id))
        cancelled = complete(kernel.computations, session.id)
        elapsed = monotonic() - started
        (tmp_path / "cancellation.json").write_text(
            json.dumps(
                {
                    "cancel_requested": started,
                    "elapsed_seconds": elapsed,
                    "forced_termination": job.view.forced_termination,
                    "outcome": cancelled.outcome.value,
                    "diagnostics": [d.code for d in cancelled.diagnostics],
                    "updates": updates,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        assert cancelled.outcome is ComputationOutcome.CANCELLED, cancelled.diagnostics
        assert not cancelled.diagnostics, cancelled.diagnostics
        assert not kernel.computations.job(session.id).view.forced_termination
        assert elapsed <= 15, elapsed
        selected = resources(cancelled, kernel.resource_store, CHECKPOINT_TYPE)[-1]
        checkpoint = CODEC.decode(kernel.resource_store.read(selected), GasCheckpoint)
        assert 500 < checkpoint.tick < 4000 and checkpoint.tick % 500 == 0
        assert checkpoint.native is not None and checkpoint.model.particle
        prefix = samples(checkpoint.history, kernel.resource_store)
        assert prefix[-1][0].step == checkpoint.tick
        copy_checkpoint(kernel, selected, destination)
    with host(project, tmp_path / "consumer") as fresh:
        resumed = execute_computation(fresh, request(project, selected))
        expected = execute_computation(fresh, request(project))
        for result in (resumed, expected):
            assert result.outcome is ComputationOutcome.SUCCEEDED, result.diagnostics
        actual = samples(
            resources(resumed, fresh.resource_store, HISTORY_TYPE)[-1], fresh.resource_store
        )
        reference = samples(
            resources(expected, fresh.resource_store, HISTORY_TYPE)[-1], fresh.resource_store
        )
        assert len(actual) == len(reference) == 9
        for a, b in zip(actual, reference, strict=True):
            assert a[:2] == b[:2]
            np.testing.assert_array_equal(a[2], b[2])
