"""Pinned scientific criteria over complete immutable accepted continuum states."""

from dataclasses import replace

import numpy as np
import pytest
from fixtures.adaptive_reference import weighted_error
from test_adaptive_domain import problem

from code_visualizer.extensions.adaptive_diffusion.adaptation import adapt, indicator
from code_visualizer.extensions.adaptive_diffusion.controller import advance, start
from code_visualizer.extensions.adaptive_diffusion.problem import AdaptiveError
from code_visualizer.extensions.adaptive_fields.mesh import Mesh


def run(p):
    state = start(p)
    samples = [state]
    decisions, changes = [], []
    for tick in range(p.policy.sample_ticks, p.policy.final_tick + 1, p.policy.sample_ticks):
        while state.tick < tick:
            old_values = state.values.copy()
            result = advance(p, state, tick)
            np.testing.assert_array_equal(state.values, old_values)
            assert not state.values.flags.writeable
            state = result.state
            decisions.extend(result.decisions)
            if result.change is not None:
                changes.append(result.change)
        samples.append(state)
    return samples, decisions, changes


def error(p, samples):
    return max(
        weighted_error(s.mesh.faces, s.values, p.policy.time(s.tick), diffusivity=p.diffusivity)
        for s in samples
    )


def test_default_adaptive_run_refines_coarsens_conserves_and_meets_reference():
    p = problem()
    samples, decisions, changes = run(p)
    errors = [
        weighted_error(s.mesh.faces, s.values, p.policy.time(s.tick), diffusivity=p.diffusivity)
        for s in samples
    ]
    assert len(samples) == 201
    assert max(errors) <= 0.005, (max(errors), errors)
    assert len(samples[0].mesh.cells) > p.policy.base_cells
    assert len(samples[-1].mesh.cells) < len(samples[0].mesh.cells)
    assert any(change.coarsened for change in changes)
    mass = [p.area * float(s.mesh.widths @ s.values) for s in samples]
    np.testing.assert_allclose(mass, mass[0], rtol=1e-9, atol=0)
    assert all(np.min(s.values) >= 0 for s in samples)
    assert all(d.cumulative_work >= 0 for d in decisions)
    assert (
        samples[-1].work
        == samples[-1].solved_unknowns
        + samples[-1].indicator_visits
        + samples[-1].transferred_cells
    )


def test_tighter_spatial_tolerances_reduce_independent_error():
    p = problem()
    errors = []
    for factor in (1, 0.5, 0.25):
        refined = replace(
            p,
            policy=replace(
                p.policy,
                spatial_atol=p.policy.spatial_atol * factor,
                spatial_rtol=p.policy.spatial_rtol * factor,
            ),
        )
        errors.append(error(refined, run(refined)[0]))
    assert errors[2] < errors[1] < errors[0], errors


def test_adaptive_work_beats_smallest_uniform_grid_meeting_same_error_target():
    p = problem()
    adaptive, _, _ = run(p)
    errors = []
    for cells in (16, 32, 64, 128, 256, 512):
        uniform = replace(p, policy=replace(p.policy, mesh_mode="uniform", base_cells=cells))
        samples, _, _ = run(uniform)
        measured = error(uniform, samples)
        errors.append((cells, measured, samples[-1].work))
        if measured <= 0.005:
            assert adaptive[-1].work < 0.75 * samples[-1].work, (adaptive[-1].work, errors)
            break
    else:
        pytest.fail(f"No uniform comparator qualifies: {errors}")


def test_failure_preserves_complete_base_instead_of_approving_insufficient_fidelity():
    p = problem()
    base = start(p)
    values = base.values.copy()
    restricted = replace(p, policy=replace(p.policy, maximum_steps=0))
    with pytest.raises(AdaptiveError) as caught:
        advance(restricted, base, p.policy.sample_ticks)
    assert caught.value.code == "ADAPTIVE_STEP_BUDGET"
    assert caught.value.object_id == p.policy_id
    np.testing.assert_array_equal(base.values, values)
    assert base.tick == base.step == 0
    restricted = replace(p, policy=replace(p.policy, maximum_cells=p.policy.base_cells))
    with pytest.raises(AdaptiveError) as caught:
        start(restricted)
    assert caught.value.code == "ADAPTIVE_CELL_BUDGET"


def test_temporal_rejections_charge_actual_work_and_never_mutate_the_base():
    p = problem()
    strict = replace(p, policy=replace(p.policy, temporal_atol=1e-9, temporal_rtol=0))
    base = start(strict)
    original = base.values.copy()
    result = advance(strict, base, strict.policy.sample_ticks)
    assert result.state.rejections > 0
    assert result.state.solved_unknowns == 3 * len(base.mesh.cells) * len(result.decisions)
    assert all(not d.accepted for d in result.decisions[:-1]) and result.decisions[-1].accepted
    assert result.decisions[-1].temporal_error <= 1
    np.testing.assert_array_equal(base.values, original)
    assert base.step == base.tick == base.rejections == 0
    with pytest.raises(ValueError):
        base.values.setflags(write=True)
    impossible = replace(p, policy=replace(p.policy, temporal_atol=1e-30, temporal_rtol=0))
    with pytest.raises(AdaptiveError) as caught:
        advance(impossible, base, p.policy.sample_ticks)
    assert caught.value.code == "ADAPTIVE_TIME_RESOLUTION"
    np.testing.assert_array_equal(base.values, original)


def test_oscillating_signal_resets_quiet_opportunities_and_dwell_blocks_early_coarsening():
    p = problem()
    p = replace(p, policy=replace(p.policy, dwell=5))
    base = Mesh.uniform(p.region_id, 16, p.length)
    mesh = replace(base, cells=(*base.cells[:7], *base.cells[7].children(), *base.cells[8:]))
    quiet = ages = (0,) * len(mesh.cells)
    low = np.ones(len(mesh.cells))
    high = low.copy()
    high[7] += 0.02
    high[8] -= 0.02
    measured = indicator(p, mesh, high)
    assert p.policy.coarsen_threshold < min(measured[7:9]) < max(measured) < 1
    for values in (low, high) * 5:
        result = adapt(p, mesh, values, quiet, ages)
        assert result.change is None and result.mesh == mesh
        quiet, ages = result.quiet, result.ages
    for _ in range(p.policy.coarsen_after - 1):
        result = adapt(p, mesh, low, quiet, ages)
        assert result.change is None
        quiet, ages = result.quiet, result.ages
    result = adapt(p, mesh, low, quiet, ages)
    assert result.change is not None and result.mesh == base
    quiet = ages = (0,) * len(mesh.cells)
    for _ in range(4):
        result = adapt(p, mesh, low, quiet, ages)
        assert result.change is None
        quiet, ages = result.quiet, result.ages
    assert adapt(p, mesh, low, quiet, ages).mesh == base


def test_complete_scientific_run_is_deterministic_and_independent_of_preview_policy():
    p = problem()
    first, decisions, _ = run(p)
    second, other_decisions, _ = run(replace(p, policy=replace(p.policy, preview_every=11)))
    assert [d.row() for d in decisions] == [d.row() for d in other_decisions]
    for left, right in zip(first, second, strict=True):
        assert (left.mesh, left.tick, left.step, left.epoch, left.quiet, left.ages, left.work) == (
            right.mesh,
            right.tick,
            right.step,
            right.epoch,
            right.quiet,
            right.ages,
            right.work,
        )
        np.testing.assert_array_equal(left.values, right.values)
    for d in decisions:
        assert d.spatial_evaluated == (d.step % p.policy.decision_every == 0)
        if not d.spatial_evaluated:
            assert d.spatial_indicator == 0 and d.refined_cells == d.coarsened_cells == 0
