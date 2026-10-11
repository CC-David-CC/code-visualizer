"""Conservative transfers and lineage are independent of notation and execution."""

from dataclasses import replace

import numpy as np
import pytest

from code_visualizer.extensions.adaptive_fields.mesh import Cell, Mesh, transfer


def test_cell_lineage_and_partition_survive_split_merge():
    base = Mesh.uniform("physical:interval", 16, 1.0)
    children = base.cells[3].children()
    refined = replace(base, cells=(*base.cells[:3], *children, *base.cells[4:]))
    assert refined.cell_ids[3] != base.cell_ids[3]
    assert refined.cell_ids[5:] == base.cell_ids[4:]
    assert np.all(np.diff(refined.faces) > 0)
    assert np.sum(refined.widths) == 1
    assert children[0].parent() == children[1].parent() == base.cells[3]
    assert base.cells[3] == Cell(3, 0, 0)


@pytest.mark.parametrize(
    "cells",
    [
        (Cell(0, 0, 0),) * 16,
        tuple(Cell(i, 0, 0) for i in range(15)),
        tuple(Cell(i, 0, 0) for i in reversed(range(16))),
    ],
)
def test_invalid_owned_partition_is_explicit(cells):
    with pytest.raises(ValueError, match="partition"):
        Mesh("region", 16, 1.0, cells)


def test_refinement_and_restriction_preserve_constant_and_integral():
    base = Mesh.uniform("region", 16, 1.0)
    finer = replace(base, cells=tuple(child for c in base.cells for child in c.children()))
    for original in (np.full(16, 7.0), np.array([1.0, 0.0] * 8)):
        before = original.copy()
        refined = transfer(base, finer, original)
        coarse = transfer(finer, base, refined)
        np.testing.assert_array_equal(original, before)
        np.testing.assert_allclose(coarse, original, rtol=0, atol=1e-14)
        assert abs(np.dot(refined, finer.widths) - np.dot(original, base.widths)) < 1e-14
        assert np.min(refined) >= 0
        assert not refined.flags.writeable


def test_local_linear_reconstruction_has_exact_cell_integrals():
    base = Mesh.uniform("region", 16, 1.0)
    original = 2 + base.centers
    cells = (*base.cells[:5], *base.cells[5].children(), *base.cells[6:])
    finer = replace(base, cells=cells)
    refined = transfer(base, finer, original)
    np.testing.assert_allclose(refined[5:7], 2 + finer.centers[5:7], rtol=0, atol=1e-14)


def test_repeated_transfer_does_not_rename_original_cells_or_drift_mass():
    base = Mesh.uniform("region", 16, 1.0)
    finer = replace(base, cells=(*base.cells[:4], *base.cells[4].children(), *base.cells[5:]))
    values = 1 + np.sin(2 * np.pi * base.centers)
    mass = float(np.dot(values, base.widths))
    for _ in range(50):
        values = transfer(finer, base, transfer(base, finer, values))
    assert float(np.dot(values, base.widths)) == pytest.approx(mass, abs=1e-13)
    assert base.cell_ids[4] == "region:cell:4:0:0"


def test_incompatible_transfer_never_changes_input():
    base = Mesh.uniform("region", 16, 1.0)
    original = np.ones(16)
    other = Mesh.uniform("other-region", 16, 1.0)
    with pytest.raises(ValueError, match="incompatible"):
        transfer(base, other, original)
    np.testing.assert_array_equal(original, np.ones(16))
