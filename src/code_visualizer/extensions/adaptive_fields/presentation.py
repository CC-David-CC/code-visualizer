"""Bounded immutable preparation for a changing-support history; no Qt or authoring."""

from collections.abc import Callable
from typing import cast

from code_visualizer.domain.preview import PreviewEvent
from code_visualizer.domain.values import ResourceReference
from code_visualizer.extensions.adaptive_fields.history import (
    AdaptiveHistory,
    Resolver,
    mixed_array,
    record,
)
from code_visualizer.extensions.adaptive_fields.preview import (
    CellPreview,
    ReducedCells,
    cell_preview,
    support_digest,
)
from code_visualizer.extensions.adaptive_fields.records import (
    DECISION_COLUMNS,
    DECISIONS_TYPE,
    DecisionLog,
)
from code_visualizer.extensions.fields.records import scalar
from code_visualizer.extensions.foundations.cell_presentation import (
    CellPresentation,
    MeshDecision,
    PresentedCell,
    PresentedComponent,
    PresentedFrame,
    PresentedSupport,
    PresentedTrial,
)
from code_visualizer.extensions.foundations.series_reader import CACHE_BYTES


def presented_trial(value: CellPreview) -> PresentedTrial:
    def frame(item: ReducedCells) -> PresentedFrame:
        length = scalar(value.length, "Length")
        cells = tuple(
            PresentedCell(
                f"{value.region_id}:cell:{cell.base}:{cell.level}:{cell.offset}",
                length * (cell.base + cell.offset / 2**cell.level) / value.base_cells,
                length * (cell.base + (cell.offset + 1) / 2**cell.level) / value.base_cells,
                cell.level,
                float(cast(float, number)),
            )
            for cell, number in zip(item.cells, item.values.elements, strict=True)
        )
        return PresentedFrame(item.tick, item.step, item.epoch, cells)

    return PresentedTrial(frame(value.base), frame(value.candidate))


class CellPresentationReader:
    def __init__(self, *, cache_bytes: int = CACHE_BYTES):
        if type(cache_bytes) is not int or not 0 <= cache_bytes <= CACHE_BYTES:
            raise ValueError("Cell presentation cache exceeds 64 MiB")
        self.limit = cache_bytes
        self.history: AdaptiveHistory | None = None
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
        def check() -> None:
            if cancelled():
                raise InterruptedError("Cell presentation superseded")

        check()
        previous = self.history
        if previous is None or self._context != context or previous.root != root:
            current = AdaptiveHistory(root, resolve, cache_bytes=self.limit)
            try:
                if previous is not None and self._context == context:
                    if current.sample_count >= previous.sample_count:
                        current.extends(previous)
                    else:
                        previous.extends(current)
                check()
            except BaseException:
                current.close()
                raise
            self.close()
            self.history, self._context = current, context
        history = self.history
        assert history is not None
        selected = history.slice(history.sample_count - 1 if sample is None else sample)
        support = history.supports[selected.epoch]
        components = history.interpretations[selected.epoch].components
        component_id = components[0].id if component_id is None else component_id
        ids = tuple(item.id for item in components)
        if component_id not in ids:
            raise ValueError("Select a component belonging to this exact history")
        column = ids.index(component_id)
        faces = selected.mesh.faces
        cells = tuple(
            PresentedCell(
                identity,
                float(faces[i]),
                float(faces[i + 1]),
                selected.mesh.cells[i].level,
                float(selected.values[i, column]),
            )
            for i, identity in enumerate(selected.mesh.cell_ids)
        )
        decisions: tuple[MeshDecision, ...] = ()
        if history.series.decisions is not None:
            log = record(history.resolve, history.series.decisions, DecisionLog, DECISIONS_TYPE)
            rows = mixed_array(history.resolve, log.values, (log.rows, len(DECISION_COLUMNS)))
            decisions = tuple(
                MeshDecision(*(int(row[i]) for i in (0, 1, 2, 3, 8, 9)))
                for row in rows
                if row[8] or row[9]
            )
        check()
        trial, retained = None, False
        if preview is not None:
            if preview.session_id != session_id or preview.input_digest != input_digest:
                raise ValueError("CELL_PREVIEW_SOURCE: preview belongs to another attempt or input")
            value = cell_preview(preview)
            last = history.slice(history.sample_count - 1)
            if (
                value.region_id,
                value.frame_id,
                value.axis_id,
                value.base_cells,
                value.length,
                value.quantum,
                value.component_id,
                value.unit_scale.unit,
            ) != (
                support.region_id,
                support.frame_id,
                support.axis_id,
                support.base_cells,
                support.length,
                history.series.quantum,
                component_id,
                components[column].unit,
            ):
                raise ValueError(
                    "CELL_PREVIEW_MEANING: preview has a different physical interpretation"
                )
            for frame in (value.base, value.candidate):
                if frame.epoch < len(history.meshes):
                    mesh = history.meshes[frame.epoch]
                    if frame.support_digest != support_digest(mesh) or not set(frame.cells) <= set(
                        mesh.cells
                    ):
                        raise ValueError(
                            "CELL_PREVIEW_SUPPORT: addresses do not belong to their epoch"
                        )
                    epoch = history.series.epochs[frame.epoch]
                    if frame.tick < epoch.tick or frame.step < epoch.step:
                        raise ValueError("CELL_PREVIEW_TIME: position precedes its support epoch")
                    if frame.epoch + 1 < len(history.meshes):
                        following = history.series.epochs[frame.epoch + 1]
                        if frame.tick >= following.tick or frame.step >= following.step:
                            raise ValueError(
                                "CELL_PREVIEW_TIME: position follows the end of its support epoch"
                            )
            if value.candidate.tick > last.tick:
                trial = value
                for chunk in history.series.chunks:
                    if chunk.first_tick <= value.base.tick <= chunk.last_tick:
                        for sample_id in range(chunk.first_sample, chunk.last_sample + 1):
                            check()
                            base = history.slice(sample_id)
                            if base.tick == value.base.tick:
                                if (base.position.step, base.epoch) != (
                                    value.base.step,
                                    value.base.epoch,
                                ):
                                    raise ValueError(
                                        "CELL_PREVIEW_TIME: retained base has a different position"
                                    )
                                lookup = {
                                    cell: float(number)
                                    for cell, number in zip(
                                        base.mesh.cells, base.values[:, column], strict=True
                                    )
                                }
                                retained = all(
                                    lookup.get(cell) == number
                                    for cell, number in zip(
                                        value.base.cells, value.base.values.elements, strict=True
                                    )
                                )
                                if not retained:
                                    raise ValueError(
                                        "CELL_PREVIEW_BASE: inconsistent retained base values"
                                    )
        return CellPresentation(
            root,
            history.series.source_digest,
            history.sample_count,
            selected.position,
            selected.tick,
            selected.epoch,
            PresentedSupport(
                support.region_id, support.frame_id, support.length, support.partition_kind
            ),
            tuple(
                PresentedComponent(c.id, c.field_id, c.unit, c.quantity_kind) for c in components
            ),
            component_id,
            cells,
            decisions,
            presented_trial(trial) if trial is not None else None,
            retained,
        )
