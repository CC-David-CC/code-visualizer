"""Persistent failures cannot advertise an unacknowledged numerical checkpoint."""

import json
from pathlib import Path

import pytest
from test_diffusion_git import experiment as experiment
from test_diffusion_git import finish_freeze, request
from test_git_experiments import untouched

from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.git_service import GitProjectController
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.extensions.fields.codec import decode_record
from code_visualizer.extensions.fields.records import CHECKPOINT_TYPE, DiffusionCheckpoint
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.resources import resource_from_data


@pytest.mark.parametrize("boundary", ("bytes", "descriptor", "receipt", "association", "report"))
def test_persistent_publication_failure_retains_only_acknowledged_restart_state(
    experiment, monkeypatch, boundary
):
    controller, original, host, root = experiment
    before = untouched(root)
    faults = []

    def reject():
        faults.append(boundary)
        raise OSError(f"{boundary} destination remains unwritable")

    def second_checkpoint(payload):
        try:
            return decode_record(payload, DiffusionCheckpoint).position.step == 512
        except (ValueError, KeyError, UnicodeError):
            return False

    with monkeypatch.context() as patch:
        if boundary == "bytes":
            import code_visualizer.persistence.resource_store as resource_module

            link = resource_module.os.link

            def fail_bytes(source, destination, *args, **kwargs):
                if (
                    "sha256" in Path(destination).parts
                    and Path(source).stat().st_size < 64 * 1024
                    and second_checkpoint(Path(source).read_bytes())
                ):
                    reject()
                return link(source, destination, *args, **kwargs)

            patch.setattr(resource_module.os, "link", fail_bytes)
        elif boundary == "descriptor":
            write = ResourceStore._write_immutable

            def fail_descriptor(path, payload):
                if path.parent.name == "descriptors":
                    descriptor = resource_from_data(json.loads(payload))
                    if descriptor.logical_type == CHECKPOINT_TYPE:
                        digest = descriptor.content_hash
                        data = path.parent.parent / "sha256" / digest[:2] / digest
                        if second_checkpoint(data.read_bytes()):
                            reject()
                return write(path, payload)

            patch.setattr(ResourceStore, "_write_immutable", staticmethod(fail_descriptor))
        elif boundary == "receipt":
            put = EvidenceStore.put_publication

            def fail_receipt(store, publication):
                if publication.artifact.id == "checkpoint:512":
                    reject()
                return put(store, publication)

            patch.setattr(EvidenceStore, "put_publication", fail_receipt)
        elif boundary == "association":
            retained = controller.experiments.store
            record = retained.record_publications

            def fail_association(identity, publications):
                evidence = EvidenceStore(retained.root)
                if any(
                    evidence.get_publication(item).artifact.id == "checkpoint:512"
                    for item in publications
                ):
                    reject()
                return record(identity, publications)

            patch.setattr(retained, "record_publications", fail_association)
        else:
            patch.setattr(EvidenceStore, "put", lambda *_: reject())

        frozen = controller.freeze_and_run(request(original))
        if boundary == "report":
            with pytest.raises(OSError, match="remains unwritable"):
                host.wait(frozen.computation.id)
        else:
            result = host.wait(frozen.computation.id)
            assert result.outcome is ComputationOutcome.FAILED, result.diagnostics
            assert all(item.id != "checkpoint:512" for item in result.artifacts)
        assert faults, "Failure must occur in the real host admission path"
        job = host.job(frozen.computation.id)
        retained = controller.experiments.store.attempt(frozen.attempt.id)
        assert set(job.publications) == set(retained.publications)
        assert controller.session.experiment_context.attempt_id == frozen.attempt.id
        choices = controller.execute("experiment_checkpoints", {"attempt_id": frozen.attempt.id})[
            "checkpoints"
        ]
        assert any("step 256" in item.label for item in choices)
        if boundary != "report":
            assert all("step 512" not in item.label for item in choices)
        assert untouched(root) == before
        active_root = controller.session.root
        controller.close_background(wait=True)
        controller.session.close()
        host.close()

    fresh_host = ComputationService()
    reopened = ProjectSession.open(active_root, computations=fresh_host)
    fresh = GitProjectController(reopened)
    try:
        assert reopened.experiment_context.attempt_id == frozen.attempt.id
        fresh.execute("recover_experiments", {})
        choice = next(
            item
            for item in fresh.execute("experiment_checkpoints", {"attempt_id": frozen.attempt.id})[
                "checkpoints"
            ]
            if "step 256" in item.label
        )
        resumed = finish_freeze(
            fresh,
            fresh.execute(
                "resume_checkpoint",
                {"attempt_id": choice.attempt_id, "publication_id": choice.publication_id},
            ),
        )
        result = fresh_host.wait(resumed.computation.id)
        assert result.outcome is ComputationOutcome.SUCCEEDED, result.diagnostics
        assert resumed.attempt.parent_attempt == frozen.attempt.id
        assert untouched(root) == before
    finally:
        fresh.close_background(wait=True)
        fresh.session.close()
        reopened.close()
        fresh_host.close()
