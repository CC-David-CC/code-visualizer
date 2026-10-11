"""Independent five-component checks before any particle coupling is admitted."""

from dataclasses import replace
from itertools import pairwise
from math import log2

import numpy as np
import pytest

from code_visualizer.extensions.hybrid_gas.continuum import (
    GasGrid,
    Wall,
    advance,
    euler_flux,
    face_fluxes,
    hllc,
    stable_step,
)
from code_visualizer.extensions.hybrid_gas.thermodynamics import GasLaw, InvalidGasState


def gas():
    # An explicit constitutive input, not a calibration of the coupled answer.
    return GasLaw(6.63e-26, 1.380649e-23, 273.15, 2.1159898883296842e-5, 0.81)


def uniform(law, grid, velocity=(0.0, 0.0, 0.0)):
    density = 7.07043e22 * law.species_mass
    w = np.tile((density, *velocity, density * law.specific_gas_constant * 273.15), (grid.cells, 1))
    return law.conserved(w)


def test_conserved_energy_includes_all_streaming_components():
    law, grid = gas(), GasGrid(0.002, 1e-10, 32)
    q = uniform(law, grid, (19.0, -7.0, 23.0))
    temperature = (q[:, 4] / q[:, 0] - 0.5 * (19**2 + 7**2 + 23**2)) / law.cv
    np.testing.assert_allclose(temperature, 273.15, rtol=1e-14)
    np.testing.assert_allclose(law.conserved(law.primitive(q)), q, rtol=1e-14)


@pytest.mark.parametrize("column,value", [(0, 0), (0, -1), (4, -1), (1, np.inf), (4, np.nan)])
def test_invalid_gas_cannot_be_repaired_by_a_floor(column, value):
    law, grid = gas(), GasGrid(0.002, 1e-10, 16)
    q = uniform(law, grid)
    q[4, column] = value
    before = q.copy()
    with pytest.raises(InvalidGasState):
        advance(law, grid, q, 1e-9)
    np.testing.assert_array_equal(q, before)


def test_stationary_contact_and_tangential_slip_have_no_acoustic_diffusion():
    law = gas()
    left = np.array([[0.004, -23.0, 0.0, 17.0, 260.0]])
    right = np.array([[0.006, 31.0, 0.0, -11.0, 260.0]])
    result = hllc(law, left, right)
    np.testing.assert_allclose(result, [[0.0, 0.0, 260.0, 0.0, 0.0]], atol=1e-10)


def test_uniform_moving_equilibrium_is_exact_under_periodic_transport():
    law, grid = gas(), GasGrid(0.002, 1e-10, 32)
    q = uniform(law, grid, (40.0, 7.0, -12.0))
    before = q.copy()
    step = advance(law, grid, q, 7e-9)
    np.testing.assert_array_equal(q, before)
    np.testing.assert_allclose(step.values, q, rtol=0, atol=1e-13)
    np.testing.assert_allclose(
        step.integrated_flux / step.duration,
        np.tile(euler_flux(law, law.primitive(q[:1])), (33, 1)),
        rtol=1e-13,
    )
    assert not step.values.flags.writeable and not step.integrated_flux.flags.writeable


def test_wall_impulse_heat_and_work_use_the_actual_update_flux():
    law, grid = gas(), GasGrid(0.002, 1e-10, 64)
    q = uniform(law, grid, (0.0, 0.0, 3.0))
    walls = (Wall(270.0, -40.0, 5.0), Wall(277.0, 40.0, -7.0))
    initial = q.sum(axis=0) * grid.volume
    transferred = np.zeros(5)
    for _ in range(60):
        step = advance(law, grid, q, 7e-9, walls)
        transferred += (step.integrated_flux[0] - step.integrated_flux[-1]) * grid.area
        q = step.values
    scale = np.array([initial[0], initial[0] * 300, initial[0] * 300, initial[0] * 300, initial[4]])
    residual = (q.sum(axis=0) * grid.volume - initial - transferred) / scale
    np.testing.assert_allclose(residual, 0.0, atol=1e-12)
    assert abs(transferred[0]) < initial[0] * 1e-13
    assert q[0, 1] < 0 < q[-1, 1]
    assert transferred[4] > 0


def test_heat_flux_uses_temperature_and_retains_thermal_energy():
    law, grid = gas(), GasGrid(0.002, 1e-10, 32)
    q = uniform(law, grid)
    w = law.primitive(q)
    temperature = 270 + 6 * (np.arange(grid.cells) + 0.5) / grid.cells
    w[:, 4] = w[:, 0] * law.specific_gas_constant * temperature
    # No normal flow at this instant; the energy flux is Fourier conduction.
    expected = -law.cp / law.prandtl * law.viscosity(np.linspace(270, 276, 33)) * 6 / grid.length
    # Interior pressure gradients also generate an inviscid Riemann energy flux.
    # With constant pressure and changing density that term vanishes.
    w[:, 4] = w[0, 4]
    w[:, 0] = w[:, 4] / (law.specific_gas_constant * temperature)
    flux = face_fluxes(law, grid, law.conserved(w), (Wall(270), Wall(276)))
    np.testing.assert_allclose(flux[:, 4], expected, rtol=1e-10, atol=1e-7)


def test_overlarge_step_rejects_without_mutating_the_base():
    law, grid = gas(), GasGrid(0.002, 1e-10, 32)
    q = uniform(law, grid)
    before = q.copy()
    with pytest.raises(InvalidGasState, match="limit"):
        advance(law, grid, q, stable_step(law, grid, q) * 1.01)
    np.testing.assert_array_equal(q, before)
    with pytest.raises(ValueError, match="viscosity"):
        replace(law, reference_viscosity=0.0)


def shear(law, grid):
    w = law.primitive(uniform(law, grid))
    faces = np.linspace(0, grid.length, grid.cells + 1)
    wave = (
        np.cos(2 * np.pi * faces[:-1] / grid.length) - np.cos(2 * np.pi * faces[1:] / grid.length)
    ) / (2 * np.pi / grid.cells)
    w[:, 1] = 1e-4 * wave
    return law.conserved(w), w[:, 1].copy()


def test_linearized_shear_spatial_order_against_exact_cell_integrals():
    law, errors = gas(), []
    end, dt = 1e-7, 1e-9
    for count in (32, 64, 128):
        grid = GasGrid(0.002, 1e-10, count)
        q, initial = shear(law, grid)
        nu = law.reference_viscosity / q[0, 0]
        exact = initial * np.exp(-nu * (2 * np.pi / grid.length) ** 2 * end)
        for _ in range(round(end / dt)):
            q = advance(law, grid, q, dt).values
        errors.append(float(np.linalg.norm(q[:, 1] / q[:, 0] - exact) / np.sqrt(count)))
    assert all(1.7 <= log2(a / b) <= 2.3 for a, b in pairwise(errors)), errors


def test_linearized_shear_temporal_order_against_semidiscrete_decay():
    law, grid, errors = gas(), GasGrid(0.002, 1e-10, 32), []
    end = 2e-6
    for steps in (100, 200, 400):
        q, initial = shear(law, grid)
        eigenvalue = (
            -4
            * law.reference_viscosity
            / q[0, 0]
            / grid.spacing**2
            * np.sin(np.pi / grid.cells) ** 2
        )
        exact = initial * np.exp(eigenvalue * end)
        for _ in range(steps):
            q = advance(law, grid, q, end / steps).values
        errors.append(float(np.linalg.norm(q[:, 1] / q[:, 0] - exact)))
    assert all(1.7 <= log2(a / b) <= 2.3 for a, b in pairwise(errors)), errors
