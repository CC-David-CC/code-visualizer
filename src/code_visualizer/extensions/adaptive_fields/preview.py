"""Reduced cell values with independent support identities; never retained evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from itertools import pairwise
from typing import TYPE_CHECKING

from code_visualizer.domain.computation import ComputationParameter
from code_visualizer.domain.preview import PreviewEvent
from code_visualizer.domain.values import CanonicalValue, QuantityValue, TensorDType, TensorValue
from code_visualizer.extensions.adaptive_fields.mesh import Cell, Mesh
from code_visualizer.extensions.adaptive_fields.records import PREVIEW_TYPE
from code_visualizer.extensions.adaptive_fields.units import quantity
from code_visualizer.extensions.fields.records import digest, identity, index, scalar

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


def support_digest(mesh: Mesh) -> str:
    """The complete support identity is independent of preview sampling density."""
    key = (
        mesh.region_id,
        mesh.base_cells,
        float(mesh.length),
        tuple((cell.base, cell.level, cell.offset) for cell in mesh.cells),
    )
    return sha256(
        json.dumps(key, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ReducedCells:
    support_digest: str
    epoch: int
    tick: int
    step: int
    lineage: TensorValue
    values: TensorValue

    def __post_init__(self) -> None:
        digest(self.support_digest)
        for value in (self.epoch, self.tick, self.step):
            index(value, "Preview position")
        if (
            not isinstance(self.lineage, TensorValue)
            or self.lineage.dtype is not TensorDType.INT64
            or len(self.lineage.shape) != 2
            or self.lineage.shape[1] != 3
            or not 1 <= self.lineage.shape[0] <= 256
        ):
            raise ValueError("A reduced support requires 1..256 exact cell addresses")
        if (
            not isinstance(self.values, TensorValue)
            or self.values.dtype is not TensorDType.FLOAT64
            or self.values.shape != (self.lineage.shape[0],)
        ):
            raise ValueError("Preview values must match their own reduced support")
        cells = self.cells
        if any(left.stop > right.start for left, right in pairwise(cells)):
            raise ValueError("Reduced cells must be unique, ordered and nonoverlapping")

    @property
    def cells(self) -> tuple[Cell, ...]:
        numbers = self.lineage.elements
        return tuple(
            Cell(*(index(value, "Cell address") for value in numbers[i : i + 3]))
            for i in range(0, len(numbers), 3)
        )

    @classmethod
    def reduce(
        cls,
        mesh: Mesh,
        epoch: int,
        tick: int,
        step: int,
        values: NDArray[np.float64],
        *,
        limit: int = 256,
    ) -> ReducedCells:
        import numpy as np

        if type(limit) is not int or not 1 <= limit <= 256:
            raise ValueError("Preview reduction must be bounded")
        if values.shape != (len(mesh.cells),):
            raise ValueError("Values belong to a different cell partition")
        selected = np.unique(
            np.linspace(0, len(mesh.cells) - 1, min(limit, len(mesh.cells)), dtype=np.int64)
        )
        return cls(
            support_digest(mesh),
            epoch,
            tick,
            step,
            TensorValue(
                TensorDType.INT64,
                (len(selected), 3),
                tuple(
                    value
                    for i in selected
                    for value in (mesh.cells[i].base, mesh.cells[i].level, mesh.cells[i].offset)
                ),
            ),
            TensorValue(
                TensorDType.FLOAT64, (len(selected),), tuple(float(values[i]) for i in selected)
            ),
        )


@dataclass(frozen=True, slots=True)
class CellPreview:
    region_id: str
    frame_id: str
    axis_id: str
    base_cells: int
    length: QuantityValue
    quantum: QuantityValue
    component_id: str
    unit_scale: QuantityValue
    base: ReducedCells
    candidate: ReducedCells

    def __post_init__(self) -> None:
        for value in (self.region_id, self.frame_id, self.axis_id, self.component_id):
            identity(value)
        if type(self.base_cells) is not int or not 16 <= self.base_cells <= 512:
            raise ValueError("Preview base partition is out of bounds")
        if (
            scalar(self.length, "Preview length") <= 0
            or self.length.unit.dimension != quantity(1, "meter").unit.dimension
            or scalar(self.quantum, "Time quantum") <= 0
            or self.quantum.unit.dimension != quantity(1).unit.dimension
            or scalar(self.unit_scale, "Component unit scale") != 1
        ):
            raise ValueError("Preview requires positive physical support/time and a component unit")
        if (
            not isinstance(self.base, ReducedCells)
            or not isinstance(self.candidate, ReducedCells)
            or self.candidate.tick <= self.base.tick
            or self.candidate.step != self.base.step + 1
            or self.candidate.epoch not in (self.base.epoch, self.base.epoch + 1)
        ):
            raise ValueError(
                "A preview must identify one next numerical state from its complete base"
            )
        if any(
            cell.base >= self.base_cells
            for state in (self.base, self.candidate)
            for cell in state.cells
        ):
            raise ValueError("Preview cell lies outside its physical partition")
        if (self.base.epoch == self.candidate.epoch) != (
            self.base.support_digest == self.candidate.support_digest
        ):
            raise ValueError("Changed support requires a new epoch")

    def event(
        self, session_id: str, sequence: int, input_digest: str, semantic_ids: tuple[str, ...]
    ) -> PreviewEvent:
        fields: list[tuple[str, CanonicalValue]] = [
            ("region", self.region_id),
            ("frame", self.frame_id),
            ("axis", self.axis_id),
            ("base_cells", self.base_cells),
            ("length", self.length),
            ("quantum", self.quantum),
            ("component", self.component_id),
            ("unit_scale", self.unit_scale),
            ("status", "numerical_candidate_pending_publication"),
        ]
        for prefix, state in (("base", self.base), ("candidate", self.candidate)):
            fields.extend(
                (prefix + "_" + name, value)
                for name, value in (
                    ("support", state.support_digest),
                    ("epoch", state.epoch),
                    ("tick", state.tick),
                    ("step", state.step),
                    ("lineage", state.lineage),
                    ("values", state.values),
                )
            )
        return PreviewEvent(
            session_id,
            sequence,
            input_digest,
            PREVIEW_TYPE,
            semantic_ids,
            tuple(ComputationParameter(name, value) for name, value in fields),
        )


def cell_preview(event: PreviewEvent) -> CellPreview:
    data = {item.name: item.value for item in event.values}
    expected = {
        "region",
        "frame",
        "axis",
        "base_cells",
        "length",
        "quantum",
        "component",
        "unit_scale",
        "status",
    }
    expected.update(
        prefix + "_" + name
        for prefix in ("base", "candidate")
        for name in ("support", "epoch", "tick", "step", "lineage", "values")
    )
    if (
        event.interpretation != PREVIEW_TYPE
        or set(data) != expected
        or data["status"] != "numerical_candidate_pending_publication"
    ):
        raise ValueError("Unknown cell preview contract or missing/extra fields")

    def typed[T](name: str, kind: type[T]) -> T:
        value = data[name]
        if not isinstance(value, kind):
            raise ValueError(f"Wrong type for preview {name}")
        return value

    def state(prefix: str) -> ReducedCells:
        return ReducedCells(
            typed(prefix + "_support", str),
            index(data[prefix + "_epoch"], "Epoch"),
            index(data[prefix + "_tick"], "Tick"),
            index(data[prefix + "_step"], "Step"),
            typed(prefix + "_lineage", TensorValue),
            typed(prefix + "_values", TensorValue),
        )

    return CellPreview(
        typed("region", str),
        typed("frame", str),
        typed("axis", str),
        index(data["base_cells"], "Base partition"),
        typed("length", QuantityValue),
        typed("quantum", QuantityValue),
        typed("component", str),
        typed("unit_scale", QuantityValue),
        state("base"),
        state("candidate"),
    )


def validate_preview(event: PreviewEvent) -> None:
    cell_preview(event)
