"""Strict, bounded v1 resource frames for portable workers and trusted transports."""

from code_visualizer.domain.resource_transfer import (
    ResourceTransferAbort,
    ResourceTransferChunk,
    ResourceTransferFinish,
    ResourceTransferFrame,
    ResourceTransferStart,
)
from code_visualizer.protocol.resources import resource_from_proto, resource_to_proto
from code_visualizer.protocol.v1 import resource_pb2 as wire
from code_visualizer.protocol.validation import check_message, invalid


def resource_frame_to_proto(value: ResourceTransferFrame) -> wire.ResourceTransferFrame:
    result = wire.ResourceTransferFrame(schema_version=1, transfer_id=value.transfer_id)
    if isinstance(value, ResourceTransferStart):
        result.start.CopyFrom(resource_to_proto(value.resource))
    elif isinstance(value, ResourceTransferChunk):
        result.chunk.CopyFrom(wire.ResourceChunk(offset=value.offset, data=value.data))
    elif isinstance(value, ResourceTransferFinish):
        result.finish.SetInParent()
    elif isinstance(value, ResourceTransferAbort):
        result.abort.CopyFrom(wire.ResourceTransferAbort(reason=value.reason))
    else:
        raise invalid("Unknown resource transfer frame")
    check_message(result, version=1)
    return result


def resource_frame_from_proto(value: wire.ResourceTransferFrame) -> ResourceTransferFrame:
    check_message(value, version=value.schema_version)
    match value.WhichOneof("frame"):
        case "start":
            return ResourceTransferStart(value.transfer_id, resource_from_proto(value.start))
        case "chunk":
            return ResourceTransferChunk(value.transfer_id, value.chunk.offset, value.chunk.data)
        case "finish":
            return ResourceTransferFinish(value.transfer_id)
        case "abort":
            return ResourceTransferAbort(value.transfer_id, value.abort.reason)
        case _:
            raise invalid("A resource transfer frame variant must be present")
