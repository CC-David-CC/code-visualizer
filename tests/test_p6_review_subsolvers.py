"""Independent NUMERICAL-SUBSOLVER checks, not P6 end-to-end acceptance.

Thermal checks call the delivered CoupledSolver.thermal with an explicit numeric
ElectrothermalProblem. They deliberately do not run the Pint/DC preparation
constructor, the electrical participant, fixed-point coordinator, or publication.
The receiver is only a test harness for that existing method; production functions
are not patched. Axial checks call the actual solve_bar assembly/P3 solve directly,
not CAD validation, authoring, retained resources, or the GUI.
"""

import math
from dataclasses import asdict, replace
from types import SimpleNamespace

import numpy as np
import pytest

from code_visualizer.extensions.axial.assembly import BarElement, solve_bar
from code_visualizer.extensions.electrothermal.numerics import (
    AcceptedState,
    CoupledSolver,
    WindowIdentity,
)
from code_visualizer.extensions.electrothermal.problem import ElectrothermalProblem


def numeric_problem(**changes):
    p = ElectrothermalProblem(
        id="review:experiment",
        circuit_model_id="review:circuit-model",
        circuit_id="review:circuit",
        resistor_id="review:resistor",
        source_id="review:source",
        resistor_body_id="review:body",
        sink_body_id="review:sink",
        law_id="review:law",
        contact_id="review:contact",
        ambient_id="review:ambient",
        policy_id="review:policy",
        exchange_ids=("review:temperature", "review:heat"),
        resistance=10.0,
        alpha=0.004,
        reference_temperature=293.15,
        ambient_temperature=293.15,
        initial_resistor_temperature=293.15,
        initial_sink_temperature=293.15,
        resistor_capacity=10.0,
        sink_capacity=20.0,
        contact_conductance=0.2,
        ambient_conductance=0.1,
        duration=10.0,
        windows=10,
        max_iterations=50,
        evaluation_order="electrical_first",
        sample_every=1,
        checkpoint_every=5,
        preview_every=1,
        chunk_rows=10,
        temperature_scale=1.0,
        power_scale=1.0,
        energy_scale=1.0,
    )
    return replace(p, **changes)


@pytest.mark.parametrize("dt", [0.1, 1.0, 4.0])
@pytest.mark.parametrize("power", [0.0, 2.5])
@pytest.mark.parametrize(
    "fixture",
    [
        (10.0, 20.0, 0.2, 0.1, 0.0, 0.0, 1.0),
        (2.0, 30.0, 0.5, 0.04, 3.0, 7.0, 0.01),
        (50.0, 8.0, 1.0, 0.3, 12.0, 2.0, 100.0),
    ],
)
def test_actual_thermal_subsolve_matches_independent_elimination(dt, power, fixture):
    cr, cs, g, h, x, y, scale = fixture
    p = numeric_problem(
        duration=dt * 10,
        resistor_capacity=cr,
        sink_capacity=cs,
        contact_conductance=g,
        ambient_conductance=h,
        temperature_scale=scale,
    )
    base = AcceptedState(3, x, y, 7.0, 2.0)
    before = asdict(base)
    window = WindowIdentity("c" * 64, 4, p.time(4))
    receiver = SimpleNamespace(problem=p)
    result = CoupledSolver.thermal(receiver, window, base, power)
    # Scalar elimination written here; no production matrix/RHS helper reused.
    a, d = cr / dt + g, cs / dt + g + h
    b1, b2 = cr * x / dt + power, cs * y / dt
    det = a * d - g * g
    wanted = ((d * b1 + g * b2) / det, (a * b2 + g * b1) / det)
    assert (result.resistor_rise, result.sink_rise) == pytest.approx(wanted, rel=1e-10, abs=1e-10)
    assert result.window == window and asdict(base) == before
    assert CoupledSolver.thermal(receiver, window, base, power) == result
    energy = cr * (result.resistor_rise - x) + cs * (result.sink_rise - y)
    assert abs(energy - dt * (power - h * result.sink_rise)) <= 1e-9


@pytest.mark.parametrize("nodes", [3, 9, 17, 65])
@pytest.mark.parametrize("force", [0.0, -1000.0, 1000.0])
@pytest.mark.parametrize("heterogeneous", [False, True])
def test_actual_axial_assembly_matches_independent_series_compliance(nodes, force, heterogeneous):
    count = nodes - 1
    lengths = [0.1 / count] * count
    areas = [1e-4 * (1 + (0.1 * (i % 3) if heterogeneous else 0)) for i in range(count)]
    moduli = [2e11 * (1 + (0.05 * (i % 2) if heterogeneous else 0)) for i in range(count)]
    elements = tuple(
        BarElement(length, a, e) for length, a, e in zip(lengths, areas, moduli, strict=True)
    )
    result = solve_bar(
        elements, force, "review:bar", ("review:geometry", "review:material", "review:load")
    )
    wanted = [0.0]
    for length, a, e in zip(lengths, areas, moduli, strict=True):
        wanted.append(wanted[-1] + force * length / (a * e))
    assert result.displacement == pytest.approx(wanted, rel=1e-8, abs=1e-12)
    assert result.stress == pytest.approx([force / a for a in areas], rel=1e-8, abs=1e-12)
    assert result.element_force == pytest.approx([force] * count, rel=1e-8, abs=1e-12)
    assert result.reaction == pytest.approx(-force, rel=1e-8, abs=1e-12)
    assert result.energy == pytest.approx(0.5 * force * wanted[-1], rel=1e-8, abs=1e-12)
    matrix = np.asarray(result.stiffness)
    assert np.array_equal(matrix, matrix.T)
    expected = np.zeros(nodes)
    expected[0] = -force
    expected[-1] = force
    assert np.allclose(
        matrix @ np.asarray(result.displacement),
        expected,
        rtol=1e-8,
        atol=1e-8 * max(1, abs(force)),
    )
    assert result.solution.rank == count
    assert max(map(abs, result.solution.normalized_residuals)) <= 1e-10
    assert math.isfinite(result.energy) and result.energy >= 0
