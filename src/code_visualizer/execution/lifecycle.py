"""Backend API v1: one cooperative lifecycle for batch and streaming execution."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from hashlib import sha256
from threading import Event

from code_visualizer.domain.boundaries import MAX_PORTABLE_ENVELOPE_BYTES
from code_visualizer.domain.computation import (
    CancelRequest,
    ComputationSession,
    ComputationStatus,
    ProgressEvent,
)
from code_visualizer.domain.evidence import (
    ComputationOutcome,
    EvidenceArtifact,
    EvidenceObservation,
    ObservationEvent,
    PublicationEvent,
)
from code_visualizer.domain.preview import PreviewEvent
from code_visualizer.domain.values import ResourceReference
from code_visualizer.execution.backends import (
    BackendContext,
    BackendResult,
    BackendUpdate,
    PreparedComputation,
    ProducedResourceEvent,
    RegisteredBackend,
)
from code_visualizer.generation.transformation import value_identities
from code_visualizer.protocol.computation import progress_to_proto
from code_visualizer.protocol.evidence import (
    artifact_to_proto,
    observation_event_to_proto,
    publication_event_to_proto,
)
from code_visualizer.protocol.preview import preview_to_proto
from code_visualizer.protocol.v1.evidence_pb2 import ComputationEvidence as WireEvidence


class BackendExecution:
    """An ephemeral driver, advanced by the host; no worker or scheduler is hidden.

    Start does not call implementation code. Each advance asks for one update;
    cancellation is cooperative and never promises to interrupt a blocked next().
    Stream observation sequences and progress share one strictly increasing clock.
    Streamed observations are collected exactly once into the terminal result.
    """

    def __init__(
        self,
        session_id: str,
        backend: RegisteredBackend,
        snapshot: PreparedComputation,
        terminal_resource: ResourceReference | None = None,
    ) -> None:
        request = snapshot.request
        if (request.backend_id, request.backend_version) != (
            backend.definition.id,
            backend.definition.version,
        ) or snapshot.representation != backend.definition.input_representation:
            raise ValueError("A lifecycle must match the admitted backend and representation")
        self.backend = backend
        self.snapshot = snapshot
        self.terminal_resource = terminal_resource
        self.session = ComputationSession(
            session_id,
            request.project_id,
            request.revision,
            request.backend_id,
            request.backend_version,
            ComputationStatus.QUEUED,
            backend.definition.capabilities.cancellation,
        )
        self.result: BackendResult | None = None
        self._context = BackendContext(session_id, Event())
        self._stream: Iterator[BackendUpdate] | None = None
        self._completion_verified = False
        self._sequence = -1
        self._observations: list[EvidenceObservation] = []
        self._observation_ids: set[str] = set()
        self._observation_bytes = 0
        self._pending_publication: ProducedResourceEvent | None = None
        self._publications: dict[str, EvidenceArtifact] = {}
        self._pending_publication_bytes = 0
        self._available = value_identities(snapshot.value) | {
            node.id for model in snapshot.dependency_models for node in model.nodes
        }

    @property
    def finished(self) -> bool:
        return self.result is not None

    def cancel(self, request: CancelRequest) -> ComputationSession:
        if request.session_id != self.session.id:
            raise ValueError("Cancellation belongs to another session")
        if self.finished:
            raise ValueError("A terminal computation cannot be cancelled")
        if not self.session.cancellation_supported:
            raise ValueError("This backend does not support cancellation")
        self._context._cancelled.set()
        return self.session

    def advance(self) -> BackendUpdate:
        if self.finished:
            raise ValueError("A terminal computation cannot emit more updates")
        if self._pending_publication is not None:
            raise ValueError("A staged publication must be admitted before its producer advances")
        if self.session.status == ComputationStatus.QUEUED:
            if self._context.cancellation_requested:
                return self.finish(BackendResult(ComputationOutcome.CANCELLED))
            self.session = replace(self.session, status=ComputationStatus.RUNNING)
        if self.backend.execute is not None:
            return self.finish(self.backend.execute(self.snapshot))
        if self._stream is None:
            assert self.backend.stream is not None
            self._stream = iter(self.backend.stream(self.snapshot, self._context))
        try:
            update = next(self._stream)
        except StopIteration as exc:
            raise ValueError("A backend stream ended without a terminal result") from exc
        if isinstance(update, BackendResult):
            return self.finish(update)
        self.accept(update)
        return update

    @property
    def pending_publication(self) -> ProducedResourceEvent | None:
        return self._pending_publication

    def acknowledge_publication(self, event: PublicationEvent) -> None:
        pending = self._pending_publication
        if pending is None:
            raise ValueError("There is no pending publication to acknowledge")
        resource = pending.resource
        artifact = event.publication.artifact
        expected_hash = (
            resource.file.content_hash
            if resource.file is not None
            else sha256(resource.data or b"").hexdigest()
        )
        if (event.session_id, event.sequence) != (pending.session_id, pending.sequence) or (
            artifact.id,
            artifact.semantic_ids,
            artifact.label,
            artifact.resource.content_hash,
        ) != (resource.id, resource.semantic_ids, resource.label, expected_hash):
            raise ValueError("Publication acknowledgement differs from its staged output")
        provenance = event.publication.provenance
        if (
            provenance.project_id,
            provenance.revision,
            provenance.backend_id,
            provenance.backend_version,
            provenance.input_digest,
        ) != (
            self.snapshot.request.project_id,
            self.snapshot.request.revision,
            self.snapshot.request.backend_id,
            self.snapshot.request.backend_version,
            self.snapshot.input_digest,
        ):
            raise ValueError("Publication acknowledgement belongs to another computation input")
        encoded = publication_event_to_proto(event)
        contribution = WireEvidence(artifacts=(encoded.publication.artifact,)).ByteSize()
        if contribution != self._pending_publication_bytes:
            raise ValueError("Publication receipt differs from its admitted metadata budget")
        self._observation_bytes += contribution
        self._publications[artifact.id] = artifact
        self._pending_publication = None
        self._pending_publication_bytes = 0

    def accept(
        self, update: ProgressEvent | ObservationEvent | ProducedResourceEvent | PreviewEvent
    ) -> None:
        """Validate a received update before any runtime publication."""
        if self.session.status != ComputationStatus.RUNNING or self.finished:
            raise ValueError("Only a running computation can emit events")
        if self._pending_publication is not None:
            raise ValueError("A staged publication is still awaiting admission")
        if not isinstance(
            update, (ProgressEvent, ObservationEvent, ProducedResourceEvent, PreviewEvent)
        ):
            raise ValueError("A backend update must use the closed typed event vocabulary")
        if update.session_id != self.session.id:
            raise ValueError("A backend event belongs to another session")
        capabilities = self.backend.definition.capabilities
        if isinstance(update, PreviewEvent):
            contract = self.backend.preview
            if contract is None or contract.logical_type != update.interpretation:
                raise ValueError("Backend did not declare this preview interpretation")
            if (
                update.input_digest != self.snapshot.input_digest
                or set(update.semantic_ids) - self._available
            ):
                raise ValueError("A preview belongs to another source/input origin")
            contract.validate(update)
            sequence = update.sequence
        elif isinstance(update, ProgressEvent):
            if not capabilities.progress:
                raise ValueError("This backend did not declare live progress")
            sequence = update.sequence
        elif isinstance(update, ProducedResourceEvent):
            if not capabilities.publications:
                raise ValueError("This backend did not declare live publications")
            sequence = update.sequence
            resource = update.resource
            if set(resource.semantic_ids) - self._available:
                raise ValueError("A live publication names an unknown input origin")
            if resource.id in self._publications or resource.id in self._observation_ids:
                raise ValueError("A publication identity cannot be repeated")
            if len(self._publications) >= 10000:
                raise ValueError("Publication metadata is bounded; publish an indexed resource")
            # Content-addressed resource IDs and hashes have fixed wire lengths.
            # Reserve the exact artifact budget before a host can commit its receipt.
            artifact = EvidenceArtifact(
                resource.id,
                ResourceReference("resource:" + "0" * 64, "0" * 64),
                resource.semantic_ids,
                resource.label,
            )
            contribution = WireEvidence(artifacts=(artifact_to_proto(artifact),)).ByteSize()
            if self._observation_bytes + contribution > MAX_PORTABLE_ENVELOPE_BYTES:
                raise ValueError("Publication metadata exceeds 2 MiB; publish an indexed resource")
            self._pending_publication_bytes = contribution
        else:
            if not capabilities.observations:
                raise ValueError("This backend did not declare live observations")
            observation = update.observation
            sequence = observation.sequence
            if set(observation.semantic_ids) - self._available:
                raise ValueError("A live observation names an unknown input origin")
            if observation.id in self._observation_ids or observation.id in self._publications:
                raise ValueError("A live observation identity cannot be repeated")
            if len(self._observations) >= 10000:
                raise ValueError("Live observation metadata is bounded; use resources for series")
        if sequence <= self._sequence:
            raise ValueError("Backend events require strictly increasing shared sequences")
        # Enforce the exact portable envelope before accumulation or publication.
        # These are the same adapters used by external workers and automation.
        if isinstance(update, ObservationEvent):
            encoded = observation_event_to_proto(update)
            # Measure exactly the repeated observation field in portable evidence.
            # The final admission also counts provenance, diagnostics and artifacts.
            contribution = WireEvidence(observations=(encoded.observation,)).ByteSize()
            if self._observation_bytes + contribution > MAX_PORTABLE_ENVELOPE_BYTES:
                raise ValueError(
                    "Live observation metadata exceeds 2 MiB; place series in resources"
                )
            self._observations.append(update.observation)
            self._observation_ids.add(update.observation.id)
            self._observation_bytes += contribution
        elif isinstance(update, ProgressEvent):
            progress_to_proto(update)
        elif isinstance(update, PreviewEvent):
            preview_to_proto(update)
        else:
            self._pending_publication = update
        self._sequence = sequence

    def finish(self, result: BackendResult) -> BackendResult:
        if self.finished:
            raise ValueError("A computation can finish exactly once")
        if not isinstance(result, BackendResult):
            raise ValueError("A backend must return a typed terminal result")
        if self._pending_publication is not None:
            raise ValueError("A staged publication must be admitted before terminal completion")
        result_ids = (
            *(item.id for item in result.artifacts),
            *(item.id for item in result.produced_resources),
            *(item.id for item in result.observations),
        )
        if set(result_ids).intersection(self._publications):
            raise ValueError("An acknowledged publication cannot be emitted again at completion")
        if self.session.status != ComputationStatus.RUNNING and not (
            self.session.status == ComputationStatus.QUEUED
            and self._context.cancellation_requested
            and result.outcome == ComputationOutcome.CANCELLED
        ):
            raise ValueError("A computation must start before producing a terminal result")
        if self.backend.stream is not None and result.observations:
            raise ValueError("Streaming observations must arrive as events, exactly once")
        if result.outcome == ComputationOutcome.CANCELLED and not (
            self.session.cancellation_supported and self._context.cancellation_requested
        ):
            raise ValueError("A backend cannot report cancellation without an accepted request")
        if self._context.cancellation_requested and result.outcome == ComputationOutcome.SUCCEEDED:
            raise ValueError("A backend must acknowledge cancellation before reporting success")
        result = replace(
            result,
            artifacts=(
                *self._publications.values(),
                *result.artifacts,
            ),
        )
        self.result = (
            replace(result, observations=tuple(self._observations))
            if self.backend.stream
            else result
        )
        return self.result

    def verify_completion(self) -> None:
        """Check stream termination after securing outputs, before evidence publication.

        Resuming the iterator can run its finally blocks and delete staging files.
        The application must import/verify those files before this check. A trailing
        update invalidates the terminal result and cannot become published evidence.
        """
        if not self.finished:
            raise ValueError("A computation must return a terminal result before completion")
        if self._completion_verified:
            return
        if self._stream is not None:
            try:
                next(self._stream)
            except StopIteration:
                pass
            else:
                raise ValueError("A backend stream emitted data after its terminal result")
        self._completion_verified = True
        assert self.result is not None
        self.session = replace(self.session, status=ComputationStatus(self.result.outcome.value))

    def close(self) -> None:
        stream, self._stream = self._stream, None
        close = getattr(stream, "close", None)
        if close is not None:
            close()
