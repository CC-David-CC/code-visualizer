"""Independent transport observations are immutable inputs, not authored coefficients.

The gas model references this resource. Its viscosity is derived by replaying
the declared fit over actual retained observations; no result is silently copied
into an editable parameter. This v1 contract is the pinned B0 periodic shear study.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import pi, sqrt
from typing import TYPE_CHECKING

from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.values import ResourceReference
from code_visualizer.execution.backends import PreparedComputation
from code_visualizer.execution.resource_interpretation import ResourceDependency
from code_visualizer.extensions.fields.arrays import read_array
from code_visualizer.extensions.fields.records import ARRAY_TYPE, digest, ref
from code_visualizer.extensions.foundations.record_codec import RecordCodec
from code_visualizer.extensions.hybrid_gas.native_api import BINARY_SHA
from code_visualizer.extensions.hybrid_gas.thermodynamics import GasLaw

CALIBRATION_TYPE = ResourceLogicalTypeReference("code_visualizer.hybrid_gas.calibration", "1")

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class CalibrationReplica:
    seed: int
    observations: ResourceReference

    def __post_init__(self) -> None:
        if type(self.seed) is not int or not 1 <= self.seed < 1 << 31:
            raise ValueError("GAS_CALIBRATION: invalid replica seed")
        ref(self.observations)


@dataclass(frozen=True, slots=True)
class ViscosityCalibration:
    replicas: tuple[CalibrationReplica, ...]
    native_binary_digest: str
    original_driver_digest: str
    original_result_digest: str
    protocol: str = "argon_vss_periodic_shear_200cells_6000steps_7ns_v1"

    def __post_init__(self) -> None:
        if (
            type(self.replicas) is not tuple
            or not 4 <= len(self.replicas) <= 32
            or any(not isinstance(r, CalibrationReplica) for r in self.replicas)
            or len({r.seed for r in self.replicas}) != len(self.replicas)
            or len({r.observations for r in self.replicas}) != len(self.replicas)
            or self.protocol != "argon_vss_periodic_shear_200cells_6000steps_7ns_v1"
        ):
            raise ValueError(
                "GAS_CALIBRATION: require distinct independent replicas of the exact study"
            )
        for value in (
            self.native_binary_digest,
            self.original_driver_digest,
            self.original_result_digest,
        ):
            digest(value)

    def dependencies(self) -> tuple[ResourceDependency, ...]:
        return tuple(ResourceDependency(r.observations, ARRAY_TYPE) for r in self.replicas)


CODEC = RecordCodec((CalibrationReplica, ViscosityCalibration))


def calibration_dependencies(payload: bytes) -> tuple[ResourceDependency, ...]:
    return CODEC.decode(payload, ViscosityCalibration).dependencies()


@dataclass(frozen=True, slots=True)
class CalibratedTransport:
    law: GasLaw
    reference: ResourceReference
    fits: tuple[float, ...]
    half_width_95: float


def transport(snapshot: PreparedComputation, reference: ResourceReference) -> CalibratedTransport:
    import numpy as np
    from scipy.optimize import curve_fit  # type: ignore[import-untyped]
    from scipy.stats import t  # type: ignore[import-untyped]

    resources = {r.descriptor.reference: r for r in snapshot.resources}
    resource = resources.get(reference)
    if resource is None or resource.descriptor.logical_type != CALIBRATION_TYPE:
        raise ValueError("GAS_CALIBRATION_RESOURCE: exact registered calibration input is required")
    with resource.open() as stream:
        saved = CODEC.decode(stream.read(65537), ViscosityCalibration)
    if saved.native_binary_digest != BINARY_SHA:
        raise ValueError("GAS_CALIBRATION_METHOD: observations belong to another native method")
    mass, boltzmann, temperature = 6.63e-26, 1.380649e-23, 273.15
    density, omega, alpha, diameter = 7.07043e22 * mass, 0.81, 1.4, 4.11e-10
    theoretical = (
        5
        * (alpha + 1)
        * (alpha + 2)
        * sqrt(mass * boltzmann * temperature / pi)
        / (4 * alpha * (5 - 2 * omega) * (7 - 2 * omega) * diameter**2)
    )
    centers = (np.arange(200) + 0.5) / 200
    sine = np.sin(2 * pi * centers)
    wave = 2 * pi / 0.002

    def decay(times: NDArray[np.float64], amplitude: float, nu: float) -> NDArray[np.float64]:
        return amplitude * np.exp(-nu * wave * wave * times)

    fits = []
    for replica in saved.replicas:
        source = resources.get(replica.observations)
        if source is None:
            raise ValueError("GAS_CALIBRATION_RESOURCE: missing raw independent observation")
        raw = read_array(source, (121, 2601))
        if not np.array_equal(raw[:, 0], np.arange(0, 6001, 50)):
            raise ValueError("GAS_CALIBRATION_TIME: observations have different physical coverage")
        moments = raw[:, 1:].reshape(121, 200, 13)
        if np.any(moments[:, :, 0:2] <= 0):
            raise ValueError("GAS_CALIBRATION_STATE: count and mass must be positive")
        amplitude = np.sum(moments[:, :, 2] * sine, axis=1) / np.sum(
            moments[:, :, 1] * sine**2, axis=1
        )
        selected = raw[:, 0] >= 500
        fitted, _ = curve_fit(
            decay,
            raw[selected, 0] * 7e-9,
            amplitude[selected],
            p0=(30.0, theoretical / density),
            bounds=((0.0, 0.0), (100.0, 0.1)),
        )
        fits.append(float(fitted[1] * density))
    mean = float(np.mean(fits))
    half = float(t.ppf(0.975, len(fits) - 1) * np.std(fits, ddof=1) / sqrt(len(fits)))
    if mean <= 0 or half / mean > 0.05 or abs(mean - theoretical) > half + 0.1 * theoretical:
        raise ValueError("GAS_CALIBRATION_FIDELITY: independent precision/compatibility failed")
    return CalibratedTransport(
        GasLaw(mass, boltzmann, temperature, mean, omega), reference, tuple(fits), half
    )
