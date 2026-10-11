"""One bounded numerical state machine inside the existing computation worker.

No worker/process, Git operation, authored mutation or publication authority is
created here. A fresh instance can reconstruct the exact accepted prefix; a
failed advanced native candidate is never reused.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from code_visualizer.extensions.hybrid_gas.continuum import advance_window, shear_stress
from code_visualizer.extensions.hybrid_gas.coupling import conservation_scale
from code_visualizer.extensions.hybrid_gas.model_transfer import (
    Activation,
    CoarseReturn,
    return_to_continuum,
)
from code_visualizer.extensions.hybrid_gas.participant import (
    CoupledParticipant,
    particle_definition,
)
from code_visualizer.extensions.hybrid_gas.particle import (
    InitialGasCell,
    ParticleBox,
    ParticleDefinition,
    coalesce_cells,
)
from code_visualizer.extensions.hybrid_gas.policy import ModelDecision, ModelState, decide
from code_visualizer.extensions.hybrid_gas.problem import GasError, GasProblem
from code_visualizer.extensions.hybrid_gas.thermodynamics import GasLaw
from code_visualizer.extensions.hybrid_gas.validity import Regime, admit, assess

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class GasState:
    tick: int
    windows: int
    model: ModelState
    values: NDArray[np.float64]
    wall_total: NDArray[np.float64]
    maximum_residual: NDArray[np.float64]
    statistics_sum: NDArray[np.float64]
    moments_sum: NDArray[np.float64]
    observation_sum: NDArray[np.float64]
    observation_flux: NDArray[np.float64]
    means: tuple[NDArray[np.float64], ...]
    moment_blocks: tuple[NDArray[np.float64], ...]
    observations: tuple[NDArray[np.float64], ...]
    particle_steps: int
    continuum_unknowns: int
    observation_shear: float = 0.0


@dataclass(frozen=True, slots=True)
class GasAdvance:
    before: GasState
    after: GasState
    input_row: NDArray[np.float64] | None
    decision: ModelDecision | None
    transfer: Activation | CoarseReturn | None
    regime: Regime | None


def readonly(values: NDArray[np.float64]) -> NDArray[np.float64]:
    values.setflags(write=False)
    return values


def observables(
    law: GasLaw,
    mean_values: NDArray[np.float64],
    wall_flux: NDArray[np.float64],
    duration: float,
    bulk_shear_integral: float,
) -> NDArray[np.float64]:
    """Thirteen primary mean-flow observables and two supplementary wall stresses."""
    import numpy as np

    if len(mean_values) % 8:
        raise ValueError("GAS_PROFILE_SUPPORT: eight equal physical profile bins required")
    averages = mean_values.reshape(8, -1, 5).mean(axis=1)
    w = law.primitive(averages)
    overall = law.primitive(mean_values.mean(axis=0)[None, :])[0]
    temperature = law.temperature(law.primitive(mean_values))
    mean_temperature = float(np.average(temperature, weights=mean_values[:, 0]))
    return readonly(
        np.r_[
            w[:, 1],
            bulk_shear_integral / duration,
            overall[0],
            mean_temperature,
            overall[2:4],
            -wall_flux[:, 1] / duration,
        ]
    )


class GasRuntime:
    def __init__(self, problem: GasProblem, law: GasLaw, source: str, law_digest: str) -> None:
        import numpy as np

        self.problem, self.law = problem, law
        self.faces = problem.faces(source, law_digest, law)
        self.coupled: CoupledParticipant | None = None
        self.full: ParticleBox | None = None
        self.closed = False
        self.initial_transfer: Activation | None = None
        q = problem.initial_values(law)
        p = problem.policy
        regime = self._regime(q)
        self.initial_regime = regime
        admit(regime, particle=p.mode != "continuum")
        self.initial_values = q
        initial_model = ModelState()
        self.initial_decision: ModelDecision | None = None
        if p.mode == "adaptive":
            self.initial_decision = decide(
                p.model, initial_model, 0, regime.gradient_knudsen, return_ready=False
            )
            initial_model = self.initial_decision.after
        elif p.mode in ("fixed", "particle"):
            initial_model = ModelState(True, 0, 0, 1, 0)
        try:
            if p.mode == "particle":
                self.full = self._full(q)
                q = self.full.conserved(problem.grid.cells)
            elif initial_model.particle:
                self.coupled = self._activate(q, 0, 0)
                self.initial_transfer = self.coupled.activation
                q = self.coupled.values
            self.initial_total = readonly(q.sum(axis=0) * problem.grid.volume)
            self.state = GasState(
                0,
                0,
                initial_model,
                q,
                readonly(np.zeros(5)),
                readonly(np.zeros(5)),
                readonly(np.zeros_like(q)),
                readonly(np.zeros((problem.slab.cells, 13))),
                readonly(np.zeros_like(q)),
                readonly(np.zeros((2, 5))),
                (),
                (),
                (),
                0,
                0,
            )
        except BaseException:
            self.close()
            raise

    def _regime(self, values: NDArray[np.float64]) -> Regime:
        p, law = self.problem, self.law
        # Mach is measured in the declared mean translating wall frame, so a
        # uniform tangential change of laboratory velocity changes no validity.
        frame = (
            (p.walls[0].stream_velocity + p.walls[1].stream_velocity) / 2,
            0.0,
            (p.walls[0].span_velocity + p.walls[1].span_velocity) / 2,
        )
        return assess(
            law,
            p.grid,
            values,
            p.policy.quantum,
            p.grid.length / p.policy.collision_cells,
            reference_velocity=frame,
        )

    def _activate(self, values: NDArray[np.float64], tick: int, switch: int) -> CoupledParticipant:
        p = self.problem
        native_cells = round(p.slab.cells / p.grid.cells * p.policy.collision_cells)
        # New activations are separate deterministic stream epochs. They never
        # substitute for exact reconstruction of an already consumed stream.
        seed = (p.policy.seed - 1 + switch * 104729) % ((1 << 31) - 1) + 1
        definition = particle_definition(
            self.law,
            p.slab,
            values,
            self.faces,
            seed=seed,
            fnum=p.fnum,
            quantum=p.policy.quantum,
            collision_cells=native_cells,
            start_tick=tick,
            maximum_steps=p.policy.final_tick - tick,
            maximum_particles=p.policy.maximum_particles,
        )
        return CoupledParticipant(p.slab, values, definition, self.faces, p.walls)

    def _full(self, values: NDArray[np.float64]) -> ParticleBox:
        p, law = self.problem, self.law
        if p.grid.cells > 128:
            raise GasError(
                "GAS_INITIALIZATION_BUDGET",
                "Native initialization has at most 128 cells",
                p.policy_id,
            )
        w = law.primitive(values)
        temperature = law.temperature(w)
        cells = tuple(
            InitialGasCell(
                i * p.grid.spacing,
                (i + 1) * p.grid.spacing,
                float(w[i, 0] / law.species_mass),
                float(temperature[i]),
                (float(w[i, 1]), float(w[i, 2]), float(w[i, 3])),
            )
            for i in range(p.grid.cells)
        )
        return ParticleBox(
            ParticleDefinition(
                law,
                p.policy.seed,
                0.0,
                p.grid.length,
                p.grid.area,
                p.policy.collision_cells,
                p.fnum,
                p.policy.quantum,
                coalesce_cells(cells),
                "walls",
                walls=p.walls,
                maximum_steps=p.policy.final_tick,
                maximum_particles=p.policy.maximum_particles,
            )
        )

    @property
    def native(self) -> ParticleBox | None:
        return self.coupled.box if self.coupled else self.full

    def advance(self) -> GasAdvance:
        if self.closed:
            raise GasError(
                "GAS_NATIVE_DISCARDED",
                "Reconstruct the accepted state before retry",
                self.problem.policy_id,
            )
        try:
            return self._advance()
        except BaseException:
            self.close()
            raise

    def _advance(self) -> GasAdvance:
        import numpy as np

        p, law, base = self.problem, self.law, self.state
        policy, grid = p.policy, p.grid
        steps = policy.window_ticks
        tick = base.tick + steps
        if tick > policy.final_tick:
            raise GasError(
                "GAS_STEP_BUDGET", "The finite computation horizon is exhausted", p.policy_id
            )
        row = None
        particle_moments = None
        particle_steps, continuum_work = base.particle_steps, base.continuum_unknowns
        if self.coupled:
            candidate = self.coupled.advance(steps)
            q, outer = candidate.accepted.values, candidate.accepted.outer_integrated_flux
            row, particle_moments = candidate.input_row, candidate.particle.moments
            particle_steps += steps
            continuum_work += 2 * candidate.continuum_substeps * grid.cells
            shear = shear_stress(law, grid, q)
            shear[p.slab.first_cell : p.slab.stop_cell] = (
                -(
                    particle_moments[:, 7]
                    - particle_moments[:, 2] * particle_moments[:, 3] / particle_moments[:, 1]
                )
                / grid.volume
            )
            bulk_shear = float(shear.mean())
        elif self.full:
            native = self.full.advance(steps, grid.cells)
            q = readonly(native.moments[:, 1:6].copy() / grid.volume)
            outer = native.outgoing[:, 1:] / grid.area * np.array([-1, 1])[:, None]
            particle_moments = native.moments[p.slab.first_cell : p.slab.stop_cell]
            particle_steps += steps
            bulk_shear = -float(
                np.sum(
                    native.moments[:, 7]
                    - native.moments[:, 2] * native.moments[:, 3] / native.moments[:, 1]
                )
            ) / (grid.area * grid.length)
        else:
            coarse, substeps = advance_window(
                law, grid, base.values, steps * policy.quantum, p.walls
            )
            q, outer = coarse.values, coarse.integrated_flux[[0, -1]]
            continuum_work += 2 * substeps * grid.cells
            bulk_shear = float(shear_stress(law, grid, q).mean())
        law.primitive(q)
        wall = base.wall_total + (outer[0] - outer[1]) * grid.area
        residual = (q.sum(axis=0) * grid.volume - self.initial_total - wall) / conservation_scale(
            law, self.initial_total
        )
        if np.any(np.abs(residual) > 1e-10):
            raise GasError(
                "GAS_CONSERVATION",
                "The whole-run five-component ledger does not close",
                p.problem_id,
            )
        maximum = np.maximum(base.maximum_residual, np.abs(residual))
        statistics_sum = base.statistics_sum + steps * q
        moments_sum = base.moments_sum.copy()
        if particle_moments is not None:
            moments_sum += steps * particle_moments
        observation_sum = base.observation_sum.copy()
        observation_flux = base.observation_flux.copy()
        observation_shear = base.observation_shear
        if tick > policy.warmup_ticks:
            observation_sum += steps * q
            observation_flux += outer
            observation_shear += bulk_shear * steps * policy.quantum
        means, moment_blocks, observations = base.means, base.moment_blocks, base.observations
        decision: ModelDecision | None = None
        transfer: Activation | CoarseReturn | None = None
        regime: Regime | None = None
        model = base.model
        if tick % policy.statistics_ticks == 0:
            mean = readonly(statistics_sum / policy.statistics_ticks)
            means = (*means, mean)
            regime = self._regime(mean)
            admit(regime, particle=model.particle)
            if particle_moments is not None and tick > policy.warmup_ticks:
                moment_blocks = (*moment_blocks, readonly(moments_sum / policy.statistics_ticks))
            statistics_sum, moments_sum = np.zeros_like(q), np.zeros_like(moments_sum)
            if policy.mode == "adaptive":
                sensor_values = q if not model.particle else mean
                # Return uses the accumulated post-warmup mean, retaining raw
                # block moments for uncertainty, not one noisy cell sample.
                post = means[policy.warmup_ticks // policy.statistics_ticks :]
                if model.particle and post:
                    sensor_values = np.mean(post, axis=0)
                sensor = self._regime(sensor_values).gradient_knudsen
                ready = False
                if (
                    self.coupled
                    and len(moment_blocks) >= 20
                    and sensor < policy.model.return_threshold
                    and tick - model.changed_tick >= policy.model.minimum_dwell_ticks
                ):
                    try:
                        transfer = return_to_continuum(
                            law, p.slab, q, self.coupled.box, self.faces, np.stack(moment_blocks)
                        )
                        ready = True
                    except ValueError as exc:
                        if not str(exc).startswith(
                            ("GAS_RETURN_STATISTICS:", "GAS_RETURN_CONSTITUTIVE:")
                        ):
                            raise
                decision = decide(policy.model, model, tick, sensor, return_ready=ready)
                if decision.action == "reject":
                    raise GasError(
                        "GAS_SWITCH_BUDGET",
                        "The declared model-switch budget is exhausted",
                        p.policy_id,
                    )
                model = decision.after
                if decision.action == "activate":
                    self.coupled = self._activate(q, tick, model.switches - 1)
                    transfer = self.coupled.activation
                    q = self.coupled.values
                    moment_blocks = ()
                elif decision.action == "return":
                    assert isinstance(transfer, CoarseReturn) and self.coupled is not None
                    q = transfer.after
                    self.coupled.close()
                    self.coupled = None
                else:
                    transfer = None
        if tick > policy.warmup_ticks and (tick - policy.warmup_ticks) % policy.block_ticks == 0:
            observations = (
                *observations,
                observables(
                    law,
                    observation_sum / policy.block_ticks,
                    observation_flux,
                    policy.block_ticks * policy.quantum,
                    observation_shear,
                ),
            )
            observation_sum, observation_flux = np.zeros_like(q), np.zeros((2, 5))
            observation_shear = 0.0
        if len(means) > 512 or len(moment_blocks) > 256 or len(observations) > 256:
            raise GasError(
                "GAS_STATISTICS_BUDGET", "The declared block storage is exhausted", p.policy_id
            )
        after = GasState(
            tick,
            base.windows + 1,
            model,
            q,
            readonly(wall),
            readonly(maximum),
            readonly(statistics_sum),
            readonly(moments_sum),
            readonly(observation_sum),
            readonly(observation_flux),
            means,
            moment_blocks,
            observations,
            particle_steps,
            continuum_work,
            observation_shear,
        )
        self.state = after
        return GasAdvance(base, after, row, decision, transfer, regime)

    def close(self) -> None:
        if self.coupled:
            self.coupled.close()
        if self.full:
            self.full.close()
        self.closed = True

    def __enter__(self) -> GasRuntime:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
