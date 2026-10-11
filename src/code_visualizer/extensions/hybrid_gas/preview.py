"""Bounded, revision-pinned gas candidate previews; never retained samples."""

from __future__ import annotations

from typing import TYPE_CHECKING

from code_visualizer.domain.computation import ComputationParameter
from code_visualizer.domain.preview import PreviewEvent
from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.values import CanonicalValue, QuantityValue, TensorDType, TensorValue
from code_visualizer.extensions.fields.records import digest, identity, index, scalar
from code_visualizer.extensions.hybrid_gas.problem import GasProblem
from code_visualizer.extensions.hybrid_gas.units import quantity

if TYPE_CHECKING:
    from code_visualizer.extensions.hybrid_gas.runtime import GasAdvance

PREVIEW_TYPE = ResourceLogicalTypeReference("code_visualizer.hybrid_gas.preview", "1")


def event(
    p: GasProblem,
    transition: GasAdvance,
    session: str,
    sequence: int,
    source: str,
    input_digest: str,
) -> PreviewEvent:
    import numpy as np

    selected = np.unique(np.linspace(0, p.grid.cells - 1, min(32, p.grid.cells), dtype=np.int64))
    values: list[tuple[str, CanonicalValue]] = [
        ("source", source),
        ("region", p.region_id),
        ("slab", p.slab_id),
        ("policy", p.policy_id),
        ("frame", p.frame_id),
        ("axis", p.axis_id),
        ("cells", p.grid.cells),
        ("height", quantity(p.grid.length, "meter")),
        ("quantum", quantity(p.policy.quantum, "second")),
        (
            "indices",
            TensorValue(TensorDType.INT64, (len(selected),), tuple(int(i) for i in selected)),
        ),
        ("status", "numerical_candidate_pending_publication"),
    ]
    for name, state in (("base", transition.before), ("candidate", transition.after)):
        values.extend(
            (
                (name + "_tick", state.tick),
                (name + "_windows", state.windows),
                (name + "_particle", state.model.particle),
                (
                    name + "_values",
                    TensorValue(
                        TensorDType.FLOAT64,
                        (len(selected), 5),
                        tuple(float(v) for v in state.values[selected].ravel()),
                    ),
                ),
            )
        )
    return PreviewEvent(
        session,
        sequence,
        input_digest,
        PREVIEW_TYPE,
        p.origins,
        tuple(ComputationParameter(k, v) for k, v in values),
    )


def validate_preview(preview: PreviewEvent) -> None:
    values = {p.name: p.value for p in preview.values}
    expected = {
        "source",
        "region",
        "slab",
        "policy",
        "frame",
        "axis",
        "cells",
        "height",
        "quantum",
        "indices",
        "status",
    }
    expected.update(
        prefix + "_" + field
        for prefix in ("base", "candidate")
        for field in ("tick", "windows", "particle", "values")
    )
    if (
        preview.interpretation != PREVIEW_TYPE
        or set(values) != expected
        or values["status"] != "numerical_candidate_pending_publication"
    ):
        raise ValueError("GAS_PREVIEW: unknown candidate interpretation")
    for name in ("source", "region", "slab", "policy", "frame", "axis"):
        value = values[name]
        if not isinstance(value, str):
            raise ValueError("GAS_PREVIEW: missing semantic/source identity")
        if name == "source":
            digest(value)
        else:
            identity(value)
    cells = index(values["cells"], "Cells")
    if not 16 <= cells <= 128:
        raise ValueError("GAS_PREVIEW: unsupported support")
    for name, unit in (("height", "meter"), ("quantum", "second")):
        q = values[name]
        if (
            not isinstance(q, QuantityValue)
            or scalar(q, name) <= 0
            or q.unit != quantity(1, unit).unit
        ):
            raise ValueError("GAS_PREVIEW: missing SI support/time")
    indices = values["indices"]
    if (
        not isinstance(indices, TensorValue)
        or indices.dtype != TensorDType.INT64
        or len(indices.shape) != 1
    ):
        raise ValueError("GAS_PREVIEW: expected explicit selected cell identities")
    if not 1 <= indices.shape[0] <= 32 or any(
        type(v) is not int or not 0 <= v < cells for v in indices.elements
    ):
        raise ValueError("GAS_PREVIEW: selected cells exceed their support")
    cell_ids = tuple(index(value, "Selected cell") for value in indices.elements)
    if len(set(cell_ids)) != len(cell_ids) or tuple(sorted(cell_ids)) != cell_ids:
        raise ValueError("GAS_PREVIEW: selected cell identities are not ordered and unique")
    for prefix in ("base", "candidate"):
        index(values[prefix + "_tick"], "Tick")
        index(values[prefix + "_windows"], "Windows")
        q = values[prefix + "_values"]
        if (
            type(values[prefix + "_particle"]) is not bool
            or not isinstance(q, TensorValue)
            or q.dtype != TensorDType.FLOAT64
            or q.shape != (indices.shape[0], 5)
        ):
            raise ValueError("GAS_PREVIEW: missing complete selected state")
    if (
        index(values["candidate_tick"], "Tick") <= index(values["base_tick"], "Tick")
        or index(values["candidate_windows"], "Windows")
        != index(values["base_windows"], "Windows") + 1
    ):
        raise ValueError("GAS_PREVIEW: state does not follow its complete base")
