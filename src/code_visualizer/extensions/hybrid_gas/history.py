"""Reopen exact nonperiodic gas samples through the shared bounded numeric reader."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.values import ResourceReference
from code_visualizer.execution.backends import ResolvedResource
from code_visualizer.extensions.fields.records import TemporalPosition, scalar
from code_visualizer.extensions.foundations.series_reader import CACHE_BYTES, NumericHistory
from code_visualizer.extensions.hybrid_gas.records import (
    CODEC,
    HISTORY_TYPE,
    INTERPRETATION_TYPE,
    GasChunk,
    GasInterpretation,
    GasSeries,
)
from code_visualizer.extensions.hybrid_gas.units import quantity

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


def record[T](
    resolve: Callable[[ResourceReference], ResolvedResource],
    reference: ResourceReference,
    kind: type[T],
    logical_type: ResourceLogicalTypeReference,
) -> T:
    resource = resolve(reference)
    if (
        resource.descriptor.logical_type != logical_type
        or resource.descriptor.media_type != "application/json"
        or resource.descriptor.byte_size > 65536
    ):
        raise ValueError("Gas resource does not match its exact bounded interpretation")
    with resource.open() as stream:
        return CODEC.decode(stream.read(65537), kind)


@dataclass(frozen=True, slots=True)
class GasSlice:
    source_digest: str
    interpretation: ResourceReference
    position: TemporalPosition
    particle: bool
    conserved: NDArray[np.float64]


class GasHistory(NumericHistory[GasChunk]):
    def __init__(
        self,
        root: ResourceReference,
        resolve: Callable[[ResourceReference], ResolvedResource],
        *,
        cache_bytes: int = CACHE_BYTES,
    ):
        self.series = record(resolve, root, GasSeries, HISTORY_TYPE)
        self.interpretation = record(
            resolve, self.series.interpretation, GasInterpretation, INTERPRETATION_TYPE
        )
        super().__init__(
            root,
            resolve,
            self.series,
            lambda r: record(resolve, r, GasSeries, HISTORY_TYPE),
            self.interpretation.width,
            quantity(1, "second").unit,
            cache_bytes=cache_bytes,
        )

    def gas_slice(self, sample: int) -> GasSlice:
        import numpy as np

        saved = self.slice(sample)
        if saved.values[0] not in (0, 1) or scalar(
            saved.position.time, "Time"
        ) != saved.position.step * scalar(self.interpretation.quantum, "Quantum"):
            raise ValueError("Gas sample has invalid ownership or physical tick")
        q = saved.values[1:].reshape(self.interpretation.cells, 5)
        if np.any(q[:, 0] <= 0) or np.any(
            q[:, 4] - 0.5 * np.sum(q[:, 1:4] ** 2, axis=1) / q[:, 0] <= 0
        ):
            raise ValueError("Retained gas sample has nonpositive density/internal energy")
        return GasSlice(
            saved.source_digest, saved.interpretation, saved.position, bool(saved.values[0]), q
        )
