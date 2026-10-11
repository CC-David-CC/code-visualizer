import numpy as np
import pytest

from code_visualizer.extensions.hybrid_gas.policy import ModelPolicy, ModelState, decide
from code_visualizer.extensions.hybrid_gas.statistics import effective_size, equivalence, estimate


def test_correlated_blocks_are_not_counted_as_independent_draws():
    rng = np.random.default_rng(1977)
    independent = rng.normal(size=(256, 3))
    correlated = np.repeat(independent[:16], 16, axis=0)
    assert np.all(effective_size(correlated) < effective_size(independent) / 4)
    assert np.all(estimate(correlated).half_width > estimate(independent).half_width * 2)


def test_equivalence_requires_the_whole_difference_interval_and_replica_variance():
    rng = np.random.default_rng(19041)
    left = tuple(rng.normal(0, 0.005, (40, 3)) for _ in range(8))
    right = tuple(rng.normal(0, 0.005, (40, 3)) for _ in range(8))
    valid = equivalence(left, right, np.ones(3))
    assert valid.equivalent.all()
    # Many autocorrelated samples cannot disguise different independent means.
    shifted = tuple(x + 0.1 for x in right)
    assert not equivalence(left, shifted, np.ones(3)).equivalent.any()
    dispersed = tuple(x + (i - 3.5) * 0.1 for i, x in enumerate(right))
    result = equivalence(left, dispersed, np.ones(3))
    assert not result.precise.any()
    assert not result.equivalent.any()


def test_constant_conserved_observation_does_not_hide_a_wrong_mean():
    left = tuple(np.ones((20, 1)) for _ in range(8))
    right = tuple(np.full((20, 1), 2.0) for _ in range(8))
    result = equivalence(left, right, np.ones(1))
    assert result.precise.all() and not result.equivalent.any()
    np.testing.assert_array_equal(result.difference, [-1.0])


@pytest.mark.parametrize("bad", [np.ones((2, 1)), np.full((20, 2), np.nan)])
def test_insufficient_or_invalid_statistics_are_explicit(bad):
    with pytest.raises(ValueError, match="GAS_STATISTICS"):
        estimate(bad)


def test_model_hysteresis_dwell_and_statistics_are_distinct_admission_requirements():
    policy = ModelPolicy(0.004, 0.001, 3, 100)
    base = ModelState()
    activated = decide(policy, base, 0, 0.005, return_ready=False)
    assert activated.action == "activate" and not base.particle
    state = activated.after
    for tick, indicator in ((10, 0.0005), (20, 0.002), (30, 0.0005), (40, 0.0005)):
        decision = decide(policy, state, tick, indicator, return_ready=True)
        assert decision.action == "retain"
        state = decision.after
    dwell = decide(policy, state, 50, 0.0005, return_ready=True)
    assert dwell.reason == "minimum_dwell"
    statistics = decide(policy, dwell.after, 100, 0.0005, return_ready=False)
    assert statistics.reason == "insufficient_return_statistics"
    returned = decide(policy, statistics.after, 110, 0.0005, return_ready=True)
    assert returned.action == "return" and returned.after.switches == 2
    exhausted = decide(policy, returned.after, 120, 0.01, return_ready=True)
    assert exhausted.action == "reject" and exhausted.reason == "switch_budget"
    assert not exhausted.after.particle
    with pytest.raises(ValueError, match="GAS_DECISION_TIME"):
        decide(policy, returned.after, 110, 0.01, return_ready=True)
