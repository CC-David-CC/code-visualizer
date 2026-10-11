"""A real worker cannot turn unacknowledged bytes into a recoverable checkpoint."""

import json
from pathlib import Path
from time import monotonic, sleep

import numpy as np
import pytest
from test_adaptive_computation import host, last_resource, reader, request
from test_adaptive_domain import change, problem

from code_visualizer.application.adaptive_examples import adaptive_diffusion_project
from code_visualizer.application.computation import execute_computation, start_computation
from code_visualizer.domain.computation import CancelRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.extensions.adaptive_diffusion.checkpoint import (
    CHECKPOINT_TYPE,
    decode_checkpoint,
)
from code_visualizer.extensions.adaptive_fields.records import HISTORY_TYPE
from code_visualizer.extensions.adaptive_fields.units import quantity
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.resources import resource_from_data


def short_project():
    project = adaptive_diffusion_project()
    project = change(project, "adaptive:policy", "final_time", quantity(0.4))
    return change(project, "adaptive:policy", "checkpoint_interval", quantity(0.1))


@pytest.mark.parametrize("boundary", ("bytes", "descriptor", "receipt", "report"))
def test_persistent_host_write_failure_preserves_only_acknowledged_checkpoint(
    tmp_path, monkeypatch, boundary
):
    project = short_project()
    target_tick = 2 * problem(project).policy.sample_ticks
    faults = []

    def reject():
        faults.append(boundary)
        raise OSError(f"{boundary} destination remains unwritable")

    def is_target(payload):
        try:
            return decode_checkpoint(payload).tick == target_tick
        except (ValueError, KeyError, UnicodeError):
            return False

    producer, consumer = tmp_path / "producer", tmp_path / "consumer"
    with host(project, producer) as kernel:
        with monkeypatch.context() as patch:
            if boundary == "bytes":
                import code_visualizer.persistence.resource_store as module

                link = module.os.link

                def fail_bytes(source, destination, *args, **kwargs):
                    if (
                        "sha256" in Path(destination).parts
                        and Path(source).stat().st_size < 64 * 1024
                        and is_target(Path(source).read_bytes())
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
                            data = path.parent.parent / "sha256" / digest[:2] / digest
                            if is_target(data.read_bytes()):
                                reject()
                    return write(path, payload)

                patch.setattr(ResourceStore, "_write_immutable", staticmethod(fail_descriptor))
            elif boundary == "receipt":
                put = EvidenceStore.put_publication

                def fail_receipt(store, publication):
                    if publication.artifact.id == f"checkpoint:{target_tick}":
                        reject()
                    return put(store, publication)

                patch.setattr(EvidenceStore, "put_publication", fail_receipt)
            else:
                patch.setattr(EvidenceStore, "put", lambda *_: reject())
            session = start_computation(kernel, request(project))
            if boundary == "report":
                with pytest.raises(OSError, match="remains unwritable"):
                    kernel.computations.wait(session.id)
            else:
                result = kernel.computations.wait(session.id)
                assert result.outcome is ComputationOutcome.FAILED, result.diagnostics
                assert all(a.id != f"checkpoint:{target_tick}" for a in result.artifacts)
            assert faults, "The injected failure must occur in the ordinary worker/host path"
            publications = kernel.computations.job(session.id).publications.values()
            checkpoints = [
                item.artifact
                for item in publications
                if kernel.resource_store.describe(item.artifact.resource).logical_type
                == CHECKPOINT_TYPE
            ]
            assert any(item.id == f"checkpoint:{target_tick // 2}" for item in checkpoints)
            if boundary != "report":
                assert all(item.id != f"checkpoint:{target_tick}" for item in checkpoints)
            selected = next(
                item.resource for item in checkpoints if item.id == f"checkpoint:{target_tick // 2}"
            )
        destination = ResourceStore(consumer)
        for ref in kernel.extensions.resource_closure((selected,), kernel.resource_store):
            destination.import_reference(kernel.resource_store, ref)
    with host(project, consumer) as fresh:
        resumed = execute_computation(fresh, request(project, selected))
        assert resumed.outcome is ComputationOutcome.SUCCEEDED, resumed.diagnostics
        final = reader(
            last_resource(resumed, fresh.resource_store, HISTORY_TYPE), fresh.resource_store
        )
        assert final.sample_count == 5
        final.close()


def test_cooperative_cancel_keeps_one_complete_sample_and_resumes_from_resources(tmp_path):
    project = change(adaptive_diffusion_project(), "adaptive:policy", "preview_every", 3)
    project = change(project, "adaptive:policy", "decision_every", 3)
    producer, consumer = tmp_path / "producer", tmp_path / "consumer"
    with host(project, producer) as kernel:
        session = start_computation(kernel, request(project))
        deadline = monotonic() + 45
        while monotonic() < deadline:
            job = kernel.computations.job(session.id)
            if job.view.progress is not None and job.view.progress.completed > 0:
                break
            assert not job.done.is_set()
            sleep(0.005)
        else:
            pytest.fail("Real adaptive worker did not report progress within 45 seconds")
        kernel.computations.cancel(CancelRequest(session.id))
        cancelled = kernel.computations.wait(session.id)
        assert cancelled.outcome is ComputationOutcome.CANCELLED, cancelled.diagnostics
        assert not cancelled.diagnostics, cancelled.diagnostics
        assert not kernel.computations.job(session.id).view.forced_termination
        selected = last_resource(cancelled, kernel.resource_store, CHECKPOINT_TYPE)
        checkpoint = decode_checkpoint(kernel.resource_store.read(selected))
        p = problem(project)
        assert 0 < checkpoint.tick < p.policy.final_tick
        assert checkpoint.tick % p.policy.sample_ticks == 0
        retained = reader(checkpoint.history, kernel.resource_store)
        assert retained.slice(retained.sample_count - 1).position.step == checkpoint.step
        retained.close()
        destination = ResourceStore(consumer)
        for ref in kernel.extensions.resource_closure((selected,), kernel.resource_store):
            destination.import_reference(kernel.resource_store, ref)
    with host(project, consumer) as fresh:
        resumed = execute_computation(fresh, request(project, selected))
        assert resumed.outcome is ComputationOutcome.SUCCEEDED, resumed.diagnostics
        complete = execute_computation(fresh, request(project))
        assert complete.outcome is ComputationOutcome.SUCCEEDED, complete.diagnostics
        actual = reader(
            last_resource(resumed, fresh.resource_store, HISTORY_TYPE), fresh.resource_store
        )
        expected = reader(
            last_resource(complete, fresh.resource_store, HISTORY_TYPE), fresh.resource_store
        )
        try:
            # A cancellation closes a partial chunk, so byte-level chunk boundaries
            # differ. The complete scientific samples, decisions and support do not.
            assert actual.sample_count == expected.sample_count == 201
            assert actual.series.epochs == expected.series.epochs
            assert actual.series.decisions == expected.series.decisions
            for index in range(actual.sample_count):
                a, b = actual.slice(index), expected.slice(index)
                assert (a.position, a.epoch, a.mesh) == (b.position, b.epoch, b.mesh)
                np.testing.assert_array_equal(a.values, b.values)
        finally:
            actual.close()
            expected.close()


@pytest.mark.parametrize("value", (-1, 61, float("nan"), float("inf"), True, "5"))
def test_registered_cleanup_budget_is_bounded_and_not_project_authored(value):
    from dataclasses import replace

    from code_visualizer.extensions.adaptive_diffusion.backend import adaptive_backend
    from code_visualizer.extensions.diffusion.backend import diffusion_backend

    assert diffusion_backend().cancellation_grace_seconds == 0.5
    assert adaptive_backend().cancellation_grace_seconds == 5.0
    with pytest.raises(ValueError, match="cancellation grace"):
        replace(adaptive_backend(), cancellation_grace_seconds=value)
