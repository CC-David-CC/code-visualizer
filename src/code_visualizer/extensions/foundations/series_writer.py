"""One bounded numeric buffer/page engine for separately typed temporal series."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import replace
from typing import TYPE_CHECKING, Protocol

from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.values import QuantityValue, ResourceReference
from code_visualizer.execution.backends import ProducedResource
from code_visualizer.extensions.fields.arrays import array_resource
from code_visualizer.extensions.fields.records import TemporalPosition
from code_visualizer.persistence.computation_resources import produced_descriptor

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


class TemporalSeries(Protocol):
    @property
    def last(self) -> TemporalPosition: ...


class NumericSeriesWriter[C, S: TemporalSeries]:
    """Publication resumes only after the existing host's complete resource ACK."""

    def __init__(
        self,
        interpretation: ResourceReference,
        source_digest: str,
        width: int,
        chunk_rows: int,
        time: Callable[[int], QuantityValue],
        chunk: Callable[[ResourceReference, TemporalPosition, TemporalPosition, int, int], C],
        series: Callable[
            [
                ResourceReference,
                str,
                tuple[C, ...],
                ResourceReference | None,
                TemporalPosition | None,
            ],
            S,
        ],
        encode: Callable[[S], bytes],
        logical_type: ResourceLogicalTypeReference,
        semantic_ids: tuple[str, ...],
        label: str,
        *,
        staged: tuple[ProducedResource, ...] = (),
        prefix: ResourceReference | None = None,
        prefix_last: TemporalPosition | None = None,
    ):
        self.interpretation, self.source_digest = interpretation, source_digest
        self.width, self.chunk_rows, self.time = width, chunk_rows, time
        self._chunk, self._series, self._encode = chunk, series, encode
        self.logical_type, self.semantic_ids, self.label = logical_type, semantic_ids, label
        self.pending: list[NDArray[np.float64]] = []
        self.positions: list[TemporalPosition] = []
        self.entries: list[C] = []
        self.staged = list(staged)
        self.prefix = self.root = prefix
        self.prefix_last = self.last = prefix_last
        self.samples = prefix_last.sample + 1 if prefix_last is not None else 0

    def _stage(self, resource: ProducedResource) -> ResourceReference:
        self.staged.append(resource)
        return produced_descriptor(resource).reference

    def sample(self, step: int, values: NDArray[np.float64]) -> bool:
        import numpy as np

        previous = self.positions[-1] if self.positions else self.last
        if previous is not None and step == previous.step:
            return False
        if previous is not None and step < previous.step:
            raise ValueError("History cannot rewind an accepted state")
        if len(self.pending) >= self.chunk_rows:
            raise ValueError("A full numeric buffer must be acknowledged before another sample")
        if (
            values.shape != (self.width,)
            or values.dtype != np.float64
            or not np.isfinite(values).all()
        ):
            raise ValueError("A sample must match its finite numeric interpretation")
        position = TemporalPosition(self.time(step), step, self.samples)
        row = np.empty(self.width + 2, dtype=np.float64)
        row[:2] = step, float(position.time.magnitude)  # type: ignore[arg-type]
        row[2:] = values
        self.pending.append(row)
        self.positions.append(position)
        self.samples += 1
        return True

    @property
    def full(self) -> bool:
        return len(self.pending) == self.chunk_rows

    def flush(self) -> Iterator[ProducedResource]:
        import numpy as np

        if not self.pending:
            return
        chunk_ref = self._stage(
            array_resource(f"samples:{self.positions[0].sample}", np.stack(self.pending))
        )
        chunk = self._chunk(
            chunk_ref, self.positions[0], self.positions[-1], len(self.pending), self.width
        )
        entries = (*self.entries, chunk)
        series = self._series(
            self.interpretation, self.source_digest, entries, self.prefix, self.prefix_last
        )
        try:
            payload = self._encode(series)
        except ValueError:
            if self.root is None or self.last is None or not self.entries:
                raise
            self.prefix, self.prefix_last = self.root, self.last
            entries = (chunk,)
            series = self._series(
                self.interpretation, self.source_digest, entries, self.prefix, self.prefix_last
            )
            payload = self._encode(series)
        resource = ProducedResource(
            f"history:{series.last.step}",
            payload,
            "application/json",
            self.semantic_ids,
            f"{self.label} through t={float(self.time(series.last.step).magnitude):.9g} s",  # type: ignore[arg-type]
            logical_type=self.logical_type,
            dependencies=tuple(self.staged),
        )
        yield resource
        self.root = produced_descriptor(replace(resource, dependencies=())).reference
        self.last = series.last
        self.entries = list(entries)
        self.pending.clear()
        self.positions.clear()
        self.staged.clear()
