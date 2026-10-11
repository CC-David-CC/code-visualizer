"""The declared VSS mean-flow envelope is physics owned by this extension."""

from __future__ import annotations

from dataclasses import dataclass
from math import pi, sqrt
from typing import TYPE_CHECKING

from code_visualizer.extensions.hybrid_gas.continuum import GasGrid
from code_visualizer.extensions.hybrid_gas.thermodynamics import GasLaw, InvalidGasState

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class Regime:
    maximum_mach: float
    height_knudsen: float
    collision_time_ratio: float
    cell_to_path_ratio: float
    gradient_knudsen: float
    thermal_departure: float


def assess(
    law: GasLaw,
    grid: GasGrid,
    conserved: NDArray[np.float64],
    microscopic_step: float,
    collision_spacing: float,
    *,
    reference_velocity: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> Regime:
    import numpy as np

    w = law.primitive(conserved)
    temperature = law.temperature(w)
    density = w[:, 0] / law.species_mass
    # The reference-diameter VSS mean free path used in the independent B0
    # specification; diameter scales with relative thermal energy.
    path = (temperature / law.reference_temperature) ** (law.viscosity_exponent - 0.5)
    path /= sqrt(2) * pi * (4.11e-10) ** 2 * density
    thermal_speed = np.sqrt(8 * law.specific_gas_constant * temperature / pi)
    sound = np.sqrt(law.gamma * law.specific_gas_constant * temperature)
    velocity = w[:, 1:4] - np.asarray(reference_velocity)
    slope = np.gradient(w[:, 1:4], grid.spacing, axis=0, edge_order=1)
    indicator = (
        path * np.linalg.norm(slope, axis=1) / np.sqrt(law.specific_gas_constant * temperature)
    )
    return Regime(
        float(np.max(np.linalg.norm(velocity, axis=1) / sound)),
        float(np.max(path) / grid.length),
        float(np.max(microscopic_step * thermal_speed / path)),
        float(sqrt(collision_spacing**2 + 2 * grid.area) / np.min(path)),
        float(np.max(indicator)),
        float(np.max(np.abs(temperature / law.reference_temperature - 1))),
    )


def admit(regime: Regime, *, particle: bool) -> None:
    from math import isfinite

    values = (
        regime.maximum_mach,
        regime.height_knudsen,
        regime.collision_time_ratio,
        regime.cell_to_path_ratio,
        regime.gradient_knudsen,
        regime.thermal_departure,
    )
    if not all(isfinite(x) and x >= 0 for x in values):
        raise InvalidGasState("GAS_REGIME: nonfinite or invalid physical scales")
    if regime.maximum_mach > 0.2 or regime.height_knudsen > 0.02:
        raise InvalidGasState("GAS_REGIME: mean-flow Mach/Knudsen envelope exceeded")
    if regime.thermal_departure > 0.2 or regime.gradient_knudsen > 0.05:
        raise InvalidGasState("GAS_REGIME: thermal/gradient constitutive envelope exceeded")
    if particle and (regime.collision_time_ratio > 0.2 or regime.cell_to_path_ratio > 1):
        raise InvalidGasState("GAS_RESOLUTION: native cell/time exceeds molecular resolution")
