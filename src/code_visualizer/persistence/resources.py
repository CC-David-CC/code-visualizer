"""Explicit resource descriptor codecs, independent of storage locations."""

from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.resources import (
    DataResource,
    ResourceAxis,
    ResourceLogicalTypeReference,
    TensorDescriptor,
)
from code_visualizer.domain.values import TensorDType
from code_visualizer.persistence.values import (
    array_data,
    integer_data,
    object_data,
    text_data,
    unit_from_data,
    unit_to_data,
)


def tensor_descriptor_to_data(value: TensorDescriptor) -> dict[str, JsonValue]:
    return {
        "dtype": value.dtype.value,
        "shape": list(value.shape),
        "axes": [{"name": axis.name, "semantic_id": axis.semantic_id} for axis in value.axes],
        "unit": None if value.unit is None else unit_to_data(value.unit),
    }


def tensor_descriptor_from_data(value: object) -> TensorDescriptor:
    data = object_data(value, {"dtype", "shape", "axes", "unit"})
    axes = [object_data(axis, {"name", "semantic_id"}) for axis in array_data(data.get("axes", []))]
    return TensorDescriptor(
        TensorDType(text_data(data.get("dtype"))),
        tuple(integer_data(size) for size in array_data(data.get("shape"))),
        tuple(
            ResourceAxis(
                text_data(axis.get("name")),
                None if axis.get("semantic_id") is None else text_data(axis["semantic_id"]),
            )
            for axis in axes
        ),
        None if data.get("unit") is None else unit_from_data(data["unit"]),
    )


def resource_to_data(value: DataResource) -> dict[str, JsonValue]:
    # Untyped v1 descriptors retain their exact historical encoding and identity.
    # Typed interpretation contracts require the explicitly versioned v2 boundary.
    return {
        "version": 1 if value.logical_type is None else 2,
        "id": value.id,
        "content_hash": value.content_hash,
        "byte_size": value.byte_size,
        "media_type": value.media_type,
        "tensor": None if value.tensor is None else tensor_descriptor_to_data(value.tensor),
        "logical_type": ""
        if value.logical_type is None
        else {"id": value.logical_type.id, "version": value.logical_type.version},
    }


def resource_from_data(value: object) -> DataResource:
    data = object_data(
        value,
        {"version", "id", "content_hash", "byte_size", "media_type", "tensor", "logical_type"},
    )
    version = integer_data(data.get("version"))
    logical_type: ResourceLogicalTypeReference | None = None
    if version == 1:
        if data.get("logical_type", "") != "":
            raise ValueError(
                "Legacy resource logical types are unversioned; explicitly regenerate or "
                "re-import with a typed descriptor v2 contract"
            )
    elif version == 2:
        reference = object_data(data.get("logical_type"), {"id", "version"})
        logical_type = ResourceLogicalTypeReference(
            text_data(reference.get("id")), text_data(reference.get("version"))
        )
    else:
        raise ValueError("Unsupported resource descriptor version")
    return DataResource(
        text_data(data.get("id")),
        text_data(data.get("content_hash")),
        integer_data(data.get("byte_size")),
        text_data(data.get("media_type")),
        None if data.get("tensor") is None else tensor_descriptor_from_data(data["tensor"]),
        logical_type,
    )
