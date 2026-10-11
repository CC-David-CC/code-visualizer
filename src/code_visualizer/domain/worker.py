"""Closed inert worker messages; executable composition stays with the trusted host."""

from dataclasses import dataclass
from re import fullmatch

from code_visualizer.domain.computation import (
    BackendDefinition,
    CancelRequest,
    ComputationPlan,
    ComputationRequest,
    ProgressEvent,
)
from code_visualizer.domain.evidence import (
    ComputationEvidence,
    EvidenceArtifact,
    EvidenceDiagnostic,
    ObservationEvent,
    PublicationEvent,
)
from code_visualizer.domain.invocation_arguments import InvocationArguments
from code_visualizer.domain.preview import PreviewEvent
from code_visualizer.domain.resource_transfer import (
    ResourceTransferAbort,
    ResourceTransferChunk,
    ResourceTransferFinish,
    ResourceTransferFrame,
    ResourceTransferStart,
)
from code_visualizer.domain.values import ResourceReference


def _session(value: str) -> None:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 256:
        raise ValueError("A worker message requires a session identity of at most 256 bytes")


def _artifact(value: ResourceReference | None) -> None:
    if value is not None and not isinstance(value, ResourceReference):
        raise ValueError("An execution artifact must be a resource reference or absent")


@dataclass(frozen=True, slots=True)
class WorkerPreparationRequest:
    session_id: str
    project: ResourceReference
    request: ComputationRequest
    backend: BackendDefinition

    def __post_init__(self) -> None:
        _session(self.session_id)
        if not isinstance(self.project, ResourceReference) or not isinstance(
            self.request, ComputationRequest
        ):
            raise ValueError("Preparation requires a project resource and computation request")
        _backend(self.request, self.backend)


def _backend(request: ComputationRequest, backend: BackendDefinition) -> None:
    if not isinstance(backend, BackendDefinition) or (
        request.backend_id,
        request.backend_version,
    ) != (backend.id, backend.version):
        raise ValueError("The expected backend contract must match the computation request")


@dataclass(frozen=True, slots=True)
class WorkerExecutionRequest:
    session_id: str
    plan: ComputationPlan
    backend: BackendDefinition
    execution_artifact: ResourceReference | None = None

    def __post_init__(self) -> None:
        _session(self.session_id)
        if not isinstance(self.plan, ComputationPlan):
            raise ValueError("Execution requires an immutable computation plan")
        _backend(self.plan.request, self.backend)
        if self.plan.representation != self.backend.input_representation:
            raise ValueError("The plan must match the expected backend representation")
        _artifact(self.execution_artifact)


@dataclass(frozen=True, slots=True)
class WorkerEditorPreparationRequest:
    session_id: str
    project: ResourceReference
    project_id: str
    revision: int
    focus_diagram_id: str | None = None
    model_id: str | None = None
    arguments: InvocationArguments | None = None

    def __post_init__(self) -> None:
        _session(self.session_id)
        if not isinstance(self.project, ResourceReference):
            raise ValueError("Editor preparation requires an immutable project resource")
        if not isinstance(self.project_id, str) or not self.project_id:
            raise ValueError("Editor preparation requires a project identity")
        if type(self.revision) is not int or not 0 <= self.revision < 1 << 64:
            raise ValueError("Editor preparation requires a nonnegative revision")
        for target in (self.focus_diagram_id, self.model_id):
            if target is not None and (not isinstance(target, str) or not target):
                raise ValueError("An editor target must be a nonempty identity or absent")
        if self.focus_diagram_id is not None and self.model_id is not None:
            raise ValueError("An editor preparation cannot select both a diagram and a model")
        if self.arguments is not None and (
            not isinstance(self.arguments, InvocationArguments) or self.focus_diagram_id is None
        ):
            raise ValueError("Literal argument overrides require a selected diagram")


@dataclass(frozen=True, slots=True)
class WorkerEditorPrepared:
    session_id: str
    source_digest: str
    execution_artifact: ResourceReference

    def __post_init__(self) -> None:
        _session(self.session_id)
        if not isinstance(self.source_digest, str) or not fullmatch(
            r"[0-9a-f]{64}", self.source_digest
        ):
            raise ValueError("Editor preparation requires its exact SHA-256 source digest")
        if not isinstance(self.execution_artifact, ResourceReference):
            raise ValueError("Editor preparation requires an execution artifact reference")


@dataclass(frozen=True, slots=True)
class WorkerPrepared:
    session_id: str
    plan: ComputationPlan
    execution_artifact: ResourceReference | None = None

    def __post_init__(self) -> None:
        _session(self.session_id)
        if not isinstance(self.plan, ComputationPlan):
            raise ValueError("Prepared output requires an immutable computation plan")
        _artifact(self.execution_artifact)


@dataclass(frozen=True, slots=True)
class WorkerResourceEvent:
    session_id: str
    frame: ResourceTransferFrame

    def __post_init__(self) -> None:
        _session(self.session_id)
        if not isinstance(
            self.frame,
            ResourceTransferStart
            | ResourceTransferChunk
            | ResourceTransferFinish
            | ResourceTransferAbort,
        ):
            raise ValueError("A worker resource event requires a typed resource frame")


@dataclass(frozen=True, slots=True)
class WorkerPublicationOffer:
    session_id: str
    sequence: int
    artifact: EvidenceArtifact

    def __post_init__(self) -> None:
        _session(self.session_id)
        if type(self.sequence) is not int or not 0 <= self.sequence < 1 << 64:
            raise ValueError("A worker publication requires a nonnegative sequence")
        if not isinstance(self.artifact, EvidenceArtifact):
            raise ValueError("A worker publication offer requires a typed artifact")


@dataclass(frozen=True, slots=True)
class WorkerEvidenceProposal:
    session_id: str
    evidence: ComputationEvidence

    def __post_init__(self) -> None:
        _session(self.session_id)
        if not isinstance(self.evidence, ComputationEvidence):
            raise ValueError("A worker evidence proposal requires typed evidence")


@dataclass(frozen=True, slots=True)
class WorkerCompletionVerified:
    session_id: str

    def __post_init__(self) -> None:
        _session(self.session_id)


@dataclass(frozen=True, slots=True)
class WorkerFailure:
    session_id: str
    diagnostic: EvidenceDiagnostic

    def __post_init__(self) -> None:
        _session(self.session_id)
        if not isinstance(self.diagnostic, EvidenceDiagnostic):
            raise ValueError("A worker failure requires a typed diagnostic")


@dataclass(frozen=True, slots=True)
class WorkerTerminalSecured:
    session_id: str
    evidence_id: str

    def __post_init__(self) -> None:
        _session(self.session_id)
        if not isinstance(self.evidence_id, str) or not self.evidence_id:
            raise ValueError("A terminal acknowledgment requires its evidence identity")


type WorkerRequest = (
    WorkerPreparationRequest | WorkerExecutionRequest | WorkerEditorPreparationRequest
)
type WorkerEvent = (
    WorkerPrepared
    | WorkerEditorPrepared
    | WorkerResourceEvent
    | ProgressEvent
    | PreviewEvent
    | ObservationEvent
    | WorkerPublicationOffer
    | WorkerEvidenceProposal
    | WorkerCompletionVerified
    | WorkerFailure
)
type WorkerControl = WorkerRequest | CancelRequest | PublicationEvent | WorkerTerminalSecured
