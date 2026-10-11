"""Real sparse finite-volume steps checked against independent physical integrals."""

from itertools import pairwise
from math import log2

import numpy as np
import pytest
from fixtures.adaptive_reference import pulse_average, weighted_error

from code_visualizer.extensions.adaptive_diffusion.numerics import diffuse
from code_visualizer.extensions.adaptive_fields.mesh import Mesh


def state(mesh, time=0):
    return np.array(
        [pulse_average(a, b, time) for a, b in zip(mesh.faces[:-1], mesh.faces[1:], strict=True)]
    )


def test_analytic_reference_agrees_with_independent_quadrature():
    from scipy.integrate import quad

    for a, b in ((0, 0.04), (0.42, 0.48), (0.9, 1.0)):
        expected = quad(
            lambda x: 1 + ((1 + np.cos(2 * np.pi * (x - 0.5))) / 2) ** 8, a, b, epsabs=1e-13
        )[0] / (b - a)
        assert pulse_average(a, b, 0) == pytest.approx(expected, rel=0, abs=2e-14)


def test_periodic_flux_keeps_constants_positive_and_conserves_mass():
    mesh = Mesh.uniform("region", 32, 1.0)
    for initial in (np.full(32, 3.0), state(mesh)):
        before = initial.copy()
        result = diffuse(mesh, initial, 0.001, 0.1)
        assert not result.flags.writeable
        np.testing.assert_array_equal(initial, before)
        assert np.all(result >= 0)
        assert np.dot(result, mesh.widths) == pytest.approx(np.dot(initial, mesh.widths), abs=1e-12)
    np.testing.assert_allclose(diffuse(mesh, np.full(32, 3.0), 0.001, 1.0), 3, atol=1e-12)


def test_uniform_spatial_second_order_against_fourier_cell_integrals():
    errors = []
    # Small fixed dt keeps BE time error below the spatial error at this horizon.
    for count in (32, 64, 128):
        mesh = Mesh.uniform("region", count, 1.0)
        values = state(mesh)
        for _ in range(1000):
            values = diffuse(mesh, values, 0.001, 0.0001)
        errors.append(weighted_error(mesh.faces, values, 0.1))
    orders = [log2(a / b) for a, b in pairwise(errors)]
    assert all(1.7 <= order <= 2.3 for order in orders), (errors, orders)


def test_temporal_first_order_against_independent_uniform_mode_decay():
    mesh = Mesh.uniform("region", 64, 1.0)
    mode = np.cos(2 * np.pi * mesh.centers)
    initial = 2 + mode
    eigenvalue = -4 * 0.001 / (1 / 64) ** 2 * np.sin(np.pi / 64) ** 2
    exact = 2 + np.exp(eigenvalue * 2) * mode
    errors = []
    for count in (10, 20, 40):
        values = initial
        for _ in range(count):
            values = diffuse(mesh, values, 0.001, 2 / count)
        errors.append(float(np.max(np.abs(values - exact))))
    assert all(0.8 <= log2(a / b) <= 1.2 for a, b in pairwise(errors)), errors


@pytest.mark.parametrize("coefficient", [0, -1, float("inf"), float("nan")])
def test_invalid_coefficient_rejected_before_solution(coefficient):
    mesh = Mesh.uniform("region", 16, 1)
    assert diffuse(mesh, np.ones(16), 0.001, 0.1).shape == (16,)
    with pytest.raises(ValueError, match="coefficient"):
        diffuse(mesh, np.ones(16), coefficient, 0.1)
