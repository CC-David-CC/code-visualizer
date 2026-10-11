"""Bounded exact channel reduction, source checks and trial decoration; no Qt or solver."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from code_visualizer.domain.preview import PreviewEvent
from code_visualizer.domain.values import ResourceReference
from code_visualizer.execution.backends import ResolvedResource
from code_visualizer.extensions.channels.history import ChannelHistory
from code_visualizer.extensions.channels.preview import ChannelPreview, channel_preview
from code_visualizer.extensions.channels.records import ChannelInterpretation
from code_visualizer.extensions.fields.records import TemporalPosition, index


@dataclass(frozen=True, slots=True)
class ChannelPresentation:
    resource: ResourceReference
    definition_digest: str
    interpretation: ChannelInterpretation
    selected: TemporalPosition
    values: tuple[float, ...]
    channel_id: str
    sample_count: int
    curve: tuple[tuple[float, float], ...]
    preview: ChannelPreview | None = None
    base_retained: bool = False


class ChannelPresentationReader:
    """One reader/cache owned by one background view worker."""

    def __init__(self) -> None:
        self.history: ChannelHistory | None = None
        self.owner: object | None = None
        self._curve: tuple[tuple[float, float], ...] = ()
        self._channel = ""

    def close(self) -> None:
        if self.history is not None:
            self.history.close()
        self.history, self.owner, self._curve, self._channel = None, None, (), ""

    def prepare(
        self,
        resource: ResourceReference,
        resolve: Callable[[ResourceReference], ResolvedResource],
        owner: object,
        sample: int | None,
        channel_id: str | None = None,
        *,
        preview: PreviewEvent | None = None,
        session_id: str = "",
        input_digest: str = "",
        cancelled: Callable[[], bool] = lambda: False,
    ) -> ChannelPresentation:
        def check() -> None:
            if cancelled():
                raise InterruptedError("Channel view request was replaced")

        check()
        if self.history is None or self.history.root != resource or self.owner != owner:
            self.close()
            self.history = ChannelHistory(resource, resolve)
            self.owner = owner
        history = self.history
        selected = history.slice(history.sample_count - 1 if sample is None else sample)
        channels = history.interpretation.channels
        channel_id = channel_id or channels[0].id
        column = next((i for i, c in enumerate(channels) if c.id == channel_id), None)
        if column is None:
            raise ValueError("Selected channel is absent from this interpretation")
        if self._channel != channel_id:
            self._curve = self._reduce(column, check)
            self._channel = channel_id
        check()
        trial, retained = None, False
        if preview is not None:
            if preview.session_id != session_id or preview.input_digest != input_digest:
                raise ValueError("CHANNEL_PREVIEW_SOURCE: another attempt/input")
            trial = channel_preview(preview)
            positions = tuple(index(i, "Channel index") for i in trial.indices.elements)
            if (
                trial.definition_digest != history.series.source_digest
                or trial.interpretation != history.series.interpretation
                or preview.semantic_ids != (history.interpretation.owner_id,)
                or trial.base_time.unit != history.interpretation.time_unit
                or positions[-1] >= len(channels)
            ):
                raise ValueError("CHANNEL_PREVIEW_MEANING: another source/channel/time meaning")
            for chunk in history.chunks:
                if chunk.first.step <= trial.base_step <= chunk.last.step:
                    # Read only the one possible chunk. The base need not have
                    # been sampled, so its window number is never a sample index.
                    low, high = chunk.first.sample, chunk.last.sample
                    while low <= high:
                        middle = (low + high) // 2
                        row = history.slice(middle)
                        if row.position.step == trial.base_step:
                            retained = True
                            if (
                                row.position.time != trial.base_time
                                or tuple(float(row.values[i]) for i in positions)
                                != trial.base_values.elements
                            ):
                                raise ValueError("CHANNEL_PREVIEW_BASE: contradicts retained base")
                            break
                        if row.position.step < trial.base_step:
                            low = middle + 1
                        else:
                            high = middle - 1
                    break
        check()
        return ChannelPresentation(
            resource,
            history.series.source_digest,
            history.interpretation,
            selected.position,
            tuple(float(v) for v in selected.values),
            channel_id,
            history.sample_count,
            self._curve,
            trial,
            retained,
        )

    def _reduce(self, column: int, check: Callable[[], None]) -> tuple[tuple[float, float], ...]:
        """Retain min/max of every bin, with actual time; at most 600 points."""
        import numpy as np

        history = self.history
        assert history is not None
        width = min(300, history.sample_count)
        minima: dict[int, tuple[float, float]] = {}
        maxima: dict[int, tuple[float, float]] = {}
        for chunk, rows in history.iter_chunks():
            check()
            bins = (np.arange(len(rows)) + chunk.first.sample) * width // history.sample_count
            keys, starts = np.unique(bins, return_index=True)
            ends = (*starts[1:], len(rows))
            for key, start, end in zip(keys, starts, ends, strict=True):
                values = rows[start:end, 2 + column]
                low = rows[start + int(np.argmin(values))]
                high = rows[start + int(np.argmax(values))]
                bottom, top = (
                    (float(low[1]), float(low[2 + column])),
                    (float(high[1]), float(high[2 + column])),
                )
                if key not in minima or bottom[1] < minima[key][1]:
                    minima[int(key)] = bottom
                if key not in maxima or top[1] > maxima[key][1]:
                    maxima[int(key)] = top
        return tuple(sorted({*minima.values(), *maxima.values()}))
