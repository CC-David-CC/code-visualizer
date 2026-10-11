"""Bounded read-only interpretation of composite resources at a real data boundary.

The store knows hashes and bytes. Trusted registrations know which other resources
those bytes require. The walker never guesses dependencies from paths or JSON keys.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from code_visualizer.domain.resources import DataResource, ResourceLogicalTypeReference
from code_visualizer.domain.values import ResourceReference

MAX_CLOSURE_RESOURCES = 1024
MAX_CLOSURE_METADATA_BYTES = 2 * 1024 * 1024
MAX_CLOSURE_DEPTH = 64


@dataclass(frozen=True, slots=True)
class ResourceDependency:
    reference: ResourceReference
    logical_type: ResourceLogicalTypeReference
    byte_size: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.reference, ResourceReference) or not isinstance(
            self.logical_type, ResourceLogicalTypeReference
        ):
            raise ValueError("Resource dependencies require exact typed contracts")
        if self.byte_size is not None and (
            type(self.byte_size) is not int or not 0 <= self.byte_size < 1 << 63
        ):
            raise ValueError("A resource dependency size must be nonnegative")


@dataclass(frozen=True, slots=True)
class ResourceInterpretation:
    logical_type: ResourceLogicalTypeReference
    dependencies: Callable[[bytes], tuple[ResourceDependency, ...]]
    metadata_limit: int = 64 * 1024

    def __post_init__(self) -> None:
        if not isinstance(self.logical_type, ResourceLogicalTypeReference):
            raise ValueError("A resource interpretation requires an exact logical type")
        if not callable(self.dependencies) or type(self.metadata_limit) is not int:
            raise ValueError("A resource interpretation requires a bounded decoder")
        if not 1 <= self.metadata_limit <= MAX_CLOSURE_METADATA_BYTES:
            raise ValueError("Resource interpretation exceeds the metadata envelope")


class ResourceReader(Protocol):
    def describe(self, reference: ResourceReference) -> DataResource: ...

    def verified_path(self, reference: ResourceReference) -> Path: ...


def resource_closure(
    roots: tuple[ResourceReference, ...],
    reader: ResourceReader,
    interpretation: Callable[[ResourceLogicalTypeReference], ResourceInterpretation | None],
    *,
    validate: Callable[[DataResource], None] | None = None,
) -> tuple[ResourceReference, ...]:
    """Verify an exact dependency-first closure with bounded metadata and traversal.

    Known types without a composite interpretation are opaque leaves. An unavailable
    public type is rejected by the caller's contract validator, never treated as a
    successfully understood composite. Duplicate IDs cannot hide conflicting hashes.
    """
    found: dict[str, ResourceReference] = {}
    visiting: set[str] = set()
    result: list[ResourceReference] = []
    metadata_bytes = 0

    def visit(reference: ResourceReference, claim: ResourceDependency | None, depth: int) -> None:
        nonlocal metadata_bytes
        if depth > MAX_CLOSURE_DEPTH or len(found) > MAX_CLOSURE_RESOURCES:
            raise ValueError("Resource closure exceeds its traversal bound")
        previous = found.get(reference.id)
        if previous is not None and previous != reference:
            raise ValueError("Resource closure contains conflicting identities")
        descriptor = reader.describe(reference)
        if descriptor.reference != reference:
            raise ValueError("Resource descriptor does not match the claimed identity/hash")
        if claim is not None and (
            descriptor.logical_type != claim.logical_type
            or (claim.byte_size is not None and descriptor.byte_size != claim.byte_size)
        ):
            raise ValueError("Resource dependency does not match its declared type/size")
        if reference.id in visiting:
            raise ValueError("Resource dependency cycle")
        if previous is not None:
            return
        if len(found) >= MAX_CLOSURE_RESOURCES:
            raise ValueError("Resource closure exceeds 1024 resources")
        found[reference.id] = reference
        visiting.add(reference.id)
        if validate is not None:
            validate(descriptor)
        path = reader.verified_path(reference)
        decoder = interpretation(descriptor.logical_type) if descriptor.logical_type else None
        if decoder is not None:
            metadata_bytes += descriptor.byte_size
            if (
                descriptor.byte_size > decoder.metadata_limit
                or metadata_bytes > MAX_CLOSURE_METADATA_BYTES
            ):
                raise ValueError("Resource closure exceeds its metadata byte bound")
            with path.open("rb") as stream:
                payload = stream.read(decoder.metadata_limit + 1)
            if (
                len(payload) != descriptor.byte_size
                or sha256(payload).hexdigest() != descriptor.content_hash
            ):
                raise ValueError("Resource metadata changed after verification")
            children = decoder.dependencies(payload)
            if (
                type(children) is not tuple
                or len(children) > MAX_CLOSURE_RESOURCES
                or any(not isinstance(child, ResourceDependency) for child in children)
            ):
                raise ValueError("Resource decoder must return bounded typed dependencies")
            for child in children:
                visit(child.reference, child, depth + 1)
        visiting.remove(reference.id)
        result.append(reference)

    for root in sorted(roots, key=lambda item: (item.id, item.content_hash)):
        visit(root, None, 0)
    return tuple(result)
