"""The channel contract cannot decode spatial fields or diffusion checkpoints."""

from code_visualizer.execution.resource_interpretation import ResourceDependency
from code_visualizer.extensions.channels.records import (
    Channel,
    ChannelChunk,
    ChannelInterpretation,
    ChannelSeries,
)
from code_visualizer.extensions.fields.records import TemporalPosition
from code_visualizer.extensions.foundations.record_codec import RecordCodec

CODEC = RecordCodec((Channel, ChannelChunk, ChannelInterpretation, ChannelSeries, TemporalPosition))


def interpretation_dependencies(payload: bytes) -> tuple[ResourceDependency, ...]:
    return CODEC.decode(payload, ChannelInterpretation).dependencies()


def series_dependencies(payload: bytes) -> tuple[ResourceDependency, ...]:
    return CODEC.decode(payload, ChannelSeries).dependencies()
