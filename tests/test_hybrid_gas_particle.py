"""Real bounded native participant tests; full host/publication proof is separate."""

import sys
from dataclasses import replace

import numpy as np
import pytest
from test_hybrid_gas_continuum import gas

from code_visualizer.extensions.hybrid_gas.continuum import Wall
from code_visualizer.extensions.hybrid_gas.coupling import conservation_scale
from code_visualizer.extensions.hybrid_gas.interface import (
    ExchangeWindow,
    FluxUnits,
    Interface,
    ReservoirState,
)
from code_visualizer.extensions.hybrid_gas.native_api import (
    BINARY_SHA,
    NativeUnavailable,
    installation,
)
from code_visualizer.extensions.hybrid_gas.particle import (
    SPECIES_MASS,
    InitialGasCell,
    ParticleBox,
    ParticleDefinition,
    transfers,
)
from code_visualizer.extensions.hybrid_gas.units import quantity

WINDOWS = pytest.mark.skipif(
    sys.platform != "win32",
    reason="Pinned SPARTA native runtime is Windows x86-64; no other platform qualification",
)


def definition(boundary="periodic", *, cells=1, start_tick=0):
    height, area, number_density = 0.0005, 1e-10, 7.07043e22
    fnum = number_density * height * area / 5000
    interfaces = (
        tuple(
            Interface(
                "a" * 64,
                "b" * 64,
                "policy",
                "slab",
                f"face:{normal}",
                "laboratory",
                "y",
                normal,
                quantity(area, "square_meter"),
                quantity(SPECIES_MASS * fnum, "kilogram"),
                FluxUnits.si(),
            )
            for normal in (-1, 1)
        )
        if boundary == "reservoir"
        else ()
    )
    initial = tuple(
        InitialGasCell(
            i * height / cells,
            (i + 1) * height / cells,
            number_density,
            273.15,
            (float(10 * i), 0.0, 0.0),
        )
        for i in range(cells)
    )
    walls = (Wall(260, -20, 5), Wall(290, 30, -7)) if boundary == "walls" else ()
    return ParticleDefinition(
        gas(),
        67891,
        0.0,
        height,
        area,
        50,
        fnum,
        7e-9,
        initial,
        boundary,
        walls,
        start_tick,
        20000,
        4000,
        interfaces,
    )


def states(box, steps, offset=0):
    result = []
    for i, interface in enumerate(box.definition.interfaces):
        w = ExchangeWindow(
            interface, box.tick, box.tick + steps, quantity(box.definition.time_step, "second")
        )
        result.append(
            ReservoirState(
                w,
                quantity(7.07043e22 * SPECIES_MASS, "kilogram_per_cubic_meter"),
                quantity(260 + 30 * i, "kelvin"),
                tuple(
                    quantity(v, "meter_per_second") for v in (-20 + 50 * i + offset, 0, 5 - 12 * i)
                ),
            )
        )
    return tuple(result)


@WINDOWS
def test_installed_native_identity_is_pinned_and_has_corresponding_source():
    import json
    import zipfile
    from hashlib import sha256

    runtime = installation()
    assert sha256(runtime.binary.read_bytes()).hexdigest() == BINARY_SHA
    metadata = json.loads((runtime.binary.parent / "manifest.json").read_text(encoding="utf-8"))
    archive = runtime.binary.parent / metadata["source_archive"]
    assert sha256(archive.read_bytes()).hexdigest() == metadata["files"][archive.name]
    with zipfile.ZipFile(archive) as source:
        for path, expected in metadata["corresponding_source_inventory"].items():
            assert sha256(source.read(path)).hexdigest() == expected
        assert "src/cv_observation.cpp" in source.namelist()
        assert "cmake/CMakeLists.txt" in source.namelist()


def test_other_platform_is_an_explicit_missing_capability(monkeypatch):
    monkeypatch.setattr(
        "code_visualizer.extensions.hybrid_gas.native_api.sys.platform", "unsupported"
    )
    with pytest.raises(NativeUnavailable, match="GAS_NATIVE_PLATFORM"):
        installation()


@WINDOWS
@pytest.mark.parametrize("boundary", ["periodic", "walls"])
def test_native_closed_box_mass_all_momenta_and_energy_ledger(boundary):
    box = ParticleBox(definition(boundary))
    try:
        before = box.moments(1)[0, 1:6]
        initial = before.copy()
        for _ in range(30):
            window = box.advance(10, 16)
            after = window.moments[:, 1:6].sum(axis=0)
            residual = (after - before + window.outgoing[:, 1:].sum(axis=0)) / conservation_scale(
                gas(), initial
            )
            np.testing.assert_allclose(residual, 0, atol=1e-10)
            assert not window.moments.flags.writeable
            before = after
        assert box.native.observation()[1] == 300
    finally:
        box.close()


@WINDOWS
def test_measured_native_reservoir_transfers_close_every_owned_window():
    box = ParticleBox(definition("reservoir"))
    try:
        before = box.moments(16)[:, 1:6].sum(axis=0)
        initial = before.copy()
        for i in range(60):
            inputs = states(box, 4, offset=3 * (i // 20))
            window = box.advance(4, 16, inputs)
            packets = transfers(window, tuple(state.window for state in inputs))
            oriented = [
                packet.admit(state.window) for packet, state in zip(packets, inputs, strict=True)
            ]
            after = window.moments[:, 1:6].sum(axis=0)
            residual = (after - before - oriented[0] + oriented[1]) / conservation_scale(
                gas(), initial
            )
            np.testing.assert_allclose(residual, 0, atol=1e-10)
            before = after
    finally:
        box.close()


@WINDOWS
def test_second_face_mismatch_rejects_before_mutating_either_native_reservoir():
    box = ParticleBox(definition("reservoir"))
    try:
        original = box.native.observation()
        inputs = states(box, 2)
        wrong = replace(
            inputs[1],
            window=replace(
                inputs[1].window,
                interface=replace(inputs[1].window.interface, frame_id="other-frame"),
            ),
        )
        with pytest.raises(ValueError, match="GAS_INTERFACE_MISMATCH"):
            box.advance(2, 16, (inputs[0], wrong))
        np.testing.assert_array_equal(box.native.observation(), original)
        box.advance(2, 16, inputs)
        assert box.tick == 2
    finally:
        box.close()


@WINDOWS
def test_spatial_initialization_and_complete_input_reconstruction_at_nonzero_time():
    snapshots, ledgers = [], []
    d = definition("reservoir", cells=4, start_tick=80)
    for _ in range(2):
        box = ParticleBox(d)
        try:
            initial = box.native.observation()
            rows = []
            for i in range(30):
                window = box.advance(4, 16, states(box, 4, offset=5 * (i // 10)))
                rows.append(
                    np.r_[window.incoming.ravel(), window.outgoing.ravel(), window.moments.ravel()]
                )
            snapshots.append((initial, box.native.observation()))
            ledgers.append(np.array(rows))
        finally:
            box.close()
    np.testing.assert_array_equal(snapshots[0][0], snapshots[1][0])
    np.testing.assert_array_equal(snapshots[0][1], snapshots[1][1])
    np.testing.assert_array_equal(ledgers[0], ledgers[1])


@WINDOWS
def test_step_budget_failure_leaves_native_state_unadvanced():
    box = ParticleBox(replace(definition(), maximum_steps=3))
    try:
        initial = box.native.observation()
        with pytest.raises(ValueError, match="GAS_STEP_BUDGET"):
            box.advance(4, 16)
        np.testing.assert_array_equal(box.native.observation(), initial)
    finally:
        box.close()
