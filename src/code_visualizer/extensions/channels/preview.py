"""Bounded trial channels with explicit window identity, independent of retained samples."""

from dataclasses import dataclass

from code_visualizer.domain.computation import ComputationParameter
from code_visualizer.domain.preview import PreviewEvent
from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.values import QuantityValue, ResourceReference, TensorDType, TensorValue
from code_visualizer.extensions.fields.records import digest, index, ref, scalar

PREVIEW_TYPE = ResourceLogicalTypeReference("foundation.channels.trial", "1")


@dataclass(frozen=True, slots=True)
class ChannelPreview:
    interpretation: ResourceReference
    definition_digest: str
    base_step: int
    base_time: QuantityValue
    candidate_step: int
    candidate_time: QuantityValue
    iteration: int
    indices: TensorValue
    base_values: TensorValue
    trial_values: TensorValue

    def __post_init__(self) -> None:
        ref(self.interpretation)
        digest(self.definition_digest)
        index(self.base_step, "Base step")
        index(self.candidate_step, "Candidate step")
        index(self.iteration, "Iteration")
        if (
            not 1 <= self.iteration <= 1_000_000
            or self.candidate_step != self.base_step + 1
            or not isinstance(self.base_time, QuantityValue)
            or not isinstance(self.candidate_time, QuantityValue)
            or self.base_time.unit != self.candidate_time.unit
            or scalar(self.base_time, "Base time") >= scalar(self.candidate_time, "Candidate time")
        ):
            raise ValueError("A trial requires one explicit next window and iteration")
        if (
            not isinstance(self.indices, TensorValue)
            or self.indices.dtype != TensorDType.INT64
            or len(self.indices.shape) != 1
            or not 1 <= self.indices.shape[0] <= 64
        ):
            raise ValueError("A trial contains at most 64 explicit channel indices")
        positions = tuple(index(i, "Channel index") for i in self.indices.elements)
        if positions != tuple(sorted(set(positions))) or positions[-1] >= 64:
            raise ValueError("Trial channel indices must be distinct, ordered and bounded")
        for values in (self.base_values, self.trial_values):
            if (
                not isinstance(values, TensorValue)
                or values.dtype != TensorDType.FLOAT64
                or values.shape != self.indices.shape
            ):
                raise ValueError("Base and trial must share the exact finite channel selection")

    def event(self, session: str, sequence: int, input_digest: str, owner: str) -> PreviewEvent:
        return PreviewEvent(
            session,
            sequence,
            input_digest,
            PREVIEW_TYPE,
            (owner,),
            tuple(
                ComputationParameter(name, getattr(self, name))
                for name in self.__dataclass_fields__
            ),
        )


def channel_preview(event: PreviewEvent) -> ChannelPreview:
    data = {item.name: item.value for item in event.values}
    if (
        event.interpretation != PREVIEW_TYPE
        or len(event.semantic_ids) != 1
        or set(data) != set(ChannelPreview.__dataclass_fields__)
    ):
        raise ValueError("Unknown channel trial contract or missing/extra fields")

    def typed[T](name: str, kind: type[T]) -> T:
        value = data[name]
        if not isinstance(value, kind):
            raise ValueError(f"Invalid trial value {name}")
        return value

    return ChannelPreview(
        typed("interpretation", ResourceReference),
        typed("definition_digest", str),
        typed("base_step", int),
        typed("base_time", QuantityValue),
        typed("candidate_step", int),
        typed("candidate_time", QuantityValue),
        typed("iteration", int),
        typed("indices", TensorValue),
        typed("base_values", TensorValue),
        typed("trial_values", TensorValue),
    )


def validate_preview(event: PreviewEvent) -> None:
    channel_preview(event)
