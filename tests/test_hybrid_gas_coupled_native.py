"""Real native/continuum exchange; conservation is distinct from mean-flow accuracy."""

from dataclasses import replace

import numpy as np
import pytest
from test_hybrid_gas_continuum import gas, uniform
from test_hybrid_gas_particle import WINDOWS

from code_visualizer.extensions.hybrid_gas.continuum import GasGrid, Wall, advance
from code_visualizer.extensions.hybrid_gas.coupling import Slab, conservation_scale, correct
from code_visualizer.extensions.hybrid_gas.interface import (
    ExchangeWindow,
    FluxUnits,
    Interface,
    ReservoirState,
)
from code_visualizer.extensions.hybrid_gas.model_transfer import activate
from code_visualizer.extensions.hybrid_gas.particle import (
    InitialGasCell,
    ParticleBox,
    ParticleDefinition,
    transfers,
)
from code_visualizer.extensions.hybrid_gas.units import quantity


def setup(velocity=(0.0, 0.0, 0.0)):
    law, grid = gas(), GasGrid(0.002, 1e-10, 64)
    slab = Slab(24, 40, grid)
    low, high = slab.first_cell * grid.spacing, slab.stop_cell * grid.spacing
    density = 7.07043e22
    fnum = density * (high - low) * grid.area / 5000
    interfaces = tuple(
        Interface(
            "a" * 64,
            "b" * 64,
            "policy",
            "slab",
            f"face:{normal}",
            "laboratory",
            "y",
            normal,
            quantity(grid.area, "square_meter"),
            quantity(law.species_mass * fnum, "kilogram"),
            FluxUnits.si(),
        )
        for normal in (-1, 1)
    )
    definition = ParticleDefinition(
        law,
        127453,
        low,
        high,
        grid.area,
        50,
        fnum,
        7e-9,
        (InitialGasCell(low, high, density, 273.15, velocity),),
        "reservoir",
        interfaces=interfaces,
    )
    return law, slab, uniform(law, grid, velocity), interfaces, definition


def inputs(law, slab, q, box, interfaces, steps):
    w = law.primitive(q)
    result = []
    for face, index in zip(interfaces, (slab.first_cell - 1, slab.stop_cell), strict=True):
        window = ExchangeWindow(
            face, box.tick, box.tick + steps, quantity(box.definition.time_step, "second")
        )
        result.append(
            ReservoirState(
                window,
                quantity(float(w[index, 0]), "kilogram_per_cubic_meter"),
                quantity(float(law.temperature(w[index : index + 1])[0]), "kelvin"),
                tuple(quantity(float(v), "meter_per_second") for v in w[index, 1:4]),
            )
        )
    return tuple(result)


@WINDOWS
@pytest.mark.parametrize("velocity", [(0.0, 0.0, 0.0), (20.0, 0.0, -7.0)])
def test_fixed_interface_real_particle_exchange_conserves_every_component(velocity):
    law, slab, coarse, faces, definition = setup(velocity)
    box = ParticleBox(definition)
    try:
        original = coarse.copy()
        transfer = activate(law, slab, coarse, box, faces)
        np.testing.assert_array_equal(coarse, original)
        np.testing.assert_allclose(transfer.normalized_residual, 0, atol=1e-12)
        assert np.any(transfer.realized_difference != 0)
        q = transfer.after
        initial = q.sum(axis=0) * slab.grid.volume
        wall_total = np.zeros(5)
        walls = (
            Wall(273.15, -40 + velocity[0], velocity[2]),
            Wall(273.15, 40 + velocity[0], velocity[2]),
        )
        for _ in range(500):
            reservoir = inputs(law, slab, q, box, faces, 2)
            provisional = advance(law, slab.grid, q, 14e-9, walls)
            native = box.advance(2, slab.cells, reservoir)
            windows = tuple(state.window for state in reservoir)
            accepted = correct(
                law,
                slab,
                q,
                provisional,
                native.moments[:, 1:6] / slab.grid.volume,
                windows,
                transfers(native, windows),
            )
            np.testing.assert_allclose(accepted.particle_residual, 0, atol=1e-10)
            np.testing.assert_allclose(accepted.system_residual, 0, atol=1e-10)
            wall_total += accepted.wall_transfer
            q = accepted.values
        residual = (q.sum(axis=0) * slab.grid.volume - initial - wall_total) / conservation_scale(
            law, initial
        )
        np.testing.assert_allclose(residual, 0, atol=1e-10)
        assert box.tick == 1000
        assert not q.flags.writeable
    finally:
        box.close()


@WINDOWS
def test_wrong_fine_mapping_preserves_original_model_and_native_input():
    law, slab, coarse, faces, definition = setup()
    box = ParticleBox(definition)
    try:
        original, native = coarse.copy(), box.native.observation()
        with pytest.raises(ValueError, match="GAS_TRANSFER_INCOMPATIBLE"):
            activate(law, replace(slab, first_cell=23), coarse, box, faces)
        wrong = (replace(faces[0], frame_id="body"), faces[1])
        with pytest.raises(ValueError, match="GAS_TRANSFER_INCOMPATIBLE"):
            activate(law, slab, coarse, box, wrong)
        np.testing.assert_array_equal(coarse, original)
        np.testing.assert_array_equal(box.native.observation(), native)
    finally:
        box.close()
