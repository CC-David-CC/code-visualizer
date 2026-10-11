"""Explicit support epochs, exact retained identities and closed resource admission."""

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import numpy as np
import pytest
from fixtures.adaptive_history import HistoryFixture

from code_visualizer.extensions.adaptive_fields.codec import decode_record, encode_record
from code_visualizer.extensions.adaptive_fields.history import AdaptiveHistory, support_mesh
from code_visualizer.extensions.adaptive_fields.records import (
    DECISION_COLUMNS,
    DECISIONS_TYPE,
    HISTORY_TYPE,
    INTERPRETATION_TYPE,
    SUPPORT_TYPE,
    TRANSFER_TYPE,
    CellHistory,
    DecisionLog,
)
from code_visualizer.extensions.adaptive_fields.units import quantity
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.computation_resources import resolve_computation_resource
from code_visualizer.persistence.resource_store import ResourceStore


def test_cell_metadata_v1_golden():
    golden = json.loads((Path(__file__).parent / "fixtures/adaptive_contracts_v1.json").read_text())
    hashes = {}
    for value in HistoryFixture().records.values():
        hashes.setdefault(type(value).__name__, set()).add(sha256(encode_record(value)).hexdigest())
    assert {key: sorted(values) for key, values in hashes.items()} == golden["metadata_sha256"]


def test_closed_canonical_metadata_and_no_project_model_in_resource_history():
    fixture = HistoryFixture()
    for record in fixture.records.values():
        payload = encode_record(record)
        assert decode_record(payload, type(record)) == record
        assert encode_record(decode_record(payload, type(record))) == payload
        extra = json.loads(payload)
        extra["value"]["fields"]["guessed"] = 7
        with pytest.raises(ValueError, match="fields"):
            decode_record(canonical_data_bytes(extra), type(record))
        with pytest.raises(ValueError, match="canonical"):
            decode_record(payload + b"\n", type(record))
    assert len(encode_record(fixture.series)) < 64 * 1024
    assert not hasattr(fixture.series, "project") and not hasattr(fixture.series, "prefix")


def test_support_change_resolves_exact_sample_cell_and_component_without_index_aliasing():
    fixture = HistoryFixture()
    history = AdaptiveHistory(fixture.root, fixture.resolve)
    assert history.sample_count == 6 and history.decoded_chunks == 0
    first, refined, last = (history.slice(i) for i in (1, 2, 5))
    assert (first.values.shape, refined.values.shape, last.values.shape) == (
        (16, 1),
        (17, 1),
        (16, 1),
    )
    assert first.mesh.cell_ids == last.mesh.cell_ids
    assert "region:cell:8:0:0" not in refined.mesh.cell_ids
    assert (
        history.probe(2, 1, "region:cell:8:1:0", "concentration").magnitude == refined.values[8, 0]
    )
    assert refined.position.time.magnitude == pytest.approx(0.2)
    assert not refined.values.flags.writeable
    with pytest.raises(ValueError, match="identity"):
        history.probe(2, 1, "region:cell:8:0:0", "concentration")
    with pytest.raises(ValueError, match="epoch"):
        history.probe(2, 0, "region:cell:8:0:0", "concentration")
    with pytest.raises(ValueError, match="exact"):
        history.slice(6)


def test_chunk_cache_is_bounded_and_admits_shape_and_coverage_before_slice():
    fixture = HistoryFixture()
    history = AdaptiveHistory(fixture.root, fixture.resolve, cache_bytes=300)
    history.slice(0)
    assert history.cache_bytes == 288
    history.slice(2)
    assert history.cache_bytes == 0  # 304-byte chunk is usable but cannot enter this cache.
    assert history.decoded_chunks == 2
    history.slice(0)
    history.slice(1)
    assert history.decoded_chunks == 3 and history.cache_bytes <= 300
    history.close()
    assert history.cache_bytes == 0
    chunk = fixture.series.chunks[0]
    values = np.zeros((2, 18))
    values[:, :2] = ((0, 0), (2, 1))
    changed = replace(
        fixture.series,
        chunks=(replace(chunk, values=fixture.array(values)), *fixture.series.chunks[1:]),
    )
    reader = AdaptiveHistory(fixture.record(changed, HISTORY_TYPE), fixture.resolve)
    with pytest.raises(ValueError, match="coverage"):
        reader.slice(1)


@pytest.mark.parametrize("fault", ("gap", "overlap", "future", "cross_epoch", "replace_prefix"))
def test_history_rejects_ambiguous_coverage_and_prefix_replacement(fault):
    fixture = HistoryFixture()
    first, second, third = fixture.series.chunks
    with pytest.raises(ValueError):
        match fault:
            case "gap":
                replace(fixture.series, chunks=(first, replace(second, first_sample=3), third))
            case "overlap":
                replace(fixture.series, chunks=(first, replace(second, first_sample=1), third))
            case "future":
                replace(fixture.series, chunks=(first, second))
            case "cross_epoch":
                replace(fixture.series, chunks=(replace(first, last_tick=2), second, third))
            case "replace_prefix":
                prefix = replace(fixture.series, epochs=fixture.series.epochs[:1], chunks=(first,))
                changed = replace(
                    fixture.series, chunks=(replace(first, values=second.values), second, third)
                )
                changed.extends(prefix)


@pytest.mark.parametrize("fault", ("duplicate", "fractional", "wrong_dimension", "wrong_shape"))
def test_partition_admission_checks_actual_bytes_and_declared_measure(fault):
    fixture = HistoryFixture()
    support = fixture.supports[0]
    if fault == "wrong_dimension":
        support = replace(support, area=quantity(1, "meter"))
    else:
        lineage = np.array(
            [(c.base, c.level, c.offset) for c in fixture.meshes[0].cells], dtype=np.float64
        )
        if fault == "duplicate":
            lineage[1] = lineage[0]
        elif fault == "fractional":
            lineage[1, 0] = 1.5
        else:
            lineage = lineage[:, :2]
        support = replace(support, lineage=fixture.array(lineage))
    with pytest.raises(ValueError):
        support_mesh(fixture.resolve, support)


def test_full_bound_lineage_uses_a_resource_instead_of_512_inline_objects():
    fixture = HistoryFixture(cells=256)
    support = fixture.supports[0]
    mesh = fixture.meshes[0]
    all_children = tuple(child for cell in mesh.cells for child in cell.children())
    lineage = np.array([(c.base, c.level, c.offset) for c in all_children], dtype=np.float64)
    support = replace(support, cells=512, lineage=fixture.array(lineage))
    assert len(encode_record(support)) < 4096
    assert (
        len(
            support_mesh(
                fixture.resolve, decode_record(encode_record(support), type(support))
            ).cells
        )
        == 512
    )


def test_transfer_rejects_conservative_but_wrong_mapping_and_changed_frame():
    fixture = HistoryFixture()
    transfer = fixture.records[fixture.transfers[0]]
    before = fixture.meshes[0]
    after = fixture.meshes[1]
    values = np.array((1 + after.centers)[:, None])
    # These cells have equal measure; change their values while preserving mass.
    values[1] += 0.1
    values[2] -= 0.1
    forged = fixture.record(replace(transfer, after=fixture.array(values)), TRANSFER_TYPE)
    epochs = (
        fixture.series.epochs[0],
        replace(fixture.series.epochs[1], transfer=forged),
        fixture.series.epochs[2],
    )
    with pytest.raises(ValueError, match="mapping"):
        AdaptiveHistory(
            fixture.record(replace(fixture.series, epochs=epochs), HISTORY_TYPE), fixture.resolve
        )
    assert before.region_id == after.region_id
    support_ref = fixture.record(
        replace(fixture.supports[1], frame_id="different-frame"), SUPPORT_TYPE
    )
    interpretation_ref = fixture.record(
        replace(fixture.records[fixture.interpretations[1]], support=support_ref),
        INTERPRETATION_TYPE,
    )
    epochs = (
        fixture.series.epochs[0],
        replace(fixture.series.epochs[1], interpretation=interpretation_ref),
        fixture.series.epochs[2],
    )
    with pytest.raises(ValueError, match="physical meaning"):
        AdaptiveHistory(
            fixture.record(replace(fixture.series, epochs=epochs), HISTORY_TYPE), fixture.resolve
        )


def test_existing_portable_closure_survives_producer_replacement_and_reopens_file_backed(tmp_path):
    fixture = HistoryFixture()
    store = ResourceStore(tmp_path / "producer")
    for resource in fixture.resources.values():
        descriptor = resource.descriptor
        store.put(
            resource.data,
            descriptor.media_type,
            tensor=descriptor.tensor,
            logical_type=descriptor.logical_type,
        )
    root = fixture.root
    closure = builtin_registry().resource_closure((root,), store)
    assert root == closure[-1] and len(closure) <= 30
    destination = ResourceStore(tmp_path / "retained")
    for ref in closure:
        destination.import_reference(store, ref)
    fixture.resources.clear()
    fixture.records.clear()
    del store, fixture
    reopened = ResourceStore(tmp_path / "retained")
    reader = AdaptiveHistory(
        root, lambda ref: resolve_computation_resource(reopened, ref, file_backed=True)
    )
    assert reader.probe(5, 2, "region:cell:8:0:0", "concentration").magnitude == 1 + 8.5 / 16
    assert reader.slice(5).position.step == 5


def test_history_metadata_cannot_sneak_a_node_association_into_an_adaptive_epoch():
    fixture = HistoryFixture()
    with pytest.raises(ValueError, match="association"):
        replace(fixture.records[fixture.interpretations[0]], association="node")
    with pytest.raises(ValueError, match="exact type"):
        decode_record(encode_record(fixture.supports[0]), CellHistory)


@pytest.mark.parametrize(
    "fault",
    ("source", "time_unit", "fractional_step", "future", "negative_indicator", "work_rewind"),
)
def test_decision_resources_are_bounded_real_counters_at_the_same_accepted_boundary(fault):
    fixture = HistoryFixture()
    values = np.zeros((6, len(DECISION_COLUMNS)))
    values[:, 0] = values[:, 1] = values[:, 11] = np.arange(6)
    values[:, 2] = np.repeat((0, 1, 2), 2)
    values[:, 3] = np.repeat((16, 17, 16), 2)
    values[:, 6:8] = 1
    values[:, 12] = 1
    log = DecisionLog("a" * 64, "policy", quantity(0.1), 6, fixture.array(values))
    encoded = encode_record(log)
    assert decode_record(encoded, DecisionLog) == log
    root = fixture.record(
        replace(fixture.series, decisions=fixture.record(log, DECISIONS_TYPE)), HISTORY_TYPE
    )
    assert AdaptiveHistory(root, fixture.resolve).sample_count == 6
    match fault:
        case "source":
            log = replace(log, source_digest="b" * 64)
        case "time_unit":
            log = replace(log, quantum=quantity(0.1, "meter"))
        case "fractional_step":
            values[2, 1] = 2.5
        case "future":
            values[5, 0:2] = 9
        case "negative_indicator":
            values[1, 4] = -1
        case "work_rewind":
            values[3, 11] = 0
    log = replace(log, values=fixture.array(values))
    root = fixture.record(
        replace(fixture.series, decisions=fixture.record(log, DECISIONS_TYPE)), HISTORY_TYPE
    )
    with pytest.raises(ValueError, match=r"Decisions|Decision log"):
        AdaptiveHistory(root, fixture.resolve)


def test_acknowledged_decision_bytes_cannot_be_rewritten_or_omitted():
    fixture = HistoryFixture()
    values = np.array([[0, 0, 0, 16, 0.5, 0, 1, 1, 0, 0, 0, 0, 1]], dtype=np.float64)
    log = DecisionLog("a" * 64, "policy", quantity(0.1), 1, fixture.array(values))
    previous_ref = fixture.record(
        replace(fixture.series, decisions=fixture.record(log, DECISIONS_TYPE)), HISTORY_TYPE
    )
    previous = AdaptiveHistory(previous_ref, fixture.resolve)
    previous.extends(previous)
    with pytest.raises(ValueError, match="drop acknowledged"):
        AdaptiveHistory(fixture.root, fixture.resolve).extends(previous)
    values[0, 4] = 0.1
    changed_log = replace(log, values=fixture.array(values))
    changed_ref = fixture.record(
        replace(fixture.series, decisions=fixture.record(changed_log, DECISIONS_TYPE)), HISTORY_TYPE
    )
    with pytest.raises(ValueError, match="replace acknowledged"):
        AdaptiveHistory(changed_ref, fixture.resolve).extends(previous)
