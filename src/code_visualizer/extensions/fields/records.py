"""Version 1 field, temporal and restart records, independent of NumPy and Qt.

These are resource interpretations, not additional canonical project contents.
Coordinates and sample vectors live in immutable resources. IDs refer to authored
meaning; physical time is neither a transport sequence nor a display clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from re import fullmatch

from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.values import QuantityValue, ResourceReference, UnitReference
from code_visualizer.execution.resource_interpretation import ResourceDependency
from code_visualizer.extensions.foundations.unit_algebra import QuantityKind

METADATA_LIMIT = 64 * 1024
CHUNK_BYTES = 4 * 1024 * 1024
PAGE_ENTRIES = 256
ARRAY_TYPE = ResourceLogicalTypeReference("foundation.fields.float64_array", "1")
SUPPORT_TYPE = ResourceLogicalTypeReference("foundation.fields.uniform_support", "1")
INTERPRETATION_TYPE = ResourceLogicalTypeReference("foundation.fields.scalar_interpretation", "1")
SERIES_TYPE = ResourceLogicalTypeReference("foundation.fields.series", "1")
CHECKPOINT_TYPE = ResourceLogicalTypeReference("code_visualizer.diffusion.checkpoint", "1")
PREVIEW_TYPE = ResourceLogicalTypeReference("foundation.fields.scalar_preview", "1")


def identity(value: str) -> None:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 1024:
        raise ValueError("Field records require bounded nonempty identities")


def index(value: object, name: str) -> int:
    if type(value) is not int or not 0 <= value < 1 << 53:
        raise ValueError(f"{name} must be an exact nonnegative integer")
    return value


def digest(value: str) -> None:
    if not isinstance(value, str) or not fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Field records require an exact SHA-256 compatibility identity")


def scalar(value: QuantityValue, name: str) -> float:
    if not isinstance(value, QuantityValue) or not isinstance(value.magnitude, (float, int)):
        raise ValueError(f"{name} requires a real scalar quantity")
    if not isfinite(value.magnitude):
        raise ValueError(f"{name} must be finite")
    return float(value.magnitude)


def ref(value: ResourceReference) -> None:
    if not isinstance(value, ResourceReference):
        raise ValueError("Field records require typed resource references")


@dataclass(frozen=True, slots=True)
class UniformSupport:
    space_id: str
    frame_id: str
    axis_id: str
    axis_name: str
    origin: QuantityValue
    spacing: QuantityValue
    nodes: int
    coordinates: ResourceReference
    frame_kind: str = "cartesian_1d"

    def __post_init__(self) -> None:
        for value in (self.space_id, self.frame_id, self.axis_id, self.axis_name):
            identity(value)
        scalar(self.origin, "Origin")
        scalar(self.spacing, "Spacing")
        index(self.nodes, "Node count")
        ref(self.coordinates)
        if self.nodes < 3 or self.nodes > 262144 or scalar(self.spacing, "Spacing") <= 0:
            raise ValueError("Uniform support requires a positive spacing and 3..262144 nodes")
        if self.origin.unit != self.spacing.unit or self.frame_kind != "cartesian_1d":
            raise ValueError("Unsupported coordinate units or frame interpretation")

    def dependencies(self) -> tuple[ResourceDependency, ...]:
        return (ResourceDependency(self.coordinates, ARRAY_TYPE),)


@dataclass(frozen=True, slots=True)
class FieldInterpretation:
    field_id: str
    support: ResourceReference
    unit: UnitReference
    quantity_kind: QuantityKind
    component_id: str = "scalar"
    association: str = "node"
    dtype: str = "float64"
    mask_policy: str = "all_finite"

    def __post_init__(self) -> None:
        identity(self.field_id)
        identity(self.component_id)
        ref(self.support)
        if (
            not isinstance(self.unit, UnitReference)
            or self.quantity_kind
            not in (QuantityKind.LINEAR, QuantityKind.INTERVAL, QuantityKind.POINT)
            or not isinstance(self.quantity_kind, QuantityKind)
        ):
            raise ValueError("Field interpretation requires an exact unit and quantity kind")
        if (self.association, self.dtype, self.mask_policy) != ("node", "float64", "all_finite"):
            raise ValueError("Unsupported field association, dtype or validity policy")

    def dependencies(self) -> tuple[ResourceDependency, ...]:
        return (ResourceDependency(self.support, SUPPORT_TYPE),)


@dataclass(frozen=True, slots=True)
class TemporalPosition:
    time: QuantityValue
    step: int
    sample: int

    def __post_init__(self) -> None:
        scalar(self.time, "Physical time")
        index(self.step, "Accepted step")
        index(self.sample, "Sample index")
        if scalar(self.time, "Physical time") < 0:
            raise ValueError("Physical time must be nonnegative")


@dataclass(frozen=True, slots=True)
class SampleChunk:
    resource: ResourceReference
    first: TemporalPosition
    last: TemporalPosition
    rows: int
    nodes: int

    @property
    def value_count(self) -> int:
        return self.nodes

    def __post_init__(self) -> None:
        ref(self.resource)
        if not isinstance(self.first, TemporalPosition) or not isinstance(
            self.last, TemporalPosition
        ):
            raise ValueError("A chunk requires exact temporal positions")
        index(self.rows, "Chunk rows")
        index(self.nodes, "Chunk nodes")
        if self.rows < 1 or self.nodes < 3 or self.rows * (self.nodes + 2) * 8 > CHUNK_BYTES - 128:
            raise ValueError("Numeric chunk exceeds its 4 MiB bound")
        if self.last.sample - self.first.sample != self.rows - 1:
            raise ValueError("Chunk coverage contains gaps or overlap")
        if self.first.time.unit != self.last.time.unit or self.last.step < self.first.step:
            raise ValueError("Chunk times/steps have incompatible interpretations")
        if self.rows == 1 and self.first != self.last:
            raise ValueError("One sample has exactly one physical position")
        if self.rows > 1 and (
            self.last.step <= self.first.step
            or scalar(self.last.time, "Last time") <= scalar(self.first.time, "First time")
        ):
            raise ValueError("Chunk physical positions must advance")


@dataclass(frozen=True, slots=True)
class FieldSeries:
    interpretation: ResourceReference
    source_digest: str
    chunks: tuple[SampleChunk, ...]
    prefix: ResourceReference | None = None
    prefix_last: TemporalPosition | None = None

    def __post_init__(self) -> None:
        ref(self.interpretation)
        digest(self.source_digest)
        if type(self.chunks) is not tuple or not 1 <= len(self.chunks) <= PAGE_ENTRIES:
            raise ValueError("A series page requires 1..256 immutable chunk entries")
        if any(not isinstance(item, SampleChunk) for item in self.chunks):
            raise ValueError("A series requires typed sample chunks")
        if (self.prefix is None) != (self.prefix_last is None):
            raise ValueError("A prefix requires its exact last accepted position")
        if self.prefix is not None:
            ref(self.prefix)
        previous = self.prefix_last
        for chunk in self.chunks:
            if previous is None and chunk.first.sample != 0:
                raise ValueError("A series must begin at sample zero or name its prefix")
            if previous is not None and (
                chunk.first.sample != previous.sample + 1
                or chunk.first.step <= previous.step
                or chunk.first.time.unit != previous.time.unit
                or scalar(chunk.first.time, "Chunk time") <= scalar(previous.time, "Previous time")
            ):
                raise ValueError("Series coverage contains gaps, overlap or incompatible times")
            if chunk.nodes != self.chunks[0].nodes:
                raise ValueError("Series chunks must share their spatial shape")
            previous = chunk.last

    @property
    def last(self) -> TemporalPosition:
        return self.chunks[-1].last

    def dependencies(self) -> tuple[ResourceDependency, ...]:
        return (
            ResourceDependency(self.interpretation, INTERPRETATION_TYPE),
            *((ResourceDependency(self.prefix, SERIES_TYPE),) if self.prefix is not None else ()),
            *(ResourceDependency(item.resource, ARRAY_TYPE) for item in self.chunks),
        )


@dataclass(frozen=True, slots=True)
class DiffusionCheckpoint:
    compatibility_digest: str
    interpretation: ResourceReference
    state: ResourceReference
    prefix: ResourceReference
    position: TemporalPosition
    numerical_identity: str
    policy_digest: str
    next_sample_step: int
    next_checkpoint_step: int
    method: str = "crank_nicolson_fixed"
    state_version: int = 1
    dtype: str = "float64"

    def __post_init__(self) -> None:
        digest(self.compatibility_digest)
        digest(self.policy_digest)
        for resource in (self.interpretation, self.state, self.prefix):
            ref(resource)
        if not isinstance(self.position, TemporalPosition):
            raise ValueError("Checkpoint requires an accepted physical position")
        identity(self.numerical_identity)
        index(self.next_sample_step, "Next sample step")
        index(self.next_checkpoint_step, "Next checkpoint step")
        if (
            self.next_sample_step <= self.position.step
            or self.next_checkpoint_step <= self.position.step
        ):
            raise ValueError("Checkpoint output cursors must follow the accepted state")
        if (self.method, self.state_version, self.dtype) != ("crank_nicolson_fixed", 1, "float64"):
            raise ValueError("Unsupported numerical checkpoint method/state format")
        if type(self.state_version) is not int:
            raise ValueError("Checkpoint format version must be an integer")

    def dependencies(self) -> tuple[ResourceDependency, ...]:
        return (
            ResourceDependency(self.interpretation, INTERPRETATION_TYPE),
            ResourceDependency(self.state, ARRAY_TYPE),
            ResourceDependency(self.prefix, SERIES_TYPE),
        )
