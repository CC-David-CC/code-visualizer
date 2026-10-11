"""Versioned evidence codec. Hashes cover provenance, observations and resources."""

from __future__ import annotations

import hashlib

from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.computation import ComputationParameter
from code_visualizer.domain.evidence import (
    ComputationEvidence,
    ComputationOutcome,
    EvidenceArtifact,
    EvidenceDiagnostic,
    EvidenceObservation,
    EvidenceProvenance,
)
from code_visualizer.domain.transformation import OriginLink, OriginMap
from code_visualizer.domain.values import ResourceReference
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.values import (
    array_data,
    canonical_value_from_data,
    canonical_value_to_data,
    integer_data,
    object_data,
    text_data,
)


def _texts(value: object) -> tuple[str, ...]:
    return tuple(text_data(item) for item in array_data(value))


def _reference(value: object) -> ResourceReference:
    reference = canonical_value_from_data(value)
    if not isinstance(reference, ResourceReference):
        raise ValueError("Expected resource reference")
    return reference


def evidence_to_data(value: ComputationEvidence) -> dict[str, JsonValue]:
    return {
        "version": 1,
        "id": value.id,
        "outcome": value.outcome.value,
        "provenance": provenance_to_data(value.provenance),
        "observations": [
            {
                "id": item.id,
                "semantic_ids": list(item.semantic_ids),
                "value": canonical_value_to_data(item.value),
                "label": item.label,
                "sequence": item.sequence,
            }
            for item in value.observations
        ],
        "artifacts": [artifact_to_data(item) for item in value.artifacts],
        "diagnostics": [
            {"code": item.code, "message": item.message, "semantic_ids": list(item.semantic_ids)}
            for item in value.diagnostics
        ],
    }


def provenance_to_data(provenance: EvidenceProvenance) -> dict[str, JsonValue]:
    return {
        "project_id": provenance.project_id,
        "revision": provenance.revision,
        "source_model_id": provenance.source_model_id,
        "backend_id": provenance.backend_id,
        "backend_version": provenance.backend_version,
        "input_digest": provenance.input_digest,
        "configuration": [
            {"name": item.name, "value": canonical_value_to_data(item.value)}
            for item in provenance.configuration
        ],
        "seed": provenance.seed,
        "resources": [canonical_value_to_data(item) for item in provenance.resources],
        "terminal_resource": None
        if provenance.terminal_resource is None
        else canonical_value_to_data(provenance.terminal_resource),
        "transformations": list(provenance.transformations),
        "origins": [
            {"generated_id": link.generated_id, "source_ids": list(link.source_ids)}
            for link in provenance.origins.links
        ],
    }


def artifact_to_data(value: EvidenceArtifact) -> dict[str, JsonValue]:
    return {
        "id": value.id,
        "resource": canonical_value_to_data(value.resource),
        "semantic_ids": list(value.semantic_ids),
        "label": value.label,
    }


def artifact_from_data(value: object) -> EvidenceArtifact:
    data = object_data(value, {"id", "resource", "semantic_ids", "label"})
    return EvidenceArtifact(
        text_data(data.get("id")),
        _reference(data.get("resource")),
        _texts(data.get("semantic_ids")),
        text_data(data.get("label")),
    )


def provenance_from_data(value: object) -> EvidenceProvenance:
    provenance = object_data(
        value,
        {
            "project_id",
            "revision",
            "source_model_id",
            "backend_id",
            "backend_version",
            "input_digest",
            "configuration",
            "seed",
            "resources",
            "terminal_resource",
            "transformations",
            "origins",
        },
    )
    project_id, revision = (
        text_data(provenance.get("project_id")),
        integer_data(provenance.get("revision")),
    )
    parameters = [
        object_data(item, {"name", "value"}) for item in array_data(provenance.get("configuration"))
    ]
    links = [
        object_data(item, {"generated_id", "source_ids"})
        for item in array_data(provenance.get("origins"))
    ]
    return EvidenceProvenance(
        project_id,
        revision,
        None
        if provenance.get("source_model_id") is None
        else text_data(provenance["source_model_id"]),
        text_data(provenance.get("backend_id")),
        text_data(provenance.get("backend_version")),
        text_data(provenance.get("input_digest")),
        tuple(
            ComputationParameter(
                text_data(item.get("name")), canonical_value_from_data(item.get("value"))
            )
            for item in parameters
        ),
        None if provenance.get("seed") is None else integer_data(provenance["seed"]),
        tuple(_reference(item) for item in array_data(provenance.get("resources"))),
        _texts(provenance.get("transformations")),
        OriginMap(
            project_id,
            revision,
            tuple(
                OriginLink(text_data(link.get("generated_id")), _texts(link.get("source_ids")))
                for link in links
            ),
        ),
        None
        if provenance.get("terminal_resource") is None
        else _reference(provenance["terminal_resource"]),
    )


def evidence_from_data(value: object) -> ComputationEvidence:
    data = object_data(
        value,
        {"version", "id", "outcome", "provenance", "observations", "artifacts", "diagnostics"},
    )
    if integer_data(data.get("version")) != 1:
        raise ValueError("Unsupported evidence version")
    observations = [
        object_data(item, {"id", "semantic_ids", "value", "label", "sequence"})
        for item in array_data(data.get("observations"))
    ]
    diagnostics = [
        object_data(item, {"code", "message", "semantic_ids"})
        for item in array_data(data.get("diagnostics"))
    ]
    return ComputationEvidence(
        text_data(data.get("id")),
        provenance_from_data(data.get("provenance")),
        ComputationOutcome(text_data(data.get("outcome"))),
        tuple(
            EvidenceObservation(
                text_data(item.get("id")),
                _texts(item.get("semantic_ids")),
                canonical_value_from_data(item.get("value")),
                text_data(item.get("label")),
                integer_data(item.get("sequence")),
            )
            for item in observations
        ),
        tuple(artifact_from_data(item) for item in array_data(data.get("artifacts"))),
        tuple(
            EvidenceDiagnostic(
                text_data(item.get("code")),
                text_data(item.get("message")),
                _texts(item.get("semantic_ids")),
            )
            for item in diagnostics
        ),
    )


def evidence_content_hash(value: ComputationEvidence) -> str:
    data = evidence_to_data(value)
    data.pop("id")
    return hashlib.sha256(canonical_data_bytes(data)).hexdigest()
