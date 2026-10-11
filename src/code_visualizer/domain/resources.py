"""Immutable descriptions of external data; no domain-specific field ontology."""

from __future__ import annotations

from dataclasses import dataclass

from code_visualizer.domain.identifiers import (
    validate_contract_version,
    validate_global_contract_id,
)
from code_visualizer.domain.values import (
    ResourceReference,
    TensorDType,
    UnitReference,
    validate_shape,
)


@dataclass(frozen=True, slots=True)
class ResourceLogicalTypeReference:
    """An exact public interpretation contract, independent of media type and storage."""

    id: str
    version: str

    def __post_init__(self) -> None:
        validate_global_contract_id(self.id)
        validate_contract_version(self.version)


TERMINAL_LOGICAL_TYPE = ResourceLogicalTypeReference("code_visualizer.computation.terminal", "2")


@dataclass(frozen=True, slots=True)
class ResourceAxis:
    name: str
    semantic_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name or len(self.name) > 1024:
            raise ValueError("Resource axes require bounded names")
        if self.semantic_id is not None and (
            not isinstance(self.semantic_id, str)
            or not self.semantic_id
            or len(self.semantic_id) > 1024
        ):
            raise ValueError("Axis semantic identities must be nonempty bounded text")


@dataclass(frozen=True, slots=True)
class TensorDescriptor:
    dtype: TensorDType
    shape: tuple[int, ...]
    axes: tuple[ResourceAxis, ...] = ()
    unit: UnitReference | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.dtype, TensorDType):
            raise ValueError("Unknown tensor dtype")
        validate_shape(self.shape)
        if type(self.axes) is not tuple or (self.axes and len(self.axes) != len(self.shape)):
            raise ValueError("Resource axes must be immutable and match the tensor rank")
        if any(not isinstance(axis, ResourceAxis) for axis in self.axes):
            raise ValueError("Expected typed resource axes")
        if len({axis.name for axis in self.axes}) != len(self.axes):
            raise ValueError("Resource axis names must be unique")
        if self.unit is not None and not isinstance(self.unit, UnitReference):
            raise ValueError("Expected versioned unit reference")


@dataclass(frozen=True, slots=True)
class DataResource:
    id: str
    content_hash: str
    byte_size: int
    media_type: str
    tensor: TensorDescriptor | None = None
    logical_type: ResourceLogicalTypeReference | None = None

    def __post_init__(self) -> None:
        ResourceReference(self.id, self.content_hash)
        if type(self.byte_size) is not int or not 0 <= self.byte_size < 1 << 63:
            raise ValueError("Resource size must be a nonnegative signed 64-bit integer")
        if (
            not isinstance(self.media_type, str)
            or not self.media_type
            or len(self.media_type) > 1024
        ):
            raise ValueError("Resources require a bounded media type")
        if self.logical_type is not None and not isinstance(
            self.logical_type, ResourceLogicalTypeReference
        ):
            raise ValueError("Logical type must be a typed public reference or absent")
        if self.tensor is not None and not isinstance(self.tensor, TensorDescriptor):
            raise ValueError("Expected typed tensor descriptor")

    @property
    def reference(self) -> ResourceReference:
        return ResourceReference(self.id, self.content_hash)
