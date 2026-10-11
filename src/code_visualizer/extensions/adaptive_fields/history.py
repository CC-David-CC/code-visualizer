"""Bounded support-aware reading; an array index never substitutes for cell identity."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.values import QuantityValue, ResourceReference
from code_visualizer.execution.backends import ResolvedResource
from code_visualizer.extensions.adaptive_fields.codec import CellRecord, decode_record
from code_visualizer.extensions.adaptive_fields.mesh import Cell, Mesh, transfer
from code_visualizer.extensions.adaptive_fields.records import (
    DECISION_COLUMNS,
    DECISIONS_TYPE,
    HISTORY_TYPE,
    INTERPRETATION_TYPE,
    SUPPORT_TYPE,
    TRANSFER_TYPE,
    CellChunk,
    CellHistory,
    CellInterpretation,
    CellSupport,
    CellTransfer,
    DecisionLog,
)
from code_visualizer.extensions.adaptive_fields.units import quantity
from code_visualizer.extensions.fields.arrays import read_array
from code_visualizer.extensions.fields.records import METADATA_LIMIT, TemporalPosition, scalar
from code_visualizer.extensions.foundations.series_reader import CACHE_BYTES

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

type Resolver = Callable[[ResourceReference], ResolvedResource]


def record[T: CellRecord](
    resolve: Resolver,
    reference: ResourceReference,
    kind: type[T],
    logical: ResourceLogicalTypeReference,
) -> T:
    resource = resolve(reference)
    descriptor = resource.descriptor
    if (
        descriptor.reference != reference
        or descriptor.logical_type != logical
        or descriptor.media_type != "application/json"
        or descriptor.byte_size > METADATA_LIMIT
    ):
        raise ValueError("Resource does not match its bounded cell interpretation contract")
    with resource.open() as stream:
        return decode_record(stream.read(METADATA_LIMIT + 1), kind)


def mixed_array(
    resolve: Resolver, reference: ResourceReference, shape: tuple[int, ...]
) -> NDArray[np.float64]:
    resource = resolve(reference)
    if (
        resource.descriptor.reference != reference
        or resource.descriptor.tensor is None
        or resource.descriptor.tensor.unit is not None
    ):
        raise ValueError("Mixed identity/time/component arrays cannot declare one array unit")
    return read_array(resource, shape)


def support_mesh(resolve: Resolver, support: CellSupport) -> Mesh:
    import numpy as np

    if (
        support.length.unit.dimension != quantity(1, "meter").unit.dimension
        or support.area.unit.dimension != quantity(1, "square_meter").unit.dimension
    ):
        raise ValueError("Cell support requires declared length and area dimensions")
    lineage = mixed_array(resolve, support.lineage, (support.cells, 3))
    if (
        np.any(lineage < 0)
        or np.any(lineage >= 1 << 53)
        or not np.equal(lineage, np.floor(lineage)).all()
    ):
        raise ValueError("Cell lineage must contain exact nonnegative integer addresses")
    return Mesh(
        support.region_id,
        support.base_cells,
        scalar(support.length, "Length"),
        tuple(Cell(*(int(value) for value in row)) for row in lineage),
    )


@dataclass(frozen=True, slots=True)
class CellSlice:
    history: ResourceReference
    source_digest: str
    epoch: int
    interpretation: ResourceReference
    position: TemporalPosition
    tick: int
    mesh: Mesh
    values: NDArray[np.float64]


class AdaptiveHistory:
    def __init__(
        self, root: ResourceReference, resolve: Resolver, *, cache_bytes: int = CACHE_BYTES
    ):
        if type(cache_bytes) is not int or not 0 <= cache_bytes <= CACHE_BYTES:
            raise ValueError("History cache exceeds 64 MiB")
        seen: set[ResourceReference] = set()
        metadata_bytes = 0
        source_resolver = resolve

        def guarded(reference: ResourceReference) -> ResolvedResource:
            nonlocal metadata_bytes
            resource = source_resolver(reference)
            if reference not in seen:
                seen.add(reference)
                if resource.descriptor.media_type == "application/json":
                    metadata_bytes += resource.descriptor.byte_size
                if len(seen) > 1024 or metadata_bytes > 2 * 1024 * 1024:
                    raise ValueError("Cell history exceeds its resource/metadata closure bound")
            return resource

        self.root, self.resolve, self.limit = root, guarded, cache_bytes
        resolve = guarded
        self.series = record(resolve, root, CellHistory, HISTORY_TYPE)
        if self.series.quantum.unit.dimension != quantity(1, "second").unit.dimension:
            raise ValueError("History requires a physical time dimension")
        self.interpretations = tuple(
            record(resolve, epoch.interpretation, CellInterpretation, INTERPRETATION_TYPE)
            for epoch in self.series.epochs
        )
        self.supports = tuple(
            record(resolve, interpretation.support, CellSupport, SUPPORT_TYPE)
            for interpretation in self.interpretations
        )
        self.meshes = tuple(support_mesh(resolve, support) for support in self.supports)
        first, first_support = self.interpretations[0], self.supports[0]
        for interpretation, support in zip(self.interpretations, self.supports, strict=True):
            if (
                interpretation.owner_id != self.series.owner_id
                or interpretation.components != first.components
                or (
                    support.region_id,
                    support.space_id,
                    support.frame_id,
                    support.axis_id,
                    support.length,
                    support.area,
                    support.base_cells,
                    support.partition_kind,
                )
                != (
                    first_support.region_id,
                    first_support.space_id,
                    first_support.frame_id,
                    first_support.axis_id,
                    first_support.length,
                    first_support.area,
                    first_support.base_cells,
                    first_support.partition_kind,
                )
            ):
                raise ValueError("History epochs cannot change authored physical meaning")
        for ordinal, epoch in enumerate(self.series.epochs[1:], start=1):
            assert epoch.transfer is not None
            item = record(resolve, epoch.transfer, CellTransfer, TRANSFER_TYPE)
            if (
                (item.tick, item.step) != (epoch.tick, epoch.step)
                or item.quantum != self.series.quantum
                or item.source != self.series.epochs[ordinal - 1].interpretation
                or item.target != epoch.interpretation
                or item.region_id != first_support.region_id
            ):
                raise ValueError("Transfer does not belong to its claimed epoch boundary")
            self._verify_transfer(item, ordinal)
        if self.series.decisions is not None:
            log = record(resolve, self.series.decisions, DecisionLog, DECISIONS_TYPE)
            if log.source_digest != self.series.source_digest or log.quantum != self.series.quantum:
                raise ValueError("Decisions belong to a different frozen source")
            self._verify_decisions(log)
        self.sample_count = self.series.chunks[-1].last_sample + 1
        self._cache: OrderedDict[ResourceReference, NDArray[np.float64]] = OrderedDict()
        self.cache_bytes = self.decoded_chunks = 0

    def _verify_transfer(self, item: CellTransfer, ordinal: int) -> None:
        import numpy as np

        before_mesh, after_mesh = self.meshes[ordinal - 1], self.meshes[ordinal]
        if before_mesh == after_mesh:
            raise ValueError("Transfer requires an actual change of cell support")
        width = len(self.interpretations[ordinal].components)
        before = mixed_array(self.resolve, item.before, (len(before_mesh.cells), width))
        after = mixed_array(self.resolve, item.after, (len(after_mesh.cells), width))
        indicators = mixed_array(self.resolve, item.indicators, (len(before_mesh.cells),))
        if np.any(indicators < 0):
            raise ValueError("Refinement indicators must be nonnegative")
        expected = transfer(before_mesh, after_mesh, before)
        scale = np.maximum(np.tensordot(before_mesh.widths, np.abs(before), axes=(0, 0)), 1e-300)
        residual = (
            np.tensordot(after_mesh.widths, after, axes=(0, 0))
            - np.tensordot(before_mesh.widths, before, axes=(0, 0))
        ) / scale
        if (
            len(item.normalized_residuals) != width
            or not np.allclose(after, expected, rtol=1e-13, atol=0)
            or np.any(np.abs(residual) > 1e-12)
            or not np.allclose(residual, item.normalized_residuals, rtol=0, atol=1e-14)
        ):
            raise ValueError("Transfer bytes do not satisfy their declared conservative mapping")

    def _verify_decisions(self, log: DecisionLog) -> None:
        import numpy as np

        values = mixed_array(self.resolve, log.values, (log.rows, len(DECISION_COLUMNS)))
        discrete = values[:, (0, 1, 2, 3, 6, 7, 8, 9, 10, 11, 12)]
        last = self.series.chunks[-1]
        if (
            np.any(values < 0)
            or np.any(discrete >= 1 << 53)
            or not np.equal(discrete, np.floor(discrete)).all()
            or np.any(values[:, 7] > 1)
            or np.any(values[:, 12] > 1)
            or np.any(values[values[:, 12] == 0, 4] != 0)
            or np.any(values[values[:, 12] == 0, 8:10] != 0)
            or np.any(values[:, 3] < 16)
            or np.any(values[:, 3] > 512)
            or np.any(np.diff(values[:, 0]) < 0)
            or np.any(np.diff(values[:, 1]) < 0)
            or np.any(np.diff(values[:, 11]) < 0)
            or np.any(values[:, 2] >= len(self.series.epochs))
            or values[-1, 0] > last.last_tick
            or values[-1, 1] > last.last_step
        ):
            raise ValueError(
                "Decision log has invalid counters or belongs to a future accepted state"
            )

    def _array(self, chunk: CellChunk) -> NDArray[np.float64]:
        import numpy as np

        cached = self._cache.pop(chunk.values, None)
        if cached is not None:
            self._cache[chunk.values] = cached
            return cached
        width = len(self.meshes[chunk.epoch].cells) * len(
            self.interpretations[chunk.epoch].components
        )
        values = mixed_array(self.resolve, chunk.values, (chunk.rows, width + 2))
        cursors = values[:, :2]
        if (
            np.any(cursors < 0)
            or np.any(cursors >= 1 << 53)
            or not np.equal(cursors, np.floor(cursors)).all()
            or np.any(np.diff(cursors, axis=0) <= 0)
            or tuple(cursors[0]) != (chunk.first_tick, chunk.first_step)
            or tuple(cursors[-1]) != (chunk.last_tick, chunk.last_step)
        ):
            raise ValueError("Chunk bytes disagree with their accepted tick/step coverage")
        self.decoded_chunks += 1
        while self._cache and self.cache_bytes + values.nbytes > self.limit:
            _, retired = self._cache.popitem(last=False)
            self.cache_bytes -= retired.nbytes
        if values.nbytes <= self.limit:
            self._cache[chunk.values] = values
            self.cache_bytes += values.nbytes
        return values

    def iter_chunks(self) -> Iterator[tuple[CellChunk, NDArray[np.float64]]]:
        for chunk in self.series.chunks:
            yield chunk, self._array(chunk)

    def extends(self, previous: AdaptiveHistory) -> None:
        """Verify both sample metadata and decision bytes against an acknowledged root."""
        import numpy as np

        self.series.extends(previous.series)
        if previous.series.decisions is not None:
            if self.series.decisions is None:
                raise ValueError("New history cannot drop acknowledged decisions")
            old = record(previous.resolve, previous.series.decisions, DecisionLog, DECISIONS_TYPE)
            new = record(self.resolve, self.series.decisions, DecisionLog, DECISIONS_TYPE)
            if (
                new.policy_id != old.policy_id
                or new.rows < old.rows
                or not np.array_equal(
                    mixed_array(self.resolve, new.values, (new.rows, len(DECISION_COLUMNS)))[
                        : old.rows
                    ],
                    mixed_array(previous.resolve, old.values, (old.rows, len(DECISION_COLUMNS))),
                )
            ):
                raise ValueError("New history cannot replace acknowledged decisions")

    def slice(self, sample: int) -> CellSlice:
        if type(sample) is not int or not 0 <= sample < self.sample_count:
            raise ValueError("Select an exact retained sample; no clamping or interpolation")
        chunk = next(
            item for item in self.series.chunks if item.first_sample <= sample <= item.last_sample
        )
        row = self._array(chunk)[sample - chunk.first_sample]
        tick, step = int(row[0]), int(row[1])
        time = QuantityValue(
            tick * scalar(self.series.quantum, "Quantum"), self.series.quantum.unit
        )
        mesh, interpretation = self.meshes[chunk.epoch], self.interpretations[chunk.epoch]
        values = row[2:].reshape(len(mesh.cells), len(interpretation.components)).copy()
        values.setflags(write=False)
        return CellSlice(
            self.root,
            self.series.source_digest,
            chunk.epoch,
            self.series.epochs[chunk.epoch].interpretation,
            TemporalPosition(time, step, sample),
            tick,
            mesh,
            values,
        )

    def probe(self, sample: int, epoch: int, cell_id: str, component_id: str) -> QuantityValue:
        result = self.slice(sample)
        if type(epoch) is not int or epoch != result.epoch:
            raise ValueError("Probe epoch does not match its exact sample")
        ids = tuple(component.id for component in self.interpretations[epoch].components)
        if cell_id not in result.mesh.cell_ids or component_id not in ids:
            raise ValueError("Cell/component identity does not exist in this sample epoch")
        i, j = result.mesh.cell_ids.index(cell_id), ids.index(component_id)
        return QuantityValue(
            float(result.values[i, j]), self.interpretations[epoch].components[j].unit
        )

    def close(self) -> None:
        self._cache.clear()
        self.cache_bytes = 0
