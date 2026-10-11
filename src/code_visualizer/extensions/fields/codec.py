"""The exact closed version-1 field contract, using the shared inert record codec."""

from code_visualizer.execution.resource_interpretation import ResourceDependency
from code_visualizer.extensions.fields.records import (
    METADATA_LIMIT,
    DiffusionCheckpoint,
    FieldInterpretation,
    FieldSeries,
    SampleChunk,
    TemporalPosition,
    UniformSupport,
)
from code_visualizer.extensions.foundations.record_codec import RecordCodec

type FieldRecord = (
    UniformSupport
    | FieldInterpretation
    | TemporalPosition
    | SampleChunk
    | FieldSeries
    | DiffusionCheckpoint
)

_CODEC = RecordCodec(
    (
        UniformSupport,
        FieldInterpretation,
        TemporalPosition,
        SampleChunk,
        FieldSeries,
        DiffusionCheckpoint,
    ),
    METADATA_LIMIT,
)


def encode_record(value: FieldRecord) -> bytes:
    return _CODEC.encode(value)


def decode_record[T: FieldRecord](payload: bytes, expected: type[T]) -> T:
    return _CODEC.decode(payload, expected)


def support_dependencies(payload: bytes) -> tuple[ResourceDependency, ...]:
    return decode_record(payload, UniformSupport).dependencies()


def interpretation_dependencies(payload: bytes) -> tuple[ResourceDependency, ...]:
    return decode_record(payload, FieldInterpretation).dependencies()


def series_dependencies(payload: bytes) -> tuple[ResourceDependency, ...]:
    return decode_record(payload, FieldSeries).dependencies()


def checkpoint_dependencies(payload: bytes) -> tuple[ResourceDependency, ...]:
    return decode_record(payload, DiffusionCheckpoint).dependencies()
