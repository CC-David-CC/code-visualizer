"""The managed Python adapter must obey host admission, including late disk failure."""

from dataclasses import replace
from threading import Event

from test_python_artifact_bindings import BYTES, host, project_with, request

from code_visualizer.application.computation import start_computation
from code_visualizer.domain.computation import CancelRequest, ResourceOutput
from code_visualizer.domain.evidence import ComputationOutcome

SOURCE = """from code_visualizer.execution.python_api import publish_bytes
from code_visualizer.domain.resources import ResourceLogicalTypeReference
kind = ResourceLogicalTypeReference('code_visualizer.python.byte_stream', '1')
publish_bytes('solid', b'first', logical_type=kind, media_type='application/octet-stream')
print('first acknowledged')
"""


def test_failed_second_receipt_preserves_first_acknowledged_output(tmp_path, monkeypatch):
    project = project_with(
        SOURCE
        + """publish_bytes('second', b'second', logical_type=kind,
    media_type='application/octet-stream')
print('second acknowledged')
"""
    )
    with host(project, tmp_path) as (service, kernel):
        put = kernel.evidence_store.put_publication

        def fail_second(publication):
            if publication.artifact.id == "python:output:second":
                raise OSError("receipt destination remains unwritable")
            return put(publication)

        monkeypatch.setattr(kernel.evidence_store, "put_publication", fail_second)
        configured = replace(
            request(project),
            outputs=(
                ResourceOutput("solid", BYTES, ("publish:operation",)),
                ResourceOutput("second", BYTES, ("publish:operation",)),
            ),
        )
        run = start_computation(kernel, configured)
        evidence = service.wait(run.id)
        assert evidence.outcome is ComputationOutcome.FAILED
        assert any("remains unwritable" in d.message for d in evidence.diagnostics)
        publication = next(iter(service.job(run.id).publications.values()))
        assert evidence.artifacts == (publication.artifact,)
        assert kernel.resource_store.read(publication.artifact.resource) == b"first"
        assert kernel.evidence_store.get_publication(publication.id) == publication


def test_cancel_during_receipt_write_waits_for_host_admission_before_cleanup(tmp_path, monkeypatch):
    entered, release = Event(), Event()
    project = project_with(SOURCE)
    with host(project, tmp_path) as (service, kernel):
        put = kernel.evidence_store.put_publication

        def blocked(publication):
            entered.set()
            assert release.wait(30), "test did not release receipt write"
            return put(publication)

        monkeypatch.setattr(kernel.evidence_store, "put_publication", blocked)
        run = start_computation(kernel, request(project))
        try:
            assert entered.wait(40)
            service.cancel(CancelRequest(run.id))
            assert not service.job(run.id).done.is_set()
        finally:
            release.set()
        evidence = service.wait(run.id)
        assert evidence.outcome is ComputationOutcome.CANCELLED, evidence.diagnostics
        publication = next(iter(service.job(run.id).publications.values()))
        assert publication.artifact in evidence.artifacts
        assert kernel.evidence_store.get_publication(publication.id) == publication
        assert service.job(run.id).managed is None
        assert kernel.resource_store.read(publication.artifact.resource) == b"first"
