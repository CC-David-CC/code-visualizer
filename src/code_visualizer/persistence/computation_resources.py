"""Resolve backend resource inputs without imposing an in-memory payload limit."""

from dataclasses import replace
from hashlib import sha256

from code_visualizer.domain.resources import DataResource
from code_visualizer.domain.values import ResourceReference
from code_visualizer.execution.backends import ProducedResource, ResolvedResource, ResourceFile
from code_visualizer.persistence import resource_store
from code_visualizer.persistence.resource_store import ResourceStore, resource_identity


def produced_descriptor(resource: ProducedResource) -> DataResource:
    """Predict the exact existing CAS identity without admitting staged output."""
    descriptor = DataResource(
        "pending",
        resource.file.content_hash
        if resource.file is not None
        else sha256(resource.data or b"").hexdigest(),
        resource.file.byte_size if resource.file is not None else len(resource.data or b""),
        resource.media_type,
        resource.tensor,
        resource.logical_type,
    )
    return replace(descriptor, id=resource_identity(descriptor))


def resolve_computation_resource(
    store: ResourceStore, reference: ResourceReference, *, file_backed: bool = False
) -> ResolvedResource:
    descriptor = store.describe(reference)
    if not file_backed and descriptor.byte_size <= resource_store.MAX_RESOURCE_READ_BYTES:
        return ResolvedResource(descriptor, store.read(reference))
    return ResolvedResource(
        descriptor,
        file=ResourceFile(
            store.verified_path(reference), descriptor.byte_size, descriptor.content_hash
        ),
    )
