"""A reduced, coherent accepted/trial pair for the scalar field interpretation."""

from dataclasses import dataclass

from code_visualizer.domain.computation import ComputationParameter
from code_visualizer.domain.preview import PreviewEvent
from code_visualizer.domain.values import QuantityValue, ResourceReference, TensorDType, TensorValue
from code_visualizer.extensions.fields.records import (
    PREVIEW_TYPE,
    TemporalPosition,
    index,
    ref,
    scalar,
)


@dataclass(frozen=True, slots=True)
class FieldPreview:
    interpretation: ResourceReference
    accepted: TemporalPosition
    candidate: TemporalPosition
    indices: TensorValue
    accepted_values: TensorValue
    trial_values: TensorValue

    def __post_init__(self) -> None:
        ref(self.interpretation)
        if not isinstance(self.accepted, TemporalPosition) or not isinstance(
            self.candidate, TemporalPosition
        ):
            raise ValueError("Field preview positions must be explicit")
        if self.candidate.step != self.accepted.step + 1 or (
            self.candidate.time.unit != self.accepted.time.unit
            or scalar(self.candidate.time, "Candidate time")
            <= scalar(self.accepted.time, "Accepted time")
        ):
            raise ValueError("A trial must identify the next step from its accepted base")
        if not isinstance(self.indices, TensorValue) or self.indices.dtype != TensorDType.INT64:
            raise ValueError("Preview sample indices must be an integer tensor")
        if len(self.indices.shape) != 1 or not 1 <= self.indices.shape[0] <= 256:
            raise ValueError("Reduced field previews contain at most 256 samples")
        positions = tuple(
            index(position, "Preview node index") for position in self.indices.elements
        )
        if tuple(sorted(set(positions))) != positions:
            raise ValueError("Preview node indices must be unique and ordered")
        for values in (self.accepted_values, self.trial_values):
            if (
                not isinstance(values, TensorValue)
                or values.dtype != TensorDType.FLOAT64
                or values.shape != self.indices.shape
            ):
                raise ValueError("Accepted and trial previews must share exact scalar support")

    def event(
        self, session_id: str, sequence: int, input_digest: str, field_id: str
    ) -> PreviewEvent:
        return PreviewEvent(
            session_id,
            sequence,
            input_digest,
            PREVIEW_TYPE,
            (field_id,),
            tuple(
                ComputationParameter(name, value)
                for name, value in (
                    ("interpretation", self.interpretation),
                    ("accepted_time", self.accepted.time),
                    ("accepted_step", self.accepted.step),
                    ("accepted_sample", self.accepted.sample),
                    ("candidate_time", self.candidate.time),
                    ("candidate_step", self.candidate.step),
                    ("candidate_sample", self.candidate.sample),
                    ("indices", self.indices),
                    ("accepted_values", self.accepted_values),
                    ("trial_values", self.trial_values),
                )
            ),
        )


def field_preview(event: PreviewEvent) -> FieldPreview:
    expected = {
        "interpretation",
        "accepted_time",
        "accepted_step",
        "accepted_sample",
        "candidate_time",
        "candidate_step",
        "candidate_sample",
        "indices",
        "accepted_values",
        "trial_values",
    }
    data = {item.name: item.value for item in event.values}
    if (
        event.interpretation != PREVIEW_TYPE
        or set(data) != expected
        or len(event.semantic_ids) != 1
    ):
        raise ValueError("Unknown scalar preview contract or missing/extra fields")

    def typed[T](name: str, kind: type[T]) -> T:
        value = data[name]
        if not isinstance(value, kind):
            raise ValueError(f"Wrong value type for preview {name}")
        return value

    return FieldPreview(
        typed("interpretation", ResourceReference),
        TemporalPosition(
            typed("accepted_time", QuantityValue),
            index(data["accepted_step"], "step"),
            index(data["accepted_sample"], "sample"),
        ),
        TemporalPosition(
            typed("candidate_time", QuantityValue),
            index(data["candidate_step"], "step"),
            index(data["candidate_sample"], "sample"),
        ),
        typed("indices", TensorValue),
        typed("accepted_values", TensorValue),
        typed("trial_values", TensorValue),
    )


def validate_preview(event: PreviewEvent) -> None:
    field_preview(event)
