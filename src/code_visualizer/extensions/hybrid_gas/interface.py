"""Typed state/flux exchange. Integrated quantities are not flux rates.

This internal Python boundary is owned by the gas extension. Native outputs are
laboratory-frame extensive quantities; the outward normal belongs to the
particle volume. Adjacent continuum cells apply the opposite transfer.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from math import isfinite
from typing import TYPE_CHECKING

from code_visualizer.domain.values import QuantityValue, UnitReference
from code_visualizer.extensions.fields.records import digest, identity, index, scalar
from code_visualizer.extensions.hybrid_gas.units import catalog, quantity

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class FluxUnits:
    mass: UnitReference
    momentum: UnitReference
    energy: UnitReference

    def __post_init__(self) -> None:
        for value, expected in (
            (self.mass, "kilogram"),
            (self.momentum, "kilogram_meter_per_second"),
            (self.energy, "joule"),
        ):
            if not isinstance(value, UnitReference):
                raise ValueError("A gas transfer requires typed unit references")
            catalog().validate_reference(value)
            if value.dimension != quantity(1, expected).unit.dimension:
                raise ValueError("A gas transfer requires mass, momentum and energy dimensions")

    @classmethod
    @cache
    def si(cls) -> FluxUnits:
        return cls(
            *(quantity(1, unit).unit for unit in ("kilogram", "kilogram_meter_per_second", "joule"))
        )


@dataclass(frozen=True, slots=True)
class Interface:
    source_digest: str
    law_digest: str
    policy_id: str
    region_id: str
    face_id: str
    frame_id: str
    axis_id: str
    outward_normal: int
    area: QuantityValue
    particle_mass: QuantityValue
    units: FluxUnits

    def __post_init__(self) -> None:
        digest(self.source_digest)
        digest(self.law_digest)
        for value in (self.policy_id, self.region_id, self.face_id, self.frame_id, self.axis_id):
            identity(value)
        if type(self.outward_normal) is not int or self.outward_normal not in (-1, 1):
            raise ValueError("An interface has one oriented outward normal")
        if (
            scalar(self.area, "Interface area") <= 0
            or self.area.unit != quantity(1, "square_meter").unit
        ):
            raise ValueError("Internal gas interfaces require positive SI area")
        if (
            scalar(self.particle_mass, "Statistical particle mass") <= 0
            or self.particle_mass.unit != quantity(1, "kilogram").unit
        ):
            raise ValueError(
                "An interface requires the positive SI mass represented by one particle"
            )
        if not isinstance(self.units, FluxUnits):
            raise ValueError("A gas interface requires exact extensive units")
        if self.units != FluxUnits.si():
            raise ValueError("GAS_INTERFACE_MISMATCH: internal transfers require exact SI units")


@dataclass(frozen=True, slots=True)
class ExchangeWindow:
    interface: Interface
    first_tick: int
    last_tick: int
    quantum: QuantityValue

    def __post_init__(self) -> None:
        if not isinstance(self.interface, Interface):
            raise ValueError("An exchange requires its exact interface")
        index(self.first_tick, "First exchange tick")
        index(self.last_tick, "Last exchange tick")
        if not self.first_tick < self.last_tick or self.last_tick - self.first_tick > 64:
            raise ValueError("A gas exchange requires 1..64 advancing microscopic steps")
        if (
            scalar(self.quantum, "Microscopic quantum") <= 0
            or self.quantum.unit != quantity(1, "second").unit
        ):
            raise ValueError("Internal gas exchange time must be positive SI time")


@dataclass(frozen=True, slots=True)
class ReservoirState:
    window: ExchangeWindow
    density: QuantityValue
    temperature: QuantityValue
    velocity: tuple[QuantityValue, QuantityValue, QuantityValue]

    def __post_init__(self) -> None:
        if not isinstance(self.window, ExchangeWindow):
            raise ValueError("A reservoir requires its exact window")
        for value, unit in (
            (self.density, "kilogram_per_cubic_meter"),
            (self.temperature, "kelvin"),
        ):
            if scalar(value, "Reservoir state") <= 0 or value.unit != quantity(1, unit).unit:
                raise ValueError(
                    "Internal reservoir density/temperature requires positive SI quantities"
                )
        if (
            type(self.velocity) is not tuple
            or len(self.velocity) != 3
            or any(
                not isinstance(value, QuantityValue)
                or value.unit != quantity(1, "meter_per_second").unit
                or not isfinite(scalar(value, "Velocity"))
                for value in self.velocity
            )
        ):
            raise ValueError(
                "A reservoir velocity requires three SI components in its declared frame"
            )


@dataclass(frozen=True, slots=True)
class ConservedAmount:
    mass: float
    momentum: tuple[float, float, float]
    energy: float

    def __post_init__(self) -> None:
        if (
            type(self.momentum) is not tuple
            or len(self.momentum) != 3
            or any(
                type(value) not in (int, float) or not isfinite(value)
                for value in (self.mass, *self.momentum, self.energy)
            )
        ):
            raise ValueError("A conserved amount requires five finite extensive values")

    def array(self) -> NDArray[np.float64]:
        import numpy as np

        return np.array((self.mass, *self.momentum, self.energy), dtype=np.float64)


@dataclass(frozen=True, slots=True)
class IntegratedFlux:
    window: ExchangeWindow
    incoming: ConservedAmount
    outgoing: ConservedAmount
    emitted_particles: int
    escaped_particles: int

    def __post_init__(self) -> None:
        if not isinstance(self.window, ExchangeWindow):
            raise ValueError("An integrated flux requires its exact window")
        index(self.emitted_particles, "Emitted particle count")
        index(self.escaped_particles, "Escaped particle count")
        for value, count in (
            (self.incoming, self.emitted_particles),
            (self.outgoing, self.escaped_particles),
        ):
            if not isinstance(value, ConservedAmount) or value.mass < 0 or value.energy < 0:
                raise ValueError("Incoming/outgoing amounts require nonnegative mass and energy")
            expected = count * scalar(self.window.interface.particle_mass, "Particle mass")
            if abs(value.mass - expected) > max(expected, 1e-300) * 1e-12:
                raise ValueError(
                    "Particle count and transferred mass disagree with the frozen particle weight"
                )
            if count == 0 and (value.energy != 0 or any(value.momentum)):
                raise ValueError("No crossing particles cannot carry particle momentum or energy")

    def admit(self, expected: ExchangeWindow) -> NDArray[np.float64]:
        """Return extensive transfer in the +axis direction, not a per-second rate."""
        if self.window != expected or expected.interface.units != FluxUnits.si():
            raise ValueError(
                "GAS_INTERFACE_MISMATCH: source, window, face, normal, frame, "
                "law, policy or units differ"
            )
        return -expected.interface.outward_normal * (self.incoming.array() - self.outgoing.array())
