"""Immutable dyadic cell identity and conservative transfers, independent of an editor."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

MAX_CELLS = 512
MAX_LEVEL = 5


@dataclass(frozen=True, slots=True)
class Cell:
    base: int
    level: int
    offset: int

    def __post_init__(self) -> None:
        if (
            any(type(value) is not int for value in (self.base, self.level, self.offset))
            or self.base < 0
            or not 0 <= self.level <= MAX_LEVEL
            or not 0 <= self.offset < 1 << self.level
        ):
            raise ValueError("Invalid dyadic cell partition address")

    def children(self) -> tuple[Cell, Cell]:
        if self.level == MAX_LEVEL:
            raise ValueError("Maximum dyadic partition level")
        return (
            Cell(self.base, self.level + 1, 2 * self.offset),
            Cell(self.base, self.level + 1, 2 * self.offset + 1),
        )

    def parent(self) -> Cell:
        if self.level == 0:
            raise ValueError("A base partition cell has no parent")
        return Cell(self.base, self.level - 1, self.offset // 2)

    @property
    def start(self) -> int:
        return (self.base << MAX_LEVEL) + (self.offset << (MAX_LEVEL - self.level))

    @property
    def stop(self) -> int:
        return self.start + (1 << (MAX_LEVEL - self.level))


@dataclass(frozen=True, slots=True)
class Mesh:
    region_id: str
    base_cells: int
    length: float
    cells: tuple[Cell, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.region_id, str)
            or not self.region_id
            or len(self.region_id.encode()) > 1024
            or type(self.base_cells) is not int
            or not 16 <= self.base_cells <= MAX_CELLS
            or type(self.length) not in (float, int)
            or not isfinite(self.length)
            or self.length <= 0
            or type(self.cells) is not tuple
            or not self.base_cells <= len(self.cells) <= MAX_CELLS
        ):
            raise ValueError("Invalid bounded cell partition")
        end = 0
        for cell in self.cells:
            if not isinstance(cell, Cell) or cell.start != end or cell.base >= self.base_cells:
                raise ValueError("Cell partition has gaps, overlap or inconsistent ordering")
            end = cell.stop
        if end != self.base_cells << MAX_LEVEL:
            raise ValueError("Cell partition does not cover the physical interval")
        if any(
            abs(left.level - right.level) > 1
            for left, right in zip(self.cells, (*self.cells[1:], self.cells[0]), strict=True)
        ):
            raise ValueError("Cell partition violates periodic two-to-one balance")

    @classmethod
    def uniform(cls, region_id: str, cells: int, length: float) -> Mesh:
        return cls(region_id, cells, length, tuple(Cell(i, 0, 0) for i in range(cells)))

    @property
    def cell_ids(self) -> tuple[str, ...]:
        return tuple(
            f"{self.region_id}:cell:{cell.base}:{cell.level}:{cell.offset}" for cell in self.cells
        )

    @property
    def faces(self) -> NDArray[np.float64]:
        import numpy as np

        result = np.array([0, *(cell.stop for cell in self.cells)], dtype=np.float64)
        result *= self.length / (self.base_cells << MAX_LEVEL)
        result.setflags(write=False)
        return result

    @property
    def widths(self) -> NDArray[np.float64]:
        import numpy as np

        result = np.diff(self.faces)
        result.setflags(write=False)
        return result

    @property
    def centers(self) -> NDArray[np.float64]:
        faces = self.faces
        result = (faces[:-1] + faces[1:]) / 2
        result.setflags(write=False)
        return result


def slopes(mesh: Mesh, values: NDArray[np.float64]) -> NDArray[np.float64]:
    """Periodic minmod reconstruction; preserves each parent's cell integral."""
    import numpy as np

    widths = mesh.widths
    if values.ndim == 2:
        widths = widths[:, None]
    left = (values - np.roll(values, 1, axis=0)) / ((widths + np.roll(widths, 1, axis=0)) / 2)
    right = (np.roll(values, -1, axis=0) - values) / ((widths + np.roll(widths, -1, axis=0)) / 2)
    return np.where(
        np.signbit(left) == np.signbit(right),
        np.sign(left) * np.minimum(np.abs(left), np.abs(right)),
        0.0,
    )


def transfer(source: Mesh, target: Mesh, values: NDArray[np.float64]) -> NDArray[np.float64]:
    """One-level conservative prolongation/restriction; no identity by array index."""
    import numpy as np

    if (source.region_id, source.base_cells, source.length) != (
        target.region_id,
        target.base_cells,
        target.length,
    ):
        raise ValueError("Transfer has incompatible physical support")
    original = np.asarray(values, dtype=np.float64)
    if original.ndim not in (1, 2) or original.shape[0] != len(source.cells):
        raise ValueError("Transfer has incompatible value shape")
    if not np.isfinite(original).all():
        raise ValueError("Transfer requires finite cell averages")
    indices = {cell: i for i, cell in enumerate(source.cells)}
    reconstruction = slopes(source, original)
    widths = source.widths
    output = []
    for cell in target.cells:
        if cell in indices:
            value = original[indices[cell]]
        elif cell.level and cell.parent() in indices:
            index = indices[cell.parent()]
            sign = -1 if cell.offset % 2 == 0 else 1
            value = original[index] + sign * reconstruction[index] * widths[index] / 4
        elif cell.level < MAX_LEVEL and all(c in indices for c in cell.children()):
            left, right = (indices[c] for c in cell.children())
            value = (original[left] * widths[left] + original[right] * widths[right]) / (
                widths[left] + widths[right]
            )
        else:
            raise ValueError("Transfer has incompatible or incomplete parent/child mapping")
        output.append(value)
    result = np.array(output, dtype=np.float64)
    before = np.tensordot(source.widths, original, axes=(0, 0))
    after = np.tensordot(target.widths, result, axes=(0, 0))
    scale = np.maximum(np.tensordot(source.widths, np.abs(original), axes=(0, 0)), 1e-300)
    if not np.isfinite(result).all() or np.any(np.abs(after - before) > 1e-12 * scale):
        raise ValueError("Conservative transfer failed its integral check")
    result.setflags(write=False)
    return result
