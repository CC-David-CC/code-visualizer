"""Shared receipt sizing and provenance for preflight and durable admission."""

from __future__ import annotations

from code_visualizer.domain.boundaries import MAX_PORTABLE_ENVELOPE_BYTES
from code_visualizer.domain.evidence import (
    EvidenceArtifact,
    EvidenceProvenance,
    EvidencePublication,
    PublicationEvent,
)
from code_visualizer.domain.values import ResourceReference
from code_visualizer.execution.backends import PreparedComputation
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.publications import publication_to_data
from code_visualizer.protocol.evidence import publication_event_to_proto


def computation_provenance(
    snapshot: PreparedComputation, terminal_resource: ResourceReference | None
) -> EvidenceProvenance:
    request = snapshot.request
    return EvidenceProvenance(
        request.project_id,
        request.revision,
        request.model_id,
        request.backend_id,
        request.backend_version,
        snapshot.input_digest,
        request.configuration,
        request.seed,
        request.resources,
        snapshot.transformations,
        snapshot.origins,
        terminal_resource,
    )


def publication_size(event: PublicationEvent) -> int:
    return max(
        publication_event_to_proto(event).ByteSize(),
        len(canonical_data_bytes(publication_to_data(event.publication))),
    )


def require_publication_capacity(
    snapshot: PreparedComputation,
    session_id: str,
    count: int,
    semantic_ids: tuple[str, ...],
    *,
    artifact_text_bytes: int,
) -> None:
    """Conservative upper bound using the actual provenance and portable encoders.

    The trusted producer supplies upper bounds for its finite publication count and
    artifact text. Generated CAS/receipt IDs have fixed lengths. Admission still
    measures every real receipt; preflight never grants extra capacity.
    """
    if type(count) is not int or count < 0 or not 0 <= artifact_text_bytes <= 65536:
        raise ValueError("Invalid finite publication bound")
    reference = ResourceReference("resource:" + "0" * 64, "0" * 64)
    artifact = EvidenceArtifact(
        "a" * artifact_text_bytes, reference, semantic_ids, "a" * artifact_text_bytes
    )
    publication = EvidencePublication(
        "publication:" + "0" * 64, computation_provenance(snapshot, reference), artifact
    )
    upper = publication_size(PublicationEvent(session_id, (1 << 64) - 1, publication))
    if upper * count > MAX_PORTABLE_ENVELOPE_BYTES:
        raise ValueError(
            "COMPUTATION_PUBLICATION_LIMIT: finite output exceeds the 2 MiB receipt budget"
        )
