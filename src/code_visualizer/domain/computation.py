"""Inert, versioned contracts for computation over a semantic representation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.transformation import OriginMap, Representation
from code_visualizer.domain.values import (
    CanonicalValue,
    ResourceReference,
    canonical_value_key,
    validate_canonical_value,
)

BACKEND_API_VERSION = 1


class BackendExecutionMode(StrEnum):
    BATCH = "batch"
    STREAMING = "streaming"


@dataclass(frozen=True, slots=True)
class BackendCapabilities:
    """Declared implementation guarantees, independent of domain semantics."""

    execution_mode: BackendExecutionMode = BackendExecutionMode.BATCH
    progress: bool = False
    observations: bool = False
    cancellation: bool = False
    deterministic: bool = False
    seeded: bool = False
    external_worker: bool = False
    publications: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.execution_mode, BackendExecutionMode) or any(
            type(value) is not bool
            for value in (
                self.progress,
                self.observations,
                self.cancellation,
                self.deterministic,
                self.seeded,
                self.external_worker,
                self.publications,
            )
        ):
            raise ValueError("Backend capabilities require a typed mode and boolean guarantees")
        if self.execution_mode == BackendExecutionMode.BATCH and (
            self.progress or self.observations or self.cancellation or self.publications
        ):
            raise ValueError(
                "Live progress, observations, publications, and cancellation require streaming"
            )


@dataclass(frozen=True, slots=True, eq=False)
class ComputationParameter:
    name: str
    value: CanonicalValue

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("A computation parameter requires a nonempty name")
        validate_canonical_value(self.value)

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, ComputationParameter)
            and self.name == other.name
            and canonical_value_key(self.value) == canonical_value_key(other.value)
        )

    def __hash__(self) -> int:
        return hash((self.name, canonical_value_key(self.value)))


@dataclass(frozen=True, slots=True)
class BackendDefinition:
    id: str
    version: str
    title: str
    input_representation: Representation
    schema_id: str | None = None
    schema_version: str | None = None
    description: str = ""
    api_version: int = BACKEND_API_VERSION
    capabilities: BackendCapabilities = BackendCapabilities()

    def __post_init__(self) -> None:
        if type(self.api_version) is not int or not 1 <= self.api_version < 1 << 32:
            raise ValueError("A backend API version must be a positive unsigned 32-bit integer")
        if not isinstance(self.capabilities, BackendCapabilities):
            raise ValueError("A backend requires typed capabilities")
        if any(
            not isinstance(item, str) or not item for item in (self.id, self.version, self.title)
        ):
            raise ValueError("A backend requires an identity, version, and title")
        if not isinstance(self.input_representation, Representation):
            raise ValueError("A backend requires a typed input representation")
        if any(
            not isinstance(item, str) or not item
            for item in (self.input_representation.id, self.input_representation.version)
        ) or not isinstance(self.description, str):
            raise ValueError("Backend representation identity and description must be text")
        if (self.schema_id is None) != (self.schema_version is None):
            raise ValueError("A backend schema scope requires both identity and version")
        if self.schema_id == "" or self.schema_version == "":
            raise ValueError("Backend schema scope cannot be empty")
        if self.schema_id is not None and (
            not isinstance(self.schema_id, str) or not isinstance(self.schema_version, str)
        ):
            raise ValueError("Backend schema scope must be text")

    @property
    def key(self) -> str:
        return f"{self.id}@{self.version}"

    @property
    def schema(self) -> tuple[str, str] | None:
        if self.schema_id is None or self.schema_version is None:
            return None
        return self.schema_id, self.schema_version


def _binding_name(name: str) -> None:
    if not isinstance(name, str) or not name.isidentifier() or len(name) > 128:
        raise ValueError("A named resource requires a bounded identifier")


@dataclass(frozen=True, slots=True)
class ResourceInput:
    name: str
    resource: ResourceReference
    logical_type: ResourceLogicalTypeReference

    def __post_init__(self) -> None:
        _binding_name(self.name)
        if not isinstance(self.resource, ResourceReference) or not isinstance(
            self.logical_type, ResourceLogicalTypeReference
        ):
            raise ValueError("An input binds an exact resource and logical type/version")


@dataclass(frozen=True, slots=True)
class ResourceOutput:
    name: str
    logical_type: ResourceLogicalTypeReference
    semantic_ids: tuple[str, ...]
    required: bool = True

    def __post_init__(self) -> None:
        _binding_name(self.name)
        if (
            not isinstance(self.logical_type, ResourceLogicalTypeReference)
            or type(self.required) is not bool
        ):
            raise ValueError("An output requires a logical type/version and completion policy")
        if (
            type(self.semantic_ids) is not tuple
            or not 1 <= len(self.semantic_ids) <= 256
            or any(not isinstance(v, str) or not v or len(v) > 1024 for v in self.semantic_ids)
            or len(set(self.semantic_ids)) != len(self.semantic_ids)
        ):
            raise ValueError("An output requires bounded unique allowed source identities")


@dataclass(frozen=True, slots=True)
class ComputationRequest:
    project_id: str
    revision: int
    backend_id: str
    backend_version: str
    model_id: str | None = None
    configuration: tuple[ComputationParameter, ...] = ()
    seed: int | None = None
    resources: tuple[ResourceReference, ...] = ()
    inputs: tuple[ResourceInput, ...] = ()
    outputs: tuple[ResourceOutput, ...] = ()

    def __post_init__(self) -> None:
        if any(
            not isinstance(item, str) or not item
            for item in (self.project_id, self.backend_id, self.backend_version)
        ):
            raise ValueError("A computation requires project and backend identities")
        if type(self.revision) is not int or not 0 <= self.revision < 1 << 64:
            raise ValueError("A computation revision must be a nonnegative integer")
        if self.model_id is not None and (not isinstance(self.model_id, str) or not self.model_id):
            raise ValueError("A computation model identity cannot be empty")
        if self.seed is not None and (
            type(self.seed) is not int or not -(1 << 63) <= self.seed < 1 << 63
        ):
            raise ValueError("A computation seed must be an integer")
        if (
            type(self.configuration) is not tuple
            or len(self.configuration) > 128
            or any(not isinstance(item, ComputationParameter) for item in self.configuration)
        ):
            raise ValueError("Computation configuration must be a bounded immutable tuple")
        if (
            type(self.resources) is not tuple
            or len(self.resources) > 1024
            or any(not isinstance(item, ResourceReference) for item in self.resources)
        ):
            raise ValueError("Computation resources must be a bounded immutable tuple")
        names = [item.name for item in self.configuration]
        if any(not name for name in names) or len(names) != len(set(names)):
            raise ValueError("Computation parameters require unique nonempty names")
        identities = [item.id for item in self.resources]
        if len(identities) != len(set(identities)):
            raise ValueError("Computation resources require unique identities")
        for items, kind in ((self.inputs, ResourceInput), (self.outputs, ResourceOutput)):
            if (
                type(items) is not tuple
                or len(items) > 128
                or any(not isinstance(item, kind) for item in items)
                or len({item.name for item in items}) != len(items)
            ):
                raise ValueError("Resource bindings require bounded unique typed declarations")
        references = {item.id: item for item in self.resources}
        for binding in self.inputs:
            if (
                binding.resource.id in references
                and references[binding.resource.id] != binding.resource
            ):
                raise ValueError("Named input conflicts with resource closure")


@dataclass(frozen=True, slots=True)
class ComputationPlan:
    request: ComputationRequest
    representation: Representation
    model: ResourceReference
    transformations: tuple[str, ...]
    origins: OriginMap
    input_digest: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.request, ComputationRequest)
            or not isinstance(self.representation, Representation)
            or not isinstance(self.model, ResourceReference)
        ):
            raise ValueError(
                "A computation plan requires typed request, representation, and terminal resource"
            )
        if (
            type(self.transformations) is not tuple
            or any(not isinstance(item, str) or not item for item in self.transformations)
            or len(self.transformations) != len(set(self.transformations))
        ):
            raise ValueError(
                "A computation plan requires immutable ordered transformation identities"
            )
        if not isinstance(self.origins, OriginMap) or (
            self.origins.project_id,
            self.origins.revision,
        ) != (self.request.project_id, self.request.revision):
            raise ValueError("Plan origins must match its pinned request")
        if (
            not isinstance(self.input_digest, str)
            or len(self.input_digest) != 64
            or any(character not in "0123456789abcdef" for character in self.input_digest)
        ):
            raise ValueError("A computation plan requires a SHA-256 input digest")


class ComputationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ComputationSession:
    id: str
    project_id: str
    revision: int
    backend_id: str
    backend_version: str
    status: ComputationStatus
    cancellation_supported: bool = False
    evidence_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("A computation session requires an identity")
        ComputationRequest(self.project_id, self.revision, self.backend_id, self.backend_version)
        if (
            not isinstance(self.status, ComputationStatus)
            or type(self.cancellation_supported) is not bool
        ):
            raise ValueError("A computation session requires typed status and capabilities")
        if self.evidence_id is not None and (
            not isinstance(self.evidence_id, str) or not self.evidence_id
        ):
            raise ValueError("Session evidence identity must be text or absent")


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    session_id: str
    sequence: int
    completed: float
    total: float | None = None
    message: str = ""

    def __post_init__(self) -> None:
        if (
            not isinstance(self.session_id, str)
            or not self.session_id
            or type(self.sequence) is not int
            or not 0 <= self.sequence < 1 << 64
        ):
            raise ValueError("Progress requires a session identity and nonnegative sequence")
        if (
            type(self.completed) is not float
            or not math.isfinite(self.completed)
            or self.completed < 0
        ):
            raise ValueError("Progress completed must be a finite nonnegative float")
        if self.total is not None and (
            type(self.total) is not float
            or not math.isfinite(self.total)
            or self.total < self.completed
        ):
            raise ValueError("Progress total must be a finite float at least equal to completed")
        if not isinstance(self.message, str):
            raise ValueError("Progress message must be text")


@dataclass(frozen=True, slots=True)
class CancelRequest:
    session_id: str
    reason: str = ""

    def __post_init__(self) -> None:
        if (
            not isinstance(self.session_id, str)
            or not self.session_id
            or not isinstance(self.reason, str)
        ):
            raise ValueError("Cancellation requires a session identity and text reason")
