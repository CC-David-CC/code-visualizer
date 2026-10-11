"""Bounded coupled numerical participant used by the host-owned gas backend.

An advanced native candidate is discarded on any admission failure. Only a
successful five-component correction replaces the immutable accepted boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from code_visualizer.extensions.fields.records import scalar
from code_visualizer.extensions.hybrid_gas.continuum import Wall, advance_window
from code_visualizer.extensions.hybrid_gas.coupling import CoupledStep, Slab, correct
from code_visualizer.extensions.hybrid_gas.interface import (
    ExchangeWindow,
    Interface,
    ReservoirState,
)
from code_visualizer.extensions.hybrid_gas.model_transfer import Activation, activate
from code_visualizer.extensions.hybrid_gas.particle import (
    InitialGasCell,
    ParticleBox,
    ParticleDefinition,
    ParticleWindow,
    coalesce_cells,
    transfers,
)
from code_visualizer.extensions.hybrid_gas.thermodynamics import GasLaw
from code_visualizer.extensions.hybrid_gas.units import quantity

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class CoupledWindow:
    accepted: CoupledStep
    particle: ParticleWindow
    input_row: NDArray[np.float64]
    continuum_substeps: int


def particle_definition(
    law: GasLaw,
    slab: Slab,
    values: NDArray[np.float64],
    faces: tuple[Interface, Interface],
    *,
    seed: int,
    fnum: float,
    quantum: float,
    collision_cells: int,
    start_tick: int = 0,
    maximum_steps: int = 400000,
    maximum_particles: int = 20000,
) -> ParticleDefinition:
    w = law.primitive(values)
    temperature = law.temperature(w)
    spacing = slab.grid.spacing
    cells = tuple(
        InitialGasCell(
            i * spacing,
            (i + 1) * spacing,
            float(w[i, 0] / law.species_mass),
            float(temperature[i]),
            (float(w[i, 1]), float(w[i, 2]), float(w[i, 3])),
        )
        for i in range(slab.first_cell, slab.stop_cell)
    )
    return ParticleDefinition(
        law,
        seed,
        cells[0].low,
        cells[-1].high,
        slab.grid.area,
        collision_cells,
        fnum,
        quantum,
        coalesce_cells(cells),
        "reservoir",
        start_tick=start_tick,
        maximum_steps=maximum_steps,
        maximum_particles=maximum_particles,
        interfaces=faces,
    )


def reservoir_states(
    law: GasLaw,
    slab: Slab,
    values: NDArray[np.float64],
    faces: tuple[Interface, Interface],
    first_tick: int,
    last_tick: int,
    quantum: float,
) -> tuple[ReservoirState, ReservoirState]:
    w = law.primitive(values)
    temperature = law.temperature(w)
    result = []
    for face, index in zip(faces, (slab.first_cell - 1, slab.stop_cell), strict=True):
        result.append(
            ReservoirState(
                ExchangeWindow(face, first_tick, last_tick, quantity(quantum, "second")),
                quantity(float(w[index, 0]), "kilogram_per_cubic_meter"),
                quantity(float(temperature[index]), "kelvin"),
                (
                    quantity(float(w[index, 1]), "meter_per_second"),
                    quantity(float(w[index, 2]), "meter_per_second"),
                    quantity(float(w[index, 3]), "meter_per_second"),
                ),
            )
        )
    return result[0], result[1]


class CoupledParticipant:
    """Numerical state inside one existing worker, not a process/session owner."""

    def __init__(
        self,
        slab: Slab,
        initial: NDArray[np.float64],
        definition: ParticleDefinition,
        faces: tuple[Interface, Interface],
        walls: tuple[Wall, Wall],
    ) -> None:
        self.slab, self.definition, self.faces, self.walls = slab, definition, faces, walls
        self.box = ParticleBox(definition)
        try:
            self.activation: Activation = activate(definition.law, slab, initial, self.box, faces)
        except BaseException:
            self.box.close()
            raise
        self.values = self.activation.after
        self.closed = False

    def advance(self, steps: int) -> CoupledWindow:
        import numpy as np

        if self.closed:
            raise ValueError("GAS_NATIVE_DISCARDED: reconstruct the accepted boundary before retry")
        d, box, slab = self.definition, self.box, self.slab
        try:
            states = reservoir_states(
                d.law, slab, self.values, self.faces, box.tick, box.tick + steps, d.time_step
            )
            provisional, substeps = advance_window(
                d.law, slab.grid, self.values, steps * d.time_step, self.walls
            )
            window = box.advance(steps, slab.cells, states)
            windows = (states[0].window, states[1].window)
            accepted = correct(
                d.law,
                slab,
                self.values,
                provisional,
                window.moments[:, 1:6] / slab.grid.volume,
                windows,
                transfers(window, windows),
            )
            row = np.array(
                [
                    window.first_tick,
                    window.last_tick,
                    *(
                        scalar(q, "Reservoir input")
                        for state in states
                        for q in (state.density, state.temperature, *state.velocity)
                    ),
                ],
                dtype=np.float64,
            )
            row.setflags(write=False)
            self.values = accepted.values
            return CoupledWindow(accepted, window, row, substeps)
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        self.box.close()
        self.closed = True

    def __enter__(self) -> CoupledParticipant:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
