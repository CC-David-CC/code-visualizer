"""Lossless evidence/provenance messages linked to semantic identities."""

from typing import cast

from code_visualizer.domain.evidence import (
    ComputationEvidence,
    ComputationOutcome,
    EvidenceArtifact,
    EvidenceDiagnostic,
    EvidenceObservation,
    EvidenceProvenance,
    EvidencePublication,
    ObservationEvent,
    PublicationEvent,
)
from code_visualizer.protocol.computation import parameter_from_proto, parameter_to_proto
from code_visualizer.protocol.identity import origins_from_proto, origins_to_proto
from code_visualizer.protocol.v1 import evidence_pb2 as wire
from code_visualizer.protocol.validation import check_message, invalid, require_field
from code_visualizer.protocol.values import (
    canonical_value_from_proto,
    canonical_value_to_proto,
    integer_from_proto,
    integer_to_proto,
    resource_reference_from_proto,
    resource_reference_to_proto,
)


def provenance_to_proto(value: EvidenceProvenance) -> wire.EvidenceProvenance:
    result = wire.EvidenceProvenance(
        project_id=value.project_id,
        revision=value.revision,
        backend_id=value.backend_id,
        backend_version=value.backend_version,
        input_digest=value.input_digest,
        configuration=[parameter_to_proto(p) for p in value.configuration],
        resources=[resource_reference_to_proto(r) for r in value.resources],
        transformations=value.transformations,
        origins=origins_to_proto(value.origins),
    )
    if value.source_model_id is not None:
        result.source_model_id = value.source_model_id
    if value.seed is not None:
        result.seed.CopyFrom(integer_to_proto(value.seed))
    if value.terminal_resource is not None:
        result.terminal_resource.CopyFrom(resource_reference_to_proto(value.terminal_resource))
    return result


def provenance_from_proto(value: wire.EvidenceProvenance) -> EvidenceProvenance:
    check_message(value)
    require_field(value, "origins")
    return EvidenceProvenance(
        value.project_id,
        value.revision,
        value.source_model_id if value.HasField("source_model_id") else None,
        value.backend_id,
        value.backend_version,
        value.input_digest,
        tuple(parameter_from_proto(p) for p in value.configuration),
        integer_from_proto(value.seed) if value.HasField("seed") else None,
        tuple(resource_reference_from_proto(r) for r in value.resources),
        tuple(value.transformations),
        origins_from_proto(value.origins),
        resource_reference_from_proto(value.terminal_resource)
        if value.HasField("terminal_resource")
        else None,
    )


def evidence_to_proto(value: ComputationEvidence) -> wire.ComputationEvidence:
    result = wire.ComputationEvidence(
        schema_version=1,
        id=value.id,
        provenance=provenance_to_proto(value.provenance),
        outcome=cast(
            wire.ComputationOutcome,
            wire.ComputationOutcome.Value("COMPUTATION_" + value.outcome.value.upper()),
        ),
        observations=[
            wire.EvidenceObservation(
                id=o.id,
                semantic_ids=o.semantic_ids,
                value=canonical_value_to_proto(o.value),
                label=o.label,
                sequence=o.sequence,
            )
            for o in value.observations
        ],
        artifacts=[artifact_to_proto(a) for a in value.artifacts],
        diagnostics=[
            wire.EvidenceDiagnostic(code=d.code, message=d.message, semantic_ids=d.semantic_ids)
            for d in value.diagnostics
        ],
    )
    check_message(result, version=1)
    return result


def evidence_from_proto(value: wire.ComputationEvidence) -> ComputationEvidence:
    check_message(value, version=value.schema_version)
    require_field(value, "provenance")
    try:
        outcome = ComputationOutcome(
            wire.ComputationOutcome.Name(value.outcome).removeprefix("COMPUTATION_").lower()
        )
    except ValueError as exc:
        raise invalid("Unknown computation outcome") from exc
    for item in value.artifacts:
        require_field(item, "resource")
    for observation in value.observations:
        require_field(observation, "value")
    return ComputationEvidence(
        value.id,
        provenance_from_proto(value.provenance),
        outcome,
        tuple(
            EvidenceObservation(
                o.id,
                tuple(o.semantic_ids),
                canonical_value_from_proto(o.value),
                o.label,
                o.sequence,
            )
            for o in value.observations
        ),
        tuple(artifact_from_proto(a) for a in value.artifacts),
        tuple(
            EvidenceDiagnostic(d.code, d.message, tuple(d.semantic_ids)) for d in value.diagnostics
        ),
    )


def observation_event_to_proto(value: ObservationEvent) -> wire.ObservationEvent:
    o = value.observation
    result = wire.ObservationEvent(
        schema_version=1,
        session_id=value.session_id,
        observation=wire.EvidenceObservation(
            id=o.id,
            semantic_ids=o.semantic_ids,
            value=canonical_value_to_proto(o.value),
            label=o.label,
            sequence=o.sequence,
        ),
    )
    check_message(result, version=1)
    return result


def observation_event_from_proto(value: wire.ObservationEvent) -> ObservationEvent:
    check_message(value, version=value.schema_version)
    require_field(value, "observation")
    o = value.observation
    require_field(o, "value")
    return ObservationEvent(
        value.session_id,
        EvidenceObservation(
            o.id, tuple(o.semantic_ids), canonical_value_from_proto(o.value), o.label, o.sequence
        ),
    )


def artifact_to_proto(value: EvidenceArtifact) -> wire.EvidenceArtifact:
    return wire.EvidenceArtifact(
        id=value.id,
        resource=resource_reference_to_proto(value.resource),
        semantic_ids=value.semantic_ids,
        label=value.label,
    )


def artifact_from_proto(value: wire.EvidenceArtifact) -> EvidenceArtifact:
    check_message(value)
    require_field(value, "resource")
    return EvidenceArtifact(
        value.id,
        resource_reference_from_proto(value.resource),
        tuple(value.semantic_ids),
        value.label,
    )


def publication_to_proto(value: EvidencePublication) -> wire.EvidencePublication:
    result = wire.EvidencePublication(
        schema_version=1,
        id=value.id,
        provenance=provenance_to_proto(value.provenance),
        artifact=artifact_to_proto(value.artifact),
    )
    check_message(result, version=1)
    return result


def publication_from_proto(value: wire.EvidencePublication) -> EvidencePublication:
    check_message(value, version=value.schema_version)
    require_field(value, "provenance")
    require_field(value, "artifact")
    return EvidencePublication(
        value.id,
        provenance_from_proto(value.provenance),
        artifact_from_proto(value.artifact),
    )


def publication_event_to_proto(value: PublicationEvent) -> wire.PublicationEvent:
    result = wire.PublicationEvent(
        schema_version=1,
        session_id=value.session_id,
        sequence=value.sequence,
        publication=publication_to_proto(value.publication),
    )
    check_message(result, version=1)
    return result


def publication_event_from_proto(value: wire.PublicationEvent) -> PublicationEvent:
    check_message(value, version=value.schema_version)
    require_field(value, "publication")
    return PublicationEvent(
        value.session_id, value.sequence, publication_from_proto(value.publication)
    )
