"""Resource interpretation requires an exact published contract at computation admission."""

from dataclasses import replace

import pytest
from computation_fixtures import InProcessTestKernel
from test_backend_lifecycle import CAPABILITIES, _setup

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.computation import (
    execute_computation,
    export_computation_plan,
    run_computation_plan,
)
from code_visualizer.application.worker_transport import (
    export_resource_stream,
    import_resource_stream,
    run_streamed_computation_plan,
)
from code_visualizer.domain.computation import BackendCapabilities
from code_visualizer.domain.evidence import (
    ComputationOutcome,
    EvidenceArtifact,
    EvidenceObservation,
    ObservationEvent,
)
from code_visualizer.domain.identifiers import (
    BundlePublication,
    ContractDefinition,
    ContractKind,
    NamespaceGrant,
    NamespaceOwnership,
)
from code_visualizer.domain.intentional import BundleReference
from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.execution.backends import BackendResult, ProducedResource, ResourceFile
from code_visualizer.extensions.builtin import computation_bundle
from code_visualizer.extensions.publication import FIRST_PARTY_OWNERSHIP
from code_visualizer.extensions.registry import DomainExtensionBundle, DomainExtensionRegistry
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.serialization import project_to_data
from code_visualizer.protocol.computation import computation_plan_to_proto
from code_visualizer.protocol.evidence import evidence_from_proto
from code_visualizer.protocol.v1 import evidence_pb2

TYPE = ResourceLogicalTypeReference("org.resourcecontract.data:waveform", "1")
OWNER = "org.resourcecontract.publisher"
OWNERSHIP = NamespaceOwnership(
    (*FIRST_PARTY_OWNERSHIP.grants, NamespaceGrant("org.resourcecontract", OWNER))
)
FAULTS = ("missing", "wrong-version", "wrong-kind", "invalid-closure", "registered")


def _supplier(fault):
    if fault == "missing":
        return ()
    return (
        DomainExtensionBundle(
            "org.resourcecontract.data",
            "1",
            publication=BundlePublication(OWNER),
            contracts=(
                ContractDefinition(
                    ContractKind.UNIT
                    if fault == "wrong-kind"
                    else ContractKind.RESOURCE_LOGICAL_TYPE,
                    TYPE.id,
                    "2" if fault == "wrong-version" else TYPE.version,
                ),
            ),
            required_bundles=(BundleReference("org.resourcecontract.unavailable", "1"),)
            if fault == "invalid-closure"
            else (),
        ),
    )


def _kernel(base, root, *, fault="registered", terminal_fault=None, resource_store=None):
    bundles = list(base.extensions.bundles())
    if terminal_fault is not None:
        bundles = [item for item in bundles if item.id != "code_visualizer.computation"]
        if terminal_fault != "missing":
            bundle = computation_bundle()
            contract = bundle.contracts[0]
            bundles.append(
                replace(
                    bundle,
                    contracts=(
                        replace(
                            contract,
                            kind=ContractKind.UNIT
                            if terminal_fault == "wrong-kind"
                            else contract.kind,
                            version=(
                                "999" if terminal_fault == "wrong-version" else contract.version
                            ),
                        ),
                    ),
                )
            )
    registry = DomainExtensionRegistry((*bundles, *_supplier(fault)), namespace_ownership=OWNERSHIP)
    return InProcessTestKernel(
        ProjectAuthority(base.authority.snapshot()),
        extensions=registry,
        resource_store=resource_store or ResourceStore(root),
        evidence_store=EvidenceStore(root),
    )


@pytest.mark.parametrize("fault", FAULTS)
@pytest.mark.parametrize("surface", ("local", "export", "portable", "streamed", "cached-worker"))
def test_input_logical_type_resolves_before_every_computation_surface(tmp_path, fault, surface):
    called = []

    def execute(snapshot):
        called.append(snapshot.request)
        return BackendResult()

    base, request, _, _ = _setup(None, BackendCapabilities(), execute=execute)
    author = _kernel(base, tmp_path / "author")
    descriptor = author.resource_store.put(
        b"samples", "application/octet-stream", logical_type=TYPE
    )
    request = replace(request, resources=(descriptor.reference,))
    plan = export_computation_plan(author, request)
    candidate = _kernel(
        base, tmp_path / "candidate", fault=fault, resource_store=author.resource_store
    )
    before = project_to_data(candidate.authority.snapshot())
    evidence_store = candidate.evidence_store
    worker = ResourceStore(tmp_path / "worker")

    def operation():
        if surface == "local":
            return execute_computation(candidate, request)
        if surface == "export":
            return export_computation_plan(candidate, request)
        if surface == "portable":
            return run_computation_plan(
                plan, candidate.extensions, author.resource_store, evidence_store
            )
        if surface == "cached-worker":
            streams = ()
            store = author.resource_store
        else:
            streams = tuple(
                (ref, export_resource_stream(author.resource_store, ref, f"input-{index}"))
                for index, ref in enumerate((*plan.request.resources, plan.model))
            )
            store = worker
        response = run_streamed_computation_plan(
            computation_plan_to_proto(plan).SerializeToString(deterministic=True),
            streams,
            candidate.extensions,
            store,
            evidence_store,
            max_total_bytes=1024 * 1024,
        )
        return evidence_from_proto(evidence_pb2.ComputationEvidence.FromString(response))

    try:
        if fault == "registered":
            operation()
            assert len(called) == (0 if surface == "export" else 1)
        else:
            with pytest.raises(ValueError):
                operation()
            assert called == []
            assert candidate.runtime.sessions() == ()
            assert evidence_store.identities() == ()
            if surface == "streamed":
                with pytest.raises(FileNotFoundError):
                    worker.describe(descriptor.reference)
        assert project_to_data(candidate.authority.snapshot()) == before
        assert author.resource_store.describe(descriptor.reference) == descriptor
        assert author.resource_store.read(descriptor.reference) == b"samples"
    finally:
        base.close()
        author.close()
        candidate.close()


@pytest.mark.parametrize("fault", FAULTS)
@pytest.mark.parametrize("execution_surface", ("local", "portable"))
@pytest.mark.parametrize(
    "surface", ("bytes", "file", "artifact", "observation", "live-observation")
)
def test_output_logical_type_resolves_before_evidence_or_live_publication(
    tmp_path, fault, surface, execution_surface
):
    source = ResourceStore(tmp_path / "source")
    descriptor = source.put(b"result samples", "application/octet-stream", logical_type=TYPE)
    called = []

    def result():
        if surface == "artifact":
            return BackendResult(
                artifacts=(EvidenceArtifact("artifact", descriptor.reference, ("node",)),)
            )
        if surface == "observation":
            return BackendResult(
                observations=(EvidenceObservation("observation", ("node",), descriptor.reference),)
            )
        return BackendResult(
            produced_resources=(
                ProducedResource(
                    "output",
                    data=b"result samples" if surface == "bytes" else None,
                    file=ResourceFile(
                        source.verified_path(descriptor.reference),
                        descriptor.byte_size,
                        descriptor.content_hash,
                    )
                    if surface == "file"
                    else None,
                    media_type="application/octet-stream",
                    logical_type=TYPE,
                    semantic_ids=("node",),
                ),
            )
        )

    def execute(snapshot):
        called.append(snapshot.request)
        return result()

    def stream(snapshot, context):
        called.append(snapshot.request)
        yield ObservationEvent(
            context.session_id, EvidenceObservation("live", ("node",), descriptor.reference)
        )
        yield BackendResult()

    base, request, _, _ = (
        _setup(stream, CAPABILITIES)
        if surface == "live-observation"
        else _setup(None, BackendCapabilities(), execute=execute)
    )
    candidate = _kernel(
        base,
        tmp_path / "candidate",
        fault=fault,
        resource_store=source
        if surface in {"artifact", "observation", "live-observation"}
        else None,
    )
    before = project_to_data(candidate.authority.snapshot())

    def operation():
        if execution_surface == "local":
            return execute_computation(candidate, request)
        plan = export_computation_plan(candidate, request)
        return run_computation_plan(
            plan, candidate.extensions, candidate.resource_store, candidate.evidence_store
        )

    try:
        if fault == "registered":
            evidence = operation()
            assert evidence.outcome == ComputationOutcome.SUCCEEDED
            assert candidate.resource_store.describe(descriptor.reference) == descriptor
        else:
            with pytest.raises(ValueError):
                operation()
            assert candidate.evidence_store.identities() == ()
            assert candidate.runtime.evidence_records() == ()
            assert candidate.runtime.computations() == ()
            if surface in {"bytes", "file"}:
                with pytest.raises(FileNotFoundError):
                    candidate.resource_store.describe(descriptor.reference)
        assert len(called) == 1
        assert project_to_data(candidate.authority.snapshot()) == before
        assert source.describe(descriptor.reference) == descriptor
        assert source.read(descriptor.reference) == b"result samples"
    finally:
        base.close()
        candidate.close()


@pytest.mark.parametrize("fault", ("missing", "wrong-version", "wrong-kind"))
@pytest.mark.parametrize("surface", ("local", "export", "portable", "streamed"))
def test_terminal_descriptor_needs_its_own_exact_contract(tmp_path, fault, surface):
    called = []

    def execute(snapshot):
        called.append(True)
        return BackendResult()

    base, request, _, _ = _setup(None, BackendCapabilities(), execute=execute)
    author = _kernel(base, tmp_path / "author")
    plan = export_computation_plan(author, request)
    candidate = _kernel(
        base, tmp_path / "candidate", terminal_fault=fault, resource_store=author.resource_store
    )
    try:
        with pytest.raises(ValueError):
            if surface == "local":
                execute_computation(candidate, request)
            elif surface == "export":
                export_computation_plan(candidate, request)
            elif surface == "portable":
                run_computation_plan(
                    plan, candidate.extensions, author.resource_store, candidate.evidence_store
                )
            else:
                run_streamed_computation_plan(
                    computation_plan_to_proto(plan).SerializeToString(deterministic=True),
                    (),
                    candidate.extensions,
                    author.resource_store,
                    candidate.evidence_store,
                    max_total_bytes=0,
                )
        assert called == []
        assert candidate.runtime.sessions() == ()
        assert candidate.evidence_store.identities() == ()
        assert author.resource_store.read(plan.model)
    finally:
        base.close()
        author.close()
        candidate.close()


def test_unknown_logical_type_can_be_stored_and_transferred_without_interpretation(tmp_path):
    source, target = ResourceStore(tmp_path / "source"), ResourceStore(tmp_path / "target")
    descriptor = source.put(b"future solver data", "application/octet-stream", logical_type=TYPE)
    import_resource_stream(
        target,
        descriptor.reference,
        export_resource_stream(source, descriptor.reference, "copy"),
        max_resource_bytes=1024,
    )
    assert target.describe(descriptor.reference) == descriptor
    assert target.read(descriptor.reference) == b"future solver data"
