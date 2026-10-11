"""No native stand-in: these tests prove only the dimensional exchange algebra."""

from dataclasses import replace

import numpy as np
import pytest
from test_hybrid_gas_continuum import gas, uniform

from code_visualizer.domain.identifiers import ContractKind
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.hybrid_gas.continuum import GasGrid, Wall, advance
from code_visualizer.extensions.hybrid_gas.coupling import Slab, correct
from code_visualizer.extensions.hybrid_gas.interface import (
    ConservedAmount,
    ExchangeWindow,
    FluxUnits,
    IntegratedFlux,
    Interface,
    ReservoirState,
)
from code_visualizer.extensions.hybrid_gas.thermodynamics import InvalidGasState
from code_visualizer.extensions.hybrid_gas.units import BUNDLE, catalog, quantity, units_bundle
from code_visualizer.extensions.publication import publication_manifest
from code_visualizer.extensions.registry import DomainExtensionRegistry


def window(normal=-1):
    return ExchangeWindow(
        Interface(
            "a" * 64,
            "b" * 64,
            "policy",
            "slab",
            f"face:{normal}",
            "laboratory",
            "y",
            normal,
            quantity(1e-10, "square_meter"),
            quantity(1e-20, "kilogram"),
            FluxUnits.si(),
        ),
        40,
        42,
        quantity(7e-9, "second"),
    )


def amount(mass, vx, vy, vz, specific_energy):
    return ConservedAmount(mass, (mass * vx, mass * vy, mass * vz), mass * specific_energy)


def packet(w):
    return IntegratedFlux(
        w,
        amount(3e-20, 21, 110 * -w.interface.outward_normal, -7, 60000),
        amount(2e-20, -3, 95 * w.interface.outward_normal, 8, 61000),
        3,
        2,
    )


def test_unit_bundle_resolves_the_declared_public_closure():
    registry = builtin_registry()
    manifest = publication_manifest(registry, BUNDLE.id, BUNDLE.version)
    references = {(value.kind, value.id) for value in manifest.references}
    assert (ContractKind.UNIT, "foundation.units.si:kilogram") in references
    assert (ContractKind.UNIT, "foundation.units.si:second") in references
    catalog().validate_reference(quantity(1, "pascal_second").unit)
    with pytest.raises(ValueError, match="already registered"):
        DomainExtensionRegistry((*registry.bundles(), units_bundle()))


def test_integral_direction_has_no_second_multiplication_by_time():
    for normal in (-1, 1):
        w = window(normal)
        flux = packet(w)
        expected = -normal * (flux.incoming.array() - flux.outgoing.array())
        np.testing.assert_array_equal(flux.admit(w), expected)
        assert abs(flux.admit(w)[0]) == pytest.approx(1e-20, rel=1e-14, abs=0)


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_digest", "c" * 64),
        ("law_digest", "d" * 64),
        ("policy_id", "other-policy"),
        ("region_id", "other-region"),
        ("face_id", "other-face"),
        ("frame_id", "body"),
        ("axis_id", "z"),
        ("outward_normal", 1),
        ("area", quantity(2e-10, "square_meter")),
        ("particle_mass", quantity(2e-20, "kilogram")),
    ],
)
def test_wrong_interface_cannot_be_reused_even_when_flux_numbers_match(field, value):
    w = window()
    other = replace(w, interface=replace(w.interface, **{field: value}))
    with pytest.raises(ValueError, match="GAS_INTERFACE_MISMATCH"):
        packet(w).admit(other)


def test_wrong_time_units_weight_or_dimension_are_rejected():
    w, flux = window(), packet(window())
    for other in (
        replace(w, first_tick=39),
        replace(w, last_tick=43),
        replace(w, quantum=quantity(8e-9, "second")),
    ):
        with pytest.raises(ValueError, match="GAS_INTERFACE_MISMATCH"):
            flux.admit(other)
    with pytest.raises(ValueError, match="GAS_INTERFACE_MISMATCH"):
        replace(w.interface, units=replace(w.interface.units, mass=quantity(1, "gram").unit))
    with pytest.raises(ValueError, match="dimensions"):
        replace(w.interface.units, energy=quantity(1, "watt").unit)
    with pytest.raises(ValueError, match="weight"):
        replace(flux, emitted_particles=4)
    with pytest.raises(ValueError, match="SI time"):
        replace(w, quantum=quantity(7e-6, "millisecond"))


def test_reservoir_carries_state_in_its_exact_frame_and_units():
    state = ReservoirState(
        window(),
        quantity(0.004, "kilogram_per_cubic_meter"),
        quantity(273.15, "kelvin"),
        tuple(quantity(v, "meter_per_second") for v in (20, 0, -7)),
    )
    assert state.window.interface.frame_id == "laboratory"
    with pytest.raises(ValueError, match="positive SI"):
        replace(state, temperature=quantity(0, "degree_celsius"))
    with pytest.raises(ValueError, match="three SI"):
        replace(state, velocity=(quantity(1, "meter"),) * 3)


def coupled_fixture():
    law, grid = gas(), GasGrid(0.002, 1e-10, 32)
    slab = Slab(12, 20, grid)
    q = uniform(law, grid)
    windows = (window(-1), window(1))
    transfers = tuple(packet(w) for w in windows)
    low, high = (p.admit(w) for p, w in zip(transfers, windows, strict=True))
    particle = q[12:20].copy()
    particle += (low - high) / (grid.volume * slab.cells)
    provisional = advance(law, grid, q, 14e-9, (Wall(273.15, -40), Wall(273.15, 40)))
    return law, slab, q, provisional, particle, windows, transfers


def test_replacement_cancels_internal_exchange_without_double_counting():
    args = coupled_fixture()
    base = args[2].copy()
    result = correct(*args)
    np.testing.assert_array_equal(args[2], base)
    np.testing.assert_allclose(result.particle_residual, 0, atol=1e-12)
    np.testing.assert_allclose(result.system_residual, 0, atol=1e-12)
    np.testing.assert_array_equal(result.values[12:20], args[4])
    assert not result.values.flags.writeable
    assert result.wall_transfer[4] > 0


def test_leak_or_incoherent_base_rejects_the_candidate():
    law, slab, q, provisional, particle, windows, transfers = coupled_fixture()
    before = q.copy()
    broken = particle.copy()
    broken[3, 4] *= 1.001
    with pytest.raises(InvalidGasState, match="do not balance"):
        correct(law, slab, q, provisional, broken, windows, transfers)
    changed_base = q.copy()
    changed_base[0, 1] += 0.01
    with pytest.raises(InvalidGasState, match="immutable base"):
        correct(law, slab, changed_base, provisional, particle, windows, transfers)
    np.testing.assert_array_equal(q, before)
