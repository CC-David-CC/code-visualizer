"""Monatomic ideal-gas conserved meaning in SI after the authored unit boundary.

Arrays have columns rho, rho*u_x, rho*u_y, rho*u_z, total energy per volume.
Primitive arrays have rho, u_x, u_y, u_z, pressure. No pressure/density floor can
turn an invalid state into an admitted one.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


class InvalidGasState(ValueError):
    """An explicit physical or numerical admission failure."""


def positive(value: float, name: str) -> None:
    if type(value) not in (int, float) or not isfinite(value) or value <= 0:
        raise ValueError(f"{name} requires a positive finite scalar")


def state_array(values: NDArray[np.float64]) -> NDArray[np.float64]:
    import numpy as np

    result = np.asarray(values, dtype=np.float64)
    if result.ndim != 2 or result.shape[1] != 5 or not 1 <= len(result) <= 514:
        raise InvalidGasState("Gas state requires 1..514 rows of five conserved/primitive values")
    if not np.isfinite(result).all():
        raise InvalidGasState("Gas state contains a nonfinite value")
    return result


@dataclass(frozen=True, slots=True)
class GasLaw:
    species_mass: float
    boltzmann: float
    reference_temperature: float
    reference_viscosity: float
    viscosity_exponent: float
    prandtl: float = 2 / 3

    def __post_init__(self) -> None:
        for value, name in (
            (self.species_mass, "Species mass"),
            (self.boltzmann, "Boltzmann constant"),
            (self.reference_temperature, "Reference temperature"),
            (self.reference_viscosity, "Reference viscosity"),
            (self.viscosity_exponent, "Viscosity exponent"),
            (self.prandtl, "Prandtl number"),
        ):
            positive(value, name)
        if not 0.5 <= self.viscosity_exponent <= 1:
            raise ValueError("This gas law supports VSS exponents in 0.5..1")

    @property
    def gamma(self) -> float:
        return 5 / 3

    @property
    def specific_gas_constant(self) -> float:
        return self.boltzmann / self.species_mass

    @property
    def cv(self) -> float:
        return 1.5 * self.specific_gas_constant

    @property
    def cp(self) -> float:
        return 2.5 * self.specific_gas_constant

    def primitive(self, conserved: NDArray[np.float64]) -> NDArray[np.float64]:
        import numpy as np

        q = state_array(conserved)
        if np.any(q[:, 0] <= 0):
            raise InvalidGasState("Gas density must be positive")
        velocity = q[:, 1:4] / q[:, :1]
        pressure = (self.gamma - 1) * (q[:, 4] - 0.5 * np.sum(q[:, 1:4] * velocity, axis=1))
        if not np.isfinite(pressure).all() or np.any(pressure <= 0):
            raise InvalidGasState("Gas internal energy and pressure must be positive")
        return np.column_stack((q[:, 0], velocity, pressure))

    def conserved(self, primitive: NDArray[np.float64]) -> NDArray[np.float64]:
        import numpy as np

        w = state_array(primitive)
        if np.any(w[:, (0, 4)] <= 0):
            raise InvalidGasState("Primitive density and pressure must be positive")
        energy = w[:, 4] / (self.gamma - 1) + 0.5 * w[:, 0] * np.sum(w[:, 1:4] ** 2, axis=1)
        result = np.column_stack((w[:, 0], w[:, :1] * w[:, 1:4], energy))
        if not np.isfinite(result).all():
            raise InvalidGasState("Gas conversion overflowed its finite interpretation")
        return result

    def temperature(self, primitive: NDArray[np.float64]) -> NDArray[np.float64]:
        import numpy as np

        w = state_array(primitive)
        if np.any(w[:, (0, 4)] <= 0):
            raise InvalidGasState("Temperature requires positive density and pressure")
        result = w[:, 4] / (w[:, 0] * self.specific_gas_constant)
        if not np.isfinite(result).all() or np.any(result <= 0):
            raise InvalidGasState("Temperature must be positive and finite")
        return result

    def viscosity(self, temperature: NDArray[np.float64]) -> NDArray[np.float64]:
        import numpy as np

        if not np.isfinite(temperature).all() or np.any(temperature <= 0):
            raise InvalidGasState("Transport requires positive finite temperature")
        result = (
            self.reference_viscosity
            * (temperature / self.reference_temperature) ** self.viscosity_exponent
        )
        if not np.isfinite(result).all() or np.any(result <= 0):
            raise InvalidGasState("Transport coefficient is undefined")
        return result
