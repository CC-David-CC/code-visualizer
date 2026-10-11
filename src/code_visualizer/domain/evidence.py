"""Immutable evidence of a computation; observed values never become authored state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from code_visualizer.domain.computation import ComputationParameter, ComputationRequest
from code_visualizer.domain.transformation import OriginMap
from code_visualizer.domain.values import (
    CanonicalValue,
    ResourceReference,
    canonical_value_key,
    validate_canonical_value,
)


class ComputationOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True, eq=False)
class EvidenceObservation:
    id: str
    semantic_ids: tuple[str, ...]
    value: CanonicalValue
    label: str = ""
    sequence: int = 0

    def __post_init__(self) -> None:
        if (
            not isinstance(self.id, str)
            or not self.id
            or type(self.sequence) is not int
            or not 0 <= self.sequence < 1 << 64
        ):
            raise ValueError("An observation requires an identity and nonnegative sequence")
        _identities(self.semantic_ids)
        if not isinstance(self.label, str):
            raise ValueError("An observation label must be text")
        validate_canonical_value(self.value)

    def _key(self) -> tuple[object, ...]:
        return (
            self.id,
            self.semantic_ids,
            canonical_value_key(self.value),
            self.label,
            self.sequence,
        )

    def __eq__(self, other: object) -> bool:
        return isinstance(other, EvidenceObservation) and self._key() == other._key()

    def __hash__(self) -> int:
        return hash(self._key())


@dataclass(frozen=True, slots=True)
class EvidenceArtifact:
    id: str
    resource: ResourceReference
    semantic_ids: tuple[str, ...] = ()
    label: str = ""

    def __post_init__(self) -> None:
        if (
            not isinstance(self.id, str)
            or not self.id
            or not isinstance(self.resource, ResourceReference)
        ):
            raise ValueError("An evidence artifact requires an identity")
        _identities(self.semantic_ids)
        if not isinstance(self.label, str):
            raise ValueError("An artifact label must be text")


@dataclass(frozen=True, slots=True)
class EvidenceDiagnostic:
    code: str
    message: str
    semantic_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if any(not isinstance(item, str) or not item for item in (self.code, self.message)):
            raise ValueError("An evidence diagnostic requires a code and message")
        _identities(self.semantic_ids)


def _identities(values: tuple[str, ...]) -> None:
    if type(values) is not tuple or len(values) > 10000:
        raise ValueError("Evidence identities must be a bounded immutable tuple")
    if any(not isinstance(item, str) or not item for item in values):
        raise ValueError("Evidence semantic identities must be nonempty strings")
    if len(values) != len(set(values)):
        raise ValueError("Evidence semantic identities cannot be duplicated")


@dataclass(frozen=True, slots=True)
class EvidenceProvenance:
    project_id: str
    revision: int
    source_model_id: str | None
    backend_id: str
    backend_version: str
    input_digest: str
    configuration: tuple[ComputationParameter, ...]
    seed: int | None
    resources: tuple[ResourceReference, ...]
    transformations: tuple[str, ...]
    origins: OriginMap
    terminal_resource: ResourceReference | None = None

    def __post_init__(self) -> None:
        if self.terminal_resource is not None and not isinstance(
            self.terminal_resource, ResourceReference
        ):
            raise ValueError("Evidence terminal must be a typed resource reference or absent")
        ComputationRequest(
            self.project_id,
            self.revision,
            self.backend_id,
            self.backend_version,
            self.source_model_id,
            self.configuration,
            self.seed,
            self.resources,
        )
        _identities(self.transformations)
        if (
            not isinstance(self.input_digest, str)
            or len(self.input_digest) != 64
            or any(character not in "0123456789abcdef" for character in self.input_digest)
        ):
            raise ValueError("Evidence input digest must be a lowercase SHA-256 digest")
        if not isinstance(self.origins, OriginMap) or (
            self.origins.project_id,
            self.origins.revision,
        ) != (self.project_id, self.revision):
            raise ValueError("Evidence origins must match its pinned project revision")


@dataclass(frozen=True, slots=True)
class ComputationEvidence:
    id: str
    provenance: EvidenceProvenance
    outcome: ComputationOutcome
    observations: tuple[EvidenceObservation, ...] = ()
    artifacts: tuple[EvidenceArtifact, ...] = ()
    diagnostics: tuple[EvidenceDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("Computation evidence requires an identity")
        if not isinstance(self.provenance, EvidenceProvenance) or not isinstance(
            self.outcome, ComputationOutcome
        ):
            raise ValueError("Evidence requires typed provenance and outcome")
        for records, kind in (
            (self.observations, EvidenceObservation),
            (self.artifacts, EvidenceArtifact),
            (self.diagnostics, EvidenceDiagnostic),
        ):
            if (
                type(records) is not tuple
                or len(records) > 10000
                or any(not isinstance(item, kind) for item in records)
            ):
                raise ValueError("Evidence records must be bounded immutable typed tuples")
        identities = [item.id for item in self.observations] + [item.id for item in self.artifacts]
        if len(identities) != len(set(identities)):
            raise ValueError("Evidence observation and artifact identities must be unique")
        sequences = [item.sequence for item in self.observations]
        if sequences != sorted(sequences) or len(sequences) != len(set(sequences)):
            raise ValueError("Evidence observations require strictly increasing sequences")


@dataclass(frozen=True, slots=True)
class ObservationEvent:
    session_id: str
    observation: EvidenceObservation

    def __post_init__(self) -> None:
        if (
            not isinstance(self.session_id, str)
            or not self.session_id
            or not isinstance(self.observation, EvidenceObservation)
        ):
            raise ValueError(
                "An observation event requires its session identity and typed observation"
            )


@dataclass(frozen=True, slots=True)
class EvidencePublication:
    """Sealed scientific output; receipt identity excludes execution/session clocks."""

    id: str
    provenance: EvidenceProvenance
    artifact: EvidenceArtifact

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("A publication requires an identity")
        if not isinstance(self.provenance, EvidenceProvenance) or not isinstance(
            self.artifact, EvidenceArtifact
        ):
            raise ValueError("A publication requires typed provenance and artifact")
        if self.provenance.terminal_resource is None:
            raise ValueError("A durable publication requires its immutable terminal resource")


@dataclass(frozen=True, slots=True)
class PublicationEvent:
    """An admitted publication attached to one ephemeral execution sequence."""

    session_id: str
    sequence: int
    publication: EvidencePublication

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, str) or not self.session_id:
            raise ValueError("A publication event requires its session identity")
        if type(self.sequence) is not int or not 0 <= self.sequence < 1 << 64:
            raise ValueError("A publication event requires a nonnegative sequence")
        if not isinstance(self.publication, EvidencePublication):
            raise ValueError("A publication event requires a typed sealed receipt")
