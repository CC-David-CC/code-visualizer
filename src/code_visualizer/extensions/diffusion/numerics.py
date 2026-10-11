"""A bounded fixed-step Crank-Nicolson adapter, with an actual predictor/corrector."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from code_visualizer.extensions.diffusion.problem import DiffusionProblem

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class StepResult:
    accepted: NDArray[np.float64]
    dimensional_residual: float
    residual_scale: float


class CrankNicolson:
    """Worker-owned transient arrays. Only complete accepted vectors can be published."""

    def __init__(self, problem: DiffusionProblem):
        import numpy as np
        import scipy  # type: ignore[import-untyped]

        self.problem = problem
        self.numerical_identity = (
            f"numpy={np.__version__};scipy={scipy.__version__};float64-le;cn-v1"
        )
        self.banded = np.zeros((3, problem.nodes - 2), dtype=np.float64)
        self.banded[0, 1:] = -problem.ratio / 2
        self.banded[1, :] = 1 + problem.ratio
        self.banded[2, :-1] = -problem.ratio / 2

    def difference(self, state: NDArray[np.float64]) -> NDArray[np.float64]:
        return self.problem.ratio * (state[:-2] - 2 * state[1:-1] + state[2:])

    def predictor(self, state: NDArray[np.float64]) -> NDArray[np.float64]:
        predicted = state.copy()
        predicted[1:-1] += self.difference(state)
        return predicted

    def correct(self, state: NDArray[np.float64], predicted: NDArray[np.float64]) -> StepResult:
        import numpy as np
        from scipy.linalg import solve_banded  # type: ignore[import-untyped]

        delta = solve_banded(
            (1, 1),
            self.banded,
            0.5 * self.difference(predicted - state),
            overwrite_ab=False,
            overwrite_b=False,
            check_finite=True,
        )
        candidate = predicted.copy()
        candidate[1:-1] += delta
        residual = (
            candidate[1:-1]
            - state[1:-1]
            - 0.5 * (self.difference(candidate) + self.difference(state))
        )
        dimensional = float(np.max(np.abs(residual)))
        scale = max(
            self.problem.scale, float(np.max(np.abs(state))), float(np.max(np.abs(candidate)))
        )
        if (
            not np.isfinite(candidate).all()
            or not np.isfinite(dimensional)
            or dimensional / scale > 1e-11
        ):
            raise ValueError("Diffusion step failed its finite normalized residual gate")
        if candidate[0] != 0 or candidate[-1] != 0 or float(candidate.min()) < -scale * 1e-12:
            raise ValueError("Diffusion step violated the declared boundary/positivity fragment")
        if float(np.linalg.norm(candidate)) > float(np.linalg.norm(state)) + scale * 1e-12:
            raise ValueError("Diffusion step increased the discrete field norm")
        return StepResult(candidate, dimensional, scale)
