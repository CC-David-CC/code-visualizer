"""Bounded field reduction; no Qt, simulation clock or mutation of scientific data."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING

from code_visualizer.domain.preview import PreviewEvent
from code_visualizer.domain.values import ResourceReference
from code_visualizer.execution.backends import ResolvedResource
from code_visualizer.extensions.fields.history import FieldHistory
from code_visualizer.extensions.fields.preview import FieldPreview, field_preview
from code_visualizer.extensions.fields.records import (
    FieldInterpretation,
    TemporalPosition,
    UniformSupport,
)
from code_visualizer.extensions.fields.records import (
    index as canonical_index,
)

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class FieldPresentation:
    resource: ResourceReference
    definition_digest: str
    interpretation: FieldInterpretation
    interpretation_reference: ResourceReference
    support: UniformSupport
    selected: TemporalPosition
    sample_count: int
    profile: tuple[tuple[float, float], ...]
    value_range: tuple[float, float]
    rgba: bytes = b""
    image_width: int = 0
    image_height: int = 0
    image_times: tuple[TemporalPosition, ...] = ()
    preview: FieldPreview | None = None


def reduce_profile(
    values: NDArray[np.float64], width: int = 600
) -> tuple[tuple[float, float], ...]:
    """Preserve each bin's extrema, instead of hiding peaks through point skipping."""
    import numpy as np

    count = len(values)
    edges = np.linspace(0, count, min(width, count) + 1, dtype=int)
    points: list[tuple[float, float]] = []
    for start, end in pairwise(edges):
        selected = values[start:end]
        locations = sorted({start + int(np.argmin(selected)), start + int(np.argmax(selected))})
        points.extend((index / (count - 1), float(values[index])) for index in locations)
    return tuple(points)


class FieldPresentationReader:
    """One worker owns one 64 MiB LRU. Replacing a view drops the previous mappings."""

    def __init__(self) -> None:
        self.history: FieldHistory | None = None
        self.owner: object | None = None

    def close(self) -> None:
        if self.history is not None:
            self.history.close()
        self.history, self.owner = None, None

    def prepare(
        self,
        resource: ResourceReference,
        resolve: Callable[[ResourceReference], ResolvedResource],
        owner: object,
        sample: int | None,
        *,
        overview: bool = False,
        preview: PreviewEvent | None = None,
        session_id: str = "",
        input_digest: str = "",
        cancelled: Callable[[], bool] = lambda: False,
    ) -> FieldPresentation:
        import numpy as np

        def check() -> None:
            if cancelled():
                raise InterruptedError("Field view request was replaced")

        check()
        if self.history is None or self.history.root != resource or self.owner != owner:
            self.close()
            self.history = FieldHistory(resource, resolve)
            self.history.coordinates()
            self.owner = owner
        history = self.history
        check()
        selected = history.slice(history.sample_count - 1 if sample is None else sample)
        profile = reduce_profile(selected.values)
        lower, upper = float(np.min(selected.values)), float(np.max(selected.values))
        trial = None
        if preview is not None:
            if preview.session_id != session_id or preview.input_digest != input_digest:
                raise ValueError("FIELD_PREVIEW_SOURCE: preview belongs to another attempt/input")
            trial = field_preview(preview)
            positions = tuple(
                canonical_index(item, "Preview index") for item in trial.indices.elements
            )
            if (
                trial.interpretation != history.series.interpretation
                or preview.semantic_ids != (history.interpretation.field_id,)
                or trial.accepted.time.unit != selected.position.time.unit
                or positions[-1] >= history.support.nodes
            ):
                raise ValueError(
                    "FIELD_PREVIEW_SUPPORT: preview has another field/time interpretation"
                )
            # When a base is in retained coverage it must match the same sample.
            # Newer solver-accepted bases remain explicitly provisional to this view.
            if trial.accepted.sample < history.sample_count:
                retained = history.slice(trial.accepted.sample)
                if (
                    retained.position != trial.accepted
                    or tuple(float(retained.values[i]) for i in positions)
                    != trial.accepted_values.elements
                ):
                    raise ValueError(
                        "FIELD_PREVIEW_BASE: preview differs from its retained accepted base"
                    )
        rgba, times = b"", []
        width = height = 0
        if overview:
            samples = np.unique(
                np.linspace(0, history.sample_count - 1, min(64, history.sample_count), dtype=int)
            )
            columns = np.unique(
                np.linspace(
                    0, history.support.nodes - 1, min(512, history.support.nodes), dtype=int
                )
            )
            values = np.empty((len(samples), len(columns)), dtype=np.float64)
            for row, index in enumerate(samples):
                check()
                retained = history.slice(int(index))
                values[row] = retained.values[columns]
                times.append(retained.position)
            lo, hi = float(np.min(values)), float(np.max(values))
            fraction = (values - lo) / (hi - lo) if hi > lo else np.zeros_like(values)
            pixels = np.empty((*values.shape, 4), dtype=np.uint8)
            pixels[:, :, 0] = fraction * 240
            pixels[:, :, 1] = 70 + fraction * 90
            pixels[:, :, 2] = 230 - fraction * 190
            pixels[:, :, 3] = 255
            height, width = values.shape
            rgba = pixels.tobytes()
        check()
        return FieldPresentation(
            resource,
            history.series.source_digest,
            history.interpretation,
            history.series.interpretation,
            history.support,
            selected.position,
            history.sample_count,
            profile,
            (lower, upper),
            rgba,
            width,
            height,
            tuple(times),
            trial,
        )
