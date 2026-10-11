"""Independent physical equations compared with decoded ordinary-host publications.

No reference imports the production participant, RHS, matrix or history-value
helpers. The parameters below are the explicitly authored test specifications.
"""

import json
from dataclasses import dataclass, replace
from math import sqrt

import numpy as np
import pytest
from scipy.integrate import solve_ivp
from scipy.linalg import expm
from test_diffusion_checkpoints import host
from test_electrothermal_checkpoints import last_root, request, rows
from test_electrothermal_contracts import changed

from code_visualizer.application.computation import execute_computation
from code_visualizer.application.coupled_examples import electrothermal_project
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.extensions.electrothermal.units import quantity
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.serialization import normalized_project_json


@dataclass(frozen=True)
class Parameters:
    voltage: float = 5.0
    resistance: float = 10.0
    alpha: float = 0.004
    cr: float = 10.0
    cs: float = 20.0
    g: float = 0.2
    h: float = 0.1
    ambient: float = 293.15
    x0: float = 0.0
    y0: float = 0.0


def authored(p, *, duration=10, step=1, sample_every=1, checkpoint_every=5, **kwargs):
    project = electrothermal_project(
        duration=duration,
        windows=round(duration / step),
        alpha=p.alpha,
        voltage=p.voltage,
        sample_every=sample_every,
        checkpoint_every=checkpoint_every,
        **kwargs,
    )
    for node, field, value, unit in (
        ("et:resistor", "resistance", p.resistance, "ohm"),
        ("et:resistor-body", "capacity", p.cr, "joule_per_kelvin"),
        ("et:sink", "capacity", p.cs, "joule_per_kelvin"),
        ("et:contact", "conductance", p.g, "watt_per_kelvin"),
        ("et:ambient", "conductance", p.h, "watt_per_kelvin"),
        ("et:resistor-body", "initial_temperature", p.ambient + p.x0, "kelvin"),
        ("et:sink", "initial_temperature", p.ambient + p.y0, "kelvin"),
    ):
        project = changed(project, node, field, quantity(value, unit))
    return project


def published(project, directory):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "authored.json"
    path.write_text(normalized_project_json(project), encoding="utf-8")
    saved = project_from_json(path.read_text(encoding="utf-8"))
    before = normalized_project_json(saved)
    with host(saved, directory) as kernel:
        result = execute_computation(kernel, request(saved))
        assert result.outcome == ComputationOutcome.SUCCEEDED, result.diagnostics
        actual = rows(kernel.resource_store, last_root(result, kernel.resource_store))
        assert normalized_project_json(kernel.authority.snapshot()) == before
    return actual


def discrete(p, dt, windows):
    # Independent elimination of the sink balance gives one scalar quadratic.
    x, y = p.x0, p.y0
    ein = eout = 0.0
    history = [(x, y, ein, eout)]
    for _ in range(windows):
        q = p.cs / dt + p.g + p.h
        a = p.cr / dt + p.g - p.g * p.g / q
        b = p.cr * x / dt + p.g * p.cs * y / (dt * q)
        linear = a - b * p.alpha
        right = b + p.voltage**2 / p.resistance
        x = 2 * right / (linear + sqrt(linear**2 + 4 * a * p.alpha * right))
        y = (p.cs * y / dt + p.g * x) / q
        ein += dt * p.voltage**2 / (p.resistance * (1 + p.alpha * x))
        eout += dt * p.h * y
        history.append((x, y, ein, eout))
    return np.asarray(history)


def continuous(p, times, method="DOP853"):
    def rhs(_time, state):
        x, y = state
        joule = p.voltage**2 / (p.resistance * (1 + p.alpha * x))
        contact = p.g * (x - y)
        return ((joule - contact) / p.cr, (contact - p.h * y) / p.cs)

    result = solve_ivp(
        rhs,
        (0, float(times[-1])),
        (p.x0, p.y0),
        method=method,
        rtol=1e-12,
        atol=(1e-13, 1e-13),
        t_eval=times,
    )
    assert result.success
    return result.y.T


def constant_exact(p, times):
    matrix = np.asarray(((-p.g / p.cr, p.g / p.cr), (p.g / p.cs, -(p.g + p.h) / p.cs)))
    forcing = np.asarray((p.voltage**2 / (p.resistance * p.cr), 0))
    steady = -np.linalg.solve(matrix, forcing)
    initial = np.asarray((p.x0, p.y0))
    return np.asarray([steady + expm(matrix * t) @ (initial - steady) for t in times])


def assert_accounting(data, p, expected):
    selected = expected[data[:, 0].astype(int)]
    np.testing.assert_allclose(data[:, 2:4], p.ambient + selected[:, :2], rtol=0, atol=2e-9)
    np.testing.assert_allclose(data[:, 11:13], selected[:, 2:4], rtol=0, atol=2e-8)
    np.testing.assert_allclose(data[:, 7], data[:, 5] * data[:, 6], rtol=0, atol=1e-10)
    np.testing.assert_allclose(data[:, 7], data[:, 6] ** 2 * data[:, 4], rtol=0, atol=1e-10)
    assert np.array_equal(data[:, 8], -data[:, 9])
    stored = p.cr * (data[:, 2] - p.ambient - p.x0) + p.cs * (data[:, 3] - p.ambient - p.y0)
    np.testing.assert_allclose(data[:, 13], stored, rtol=0, atol=2e-9)
    np.testing.assert_allclose(data[:, 11] - data[:, 12], stored, rtol=0, atol=2e-8)
    assert np.max(np.abs(data[:, 14])) < 2e-8
    assert np.max(np.abs(data[:, 15:18])) <= 1e-10
    assert np.max(data[:, 18]) <= 1e-10


@pytest.fixture(scope="module")
def refinement(tmp_path_factory):
    root = tmp_path_factory.mktemp("coupled-refinement")
    return {
        h: published(
            authored(
                Parameters(),
                duration=100,
                step=h,
                sample_every=round(5 / h),
                checkpoint_every=round(25 / h),
            ),
            root / str(h),
        )
        for h in (1.0, 0.5, 0.25)
    }


def test_published_nonlinear_transient_first_order_and_independent_reference(
    refinement, record_property
):
    times = np.arange(0, 101, 5, dtype=float)
    reference = continuous(Parameters(), times)
    independent_method = continuous(Parameters(), times, "Radau")
    np.testing.assert_allclose(reference, independent_method, rtol=0, atol=1e-9)
    errors = []
    for step, actual in refinement.items():
        assert np.array_equal(actual[:, 1], times)
        error = float(np.max(np.abs(actual[:, 2:4] - 293.15 - reference)))
        errors.append(error)
        assert_accounting(actual, Parameters(), discrete(Parameters(), step, round(100 / step)))
    orders = np.log2(np.asarray(errors[:-1]) / errors[1:])
    assert np.all((orders >= 0.9) & (orders <= 1.1)), orders
    assert errors[-1] < 0.02
    record_property("temperature_errors_kelvin", json.dumps(errors))
    record_property("observed_orders", json.dumps(orders.tolist()))
    record_property("reference_methods", "Independent DOP853 and Radau, rtol=1e-12, atol=1e-13")


@pytest.mark.parametrize(
    "p",
    (
        Parameters(alpha=0),
        Parameters(voltage=0),
        Parameters(x0=5, y0=2),
        Parameters(voltage=7, cr=15, cs=22, g=0.3, h=0.07),
        Parameters(voltage=-5),
    ),
)
def test_positive_fragments_follow_independently_eliminated_windows(tmp_path, p):
    actual = published(authored(p), tmp_path)
    assert_accounting(actual, p, discrete(p, 1, 10))
    if p.voltage == 0:
        assert np.array_equal(actual[:, 2:4], np.full((11, 2), p.ambient))
        assert np.count_nonzero(actual[:, 6:19]) == 0


def test_constant_resistance_continuous_matrix_exponential(tmp_path, record_property):
    p = Parameters(alpha=0)
    actual = published(
        authored(p, duration=100, step=0.25, sample_every=20, checkpoint_every=100), tmp_path
    )
    exact = constant_exact(p, actual[:, 1])
    np.testing.assert_allclose(exact, continuous(p, actual[:, 1]), rtol=0, atol=1e-9)
    error = float(np.max(np.abs(actual[:, 2:4] - p.ambient - exact)))
    assert error < 0.02
    record_property("constant_resistance_error_kelvin", str(error))
    assert_accounting(actual, p, discrete(p, 0.25, 400))


def test_independently_derived_steady_state_remains_stationary(tmp_path):
    p = Parameters()
    conductance = p.g * p.h / (p.g + p.h)
    forcing = p.voltage**2 / (p.resistance * conductance)
    x = 2 * forcing / (1 + sqrt(1 + 4 * p.alpha * forcing))
    y = p.g * x / (p.g + p.h)
    p = replace(p, x0=x, y0=y)
    actual = published(authored(p, duration=100, step=10), tmp_path)
    np.testing.assert_allclose(actual[:, 2], 326.2638830084, rtol=0, atol=1e-9)
    np.testing.assert_allclose(actual[:, 3], 315.2259220056, rtol=0, atol=1e-9)
    np.testing.assert_allclose(actual[:, 7], 2.20759220056, rtol=0, atol=1e-10)
    np.testing.assert_allclose(actual[:, 11], actual[:, 12], rtol=0, atol=1e-8)


@pytest.mark.parametrize("variation", ("order", "sampling", "units", "author_order"))
def test_execution_policy_and_authoring_order_do_not_choose_physical_causality(tmp_path, variation):
    p = Parameters()
    project = authored(p)
    if variation == "order":
        project = changed(project, "et:policy", "evaluation_order", "thermal_first")
    elif variation == "sampling":
        for field, value in (
            ("sample_every", 2),
            ("checkpoint_every", 3),
            ("preview_every", 7),
            ("chunk_rows", 2),
        ):
            project = changed(project, "et:policy", field, value)
    elif variation == "units":
        for node, field in (
            ("et:resistor-body", "initial_temperature"),
            ("et:sink", "initial_temperature"),
            ("et:ambient", "temperature"),
            ("et:law", "reference_temperature"),
        ):
            project = changed(project, node, field, quantity(20, "degree_celsius"))
    else:
        workspace = project.domain_workspace
        # IDs, containment and reference roles retain meaning; storage enumeration
        # and descriptive presentation text cannot choose the coupling order.
        project = replace(
            project,
            description="A different presentation of the same physics",
            domain_workspace=replace(
                workspace,
                models=tuple(
                    replace(model, nodes=tuple(reversed(model.nodes)))
                    if model.id.startswith("electrothermal:")
                    else model
                    for model in reversed(workspace.models)
                ),
            ),
        )
    data = published(project, tmp_path)
    assert_accounting(data, p, discrete(p, 1, 10))
