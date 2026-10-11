"""Explicit conservative initialization of a particle-owned slab.

Coarse moments do not specify a unique microstate. The native conditional
ensemble is observed, its realized difference recorded, and a declared uniform
correction of the exterior reservoir preserves all five global integrals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from code_visualizer.extensions.hybrid_gas.coupling import Slab, conservation_scale
from code_visualizer.extensions.hybrid_gas.interface import Interface
from code_visualizer.extensions.hybrid_gas.particle import ParticleBox
from code_visualizer.extensions.hybrid_gas.statistics import Estimate, estimate
from code_visualizer.extensions.hybrid_gas.thermodynamics import GasLaw, InvalidGasState

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class Activation:
    before: NDArray[np.float64]
    after: NDArray[np.float64]
    realized_particle_moments: NDArray[np.float64]
    realized_difference: NDArray[np.float64]
    exterior_density_correction: NDArray[np.float64]
    normalized_residual: NDArray[np.float64]


def activate(
    law: GasLaw,
    slab: Slab,
    base: NDArray[np.float64],
    box: ParticleBox,
    interfaces: tuple[Interface, Interface],
) -> Activation:
    import numpy as np

    grid, d = slab.grid, box.definition
    if (
        d.law != law
        or d.boundary != "reservoir"
        or d.interfaces != interfaces
        or d.area != grid.area
        or d.low != slab.first_cell * grid.spacing
        or d.high != slab.stop_cell * grid.spacing
        or box.tick != d.start_tick
    ):
        raise ValueError(
            "GAS_TRANSFER_INCOMPATIBLE: initialization requires the exact law, "
            "interfaces and owned volume"
        )
    law.primitive(base)
    if base.shape != (grid.cells, 5):
        raise ValueError("GAS_TRANSFER_INCOMPATIBLE: coarse state has a different support")
    before = base.copy()
    moments = box.moments(slab.cells)
    particle = moments[:, 1:6] / grid.volume
    law.primitive(particle)
    coarse_total = before[slab.first_cell : slab.stop_cell].sum(axis=0) * grid.volume
    realized = moments[:, 1:6].sum(axis=0)
    difference = realized - coarse_total
    if np.any(np.abs(difference) / conservation_scale(law, coarse_total) > 0.1):
        raise InvalidGasState(
            "GAS_INITIALIZATION_FIDELITY: realized ensemble exceeds the declared 10% integral bound"
        )
    exterior_volume = (grid.cells - slab.cells) * grid.volume
    correction = -difference / exterior_volume
    after = before + correction
    after[slab.first_cell : slab.stop_cell] = particle
    law.primitive(after)
    total = before.sum(axis=0) * grid.volume
    residual = (after.sum(axis=0) * grid.volume - total) / conservation_scale(law, total)
    if np.any(np.abs(residual) > 1e-10):
        raise InvalidGasState(
            "GAS_TRANSFER_CONSERVATION: initialization reservoir correction does not close"
        )
    for value in (before, after, difference, correction, residual):
        value.setflags(write=False)
    return Activation(before, after, moments, difference, correction, residual)


@dataclass(frozen=True, slots=True)
class CoarseReturn:
    before: NDArray[np.float64]
    after: NDArray[np.float64]
    particle_moments: NDArray[np.float64]
    block_moments: NDArray[np.float64]
    uncertainty: Estimate
    normalized_residual: NDArray[np.float64]


def moment_observables(
    law: GasLaw, moments: NDArray[np.float64], volume: float
) -> NDArray[np.float64]:
    """Dimensionless density/velocity/temperature/stress/heat block observables.

    Temperature follows restriction of total energy and momentum. Stress and
    heat retain the unresolved second/third moments, not averaged temperatures.
    """
    import numpy as np

    if moments.ndim != 2 or moments.shape[1] != 13 or not np.isfinite(moments).all():
        raise ValueError("GAS_RETURN_MOMENTS: expected actual thirteen-component particle moments")
    q = moments[:, 1:6] / volume
    w = law.primitive(q)
    density, velocity, pressure = w[:, 0], w[:, 1:4], w[:, 4]
    second = moments[:, 6:12] / volume
    # Order: xx, xy, xz, yy, yz, zz. Central stress includes equilibrium pI.
    products = np.column_stack(
        (
            velocity[:, 0] ** 2,
            velocity[:, 0] * velocity[:, 1],
            velocity[:, 0] * velocity[:, 2],
            velocity[:, 1] ** 2,
            velocity[:, 1] * velocity[:, 2],
            velocity[:, 2] ** 2,
        )
    )
    central = second - density[:, None] * products
    stress = central.copy()
    stress[:, (0, 3, 5)] -= pressure[:, None]
    # Total-energy flux = (E+p)u_y + u_i*pi_iy + conductive heat.
    heat = moments[:, 12] / volume - q[:, 4] * velocity[:, 1]
    heat -= np.sum(velocity * central[:, (1, 3, 4)], axis=1)
    speed = (law.specific_gas_constant * law.reference_temperature) ** 0.5
    reference_density = 7.07043e22 * law.species_mass
    return np.column_stack(
        (
            density / reference_density,
            velocity / speed,
            law.temperature(w) / law.reference_temperature,
            stress / pressure[:, None],
            heat / (pressure * speed),
        )
    )


def return_to_continuum(
    law: GasLaw,
    slab: Slab,
    base: NDArray[np.float64],
    box: ParticleBox,
    interfaces: tuple[Interface, Interface],
    block_moments: NDArray[np.float64],
    *,
    minimum_effective: float = 20,
    precision: float = 0.05,
) -> CoarseReturn:
    import numpy as np

    grid, d = slab.grid, box.definition
    if (
        d.law != law
        or d.boundary != "reservoir"
        or d.interfaces != interfaces
        or d.area != grid.area
        or d.low != slab.first_cell * grid.spacing
        or d.high != slab.stop_cell * grid.spacing
        or base.shape != (grid.cells, 5)
        or block_moments.ndim != 3
        or block_moments.shape[1:] != (slab.cells, 13)
        or not 20 <= len(block_moments) <= 256
        or not 20 <= minimum_effective <= 256
        or not 0 < precision <= 0.05
    ):
        raise ValueError(
            "GAS_RETURN_INCOMPATIBLE: exact support/law and bounded statistics required"
        )
    law.primitive(base)
    values = np.stack([moment_observables(law, row, grid.volume).ravel() for row in block_moments])
    uncertainty = estimate(values)
    if np.any(uncertainty.effective_blocks < minimum_effective) or np.any(
        uncertainty.half_width > precision
    ):
        raise InvalidGasState("GAS_RETURN_STATISTICS: insufficient effective blocks or precision")
    average = uncertainty.mean.reshape(slab.cells, 12)
    half = uncertainty.half_width.reshape(slab.cells, 12)
    # Return is qualified only near local equilibrium. The permitted unresolved
    # stress/heat band is pressure / pressure*thermal-speed, not a shear-fit test.
    if np.any(np.abs(average[:, 5:]) + half[:, 5:] > 0.05):
        raise InvalidGasState(
            "GAS_RETURN_CONSTITUTIVE: unresolved stress/heat exceeds coarse closure"
        )
    moments = box.moments(slab.cells)
    actual = moments[:, 1:6] / grid.volume
    # An accepted coupled boundary already owns precisely these moments.
    scales = conservation_scale(law, actual.sum(axis=0) * grid.volume)
    difference = (actual - base[slab.first_cell : slab.stop_cell]) * grid.volume
    if np.any(np.abs(difference) / scales > 1e-10):
        raise InvalidGasState("GAS_RETURN_STATE: particle state is not the accepted owned state")
    before = base.copy()
    after = before.copy()
    after[slab.first_cell : slab.stop_cell] = actual
    law.primitive(after)
    residual = (after - base).sum(axis=0) * grid.volume / scales
    retained = block_moments.copy()
    for value in (before, after, retained, residual):
        value.setflags(write=False)
    return CoarseReturn(before, after, moments, retained, uncertainty, residual)
