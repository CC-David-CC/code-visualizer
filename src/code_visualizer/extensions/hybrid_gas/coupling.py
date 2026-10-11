"""Conservative replacement of provisional interface flux at one accepted window.

No particle algorithm lives here. The measured participant flux and actual
particle moments must balance before they can replace a continuum contribution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from code_visualizer.extensions.fields.records import scalar
from code_visualizer.extensions.hybrid_gas.continuum import GasGrid, GasStep
from code_visualizer.extensions.hybrid_gas.interface import ExchangeWindow, IntegratedFlux
from code_visualizer.extensions.hybrid_gas.thermodynamics import GasLaw, InvalidGasState

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class Slab:
    first_cell: int
    stop_cell: int
    grid: GasGrid

    def __post_init__(self) -> None:
        if (
            not isinstance(self.grid, GasGrid)
            or any(type(v) is not int for v in (self.first_cell, self.stop_cell))
            or not 0 < self.first_cell < self.stop_cell < self.grid.cells
        ):
            raise ValueError(
                "A particle slab requires disjoint interior cells and two continuum neighbors"
            )

    @property
    def cells(self) -> int:
        return self.stop_cell - self.first_cell


@dataclass(frozen=True, slots=True)
class CoupledStep:
    values: NDArray[np.float64]
    wall_transfer: NDArray[np.float64]
    interfaces: tuple[IntegratedFlux, IntegratedFlux]
    particle_residual: NDArray[np.float64]
    system_residual: NDArray[np.float64]
    outer_integrated_flux: NDArray[np.float64]


def conservation_scale(law: GasLaw, total: NDArray[np.float64]) -> NDArray[np.float64]:
    import numpy as np

    # Ratios of extensive conserved quantities have the same thermodynamic
    # meaning as ratios of densities. No division by a zero mean momentum.
    w = law.primitive(total[None, :])
    speed = float(np.sqrt(law.specific_gas_constant * law.temperature(w)[0]))
    return np.array((total[0], total[0] * speed, total[0] * speed, total[0] * speed, total[4]))


def correct(
    law: GasLaw,
    slab: Slab,
    base: NDArray[np.float64],
    provisional: GasStep,
    particle_after: NDArray[np.float64],
    windows: tuple[ExchangeWindow, ExchangeWindow],
    transfers: tuple[IntegratedFlux, IntegratedFlux],
) -> CoupledStep:
    import numpy as np

    grid = slab.grid
    if (
        provisional.law != law
        or provisional.grid != grid
        or not np.array_equal(provisional.base, base)
    ):
        raise InvalidGasState("Provisional gas step belongs to another immutable base, law or grid")
    law.primitive(base)
    law.primitive(provisional.values)
    law.primitive(particle_after)
    if (
        base.shape != (grid.cells, 5)
        or provisional.values.shape != base.shape
        or particle_after.shape != (slab.cells, 5)
        or provisional.integrated_flux.shape != (grid.cells + 1, 5)
    ):
        raise InvalidGasState("Coupled state belongs to another owned support")
    if len(windows) != 2 or len(transfers) != 2:
        raise ValueError("A slab requires exactly two interface packets")
    low, high = windows
    if (
        low.interface.outward_normal != -1
        or high.interface.outward_normal != 1
        or low.interface.face_id == high.interface.face_id
        or (low.first_tick, low.last_tick, low.quantum)
        != (high.first_tick, high.last_tick, high.quantum)
        or any(scalar(w.interface.area, "Area") != grid.area for w in windows)
        or (low.last_tick - low.first_tick) * scalar(low.quantum, "Quantum") != provisional.duration
    ):
        raise ValueError("GAS_INTERFACE_MISMATCH: slab orientation, area or window differs")
    for attribute in (
        "source_digest",
        "law_digest",
        "policy_id",
        "region_id",
        "frame_id",
        "axis_id",
        "units",
        "particle_mass",
    ):
        if getattr(low.interface, attribute) != getattr(high.interface, attribute):
            raise ValueError("GAS_INTERFACE_MISMATCH: slab faces have incompatible meanings")
    incoming_low, outgoing_high = (
        packet.admit(window) for packet, window in zip(transfers, windows, strict=True)
    )
    before_particle = base[slab.first_cell : slab.stop_cell].sum(axis=0) * grid.volume
    after_particle = particle_after.sum(axis=0) * grid.volume
    particle_residual = (
        after_particle - before_particle - incoming_low + outgoing_high
    ) / conservation_scale(law, before_particle)
    if np.any(np.abs(particle_residual) > 1e-10):
        raise InvalidGasState(
            "Measured particle transfers do not balance actual owned particle moments"
        )
    candidate = provisional.values.copy()
    # Each neighboring continuum cell loses exactly what its particle face
    # receives. Remove the provisional flux before inserting the measured one.
    candidate[slab.first_cell - 1] += (
        provisional.integrated_flux[slab.first_cell] * grid.area - incoming_low
    ) / grid.volume
    candidate[slab.stop_cell] += (
        outgoing_high - provisional.integrated_flux[slab.stop_cell] * grid.area
    ) / grid.volume
    candidate[slab.first_cell : slab.stop_cell] = particle_after
    law.primitive(candidate)
    initial = base.sum(axis=0) * grid.volume
    wall = (provisional.integrated_flux[0] - provisional.integrated_flux[-1]) * grid.area
    system_residual = (candidate.sum(axis=0) * grid.volume - initial - wall) / conservation_scale(
        law, initial
    )
    if np.any(np.abs(system_residual) > 1e-10):
        raise InvalidGasState("Coupled mass, momentum or energy ledger does not close")
    for value in (candidate, wall, particle_residual, system_residual):
        value.setflags(write=False)
    outer = provisional.integrated_flux[[0, -1]].copy()
    outer.setflags(write=False)
    return CoupledStep(candidate, wall, transfers, particle_residual, system_residual, outer)
