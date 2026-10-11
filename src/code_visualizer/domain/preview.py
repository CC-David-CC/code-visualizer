"""Small replaceable computation presentations; never durable observations."""

from dataclasses import dataclass
from re import fullmatch

from code_visualizer.domain.computation import ComputationParameter
from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.values import MAX_INLINE_BYTES, canonical_value_key


@dataclass(frozen=True, slots=True)
class PreviewEvent:
    session_id: str
    sequence: int
    input_digest: str
    interpretation: ResourceLogicalTypeReference
    semantic_ids: tuple[str, ...]
    values: tuple[ComputationParameter, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, str) or not 1 <= len(self.session_id) <= 256:
            raise ValueError("A preview requires its bounded session identity")
        if type(self.sequence) is not int or not 0 <= self.sequence < 1 << 64:
            raise ValueError("A preview requires a monotonic transport sequence")
        if not isinstance(self.input_digest, str) or not fullmatch(
            r"[0-9a-f]{64}", self.input_digest
        ):
            raise ValueError("A preview requires its exact input digest")
        if not isinstance(self.interpretation, ResourceLogicalTypeReference):
            raise ValueError("A preview requires a registered interpretation")
        if (
            type(self.semantic_ids) is not tuple
            or not 1 <= len(self.semantic_ids) <= 32
            or any(
                not isinstance(item, str) or not 1 <= len(item) <= 1024
                for item in self.semantic_ids
            )
            or len(set(self.semantic_ids)) != len(self.semantic_ids)
        ):
            raise ValueError("A preview requires bounded unique semantic origins")
        if (
            type(self.values) is not tuple
            or not 1 <= len(self.values) <= 32
            or any(
                not isinstance(item, ComputationParameter) or len(item.name) > 128
                for item in self.values
            )
            or len({item.name for item in self.values}) != len(self.values)
        ):
            raise ValueError("A preview requires bounded uniquely named canonical values")
        if (
            sum(len(repr(canonical_value_key(item.value)).encode("utf-8")) for item in self.values)
            > MAX_INLINE_BYTES
        ):
            raise ValueError("Preview values exceed the 64 KiB inline boundary")
