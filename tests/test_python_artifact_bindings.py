"""Named typed requests retain historical encoding and normal Python package execution."""

from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256

import pytest
from test_generated_symbol_execution_parity import _action

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.computation import execute_computation, start_computation
from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.project_factory import create_default_project
from code_visualizer.domain.computation import (
    CancelRequest,
    ComputationParameter,
    ComputationRequest,
    ResourceInput,
    ResourceOutput,
)
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.values import ResourceReference
from code_visualizer.persistence.computation import (
    computation_request_from_data,
    computation_request_to_data,
)
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.serialization import project_to_data
from code_visualizer.protocol.computation import (
    computation_request_from_proto,
    computation_request_to_proto,
)

BYTES = ResourceLogicalTypeReference("code_visualizer.python.byte_stream", "1")


def project_with(source):
    project = create_default_project()
    function = project.program_model.functions[0]
    function = replace(
        function, body=replace(function.body, statements=(_action("publish:operation", source),))
    )
    return replace(project, program_model=replace(project.program_model, functions=(function,)))


@contextmanager
def host(project, path):
    service = ComputationService()
    kernel = ProjectKernel(
        ProjectAuthority(project),
        computations=service,
        resource_store=ResourceStore(path),
        evidence_store=EvidenceStore(path),
    )
    try:
        yield service, kernel
    finally:
        kernel.close()
        service.close()


def request(project, *, outputs=True, inputs=()):
    return ComputationRequest(
        project.id,
        project.revision,
        "code_visualizer.python",
        "2",
        configuration=(ComputationParameter("timeout_seconds", 30),),
        inputs=inputs,
        outputs=(ResourceOutput("solid", BYTES, ("publish:operation",)),) if outputs else (),
    )


def test_old_request_bytes_and_new_roundtrips():
    old = ComputationRequest("p", 2, "code_visualizer.python", "1")
    data = computation_request_to_data(old)
    assert set(data) == {
        "project_id",
        "revision",
        "backend_id",
        "backend_version",
        "model_id",
        "configuration",
        "seed",
        "resources",
    }
    proto = computation_request_to_proto(old)
    assert proto.schema_version == 1 and not proto.inputs and not proto.outputs
    new = replace(
        old,
        inputs=(ResourceInput("input", ResourceReference("r", "0" * 64), BYTES),),
        outputs=(ResourceOutput("output", BYTES, ("node",)),),
    )
    assert computation_request_from_data(computation_request_to_data(new)) == new
    assert computation_request_from_proto(computation_request_to_proto(new)) == new
    assert computation_request_to_proto(new).schema_version == 2
    invalid = computation_request_to_proto(new)
    invalid.schema_version = 1
    with pytest.raises(ValueError):
        computation_request_from_proto(invalid)
    data.update(version=2, inputs=[], outputs=[])
    with pytest.raises(ValueError, match="historical"):
        computation_request_from_data(data)


def test_python_publication_is_acknowledged_and_consumed_by_new_host(tmp_path):
    source = """from code_visualizer.execution.python_api import publish_bytes
from code_visualizer.domain.resources import ResourceLogicalTypeReference
from pathlib import Path
import os
assert Path(__file__).exists()
os.write(1, b'native output cannot be a protocol frame\\n')
receipt = publish_bytes('solid', b'CAD-test' * 400000,
    logical_type=ResourceLogicalTypeReference('code_visualizer.python.byte_stream', '1'),
    media_type='application/octet-stream')
print('ACK:' + receipt)
"""
    project = project_with(source)
    before = project_to_data(project)
    with host(project, tmp_path) as (service, kernel):
        session = start_computation(kernel, request(project))
        result = service.wait(session.id)
        assert result.outcome is ComputationOutcome.SUCCEEDED, result.diagnostics
        publications = tuple(service.job(session.id).publications.values())
        assert len(publications) == 1
        publication = publications[0]
        assert kernel.evidence_store.get_publication(publication.id) == publication

        assert publication.artifact in result.artifacts
        reference = publication.artifact.resource
        assert reference.content_hash == sha256(b"CAD-test" * 400000).hexdigest()
        assert any("ACK:" + publication.id in str(o.value) for o in result.observations)
        assert any(
            "native output cannot be a protocol frame" in str(o.value) for o in result.observations
        )
        assert project_to_data(kernel.authority.snapshot()) == before
        assert service.job(session.id).managed is None
    consumer = project_with("""from code_visualizer.execution.python_api import input_resource
from code_visualizer.domain.resources import ResourceLogicalTypeReference
import hashlib
kind = ResourceLogicalTypeReference('code_visualizer.python.byte_stream', '1')
data = input_resource('geometry', kind).read_bytes()
print(hashlib.sha256(data).hexdigest())
""")
    with host(consumer, tmp_path) as (_, kernel):
        result = execute_computation(
            kernel,
            request(consumer, outputs=False, inputs=(ResourceInput("geometry", reference, BYTES),)),
        )
        assert result.outcome is ComputationOutcome.SUCCEEDED, result.diagnostics
        assert reference in result.provenance.resources
        assert any(reference.content_hash in str(o.value) for o in result.observations)


def test_required_output_absence_is_a_failed_computation(tmp_path):
    project = project_with("print('no output')")
    with host(project, tmp_path) as (_, kernel):
        result = execute_computation(kernel, request(project))
        assert result.outcome is ComputationOutcome.FAILED
        assert any(d.code == "COMPUTATION_OUTPUT_MISSING" for d in result.diagnostics)


def test_publication_survives_later_failure(tmp_path):
    project = project_with("""from code_visualizer.execution.python_api import publish_bytes
from code_visualizer.domain.resources import ResourceLogicalTypeReference
kind = ResourceLogicalTypeReference('code_visualizer.python.byte_stream', '1')
publish_bytes('solid', b'preserve', logical_type=kind, media_type='application/octet-stream')
int('later failure')
""")
    with host(project, tmp_path) as (service, kernel):
        session = start_computation(kernel, request(project))
        result = service.wait(session.id)
        assert result.outcome is ComputationOutcome.FAILED
        publication = next(iter(service.job(session.id).publications.values()))
        assert kernel.resource_store.read(publication.artifact.resource) == b"preserve"
        assert kernel.evidence_store.get_publication(publication.id) == publication


def test_cancel_keeps_already_acknowledged_python_artifact(tmp_path):
    project = project_with("""from code_visualizer.execution.python_api import publish_bytes
from code_visualizer.domain.resources import ResourceLogicalTypeReference
import time
kind = ResourceLogicalTypeReference('code_visualizer.python.byte_stream', '1')
publish_bytes('solid', b'retained', logical_type=kind, media_type='application/octet-stream')
time.sleep(60)
""")
    with host(project, tmp_path) as (service, kernel):
        session = start_computation(kernel, request(project))
        job = service.job(session.id)
        with job.condition:
            assert job.condition.wait_for(lambda: bool(job.publications) or job.done.is_set(), 30)
            assert job.publications, job.error
            publication = next(iter(job.publications.values()))
        assert not job.done.is_set()
        service.cancel(CancelRequest(session.id))
        result = service.wait(session.id)
        assert result.outcome is ComputationOutcome.CANCELLED
        assert publication.artifact in result.artifacts
        assert kernel.resource_store.read(publication.artifact.resource) == b"retained"


def test_typed_input_mismatch_never_launches_python(tmp_path):
    project = project_with("print('must not execute')")
    with host(project, tmp_path) as (service, kernel):
        wrong = kernel.resource_store.put(
            b"bytes without declared meaning", "application/octet-stream"
        )
        session = start_computation(
            kernel,
            request(
                project, outputs=False, inputs=(ResourceInput("geometry", wrong.reference, BYTES),)
            ),
        )
        with pytest.raises(ValueError, match="wrong logical type"):
            service.wait(session.id)
        assert service.job(session.id).managed is None
