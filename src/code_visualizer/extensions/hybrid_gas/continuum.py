"""Uniform five-component finite-volume gas participant, not a general solver.

MC primitive reconstruction, HLLC (Toro/Spruce/Speares), centered Newtonian
stress and Fourier conduction, SSP RK2. Every accepted update returns its exact
time-integrated oriented face flux; walls and coupling use that same ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING

from code_visualizer.extensions.hybrid_gas.thermodynamics import GasLaw, InvalidGasState, positive

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class Wall:
    temperature: float
    stream_velocity: float = 0.0
    span_velocity: float = 0.0

    def __post_init__(self) -> None:
        positive(self.temperature, "Wall temperature")
        if any(
            type(v) not in (int, float) or not isfinite(v)
            for v in (self.stream_velocity, self.span_velocity)
        ):
            raise ValueError("Wall velocity must be finite")


@dataclass(frozen=True, slots=True)
class GasGrid:
    length: float
    area: float
    cells: int

    def __post_init__(self) -> None:
        positive(self.length, "Channel length")
        positive(self.area, "Channel area")
        if type(self.cells) is not int or not 16 <= self.cells <= 512:
            raise ValueError("Gas grid requires 16..512 cells")

    @property
    def spacing(self) -> float:
        return self.length / self.cells

    @property
    def volume(self) -> float:
        return self.area * self.spacing


@dataclass(frozen=True, slots=True)
class GasStep:
    law: GasLaw
    grid: GasGrid
    base: NDArray[np.float64]
    values: NDArray[np.float64]
    integrated_flux: NDArray[np.float64]
    duration: float


def euler_flux(law: GasLaw, w: NDArray[np.float64]) -> NDArray[np.float64]:
    q = law.conserved(w)
    result = q * w[:, 2:3]
    result[:, 2] += w[:, 4]
    result[:, 4] += w[:, 4] * w[:, 2]
    return result


def hllc(law: GasLaw, left: NDArray[np.float64], right: NDArray[np.float64]) -> NDArray[np.float64]:
    """Contact/shear-preserving normal-y inviscid flux in laboratory coordinates."""
    import numpy as np

    ql, qr = law.conserved(left), law.conserved(right)
    if ql.shape != qr.shape:
        raise InvalidGasState("A face requires two corresponding states")
    cl, cr = (np.sqrt(law.gamma * w[:, 4] / w[:, 0]) for w in (left, right))
    ul, ur = left[:, 2], right[:, 2]
    sl, sr = np.minimum(ul - cl, ur - cr), np.maximum(ul + cl, ur + cr)
    dl, dr = left[:, 0] * (sl - ul), right[:, 0] * (sr - ur)
    sm = (right[:, 4] - left[:, 4] + dl * ul - dr * ur) / (dl - dr)
    if np.any(sm <= sl) or np.any(sm >= sr) or not np.isfinite(sm).all():
        raise InvalidGasState("HLLC intermediate wave lies outside its admissible fan")

    def star(
        w: NDArray[np.float64], q: NDArray[np.float64], speed: NDArray[np.float64]
    ) -> NDArray[np.float64]:
        rho, un, pressure = w[:, 0], w[:, 2], w[:, 4]
        density = rho * (speed - un) / (speed - sm)
        result = np.column_stack((density, density[:, None] * w[:, 1:4], np.zeros(len(w))))
        result[:, 2] = density * sm
        result[:, 4] = density * (
            q[:, 4] / rho + (sm - un) * (sm + pressure / (rho * (speed - un)))
        )
        law.primitive(result)
        return result

    fl, fr = euler_flux(law, left), euler_flux(law, right)
    fls, frs = (
        fl + sl[:, None] * (star(left, ql, sl) - ql),
        fr + sr[:, None] * (star(right, qr, sr) - qr),
    )
    return np.where(
        (sl >= 0)[:, None],
        fl,
        np.where((sm >= 0)[:, None], fls, np.where((sr > 0)[:, None], frs, fr)),
    )


def mc_slopes(values: NDArray[np.float64]) -> NDArray[np.float64]:
    import numpy as np

    left, right = values[1:-1] - values[:-2], values[2:] - values[1:-1]
    middle = (left + right) / 2
    return np.where(
        left * right > 0,
        np.sign(middle)
        * np.minimum(np.abs(middle), np.minimum(2 * np.abs(left), 2 * np.abs(right))),
        0.0,
    )


def ghost(law: GasLaw, row: NDArray[np.float64], wall: Wall) -> NDArray[np.float64]:
    result = row.copy()
    temperature = 2 * wall.temperature - float(law.temperature(row[None, :])[0])
    if temperature <= 0:
        raise InvalidGasState("Wall extrapolation would have nonpositive temperature")
    result[0] = row[4] / (law.specific_gas_constant * temperature)
    result[1:4] = (2 * wall.stream_velocity - row[1], -row[2], 2 * wall.span_velocity - row[3])
    return result


def face_fluxes(
    law: GasLaw, grid: GasGrid, values: NDArray[np.float64], walls: tuple[Wall, Wall] | None
) -> NDArray[np.float64]:
    import numpy as np

    w = law.primitive(values)
    if len(w) != grid.cells:
        raise InvalidGasState("State belongs to another gas grid")
    if walls is None:
        padded = np.vstack((w[-1], w, w[0]))
    else:
        if len(walls) != 2 or not all(isinstance(wall, Wall) for wall in walls):
            raise ValueError("A channel requires two declared walls")
        padded = np.vstack((ghost(law, w[0], walls[0]), w, ghost(law, w[-1], walls[1])))
    slope = mc_slopes(padded)
    left, right = np.empty((grid.cells + 1, 5)), np.empty((grid.cells + 1, 5))
    left[1:], right[:-1] = w + slope / 2, w - slope / 2
    if walls is None:
        left[0], right[-1] = left[-1], right[0]
    else:
        # Inviscid walls reflect only normal velocity; no artificial acoustic
        # diffusion of tangential velocity is used as a physical shear stress.
        left[0], right[-1] = right[0], left[-1]
        left[0, 2] *= -1
        right[-1, 2] *= -1
    flux = hllc(law, left, right)
    temperature = law.temperature(padded)
    face_temperature = (temperature[:-1] + temperature[1:]) / 2
    mu = law.viscosity(face_temperature)
    velocity = (padded[:-1, 1:4] + padded[1:, 1:4]) / 2
    stress = mu[:, None] * np.diff(padded[:, 1:4], axis=0) / grid.spacing
    stress[:, 1] *= 4 / 3
    heat = law.cp * mu / law.prandtl * np.diff(temperature) / grid.spacing
    flux[:, 1:4] -= stress
    flux[:, 4] -= np.sum(velocity * stress, axis=1) + heat
    if not np.isfinite(flux).all():
        raise InvalidGasState("Gas flux is nonfinite")
    return flux


def stable_step(law: GasLaw, grid: GasGrid, values: NDArray[np.float64]) -> float:
    import numpy as np

    w = law.primitive(values)
    a = np.abs(w[:, 2]) + np.sqrt(law.gamma * w[:, 4] / w[:, 0])
    nu = law.viscosity(law.temperature(w)) / w[:, 0]
    diffusivity = max(4 / 3, law.gamma / law.prandtl) * nu
    return float(0.8 / np.max(a / grid.spacing + 2 * diffusivity / grid.spacing**2))


def advance(
    law: GasLaw,
    grid: GasGrid,
    values: NDArray[np.float64],
    duration: float,
    walls: tuple[Wall, Wall] | None = None,
) -> GasStep:
    """One immutable explicit candidate; caller decides whether to admit it."""
    import numpy as np

    positive(duration, "Step duration")
    base = values.copy()
    if duration > stable_step(law, grid, values) * (1 + 1e-14):
        raise InvalidGasState("Gas step exceeds its advective/diffusive limit")
    first = face_fluxes(law, grid, values, walls)
    trial = values - duration * np.diff(first, axis=0) / grid.spacing
    law.primitive(trial)
    if duration > stable_step(law, grid, trial) * (1 + 1e-14):
        raise InvalidGasState("Gas stage exceeds its advective/diffusive limit")
    second = face_fluxes(law, grid, trial, walls)
    integral = duration * (first + second) / 2
    candidate = values - np.diff(integral, axis=0) / grid.spacing
    law.primitive(candidate)
    # The integrated flux has units per area. Multiply by area exactly once
    # when it is compared with an extensive gas or particle quantity.
    candidate.setflags(write=False)
    integral.setflags(write=False)
    base.setflags(write=False)
    return GasStep(law, grid, base, candidate, integral, duration)


def advance_window(
    law: GasLaw,
    grid: GasGrid,
    values: NDArray[np.float64],
    duration: float,
    walls: tuple[Wall, Wall] | None = None,
) -> tuple[GasStep, int]:
    """Bounded continuum subdivision leaves the particle clock/window unchanged."""
    import numpy as np

    positive(duration, "Window duration")
    count = 1
    while duration / count > 0.9 * stable_step(law, grid, values):
        count *= 2
        if count > 16:
            raise InvalidGasState(
                "GAS_CONTINUUM_BUDGET: communication window needs over 16 substeps"
            )
    current = values
    integrated = np.zeros((grid.cells + 1, 5))
    for _ in range(count):
        candidate = advance(law, grid, current, duration / count, walls)
        integrated += candidate.integrated_flux
        current = candidate.values
    base = values.copy()
    base.setflags(write=False)
    integrated.setflags(write=False)
    return GasStep(law, grid, base, current, integrated, duration), count


def shear_stress(law: GasLaw, grid: GasGrid, values: NDArray[np.float64]) -> NDArray[np.float64]:
    """The cell-centered Newtonian constitutive shear used for bulk observations."""
    import numpy as np

    w = law.primitive(values)
    return law.viscosity(law.temperature(w)) * np.gradient(w[:, 1], grid.spacing, edge_order=2)
