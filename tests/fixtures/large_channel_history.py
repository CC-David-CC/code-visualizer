"""Synthetic reader workload, explicitly not simulated physical evidence."""

from dataclasses import replace

import numpy as np

from code_visualizer.extensions.channels.codec import CODEC
from code_visualizer.extensions.channels.records import (
    INTERPRETATION_TYPE,
    SERIES_TYPE,
    Channel,
    ChannelChunk,
    ChannelInterpretation,
    ChannelSeries,
)
from code_visualizer.extensions.electrothermal.units import quantity
from code_visualizer.extensions.fields.arrays import array_resource
from code_visualizer.extensions.fields.records import TemporalPosition
from code_visualizer.extensions.foundations.unit_algebra import QuantityKind

COLUMNS, ROWS = 17, 27000


def build_channel_histories(store):
    def record(value, kind):
        return store.put(CODEC.encode(value), "application/json", logical_type=kind).reference

    interpretation = record(
        ChannelInterpretation(
            "stress:instrument",
            tuple(
                Channel(
                    f"stress:channel:{i}",
                    f"Reader channel {i}",
                    (f"stress:support:{i}",),
                    f"stress:support:{i}",
                    quantity(1, "kelvin").unit,
                    QuantityKind.INTERVAL,
                )
                for i in range(COLUMNS)
            ),
            quantity(1).unit,
        ),
        INTERPRETATION_TYPE,
    )
    roots, chunks, entries = {}, [], []
    prefix = prefix_last = None
    for ordinal in range(128):
        samples = np.arange(ordinal * ROWS, (ordinal + 1) * ROWS)
        values = np.empty((ROWS, COLUMNS + 2), dtype=np.float64)
        values[:, 0], values[:, 1] = samples, samples * 0.01
        values[:, 2:] = np.sin(samples[:, None] * 0.001 + np.arange(COLUMNS))
        produced = array_resource("channel-reader-workload", values)
        reference = store.put(
            produced.data,
            produced.media_type,
            tensor=produced.tensor,
            logical_type=produced.logical_type,
        ).reference
        chunks.append(reference)
        first = TemporalPosition(quantity(float(values[0, 1])), int(samples[0]), int(samples[0]))
        last = TemporalPosition(quantity(float(values[-1, 1])), int(samples[-1]), int(samples[-1]))
        entry = ChannelChunk(reference, first, last, ROWS, COLUMNS)
        page = ChannelSeries(interpretation, "b" * 64, (*entries, entry), prefix, prefix_last)
        try:
            CODEC.encode(page)
        except ValueError:
            previous = replace(page, chunks=tuple(entries))
            prefix, prefix_last = record(previous, SERIES_TYPE), previous.last
            entries = []
            page = ChannelSeries(interpretation, "b" * 64, (entry,), prefix, prefix_last)
        entries.append(entry)
        if ordinal + 1 in (16, 128):
            roots[ordinal + 1] = record(page, SERIES_TYPE)
            prefix, prefix_last = roots[ordinal + 1], page.last
            entries = []
    return roots, tuple(chunks)
