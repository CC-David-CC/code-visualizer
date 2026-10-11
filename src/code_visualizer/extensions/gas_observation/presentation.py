"""Prepare wall-bounded gas resources for the shared cell view; no native execution."""

from collections.abc import Callable
from typing import cast

from code_visualizer.domain.preview import PreviewEvent
from code_visualizer.domain.values import ResourceReference, TensorValue
from code_visualizer.extensions.fields.records import index, scalar
from code_visualizer.extensions.foundations.cell_presentation import (
    CellPresentation,
    PresentedCell,
    PresentedComponent,
    PresentedFrame,
    PresentedSupport,
    PresentedTrial,
    Resolver,
)
from code_visualizer.extensions.foundations.series_reader import CACHE_BYTES
from code_visualizer.extensions.foundations.unit_algebra import QuantityKind
from code_visualizer.extensions.gas_observation.reader import cell_ids
from code_visualizer.extensions.hybrid_gas.history import GasHistory
from code_visualizer.extensions.hybrid_gas.preview import validate_preview


def _trial(
    history: GasHistory, preview: PreviewEvent, column: int, session_id: str, input_digest: str
) -> tuple[PresentedTrial | None, bool]:
    if preview.session_id != session_id or preview.input_digest != input_digest:
        raise ValueError("GAS_PREVIEW_SOURCE: preview belongs to another attempt or input")
    validate_preview(preview)
    values, support = {p.name: p.value for p in preview.values}, history.interpretation
    expected = {
        "source": history.series.source_digest,
        "region": support.region_id,
        "slab": support.slab_id,
        "policy": support.policy_id,
        "frame": support.frame_id,
        "axis": support.axis_id,
        "cells": support.cells,
        "height": support.height,
        "quantum": support.quantum,
    }
    if any(values[name] != value for name, value in expected.items()):
        raise ValueError("GAS_PREVIEW_MEANING: source, geometry or frame differs")
    indices = tuple(index(i, "Cell") for i in cast(TensorValue, values["indices"]).elements)
    ids, width = cell_ids(history), scalar(support.height, "Height") / support.cells

    def frame(name: str) -> PresentedFrame:
        tick = index(values[name + "_tick"], "Tick")
        numbers = cast(TensorValue, values[name + "_values"]).elements
        return PresentedFrame(
            tick,
            tick,
            0,
            tuple(
                PresentedCell(
                    ids[i],
                    i * width,
                    (i + 1) * width,
                    0,
                    float(cast(float, numbers[j * 5 + column])),
                )
                for j, i in enumerate(indices)
            ),
        )

    base, candidate = frame("base"), frame("candidate")
    last = history.gas_slice(history.sample_count - 1)
    if candidate.tick <= last.position.step:
        return None, False
    retained = False
    if base.tick <= last.position.step:
        for sample in range(history.sample_count):
            saved = history.gas_slice(sample)
            if saved.position.step == base.tick:
                actual = tuple(float(n) for row in saved.conserved[list(indices)] for n in row)
                if (
                    actual != cast(TensorValue, values["base_values"]).elements
                    or saved.particle != values["base_particle"]
                ):
                    raise ValueError("GAS_PREVIEW_BASE: retained base values or ownership differ")
                retained = True
                break
    return PresentedTrial(base, candidate), retained


class GasPresentationReader:
    def __init__(self, *, cache_bytes: int = CACHE_BYTES):
        if type(cache_bytes) is not int or not 0 <= cache_bytes <= CACHE_BYTES:
            raise ValueError("Cell presentation cache exceeds 64 MiB")
        self.limit = cache_bytes
        self.history: GasHistory | None = None
        self._context: object = None

    @property
    def cache_bytes(self) -> int:
        return self.history.cache_bytes if self.history is not None else 0

    def close(self) -> None:
        if self.history is not None:
            self.history.close()
        self.history, self._context = None, None

    def prepare(
        self,
        root: ResourceReference,
        resolve: Resolver,
        context: object,
        sample: int | None = None,
        component_id: str | None = None,
        *,
        preview: PreviewEvent | None = None,
        session_id: str = "",
        input_digest: str = "",
        cancelled: Callable[[], bool] = lambda: False,
    ) -> CellPresentation:
        import numpy as np

        def check() -> None:
            if cancelled():
                raise InterruptedError("Cell presentation superseded")

        check()
        previous = self.history
        if previous is None or previous.root != root or self._context != context:
            current = GasHistory(root, resolve, cache_bytes=0)
            try:
                if previous is not None and self._context == context:
                    if (previous.series.source_digest, previous.series.interpretation) != (
                        current.series.source_digest,
                        current.series.interpretation,
                    ):
                        raise ValueError(
                            "Gas history changed its source or physical interpretation"
                        )
                    # Different publication boundaries may contain the same exact samples.
                    # The bounded overlap is checked without retaining a second numeric cache.
                    for i in range(min(previous.sample_count, current.sample_count)):
                        check()
                        a, b = previous.slice(i), current.slice(i)
                        if a.position != b.position or not np.array_equal(a.values, b.values):
                            raise ValueError("Gas history rewrote a retained sample")
                check()
            except BaseException:
                current.close()
                raise
            self.close()
            current.limit = self.limit
            self.history, self._context = current, context
        history = self.history
        assert history is not None
        selected = history.gas_slice(history.sample_count - 1 if sample is None else sample)
        support = history.interpretation
        component_id = support.field_ids[0] if component_id is None else component_id
        if component_id not in support.field_ids:
            raise ValueError("Select a component of this exact gas history")
        column, width = (
            support.field_ids.index(component_id),
            scalar(support.height, "Height") / support.cells,
        )
        cells = tuple(
            PresentedCell(
                identity, i * width, (i + 1) * width, 0, float(selected.conserved[i, column])
            )
            for i, identity in enumerate(cell_ids(history))
        )
        trial, retained = (
            (None, False)
            if preview is None
            else _trial(history, preview, column, session_id, input_digest)
        )
        check()
        return CellPresentation(
            root,
            history.series.source_digest,
            history.sample_count,
            selected.position,
            selected.position.step,
            0,
            PresentedSupport(
                support.region_id, support.frame_id, support.height, support.association
            ),
            tuple(
                PresentedComponent(field, field, unit, QuantityKind.LINEAR)
                for field, unit in zip(support.field_ids, support.units, strict=True)
            ),
            component_id,
            cells,
            (),
            trial,
            retained,
            (
                "Particle participant active"
                if selected.particle
                else "Continuum participant active",
                "Stored density, three momenta and total energy are cell averages.",
            ),
        )
