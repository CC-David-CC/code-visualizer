"""Actual element equilibrium, with the existing P3 scaled linear solve."""

from dataclasses import dataclass
from math import isfinite

from code_visualizer.extensions.axial.domain import quantity
from code_visualizer.extensions.foundations.equation_backend import LinearSolution, solve_linear
from code_visualizer.extensions.foundations.equation_compiler import (
    LinearSystem,
    Residual,
    Variable,
)
from code_visualizer.extensions.foundations.unit_algebra import QuantityKind


@dataclass(frozen=True, slots=True)
class BarElement:
    length: float
    area: float
    young_modulus: float

    def __post_init__(self) -> None:
        if any(
            type(v) not in (int, float) or not isfinite(v) or v <= 0
            for v in (self.length, self.area, self.young_modulus)
        ):
            raise ValueError("Bar elements require positive finite SI length, area and modulus")


@dataclass(frozen=True, slots=True)
class Equilibrium:
    displacement: tuple[float, ...]
    stress: tuple[float, ...]
    element_force: tuple[float, ...]
    stiffness: tuple[tuple[float, ...], ...]
    right: tuple[float, ...]
    reaction: float
    energy: float
    solution: LinearSolution


def solve_bar(
    elements: tuple[BarElement, ...], force: float, object_id: str, origins: tuple[str, ...]
) -> Equilibrium:
    import numpy as np

    if not 2 <= len(elements) <= 64 or not isfinite(force):
        raise ValueError("The axial system requires 2..64 elements and a finite force")
    count = len(elements) + 1
    matrix = np.zeros((count, count), dtype=np.float64)
    right = np.zeros(count, dtype=np.float64)
    right[-1] = force
    for index, element in enumerate(elements):
        stiffness = element.young_modulus * element.area / element.length
        matrix[index : index + 2, index : index + 2] += stiffness * np.asarray(
            ((1.0, -1.0), (-1.0, 1.0))
        )
    residual_scale = max(1.0, abs(force))
    system = LinearSystem(
        object_id,
        tuple(
            Variable(
                object_id + f":u:{i}",
                f"Axial displacement {i}",
                quantity(1e-5),
                QuantityKind.INTERVAL,
            )
            for i in range(1, count)
        ),
        tuple(
            Residual(
                object_id + f":equilibrium:{i}",
                object_id,
                f"Node {i} force balance",
                quantity(residual_scale, "newton"),
                residual_scale,
                1.0,
                origins,
            )
            for i in range(1, count)
        ),
        tuple(tuple(float(v) for v in row) for row in matrix[1:, 1:]),
        tuple(float(v) for v in right[1:]),
        1e-12,
        1e-10,
        1e12,
    )
    solved = solve_linear(system)
    displacement = np.asarray((0.0, *solved.values))
    stresses, forces, energy = [], [], 0.0
    for i, element in enumerate(elements):
        delta = float(displacement[i + 1] - displacement[i])
        stress = element.young_modulus * delta / element.length
        axial_force = stress * element.area
        stresses.append(stress)
        forces.append(axial_force)
        energy += 0.5 * axial_force * delta
    reaction = float((matrix @ displacement - right)[0])
    if not isfinite(energy) or energy < 0:
        raise ValueError("The axial equilibrium has invalid elastic energy")
    return Equilibrium(
        tuple(float(v) for v in displacement),
        tuple(stresses),
        tuple(forces),
        tuple(tuple(float(v) for v in row) for row in matrix),
        tuple(float(v) for v in right),
        reaction,
        energy,
        solved,
    )
