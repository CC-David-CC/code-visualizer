"""Trusted backend implementations consume immutable terminal snapshots."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, fields, is_dataclass
from io import BytesIO
from pathlib import Path
from threading import Event
from typing import BinaryIO

from code_visualizer.domain.computation import (
    BACKEND_API_VERSION,
    BackendDefinition,
    BackendExecutionMode,
    ComputationRequest,
    ProgressEvent,
)
from code_visualizer.domain.evidence import (
    ComputationOutcome,
    EvidenceArtifact,
    EvidenceDiagnostic,
    EvidenceObservation,
    ObservationEvent,
)
from code_visualizer.domain.intentional import DomainModel, DomainSchema, DomainWorkspace
from code_visualizer.domain.preview import PreviewEvent
from code_visualizer.domain.program import ProgramModel
from code_visualizer.domain.project import Project
from code_visualizer.domain.resources import (
    DataResource,
    ResourceLogicalTypeReference,
    TensorDescriptor,
)
from code_visualizer.domain.transformation import OriginMap, Representation
from code_visualizer.domain.values import ResourceReference


@dataclass(frozen=True, slots=True)
class ResourceFile:
    """Ephemeral file location with immutable content claims; never persisted.

    Input files are verified managed resources. Output files belong to the
    backend. Batch outputs remain available until the enclosing call returns;
    streaming outputs remain available until the host resumes the terminal yield,
    after importing their contents. The backend owns cleanup in either case.
    The host never deletes this caller-owned path.
    """

    path: Path
    byte_size: int
    content_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path) or not self.path.is_absolute():
            raise ValueError("A resource file requires an absolute ephemeral path")
        if type(self.byte_size) is not int or not 0 <= self.byte_size < 1 << 63:
            raise ValueError("A resource file requires a nonnegative signed 64-bit size")
        ResourceReference("ephemeral-file", self.content_hash)


@dataclass(frozen=True, slots=True)
class ResolvedResource:
    descriptor: DataResource
    data: bytes | None = None
    file: ResourceFile | None = None

    def __post_init__(self) -> None:
        if (self.data is None) == (self.file is None):
            raise ValueError("A resolved resource requires exactly one bytes or file input")
        if self.data is not None and (
            type(self.data) is not bytes or len(self.data) != self.descriptor.byte_size
        ):
            raise ValueError("Resolved bytes must match their resource size")
        if self.file is not None and (
            not isinstance(self.file, ResourceFile)
            or self.file.byte_size != self.descriptor.byte_size
            or self.file.content_hash != self.descriptor.content_hash
        ):
            raise ValueError("Resolved file claims must match their resource descriptor")

    def open(self) -> BinaryIO:
        """Open a caller-closed stream; file integrity was checked during resolution."""
        if self.data is not None:
            return BytesIO(self.data)
        assert self.file is not None
        return self.file.path.open("rb")


@dataclass(frozen=True, slots=True)
class PreparedComputation:
    project: Project
    request: ComputationRequest
    representation: Representation
    value: DomainModel | ProgramModel
    origins: OriginMap
    transformations: tuple[str, ...]
    input_digest: str
    entrypoint_ids: tuple[str, ...] = ()
    resources: tuple[ResolvedResource, ...] = ()
    dependency_models: tuple[DomainModel, ...] = ()


@dataclass(frozen=True, slots=True)
class ProducedResource:
    id: str
    data: bytes | None = None
    media_type: str = ""
    semantic_ids: tuple[str, ...] = ()
    label: str = ""
    tensor: TensorDescriptor | None = None
    logical_type: ResourceLogicalTypeReference | None = None
    file: ResourceFile | None = None
    dependencies: tuple[ProducedResource, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("A produced resource requires an identity")
        if (
            type(self.dependencies) is not tuple
            or len(self.dependencies) > 1023
            or any(
                not isinstance(item, ProducedResource) or item.dependencies
                for item in self.dependencies
            )
        ):
            raise ValueError("A produced root requires a bounded flat set of staged dependencies")
        if (self.data is None) == (self.file is None):
            raise ValueError("A produced resource requires exactly one bytes or file output")
        if self.data is not None and type(self.data) is not bytes:
            raise ValueError("Produced resource bytes must be immutable")
        if self.data is not None and len(self.data) > 64 * 1024 * 1024:
            raise ValueError("Produced resource exceeds the in-process payload bound")
        if self.file is not None and not isinstance(self.file, ResourceFile):
            raise ValueError("A produced file requires a typed resource file")
        if not isinstance(self.media_type, str) or not self.media_type:
            raise ValueError("A produced resource requires a media type")
        if type(self.semantic_ids) is not tuple or any(
            not isinstance(item, str) or not item for item in self.semantic_ids
        ):
            raise ValueError("Produced resource origins require immutable semantic identities")
        if len(self.semantic_ids) != len(set(self.semantic_ids)):
            raise ValueError("Produced resource origins cannot be duplicated")
        if self.tensor is not None and not isinstance(self.tensor, TensorDescriptor):
            raise ValueError("A produced tensor requires a typed descriptor")
        if self.logical_type is not None and not isinstance(
            self.logical_type, ResourceLogicalTypeReference
        ):
            raise ValueError("Logical type must be a typed public reference or absent")


@dataclass(frozen=True, slots=True)
class ProducedResourceEvent:
    """A staged output; its producer must retain the bytes until host admission."""

    session_id: str
    sequence: int
    resource: ProducedResource

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, str) or not self.session_id:
            raise ValueError("A publication requires its execution session identity")
        if type(self.sequence) is not int or not 0 <= self.sequence < 1 << 64:
            raise ValueError("A publication sequence must be an unsigned 64-bit integer")
        if not isinstance(self.resource, ProducedResource):
            raise ValueError("A publication requires a typed produced resource")


@dataclass(frozen=True, slots=True)
class BackendResult:
    outcome: ComputationOutcome = ComputationOutcome.SUCCEEDED
    observations: tuple[EvidenceObservation, ...] = ()
    artifacts: tuple[EvidenceArtifact, ...] = ()
    diagnostics: tuple[EvidenceDiagnostic, ...] = ()
    produced_resources: tuple[ProducedResource, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, ComputationOutcome):
            raise ValueError("A backend result requires a typed outcome")
        for records, kind in (
            (self.observations, EvidenceObservation),
            (self.artifacts, EvidenceArtifact),
            (self.diagnostics, EvidenceDiagnostic),
            (self.produced_resources, ProducedResource),
        ):
            if (
                type(records) is not tuple
                or len(records) > 10000
                or any(not isinstance(item, kind) for item in records)
            ):
                raise ValueError("Backend results require bounded immutable typed records")


@dataclass(frozen=True, slots=True)
class BackendContext:
    """Ephemeral cooperative control; never part of a request or persisted input."""

    session_id: str
    _cancelled: Event

    @property
    def cancellation_requested(self) -> bool:
        return self._cancelled.is_set()


BackendUpdate = (
    ProgressEvent | ObservationEvent | ProducedResourceEvent | PreviewEvent | BackendResult
)
BackendStream = Callable[[PreparedComputation, BackendContext], Iterator[BackendUpdate]]


@dataclass(frozen=True, slots=True)
class CheckpointContract:
    """Trusted backend restart adapter; no change to portable v1 backend definitions.

    The registered implementation consumes this resource-valued configuration
    parameter. Absence explicitly means restart is unsupported.
    """

    logical_type: ResourceLogicalTypeReference
    parameter: str

    def __post_init__(self) -> None:
        if not isinstance(self.logical_type, ResourceLogicalTypeReference):
            raise ValueError("Checkpoint interpretation requires a registered resource contract")
        if not isinstance(self.parameter, str) or not self.parameter:
            raise ValueError("Checkpoint binding requires a configuration parameter")


@dataclass(frozen=True, slots=True)
class PreviewContract:
    logical_type: ResourceLogicalTypeReference
    validate: Callable[[PreviewEvent], None]

    def __post_init__(self) -> None:
        if not isinstance(self.logical_type, ResourceLogicalTypeReference) or not callable(
            self.validate
        ):
            raise ValueError("A preview contract requires an exact registered type and validator")


@dataclass(frozen=True, slots=True)
class RegisteredBackend:
    definition: BackendDefinition
    execute: Callable[[PreparedComputation], BackendResult] | None = None
    stream: BackendStream | None = None
    checkpoint: CheckpointContract | None = None
    source_file_parameter_prefix: str | None = None
    preview: PreviewContract | None = None
    file_backed_inputs: bool = False
    cancellation_grace_seconds: float = 0.5

    def __post_init__(self) -> None:
        if not isinstance(self.definition, BackendDefinition):
            raise ValueError("A backend registration requires a typed definition")
        if self.preview is not None and (
            not isinstance(self.preview, PreviewContract)
            or self.definition.capabilities.execution_mode != BackendExecutionMode.STREAMING
        ):
            raise ValueError("Only streaming backends can declare a preview contract")
        if type(self.file_backed_inputs) is not bool:
            raise ValueError("Resource access policy must be explicit")
        if (
            type(self.cancellation_grace_seconds) not in (int, float)
            or not 0 <= self.cancellation_grace_seconds <= 60
        ):
            raise ValueError("Registered cancellation grace must be finite and between 0 and 60 s")
        if self.checkpoint is not None and not isinstance(self.checkpoint, CheckpointContract):
            raise ValueError("A checkpoint adapter requires a typed contract")
        if self.source_file_parameter_prefix is not None and (
            not isinstance(self.source_file_parameter_prefix, str)
            or not self.source_file_parameter_prefix
        ):
            raise ValueError("Source file binding requires a nonempty declared parameter prefix")
        if self.definition.api_version != BACKEND_API_VERSION:
            raise ValueError(f"Unsupported backend API version {self.definition.api_version}")
        mode = self.definition.capabilities.execution_mode
        if mode == BackendExecutionMode.BATCH:
            if not callable(self.execute) or self.stream is not None:
                raise ValueError("A batch backend requires exactly one execute implementation")
        elif not callable(self.stream) or self.execute is not None:
            raise ValueError("A streaming backend requires exactly one stream implementation")


def resource_references(value: object) -> tuple[ResourceReference, ...]:
    """Find handles in closed immutable input values without dereferencing them."""
    found: dict[str, ResourceReference] = {}

    def visit(item: object) -> None:
        if isinstance(item, ResourceReference):
            previous = found.get(item.id)
            if previous is not None and previous != item:
                raise ValueError("One resource identity names different content")
            found[item.id] = item
        elif is_dataclass(item) and not isinstance(item, type):
            for field in fields(item):
                visit(getattr(item, field.name))
        elif isinstance(item, tuple):
            for child in item:
                visit(child)

    visit(value)
    return tuple(found[key] for key in sorted(found))


def terminal_schemas(snapshot: PreparedComputation) -> tuple[DomainSchema, ...]:
    schemas = snapshot.project.domain_workspace.schemas
    concept_owners = {concept.id: schema.id for schema in schemas for concept in schema.concepts}
    required = {model.schema_id for model in snapshot.dependency_models}
    if isinstance(snapshot.value, DomainModel):
        required.add(snapshot.value.schema_id)
    pending = list(required)
    while pending:
        schema = snapshot.project.domain_workspace.schema(pending.pop())
        if schema is None:
            raise ValueError("Computation input schema is unavailable")
        for concept in schema.concepts:
            for role in (*concept.containment_roles, *concept.reference_roles):
                for allowed in role.allowed_concept_ids:
                    owner = concept_owners.get(allowed)
                    if owner is not None and owner not in required:
                        required.add(owner)
                        pending.append(owner)
    return tuple(
        sorted((schema for schema in schemas if schema.id in required), key=lambda item: item.id)
    )


def terminal_context(snapshot: PreparedComputation) -> Project:
    """A backend sees only the same immutable input context available to a worker."""

    models = (
        (snapshot.value, *snapshot.dependency_models)
        if isinstance(snapshot.value, DomainModel)
        else snapshot.dependency_models
    )
    return Project(
        snapshot.request.project_id,
        "Computation input",
        (),
        revision=snapshot.request.revision,
        program_model=snapshot.value
        if isinstance(snapshot.value, ProgramModel)
        else ProgramModel(),
        domain_workspace=DomainWorkspace(terminal_schemas(snapshot), models),
    )
