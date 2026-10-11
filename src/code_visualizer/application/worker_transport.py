"""Bounded resource streams feed the existing portable computation worker.

The caller owns transport authentication and supplies explicit storage budgets.
This adapter neither opens a server nor creates an editor authority.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING

from code_visualizer.application.computation import run_computation_plan
from code_visualizer.application.resource_admission import validate_resource_descriptor
from code_visualizer.domain.computation import ComputationPlan
from code_visualizer.domain.resource_transfer import ResourceTransferStart
from code_visualizer.domain.values import ResourceReference
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.resource_transfer import (
    ResourceTransferReceiver,
    resource_transfer_frames,
)
from code_visualizer.protocol.computation import computation_plan_from_proto
from code_visualizer.protocol.evidence import evidence_to_proto
from code_visualizer.protocol.resource_transfer import (
    resource_frame_from_proto,
    resource_frame_to_proto,
)
from code_visualizer.protocol.v1 import computation_pb2, resource_pb2
from code_visualizer.protocol.validation import parse_message

if TYPE_CHECKING:
    from code_visualizer.extensions.registry import DomainExtensionRegistry
    from code_visualizer.persistence.evidence_store import EvidenceStore


def export_resource_stream(
    store: ResourceStore, reference: ResourceReference, transfer_id: str
) -> Iterator[bytes]:
    """Yield individual protobuf messages, never the complete resource payload."""
    for frame in resource_transfer_frames(store, reference, transfer_id):
        yield resource_frame_to_proto(frame).SerializeToString(deterministic=True)


def import_resource_stream(
    store: ResourceStore,
    expected: ResourceReference,
    frames: Iterable[bytes],
    *,
    max_resource_bytes: int,
    registry: DomainExtensionRegistry | None = None,
) -> int:
    """Verify storage; an explicit registry additionally admits resource interpretation.

    Raw archival transfer preserves unknown typed metadata. Computation callers
    supply their registry and reject unavailable contracts before committing bytes.
    """
    with ResourceTransferReceiver(
        store, expected, max_resource_bytes=max_resource_bytes
    ) as receiver:
        for payload in frames:
            frame = resource_frame_from_proto(
                parse_message(payload, resource_pb2.ResourceTransferFrame)
            )
            if isinstance(frame, ResourceTransferStart) and registry is not None:
                validate_resource_descriptor(frame.resource, registry)
            receiver.accept(frame)
        return receiver.commit().byte_size


def receive_plan_resources(
    plan: ComputationPlan,
    streams: Iterable[tuple[ResourceReference, Iterable[bytes]]],
    store: ResourceStore,
    *,
    max_total_bytes: int,
    registry: DomainExtensionRegistry,
) -> None:
    """Only explicitly requested plan inputs can be admitted by this worker API.

    Previously cached resources can be omitted from the incoming streams; each
    required descriptor and payload is still verified before starting execution.
    Successfully transferred CAS resources remain reusable if a later input fails.
    """
    if type(max_total_bytes) is not int or not 0 <= max_total_bytes < 1 << 63:
        raise ValueError("Worker transfer budget must be a nonnegative 64-bit integer")
    expected = {*plan.request.resources, plan.model}
    received: set[ResourceReference] = set()
    remaining = max_total_bytes
    for reference, frames in streams:
        if reference not in expected or reference in received:
            raise ValueError("Worker resource transfer is unsolicited or duplicated")
        remaining -= import_resource_stream(
            store, reference, frames, max_resource_bytes=remaining, registry=registry
        )
        received.add(reference)
    for reference in sorted(expected, key=lambda value: value.id):
        store.verified_path(reference)
        validate_resource_descriptor(store.describe(reference), registry)


def run_streamed_computation_plan(
    plan_payload: bytes,
    streams: Iterable[tuple[ResourceReference, Iterable[bytes]]],
    registry: DomainExtensionRegistry,
    resource_store: ResourceStore,
    evidence_store: EvidenceStore | None = None,
    *,
    max_total_bytes: int,
) -> bytes:
    """Run a binary plan after receiving its chunked inputs, returning bounded evidence.

    This is the same run_computation_plan path used by the CLI. Output artifacts
    use export_resource_stream in the reverse direction; evidence remains one
    small metadata envelope regardless of the size of those output resources.
    """
    plan = computation_plan_from_proto(parse_message(plan_payload, computation_pb2.ComputationPlan))
    receive_plan_resources(
        plan, streams, resource_store, max_total_bytes=max_total_bytes, registry=registry
    )
    evidence = run_computation_plan(plan, registry, resource_store, evidence_store)
    return evidence_to_proto(evidence).SerializeToString(deterministic=True)
