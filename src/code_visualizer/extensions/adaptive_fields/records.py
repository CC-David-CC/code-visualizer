"""Closed cell-average interpretations. Meshes and accepted history are resources."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.values import QuantityValue, ResourceReference, UnitReference
from code_visualizer.execution.resource_interpretation import ResourceDependency
from code_visualizer.extensions.fields.records import (
    ARRAY_TYPE,
    digest,
    identity,
    index,
    ref,
    scalar,
)
from code_visualizer.extensions.foundations.unit_algebra import QuantityKind

SUPPORT_TYPE = ResourceLogicalTypeReference("foundation.adaptive_fields.cell_support", "1")
INTERPRETATION_TYPE = ResourceLogicalTypeReference("foundation.adaptive_fields.interpretation", "1")
HISTORY_TYPE = ResourceLogicalTypeReference("foundation.adaptive_fields.history", "1")
TRANSFER_TYPE = ResourceLogicalTypeReference("foundation.adaptive_fields.transfer", "1")
DECISIONS_TYPE = ResourceLogicalTypeReference("foundation.adaptive_fields.decisions", "1")
PREVIEW_TYPE = ResourceLogicalTypeReference("foundation.adaptive_fields.preview", "1")
MAX_CELLS = 512
MAX_COMPONENTS = 8
MAX_EPOCHS = 32
MAX_CHUNKS = 64
MAX_SAMPLES = 256
MAX_DECISIONS = 8192 + 1024


def bounded(value: int, low: int, high: int, name: str) -> None:
    if not low <= index(value, name) <= high:
        raise ValueError(f"{name} must be in {low}..{high}")


@dataclass(frozen=True, slots=True)
class CellSupport:
    region_id: str
    space_id: str
    frame_id: str
    axis_id: str
    axis_name: str
    length: QuantityValue
    area: QuantityValue
    base_cells: int
    cells: int
    lineage: ResourceReference
    partition_kind: str = "periodic_cartesian_dyadic_1d"

    def __post_init__(self) -> None:
        for value in (self.region_id, self.space_id, self.frame_id, self.axis_id, self.axis_name):
            identity(value)
        if min(scalar(self.length, "Length"), scalar(self.area, "Area")) <= 0:
            raise ValueError("Cell support requires positive length and area")
        bounded(self.base_cells, 16, MAX_CELLS, "Base cells")
        bounded(self.cells, self.base_cells, MAX_CELLS, "Cells")
        ref(self.lineage)
        if self.partition_kind != "periodic_cartesian_dyadic_1d":
            raise ValueError("Unsupported cell partition interpretation")

    def dependencies(self) -> tuple[ResourceDependency, ...]:
        return (ResourceDependency(self.lineage, ARRAY_TYPE),)


@dataclass(frozen=True, slots=True)
class CellComponent:
    id: str
    field_id: str
    unit: UnitReference
    quantity_kind: QuantityKind

    def __post_init__(self) -> None:
        identity(self.id)
        identity(self.field_id)
        if (
            not isinstance(self.unit, UnitReference)
            or not isinstance(self.quantity_kind, QuantityKind)
            or self.quantity_kind not in (QuantityKind.LINEAR, QuantityKind.INTERVAL)
        ):
            raise ValueError("Cell averages require an exact unit and linear/interval component")


@dataclass(frozen=True, slots=True)
class CellInterpretation:
    owner_id: str
    support: ResourceReference
    components: tuple[CellComponent, ...]
    association: str = "cell_average"
    dtype: str = "float64"
    mask_policy: str = "all_finite"

    def __post_init__(self) -> None:
        identity(self.owner_id)
        ref(self.support)
        if (
            type(self.components) is not tuple
            or not 1 <= len(self.components) <= MAX_COMPONENTS
            or not all(isinstance(component, CellComponent) for component in self.components)
            or len({component.id for component in self.components}) != len(self.components)
        ):
            raise ValueError("A cell interpretation requires 1..8 distinct typed components")
        if (self.association, self.dtype, self.mask_policy) != (
            "cell_average",
            "float64",
            "all_finite",
        ):
            raise ValueError("Unsupported cell association, dtype or validity policy")

    def dependencies(self) -> tuple[ResourceDependency, ...]:
        return (ResourceDependency(self.support, SUPPORT_TYPE),)


@dataclass(frozen=True, slots=True)
class CellEpoch:
    index: int
    tick: int
    step: int
    interpretation: ResourceReference
    transfer: ResourceReference | None = None

    def __post_init__(self) -> None:
        bounded(self.index, 0, MAX_EPOCHS - 1, "Epoch")
        index(self.tick, "Tick")
        index(self.step, "Step")
        ref(self.interpretation)
        if self.index == 0:
            if self.tick != 0 or self.step != 0 or self.transfer is not None:
                raise ValueError("The initial epoch begins at zero without a runtime transfer")
        elif self.tick == 0 or self.step == 0 or self.transfer is None:
            raise ValueError("A support change requires its accepted instant and transfer")
        if self.transfer is not None:
            ref(self.transfer)


@dataclass(frozen=True, slots=True)
class CellChunk:
    values: ResourceReference
    epoch: int
    first_sample: int
    rows: int
    first_tick: int
    last_tick: int
    first_step: int
    last_step: int

    def __post_init__(self) -> None:
        ref(self.values)
        bounded(self.epoch, 0, MAX_EPOCHS - 1, "Epoch")
        bounded(self.first_sample, 0, MAX_SAMPLES - 1, "First sample")
        bounded(self.rows, 1, MAX_SAMPLES - self.first_sample, "Chunk rows")
        for value in (self.first_tick, self.last_tick, self.first_step, self.last_step):
            index(value, "Sample position")
        if self.rows == 1:
            if (self.first_tick, self.first_step) != (self.last_tick, self.last_step):
                raise ValueError("A singleton sample has one accepted position")
        elif self.last_tick <= self.first_tick or self.last_step <= self.first_step:
            raise ValueError("Chunk time and step must advance")

    @property
    def last_sample(self) -> int:
        return self.first_sample + self.rows - 1


@dataclass(frozen=True, slots=True)
class CellHistory:
    owner_id: str
    source_digest: str
    quantum: QuantityValue
    epochs: tuple[CellEpoch, ...]
    chunks: tuple[CellChunk, ...]
    decisions: ResourceReference | None = None

    def __post_init__(self) -> None:
        identity(self.owner_id)
        digest(self.source_digest)
        if scalar(self.quantum, "Time quantum") <= 0:
            raise ValueError("History requires a positive physical tick")
        if (
            type(self.epochs) is not tuple
            or not 1 <= len(self.epochs) <= MAX_EPOCHS
            or not all(isinstance(epoch, CellEpoch) for epoch in self.epochs)
        ):
            raise ValueError("History requires a bounded complete epoch index")
        if (
            type(self.chunks) is not tuple
            or not 1 <= len(self.chunks) <= MAX_CHUNKS
            or not all(isinstance(chunk, CellChunk) for chunk in self.chunks)
        ):
            raise ValueError("History requires a bounded complete chunk index")
        for ordinal, epoch in enumerate(self.epochs):
            if epoch.index != ordinal:
                raise ValueError("Epoch coverage must begin at zero without gaps")
            if ordinal and (
                epoch.tick <= self.epochs[ordinal - 1].tick
                or epoch.step <= self.epochs[ordinal - 1].step
                or epoch.interpretation == self.epochs[ordinal - 1].interpretation
            ):
                raise ValueError("An epoch requires an advancing instant and a changed support")
        previous = None
        for chunk in self.chunks:
            if chunk.epoch >= len(self.epochs):
                raise ValueError("Chunk references a missing epoch")
            epoch = self.epochs[chunk.epoch]
            if chunk.first_tick < epoch.tick or chunk.first_step < epoch.step:
                raise ValueError("A chunk cannot precede its support epoch")
            if chunk.epoch + 1 < len(self.epochs):
                next_epoch = self.epochs[chunk.epoch + 1]
                if chunk.last_tick >= next_epoch.tick or chunk.last_step >= next_epoch.step:
                    raise ValueError("A chunk cannot cross a support change")
            if previous is None:
                if (chunk.first_sample, chunk.first_tick, chunk.first_step, chunk.epoch) != (
                    0,
                    0,
                    0,
                    0,
                ):
                    raise ValueError("History starts at the initial sample")
            elif (
                chunk.first_sample != previous.last_sample + 1
                or chunk.first_tick <= previous.last_tick
                or chunk.first_step <= previous.last_step
                or chunk.epoch < previous.epoch
            ):
                raise ValueError(
                    "History has a sample gap, overlap, reversal or incompatible epoch"
                )
            previous = chunk
        if self.epochs[-1].tick > self.chunks[-1].last_tick:
            raise ValueError("History cannot include a future support")
        if self.decisions is not None:
            ref(self.decisions)

    def dependencies(self) -> tuple[ResourceDependency, ...]:
        return (
            *(
                ResourceDependency(epoch.interpretation, INTERPRETATION_TYPE)
                for epoch in self.epochs
            ),
            *(
                ResourceDependency(epoch.transfer, TRANSFER_TYPE)
                for epoch in self.epochs
                if epoch.transfer is not None
            ),
            *(ResourceDependency(chunk.values, ARRAY_TYPE) for chunk in self.chunks),
            *(
                (ResourceDependency(self.decisions, DECISIONS_TYPE),)
                if self.decisions is not None
                else ()
            ),
        )

    def extends(self, previous: CellHistory) -> None:
        """Writer admission checks the immutable acknowledged prefix before publication."""
        if (
            (self.owner_id, self.source_digest, self.quantum)
            != (previous.owner_id, previous.source_digest, previous.quantum)
            or self.epochs[: len(previous.epochs)] != previous.epochs
            or self.chunks[: len(previous.chunks)] != previous.chunks
        ):
            raise ValueError("New history cannot replace an acknowledged prefix")


@dataclass(frozen=True, slots=True)
class CellTransfer:
    region_id: str
    policy_id: str
    tick: int
    step: int
    quantum: QuantityValue
    source: ResourceReference
    target: ResourceReference
    before: ResourceReference
    after: ResourceReference
    indicators: ResourceReference
    normalized_residuals: tuple[float, ...]
    mapping_kind: str = "limited_linear_dyadic"

    def __post_init__(self) -> None:
        identity(self.region_id)
        identity(self.policy_id)
        index(self.tick, "Transfer tick")
        index(self.step, "Transfer step")
        if scalar(self.quantum, "Transfer time quantum") <= 0:
            raise ValueError("Transfer requires a positive physical tick")
        for value in (self.source, self.target, self.before, self.after, self.indicators):
            ref(value)
        if (
            self.source == self.target
            or self.mapping_kind != "limited_linear_dyadic"
            or type(self.normalized_residuals) is not tuple
            or not 1 <= len(self.normalized_residuals) <= MAX_COMPONENTS
            or any(
                type(value) is not float or not isfinite(value) or abs(value) > 1e-12
                for value in self.normalized_residuals
            )
        ):
            raise ValueError("Transfer requires distinct compatible supports and bounded residuals")

    def dependencies(self) -> tuple[ResourceDependency, ...]:
        return (
            ResourceDependency(self.source, INTERPRETATION_TYPE),
            ResourceDependency(self.target, INTERPRETATION_TYPE),
            *(
                ResourceDependency(value, ARRAY_TYPE)
                for value in (self.before, self.after, self.indicators)
            ),
        )


# Exact numeric table columns are part of this interpretation's v1 contract.
DECISION_COLUMNS = (
    "tick",
    "step",
    "epoch",
    "cells",
    "spatial_indicator",
    "temporal_error",
    "dt_ticks",
    "accepted",
    "refined_cells",
    "coarsened_cells",
    "solved_unknowns",
    "cumulative_work",
    "spatial_evaluated",
)


@dataclass(frozen=True, slots=True)
class DecisionLog:
    source_digest: str
    policy_id: str
    quantum: QuantityValue
    rows: int
    values: ResourceReference

    def __post_init__(self) -> None:
        digest(self.source_digest)
        identity(self.policy_id)
        if scalar(self.quantum, "Decision time quantum") <= 0:
            raise ValueError("Decisions require a positive physical tick")
        bounded(self.rows, 1, MAX_DECISIONS, "Decisions")
        ref(self.values)

    def dependencies(self) -> tuple[ResourceDependency, ...]:
        return (ResourceDependency(self.values, ARRAY_TYPE),)
