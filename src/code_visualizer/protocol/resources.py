"""Resource metadata crosses the wire; immutable content stays in the managed store."""

from code_visualizer.domain.resources import (
    DataResource,
    ResourceAxis,
    ResourceLogicalTypeReference,
    TensorDescriptor,
)
from code_visualizer.protocol.v1 import resource_pb2 as wire
from code_visualizer.protocol.validation import ProtocolBoundaryError, check_message, invalid
from code_visualizer.protocol.values import (
    dtype_from_proto,
    dtype_to_proto,
    unit_from_proto,
    unit_to_proto,
)


def resource_to_proto(value: DataResource) -> wire.DataResource:
    result = wire.DataResource(
        schema_version=1 if value.logical_type is None else 2,
        id=value.id,
        content_hash=value.content_hash,
        byte_size=value.byte_size,
        media_type=value.media_type,
    )
    if value.logical_type is not None:
        result.logical_type_reference.CopyFrom(
            wire.ResourceLogicalTypeReference(
                id=value.logical_type.id, version=value.logical_type.version
            )
        )
    if value.tensor is not None:
        tensor = value.tensor
        result.tensor.CopyFrom(
            wire.TensorDescriptor(dtype=dtype_to_proto(tensor.dtype), shape=tensor.shape)
        )
        for axis in tensor.axes:
            item = result.tensor.axes.add(name=axis.name)
            if axis.semantic_id is not None:
                item.semantic_id = axis.semantic_id
        if tensor.unit is not None:
            result.tensor.unit.CopyFrom(unit_to_proto(tensor.unit))
    check_message(result)
    return result


def resource_from_proto(value: wire.DataResource) -> DataResource:
    check_message(value)
    logical_type: ResourceLogicalTypeReference | None = None
    if value.schema_version == 1:
        if value.HasField("logical_type_reference"):
            raise invalid("A typed resource logical type requires descriptor version 2")
    elif value.schema_version == 2:
        if not value.HasField("logical_type_reference"):
            raise invalid("Resource descriptor version 2 requires a typed logical type")
        logical_type = ResourceLogicalTypeReference(
            value.logical_type_reference.id, value.logical_type_reference.version
        )
    else:
        raise ProtocolBoundaryError(
            "PROTOCOL_VERSION_UNSUPPORTED", "Supported resource descriptor versions are 1 and 2"
        )
    tensor = None
    if value.HasField("tensor"):
        t = value.tensor
        tensor = TensorDescriptor(
            dtype_from_proto(t.dtype),
            tuple(t.shape),
            tuple(
                ResourceAxis(a.name, a.semantic_id if a.HasField("semantic_id") else None)
                for a in t.axes
            ),
            unit_from_proto(t.unit) if t.HasField("unit") else None,
        )
    return DataResource(
        value.id, value.content_hash, value.byte_size, value.media_type, tensor, logical_type
    )
