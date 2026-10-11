"""Spatial field admission over the shared bounded numeric history index."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.values import ResourceReference
from code_visualizer.execution.backends import ResolvedResource
from code_visualizer.extensions.fields.arrays import read_array
from code_visualizer.extensions.fields.codec import FieldRecord, decode_record
from code_visualizer.extensions.fields.records import (
    INTERPRETATION_TYPE,
    METADATA_LIMIT,
    SERIES_TYPE,
    SUPPORT_TYPE,
    FieldInterpretation,
    FieldSeries,
    SampleChunk,
    UniformSupport,
    scalar,
)
from code_visualizer.extensions.foundations.series_reader import (
    CACHE_BYTES,
    NumericHistory,
    NumericSlice,
)
from code_visualizer.extensions.foundations.units_si import si_catalog

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class FieldSlice(NumericSlice):
    """A numeric slice whose spatial field interpretation was admitted."""


class FieldHistory(NumericHistory[SampleChunk]):
    def __init__(
        self,
        root: ResourceReference,
        resolve: Callable[[ResourceReference], ResolvedResource],
        *,
        cache_bytes: int = CACHE_BYTES,
    ):
        self.resolve = resolve
        self.series = self.record(root, FieldSeries, SERIES_TYPE)
        self.interpretation = self.record(
            self.series.interpretation, FieldInterpretation, INTERPRETATION_TYPE
        )
        self.support = self.record(self.interpretation.support, UniformSupport, SUPPORT_TYPE)
        if (
            self.support.spacing.unit.dimension
            != si_catalog().unit("foundation.units.si:meter").dimension
        ):
            raise ValueError("Field spatial support must declare a length dimension")
        time_unit = self.series.chunks[0].first.time.unit
        if time_unit.dimension != si_catalog().unit("foundation.units.si:second").dimension:
            raise ValueError("Field physical time must have a time dimension")
        super().__init__(
            root,
            resolve,
            self.series,
            lambda ref: self.record(ref, FieldSeries, SERIES_TYPE),
            self.support.nodes,
            time_unit,
            cache_bytes=cache_bytes,
        )

    def slice(self, sample: int) -> FieldSlice:
        result = super().slice(sample)
        return FieldSlice(
            result.series,
            result.interpretation,
            result.source_digest,
            result.position,
            result.values,
        )

    def record[T: FieldRecord](
        self, reference: ResourceReference, kind: type[T], logical: ResourceLogicalTypeReference
    ) -> T:
        resource = self.resolve(reference)
        if (
            resource.descriptor.logical_type != logical
            or resource.descriptor.media_type != "application/json"
        ):
            raise ValueError("Resource does not match its field interpretation contract")
        if resource.descriptor.byte_size > METADATA_LIMIT:
            raise ValueError("Field metadata exceeds 64 KiB")
        with resource.open() as stream:
            return decode_record(stream.read(METADATA_LIMIT + 1), kind)

    def coordinates(self) -> NDArray[np.float64]:
        import numpy as np

        resource = self.resolve(self.support.coordinates)
        tensor = resource.descriptor.tensor
        if tensor is not None and tensor.unit not in (None, self.support.spacing.unit):
            raise ValueError("Coordinate array unit conflicts with its spatial interpretation")
        values = read_array(resource, (self.support.nodes,))
        expected = scalar(self.support.origin, "Origin") + np.arange(self.support.nodes) * scalar(
            self.support.spacing, "Spacing"
        )
        if not np.array_equal(values, expected):
            raise ValueError("Coordinate resource disagrees with its declared uniform support")
        return values
