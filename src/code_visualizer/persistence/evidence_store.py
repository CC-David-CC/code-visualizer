"""Durable immutable evidence, separate from authored project state and undo."""

from __future__ import annotations

import json
from pathlib import Path

from code_visualizer.domain.boundaries import MAX_PORTABLE_ENVELOPE_BYTES
from code_visualizer.domain.evidence import ComputationEvidence, EvidencePublication
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.evidence import (
    evidence_content_hash,
    evidence_from_data,
    evidence_to_data,
)
from code_visualizer.persistence.publications import (
    publication_content_hash,
    publication_from_data,
    publication_to_data,
)
from code_visualizer.persistence.resource_store import ResourceStore, read_bounded
from code_visualizer.protocol.evidence import evidence_to_proto, publication_to_proto

MAX_EVIDENCE_BYTES = MAX_PORTABLE_ENVELOPE_BYTES


def validate_portable_evidence(evidence: ComputationEvidence) -> bytes:
    """Admit metadata only when both durable and wire encodings fit one envelope.

    This outer boundary uses the actual v1 adapter rather than an approximate or
    duplicated wire-size formula. Domain objects remain independent of protobuf.
    """
    data = canonical_data_bytes(evidence_to_data(evidence))
    if len(data) > MAX_EVIDENCE_BYTES:
        raise ValueError("Evidence exceeds 2 MiB; publish bulk observations as resources")
    evidence_to_proto(evidence)
    return data


def validate_portable_publication(publication: EvidencePublication) -> bytes:
    data = canonical_data_bytes(publication_to_data(publication))
    if len(data) > MAX_EVIDENCE_BYTES:
        raise ValueError("Publication exceeds 2 MiB; publish bulk observations as resources")
    publication_to_proto(publication)
    return data


class EvidenceStore:
    def __init__(self, root: Path) -> None:
        project_root = root.resolve()
        self.root = (project_root / "evidence").resolve()
        if not self.root.is_relative_to(project_root):
            raise ValueError("Evidence store must remain inside its project directory")

    def _path(self, identity: str) -> Path:
        digest = identity.removeprefix("evidence:")
        if (
            not identity.startswith("evidence:")
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ValueError("Evidence requires a content-addressed identity")
        path = (self.root / f"{digest}.json").resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Evidence location escapes its store")
        return path

    def put(self, evidence: ComputationEvidence) -> Path:
        if evidence.id != "evidence:" + evidence_content_hash(evidence):
            raise ValueError("Evidence content hash does not match its identity")
        data = validate_portable_evidence(evidence)
        path = self._path(evidence.id)
        ResourceStore._write_immutable(path, data)
        return path

    def get(self, identity: str) -> ComputationEvidence:
        path = self._path(identity)
        if path.stat().st_size > MAX_EVIDENCE_BYTES:
            raise ValueError("Evidence exceeds the record bound")
        evidence = evidence_from_data(json.loads(read_bounded(path, MAX_EVIDENCE_BYTES)))
        validate_portable_evidence(evidence)
        if evidence.id != identity or identity != "evidence:" + evidence_content_hash(evidence):
            raise ValueError("Evidence content hash mismatch")
        return evidence

    def identities(self) -> tuple[str, ...]:
        if not self.root.exists():
            return ()
        return tuple(
            sorted(
                "evidence:" + path.stem
                for path in self.root.glob("*.json")
                if len(path.stem) == 64 and all(char in "0123456789abcdef" for char in path.stem)
            )
        )

    def _publication_path(self, identity: str) -> Path:
        digest = identity.removeprefix("publication:")
        if (
            not identity.startswith("publication:")
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ValueError("Publication requires a content-addressed identity")
        path = (self.root / "publications" / f"{digest}.json").resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Publication location escapes its store")
        return path

    def put_publication(self, publication: EvidencePublication) -> Path:
        if publication.id != "publication:" + publication_content_hash(publication):
            raise ValueError("Publication content hash does not match its identity")
        data = validate_portable_publication(publication)
        path = self._publication_path(publication.id)
        ResourceStore._write_immutable(path, data)
        return path

    def get_publication(self, identity: str) -> EvidencePublication:
        path = self._publication_path(identity)
        publication = publication_from_data(json.loads(read_bounded(path, MAX_EVIDENCE_BYTES)))
        validate_portable_publication(publication)
        if publication.id != identity or identity != (
            "publication:" + publication_content_hash(publication)
        ):
            raise ValueError("Publication content hash mismatch")
        return publication

    def publication_identities(self) -> tuple[str, ...]:
        if not self.root.exists():
            return ()
        return tuple(
            sorted(
                "publication:" + path.stem
                for path in (self.root / "publications").glob("*.json")
                if len(path.stem) == 64 and all(char in "0123456789abcdef" for char in path.stem)
            )
        )
