"""Exact constant observables must not acquire fictitious autocorrelation."""

import numpy as np
import pytest

from code_visualizer.extensions.hybrid_gas.statistics import effective_size, equivalence


@pytest.mark.parametrize("value", (0.0, 0.001, 273.15, -11.0, 1e-12))
def test_every_exactly_constant_column_retains_all_thirty_observations(value):
    samples = np.full((30, 2), value)
    before = samples.copy()
    assert np.array_equal(effective_size(samples), [30.0, 30.0])
    assert np.array_equal(samples, before)


def test_constant_between_replica_bias_is_still_a_precise_equivalence_failure():
    left = tuple(np.full((30, 1), 0.001) for _ in range(8))
    right = tuple(np.zeros((30, 1)) for _ in range(8))
    result = equivalence(left, right, np.array([0.01]))
    assert result.left_effective[0] == result.right_effective[0] == 240
    assert result.precise[0]
    assert not result.equivalent[0]
    assert result.difference[0] == pytest.approx(0.001)


def test_tiny_real_serial_fluctuations_are_not_rounded_into_constant_observations():
    base = np.concatenate((np.zeros(15), np.ones(15))).reshape(30, 1)
    expected = effective_size(base)
    tiny = base * np.finfo(float).eps
    assert expected[0] < 20
    assert np.array_equal(effective_size(tiny), expected)


def test_underflowed_variance_preserves_the_existing_zero_variance_rule():
    samples = np.arange(30, dtype=float).reshape(30, 1) * 1e-200
    assert np.any(samples != samples[0])
    with np.errstate(divide="raise", invalid="raise"):
        assert np.array_equal(effective_size(samples), [30.0])
