"""Complete immutable scientific transitions; no worker, GUI or authority ownership."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING

from code_visualizer.extensions.adaptive_diffusion.adaptation import (
    MeshChange,
    adapt,
    balanced_partition,
    indicator,
)
from code_visualizer.extensions.adaptive_diffusion.numerics import diffuse
from code_visualizer.extensions.adaptive_diffusion.problem import AdaptiveError, AdaptiveProblem
from code_visualizer.extensions.adaptive_fields.mesh import Mesh

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class AcceptedState:
    mesh: Mesh
    values: NDArray[np.float64]
    quiet: tuple[int, ...]
    ages: tuple[int, ...]
    tick: int
    step: int
    epoch: int
    next_dt_ticks: int
    rejections: int
    solved_unknowns: int
    indicator_visits: int
    transferred_cells: int
    initial_mass: float

    def __post_init__(self) -> None:
        import numpy as np

        if (
            not isinstance(self.mesh, Mesh)
            or not isinstance(self.values, np.ndarray)
            or self.values.shape != (len(self.mesh.cells),)
            or self.values.dtype != np.dtype("<f8")
            or not np.isfinite(self.values).all()
            or np.any(self.values < 0)
        ):
            raise ValueError("Accepted concentration must be a finite nonnegative cell vector")
        for counters in (self.quiet, self.ages):
            if (
                type(counters) is not tuple
                or len(counters) != len(self.mesh.cells)
                or any(type(value) is not int or not 0 <= value <= 1000 for value in counters)
            ):
                raise ValueError("Accepted controller counters must match their exact support")
        for value in (
            self.tick,
            self.step,
            self.epoch,
            self.rejections,
            self.solved_unknowns,
            self.indicator_visits,
            self.transferred_cells,
        ):
            if type(value) is not int or not 0 <= value < 1 << 53:
                raise ValueError("Accepted state requires exact nonnegative counters")
        if (
            type(self.next_dt_ticks) is not int
            or not 1 <= self.next_dt_ticks <= 1 << 20
            or self.next_dt_ticks & (self.next_dt_ticks - 1)
            or not isfinite(self.initial_mass)
            or self.initial_mass < 0
        ):
            raise ValueError("Accepted state requires a binary time step and finite initial mass")
        # Bytes own the accepted vector. A caller cannot re-enable writing through
        # a mutable NumPy owner and thereby alter the base of a retry/checkpoint.
        object.__setattr__(self, "values", np.frombuffer(self.values.tobytes(), dtype="<f8"))

    @property
    def work(self) -> int:
        return self.solved_unknowns + self.indicator_visits + self.transferred_cells


@dataclass(frozen=True, slots=True)
class StepDecision:
    tick: int
    step: int
    epoch: int
    cells: int
    spatial_indicator: float
    temporal_error: float
    dt_ticks: int
    accepted: bool
    refined_cells: int
    coarsened_cells: int
    solved_unknowns: int
    cumulative_work: int
    spatial_evaluated: bool

    def row(self) -> tuple[float, ...]:
        return tuple(
            float(value)
            for value in (
                self.tick,
                self.step,
                self.epoch,
                self.cells,
                self.spatial_indicator,
                self.temporal_error,
                self.dt_ticks,
                self.accepted,
                self.refined_cells,
                self.coarsened_cells,
                self.solved_unknowns,
                self.cumulative_work,
                self.spatial_evaluated,
            )
        )


@dataclass(frozen=True, slots=True)
class Transition:
    state: AcceptedState
    decisions: tuple[StepDecision, ...]
    change: MeshChange | None


@dataclass(frozen=True, slots=True)
class InitialPass:
    mesh: Mesh
    values: NDArray[np.float64]
    indicators: NDArray[np.float64] | None


@dataclass(frozen=True, slots=True)
class Initialization:
    state: AcceptedState
    passes: tuple[InitialPass, ...]


def initialize(p: AdaptiveProblem) -> Initialization:
    mesh = Mesh.uniform(p.region_id, p.policy.base_cells, p.length)
    values = p.initial_values(mesh)
    visits = transferred = 0
    passes = []
    if p.policy.mesh_mode == "adaptive":
        for _ in range(p.policy.maximum_level + 1):
            eta = indicator(p, mesh, values)
            passes.append(InitialPass(mesh, values, eta))
            visits += len(mesh.cells)
            marks = {cell for cell, value in zip(mesh.cells, eta, strict=True) if value > 1}
            if not marks:
                break
            candidate, _, _ = balanced_partition(p, mesh, marks, set())
            # This is initialization from the same authored function, not a claim
            # that interpolation repaired a previously evolved coarse solution.
            transferred += len(mesh.cells) + len(candidate.cells)
            mesh = candidate
            values = p.initial_values(mesh)
        else:
            raise AdaptiveError(
                "ADAPTIVE_INITIAL_RESOLUTION",
                "Initial refinement cannot meet the declared fidelity",
                p.policy_id,
            )
    else:
        passes.append(InitialPass(mesh, values, None))
    state = AcceptedState(
        mesh,
        values,
        (0,) * len(mesh.cells),
        (0,) * len(mesh.cells),
        0,
        0,
        0,
        p.policy.maximum_dt_ticks,
        0,
        0,
        visits,
        transferred,
        p.area * float(mesh.widths @ values),
    )
    return Initialization(state, tuple(passes))


def start(p: AdaptiveProblem) -> AcceptedState:
    return initialize(p).state


def advance(p: AdaptiveProblem, base: AcceptedState, cutoff_tick: int) -> Transition:
    import numpy as np

    if base.step >= p.policy.maximum_steps:
        raise AdaptiveError("ADAPTIVE_STEP_BUDGET", "Accepted-step budget exhausted", p.policy_id)
    if type(cutoff_tick) is not int or not base.tick < cutoff_tick <= p.policy.final_tick:
        raise AdaptiveError(
            "ADAPTIVE_SCHEDULE", "A transition needs a future bounded output tick", p.policy_id
        )
    if (base.mesh.region_id, base.mesh.length, base.mesh.base_cells) != (
        p.region_id,
        p.length,
        p.policy.base_cells,
    ):
        raise AdaptiveError(
            "ADAPTIVE_MAPPING", "Accepted state belongs to a different physical region", p.region_id
        )
    maximum = min(base.next_dt_ticks, p.policy.maximum_dt_ticks, cutoff_tick - base.tick)
    dt_ticks = 1 << (maximum.bit_length() - 1)
    solved, rejected = base.solved_unknowns, base.rejections
    decisions = []
    while True:
        dt = p.policy.time(dt_ticks)
        try:
            full = diffuse(base.mesh, base.values, p.diffusivity, dt)
            half = diffuse(base.mesh, base.values, p.diffusivity, dt / 2)
            candidate = diffuse(base.mesh, half, p.diffusivity, dt / 2)
        except ValueError as exc:
            raise AdaptiveError("ADAPTIVE_NUMERICAL", str(exc), p.field_id) from exc
        solved += 3 * len(base.mesh.cells)
        error = float(
            np.max(
                np.abs(candidate - full)
                / (
                    p.policy.temporal_atol
                    + p.policy.temporal_rtol
                    * np.maximum(np.maximum(np.abs(candidate), np.abs(base.values)), p.scale)
                )
            )
        )
        if not np.isfinite(error):
            raise AdaptiveError("ADAPTIVE_NUMERICAL", "Temporal estimate is not finite", p.field_id)
        if error <= 1:
            break
        rejected += 1
        decisions.append(
            StepDecision(
                base.tick,
                base.step,
                base.epoch,
                len(base.mesh.cells),
                0,
                error,
                dt_ticks,
                False,
                0,
                0,
                solved,
                solved + base.indicator_visits + base.transferred_cells,
                False,
            )
        )
        if rejected > p.policy.maximum_rejections:
            raise AdaptiveError(
                "ADAPTIVE_REJECTION_BUDGET", "Temporal rejection budget exhausted", p.policy_id
            )
        if dt_ticks == 1:
            raise AdaptiveError(
                "ADAPTIVE_TIME_RESOLUTION",
                "Required temporal fidelity is below the minimum tick",
                p.policy_id,
            )
        dt_ticks //= 2
    mesh, values = base.mesh, candidate
    quiet, ages = base.quiet, base.ages
    visits, transferred, eta, change = base.indicator_visits, base.transferred_cells, 0.0, None
    spatial_evaluated = (
        p.policy.mesh_mode == "adaptive" and (base.step + 1) % p.policy.decision_every == 0
    )
    if spatial_evaluated:
        result = adapt(p, base.mesh, candidate, base.quiet, base.ages)
        mesh, values, quiet, ages = result.mesh, result.values, result.quiet, result.ages
        visits += result.indicator_visits
        transferred += result.transferred_cells
        eta, change = result.maximum_indicator, result.change
    epoch = base.epoch + (change is not None)
    if epoch >= p.policy.maximum_epochs:
        raise AdaptiveError("ADAPTIVE_EPOCH_BUDGET", "Support epoch budget exhausted", p.policy_id)
    mass = p.area * float(mesh.widths @ values)
    if abs(mass - base.initial_mass) > 1e-9 * max(abs(base.initial_mass), 1e-300):
        raise AdaptiveError(
            "ADAPTIVE_CONSERVATION", "Whole-run mass balance exceeds its bound", p.field_id
        )
    next_dt = min(p.policy.maximum_dt_ticks, dt_ticks * (2 if error < 0.25 else 1))
    state = AcceptedState(
        mesh,
        values,
        quiet,
        ages,
        base.tick + dt_ticks,
        base.step + 1,
        epoch,
        next_dt,
        rejected,
        solved,
        visits,
        transferred,
        base.initial_mass,
    )
    decisions.append(
        StepDecision(
            state.tick,
            state.step,
            epoch,
            len(mesh.cells),
            eta,
            error,
            dt_ticks,
            True,
            len(change.refined) if change else 0,
            len(change.coarsened) if change else 0,
            solved,
            state.work,
            spatial_evaluated,
        )
    )
    return Transition(state, tuple(decisions), change)
