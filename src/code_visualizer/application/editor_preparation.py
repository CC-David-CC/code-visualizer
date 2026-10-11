"""Typed, editor-owned preparation using the existing supervised worker transport.

There is one active request and one replaceable pending request per editor. The
supervisor performs serialization and admission; registered generation runs in the
fixed worker. This is a disposable preparation adapter, not an authoring authority
or a scientific computation lifecycle.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Condition, Thread
from time import monotonic

from code_visualizer.domain.common import new_id
from code_visualizer.domain.computation import CancelRequest
from code_visualizer.domain.invocation import InvocationBindingError, bind_invocation
from code_visualizer.domain.invocation_arguments import InvocationArguments
from code_visualizer.domain.project import Project
from code_visualizer.domain.resource_transfer import ResourceTransferFinish, ResourceTransferStart
from code_visualizer.domain.values import ResourceReference
from code_visualizer.domain.worker import (
    WorkerEditorPreparationRequest,
    WorkerEditorPrepared,
    WorkerFailure,
    WorkerResourceEvent,
)
from code_visualizer.execution.runtime import RuntimeBindingSpec, program_binding_specs
from code_visualizer.execution.worker_process import (
    WorkerChannel,
    WorkerExited,
    WorkerProcess,
    WorkerProfile,
    profile_for_backend,
)
from code_visualizer.extensions.registry import DomainExtensionRegistry
from code_visualizer.generation.emitter import GeneratedProject, GenerationError
from code_visualizer.persistence.resource_store import MAX_RESOURCE_READ_BYTES, ResourceStore
from code_visualizer.persistence.resource_transfer import (
    ResourceTransferReceiver,
    resource_transfer_frames,
)
from code_visualizer.persistence.serialization import project_data_chunks
from code_visualizer.protocol.worker import worker_control_to_bytes, worker_event_from_bytes


@dataclass(frozen=True, slots=True)
class EditorPreparedSnapshot:
    request_id: str
    project_id: str
    revision: int
    status: str
    source_digest: str = ""
    generated: GeneratedProject | None = None
    binding_specs: tuple[RuntimeBindingSpec, ...] = ()
    diagnostic: str = ""


@dataclass(frozen=True, slots=True)
class _Request:
    identity: str
    project: Project
    focus_diagram_id: str | None
    model_id: str | None
    arguments: InvocationArguments | None


class EditorPreparation:
    """A latest-request mailbox owned by one editor attachment.

    Submit/cancel/snapshot never wait for worker execution. The only background
    entrypoint is this adapter's typed preparation operation, not a caller-supplied
    callback. A custom extension composition requires an explicit worker profile.
    """

    def __init__(
        self,
        *,
        profiles: tuple[WorkerProfile, ...] | None = None,
        resource_store: ResourceStore | None = None,
    ) -> None:
        self._profiles = profiles
        self._resource_store = resource_store
        self._condition = Condition()
        self._pending: _Request | None = None
        self._view: EditorPreparedSnapshot | None = None
        self._cache: tuple[_Request, EditorPreparedSnapshot] | None = None
        self._worker: WorkerProcess | None = None
        self._worker_id: str | None = None
        self._closed = False
        self._thread: Thread | None = None

    def submit(
        self,
        project: Project,
        *,
        focus_diagram_id: str | None = None,
        model_id: str | None = None,
        arguments: InvocationArguments | None = None,
    ) -> str:
        with self._condition:
            if self._closed:
                raise RuntimeError("Editor preparation is closed")
            identity = new_id("editor-preparation")
            # Validate the small target immediately, without touching author state.
            WorkerEditorPreparationRequest(
                identity,
                ResourceReference("pending", "0" * 64),
                project.id,
                project.revision,
                focus_diagram_id,
                model_id,
                arguments,
            )
            self._pending = _Request(identity, project, focus_diagram_id, model_id, arguments)
            self._view = EditorPreparedSnapshot(identity, project.id, project.revision, "queued")
            if self._worker is not None and self._worker_id is not None:
                self._worker.cancel(worker_control_to_bytes(CancelRequest(self._worker_id)))
            cached = self._cache
            if cached is not None:
                previous, admitted = cached
                invocation = admitted.generated.invocation if admitted.generated else None
                # A preview already contains a bound, validated invocation.
                # Explicit Run/Trace/Debug arguments with exactly those values
                # need no second generation. A default request never adopts an
                # earlier override, and changed values still go through binding.
                same_arguments = previous.arguments == arguments or (
                    previous.arguments is None
                    and arguments is not None
                    and invocation is not None
                    and invocation.arguments == arguments
                )
                if (
                    previous.project is project
                    and (
                        previous.focus_diagram_id,
                        previous.model_id,
                    )
                    == (focus_diagram_id, model_id)
                    and same_arguments
                ):
                    self._pending = None
                    self._view = replace(admitted, request_id=identity)
                    self._condition.notify_all()
                    return identity
                self._cache = None
            if self._thread is None:
                self._thread = Thread(target=self._run, daemon=True, name="editor-preparation")
                self._thread.start()
            self._condition.notify_all()
            return identity

    def snapshot(self) -> EditorPreparedSnapshot | None:
        with self._condition:
            return self._view

    def cancel(self) -> None:
        with self._condition:
            self._pending = None
            if self._view is not None and self._view.status in {"queued", "preparing"}:
                self._view = replace(self._view, status="cancelled")
            if self._worker is not None and self._worker_id is not None:
                self._worker.cancel(worker_control_to_bytes(CancelRequest(self._worker_id)))
            self._condition.notify_all()

    def close(self, *, wait: bool = False) -> None:
        with self._condition:
            self._closed = True
            self._cache = None
            self.cancel()
            thread = self._thread
        if wait and thread is not None:
            thread.join(timeout=10)

    def _publish(
        self,
        request: _Request,
        *,
        status: str | None = None,
        source_digest: str | None = None,
        generated: GeneratedProject | None = None,
        binding_specs: tuple[RuntimeBindingSpec, ...] | None = None,
        diagnostic: str | None = None,
    ) -> None:
        with self._condition:
            view = self._view
            if (
                not self._closed
                and view is not None
                and view.request_id == request.identity
                and view.status != "cancelled"
            ):
                self._view = replace(
                    view,
                    status=status if status is not None else view.status,
                    source_digest=source_digest
                    if source_digest is not None
                    else view.source_digest,
                    generated=generated if generated is not None else view.generated,
                    binding_specs=binding_specs
                    if binding_specs is not None
                    else view.binding_specs,
                    diagnostic=diagnostic if diagnostic is not None else view.diagnostic,
                )
                if self._view.status == "ready" and self._view.generated is not None:
                    self._cache = (request, self._view)
                self._condition.notify_all()

    def _run(self) -> None:
        while True:
            with self._condition:
                while self._pending is None and not self._closed:
                    self._condition.wait()
                if self._closed:
                    return
                request, self._pending = self._pending, None
            assert request is not None
            try:
                self._prepare(request)
            except Exception as exc:
                self._publish(request, status="failed", diagnostic=f"{type(exc).__name__}: {exc}")

    def _prepare(self, request: _Request) -> None:
        from code_visualizer.application.computation_process import (
            default_profiles,
            worker_resource_environment,
        )
        from code_visualizer.persistence.python_execution import load_python_execution_artifact

        self._publish(request, status="preparing")
        profiles = default_profiles() if self._profiles is None else self._profiles
        profile = profile_for_backend(profiles, "code_visualizer.python", "1")
        temporary = TemporaryDirectory(prefix="code-visualizer-editor-preparation-")
        store = ResourceStore(Path(temporary.name), inputs=self._resource_store)
        worker: WorkerProcess | None = None
        receiver: ResourceTransferReceiver | None = None
        try:
            source = store.put(
                b"".join(project_data_chunks(request.project)),
                "application/vnd.code-visualizer.project+json;version=11",
            )
            control = WorkerEditorPreparationRequest(
                request.identity,
                source.reference,
                request.project.id,
                request.project.revision,
                request.focus_diagram_id,
                request.model_id,
                request.arguments,
            )
            worker = WorkerProcess(profile, environment=worker_resource_environment(store))
            with self._condition:
                view = self._view
                if (
                    self._closed
                    or view is None
                    or view.request_id != request.identity
                    or view.status == "cancelled"
                ):
                    return
            worker.start()
            worker.send(worker_control_to_bytes(control))
            with self._condition:
                self._worker, self._worker_id = worker, request.identity
                view = self._view
                cancelled = (
                    self._closed
                    or view is None
                    or view.request_id != request.identity
                    or view.status == "cancelled"
                )
            if cancelled:
                worker.cancel(worker_control_to_bytes(CancelRequest(request.identity)))
            self._publish(request, source_digest=source.content_hash)
            prepared: WorkerEditorPrepared | None = None
            transferred: ResourceReference | None = None
            deadline = monotonic() + 120
            while True:
                try:
                    event = worker_event_from_bytes(
                        worker.receive(timeout=max(0.01, deadline - monotonic()))
                    )
                except WorkerExited as exc:
                    if exc.return_code == 0 and prepared is not None and receiver is None:
                        break
                    raise
                if event.session_id != request.identity or prepared is not None:
                    raise ValueError("Preparation produced an unrelated or repeated result")
                if isinstance(event, WorkerResourceEvent):
                    frame = event.frame
                    if isinstance(frame, ResourceTransferStart):
                        if receiver is not None or transferred is not None:
                            raise ValueError(
                                "Editor preparation permits exactly one emitted artifact"
                            )
                        receiver = ResourceTransferReceiver(
                            store,
                            frame.resource.reference,
                            max_resource_bytes=MAX_RESOURCE_READ_BYTES,
                        )
                    if receiver is None:
                        raise ValueError("Editor resource transfer has no start")
                    receiver.accept(frame)
                    if isinstance(frame, ResourceTransferFinish):
                        transferred = receiver.commit().reference
                        receiver.close()
                        receiver = None
                elif isinstance(event, WorkerEditorPrepared):
                    if (
                        event.source_digest != source.content_hash
                        or event.execution_artifact != transferred
                    ):
                        raise ValueError(
                            "Prepared editor artifact differs from its source or transfer"
                        )
                    prepared = event
                    worker.expect_exit()
                elif isinstance(event, WorkerFailure):
                    raise GenerationError(f"{event.diagnostic.code}: {event.diagnostic.message}")
                else:
                    raise ValueError("Unexpected editor preparation event")
            assert prepared is not None
            artifact = load_python_execution_artifact(prepared.execution_artifact, store)
            origins = artifact.generated.origins
            if origins is not None and (origins.project_id, origins.revision) != (
                request.project.id,
                request.project.revision,
            ):
                raise ValueError(
                    "Prepared origin mapping differs from the captured author revision"
                )
            self._publish(
                request,
                status="ready",
                generated=artifact.generated,
                binding_specs=artifact.binding_specs,
            )
        finally:
            if receiver is not None:
                receiver.close()
            if worker is not None:
                worker.close()
            with self._condition:
                if self._worker is worker:
                    self._worker, self._worker_id = None, None
            temporary.cleanup()


def prepare_editor(
    request: WorkerEditorPreparationRequest,
    registry: DomainExtensionRegistry,
    store: ResourceStore,
    channel: WorkerChannel,
) -> None:
    """Fixed worker dispatch; binding, validation and generation stay off Qt."""
    from code_visualizer.application.program_model import function_for_document
    from code_visualizer.generation.python import prepare_python_project
    from code_visualizer.persistence.decoding import project_from_data
    from code_visualizer.persistence.python_execution import publish_python_execution
    from code_visualizer.protocol.worker import worker_event_to_bytes

    project = project_from_data(json.loads(store.read(request.project)))
    if (project.id, project.revision) != (request.project_id, request.revision):
        raise ValueError("Editor request does not identify its immutable source")
    invocation = None
    if request.arguments is not None:
        assert request.focus_diagram_id is not None
        function = function_for_document(project, request.focus_diagram_id)
        if function is None:
            raise GenerationError("Selected diagram has no canonical callable")
        try:
            invocation = bind_invocation(project.program_model, function, request.arguments)
        except InvocationBindingError as exc:
            raise GenerationError(f"{exc.code}: {exc}") from exc
    build, generated = prepare_python_project(
        project,
        extensions=registry,
        focus_diagram_id=request.focus_diagram_id,
        entrypoint_model_id=request.model_id,
        invocation=invocation,
    )
    artifact = publish_python_execution(
        generated, store, binding_specs=program_binding_specs(build.project.program_model)
    )
    for frame in resource_transfer_frames(store, artifact, request.session_id):
        channel.send(worker_event_to_bytes(WorkerResourceEvent(request.session_id, frame)))
    channel.send(
        worker_event_to_bytes(
            WorkerEditorPrepared(request.session_id, request.project.content_hash, artifact)
        )
    )
