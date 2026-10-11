"""Independent closed channel meanings; no temperature-specific kernel types."""

from dataclasses import dataclass

from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.values import ResourceReference, UnitReference
from code_visualizer.execution.resource_interpretation import ResourceDependency
from code_visualizer.extensions.fields.records import (
    ARRAY_TYPE,
    CHUNK_BYTES,
    PAGE_ENTRIES,
    TemporalPosition,
    digest,
    identity,
    index,
    ref,
    scalar,
)
from code_visualizer.extensions.foundations.unit_algebra import QuantityKind
from code_visualizer.extensions.foundations.units_si import si_catalog

INTERPRETATION_TYPE = ResourceLogicalTypeReference("foundation.channels.interpretation", "1")
SERIES_TYPE = ResourceLogicalTypeReference("foundation.channels.series", "1")


@dataclass(frozen=True, slots=True)
class Channel:
    id: str
    name: str
    semantic_ids: tuple[str, ...]
    support_id: str
    unit: UnitReference
    quantity_kind: QuantityKind
    support_kind: str = "lumped_object"

    def __post_init__(self) -> None:
        for value in (self.id, self.name, self.support_id):
            identity(value)
        if (
            type(self.semantic_ids) is not tuple
            or not 1 <= len(self.semantic_ids) <= 32
            or len(set(self.semantic_ids)) != len(self.semantic_ids)
        ):
            raise ValueError("Channels require bounded distinct semantic origins")
        for node in self.semantic_ids:
            identity(node)
        if (
            not isinstance(self.unit, UnitReference)
            or not isinstance(self.quantity_kind, QuantityKind)
            or self.support_kind != "lumped_object"
        ):
            raise ValueError("A channel requires typed units/kind on a named lumped support")


@dataclass(frozen=True, slots=True)
class ChannelInterpretation:
    owner_id: str
    channels: tuple[Channel, ...]
    time_unit: UnitReference
    dtype: str = "float64"
    mask_policy: str = "all_finite"

    def __post_init__(self) -> None:
        identity(self.owner_id)
        if (
            type(self.channels) is not tuple
            or not 1 <= len(self.channels) <= 64
            or any(not isinstance(item, Channel) for item in self.channels)
            or len({item.id for item in self.channels}) != len(self.channels)
        ):
            raise ValueError("An interpretation requires 1..64 distinct typed channels")
        if (
            not isinstance(self.time_unit, UnitReference)
            or self.time_unit.dimension != si_catalog().unit("foundation.units.si:second").dimension
            or self.dtype != "float64"
            or self.mask_policy != "all_finite"
        ):
            raise ValueError("Channel time/numeric interpretation is unsupported")

    def dependencies(self) -> tuple[ResourceDependency, ...]:
        return ()


@dataclass(frozen=True, slots=True)
class ChannelChunk:
    resource: ResourceReference
    first: TemporalPosition
    last: TemporalPosition
    rows: int
    columns: int

    @property
    def value_count(self) -> int:
        return self.columns

    def __post_init__(self) -> None:
        ref(self.resource)
        index(self.rows, "Chunk rows")
        index(self.columns, "Channel columns")
        if (
            not isinstance(self.first, TemporalPosition)
            or not isinstance(self.last, TemporalPosition)
            or not 1 <= self.columns <= 64
            or self.rows < 1
            or self.rows * (self.columns + 2) * 8 > CHUNK_BYTES - 128
        ):
            raise ValueError("Invalid bounded channel chunk")
        if (
            self.last.sample - self.first.sample != self.rows - 1
            or self.first.time.unit != self.last.time.unit
            or self.last.step < self.first.step
            or (self.rows == 1 and self.first != self.last)
            or (
                self.rows > 1
                and (
                    self.last.step <= self.first.step
                    or scalar(self.last.time, "Last") <= scalar(self.first.time, "First")
                )
            )
        ):
            raise ValueError("Channel chunk coverage contains gaps/overlap or mixed physical time")


@dataclass(frozen=True, slots=True)
class ChannelSeries:
    interpretation: ResourceReference
    source_digest: str
    chunks: tuple[ChannelChunk, ...]
    prefix: ResourceReference | None = None
    prefix_last: TemporalPosition | None = None

    def __post_init__(self) -> None:
        ref(self.interpretation)
        digest(self.source_digest)
        if (
            type(self.chunks) is not tuple
            or not 1 <= len(self.chunks) <= PAGE_ENTRIES
            or any(not isinstance(item, ChannelChunk) for item in self.chunks)
        ):
            raise ValueError("A channel page requires bounded typed chunks")
        if (self.prefix is None) != (self.prefix_last is None):
            raise ValueError("A prefix must name its last accepted position")
        if self.prefix is not None:
            ref(self.prefix)
            if not isinstance(self.prefix_last, TemporalPosition):
                raise ValueError("A prefix requires a typed position")
        previous = self.prefix_last
        for chunk in self.chunks:
            if previous is None and chunk.first.sample != 0:
                raise ValueError("Channel history starts at zero or an explicit prefix")
            if previous is not None and (
                chunk.first.sample != previous.sample + 1
                or chunk.first.step <= previous.step
                or chunk.first.time.unit != previous.time.unit
                or scalar(chunk.first.time, "Time") <= scalar(previous.time, "Previous time")
            ):
                raise ValueError("Channel pages have gaps, overlap or mixed time")
            if chunk.columns != self.chunks[0].columns:
                raise ValueError("All channel chunks require one column interpretation")
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
