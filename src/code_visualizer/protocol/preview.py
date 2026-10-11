"""Explicit v1 preview envelope at the worker boundary only."""

from code_visualizer.domain.preview import PreviewEvent
from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.values import MAX_INLINE_BYTES
from code_visualizer.protocol.computation import parameter_from_proto, parameter_to_proto
from code_visualizer.protocol.v1.identity_pb2 import VersionedReference
from code_visualizer.protocol.v1.worker_pb2 import PreviewEvent as WirePreview
from code_visualizer.protocol.validation import check_message, invalid, require_field


def preview_to_proto(value: PreviewEvent) -> WirePreview:
    result = WirePreview(
        schema_version=1,
        session_id=value.session_id,
        sequence=value.sequence,
        input_digest=value.input_digest,
        interpretation=VersionedReference(
            id=value.interpretation.id, version=value.interpretation.version
        ),
        semantic_ids=value.semantic_ids,
        values=[parameter_to_proto(item) for item in value.values],
    )
    check_message(result, version=1)
    if result.ByteSize() > MAX_INLINE_BYTES:
        raise invalid("A preview exceeds the 64 KiB inline envelope")
    return result


def preview_from_proto(value: WirePreview) -> PreviewEvent:
    check_message(value, version=value.schema_version)
    require_field(value, "interpretation")
    if len(value.values) > 32 or value.ByteSize() > MAX_INLINE_BYTES:
        raise invalid("A preview exceeds its inline bounds")
    return PreviewEvent(
        value.session_id,
        value.sequence,
        value.input_digest,
        ResourceLogicalTypeReference(value.interpretation.id, value.interpretation.version),
        tuple(value.semantic_ids),
        tuple(parameter_from_proto(item) for item in value.values),
    )
