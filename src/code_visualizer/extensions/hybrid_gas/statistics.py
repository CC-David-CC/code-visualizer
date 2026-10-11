"""Bounded block statistics. Independent replicas, not individual collisions, are samples.

The initial-positive, initial-monotone autocorrelation estimate uses paired lags
(0,1), (2,3), ... and grants no antithetic effective-size bonus. Qualification
uses independent replica means with Welch intervals and Bonferroni coverage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


def blocks(values: NDArray[np.float64]) -> NDArray[np.float64]:
    import numpy as np

    x = np.asarray(values, dtype=np.float64)
    if x.ndim != 2 or not 4 <= len(x) <= 256 or not 1 <= x.shape[1] <= 4096:
        raise ValueError("GAS_STATISTICS_SHAPE: require 4..256 blocks and 1..4096 observables")
    if not np.isfinite(x).all():
        raise ValueError("GAS_STATISTICS_FINITE: block observations must be finite")
    return x


def effective_size(values: NDArray[np.float64]) -> NDArray[np.float64]:
    import numpy as np

    x = blocks(values)
    n = len(x)
    centered = x - x.mean(axis=0)
    variance = np.mean(centered * centered, axis=0)
    rho = np.ones((n, x.shape[1]))
    # Summation can round the mean of identical binary64 values away from that
    # value (for example thirty copies of0.001). That residual is not variance
    # or serial correlation. Use exact equality, without an epsilon that could
    # erase real small fluctuations. Nonconstant columns keep the same estimator.
    varying = (variance > 0) & np.any(x != x[0], axis=0)
    for lag in range(1, n):
        rho[lag, varying] = (
            np.sum(centered[:-lag, varying] * centered[lag:, varying], axis=0)
            / n
            / variance[varying]
        )
    pairs = rho[: 2 * (n // 2)].reshape(n // 2, 2, x.shape[1]).sum(axis=1)
    alive = np.ones(x.shape[1], dtype=bool)
    previous = np.full(x.shape[1], np.inf)
    total = np.zeros(x.shape[1])
    for pair in pairs:
        alive &= pair > 0
        previous = np.minimum(previous, pair)
        total += np.where(alive, previous, 0)
    tau = np.maximum(1, 2 * total - 1)
    # Exactly constant observables retain the number of blocks; that does not
    # erase between-replica variability or imply that a different mean is valid.
    result = np.where(varying, n / tau, n)
    result.setflags(write=False)
    return result


@dataclass(frozen=True, slots=True)
class Estimate:
    mean: NDArray[np.float64]
    half_width: NDArray[np.float64]
    effective_blocks: NDArray[np.float64]


def estimate(values: NDArray[np.float64], *, alpha: float = 0.05) -> Estimate:
    import numpy as np
    from scipy.stats import t  # type: ignore[import-untyped]

    x = blocks(values)
    if not 0 < alpha < 1:
        raise ValueError("Confidence error probability must be in (0,1)")
    effective = effective_size(x)
    mean = x.mean(axis=0)
    critical = t.ppf(1 - alpha / (2 * x.shape[1]), np.maximum(1, effective - 1))
    half = critical * x.std(axis=0, ddof=1) / np.sqrt(effective)
    mean.setflags(write=False)
    half.setflags(write=False)
    return Estimate(mean, half, effective)


@dataclass(frozen=True, slots=True)
class Equivalence:
    difference: NDArray[np.float64]
    half_width: NDArray[np.float64]
    left_effective: NDArray[np.float64]
    right_effective: NDArray[np.float64]
    equivalent: NDArray[np.bool_]
    precise: NDArray[np.bool_]


def equivalence(
    left: tuple[NDArray[np.float64], ...],
    right: tuple[NDArray[np.float64], ...],
    scales: NDArray[np.float64],
    *,
    tolerance: float = 0.05,
    minimum_effective: float = 20,
    alpha: float = 0.05,
) -> Equivalence:
    import numpy as np
    from scipy.stats import t

    if not 2 <= len(left) <= 12 or not 2 <= len(right) <= 12:
        raise ValueError("GAS_ENSEMBLE: each side requires 2..12 independent replicas")
    a, b = tuple(blocks(x) for x in left), tuple(blocks(x) for x in right)
    scale = np.asarray(scales, dtype=np.float64)
    if (
        scale.shape != (a[0].shape[1],)
        or any(x.shape[1] != len(scale) for x in (*a, *b))
        or not np.isfinite(scale).all()
        or np.any(scale <= 0)
        or not 0 < tolerance < 1
        or not 0 < alpha < 1
        or not 1 <= minimum_effective <= 3072
    ):
        raise ValueError("GAS_ENSEMBLE: invalid observable scales or coverage policy")
    am, bm = np.stack([x.mean(axis=0) for x in a]), np.stack([x.mean(axis=0) for x in b])
    av, bv = am.var(axis=0, ddof=1) / len(a), bm.var(axis=0, ddof=1) / len(b)
    variance = av + bv
    denominator = av * av / (len(a) - 1) + bv * bv / (len(b) - 1)
    degrees = np.full(len(scale), float(len(a) + len(b) - 2))
    np.divide(variance * variance, denominator, out=degrees, where=denominator > 0)
    half = t.ppf(1 - alpha / (2 * len(scale)), degrees) * np.sqrt(variance)
    difference = am.mean(axis=0) - bm.mean(axis=0)
    ae = np.sum([effective_size(x) for x in a], axis=0)
    be = np.sum([effective_size(x) for x in b], axis=0)
    precise = (half <= tolerance * scale) & (ae >= minimum_effective) & (be >= minimum_effective)
    equivalent = precise & (np.abs(difference) + half <= tolerance * scale)
    for x in (difference, half, ae, be, precise, equivalent):
        x.setflags(write=False)
    return Equivalence(difference, half, ae, be, equivalent, precise)
