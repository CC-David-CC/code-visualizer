"""One complete accepted adaptive state and its independently validated retained prefix."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.values import QuantityValue, ResourceReference
from code_visualizer.execution.backends import PreparedComputation, ProducedResource
from code_visualizer.execution.resource_interpretation import ResourceDependency
from code_visualizer.extensions.adaptive_diffusion.problem import AdaptiveError, AdaptiveProblem
from code_visualizer.extensions.adaptive_fields.records import (
    DECISION_COLUMNS,
    DECISIONS_TYPE,
    HISTORY_TYPE,
    DecisionLog,
)
from code_visualizer.extensions.adaptive_fields.units import quantity
from code_visualizer.extensions.fields.arrays import array_resource
from code_visualizer.extensions.fields.records import (
    ARRAY_TYPE,
    METADATA_LIMIT,
    digest,
    identity,
    index,
    ref,
    scalar,
)
from code_visualizer.extensions.foundations.record_codec import RecordCodec
from code_visualizer.extensions.foundations.unit_algebra import QuantityKind
from code_visualizer.persistence.computation_resources import produced_descriptor

if TYPE_CHECKING:
    from code_visualizer.extensions.adaptive_diffusion.controller import AcceptedState
    from code_visualizer.extensions.adaptive_diffusion.history import AdaptiveWriter
    from code_visualizer.extensions.adaptive_fields.history import AdaptiveHistory

CHECKPOINT_TYPE = ResourceLogicalTypeReference("code_visualizer.adaptive_diffusion.checkpoint", "1")


@dataclass(frozen=True, slots=True)
class AdaptiveCheckpoint:
    source_digest: str
    numerical_identity: str
    history: ResourceReference
    state: ResourceReference
    counters: ResourceReference
    tick: int
    step: int
    epoch: int
    next_dt_ticks: int
    rejections: int
    solved_unknowns: int
    indicator_visits: int
    transferred_cells: int
    initial_mass: QuantityValue
    next_sample_tick: int
    next_checkpoint_tick: int
    method: str = "backward_euler_two_half_dyadic"
    state_version: int = 1

    def __post_init__(self) -> None:
        digest(self.source_digest)
        identity(self.numerical_identity)
        for reference in (self.history, self.state, self.counters):
            ref(reference)
        for value in (
            self.tick,
            self.step,
            self.epoch,
            self.next_dt_ticks,
            self.rejections,
            self.solved_unknowns,
            self.indicator_visits,
            self.transferred_cells,
            self.next_sample_tick,
            self.next_checkpoint_tick,
        ):
            index(value, "Checkpoint cursor/counter")
        if (
            self.next_dt_ticks < 1
            or self.next_dt_ticks & (self.next_dt_ticks - 1)
            or self.next_sample_tick <= self.tick
            or self.next_checkpoint_tick <= self.tick
            or scalar(self.initial_mass, "Initial mass") < 0
        ):
            raise ValueError("Checkpoint requires a binary next step and future output cursors")
        if (
            self.method != "backward_euler_two_half_dyadic"
            or type(self.state_version) is not int
            or self.state_version != 1
        ):
            raise ValueError("Unsupported adaptive checkpoint method/state format")

    def dependencies(self) -> tuple[ResourceDependency, ...]:
        return (
            ResourceDependency(self.history, HISTORY_TYPE),
            ResourceDependency(self.state, ARRAY_TYPE),
            ResourceDependency(self.counters, ARRAY_TYPE),
        )


_CODEC = RecordCodec((AdaptiveCheckpoint,))


def encode_checkpoint(value: AdaptiveCheckpoint) -> bytes:
    return _CODEC.encode(value)


def decode_checkpoint(payload: bytes) -> AdaptiveCheckpoint:
    return _CODEC.decode(payload, AdaptiveCheckpoint)


def checkpoint_dependencies(payload: bytes) -> tuple[ResourceDependency, ...]:
    return decode_checkpoint(payload).dependencies()


def numerical_identity() -> str:
    import platform
    import sys

    import numpy as np
    import scipy  # type: ignore[import-untyped]

    return (
        f"numpy={np.__version__};scipy={scipy.__version__};"
        f"{platform.system()}-{platform.machine()};python={sys.version_info.major}.{sys.version_info.minor};"
        "float64-le;be-two-half-dyadic-v1"
    )


def next_cursor(tick: int, every: int) -> int:
    return (tick // every + 1) * every


def checkpoint_resource(
    p: AdaptiveProblem,
    source: str,
    method_identity: str,
    writer: AdaptiveWriter,
    state: AcceptedState,
) -> ProducedResource:
    import numpy as np

    history = writer.acknowledged
    if (
        history is None
        or writer.root is None
        or writer.pending
        or state is not writer.sampled_state
        or state is not writer.last_state
        or (history.chunks[-1].last_tick, history.chunks[-1].last_step) != (state.tick, state.step)
    ):
        raise ValueError(
            "Checkpoint requires the acknowledged sampled solution/controller boundary"
        )
    values = array_resource("accepted-state", state.values)
    counters = array_resource(
        "accepted-controller", np.array((state.quiet, state.ages), dtype=np.float64).T
    )
    checkpoint = AdaptiveCheckpoint(
        source,
        method_identity,
        writer.root,
        produced_descriptor(values).reference,
        produced_descriptor(counters).reference,
        state.tick,
        state.step,
        state.epoch,
        state.next_dt_ticks,
        state.rejections,
        state.solved_unknowns,
        state.indicator_visits,
        state.transferred_cells,
        quantity(state.initial_mass, "kilogram"),
        next_cursor(state.tick, p.policy.sample_ticks),
        next_cursor(state.tick, p.policy.checkpoint_ticks),
    )
    return ProducedResource(
        f"checkpoint:{state.tick}",
        encode_checkpoint(checkpoint),
        "application/json",
        (p.problem_id, p.field_id, p.policy_id),
        f"Complete adaptive restart at t={p.policy.time(state.tick):.9g} s",
        logical_type=CHECKPOINT_TYPE,
        dependencies=(values, counters),
    )


def restore(
    snapshot: PreparedComputation,
    reference: ResourceReference,
    p: AdaptiveProblem,
    source: str,
    method_identity: str,
) -> tuple[AdaptiveHistory, AcceptedState]:
    import numpy as np

    from code_visualizer.extensions.adaptive_fields.history import (
        AdaptiveHistory,
        mixed_array,
        record,
    )

    resources = {item.descriptor.reference: item for item in snapshot.resources}
    try:
        resource = resources[reference]
    except KeyError as exc:
        raise AdaptiveError(
            "ADAPTIVE_CHECKPOINT_RESOURCE", "Checkpoint is absent from admitted input", p.problem_id
        ) from exc
    descriptor = resource.descriptor
    if (
        descriptor.logical_type != CHECKPOINT_TYPE
        or descriptor.media_type != "application/json"
        or descriptor.byte_size > METADATA_LIMIT
    ):
        raise AdaptiveError(
            "ADAPTIVE_CHECKPOINT_TYPE", "Unsupported checkpoint resource", p.problem_id
        )
    with resource.open() as stream:
        saved = decode_checkpoint(stream.read(METADATA_LIMIT + 1))
    if saved.source_digest != source or saved.numerical_identity != method_identity:
        raise AdaptiveError(
            "ADAPTIVE_CHECKPOINT_COMPATIBILITY",
            "Frozen source/policy or numerical implementation changed",
            p.policy_id,
        )
    if (
        saved.tick > p.policy.final_tick
        or saved.tick % p.policy.sample_ticks
        or saved.step > p.policy.maximum_steps
        or saved.epoch >= p.policy.maximum_epochs
        or saved.rejections > p.policy.maximum_rejections
        or saved.next_dt_ticks > p.policy.maximum_dt_ticks
        or saved.next_sample_tick != next_cursor(saved.tick, p.policy.sample_ticks)
        or saved.next_checkpoint_tick != next_cursor(saved.tick, p.policy.checkpoint_ticks)
        or saved.initial_mass.unit != quantity(1, "kilogram").unit
    ):
        raise AdaptiveError(
            "ADAPTIVE_CHECKPOINT_CURSOR",
            "Checkpoint counters or output schedule are incompatible",
            p.policy_id,
        )
    history = AdaptiveHistory(saved.history, resources.__getitem__, cache_bytes=0)
    try:
        support = history.supports[-1]
        meaning = history.interpretations[-1]
        last = history.slice(history.sample_count - 1)
        if (
            history.series.source_digest != source
            or history.series.quantum != quantity(p.policy.quantum)
            or (last.tick, last.position.step, last.epoch) != (saved.tick, saved.step, saved.epoch)
            or history.sample_count != saved.tick // p.policy.sample_ticks + 1
            or (
                support.region_id,
                support.space_id,
                support.frame_id,
                support.axis_id,
                support.axis_name,
            )
            != (p.region_id, p.space_id, p.frame_id, p.axis_id, p.axis_name)
            or (support.length, support.area, support.base_cells)
            != (quantity(p.length, "meter"), quantity(p.area, "square_meter"), p.policy.base_cells)
            or meaning.owner_id != p.field_id
            or len(meaning.components) != 1
            or meaning.components[0].quantity_kind is not QuantityKind.LINEAR
            or (
                meaning.components[0].id,
                meaning.components[0].field_id,
                meaning.components[0].unit,
            )
            != ("concentration", p.field_id, p.unit)
            or len(last.mesh.cells) > p.policy.maximum_cells
            or max(cell.level for cell in last.mesh.cells) > p.policy.maximum_level
        ):
            raise AdaptiveError(
                "ADAPTIVE_CHECKPOINT_INTERPRETATION",
                "State, field, support or complete history differs",
                p.field_id,
            )
        for chunk, array in history.iter_chunks():
            expected_ticks = (
                np.arange(chunk.first_sample, chunk.first_sample + chunk.rows)
                * p.policy.sample_ticks
            )
            if not np.array_equal(array[:, 0], expected_ticks):
                raise AdaptiveError(
                    "ADAPTIVE_CHECKPOINT_HISTORY",
                    "Retained samples do not follow the frozen schedule",
                    p.policy_id,
                )
        values = mixed_array(resources.__getitem__, saved.state, (len(last.mesh.cells),))
        counters = mixed_array(resources.__getitem__, saved.counters, (len(last.mesh.cells), 2))
        if (
            not np.array_equal(values, last.values[:, 0])
            or np.any(values < 0)
            or not np.equal(counters, np.floor(counters)).all()
            or np.any(counters < 0)
            or np.any(counters[:, 0] > p.policy.coarsen_after)
            or np.any(counters[:, 1] > p.policy.dwell)
        ):
            raise AdaptiveError(
                "ADAPTIVE_CHECKPOINT_STATE",
                "Solution or complete controller counters are invalid",
                p.policy_id,
            )
        mass = scalar(saved.initial_mass, "Initial mass")
        expected_mass = p.area * p.length * p.mean
        if abs(mass - expected_mass) > 1e-12 * max(expected_mass, 1e-300) or abs(
            p.area * float(last.mesh.widths @ values) - mass
        ) > 1e-9 * max(mass, 1e-300):
            raise AdaptiveError(
                "ADAPTIVE_CHECKPOINT_CONSERVATION",
                "Checkpoint mass differs from frozen initial meaning",
                p.field_id,
            )
        if saved.step:
            if history.series.decisions is None:
                raise AdaptiveError(
                    "ADAPTIVE_CHECKPOINT_DECISIONS", "Accepted decisions are missing", p.policy_id
                )
            log = record(
                resources.__getitem__, history.series.decisions, DecisionLog, DECISIONS_TYPE
            )
            decisions = mixed_array(
                resources.__getitem__, log.values, (log.rows, len(DECISION_COLUMNS))
            )
            if (
                log.policy_id != p.policy_id
                or log.rows != saved.step + saved.rejections
                or int(np.sum(decisions[:, 7])) != saved.step
                or tuple(decisions[-1, :3]) != (saved.tick, saved.step, saved.epoch)
                or decisions[-1, 10] != saved.solved_unknowns
                or decisions[-1, 11]
                != saved.solved_unknowns + saved.indicator_visits + saved.transferred_cells
            ):
                raise AdaptiveError(
                    "ADAPTIVE_CHECKPOINT_DECISIONS",
                    "Controller work/cursors disagree with accepted decisions",
                    p.policy_id,
                )
        from code_visualizer.extensions.adaptive_diffusion.controller import AcceptedState

        state = AcceptedState(
            last.mesh,
            values,
            tuple(int(v) for v in counters[:, 0]),
            tuple(int(v) for v in counters[:, 1]),
            saved.tick,
            saved.step,
            saved.epoch,
            saved.next_dt_ticks,
            saved.rejections,
            saved.solved_unknowns,
            saved.indicator_visits,
            saved.transferred_cells,
            mass,
        )
        return history, state
    except BaseException:
        history.close()
        raise
