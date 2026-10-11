"""Private supervised worker with a statically composed implementation registry."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from queue import Queue
from threading import Thread

if __name__ == "__main__" and not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from code_visualizer.domain.computation import CancelRequest
from code_visualizer.domain.evidence import EvidenceDiagnostic, ObservationEvent, PublicationEvent
from code_visualizer.domain.values import ResourceReference
from code_visualizer.domain.worker import (
    WorkerCompletionVerified,
    WorkerControl,
    WorkerEditorPreparationRequest,
    WorkerEvidenceProposal,
    WorkerExecutionRequest,
    WorkerFailure,
    WorkerPreparationRequest,
    WorkerPrepared,
    WorkerPublicationOffer,
    WorkerResourceEvent,
    WorkerTerminalSecured,
)
from code_visualizer.execution.backends import (
    BackendResult,
    PreparedComputation,
    ProducedResourceEvent,
    resource_references,
)
from code_visualizer.execution.lifecycle import BackendExecution
from code_visualizer.execution.worker_process import WorkerChannel, open_worker_channel
from code_visualizer.extensions.registry import DomainExtensionRegistry
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.resource_transfer import resource_transfer_frames
from code_visualizer.protocol.worker import worker_control_from_bytes, worker_event_to_bytes

RESOURCE_ROOT_ENV = "CODE_VISUALIZER_COMPUTATION_RESOURCES"
INPUT_RESOURCE_ROOT_ENV = "CODE_VISUALIZER_COMPUTATION_INPUT_RESOURCES"
PreparationAdapter = Callable[[PreparedComputation, ResourceStore], ResourceReference]


def _send_resources(
    channel: WorkerChannel,
    session_id: str,
    references: tuple[ResourceReference, ...],
    store: ResourceStore,
    *,
    sent: set[ResourceReference] | None = None,
) -> None:
    for index, reference in enumerate(references):
        if sent is not None and reference in sent:
            continue
        for frame in resource_transfer_frames(
            store, reference, f"{session_id}:{index}:{reference.content_hash}"
        ):
            channel.send(worker_event_to_bytes(WorkerResourceEvent(session_id, frame)))
        if sent is not None:
            sent.add(reference)


def _prepare(
    request: WorkerPreparationRequest,
    registry: DomainExtensionRegistry,
    store: ResourceStore,
    preparers: Mapping[tuple[str, str], PreparationAdapter],
    channel: WorkerChannel,
) -> None:
    from code_visualizer.application.computation import _resolve_resources, _validate_input_values
    from code_visualizer.extensions.languages import resolve_domain_languages
    from code_visualizer.generation.computation import prepare_computation
    from code_visualizer.persistence.computation_terminal import publish_terminal
    from code_visualizer.persistence.decoding import project_from_data

    project = project_from_data(json.loads(store.read(request.project)))
    installed = resolve_domain_languages(project, registry)
    snapshot = _resolve_resources(
        store, prepare_computation(project, request.request, installed), installed
    )
    _validate_input_values(snapshot, installed)
    plan = publish_terminal(snapshot, store)
    preparer = preparers.get((request.backend.id, request.backend.version))
    execution = preparer(snapshot, store) if preparer is not None else None
    _send_resources(
        channel, request.session_id, (plan.model, *((execution,) if execution else ())), store
    )
    channel.send(worker_event_to_bytes(WorkerPrepared(request.session_id, plan, execution)))


def _execute(
    request: WorkerExecutionRequest,
    registry: DomainExtensionRegistry,
    store: ResourceStore,
    channel: WorkerChannel,
) -> None:
    from code_visualizer.application.computation import _advance_backend, _evidence
    from code_visualizer.application.computation_publications import seal_resource
    from code_visualizer.application.resource_admission import (
        validate_resource_descriptor,
        validate_value_contracts,
    )
    from code_visualizer.persistence.computation_terminal import load_terminal

    snapshot = load_terminal(request.plan, store, registry)
    backend = registry.backend(request.backend.id, request.backend.version)
    assert backend is not None
    execution = BackendExecution(request.session_id, backend, snapshot, request.plan.model)
    controls: Queue[WorkerControl | Exception] = Queue(maxsize=8)

    def listen() -> None:
        try:
            while True:
                control = worker_control_from_bytes(channel.receive())
                if control.session_id != request.session_id:
                    raise ValueError("Worker control belongs to another attempt")
                if isinstance(control, CancelRequest):
                    if execution.session.cancellation_supported and not execution.finished:
                        execution.cancel(control)
                else:
                    controls.put(control)
                    if isinstance(control, WorkerTerminalSecured):
                        return
        except Exception as exc:
            controls.put(exc)

    def receive() -> WorkerControl:
        control = controls.get()
        if isinstance(control, Exception):
            raise control
        return control

    Thread(target=listen, name="computation-control", daemon=True).start()
    sent: set[ResourceReference] = set()
    try:
        while True:
            update = _advance_backend(execution)
            if isinstance(update, ProducedResourceEvent):
                artifact = seal_resource(snapshot, update.resource, store, registry)
                _send_resources(
                    channel,
                    request.session_id,
                    registry.resource_closure((artifact.resource,), store),
                    store,
                    sent=sent,
                )
                channel.send(
                    worker_event_to_bytes(
                        WorkerPublicationOffer(request.session_id, update.sequence, artifact)
                    )
                )
                receipt = receive()
                if not isinstance(receipt, PublicationEvent):
                    raise ValueError("A pending publication requires its admitted receipt")
                execution.acknowledge_publication(receipt)
            elif isinstance(update, BackendResult):
                for observation in update.observations:
                    validate_value_contracts(observation.value, registry)
                proposal = _evidence(snapshot, update, store, request.plan.model, registry=registry)
                for reference in resource_references((proposal.observations, proposal.artifacts)):
                    store.verified_path(reference)
                    validate_resource_descriptor(store.describe(reference), registry)
                _send_resources(
                    channel,
                    request.session_id,
                    registry.resource_closure(
                        resource_references((proposal.observations, proposal.artifacts)), store
                    ),
                    store,
                    sent=sent,
                )
                channel.send(
                    worker_event_to_bytes(WorkerEvidenceProposal(request.session_id, proposal))
                )
                secured = receive()
                if (
                    not isinstance(secured, WorkerTerminalSecured)
                    or secured.evidence_id != proposal.id
                ):
                    raise ValueError(
                        "A terminal result requires its exact resource-secured acknowledgment"
                    )
                execution.verify_completion()
                channel.send(worker_event_to_bytes(WorkerCompletionVerified(request.session_id)))
                return
            else:
                if isinstance(update, ObservationEvent):
                    validate_value_contracts(update.observation.value, registry)
                    for reference in resource_references(update.observation.value):
                        store.verified_path(reference)
                        validate_resource_descriptor(store.describe(reference), registry)
                channel.send(worker_event_to_bytes(update))
    finally:
        execution.close()


def serve(
    registry_factory: Callable[[], DomainExtensionRegistry],
    preparation_factory: Callable[[], Mapping[tuple[str, str], PreparationAdapter]] | None = None,
) -> int:
    """Trusted installed code supplies factories; requests never name imports or callbacks."""
    channel = open_worker_channel()
    session_id = "worker-startup"
    try:
        registry = registry_factory()
        preparers = preparation_factory() if preparation_factory is not None else {}
        root = os.environ.get(RESOURCE_ROOT_ENV)
        if root is None:
            raise ValueError("The host must supply an explicit computation resource root")
        input_root = os.environ.get(INPUT_RESOURCE_ROOT_ENV)
        store = ResourceStore(
            Path(root), inputs=None if input_root is None else ResourceStore(Path(input_root))
        )
        request = worker_control_from_bytes(channel.receive())
        if isinstance(request, WorkerEditorPreparationRequest):
            from code_visualizer.application.editor_preparation import prepare_editor

            session_id = request.session_id
            prepare_editor(request, registry, store, channel)
            return 0
        if not isinstance(request, WorkerPreparationRequest | WorkerExecutionRequest):
            raise ValueError("Worker requires one preparation or execution request")
        session_id = request.session_id
        backend = registry.backend(request.backend.id, request.backend.version)
        if backend is None or backend.definition != request.backend:
            raise ValueError(
                "Worker composition does not provide the exact submitted backend contract"
            )
        if isinstance(request, WorkerPreparationRequest):
            _prepare(request, registry, store, preparers, channel)
        else:
            _execute(request, registry, store, channel)
        return 0
    except Exception as exc:
        diagnostic = EvidenceDiagnostic(
            getattr(exc, "code", "COMPUTATION_WORKER_FAILED"), f"{type(exc).__name__}: {exc}"[:4096]
        )
        channel.send(worker_event_to_bytes(WorkerFailure(session_id, diagnostic)))
        return 1
    finally:
        channel.close()


def _preparers() -> Mapping[tuple[str, str], PreparationAdapter]:
    from code_visualizer.domain.program import ProgramModel
    from code_visualizer.execution.python_backend import prepare_python
    from code_visualizer.execution.runtime import program_binding_specs
    from code_visualizer.persistence.python_execution import publish_python_execution

    def python(snapshot: PreparedComputation, store: ResourceStore) -> ResourceReference:
        generated = prepare_python(snapshot)
        assert isinstance(snapshot.value, ProgramModel)
        return publish_python_execution(
            generated, store, binding_specs=program_binding_specs(snapshot.value)
        )

    return {("code_visualizer.python", "1"): python, ("code_visualizer.python", "2"): python}


def main() -> int:
    from code_visualizer.extensions.builtin import builtin_registry

    return serve(builtin_registry, _preparers)


if __name__ == "__main__":
    raise SystemExit(main())
