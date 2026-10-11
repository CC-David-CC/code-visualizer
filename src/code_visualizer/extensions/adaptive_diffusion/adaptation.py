"""Deterministic, bounded, conservative marking on one immutable accepted support."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from code_visualizer.extensions.adaptive_diffusion.problem import AdaptiveError, AdaptiveProblem
from code_visualizer.extensions.adaptive_fields.mesh import Cell, Mesh, transfer

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


def indicator(p: AdaptiveProblem, mesh: Mesh, values: NDArray[np.float64]) -> NDArray[np.float64]:
    import numpy as np

    widths = mesh.widths
    left = (values - np.roll(values, 1)) / ((widths + np.roll(widths, 1)) / 2)
    right = (np.roll(values, -1) - values) / ((widths + np.roll(widths, -1)) / 2)
    dimensional = widths * np.abs(right - left) / 8
    eta = dimensional / (
        p.policy.spatial_atol + p.policy.spatial_rtol * np.maximum(np.abs(values), p.scale)
    )
    if not np.isfinite(eta).all():
        raise AdaptiveError(
            "ADAPTIVE_INDICATOR", "Spatial indicator exceeds the finite fragment", p.field_id
        )
    eta.setflags(write=False)
    return eta


def _partition(mesh: Mesh, refine: set[Cell], merge: set[Cell]) -> tuple[Cell, ...]:
    result = []
    for cell in mesh.cells:
        parent = cell.parent() if cell.level else None
        if parent in merge:
            if cell.offset % 2 == 0:
                assert parent is not None
                result.append(parent)
        elif cell in refine:
            result.extend(cell.children())
        else:
            result.append(cell)
    return tuple(result)


def balanced_partition(
    p: AdaptiveProblem, mesh: Mesh, refine: set[Cell], merge: set[Cell]
) -> tuple[Mesh, set[Cell], set[Cell]]:
    """Balance propagation is mandatory; optional coarsening may be deferred."""
    refine, merge = refine.copy(), merge.copy()
    for _ in range(7):
        if any(cell.level >= p.policy.maximum_level for cell in refine):
            raise AdaptiveError(
                "ADAPTIVE_LEVEL_BUDGET",
                "Required fidelity exceeds the maximum cell level",
                p.policy_id,
            )
        cells = _partition(mesh, refine, merge)
        changed = False
        for left, right in zip(cells, (*cells[1:], cells[0]), strict=True):
            if abs(left.level - right.level) <= 1:
                continue
            coarse = left if left.level < right.level else right
            if coarse in merge:
                merge.remove(coarse)
            else:
                refine.add(coarse)
            changed = True
        if not changed:
            if len(cells) > p.policy.maximum_cells:
                raise AdaptiveError(
                    "ADAPTIVE_CELL_BUDGET",
                    "All required marks and balance cells do not fit",
                    p.policy_id,
                )
            return replace(mesh, cells=cells), refine, merge
    raise AdaptiveError(
        "ADAPTIVE_BALANCE", "Bounded balance propagation did not converge", p.region_id
    )


@dataclass(frozen=True, slots=True)
class MeshChange:
    before_mesh: Mesh
    after_mesh: Mesh
    before: NDArray[np.float64]
    after: NDArray[np.float64]
    indicators: NDArray[np.float64]
    refined: tuple[Cell, ...]
    coarsened: tuple[Cell, ...]


@dataclass(frozen=True, slots=True)
class Adapted:
    mesh: Mesh
    values: NDArray[np.float64]
    quiet: tuple[int, ...]
    ages: tuple[int, ...]
    maximum_indicator: float
    indicator_visits: int
    transferred_cells: int
    change: MeshChange | None


def adapt(
    p: AdaptiveProblem,
    mesh: Mesh,
    values: NDArray[np.float64],
    quiet: tuple[int, ...],
    ages: tuple[int, ...],
) -> Adapted:
    eta = indicator(p, mesh, values)
    if len(quiet) != len(mesh.cells) or len(ages) != len(mesh.cells):
        raise AdaptiveError(
            "ADAPTIVE_CONTROLLER", "Hysteresis counters do not belong to this support", p.policy_id
        )
    next_quiet = tuple(
        min(q + 1, p.policy.coarsen_after) if value < p.policy.coarsen_threshold else 0
        for q, value in zip(quiet, eta, strict=True)
    )
    next_ages = tuple(min(age + 1, p.policy.dwell) for age in ages)
    refine = {cell for cell, value in zip(mesh.cells, eta, strict=True) if value > 1}
    merge = set()
    indices = {cell: ordinal for ordinal, cell in enumerate(mesh.cells)}
    for cell in mesh.cells:
        if cell.level == 0 or cell.offset % 2:
            continue
        parent = cell.parent()
        children = parent.children()
        if all(
            child in indices
            and child not in refine
            and next_quiet[indices[child]] >= p.policy.coarsen_after
            and next_ages[indices[child]] >= p.policy.dwell
            for child in children
        ):
            merge.add(parent)
    visits, transfers = len(mesh.cells), 0
    if not refine and not merge:
        return Adapted(
            mesh, values, next_quiet, next_ages, float(max(eta)), visits, transfers, None
        )
    # Every retry removes at least one proposed merge; a bounded fallback defers
    # optional coarsening without relaxing any mandatory refinement mark.
    for attempt in range(7):
        if attempt == 6:
            merge.clear()
        candidate, refined, merged = balanced_partition(p, mesh, refine, merge)
        if candidate == mesh:
            return Adapted(
                mesh, values, next_quiet, next_ages, float(max(eta)), visits, transfers, None
            )
        mapped = transfer(mesh, candidate, values)
        transfers += len(mesh.cells) + len(candidate.cells)
        measured = indicator(p, candidate, mapped)
        visits += len(candidate.cells)
        rejected = {
            cell
            for cell, value in zip(candidate.cells, measured, strict=True)
            if cell in merged and value > p.policy.parent_threshold
        }
        if rejected:
            merge.difference_update(rejected)
            continue
        if max(measured) > 1:
            raise AdaptiveError(
                "ADAPTIVE_SPATIAL_RESOLUTION",
                "One-level conservative mapping cannot satisfy spatial fidelity",
                p.policy_id,
            )
        new_quiet = tuple(
            next_quiet[indices[cell]] if cell in indices else 0 for cell in candidate.cells
        )
        new_ages = tuple(
            next_ages[indices[cell]] if cell in indices else 0 for cell in candidate.cells
        )

        def key(cell: Cell) -> tuple[int, int]:
            return cell.start, cell.level

        change = MeshChange(
            mesh,
            candidate,
            values,
            mapped,
            eta,
            tuple(sorted(refined, key=key)),
            tuple(sorted(merged, key=key)),
        )
        return Adapted(
            candidate, mapped, new_quiet, new_ages, float(max(measured)), visits, transfers, change
        )
    raise AdaptiveError(
        "ADAPTIVE_BALANCE", "Bounded coarsening evaluation did not settle", p.policy_id
    )
