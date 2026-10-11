"""Independent analytic cell integrals; never imported by production numerical code."""

from itertools import pairwise
from math import comb, exp, fsum, pi, sin


def pulse_average(left: float, right: float, time: float, *, diffusivity: float = 0.001) -> float:
    width = right - left
    terms = [1.0, comb(16, 8) / 65536]
    for mode in range(1, 9):
        frequency = 2 * pi * mode
        integral = (sin(frequency * (right - 0.5)) - sin(frequency * (left - 0.5))) / (
            frequency * width
        )
        terms.append(
            comb(16, 8 - mode) / 32768 * exp(-diffusivity * frequency**2 * time) * integral
        )
    return fsum(terms)


def weighted_error(faces, values, time, *, diffusivity=0.001):
    reference = [
        pulse_average(float(a), float(b), time, diffusivity=diffusivity) for a, b in pairwise(faces)
    ]
    return (
        fsum(
            float(b - a) * (float(v) - r) ** 2
            for a, b, v, r in zip(faces[:-1], faces[1:], values, reference, strict=True)
        )
        ** 0.5
    )
