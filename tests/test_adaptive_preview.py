"""Ephemeral candidates keep their own support and cannot change numerical decisions."""

from dataclasses import replace

import numpy as np
import pytest
from test_adaptive_domain import problem

from code_visualizer.domain.computation import ComputationParameter
from code_visualizer.domain.values import QuantityValue, TensorDType, TensorValue
from code_visualizer.extensions.adaptive_diffusion.controller import advance, start
from code_visualizer.extensions.adaptive_fields.mesh import Mesh
from code_visualizer.extensions.adaptive_fields.preview import (
    CellPreview,
    ReducedCells,
    cell_preview,
)
from code_visualizer.extensions.adaptive_fields.units import quantity
from code_visualizer.protocol.preview import preview_from_proto, preview_to_proto


def sample_preview():
    p = problem()
    base = start(p)
    while True:
        result = advance(p, base, min(p.policy.final_tick, base.tick + p.policy.sample_ticks))
        if result.change is not None:
            break
        base = result.state
        assert base.tick < p.policy.final_tick
    next_state = result.state
    return CellPreview(
        p.region_id,
        p.frame_id,
        p.axis_id,
        p.policy.base_cells,
        quantity(p.length, "meter"),
        quantity(p.policy.quantum),
        "concentration",
        QuantityValue(1.0, p.unit),
        ReducedCells.reduce(base.mesh, base.epoch, base.tick, base.step, base.values),
        ReducedCells.reduce(
            next_state.mesh, next_state.epoch, next_state.tick, next_state.step, next_state.values
        ),
    )


def test_real_coarsening_preview_has_distinct_supports_and_roundtrips_portably():
    preview = sample_preview()
    assert preview.base.support_digest != preview.candidate.support_digest
    assert len(preview.base.cells) != len(preview.candidate.cells)
    event = preview.event("attempt", 17, "a" * 64, ("adaptive:field", "adaptive:policy"))
    assert cell_preview(preview_from_proto(preview_to_proto(event))) == preview
    assert len(preview_to_proto(event).SerializeToString()) < 65536


@pytest.mark.parametrize("fault", ("epoch", "step", "lineage", "values", "unit", "extra", "status"))
def test_malformed_provisional_support_and_claims_are_rejected(fault):
    preview = sample_preview()
    with pytest.raises(ValueError):
        if fault == "epoch":
            replace(preview, candidate=replace(preview.candidate, epoch=preview.base.epoch))
        elif fault == "step":
            replace(preview, candidate=replace(preview.candidate, step=preview.base.step))
        elif fault == "lineage":
            replace(
                preview.base, lineage=TensorValue(TensorDType.INT64, (2, 3), (0, 0, 0, 0, 0, 0))
            )
        elif fault == "values":
            replace(preview.base, values=TensorValue(TensorDType.FLOAT64, (1,), (1.0,)))
        elif fault == "unit":
            replace(preview, length=quantity(1, "second"))
        else:
            event = preview.event("attempt", 1, "a" * 64, ("adaptive:field",))
            values = (
                (*event.values, ComputationParameter("extra", 1))
                if fault == "extra"
                else tuple(
                    ComputationParameter("status", "retained") if v.name == "status" else v
                    for v in event.values
                )
            )
            cell_preview(replace(event, values=values))


def test_preview_reduction_is_bounded_and_does_not_change_state_or_support_hash():
    mesh = Mesh.uniform("region", 512, 1.0)
    values = np.linspace(1, 2, 512)
    before = values.copy()
    full = ReducedCells.reduce(mesh, 0, 0, 0, values)
    small = ReducedCells.reduce(mesh, 0, 0, 0, values, limit=37)
    assert full.values.shape == (256,) and small.values.shape == (37,)
    assert full.support_digest == small.support_digest
    assert small.cells[0] == mesh.cells[0] and small.cells[-1] == mesh.cells[-1]
    np.testing.assert_array_equal(values, before)
