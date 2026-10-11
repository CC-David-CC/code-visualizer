"""Shared bounded temporal coverage and numeric cache, independent of notation/support."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from code_visualizer.domain.values import QuantityValue, ResourceReference, UnitReference
from code_visualizer.execution.backends import ResolvedResource
from code_visualizer.extensions.fields.arrays import read_array
from code_visualizer.extensions.fields.records import TemporalPosition, scalar

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

CACHE_BYTES = 64 * 1024 * 1024


class TimedChunk(Protocol):
    @property
    def resource(self) -> ResourceReference: ...
    @property
    def first(self) -> TemporalPosition: ...
    @property
    def last(self) -> TemporalPosition: ...
    @property
    def rows(self) -> int: ...
    @property
    def value_count(self) -> int: ...


class IndexedSeries[C: TimedChunk](Protocol):
    @property
    def interpretation(self) -> ResourceReference: ...
    @property
    def source_digest(self) -> str: ...
    @property
    def chunks(self) -> tuple[C, ...]: ...
    @property
    def prefix(self) -> ResourceReference | None: ...
    @property
    def prefix_last(self) -> TemporalPosition | None: ...
    @property
    def last(self) -> TemporalPosition: ...


@dataclass(frozen=True, slots=True)
class NumericSlice:
    series: ResourceReference
    interpretation: ResourceReference
    source_digest: str
    position: TemporalPosition
    values: NDArray[np.float64]


class NumericHistory[C: TimedChunk]:
    """The interpretation-specific reader admits records and physical support."""

    def __init__(
        self,
        root: ResourceReference,
        resolve: Callable[[ResourceReference], ResolvedResource],
        series: IndexedSeries[C],
        load_series: Callable[[ResourceReference], IndexedSeries[C]],
        width: int,
        time_unit: UnitReference,
        *,
        cache_bytes: int = CACHE_BYTES,
    ):
        if type(cache_bytes) is not int or not 0 <= cache_bytes <= CACHE_BYTES:
            raise ValueError("History cache exceeds 64 MiB")
        self.root, self.resolve, self.limit = root, resolve, cache_bytes
        self._cache: OrderedDict[ResourceReference, NDArray[np.float64]] = OrderedDict()
        self.cache_bytes = self.decoded_chunks = 0
        self._series = series
        seen: set[ResourceReference] = set()
        pages: list[IndexedSeries[C]] = []
        current, reference = series, root
        metadata_bytes = 0
        while True:
            if reference in seen or len(seen) >= 64:
                raise ValueError("History prefix cycle or depth limit")
            seen.add(reference)
            metadata_bytes += resolve(reference).descriptor.byte_size
            if metadata_bytes > 2 * 1024 * 1024:
                raise ValueError("History exceeds its metadata envelope")
            if (
                current.interpretation != series.interpretation
                or current.source_digest != series.source_digest
            ):
                raise ValueError("History pages do not share one interpretation/input")
            pages.append(current)
            if current.prefix is None:
                break
            parent = load_series(current.prefix)
            if parent.last != current.prefix_last:
                raise ValueError("History prefix does not end at its claimed accepted position")
            reference, current = current.prefix, parent
        self.chunks = tuple(chunk for page in reversed(pages) for chunk in page.chunks)
        if len(self.chunks) > 1024 or any(chunk.value_count != width for chunk in self.chunks):
            raise ValueError("History chunks exceed closure limits or disagree with support")
        if any(chunk.first.time.unit != time_unit for chunk in self.chunks):
            raise ValueError("History physical time must share the declared unit")
        self.sample_count = series.last.sample + 1

    def _array(self, chunk: C) -> NDArray[np.float64]:
        import numpy as np

        cached = self._cache.pop(chunk.resource, None)
        if cached is not None:
            self._cache[chunk.resource] = cached
            return cached
        resource = self.resolve(chunk.resource)
        tensor = resource.descriptor.tensor
        if tensor is not None and tensor.unit is not None:
            raise ValueError("Mixed step/time/value columns cannot declare one array unit")
        values = read_array(resource, (chunk.rows, chunk.value_count + 2))
        steps, times = values[:, 0], values[:, 1]
        if (
            not np.equal(steps, np.floor(steps)).all()
            or np.any(np.diff(steps) <= 0)
            or np.any(np.diff(times) <= 0)
            or steps[0] != chunk.first.step
            or steps[-1] != chunk.last.step
            or times[0] != scalar(chunk.first.time, "First time")
            or times[-1] != scalar(chunk.last.time, "Last time")
        ):
            raise ValueError("Chunk samples disagree with their declared physical coverage")
        self.decoded_chunks += 1
        while self._cache and self.cache_bytes + values.nbytes > self.limit:
            _, retired = self._cache.popitem(last=False)
            self.cache_bytes -= retired.nbytes
        if values.nbytes <= self.limit:
            self._cache[chunk.resource] = values
            self.cache_bytes += values.nbytes
        return values

    def iter_chunks(self) -> Iterator[tuple[C, NDArray[np.float64]]]:
        for chunk in self.chunks:
            yield chunk, self._array(chunk)

    def slice(self, sample: int) -> NumericSlice:
        if type(sample) is not int or not 0 <= sample < self.sample_count:
            raise ValueError("Select an exact retained sample; no clamping or interpolation")
        chunk = next(
            item for item in self.chunks if item.first.sample <= sample <= item.last.sample
        )
        row = self._array(chunk)[sample - chunk.first.sample]
        position = TemporalPosition(
            QuantityValue(float(row[1]), chunk.first.time.unit), int(row[0]), sample
        )
        values = row[2:].copy()
        values.setflags(write=False)
        return NumericSlice(
            self.root, self._series.interpretation, self._series.source_digest, position, values
        )

    def close(self) -> None:
        self._cache.clear()
        self.cache_bytes = 0
