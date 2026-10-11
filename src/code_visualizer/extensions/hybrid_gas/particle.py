"""The selected native gas participant; configuration is typed and disposable.

SPARTA owns particle creation, collisions, motion, wall scattering and reservoir
sampling. This adapter supplies validated state and observes actual transfers.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite, sqrt
from typing import TYPE_CHECKING

from code_visualizer.extensions.fields.records import scalar
from code_visualizer.extensions.hybrid_gas.continuum import Wall
from code_visualizer.extensions.hybrid_gas.interface import (
    ConservedAmount,
    ExchangeWindow,
    IntegratedFlux,
    Interface,
    ReservoirState,
)
from code_visualizer.extensions.hybrid_gas.native_api import NativeSparta
from code_visualizer.extensions.hybrid_gas.thermodynamics import GasLaw, InvalidGasState, positive

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

SPECIES_MASS = 6.63e-26
BOLTZMANN = 1.380649e-23


@dataclass(frozen=True, slots=True)
class InitialGasCell:
    low: float
    high: float
    number_density: float
    temperature: float
    velocity: tuple[float, float, float]

    def __post_init__(self) -> None:
        if (
            any(type(v) not in (int, float) or not isfinite(v) for v in (self.low, self.high))
            or self.low >= self.high
        ):
            raise ValueError("Initial gas cells require finite increasing coordinates")
        positive(self.number_density, "Initial number density")
        positive(self.temperature, "Initial temperature")
        if (
            type(self.velocity) is not tuple
            or len(self.velocity) != 3
            or any(type(v) not in (int, float) or not isfinite(v) for v in self.velocity)
        ):
            raise ValueError("Initial gas velocity requires three finite components")


def coalesce_cells(cells: tuple[InitialGasCell, ...]) -> tuple[InitialGasCell, ...]:
    """Equal adjacent initial meanings are one native sampling region.

    This preserves exact physical boundaries, without floating tolerance or
    averaging distinct states. Uniform gas is sampled once over its whole volume.
    """
    result: list[InitialGasCell] = []
    for cell in cells:
        if result and (
            result[-1].high,
            result[-1].number_density,
            result[-1].temperature,
            result[-1].velocity,
        ) == (cell.low, cell.number_density, cell.temperature, cell.velocity):
            result[-1] = replace(result[-1], high=cell.high)
        else:
            result.append(cell)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class ParticleDefinition:
    law: GasLaw
    seed: int
    low: float
    high: float
    area: float
    collision_cells: int
    fnum: float
    time_step: float
    initial: tuple[InitialGasCell, ...]
    boundary: str
    walls: tuple[Wall, ...] = ()
    start_tick: int = 0
    maximum_particles: int = 200000
    maximum_steps: int = 400000
    interfaces: tuple[Interface, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.law, GasLaw) or (
            self.law.species_mass,
            self.law.boltzmann,
            self.law.reference_temperature,
            self.law.viscosity_exponent,
            self.law.prandtl,
        ) != (SPECIES_MASS, BOLTZMANN, 273.15, 0.81, 2 / 3):
            raise ValueError(
                "GAS_SPECIES_UNSUPPORTED: the pinned native law is monatomic argon VSS"
            )
        if type(self.seed) is not int or not 1 <= self.seed < 1 << 31:
            raise ValueError("Native seed is outside its declared range")
        if type(self.collision_cells) is not int or not 1 <= self.collision_cells <= 512:
            raise ValueError("Native collision grid exceeds its bound")
        if type(self.start_tick) is not int or not 0 <= self.start_tick < 1 << 40:
            raise ValueError("Invalid initial native tick")
        if type(self.maximum_steps) is not int or not 1 <= self.maximum_steps <= 400000:
            raise ValueError("Native step budget exceeds 400000")
        if type(self.maximum_particles) is not int or not 100 <= self.maximum_particles <= 200000:
            raise ValueError("Native population budget exceeds 200000")
        for value, name in (
            (self.area, "Transverse area"),
            (self.fnum, "Particle weight"),
            (self.time_step, "Microscopic time step"),
        ):
            positive(value, name)
        if (
            type(self.initial) is not tuple
            or not 1 <= len(self.initial) <= 128
            or not all(isinstance(c, InitialGasCell) for c in self.initial)
        ):
            raise ValueError("Native initialization requires 1..128 typed owned cells")
        cursor = self.low
        for cell in self.initial:
            if cell.low != cursor:
                raise ValueError("Initial native cells have gaps, overlap or wrong ownership")
            cursor = cell.high
        if cursor != self.high:
            raise ValueError("Initial native cells do not cover the exact particle volume")
        if self.boundary not in ("periodic", "walls", "reservoir"):
            raise ValueError("Unsupported native boundary interpretation")
        if (
            type(self.interfaces) is not tuple
            or (self.boundary == "reservoir") != (len(self.interfaces) == 2)
            or (self.boundary != "reservoir" and self.interfaces)
        ):
            raise ValueError("Open native volumes require exactly two frozen interface definitions")
        for face, normal in zip(self.interfaces, (-1, 1), strict=False):
            if not isinstance(face, Interface) or (
                face.outward_normal,
                scalar(face.area, "Area"),
                scalar(face.particle_mass, "Particle mass"),
            ) != (normal, self.area, SPECIES_MASS * self.fnum):
                raise ValueError(
                    "GAS_INTERFACE_MISMATCH: native definition and interface "
                    "geometry or weight differ"
                )
        if (
            (self.boundary == "walls") != (len(self.walls) == 2)
            or (self.boundary != "walls" and self.walls)
            or not all(isinstance(wall, Wall) for wall in self.walls)
        ):
            raise ValueError("Native wall semantics require exactly two fixed diffuse walls")
        expected = sum(
            cell.number_density * (cell.high - cell.low) * self.area / self.fnum
            for cell in self.initial
        )
        if not 100 <= expected <= self.maximum_particles:
            raise ValueError("Initial native population is outside its declared budget")


@dataclass(frozen=True, slots=True)
class ParticleWindow:
    first_tick: int
    last_tick: int
    moments: NDArray[np.float64]
    incoming: NDArray[np.float64]
    outgoing: NDArray[np.float64]


class ParticleBox:
    def __init__(self, definition: ParticleDefinition) -> None:
        self.definition = definition
        self.tick = definition.start_tick
        self.native = NativeSparta()
        try:
            self._configure()
        except BaseException:
            self.native.close()
            raise

    def _configure(self) -> None:
        d, native = self.definition, self.native
        width = sqrt(d.area)
        flag = {"periodic": "p", "walls": "s", "reservoir": "o"}[d.boundary]
        commands = [
            f"seed {d.seed}",
            "dimension 3",
            f"boundary p {flag} p",
            f"create_box 0 {width:.17g} {d.low:.17g} {d.high:.17g} 0 {width:.17g}",
            f"create_grid 1 {d.collision_cells} 1",
            f'species "{native.installation.species.as_posix()}" Ar',
            "mixture gas Ar temp 273.15",
            f"global nrho {d.initial[0].number_density:.17g} fnum {d.fnum:.17g}",
            f'collide vss gas "{native.installation.collision.as_posix()}"',
        ]
        if d.boundary == "walls":
            for name, face, wall in zip(("cold", "hot"), ("ylo", "yhi"), d.walls, strict=True):
                commands += [
                    f"surf_collide {name} diffuse {wall.temperature:.17g} 1.0 "
                    f"translate {wall.stream_velocity:.17g} 0 {wall.span_velocity:.17g}",
                    f"bound_modify {face} collide {name}",
                ]
        for i, cell in enumerate(d.initial):
            velocity = " ".join(f"{v:.17g}" for v in cell.velocity)
            commands.append(
                f"mixture initial{i} Ar nrho {cell.number_density:.17g} "
                f"temp {cell.temperature:.17g} vstream {velocity}"
            )
            if len(d.initial) == 1:
                commands.append(f"create_particles initial{i} n 0 twopass")
            else:
                commands += [
                    f"region initial_region{i} block 0 {width:.17g} "
                    f"{cell.low:.17g} {cell.high:.17g} 0 {width:.17g}",
                    f"create_particles initial{i} n 0 region initial_region{i} twopass",
                ]
        commands += [f"timestep {d.time_step:.17g}", f"reset_timestep {d.start_tick}"]
        if d.boundary == "reservoir":
            for name, face, cell in zip(
                ("low", "high"), ("ylo", "yhi"), (d.initial[0], d.initial[-1]), strict=True
            ):
                velocity = " ".join(f"{v:.17g}" for v in cell.velocity)
                commands += [
                    f"mixture {name} Ar nrho {cell.number_density:.17g} "
                    f"temp {cell.temperature:.17g} vstream {velocity}",
                    f"fix {name} cv/emit/face {name} {face}",
                ]
        commands += [
            "compute cross boundary gas n mflux shx press shz etot",
            "fix ledger ave/time 1 1 1 c_cross[*] mode vector",
            "stats 1000000",
            "run 0",
        ]
        for command in commands:
            native._command(command)
        self._population()

    def _population(self) -> None:
        if not 1 <= self.native.particle_count() <= self.definition.maximum_particles:
            raise InvalidGasState("GAS_PARTICLE_BUDGET: native population exhausted its bound")

    def moments(self, bins: int) -> NDArray[np.float64]:
        return self.native.moments(self.definition.low, self.definition.high, bins)

    def conserved(self, bins: int) -> NDArray[np.float64]:
        result = self.moments(bins)[:, 1:6].copy()
        result /= (self.definition.high - self.definition.low) * self.definition.area / bins
        self.definition.law.primitive(result)
        result.setflags(write=False)
        return result

    def advance(
        self, steps: int, bins: int, states: tuple[ReservoirState, ...] = ()
    ) -> ParticleWindow:

        d = self.definition
        if (
            type(steps) is not int
            or not 1 <= steps <= 64
            or self.tick - d.start_tick + steps > d.maximum_steps
        ):
            raise InvalidGasState(
                "GAS_STEP_BUDGET: bounded microscopic advance would exceed its limit"
            )
        if (d.boundary == "reservoir") != (len(states) == 2) or (
            d.boundary != "reservoir" and states
        ):
            raise ValueError("Only an open particle volume accepts two reservoir states")
        # Preflight both faces before changing either native reservoir.
        for i, state in enumerate(states):
            w = state.window
            if w.interface != d.interfaces[i] or (
                w.first_tick,
                w.last_tick,
                scalar(w.quantum, "Quantum"),
            ) != (self.tick, self.tick + steps, d.time_step):
                raise ValueError(
                    "GAS_INTERFACE_MISMATCH: native reservoir belongs to a "
                    "different window, face or weight"
                )
        return self._advance(steps, bins, states)

    def _advance(self, steps: int, bins: int, states: tuple[ReservoirState, ...]) -> ParticleWindow:
        try:
            return self._advance_native(steps, bins, states)
        except BaseException:
            # An advanced rejected native candidate has no in-place retry.
            # Its accepted boundary is reconstructed from the retained inputs.
            self.close()
            raise

    def _advance_native(
        self, steps: int, bins: int, states: tuple[ReservoirState, ...]
    ) -> ParticleWindow:
        import numpy as np

        d = self.definition
        for name, state in zip(("low", "high"), states, strict=False):
            self.native._reservoir(
                name,
                scalar(state.density, "Density") / SPECIES_MASS,
                scalar(state.temperature, "Temperature"),
                (
                    scalar(state.velocity[0], "Velocity"),
                    scalar(state.velocity[1], "Velocity"),
                    scalar(state.velocity[2], "Velocity"),
                ),
            )
        incoming, outgoing = np.zeros((2, 6)), np.zeros((2, 6))
        for _ in range(steps):
            self.native._command("run 1 pre no post no")
            if d.boundary == "reservoir":
                incoming += np.array(
                    [self.native._vector(face, 6, fix=True) for face in ("low", "high")]
                )
            crossed = self.native._boundary()[[2, 3]].copy()
            crossed[:, 1:] *= d.time_step * d.area
            crossed[:, 3] *= [-1, 1]
            outgoing += crossed
            self._population()
        moments = self.moments(bins)
        first = self.tick
        self.tick += steps
        for value in (incoming, outgoing):
            value.setflags(write=False)
        return ParticleWindow(first, self.tick, moments, incoming, outgoing)

    def close(self) -> None:
        self.native.close()


def transfers(
    result: ParticleWindow, windows: tuple[ExchangeWindow, ExchangeWindow]
) -> tuple[IntegratedFlux, IntegratedFlux]:
    packets = []
    for i, window in enumerate(windows):
        if (window.first_tick, window.last_tick) != (result.first_tick, result.last_tick):
            raise ValueError(
                "GAS_INTERFACE_MISMATCH: native measurements belong to another interval"
            )
        rows = (result.incoming[i], result.outgoing[i])
        values = []
        counts = []
        for row in rows:
            count = int(row[0])
            if count != row[0]:
                raise ValueError("Microscopic crossing counts must be exact integers")
            counts.append(count)
            values.append(
                ConservedAmount(
                    float(row[1]), (float(row[2]), float(row[3]), float(row[4])), float(row[5])
                )
            )
        packets.append(IntegratedFlux(window, values[0], values[1], counts[0], counts[1]))
    return packets[0], packets[1]
