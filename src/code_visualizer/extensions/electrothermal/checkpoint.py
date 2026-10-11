"""Complete accepted coupled state and exact history, selected through the existing host."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import TYPE_CHECKING

from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.values import ResourceReference
from code_visualizer.execution.backends import PreparedComputation, ProducedResource
from code_visualizer.execution.resource_interpretation import ResourceDependency
from code_visualizer.extensions.channels.history import ChannelHistory
from code_visualizer.extensions.channels.records import INTERPRETATION_TYPE, SERIES_TYPE
from code_visualizer.extensions.electrothermal.domain import MAPPING_ID, METHOD_ID
from code_visualizer.extensions.electrothermal.history import HistoryWriter, interpretation, values
from code_visualizer.extensions.electrothermal.numerics import (
    ENERGY_TOLERANCE,
    TOLERANCE,
    AcceptedState,
    CoupledSolver,
    WindowIdentity,
)
from code_visualizer.extensions.electrothermal.problem import CouplingError, ElectrothermalProblem
from code_visualizer.extensions.electrothermal.units import quantity
from code_visualizer.extensions.fields.arrays import array_resource, read_array
from code_visualizer.extensions.fields.records import (
    ARRAY_TYPE,
    METADATA_LIMIT,
    TemporalPosition,
    digest,
    identity,
    index,
    ref,
)
from code_visualizer.extensions.foundations.record_codec import RecordCodec
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.computation_resources import produced_descriptor

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

CHECKPOINT_TYPE = ResourceLogicalTypeReference("org.codevisualizer.electrothermal.checkpoint", "1")
STATE_LAYOUT = ("resistor_rise_kelvin", "sink_rise_kelvin", "input_joule", "ambient_joule")


@dataclass(frozen=True, slots=True)
class CoupledCheckpoint:
    compatibility_digest: str
    interpretation: ResourceReference
    state: ResourceReference
    prefix: ResourceReference
    position: TemporalPosition
    numerical_identity: str
    policy_digest: str
    next_sample_step: int
    next_checkpoint_step: int
    method_id: str = METHOD_ID
    method_version: str = "1"
    state_version: int = 1
    state_layout: tuple[str, ...] = STATE_LAYOUT
    dtype: str = "float64"

    def __post_init__(self) -> None:
        digest(self.compatibility_digest)
        digest(self.policy_digest)
        for value in (self.interpretation, self.state, self.prefix):
            ref(value)
        identity(self.numerical_identity)
        if not isinstance(self.position, TemporalPosition):
            raise ValueError("A coupled checkpoint requires an accepted position")
        index(self.next_sample_step, "Next sample")
        index(self.next_checkpoint_step, "Next checkpoint")
        if min(self.next_sample_step, self.next_checkpoint_step) <= self.position.step:
            raise ValueError("Checkpoint cursors must follow the accepted window")
        if (
            self.method_id != METHOD_ID
            or self.method_version != "1"
            or self.dtype != "float64"
            or type(self.state_version) is not int
            or self.state_version != 1
            or self.state_layout != STATE_LAYOUT
        ):
            raise ValueError("Unsupported coupled numerical state/method layout")

    def dependencies(self) -> tuple[ResourceDependency, ...]:
        return (
            ResourceDependency(self.interpretation, INTERPRETATION_TYPE),
            ResourceDependency(self.state, ARRAY_TYPE),
            ResourceDependency(self.prefix, SERIES_TYPE),
        )


CODEC = RecordCodec((CoupledCheckpoint, TemporalPosition))


def checkpoint_dependencies(payload: bytes) -> tuple[ResourceDependency, ...]:
    return CODEC.decode(payload, CoupledCheckpoint).dependencies()


def next_cursor(step: int, every: int) -> int:
    return (step // every + 1) * every


def policy_digest(problem: ElectrothermalProblem) -> str:
    data: dict[str, JsonValue] = {
        "problem": asdict(problem),
        "mapping_id": MAPPING_ID,
        "mapping_version": "1",
        "method_id": METHOD_ID,
        "method_version": "1",
    }
    return sha256(canonical_data_bytes(data)).hexdigest()


def checkpoint_resource(
    problem: ElectrothermalProblem,
    source_digest: str,
    numerical_identity: str,
    history: HistoryWriter,
    state: AcceptedState,
) -> ProducedResource:
    import numpy as np

    if (
        history.root is None
        or history.last is None
        or history.pending
        or history.last.step != state.step
    ):
        raise ValueError("A checkpoint requires its acknowledged exact accepted prefix")
    resource = array_resource(
        f"state:{state.step}",
        np.asarray(
            (state.resistor_rise, state.sink_rise, state.energy_in, state.energy_out),
            dtype=np.float64,
        ),
    )
    record = CoupledCheckpoint(
        source_digest,
        history.interpretation,
        produced_descriptor(resource).reference,
        history.root,
        history.last,
        numerical_identity,
        policy_digest(problem),
        next_cursor(state.step, problem.sample_every),
        next_cursor(state.step, problem.checkpoint_every),
    )
    return ProducedResource(
        f"checkpoint:{state.step}",
        CODEC.encode(record),
        "application/json",
        problem.origins,
        f"Restart at accepted window {state.step}; t={problem.time(state.step):.9g} s",
        logical_type=CHECKPOINT_TYPE,
        dependencies=(resource,),
    )


def restore(
    snapshot: PreparedComputation,
    reference: ResourceReference,
    problem: ElectrothermalProblem,
    source_digest: str,
    solver: CoupledSolver,
) -> tuple[ChannelHistory, AcceptedState]:
    import numpy as np

    resources = {item.descriptor.reference: item for item in snapshot.resources}
    try:
        resource = resources[reference]
    except KeyError as exc:
        raise CouplingError(
            "COUPLING_CHECKPOINT_RESOURCE", "Selected checkpoint is unavailable", problem.id
        ) from exc
    if (
        resource.descriptor.logical_type != CHECKPOINT_TYPE
        or resource.descriptor.media_type != "application/json"
        or resource.descriptor.byte_size > METADATA_LIMIT
    ):
        raise CouplingError(
            "COUPLING_CHECKPOINT_TYPE", "Unsupported checkpoint resource", problem.id
        )
    with resource.open() as stream:
        record = CODEC.decode(stream.read(METADATA_LIMIT + 1), CoupledCheckpoint)
    if (
        record.compatibility_digest != source_digest
        or record.policy_digest != policy_digest(problem)
        or record.numerical_identity != solver.numerical_identity
    ):
        raise CouplingError(
            "COUPLING_CHECKPOINT_COMPATIBILITY",
            "Scientific input, mapping, method or schedule changed",
            problem.id,
        )
    position = record.position
    if (
        position.step > problem.windows
        or position.time != quantity(problem.time(position.step))
        or record.next_sample_step != next_cursor(position.step, problem.sample_every)
        or record.next_checkpoint_step != next_cursor(position.step, problem.checkpoint_every)
    ):
        raise CouplingError(
            "COUPLING_CHECKPOINT_CURSOR",
            "Checkpoint time or future cursors are incompatible",
            problem.policy_id,
        )
    history = ChannelHistory(record.prefix, resources.__getitem__, cache_bytes=0)
    try:
        if (
            history.series.source_digest != source_digest
            or history.series.interpretation != record.interpretation
            or history.series.last != position
            or history.interpretation != interpretation(problem)
        ):
            raise CouplingError(
                "COUPLING_CHECKPOINT_INTERPRETATION",
                "Checkpoint channels/support/input disagree",
                problem.id,
            )
        state_resource = resources[record.state]
        if (
            state_resource.descriptor.tensor is None
            or state_resource.descriptor.tensor.unit is not None
        ):
            raise CouplingError(
                "COUPLING_CHECKPOINT_STATE",
                "Mixed restart state cannot declare one unit",
                problem.id,
            )
        array = read_array(state_resource, (4,))
        state = AcceptedState(position.step, *(float(v) for v in array))
        if min(array) < 0:
            raise CouplingError(
                "COUPLING_CHECKPOINT_STATE",
                "Restart rises and accepted energy must be nonnegative",
                problem.id,
            )
        circuit = solver.electrical(
            WindowIdentity(source_digest, state.step, problem.time(state.step)),
            problem.ambient_temperature + state.resistor_rise,
        )
        last = history.slice(position.sample).values
        if not np.array_equal(last[:13], values(problem, state, circuit)[:13]):
            raise CouplingError(
                "COUPLING_CHECKPOINT_STATE",
                "Complete thermal/energy/circuit state disagrees with prefix",
                problem.id,
            )
        expected = tuple(
            step
            for step in range(position.step + 1)
            if step % problem.sample_every == 0
            or step % problem.checkpoint_every == 0
            or step == problem.windows
        )
        if len(expected) != history.sample_count:
            raise CouplingError(
                "COUPLING_CHECKPOINT_HISTORY",
                "The declared sampled prefix is incomplete",
                problem.policy_id,
            )
        cursor = 0
        previous_row = None
        for _chunk, rows in history.iter_chunks():
            steps = np.asarray(expected[cursor : cursor + len(rows)], dtype=np.float64)
            if (
                not np.array_equal(rows[:, 0], steps)
                or not np.array_equal(rows[:, 1], steps * problem.dt)
                or np.any(np.abs(rows[:, 14]) > ENERGY_TOLERANCE * np.maximum(1, steps))
                or np.any(np.abs(rows[:, 15:18]) > problem.power_scale * TOLERANCE)
                or np.any(rows[:, 18] > TOLERANCE)
                or np.any(rows[:, 18] < 0)
            ):
                raise CouplingError(
                    "COUPLING_CHECKPOINT_HISTORY",
                    "Retained physical samples or balances are invalid",
                    problem.id,
                )
            # Every retained row is evidence, not just the restart endpoint.
            # Check the algebra and balances observable in this sampled prefix;
            # do not replay missing windows or trust self-reported residuals.
            validate_sampled_physics(rows, problem, circuit.voltage, previous_row)
            previous_row = rows[-1].copy()
            cursor += len(rows)
        return history, state
    except BaseException:
        history.close()
        raise


def validate_sampled_physics(
    rows: NDArray[np.float64],
    p: ElectrothermalProblem,
    voltage: float,
    previous: NDArray[np.float64] | None = None,
) -> None:
    import numpy as np

    data = rows[:, 2:]
    x, y = data[:, 0] - p.ambient_temperature, data[:, 1] - p.ambient_temperature
    resistance = p.resistance * (1 + p.alpha * (data[:, 0] - p.reference_temperature))
    if (
        np.any(data[:, :2] < 200)
        or np.any(data[:, :2] > 1000)
        or np.any(x < -TOLERANCE * p.temperature_scale)
        or np.any(y < -TOLERANCE * p.temperature_scale)
        or np.any(resistance <= 0)
        or np.any(data[:, 9:11] < 0)
    ):
        raise CouplingError("COUPLING_CHECKPOINT_HISTORY", "Invalid retained physical range", p.id)
    current = voltage / resistance
    contact = p.contact_conductance * (x - y)
    stored = p.resistor_capacity * (
        x - p.initial_resistor_temperature + p.ambient_temperature
    ) + p.sink_capacity * (y - p.initial_sink_temperature + p.ambient_temperature)
    expected = np.column_stack(
        (
            resistance,
            np.full(len(rows), voltage),
            current,
            voltage * current,
            contact,
            -contact,
            p.ambient_conductance * y,
            stored,
            data[:, 9] - data[:, 10] - stored,
        )
    )
    observed = data[:, (2, 3, 4, 5, 6, 7, 8, 11, 12)]
    scales = np.asarray(
        (
            max(1, p.resistance),
            max(1, abs(voltage)),
            max(1, abs(voltage) / p.resistance),
            p.power_scale,
            p.power_scale,
            p.power_scale,
            p.power_scale,
            p.energy_scale,
            p.energy_scale,
        )
    )
    if np.any(np.abs(expected - observed) > TOLERANCE * scales):
        raise CouplingError(
            "COUPLING_CHECKPOINT_HISTORY",
            "Retained channels contradict their physical meaning",
            p.id,
        )
    for row in rows:
        v = row[2:]
        if row[0] == 0 and (
            v[0] != p.initial_resistor_temperature
            or v[1] != p.initial_sink_temperature
            or np.any(v[9:13] != 0)
        ):
            raise CouplingError(
                "COUPLING_CHECKPOINT_HISTORY", "Retained initial state differs from input", p.id
            )
        if previous is not None:
            before = previous[2:]
            if np.any(v[9:11] < before[9:11]):
                raise CouplingError(
                    "COUPLING_CHECKPOINT_HISTORY", "Retained cumulative energy decreases", p.id
                )
            if row[0] == previous[0] + 1:
                balances = np.asarray(
                    (
                        p.resistor_capacity * (v[0] - before[0]) / p.dt - v[5] + v[6],
                        p.sink_capacity * (v[1] - before[1]) / p.dt + v[7] + v[8],
                    )
                )
                # Absolute-temperature subtraction loses a few ulps. Bound this
                # roundoff explicitly, separately from the solver's residual.
                roundoff = (
                    8
                    * np.finfo(float).eps
                    * 1000
                    * max(p.resistor_capacity, p.sink_capacity)
                    / p.dt
                )
                if (
                    np.any(np.abs(balances - v[13:15]) > p.power_scale * TOLERANCE + roundoff)
                    or abs(v[9] - before[9] - p.dt * v[5]) > ENERGY_TOLERANCE
                    or abs(v[10] - before[10] - p.dt * v[8]) > ENERGY_TOLERANCE
                ):
                    raise CouplingError(
                        "COUPLING_CHECKPOINT_HISTORY",
                        "Retained adjacent windows do not balance",
                        p.id,
                    )
        previous = row
