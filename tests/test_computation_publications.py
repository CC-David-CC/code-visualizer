"""Sealed outputs survive worker lifetime without becoming authored project state."""

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from code_visualizer.application.computation import run_computation_plan
from code_visualizer.application.computation_publications import (
    PublicationBudget,
    seal_admitted_publication,
    seal_publication,
    seal_resource,
)
from code_visualizer.domain.boundaries import MAX_PORTABLE_ENVELOPE_BYTES
from code_visualizer.domain.computation import (
    BackendCapabilities,
    BackendDefinition,
    BackendExecutionMode,
    CancelRequest,
    ComputationParameter,
    ComputationRequest,
)
from code_visualizer.domain.evidence import ComputationOutcome, PublicationEvent
from code_visualizer.domain.identifiers import (
    BundlePublication,
    ContractDefinition,
    ContractKind,
    NamespaceGrant,
    NamespaceOwnership,
)
from code_visualizer.domain.intentional import (
    BundleReference,
    ConceptDefinition,
    DomainIssue,
    DomainModel,
    DomainSchema,
    DomainWorkspace,
    IntentionalNode,
)
from code_visualizer.domain.program import ProgramFunctionReference, ProgramModel, ProgramModule
from code_visualizer.domain.project import Project
from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.transformation import (
    PROGRAM_REPRESENTATION,
    OriginLink,
    OriginMap,
    Representation,
)
from code_visualizer.execution.backends import (
    BackendResult,
    PreparedComputation,
    ProducedResource,
    ProducedResourceEvent,
    RegisteredBackend,
    ResourceFile,
)
from code_visualizer.execution.lifecycle import BackendExecution
from code_visualizer.extensions.builtin import builtin_registry, computation_bundle
from code_visualizer.extensions.publication import FIRST_PARTY_OWNERSHIP
from code_visualizer.extensions.registry import DomainExtensionBundle, DomainExtensionRegistry
from code_visualizer.generation.computation import prepare_computation
from code_visualizer.generation.transformation import TransformationError
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.computation_resources import resolve_computation_resource
from code_visualizer.persistence.computation_terminal import (
    decode_terminal,
    load_terminal,
    publish_terminal,
)
from code_visualizer.persistence.evidence import (
    evidence_content_hash,
    evidence_from_data,
    evidence_to_data,
)
from code_visualizer.persistence.evidence_store import EvidenceStore, validate_portable_publication
from code_visualizer.persistence.project_resources import copy_project_resources
from code_visualizer.persistence.publications import (
    publication_content_hash,
    publication_from_data,
    publication_to_data,
)
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.serialization import project_to_data
from code_visualizer.protocol.computation import backend_from_proto, backend_to_proto
from code_visualizer.protocol.evidence import (
    evidence_to_proto,
    publication_event_from_proto,
    publication_event_to_proto,
    publication_from_proto,
    publication_to_proto,
)
from code_visualizer.protocol.v1.computation_pb2 import BackendDefinition as WireBackend

LOGICAL_TYPE = ResourceLogicalTypeReference("org.example.publications:model", "1")
PAYLOAD = b'{"items":[1,2,3]}'


@pytest.fixture
def publication_context(tmp_path):
    bundle = BundleReference("org.example.publications", "1")
    schema = DomainSchema(
        "schema",
        "org.example.publications",
        "1",
        (ConceptDefinition("concept", "Model"),),
        bundle=bundle,
    )
    model = DomainModel("model", schema.id, "1", ("node",), (IntentionalNode("node", "concept"),))
    project = Project(
        "project",
        "Publication",
        (),
        domain_workspace=DomainWorkspace((schema,), (model,), (bundle,)),
    )
    backend = RegisteredBackend(
        BackendDefinition(
            "org.example.publications.backend",
            "1",
            "Publication backend",
            Representation(schema.namespace),
            schema.id,
            "1",
            capabilities=BackendCapabilities(
                BackendExecutionMode.STREAMING, cancellation=True, publications=True
            ),
        ),
        stream=lambda _snapshot, _context: iter((BackendResult(),)),
    )
    registry = DomainExtensionRegistry(
        (
            computation_bundle(),
            DomainExtensionBundle(
                "org.example.publications",
                "1",
                schemas=(schema,),
                backends=(backend,),
                publication=BundlePublication("org.example.publisher"),
                contracts=(
                    ContractDefinition(ContractKind.RESOURCE_LOGICAL_TYPE, LOGICAL_TYPE.id, "1"),
                ),
            ),
        ),
        namespace_ownership=NamespaceOwnership(
            (*FIRST_PARTY_OWNERSHIP.grants, NamespaceGrant("org.example", "org.example.publisher"))
        ),
    )
    request = ComputationRequest(project.id, 0, backend.definition.id, "1", model.id)
    snapshot = prepare_computation(project, request, registry)
    resources = ResourceStore(tmp_path / "store")
    evidence = EvidenceStore(tmp_path / "store")
    plan = publish_terminal(snapshot, resources)
    return snapshot, plan, resources, evidence, registry, backend


def _event(**changes):
    resource = ProducedResource(
        "output", PAYLOAD, "application/json", ("node",), "Model", logical_type=LOGICAL_TYPE
    )
    return ProducedResourceEvent("session", 1, replace(resource, **changes))


def _seal(context, event=None, *, budget=None):
    snapshot, plan, resources, evidence, registry, _ = context
    return seal_publication(
        snapshot,
        event or _event(),
        plan.model,
        resources,
        evidence,
        registry,
        budget=budget or PublicationBudget(),
    )


def test_publication_is_durable_before_return_and_scientific_identity_ignores_clock(
    publication_context,
):
    snapshot, _, resources, evidence, _, _ = publication_context
    before = project_to_data(snapshot.project)
    first = _seal(publication_context)
    second = _seal(
        publication_context, replace(_event(), session_id="another-attempt", sequence=88)
    )
    assert first.publication == second.publication
    assert first != second
    assert evidence.get_publication(first.publication.id) == first.publication
    assert evidence.publication_identities() == (first.publication.id,)
    assert evidence.identities() == ()
    assert resources.read(first.publication.artifact.resource) == PAYLOAD
    assert project_to_data(snapshot.project) == before


def test_new_store_resolves_sealed_output_after_staging_file_is_deleted(
    publication_context, tmp_path
):
    _, _, _, evidence, _, _ = publication_context
    staging = tmp_path / "output.bin"
    staging.write_bytes(PAYLOAD)
    event = _event(
        data=None, file=ResourceFile(staging.resolve(), len(PAYLOAD), sha256(PAYLOAD).hexdigest())
    )
    publication = _seal(publication_context, event).publication
    staging.unlink()
    reopened = EvidenceStore(tmp_path / "store").get_publication(publication.id)
    resource = resolve_computation_resource(
        ResourceStore(tmp_path / "store"), reopened.artifact.resource
    )
    assert resource.descriptor.logical_type == LOGICAL_TYPE
    with resource.open() as stream:
        assert stream.read() == PAYLOAD
    assert evidence.identities() == ()  # No completed computation was manufactured.


def test_resource_valued_request_keeps_exact_publication_reference(publication_context):
    snapshot, _, resources, _, _, _ = publication_context
    publication = _seal(publication_context).publication
    request = replace(
        snapshot.request,
        configuration=(ComputationParameter("input", publication.artifact.resource),),
        resources=(publication.artifact.resource,),
    )
    resolved = resolve_computation_resource(resources, request.resources[0])
    assert resolved.descriptor.logical_type == LOGICAL_TYPE
    assert request.configuration[0].value == resolved.descriptor.reference
    with resolved.open() as stream:
        assert json.load(stream) == {"items": [1, 2, 3]}


def test_transferred_artifact_uses_same_receipt_without_reimport(publication_context, monkeypatch):
    snapshot, plan, resources, evidence, registry, _ = publication_context
    first = _seal(publication_context)

    def forbid(*_args, **_kwargs):
        raise AssertionError("An already admitted resource must not be imported again")

    monkeypatch.setattr(resources, "put", forbid)
    monkeypatch.setattr(resources, "import_file", forbid)
    second = seal_admitted_publication(
        snapshot,
        "remote",
        99,
        first.publication.artifact,
        plan.model,
        resources,
        evidence,
        registry,
        budget=PublicationBudget(),
    )
    assert second.publication == first.publication


@pytest.mark.parametrize("fault", ("origin", "type", "hash", "size"))
def test_invalid_publication_never_gets_a_durable_receipt(publication_context, tmp_path, fault):
    event = _event()
    if fault == "origin":
        event = _event(semantic_ids=("unrelated",))
    elif fault == "type":
        event = _event(logical_type=replace(LOGICAL_TYPE, version="999"))
    else:
        path = tmp_path / "source.bin"
        path.write_bytes(PAYLOAD)
        event = _event(
            data=None,
            file=ResourceFile(
                path.resolve(),
                len(PAYLOAD) + (1 if fault == "size" else 0),
                "a" * 64 if fault == "hash" else sha256(PAYLOAD).hexdigest(),
            ),
        )
    with pytest.raises((TransformationError, ValueError)):
        _seal(publication_context, event)
    assert publication_context[3].publication_identities() == ()


@pytest.mark.parametrize("missing", ("resources", "evidence", "terminal"))
def test_publication_requires_durable_context(publication_context, missing):
    snapshot, plan, resources, evidence, registry, _ = publication_context
    with pytest.raises(TransformationError, match="immutable terminal"):
        seal_publication(
            snapshot,
            _event(),
            None if missing == "terminal" else plan.model,
            None if missing == "resources" else resources,
            None if missing == "evidence" else evidence,
            registry,
            budget=PublicationBudget(),
        )
    assert evidence.publication_identities() == ()


def test_publication_only_recovery_copies_complete_resource_closure(publication_context, tmp_path):
    snapshot, plan, resources, evidence, _, _ = publication_context
    publication = _seal(publication_context).publication
    destination = tmp_path / "recovered"
    copy_project_resources(snapshot.project, resources, evidence, destination)
    recovered = EvidenceStore(destination)
    assert recovered.identities() == ()
    assert recovered.get_publication(publication.id) == publication
    assert ResourceStore(destination).read(publication.artifact.resource) == PAYLOAD
    assert ResourceStore(destination).read(plan.model) == resources.read(plan.model)


def test_receipt_rejects_mutation_and_hash_mismatch(publication_context):
    publication = _seal(publication_context).publication
    store = publication_context[3]
    bad = replace(publication, artifact=replace(publication.artifact, label="changed"))
    with pytest.raises(ValueError, match="hash"):
        store.put_publication(bad)
    path = store.put_publication(publication)
    data = json.loads(path.read_text())
    data["artifact"]["label"] = "disk corruption"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="hash"):
        store.get_publication(publication.id)


def test_publication_native_and_wire_roundtrips_are_deterministic(publication_context):
    event = _seal(publication_context)
    receipt = event.publication
    assert publication_from_data(publication_to_data(receipt)) == receipt
    assert publication_from_proto(publication_to_proto(receipt)) == receipt
    assert publication_event_from_proto(publication_event_to_proto(event)) == event
    assert receipt.id == "publication:" + publication_content_hash(receipt)
    for key in ("session_id", "sequence", "outcome"):
        assert key not in publication_to_data(receipt)


def test_publication_decoders_reject_unknown_fields_versions_and_envelope(publication_context):
    receipt = _seal(publication_context).publication
    data = publication_to_data(receipt)
    with pytest.raises(ValueError):
        publication_from_data({**data, "unknown": True})
    with pytest.raises(ValueError, match="version"):
        publication_from_data({**data, "version": 2})
    wire = publication_to_proto(receipt)
    wire.schema_version = 2
    with pytest.raises(ValueError, match="version"):
        publication_from_proto(wire)
    oversized = replace(
        receipt, artifact=replace(receipt.artifact, label="x" * MAX_PORTABLE_ENVELOPE_BYTES)
    )
    with pytest.raises(ValueError, match="2 MiB"):
        validate_portable_publication(oversized)


def test_publication_clock_and_terminal_are_explicit_invalid_states(publication_context):
    receipt = _seal(publication_context).publication
    for sequence in (-1, True, 1 << 64):
        with pytest.raises(ValueError, match="sequence"):
            PublicationEvent("session", sequence, receipt)
    with pytest.raises(ValueError, match="terminal"):
        replace(receipt, provenance=replace(receipt.provenance, terminal_resource=None))
    with pytest.raises(ValueError, match="streaming"):
        BackendCapabilities(publications=True)


def test_historical_evidence_and_backend_bytes_remain_exact():
    golden = json.loads(
        (Path(__file__).parent / "fixtures" / "publication_legacy_contracts.json").read_text()
    )
    evidence = evidence_from_data(golden["evidence"])
    assert evidence_to_data(evidence) == golden["evidence"]
    assert canonical_data_bytes(evidence_to_data(evidence)).hex() == golden["canonical_json_hex"]
    assert evidence_content_hash(evidence) == golden["content_hash"]
    assert (
        evidence_to_proto(evidence).SerializeToString(deterministic=True).hex()
        == golden["evidence_proto_hex"]
    )
    backend = backend_from_proto(WireBackend.FromString(bytes.fromhex(golden["backend_proto_hex"])))
    assert not backend.capabilities.publications
    assert (
        backend_to_proto(backend).SerializeToString(deterministic=True).hex()
        == golden["backend_proto_hex"]
    )
    changed = replace(backend, capabilities=replace(backend.capabilities, publications=True))
    assert backend_from_proto(backend_to_proto(changed)) == changed


@pytest.mark.parametrize("ending", ("success", "cancel", "crash"))
def test_lifecycle_seals_before_resume_and_retains_output_after_termination(
    publication_context, tmp_path, ending
):
    snapshot, plan, resources, evidence, registry, backend = publication_context
    source = tmp_path / "worker-stage.bin"
    cleanup = []

    def stream(_snapshot, context):
        source.write_bytes(PAYLOAD)
        try:
            yield ProducedResourceEvent(
                context.session_id,
                0,
                _event(
                    data=None,
                    file=ResourceFile(source.resolve(), len(PAYLOAD), sha256(PAYLOAD).hexdigest()),
                ).resource,
            )
            if ending == "crash":
                raise RuntimeError("worker failed after publication")
            yield BackendResult(
                ComputationOutcome.CANCELLED
                if context.cancellation_requested
                else ComputationOutcome.SUCCEEDED
            )
        finally:
            source.unlink()
            cleanup.append(True)

    driver = BackendExecution(
        "active-producer", replace(backend, stream=stream), snapshot, plan.model
    )
    try:
        offered = driver.advance()
        assert isinstance(offered, ProducedResourceEvent)
        assert source.exists()
        with pytest.raises(ValueError, match="admitted"):
            driver.advance()
        event = seal_publication(
            snapshot, offered, plan.model, resources, evidence, registry, budget=PublicationBudget()
        )
        driver.acknowledge_publication(event)
        assert driver.pending_publication is None
        assert not driver.finished
        with resolve_computation_resource(
            resources, event.publication.artifact.resource
        ).open() as consumer:
            assert consumer.read() == PAYLOAD  # Independent input while producer remains active.
        if ending == "cancel":
            driver.cancel(CancelRequest(driver.session.id))
        if ending == "crash":
            with pytest.raises(RuntimeError, match="after publication"):
                driver.advance()
        else:
            result = driver.advance()
            assert result.artifacts == (event.publication.artifact,)
            assert result.outcome == (
                ComputationOutcome.CANCELLED if ending == "cancel" else ComputationOutcome.SUCCEEDED
            )
            assert source.exists()
            driver.verify_completion()
        assert cleanup == [True]
        assert not source.exists()
        reopened = EvidenceStore(tmp_path / "store").get_publication(event.publication.id)
        assert ResourceStore(tmp_path / "store").read(reopened.artifact.resource) == PAYLOAD
        assert evidence.identities() == ()
    finally:
        driver.close()


def test_publication_ack_requires_exact_session_sequence_and_artifact(publication_context):
    snapshot, plan, resources, evidence, registry, backend = publication_context

    def stream(_snapshot, context):
        yield replace(_event(), session_id=context.session_id)
        yield BackendResult()

    driver = BackendExecution("producer", replace(backend, stream=stream), snapshot, plan.model)
    try:
        offered = driver.advance()
        admitted = seal_publication(
            snapshot, offered, plan.model, resources, evidence, registry, budget=PublicationBudget()
        )
        for wrong in (
            replace(admitted, session_id="other"),
            replace(admitted, sequence=admitted.sequence + 1),
            replace(
                admitted,
                publication=replace(
                    admitted.publication,
                    artifact=replace(admitted.publication.artifact, id="wrong-output"),
                ),
            ),
        ):
            with pytest.raises(ValueError):
                driver.acknowledge_publication(wrong)
            assert driver.pending_publication is offered
        driver.acknowledge_publication(admitted)
        with pytest.raises(ValueError):
            driver.acknowledge_publication(admitted)
        driver.advance()
        driver.verify_completion()
    finally:
        driver.close()


@pytest.mark.parametrize("trailing", (False, True))
def test_portable_worker_uses_same_publication_admission_and_terminal_guard(
    publication_context, tmp_path, trailing
):
    snapshot, plan, resources, evidence, registry, backend = publication_context
    staging = tmp_path / "portable-worker.bin"
    after_ack = []

    def stream(_snapshot, context):
        staging.write_bytes(PAYLOAD)
        try:
            yield ProducedResourceEvent(
                context.session_id,
                0,
                _event(
                    data=None,
                    file=ResourceFile(staging.resolve(), len(PAYLOAD), sha256(PAYLOAD).hexdigest()),
                ).resource,
            )
            ids = evidence.publication_identities()
            assert len(ids) == 1
            receipt = evidence.get_publication(ids[0])
            after_ack.append(resources.read(receipt.artifact.resource))
            yield BackendResult()
            if trailing:
                yield BackendResult()
        finally:
            staging.unlink()

    registry = DomainExtensionRegistry(
        tuple(
            replace(bundle, backends=(replace(backend, stream=stream),))
            if bundle.id == "org.example.publications"
            else bundle
            for bundle in registry.bundles()
        ),
        namespace_ownership=registry.namespace_ownership,
    )
    before = project_to_data(snapshot.project)
    if trailing:
        with pytest.raises(TransformationError, match="after its terminal"):
            run_computation_plan(plan, registry, resources, evidence)
        assert evidence.identities() == ()
    else:
        result = run_computation_plan(plan, registry, resources, evidence)
        assert result.outcome is ComputationOutcome.SUCCEEDED
        assert resources.read(result.artifacts[0].resource) == PAYLOAD
        assert evidence.get(result.id) == result
    assert after_ack == [PAYLOAD]
    assert not staging.exists()
    assert len(evidence.publication_identities()) == 1
    assert project_to_data(snapshot.project) == before


def test_decode_terminal_is_inert_but_worker_load_runs_registered_validation(publication_context):
    _, plan, resources, _, registry, _ = publication_context
    calls = []

    def validate(_project, model):
        calls.append(model.id)
        return (DomainIssue("WORKER_VALIDATOR", "Worker behavioral validation", model.id),)

    registry = DomainExtensionRegistry(
        tuple(
            replace(bundle, validators=(validate,))
            if bundle.id == "org.example.publications"
            else bundle
            for bundle in registry.bundles()
        ),
        namespace_ownership=registry.namespace_ownership,
    )
    assert decode_terminal(plan, resources, registry).value.id == "model"
    assert calls == []
    with pytest.raises(TransformationError) as error:
        load_terminal(plan, resources, registry)
    assert error.value.code == "WORKER_VALIDATOR"
    assert calls == ["model"]


def test_decode_terminal_rejects_corrupt_program_ownership_without_callbacks(tmp_path):
    program = ProgramModel(
        modules=(ProgramModule("module", "main", (ProgramFunctionReference("missing"),)),)
    )
    request = ComputationRequest("project", 0, "code_visualizer.python", "1")
    snapshot = PreparedComputation(
        Project("project", "Input", (), program_model=program),
        request,
        PROGRAM_REPRESENTATION,
        program,
        OriginMap("project", 0, (OriginLink("module", ("module",)),)),
        (),
        "a" * 64,
    )
    store = ResourceStore(tmp_path)
    plan = publish_terminal(snapshot, store)
    with pytest.raises(TransformationError) as error:
        decode_terminal(plan, store, builtin_registry())
    assert error.value.code == "PROGRAM_UNRESOLVED_FUNCTION_REFERENCE"


@pytest.mark.parametrize("transferred", (False, True))
def test_cumulative_receipt_budget_rejects_before_commit(publication_context, transferred):
    original, _, resources, evidence, registry, _ = publication_context
    request = replace(
        original.request,
        configuration=tuple(
            ComputationParameter(f"parameter-{index}", "x" * 60_000) for index in range(16)
        ),
    )
    snapshot = prepare_computation(original.project, request, registry)
    plan = publish_terminal(snapshot, resources)
    budget = PublicationBudget()

    def publish(index):
        event = replace(_event(id=f"output-{index}"), sequence=index)
        if transferred:
            artifact = seal_resource(snapshot, event.resource, resources, registry)
            return seal_admitted_publication(
                snapshot,
                event.session_id,
                event.sequence,
                artifact,
                plan.model,
                resources,
                evidence,
                registry,
                budget=budget,
            )
        return seal_publication(
            snapshot,
            event,
            plan.model,
            resources,
            evidence,
            registry,
            budget=budget,
        )

    first, second = publish(0), publish(1)
    committed = evidence.publication_identities()
    assert set(committed) == {first.publication.id, second.publication.id}
    assert 1_900_000 < budget.used_bytes < MAX_PORTABLE_ENVELOPE_BYTES
    before = budget.used_bytes
    with pytest.raises(TransformationError) as error:
        publish(2)
    assert error.value.code == "COMPUTATION_PUBLICATION_LIMIT"
    assert budget.used_bytes == before
    assert evidence.publication_identities() == committed
    assert evidence.identities() == ()
