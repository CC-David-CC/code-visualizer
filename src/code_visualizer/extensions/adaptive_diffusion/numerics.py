"""Conservative periodic finite volumes; standard sparse solves and immutable results."""

from __future__ import annotations

from math import isfinite
from typing import TYPE_CHECKING

from code_visualizer.extensions.adaptive_fields.mesh import Mesh

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


def diffuse(
    mesh: Mesh, values: NDArray[np.float64], coefficient: float, dt: float
) -> NDArray[np.float64]:
    import numpy as np
    from scipy.sparse import coo_matrix  # type: ignore[import-untyped]
    from scipy.sparse.linalg import spsolve  # type: ignore[import-untyped]

    if (
        type(coefficient) not in (int, float)
        or not isfinite(coefficient)
        or coefficient <= 0
        or type(dt) not in (int, float)
        or not isfinite(dt)
        or dt <= 0
    ):
        raise ValueError("Diffusion coefficient and timestep must be finite and positive")
    initial = np.asarray(values, dtype=np.float64)
    count = len(mesh.cells)
    if initial.shape != (count,) or not np.isfinite(initial).all() or np.any(initial < 0):
        raise ValueError("Diffusion requires finite nonnegative cell averages")
    widths = mesh.widths
    conductance = coefficient / ((widths + np.roll(widths, -1)) / 2)
    rows = np.arange(count)
    data = np.concatenate(
        (
            widths + dt * (conductance + np.roll(conductance, 1)),
            -dt * conductance,
            -dt * np.roll(conductance, 1),
        )
    )
    matrix = coo_matrix(
        (data, (np.tile(rows, 3), np.concatenate((rows, (rows + 1) % count, (rows - 1) % count)))),
        shape=(count, count),
    ).tocsc()
    rhs = widths * initial
    result = np.asarray(spsolve(matrix, rhs), dtype=np.float64)
    scale = max(float(np.max(np.abs(rhs))), 1e-300)
    residual = float(np.max(np.abs(matrix @ result - rhs))) / scale
    if not np.isfinite(result).all() or np.any(result < 0) or residual > 1e-11:
        raise ValueError("Adaptive diffusion solution failed residual/positivity validation")
    mass_scale = max(float(np.dot(widths, np.abs(initial))), 1e-300)
    if abs(float(np.dot(widths, result - initial))) > 1e-12 * mass_scale:
        raise ValueError("Adaptive diffusion solution violates mass conservation")
    result.setflags(write=False)
    return result
