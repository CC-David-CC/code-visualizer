"""One verified resource admission path for final outputs and live publications."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from code_visualizer.application.resource_admission import (
    check_resource_descriptor,
    validate_resource_contracts,
)
from code_visualizer.domain.boundaries import MAX_PORTABLE_ENVELOPE_BYTES
from code_visualizer.domain.evidence import (
    EvidenceArtifact,
    EvidencePublication,
    PublicationEvent,
)
from code_visualizer.domain.values import ResourceReference
from code_visualizer.execution.backends import (
    PreparedComputation,
    ProducedResource,
    ProducedResourceEvent,
)
from code_visualizer.execution.publication_budget import computation_provenance, publication_size
from code_visualizer.extensions.registry import DomainExtensionRegistry
from code_visualizer.generation.transformation import TransformationError, value_identities
from code_visualizer.persistence.evidence_store import EvidenceStore, validate_portable_publication
from code_visualizer.persistence.publications import publication_content_hash
from code_visualizer.persistence.resource_store import ResourceStore


@dataclass(slots=True)
class PublicationBudget:
    """One attempt's bounded receipt retention; reserve before any durable commit."""

    _used_bytes: int = field(default=0, init=False)

    @property
    def used_bytes(self) -> int:
        return self._used_bytes

    def reserve(self, event: PublicationEvent) -> None:
        validate_portable_publication(event.publication)
        size = publication_size(event)
        if self._used_bytes + size > MAX_PORTABLE_ENVELOPE_BYTES:
            raise TransformationError(
                "COMPUTATION_PUBLICATION_LIMIT",
                "An attempt's sealed publication receipts exceed the 2 MiB metadata budget",
            )
        self._used_bytes += size


def seal_resource(
    snapshot: PreparedComputation,
    resource: ProducedResource,
    resource_store: ResourceStore | None,
    registry: DomainExtensionRegistry,
) -> EvidenceArtifact:
    """Seal a root and its declared children, without a receipt per child.

    No root can be acknowledged until its interpreted closure is complete. Orphan
    bytes after a failure are inert; they are never proof of admitted output.
    """
    children = tuple(
        _seal_one(snapshot, child, resource_store, registry).resource
        for child in resource.dependencies
    )
    artifact = _seal_one(snapshot, resource, resource_store, registry)
    assert resource_store is not None
    closure = registry.resource_closure((artifact.resource,), resource_store)
    if set(children) - set(closure):
        raise TransformationError(
            "COMPUTATION_RESOURCE_OUTPUT", "Output contains undeclared child resources"
        )
    return artifact


def _seal_one(
    snapshot: PreparedComputation,
    resource: ProducedResource,
    resource_store: ResourceStore | None,
    registry: DomainExtensionRegistry,
) -> EvidenceArtifact:
    available = value_identities(snapshot.value) | {
        node.id for model in snapshot.dependency_models for node in model.nodes
    }
    if set(resource.semantic_ids) - available:
        raise TransformationError(
            "COMPUTATION_ORIGIN_UNKNOWN",
            "Backend evidence names an object absent from its terminal input",
        )
    if resource_store is None:
        raise TransformationError(
            "COMPUTATION_RESOURCE_STORE",
            "Backend resource output requires an explicit resource store",
        )
    validate_resource_contracts(resource.logical_type, resource.tensor, registry)
    try:
        if resource.file is not None:
            descriptor = resource_store.import_file(
                resource.file.path,
                resource.media_type,
                tensor=resource.tensor,
                logical_type=resource.logical_type,
                expected_byte_size=resource.file.byte_size,
                expected_content_hash=resource.file.content_hash,
            )
        else:
            assert resource.data is not None
            descriptor = resource_store.put(
                resource.data,
                resource.media_type,
                tensor=resource.tensor,
                logical_type=resource.logical_type,
            )
    except (ValueError, OSError) as exc:
        raise TransformationError("COMPUTATION_RESOURCE_OUTPUT", str(exc)) from exc
    return EvidenceArtifact(
        resource.id, descriptor.reference, resource.semantic_ids, resource.label
    )


def seal_publication(
    snapshot: PreparedComputation,
    event: ProducedResourceEvent,
    terminal_resource: ResourceReference | None,
    resource_store: ResourceStore | None,
    evidence_store: EvidenceStore | None,
    registry: DomainExtensionRegistry,
    *,
    budget: PublicationBudget,
) -> PublicationEvent:
    """Commit a sealed receipt before the caller acknowledges or resumes a worker."""
    if resource_store is None or evidence_store is None or terminal_resource is None:
        raise TransformationError(
            "COMPUTATION_PUBLICATION_STORE",
            "Live publication requires resource/evidence stores and an immutable terminal",
        )
    artifact = seal_resource(snapshot, event.resource, resource_store, registry)
    return seal_admitted_publication(
        snapshot,
        event.session_id,
        event.sequence,
        artifact,
        terminal_resource,
        resource_store,
        evidence_store,
        registry,
        budget=budget,
    )


def seal_admitted_publication(
    snapshot: PreparedComputation,
    session_id: str,
    sequence: int,
    artifact: EvidenceArtifact,
    terminal_resource: ResourceReference | None,
    resource_store: ResourceStore | None,
    evidence_store: EvidenceStore | None,
    registry: DomainExtensionRegistry,
    *,
    budget: PublicationBudget,
) -> PublicationEvent:
    """Verify transferred CAS output and commit the same receipt used for local output."""
    if resource_store is None or evidence_store is None or terminal_resource is None:
        raise TransformationError(
            "COMPUTATION_PUBLICATION_STORE",
            "Live publication requires resource/evidence stores and an immutable terminal",
        )
    available = value_identities(snapshot.value) | {
        node.id for model in snapshot.dependency_models for node in model.nodes
    }
    if set(artifact.semantic_ids) - available:
        raise TransformationError(
            "COMPUTATION_ORIGIN_UNKNOWN",
            "Backend evidence names an object absent from its terminal input",
        )
    for reference in registry.resource_closure(
        (terminal_resource, artifact.resource), resource_store
    ):
        try:
            resource_store.verified_path(reference)
            descriptor = resource_store.describe(reference)
        except (ValueError, OSError) as exc:
            raise TransformationError("COMPUTATION_RESOURCE_UNAVAILABLE", str(exc)) from exc
        check_resource_descriptor(descriptor, registry)
    publication = EvidencePublication(
        "pending", computation_provenance(snapshot, terminal_resource), artifact
    )
    publication = replace(publication, id="publication:" + publication_content_hash(publication))
    admitted = PublicationEvent(session_id, sequence, publication)
    budget.reserve(admitted)
    evidence_store.put_publication(publication)
    return admitted
