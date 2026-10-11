"""Immutable sealed-publication receipts, independent of execution event clocks."""

from __future__ import annotations

from hashlib import sha256

from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.evidence import EvidencePublication
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.evidence import (
    artifact_from_data,
    artifact_to_data,
    provenance_from_data,
    provenance_to_data,
)
from code_visualizer.persistence.values import integer_data, object_data, text_data


def publication_to_data(value: EvidencePublication) -> dict[str, JsonValue]:
    return {
        "version": 1,
        "id": value.id,
        "provenance": provenance_to_data(value.provenance),
        "artifact": artifact_to_data(value.artifact),
    }


def publication_from_data(value: object) -> EvidencePublication:
    data = object_data(value, {"version", "id", "provenance", "artifact"})
    if integer_data(data.get("version")) != 1:
        raise ValueError("Unsupported publication version")
    return EvidencePublication(
        text_data(data.get("id")),
        provenance_from_data(data.get("provenance")),
        artifact_from_data(data.get("artifact")),
    )


def publication_content_hash(value: EvidencePublication) -> str:
    data = publication_to_data(value)
    data.pop("id")
    return sha256(canonical_data_bytes(data)).hexdigest()
