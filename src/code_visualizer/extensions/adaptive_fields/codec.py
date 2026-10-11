"""Deterministic inert v1 metadata, separately closed from P5/P6 interpretations."""

from code_visualizer.execution.resource_interpretation import ResourceDependency
from code_visualizer.extensions.adaptive_fields.records import (
    CellChunk,
    CellComponent,
    CellEpoch,
    CellHistory,
    CellInterpretation,
    CellSupport,
    CellTransfer,
    DecisionLog,
)
from code_visualizer.extensions.foundations.record_codec import RecordCodec

type CellRecord = (
    CellSupport
    | CellComponent
    | CellInterpretation
    | CellEpoch
    | CellChunk
    | CellHistory
    | CellTransfer
    | DecisionLog
)
_CODEC = RecordCodec(
    (
        CellSupport,
        CellComponent,
        CellInterpretation,
        CellEpoch,
        CellChunk,
        CellHistory,
        CellTransfer,
        DecisionLog,
    )
)


def encode_record(value: CellRecord) -> bytes:
    return _CODEC.encode(value)


def decode_record[T: CellRecord](payload: bytes, expected: type[T]) -> T:
    return _CODEC.decode(payload, expected)


def support_dependencies(payload: bytes) -> tuple[ResourceDependency, ...]:
    return decode_record(payload, CellSupport).dependencies()


def interpretation_dependencies(payload: bytes) -> tuple[ResourceDependency, ...]:
    return decode_record(payload, CellInterpretation).dependencies()


def history_dependencies(payload: bytes) -> tuple[ResourceDependency, ...]:
    return decode_record(payload, CellHistory).dependencies()


def transfer_dependencies(payload: bytes) -> tuple[ResourceDependency, ...]:
    return decode_record(payload, CellTransfer).dependencies()


def decisions_dependencies(payload: bytes) -> tuple[ResourceDependency, ...]:
    return decode_record(payload, DecisionLog).dependencies()
