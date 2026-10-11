"""Incrementally write real CAS chunks; never construct a whole history in RAM."""

from dataclasses import replace

import numpy as np

from code_visualizer.extensions.diffusion.domain import quantity
from code_visualizer.extensions.fields.arrays import array_resource
from code_visualizer.extensions.fields.codec import encode_record
from code_visualizer.extensions.fields.records import (
    INTERPRETATION_TYPE,
    SERIES_TYPE,
    SUPPORT_TYPE,
    FieldInterpretation,
    FieldSeries,
    SampleChunk,
    TemporalPosition,
    UniformSupport,
)
from code_visualizer.extensions.foundations.unit_algebra import QuantityKind

NODES, ROWS = 1025, 510


def build_histories(store):
    def array(values):
        resource = array_resource("stress-array", values)
        return store.put(
            resource.data,
            resource.media_type,
            tensor=resource.tensor,
            logical_type=resource.logical_type,
        ).reference

    def record(value, kind):
        return store.put(encode_record(value), "application/json", logical_type=kind).reference

    coordinates = np.arange(NODES, dtype=np.float64) / (NODES - 1)
    support = record(
        UniformSupport(
            "stress:space",
            "stress:frame",
            "stress:axis",
            "x",
            quantity(0.0, "meter"),
            quantity(1.0 / (NODES - 1), "meter"),
            NODES,
            array(coordinates),
        ),
        SUPPORT_TYPE,
    )
    interpretation = record(
        FieldInterpretation(
            "stress:field", support, quantity(1.0, "kelvin").unit, QuantityKind.INTERVAL
        ),
        INTERPRETATION_TYPE,
    )
    prefix = prefix_last = None
    entries = []
    roots = {}
    chunk_refs = []
    for ordinal in range(128):
        samples = np.arange(ordinal * ROWS, (ordinal + 1) * ROWS)
        values = np.empty((ROWS, NODES + 2), dtype=np.float64)
        values[:, 0] = samples
        values[:, 1] = samples * 0.01
        values[:, 2:] = np.sin(coordinates * np.pi) * np.exp(-samples[:, None] * 0.00001)
        reference = array(values)
        chunk_refs.append(reference)
        first = TemporalPosition(quantity(float(values[0, 1])), int(samples[0]), int(samples[0]))
        last = TemporalPosition(quantity(float(values[-1, 1])), int(samples[-1]), int(samples[-1]))
        entry = SampleChunk(reference, first, last, ROWS, NODES)
        candidate = FieldSeries(interpretation, "a" * 64, (*entries, entry), prefix, prefix_last)
        try:
            encode_record(candidate)
        except ValueError:
            previous = replace(candidate, chunks=tuple(entries))
            prefix = record(previous, SERIES_TYPE)
            prefix_last = previous.last
            entries = []
            candidate = FieldSeries(interpretation, "a" * 64, (entry,), prefix, prefix_last)
        entries.append(entry)
        if ordinal + 1 in (16, 128):
            roots[ordinal + 1] = record(candidate, SERIES_TYPE)
            prefix, prefix_last = roots[ordinal + 1], candidate.last
            entries = []
    return roots, tuple(chunk_refs)
