"""Large resources cross local and portable backend boundaries without byte loading."""

import hashlib
import shutil

import pytest
from computation_fixtures import InProcessTestKernel

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.computation import (
    execute_computation,
    export_computation_plan,
    run_computation_plan,
)
from code_visualizer.domain.computation import BackendDefinition, ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome, EvidenceObservation
from code_visualizer.domain.intentional import (
    ConceptDefinition,
    DomainModel,
    DomainSchema,
    DomainWorkspace,
    IntentionalNode,
)
from code_visualizer.domain.project import Project
from code_visualizer.domain.transformation import Representation
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
from code_visualizer.generation.transformation import TransformationError
from code_visualizer.persistence import resource_store
from code_visualizer.persistence.computation import computation_plan_to_data
from code_visualizer.persistence.evidence import evidence_to_data
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.serialization import normalized_project_json


def _project():
    schema = DomainSchema(
        "stream:schema", "stream", "1", (ConceptDefinition("stream:node", "Node"),)
    )
    node = IntentionalNode("stream:instance", "stream:node")
    model = DomainModel("stream:model", schema.id, "1", (node.id,), (node,))
    return Project(
        "stream:project",
        "Streamed resources",
        (),
        domain_workspace=DomainWorkspace((schema,), (model,)),
    )


def _registry(implementation):
    backend = RegisteredBackend(
        BackendDefinition(
            "stream:backend",
            "1",
            "Streaming backend",
            Representation("stream"),
            "stream:schema",
            "1",
        ),
        implementation,
    )
    return DomainExtensionRegistry(
        (
            computation_bundle(),
            program_bundle(),
            intentional_bundle(),
            DomainExtensionBundle("stream", "1", backends=(backend,)),
        )
    )


def _input(tmp_path, monkeypatch):
    monkeypatch.setattr(resource_store, "MAX_RESOURCE_READ_BYTES", 64 * 1024)
    source = tmp_path / "input.bin"
    with source.open("wb") as stream:
        for _ in range(512):
            stream.write(bytes(range(256)))
    store = ResourceStore(tmp_path / "project")
    descriptor = store.import_file(source, "application/octet-stream")
    original_read = ResourceStore.read

    def bounded_read(self, reference):
        assert reference != descriptor.reference, "Large input reached the byte-only API"
        return original_read(self, reference)

    monkeypatch.setattr(ResourceStore, "read", bounded_read)
    return store, descriptor


def test_streamed_input_and_output_have_identical_local_and_portable_evidence(
    tmp_path, monkeypatch
):
    store, descriptor = _input(tmp_path, monkeypatch)
    input_paths, output_paths = [], []

    def backend(snapshot):
        resource = snapshot.resources[0]
        assert resource.data is None and resource.file is not None
        assert resource.file.byte_size == descriptor.byte_size
        assert resource.file.content_hash == descriptor.content_hash
        input_paths.append(resource.file.path)
        destination = tmp_path / f"backend-output-{len(input_paths)}.bin"
        digest, size = hashlib.sha256(), 0
        with resource.open() as source, destination.open("wb") as target:
            while chunk := source.read(4096):
                changed = bytes(value ^ 255 for value in chunk)
                target.write(changed)
                digest.update(changed)
                size += len(changed)
        output_paths.append(destination)
        return BackendResult(
            observations=(EvidenceObservation("stream:result", ("stream:instance",), size),),
            produced_resources=(
                ProducedResource(
                    "stream:output",
                    media_type="application/octet-stream",
                    semantic_ids=("stream:instance",),
                    file=ResourceFile(destination, size, digest.hexdigest()),
                ),
            ),
        )

    project, registry = _project(), _registry(backend)
    kernel = InProcessTestKernel(
        ProjectAuthority(project), extensions=registry, resource_store=store
    )
    request = ComputationRequest(
        project.id,
        project.revision,
        "stream:backend",
        "1",
        "stream:model",
        resources=(descriptor.reference,),
    )
    try:
        before = normalized_project_json(project)
        local = execute_computation(kernel, request)
        plan = export_computation_plan(kernel, request)
        worker_store = ResourceStore(tmp_path / "worker")
        shutil.copytree(store.root, worker_store.root)
        portable = run_computation_plan(plan, registry, worker_store)
        assert local == portable and local.outcome is ComputationOutcome.SUCCEEDED
        assert local.observations[0].value == descriptor.byte_size
        assert input_paths[0] != input_paths[1]
        assert all(path.exists() for path in output_paths), "The host deleted backend-owned files"
        output = store.describe(local.artifacts[0].resource)
        assert output.byte_size == descriptor.byte_size
        assert output.content_hash != descriptor.content_hash
        assert store.verified_path(output.reference).exists()
        assert worker_store.verified_path(output.reference).exists()
        assert normalized_project_json(kernel.authority.snapshot()) == before
        assert str(tmp_path) not in repr(computation_plan_to_data(plan))
        assert str(tmp_path) not in repr(evidence_to_data(local))
    finally:
        kernel.close()


@pytest.mark.parametrize("portable", (False, True))
def test_streamed_input_integrity_is_checked_before_backend_entry(tmp_path, monkeypatch, portable):
    store, descriptor = _input(tmp_path, monkeypatch)
    entered = []

    def backend(_snapshot):
        entered.append(True)
        return BackendResult()

    project, registry = _project(), _registry(backend)
    kernel = InProcessTestKernel(
        ProjectAuthority(project), extensions=registry, resource_store=store
    )
    request = ComputationRequest(
        project.id,
        project.revision,
        "stream:backend",
        "1",
        "stream:model",
        resources=(descriptor.reference,),
    )
    try:
        plan = export_computation_plan(kernel, request)
        path = store.verified_path(descriptor.reference)
        with path.open("r+b") as stream:
            stream.write(b"changed")
        with pytest.raises((ValueError, TransformationError), match="hash or byte size mismatch"):
            if portable:
                run_computation_plan(plan, registry, store)
            else:
                execute_computation(kernel, request)
        assert not entered
    finally:
        kernel.close()


@pytest.mark.parametrize("claim", ("hash", "size"))
def test_file_output_claims_are_checked_before_publication_without_deleting_source(tmp_path, claim):
    source = tmp_path / "backend-output.bin"
    source.write_bytes(b"result contents")
    size = source.stat().st_size
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    resource = ResourceFile(
        source, size + (claim == "size"), "0" * 64 if claim == "hash" else digest
    )

    def backend(_snapshot):
        return BackendResult(
            produced_resources=(
                ProducedResource("output", media_type="application/octet-stream", file=resource),
            )
        )

    project, registry = _project(), _registry(backend)
    store = ResourceStore(tmp_path / "project")
    kernel = InProcessTestKernel(
        ProjectAuthority(project), extensions=registry, resource_store=store
    )
    request = ComputationRequest(
        project.id, project.revision, "stream:backend", "1", "stream:model"
    )
    try:
        with pytest.raises(TransformationError, match="differs from declared") as failure:
            execute_computation(kernel, request)
        assert failure.value.code == "COMPUTATION_RESOURCE_OUTPUT"
        assert source.read_bytes() == b"result contents"
        assert not any(item.content_hash == digest for item in store.descriptors())
        assert not tuple((store.root / "staging").iterdir())
    finally:
        kernel.close()
