"""Accepted numerical boundaries; host/resource lifecycle is tested separately."""

from dataclasses import replace

import numpy as np
import pytest
from test_hybrid_gas_continuum import gas
from test_hybrid_gas_particle import WINDOWS

from code_visualizer.domain.values import ResourceReference
from code_visualizer.extensions.hybrid_gas.continuum import GasGrid, Wall
from code_visualizer.extensions.hybrid_gas.coupling import Slab
from code_visualizer.extensions.hybrid_gas.model_transfer import moment_observables
from code_visualizer.extensions.hybrid_gas.policy import ModelPolicy
from code_visualizer.extensions.hybrid_gas.problem import GasError, GasPolicy, GasProblem
from code_visualizer.extensions.hybrid_gas.runtime import GasRuntime
from code_visualizer.extensions.hybrid_gas.validity import admit, assess


def problem(mode="fixed", ticks=4000):
    grid = GasGrid(0.002, 1e-10, 64)
    return GasProblem(
        "problem",
        "gas",
        "channel",
        "slab",
        "initial",
        "policy",
        "space",
        "frame",
        "y",
        tuple("field:" + str(i) for i in range(5)),
        ("lower", "upper"),
        ("wall:lower", "wall:upper"),
        ResourceReference("calibration", "a" * 64),
        grid,
        Slab(24, 40, grid),
        (Wall(273.15, -40), Wall(273.15, 40)),
        7.07043e22,
        273.15,
        (0.0, 0.0, 0.0),
        0.0,
        GasPolicy(
            mode,
            129731,
            7e-9,
            2,
            ticks,
            1000,
            2000,
            1000,
            0,
            1000,
            4,
            50,
            200,
            20000,
            20000,
            ModelPolicy(0.004, 0.001, 3, 1000),
        ),
    )


@WINDOWS
@pytest.mark.parametrize("mode", ["fixed", "particle", "continuum"])
def test_real_participants_keep_global_accounting_and_exact_observation_support(mode):
    p = problem(mode)
    with GasRuntime(p, gas(), "a" * 64, "b" * 64) as runtime:
        base = runtime.state
        assert not base.values.flags.writeable
        while runtime.state.tick < p.policy.final_tick:
            result = runtime.advance()
            assert result.after.tick == result.before.tick + p.policy.window_ticks
        saved = runtime.state
        assert np.max(saved.maximum_residual) < 1e-10
        assert len(saved.observations) == 4
        assert np.stack(saved.observations).shape == (4, 15)
        assert saved.particle_steps == (0 if mode == "continuum" else 4000)
        np.testing.assert_array_equal(base.wall_total, np.zeros(5))
        with pytest.raises(GasError, match="horizon"):
            runtime.advance()
        assert runtime.state is saved
        assert runtime.closed


@WINDOWS
def test_full_input_reconstruction_reproduces_actual_rng_state_and_future_coupled_inputs():
    p = problem(ticks=2000)
    with GasRuntime(p, gas(), "a" * 64, "b" * 64) as first:
        rows = [first.advance().input_row for _ in range(500)]
        prefix, native = first.state, first.native.native.observation()
        future = [first.advance().input_row for _ in range(250)]
        end, end_native = first.state, first.native.native.observation()
    with GasRuntime(p, gas(), "a" * 64, "b" * 64) as second:
        for expected in rows:
            np.testing.assert_array_equal(second.advance().input_row, expected)
        np.testing.assert_array_equal(second.state.values, prefix.values)
        np.testing.assert_array_equal(second.native.native.observation(), native)
        for expected in future:
            np.testing.assert_array_equal(second.advance().input_row, expected)
        np.testing.assert_array_equal(second.state.values, end.values)
        np.testing.assert_array_equal(second.native.native.observation(), end_native)


def test_declared_physical_and_numerical_regimes_are_independent_and_not_clipped():
    p, law = problem("continuum"), gas()
    q = p.initial_values(law)
    valid = assess(law, p.grid, q, 7e-9, 1e-5)
    admit(valid, particle=True)
    for invalid in (
        replace(valid, maximum_mach=0.3),
        replace(valid, height_knudsen=0.1),
        replace(valid, thermal_departure=0.3),
        replace(valid, gradient_knudsen=0.1),
    ):
        with pytest.raises(ValueError, match="GAS_REGIME"):
            admit(invalid, particle=True)
    with pytest.raises(ValueError, match="GAS_RESOLUTION"):
        admit(replace(valid, collision_time_ratio=0.3), particle=True)
    changed = replace(p, velocity=(200.0, 0.0, 0.0))
    with pytest.raises(ValueError, match="GAS_REGIME"):
        GasRuntime(changed, law, "a" * 64, "b" * 64)


def test_initial_shear_is_integrated_as_momentum_and_total_energy_not_mean_temperature():
    p, law = replace(problem("continuum"), sine_amplitude=30.0), gas()
    q = p.initial_values(law)
    rho = p.number_density * law.species_mass
    total = q.sum(axis=0) * p.grid.volume
    mass = rho * p.grid.length * p.grid.area
    assert total[0] == pytest.approx(mass, rel=1e-14)
    assert abs(total[1]) < mass * 1e-14
    assert total[4] == pytest.approx(mass * (law.cv * 273.15 + 0.25 * 30.0**2), rel=1e-14)


def test_central_particle_moments_remove_translation_before_constitutive_return():
    # Independent Maxwellian moment identities. No finite sampling claim.
    law = gas()
    rho, volume = 0.004, 2e-15
    u = np.array([37.0, 11.0, -7.0])
    theta = law.specific_gas_constant * 273.15
    energy = rho * (1.5 * theta + 0.5 * u.dot(u))
    second = rho * np.array(
        [
            u[0] ** 2 + theta,
            u[0] * u[1],
            u[0] * u[2],
            u[1] ** 2 + theta,
            u[1] * u[2],
            u[2] ** 2 + theta,
        ]
    )
    moment = np.r_[
        1000.0,
        rho * volume,
        rho * u * volume,
        energy * volume,
        second * volume,
        (energy + rho * theta) * u[1] * volume,
    ][None, :]
    result = moment_observables(law, moment, volume)
    np.testing.assert_allclose(result[:, 5:], 0, atol=1e-14)
    assert result[0, 4] == pytest.approx(1.0)
