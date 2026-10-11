"""Copy a snapshot's immutable resource closure without copying editor storage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields, is_dataclass
from pathlib import Path

from code_visualizer.domain.project import Project
from code_visualizer.domain.values import ResourceReference
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore


def copy_project_resources(
    project: Project,
    resources: ResourceStore | None,
    evidence: EvidenceStore | None,
    destination: Path,
    *,
    resolve_closure: Callable[[tuple[ResourceReference, ...]], tuple[ResourceReference, ...]]
    | None = None,
) -> None:
    """Preserve referenced data and this project's durable evidence by verified import.

    Project metadata is published by the caller only after this succeeds. A failed
    import can leave unreferenced immutable objects, never a misleading snapshot.
    """
    records = tuple(
        record
        for identity in (() if evidence is None else evidence.identities())
        if evidence is not None
        and (record := evidence.get(identity)).provenance.project_id == project.id
    )
    publications = tuple(
        publication_record
        for identity in (() if evidence is None else evidence.publication_identities())
        if evidence is not None
        and (publication_record := evidence.get_publication(identity)).provenance.project_id
        == project.id
    )
    references: dict[str, ResourceReference] = {}
    pending: list[object] = [project, *records, *publications]
    while pending:
        value = pending.pop()
        if isinstance(value, ResourceReference):
            previous = references.setdefault(value.id, value)
            if previous != value:
                raise ValueError("A copied resource identity has conflicting content hashes")
        elif isinstance(value, tuple):
            pending.extend(value)
        elif is_dataclass(value) and not isinstance(value, type):
            pending.extend(getattr(value, member.name) for member in fields(value))
    if references and resources is None:
        raise ValueError("A resource-valued recovery copy requires its source resource store")
    if resolve_closure is not None:
        references = {item.id: item for item in resolve_closure(tuple(references.values()))}
    if resources is not None:
        target = ResourceStore(destination)
        for reference in sorted(references.values(), key=lambda item: item.id):
            descriptor = resources.describe(reference)
            path = resources.verified_path(reference)
            copied = target.import_file(
                path,
                descriptor.media_type,
                tensor=descriptor.tensor,
                logical_type=descriptor.logical_type,
            )
            if copied != descriptor:
                raise ValueError("Source resource changed during recovery copying")
    target_evidence = EvidenceStore(destination)
    for record in records:
        target_evidence.put(record)
    for publication in publications:
        target_evidence.put_publication(publication)
