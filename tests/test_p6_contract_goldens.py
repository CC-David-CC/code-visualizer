"""Independent fixed bytes for newly versioned P6 records and the portable trial."""

from pathlib import Path

import pytest
from test_channel_contracts import records, ref

from code_visualizer.domain.values import TensorDType, TensorValue
from code_visualizer.extensions.channels.codec import CODEC as CHANNEL_CODEC
from code_visualizer.extensions.channels.preview import ChannelPreview, channel_preview
from code_visualizer.extensions.electrothermal.checkpoint import CODEC, CoupledCheckpoint
from code_visualizer.extensions.electrothermal.units import quantity
from code_visualizer.extensions.fields.records import TemporalPosition
from code_visualizer.protocol.preview import preview_from_proto, preview_to_proto
from code_visualizer.protocol.v1.worker_pb2 import PreviewEvent as WirePreview

FIXTURES = Path(__file__).parent / "fixtures" / "p6"


def golden_records():
    _, meaning, _, series = records()
    checkpoint = CoupledCheckpoint(
        "a" * 64,
        ref("meaning"),
        ref("state"),
        ref("prefix"),
        TemporalPosition(quantity(1), 1, 1),
        "qualified-test-numerics-v1",
        "b" * 64,
        2,
        2,
    )
    return (
        ("channel-interpretation-v1.json", meaning, CHANNEL_CODEC),
        ("channel-series-v1.json", series, CHANNEL_CODEC),
        ("coupled-checkpoint-v1.json", checkpoint, CODEC),
    )


def trial_event():
    return ChannelPreview(
        ref("meaning"),
        "a" * 64,
        0,
        quantity(0),
        1,
        quantity(1),
        1,
        TensorValue(TensorDType.INT64, (1,), (0,)),
        TensorValue(TensorDType.FLOAT64, (1,), (293.15,)),
        TensorValue(TensorDType.FLOAT64, (1,), (293.4,)),
    ).event("trial-run", 7, "c" * 64, "experiment")


@pytest.mark.parametrize(
    "name,record,codec", golden_records(), ids=lambda v: v if isinstance(v, str) else None
)
def test_new_record_versions_keep_their_exact_bytes(name, record, codec):
    data = (FIXTURES / name).read_bytes()
    assert codec.encode(record) == data
    assert codec.decode(data, type(record)) == record
    with pytest.raises(ValueError):
        codec.decode(data.replace(b'"version":1', b'"version":2', 1), type(record))


def test_portable_trial_is_lossless_and_does_not_become_durable_evidence():
    event = trial_event()
    data = (FIXTURES / "channel-trial-v1.pb").read_bytes()
    assert preview_to_proto(event).SerializeToString(deterministic=True) == data
    assert preview_from_proto(WirePreview.FromString(data)) == event
    assert channel_preview(preview_from_proto(WirePreview.FromString(data))) == channel_preview(
        event
    )
