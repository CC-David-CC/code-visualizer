"""Independently reopen channel resources without a running producer or solver."""

from collections.abc import Callable

from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.values import ResourceReference
from code_visualizer.execution.backends import ResolvedResource
from code_visualizer.extensions.channels.codec import CODEC
from code_visualizer.extensions.channels.records import (
    INTERPRETATION_TYPE,
    SERIES_TYPE,
    ChannelChunk,
    ChannelInterpretation,
    ChannelSeries,
)
from code_visualizer.extensions.fields.records import METADATA_LIMIT
from code_visualizer.extensions.foundations.series_reader import CACHE_BYTES, NumericHistory


class ChannelHistory(NumericHistory[ChannelChunk]):
    def __init__(
        self,
        root: ResourceReference,
        resolve: Callable[[ResourceReference], ResolvedResource],
        *,
        cache_bytes: int = CACHE_BYTES,
    ):
        self.resolve = resolve
        self.series = self.record(root, ChannelSeries, SERIES_TYPE)
        self.interpretation = self.record(
            self.series.interpretation, ChannelInterpretation, INTERPRETATION_TYPE
        )
        super().__init__(
            root,
            resolve,
            self.series,
            lambda ref: self.record(ref, ChannelSeries, SERIES_TYPE),
            len(self.interpretation.channels),
            self.interpretation.time_unit,
            cache_bytes=cache_bytes,
        )

    def record[T](
        self,
        reference: ResourceReference,
        kind: type[T],
        logical_type: ResourceLogicalTypeReference,
    ) -> T:
        resource = self.resolve(reference)
        if (
            resource.descriptor.logical_type != logical_type
            or resource.descriptor.media_type != "application/json"
            or resource.descriptor.byte_size > METADATA_LIMIT
        ):
            raise ValueError("Resource does not match its exact channel contract")
        with resource.open() as stream:
            return CODEC.decode(stream.read(METADATA_LIMIT + 1), kind)
