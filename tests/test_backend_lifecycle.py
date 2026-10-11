"""Backend API v1 is a real cooperative protocol on the existing runtime plane."""

from dataclasses import replace

import pytest
from computation_fixtures import InProcessTestKernel

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.computation import (
    advance_computation,
    cancel_computation,
    computation_sessions,
    execute_computation,
    export_computation_plan,
    run_computation_plan,
    start_computation,
)
from code_visualizer.domain.boundaries import MAX_PORTABLE_ENVELOPE_BYTES
from code_visualizer.domain.computation import (
    BackendCapabilities,
    BackendDefinition,
    BackendExecutionMode,
    CancelRequest,
    ComputationRequest,
    ComputationStatus,
    ProgressEvent,
)
from code_visualizer.domain.evidence import (
    ComputationEvidence,
    ComputationOutcome,
    EvidenceObservation,
    ObservationEvent,
)
from code_visualizer.domain.intentional import (
    ConceptDefinition,
    DomainModel,
    DomainSchema,
    DomainWorkspace,
    IntentionalNode,
)
from code_visualizer.domain.project import Project
from code_visualizer.domain.transformation import OriginLink, Representation
from code_visualizer.execution.backends import BackendResult, RegisteredBackend
from code_visualizer.execution.lifecycle import BackendExecution
from code_visualizer.extensions.builtin import computation_bundle
from code_visualizer.extensions.registry import DomainExtensionBundle, DomainExtensionRegistry
from code_visualizer.generation.computation import prepare_computation
from code_visualizer.generation.transformation import TransformationError
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.serialization import project_to_data
from code_visualizer.protocol.computation import (
    backend_from_proto,
    backend_to_proto,
    progress_from_proto,
    progress_to_proto,
)
from code_visualizer.protocol.evidence import (
    observation_event_from_proto,
    observation_event_to_proto,
)

CAPABILITIES = BackendCapabilities(
    BackendExecutionMode.STREAMING,
    progress=True,
    observations=True,
    cancellation=True,
    deterministic=True,
)


def _stream(snapshot, context):
    yield ProgressEvent(context.session_id, 0, 0.0, 1.0, "Started")
    if context.cancellation_requested:
        yield BackendResult(ComputationOutcome.CANCELLED)
        return
    yield ObservationEvent(
        context.session_id, EvidenceObservation("observed", ("node",), 7, sequence=1)
    )
    yield ProgressEvent(context.session_id, 2, 1.0, 1.0, "Finished")
    yield BackendResult()


def _setup(stream=_stream, capabilities=CAPABILITIES, *, execute=None):
    schema = DomainSchema(
        "org.example.lifecycle:schema",
        "org.example.lifecycle",
        "1",
        (ConceptDefinition("org.example.lifecycle:item", "Item"),),
    )
    model = DomainModel(
        "model", schema.id, "1", ("node",), (IntentionalNode("node", schema.concepts[0].id),)
    )
    project = Project(
        "project", "Lifecycle", (), domain_workspace=DomainWorkspace((schema,), (model,))
    )
    definition = BackendDefinition(
        "org.example.lifecycle.backend",
        "1",
        "Lifecycle",
        Representation(schema.namespace),
        schema.id,
        "1",
        capabilities=capabilities,
    )
    backend = RegisteredBackend(definition, execute=execute, stream=stream)
    registry = DomainExtensionRegistry(
        (
            computation_bundle(),
            DomainExtensionBundle("org.example.lifecycle", "1", backends=(backend,)),
        )
    )
    kernel = InProcessTestKernel(ProjectAuthority(project), extensions=registry)
    request = ComputationRequest(project.id, project.revision, definition.id, "1", model.id)
    return kernel, request, backend, prepare_computation(project, request, registry)


def test_streaming_start_progress_observations_finish_use_existing_runtime_and_authority():
    kernel, request, _, _ = _setup()
    before = project_to_data(kernel.authority.snapshot())
    session = start_computation(kernel, request)
    assert session.status == ComputationStatus.QUEUED
    assert computation_sessions(kernel) == (session,)
    assert kernel.runtime.active.execution_session_id == session.id
    assert isinstance(advance_computation(kernel, session.id), ProgressEvent)
    assert computation_sessions(kernel)[0].status == ComputationStatus.RUNNING
    assert isinstance(advance_computation(kernel, session.id), ObservationEvent)
    assert kernel.runtime.active.origin_ids == ("node",)
    assert kernel.selection.state.semantic_ids == ("node",)
    assert isinstance(advance_computation(kernel, session.id), ProgressEvent)
    evidence = advance_computation(kernel, session.id)
    assert isinstance(evidence, ComputationEvidence)
    assert evidence.outcome == ComputationOutcome.SUCCEEDED
    assert len(evidence.observations) == 1
    assert [state.event_sequence for state in kernel.runtime.history(session.id)] == [0, 1, 2, 3, 4]
    assert computation_sessions(kernel)[0].evidence_id == evidence.id
    assert kernel.runtime.computation(session.id) is None
    assert project_to_data(kernel.authority.snapshot()) == before
    with pytest.raises(TransformationError, match="No active computation"):
        advance_computation(kernel, session.id)


@pytest.mark.parametrize("before_start", [True, False])
def test_cooperative_cancel_is_acknowledged_in_evidence(before_start):
    kernel, request, _, _ = _setup()
    session = start_computation(kernel, request)
    if not before_start:
        advance_computation(kernel, session.id)
    cancel_computation(kernel, CancelRequest(session.id, "user request"))
    evidence = advance_computation(kernel, session.id)
    assert isinstance(evidence, ComputationEvidence)
    assert evidence.outcome == ComputationOutcome.CANCELLED
    assert computation_sessions(kernel)[0].status == ComputationStatus.CANCELLED
    assert kernel.runtime.active.status.value == "stopped"


def test_batch_backend_uses_same_lifecycle_and_reports_unsupported_cancel():
    kernel, request, _, _ = _setup(
        None,
        BackendCapabilities(),
        execute=lambda _: BackendResult(
            observations=(EvidenceObservation("result", ("node",), 7),)
        ),
    )
    session = start_computation(kernel, request)
    assert not session.cancellation_supported
    with pytest.raises(TransformationError) as caught:
        cancel_computation(kernel, CancelRequest(session.id))
    assert caught.value.code == "COMPUTATION_CANCEL_UNSUPPORTED"
    evidence = advance_computation(kernel, session.id)
    assert isinstance(evidence, ComputationEvidence)
    assert evidence == execute_computation(kernel, request)


def test_synchronous_wrapper_consumes_stream_and_preserves_deterministic_evidence():
    kernel, request, _, _ = _setup()
    assert execute_computation(kernel, request) == execute_computation(kernel, request)


@pytest.mark.parametrize("version", [2, 99])
def test_registration_rejects_unknown_backend_api(version):
    _, _, backend, _ = _setup()
    with pytest.raises(ValueError, match="Unsupported backend API"):
        replace(backend, definition=replace(backend.definition, api_version=version))


def test_registration_capabilities_and_implementation_must_agree():
    _, _, backend, _ = _setup()
    with pytest.raises(ValueError, match="exactly one"):
        replace(backend, execute=lambda _: BackendResult())
    with pytest.raises(ValueError, match="require streaming"):
        BackendCapabilities(cancellation=True)
    with pytest.raises(ValueError, match="boolean guarantees"):
        BackendCapabilities(deterministic=1)


@pytest.mark.parametrize(
    "fault",
    [
        "session",
        "sequence",
        "origin",
        "identity",
        "capability",
        "after_finish",
        "missing_finish",
        "unrequested_cancel",
        "ignored_cancel",
        "duplicate_final_observations",
    ],
)
def test_stream_protocol_rejects_invalid_backend_behavior(fault):
    def broken(snapshot, context):
        yield ProgressEvent(context.session_id, 0, 0.0)
        if fault == "session":
            yield ProgressEvent("wrong", 1, 0.0)
        elif fault == "sequence":
            yield ProgressEvent(context.session_id, 0, 0.0)
        elif fault == "origin":
            yield ObservationEvent(
                context.session_id, EvidenceObservation("bad", ("missing",), 1, sequence=1)
            )
        elif fault == "identity":
            yield ObservationEvent(
                context.session_id, EvidenceObservation("same", ("node",), 1, sequence=1)
            )
            yield ObservationEvent(
                context.session_id, EvidenceObservation("same", ("node",), 2, sequence=2)
            )
        elif fault == "capability":
            yield ObservationEvent(
                context.session_id, EvidenceObservation("bad", ("node",), 1, sequence=1)
            )
        elif fault == "after_finish":
            yield BackendResult()
            yield ProgressEvent(context.session_id, 1, 1.0)
        elif fault == "missing_finish":
            return
        elif fault == "unrequested_cancel":
            yield BackendResult(ComputationOutcome.CANCELLED)
        elif fault == "ignored_cancel":
            yield BackendResult()
        else:
            yield BackendResult(observations=(EvidenceObservation("result", ("node",), 7),))

    caps = replace(CAPABILITIES, observations=False) if fault == "capability" else CAPABILITIES
    kernel, request, _, _ = _setup(broken, caps)
    session = start_computation(kernel, request)
    advance_computation(kernel, session.id)
    if fault == "ignored_cancel":
        cancel_computation(kernel, CancelRequest(session.id))
    if fault == "after_finish":
        with pytest.raises(TransformationError) as caught:
            advance_computation(kernel, session.id)
        assert caught.value.code == "COMPUTATION_BACKEND_PROTOCOL"
        assert kernel.runtime.evidence_records() == ()
        assert kernel.runtime.computations() == ()
        return
    while True:
        result = advance_computation(kernel, session.id)
        if isinstance(result, ComputationEvidence):
            break
    assert result.outcome == ComputationOutcome.FAILED
    assert result.diagnostics[0].code == "COMPUTATION_BACKEND_FAILED"


def test_driver_cannot_finish_twice_or_accept_events_before_start():
    _, _, backend, snapshot = _setup()
    driver = BackendExecution("session", backend, snapshot)
    with pytest.raises(ValueError, match="Only a running"):
        driver.accept(ProgressEvent("session", 0, 0.0))
    driver.advance()
    driver.finish(BackendResult())
    with pytest.raises(ValueError, match="exactly once"):
        driver.finish(BackendResult())
    with pytest.raises(ValueError, match="terminal computation"):
        driver.cancel(CancelRequest("session"))


def test_backend_api_and_capabilities_round_trip_and_unknown_versions_are_inert():
    _, _, backend, _ = _setup()
    definition = replace(backend.definition, api_version=99)
    assert backend_from_proto(backend_to_proto(definition)) == definition
    value = backend_to_proto(backend.definition)
    value.capabilities.execution_mode = 77
    with pytest.raises(ValueError, match="execution mode"):
        backend_from_proto(value)
    value = backend_to_proto(backend.definition)
    value.ClearField("capabilities")
    with pytest.raises(ValueError, match="capabilities"):
        backend_from_proto(value)


def test_lifecycle_is_exposed_through_existing_kernel_capabilities():
    kernel, request, _, _ = _setup()
    session = kernel.capabilities.invoke("execution.computation_start", {"request": request})
    progress = kernel.capabilities.invoke(
        "execution.computation_advance", {"session_id": session.id}
    )
    assert isinstance(progress, ProgressEvent)
    kernel.capabilities.invoke("execution.computation_cancel", {"session_id": session.id})
    evidence = kernel.capabilities.invoke(
        "execution.computation_advance", {"session_id": session.id}
    )
    assert evidence["outcome"] == "cancelled"
    assert kernel.authority.revision == request.revision


def test_streaming_portable_worker_has_identical_evidence_without_an_editor_authority(tmp_path):
    kernel, request, _, _ = _setup()
    kernel.resource_store = ResourceStore(tmp_path)
    kernel.evidence_store = EvidenceStore(tmp_path)
    plan = export_computation_plan(kernel, request)
    local = execute_computation(kernel, request)
    remote = run_computation_plan(plan, kernel.extensions, ResourceStore(tmp_path))
    assert local == remote
    assert local.provenance.terminal_resource == plan.model


def test_origin_link_does_not_authorize_an_object_absent_from_terminal_input():
    _, _, backend, snapshot = _setup()
    snapshot = replace(
        snapshot,
        origins=replace(
            snapshot.origins, links=(*snapshot.origins.links, OriginLink("absent", ("node",)))
        ),
    )
    driver = BackendExecution("session", backend, snapshot)
    driver.advance()
    with pytest.raises(ValueError, match="unknown input origin"):
        driver.accept(
            ObservationEvent("session", EvidenceObservation("bad", ("absent",), 7, sequence=1))
        )
    driver.close()


@pytest.mark.parametrize("kind", ("progress", "observation"))
def test_live_update_codecs_reject_oversized_metadata_in_both_directions(kind):
    huge = "x" * MAX_PORTABLE_ENVELOPE_BYTES
    if kind == "progress":
        encode, decode = progress_to_proto, progress_from_proto
        small = ProgressEvent("session", 0, 0.0)
        large = replace(small, message=huge)
        wire = encode(small)
        wire.message = huge
    else:
        encode, decode = observation_event_to_proto, observation_event_from_proto
        small = ObservationEvent("session", EvidenceObservation("o", ("node",), 1))
        large = replace(small, observation=replace(small.observation, label=huge))
        wire = encode(small)
        wire.observation.label = huge
    with pytest.raises(ValueError, match="exceeds 2 MiB"):
        encode(large)
    with pytest.raises(ValueError, match="exceeds 2 MiB"):
        decode(wire)


@pytest.mark.parametrize("kind", ("progress", "observation"))
def test_oversized_live_update_never_enters_runtime_or_evidence(kind):
    huge = "x" * MAX_PORTABLE_ENVELOPE_BYTES

    def stream(snapshot, context):
        if kind == "progress":
            yield ProgressEvent(context.session_id, 0, 0.0, message=huge)
        else:
            yield ObservationEvent(
                context.session_id, EvidenceObservation("bad", ("node",), 1, label=huge)
            )
        yield BackendResult()

    kernel, request, _, _ = _setup(stream)
    evidence = execute_computation(kernel, request)
    assert evidence.outcome == ComputationOutcome.FAILED
    assert evidence.observations == ()
    assert "exceeds 2 MiB" in evidence.diagnostics[0].message
    assert all(
        state.observation is None and state.progress is None for state in kernel.runtime.history()
    )


def test_accumulated_live_observations_share_portable_evidence_metadata_bound():
    label = "x" * (3 * MAX_PORTABLE_ENVELOPE_BYTES // 8)

    def stream(snapshot, context):
        for index in range(3):
            yield ObservationEvent(
                context.session_id,
                EvidenceObservation(
                    f"observation-{index}",
                    ("node",),
                    index,
                    label=label,
                    sequence=index,
                ),
            )
        yield BackendResult()

    kernel, request, _, _ = _setup(stream)
    evidence = execute_computation(kernel, request)
    assert evidence.outcome == ComputationOutcome.FAILED
    assert [item.id for item in evidence.observations] == ["observation-0", "observation-1"]
    assert "place series in resources" in evidence.diagnostics[0].message
    assert all(
        state.observation is None or state.observation.id != "observation-2"
        for state in kernel.runtime.history()
    )
