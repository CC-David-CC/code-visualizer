"""Closed nonperiodic cell, input-tape and complete gas restart interpretations."""

from dataclasses import dataclass

from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.values import QuantityValue, ResourceReference, UnitReference
from code_visualizer.execution.resource_interpretation import ResourceDependency
from code_visualizer.extensions.fields.records import (
    ARRAY_TYPE,
    CHUNK_BYTES,
    TemporalPosition,
    digest,
    identity,
    index,
    ref,
    scalar,
)
from code_visualizer.extensions.foundations.record_codec import RecordCodec
from code_visualizer.extensions.hybrid_gas.policy import ModelState
from code_visualizer.extensions.hybrid_gas.units import quantity

PREFIX = "code_visualizer.hybrid_gas."
INTERPRETATION_TYPE = ResourceLogicalTypeReference(PREFIX + "interpretation", "1")
HISTORY_TYPE = ResourceLogicalTypeReference(PREFIX + "history", "1")
TAPE_TYPE = ResourceLogicalTypeReference(PREFIX + "input_tape", "1")
CHECKPOINT_TYPE = ResourceLogicalTypeReference(PREFIX + "checkpoint", "1")
TRANSFER_TYPE = ResourceLogicalTypeReference(PREFIX + "model_transfer", "1")
STATISTICS_TYPE = ResourceLogicalTypeReference(PREFIX + "statistics", "1")


def bounded(n: int, low: int, high: int, label: str) -> None:
    if type(n) is not int or not low <= n <= high:
        raise ValueError(f"{label} requires an integer in {low}..{high}")


@dataclass(frozen=True, slots=True)
class GasInterpretation:
    owner_id: str
    region_id: str
    slab_id: str
    policy_id: str
    space_id: str
    frame_id: str
    axis_id: str
    field_ids: tuple[str, ...]
    units: tuple[UnitReference, ...]
    height: QuantityValue
    area: QuantityValue
    quantum: QuantityValue
    cells: int
    slab_first: int
    slab_stop: int
    association: str = "wall_bounded_uniform_cell_average"

    def __post_init__(self) -> None:
        for v in (
            self.owner_id,
            self.region_id,
            self.slab_id,
            self.policy_id,
            self.space_id,
            self.frame_id,
            self.axis_id,
        ):
            identity(v)
        bounded(self.cells, 16, 128, "Gas cells")
        bounded(self.slab_first, 1, self.cells - 2, "Slab first")
        bounded(self.slab_stop, self.slab_first + 1, self.cells - 1, "Slab stop")
        if (
            type(self.field_ids) is not tuple
            or len(self.field_ids) != 5
            or len(set(self.field_ids)) != 5
        ):
            raise ValueError("Gas interpretation requires five distinct conserved field identities")
        for v in self.field_ids:
            identity(v)
        expected = (
            quantity(1, "kilogram_per_cubic_meter").unit,
            *(quantity(1, "momentum_per_volume").unit for _ in range(3)),
            quantity(1, "joule_per_cubic_meter").unit,
        )
        if self.units != expected or self.association != "wall_bounded_uniform_cell_average":
            raise ValueError(
                "Gas conserved component order/units or support interpretation differs"
            )
        for q, unit in (
            (self.height, "meter"),
            (self.area, "square_meter"),
            (self.quantum, "second"),
        ):
            if scalar(q, "Gas support") <= 0 or q.unit != quantity(1, unit).unit:
                raise ValueError("Gas support and time require positive SI quantities")

    @property
    def width(self) -> int:
        return 1 + 5 * self.cells  # mode flag, then cell-major conserved components

    def dependencies(self) -> tuple[ResourceDependency, ...]:
        return ()


@dataclass(frozen=True, slots=True)
class GasChunk:
    resource: ResourceReference
    first: TemporalPosition
    last: TemporalPosition
    rows: int
    value_count: int

    def __post_init__(self) -> None:
        ref(self.resource)
        bounded(self.rows, 1, 256, "Gas chunk rows")
        bounded(self.value_count, 81, 641, "Gas chunk width")
        if (self.value_count - 1) % 5 or self.rows * (self.value_count + 2) * 8 > CHUNK_BYTES - 128:
            raise ValueError("Gas chunk exceeds its support/numeric boundary")
        if not isinstance(self.first, TemporalPosition) or not isinstance(
            self.last, TemporalPosition
        ):
            raise ValueError("Gas chunk requires exact physical positions")
        if (
            self.last.sample - self.first.sample != self.rows - 1
            or self.first.time.unit != quantity(1, "second").unit
            or self.last.time.unit != self.first.time.unit
            or (self.rows == 1 and self.first != self.last)
            or (
                self.rows > 1
                and (
                    self.first.step >= self.last.step
                    or scalar(self.first.time, "First") >= scalar(self.last.time, "Last")
                )
            )
        ):
            raise ValueError("Gas chunk physical coverage disagrees")


@dataclass(frozen=True, slots=True)
class GasSeries:
    interpretation: ResourceReference
    source_digest: str
    chunks: tuple[GasChunk, ...]
    prefix: ResourceReference | None = None
    prefix_last: TemporalPosition | None = None

    def __post_init__(self) -> None:
        ref(self.interpretation)
        digest(self.source_digest)
        if type(self.chunks) is not tuple or not 1 <= len(self.chunks) <= 64:
            raise ValueError("Gas history requires 1..64 bounded chunks")
        if (self.prefix is None) != (self.prefix_last is None):
            raise ValueError("Gas prefix requires its exact accepted position")
        if self.prefix is not None:
            ref(self.prefix)
        previous = self.prefix_last
        for chunk in self.chunks:
            if not isinstance(chunk, GasChunk) or chunk.value_count != self.chunks[0].value_count:
                raise ValueError("Gas history has incompatible chunk meanings")
            if previous is None:
                if chunk.first.sample != 0:
                    raise ValueError("Gas history begins at zero or an explicit prefix")
            elif (
                chunk.first.sample != previous.sample + 1
                or chunk.first.step <= previous.step
                or scalar(chunk.first.time, "Time") <= scalar(previous.time, "Previous")
            ):
                raise ValueError("Gas history has gaps or overlap")
            previous = chunk.last
        bounded(self.last.sample, 0, 255, "Gas sample")

    @property
    def last(self) -> TemporalPosition:
        return self.chunks[-1].last

    def dependencies(self) -> tuple[ResourceDependency, ...]:
        return (
            ResourceDependency(self.interpretation, INTERPRETATION_TYPE),
            *((ResourceDependency(self.prefix, HISTORY_TYPE),) if self.prefix else ()),
            *(ResourceDependency(c.resource, ARRAY_TYPE) for c in self.chunks),
        )


@dataclass(frozen=True, slots=True)
class TapeChunk:
    resource: ResourceReference
    rows: int

    def __post_init__(self) -> None:
        ref(self.resource)
        bounded(self.rows, 1, 4096, "Input-tape rows")


@dataclass(frozen=True, slots=True)
class GasTape:
    source_digest: str
    chunks: tuple[TapeChunk, ...]
    columns: str = "first_tick,last_tick,lower_rho,T,ux,uy,uz,upper_rho,T,ux,uy,uz"

    def __post_init__(self) -> None:
        digest(self.source_digest)
        if (
            type(self.chunks) is not tuple
            or len(self.chunks) > 128
            or any(not isinstance(c, TapeChunk) for c in self.chunks)
            or sum(c.rows for c in self.chunks) > 400000
            or self.columns != "first_tick,last_tick,lower_rho,T,ux,uy,uz,upper_rho,T,ux,uy,uz"
        ):
            raise ValueError("Gas tape exceeds its exact state-input contract")

    def dependencies(self) -> tuple[ResourceDependency, ...]:
        return tuple(ResourceDependency(c.resource, ARRAY_TYPE) for c in self.chunks)


@dataclass(frozen=True, slots=True)
class GasCheckpoint:
    source_digest: str
    method_digest: str
    history: ResourceReference
    tape: ResourceReference
    state: ResourceReference
    accumulators: ResourceReference
    means: ResourceReference | None
    moment_blocks: ResourceReference | None
    observations: ResourceReference | None
    native: ResourceReference | None
    decisions: ResourceReference | None
    transfers: tuple[ResourceReference, ...]
    tick: int
    windows: int
    model: ModelState
    mean_count: int
    moment_count: int
    observation_count: int
    native_length: int
    decision_count: int
    particle_steps: int
    continuum_unknowns: int
    method: str = "sparta_v3_exact_complete_input_reconstruction_ssprk2_v1"

    def __post_init__(self) -> None:
        digest(self.source_digest)
        digest(self.method_digest)
        for r in (self.history, self.tape, self.state, self.accumulators):
            ref(r)
        bounded(self.tick, 0, 400000, "Checkpoint tick")
        bounded(self.windows, 0, 400000, "Checkpoint windows")
        for resource, count, limit in (
            (self.means, self.mean_count, 512),
            (self.moment_blocks, self.moment_count, 256),
            (self.observations, self.observation_count, 256),
            (self.native, self.native_length, 500000),
            (self.decisions, self.decision_count, 513),
        ):
            bounded(count, 0, limit, "Checkpoint length")
            if (resource is None) != (count == 0):
                raise ValueError("Checkpoint counts and retained arrays disagree")
            if resource is not None:
                ref(resource)
        if not isinstance(self.model, ModelState) or self.model.particle != (
            self.native is not None
        ):
            raise ValueError("A particle checkpoint requires its complete native observation")
        bounded(self.particle_steps, 0, 400000, "Particle work")
        bounded(self.continuum_unknowns, 0, 1638400000, "Continuum work")
        if type(self.transfers) is not tuple or len(self.transfers) > 8:
            raise ValueError("Model transfers exceed the checkpoint bound")
        for r in self.transfers:
            ref(r)
        if self.method != "sparta_v3_exact_complete_input_reconstruction_ssprk2_v1":
            raise ValueError("Unsupported gas reconstruction contract")

    def dependencies(self) -> tuple[ResourceDependency, ...]:
        return (
            ResourceDependency(self.history, HISTORY_TYPE),
            ResourceDependency(self.tape, TAPE_TYPE),
            *(
                ResourceDependency(r, ARRAY_TYPE)
                for r in (
                    self.state,
                    self.accumulators,
                    self.means,
                    self.moment_blocks,
                    self.observations,
                    self.native,
                    self.decisions,
                )
                if r is not None
            ),
            *(ResourceDependency(r, TRANSFER_TYPE) for r in self.transfers),
        )


@dataclass(frozen=True, slots=True)
class GasTransfer:
    source_digest: str
    interpretation: ResourceReference
    policy_id: str
    tick: int
    kind: str
    before: ResourceReference
    after: ResourceReference
    moments: ResourceReference
    accounting: ResourceReference
    blocks: ResourceReference | None = None
    block_count: int = 0
    uncertainty: ResourceReference | None = None

    def __post_init__(self) -> None:
        digest(self.source_digest)
        identity(self.policy_id)
        bounded(self.tick, 0, 400000, "Transfer tick")
        bounded(self.block_count, 0, 256, "Transfer block count")
        if self.kind not in ("activation", "return") or (self.kind == "return") != (
            self.block_count >= 20
        ):
            raise ValueError(
                "Model transfer requires its declared initialization or return statistics"
            )
        if (self.blocks is None) != (self.block_count == 0):
            raise ValueError("Transfer blocks disagree with their declared coverage")
        if (self.uncertainty is None) != (self.block_count == 0):
            raise ValueError("Return requires its recorded uncertainty")
        for r in (self.interpretation, self.before, self.after, self.moments, self.accounting):
            ref(r)
        if self.blocks is not None:
            ref(self.blocks)
        if self.uncertainty is not None:
            ref(self.uncertainty)

    def dependencies(self) -> tuple[ResourceDependency, ...]:
        return (
            ResourceDependency(self.interpretation, INTERPRETATION_TYPE),
            *(
                ResourceDependency(r, ARRAY_TYPE)
                for r in (
                    self.before,
                    self.after,
                    self.moments,
                    self.accounting,
                    self.blocks,
                    self.uncertainty,
                )
                if r is not None
            ),
        )


@dataclass(frozen=True, slots=True)
class GasStatistics:
    source_digest: str
    physical_digest: str
    interpretation: ResourceReference
    blocks: ResourceReference
    count: int
    seed: int
    first_tick: int
    block_ticks: int
    protocol: str = "profiles8,bulk_shear,rho,T,uy,uz,wall_shear2"

    def __post_init__(self) -> None:
        digest(self.source_digest)
        digest(self.physical_digest)
        ref(self.interpretation)
        ref(self.blocks)
        bounded(self.count, 1, 256, "Statistical blocks")
        bounded(self.seed, 1, (1 << 31) - 1, "Replica seed")
        index(self.first_tick, "Warmup end")
        bounded(self.block_ticks, 1, 400000, "Block ticks")
        if (
            self.first_tick + self.block_ticks * self.count > 400000
            or self.protocol != "profiles8,bulk_shear,rho,T,uy,uz,wall_shear2"
        ):
            raise ValueError("Unsupported statistical interpretation/coverage")

    def dependencies(self) -> tuple[ResourceDependency, ...]:
        return (
            ResourceDependency(self.interpretation, INTERPRETATION_TYPE),
            ResourceDependency(self.blocks, ARRAY_TYPE),
        )


CODEC = RecordCodec(
    (
        GasInterpretation,
        GasChunk,
        GasSeries,
        TemporalPosition,
        TapeChunk,
        GasTape,
        ModelState,
        GasCheckpoint,
        GasTransfer,
        GasStatistics,
    )
)
