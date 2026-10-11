"""Closed lumped meanings share P5 bytes/closure, never its spatial semantics."""

from dataclasses import replace
from hashlib import sha256

import pytest

from code_visualizer.domain.intentional import BundleReference
from code_visualizer.domain.values import ResourceReference
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.channels.codec import CODEC
from code_visualizer.extensions.channels.records import (
    Channel,
    ChannelChunk,
    ChannelInterpretation,
    ChannelSeries,
)
from code_visualizer.extensions.electrothermal.units import quantity
from code_visualizer.extensions.fields.codec import decode_record, encode_record
from code_visualizer.extensions.fields.records import FieldSeries, TemporalPosition
from code_visualizer.extensions.foundations.unit_algebra import QuantityKind
from code_visualizer.extensions.publication import publication_manifest


def ref(name):
    return ResourceReference(name, sha256(name.encode()).hexdigest())


def records():
    channel = Channel(
        "temperature",
        "Body temperature",
        ("body",),
        "body",
        quantity(1, "kelvin").unit,
        QuantityKind.POINT,
    )
    interpretation = ChannelInterpretation("experiment", (channel,), quantity(1).unit)
    chunk = ChannelChunk(
        ref("values"),
        TemporalPosition(quantity(0), 0, 0),
        TemporalPosition(quantity(1), 1, 1),
        2,
        1,
    )
    return channel, interpretation, chunk, ChannelSeries(ref("meaning"), "a" * 64, (chunk,))


@pytest.mark.parametrize("record", records())
def test_closed_canonical_roundtrip_and_field_separation(record):
    payload = CODEC.encode(record)
    assert CODEC.decode(payload, type(record)) == record
    with pytest.raises(ValueError, match="canonical"):
        CODEC.decode(payload + b"\n", type(record))
    with pytest.raises(ValueError):
        decode_record(payload, FieldSeries)
    with pytest.raises(ValueError):
        encode_record(record)


@pytest.mark.parametrize(
    "changes",
    (
        {"support_kind": "mesh"},
        {"unit": "kelvin"},
        {"quantity_kind": "point"},
        {"semantic_ids": ()},
        {"support_id": ""},
    ),
)
def test_lumped_channel_never_guesses_support_or_kind(changes):
    with pytest.raises(ValueError):
        replace(records()[0], **changes)


def test_duplicate_columns_and_mixed_chunk_coverage_rejected():
    channel, meaning, chunk, series = records()
    with pytest.raises(ValueError):
        replace(meaning, channels=(channel, channel))
    for bad in (replace(chunk.first, sample=1), replace(chunk.first, time=quantity(0, "meter"))):
        with pytest.raises(ValueError):
            replace(chunk, first=bad)
    with pytest.raises(ValueError):
        replace(series, chunks=(chunk, chunk))
    with pytest.raises(ValueError):
        replace(series, prefix=ref("previous"))


def test_exact_registry_publication_and_duplicate_interpretation_rejected():
    registry = builtin_registry()
    for name in (
        "foundation.channels",
        "org.codevisualizer.electrothermal.units",
        "org.codevisualizer.electrothermal",
    ):
        manifest = publication_manifest(registry, name, "1")
        assert manifest.references
        registry.validate_publication_closure(BundleReference(name, "1"))
    with pytest.raises(ValueError):
        registry.register(replace(registry.get("foundation.channels", "1"), id="private.channels"))
