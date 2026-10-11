"""P5-02: closed meanings and real CAS dependency closure before numerical work."""

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from code_visualizer.domain.intentional import BundleReference
from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.values import QuantityValue, ResourceReference
from code_visualizer.execution.resource_interpretation import (
    ResourceDependency,
    ResourceInterpretation,
    resource_closure,
)
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.fields.codec import decode_record, encode_record
from code_visualizer.extensions.fields.records import (
    ARRAY_TYPE,
    INTERPRETATION_TYPE,
    SERIES_TYPE,
    SUPPORT_TYPE,
    DiffusionCheckpoint,
    FieldInterpretation,
    FieldSeries,
    SampleChunk,
    TemporalPosition,
    UniformSupport,
)
from code_visualizer.extensions.fields.units import field_catalog
from code_visualizer.extensions.foundations.space import space_bundle
from code_visualizer.extensions.foundations.unit_algebra import QuantityKind, UnitAlgebra
from code_visualizer.extensions.foundations.units_si import si_catalog
from code_visualizer.extensions.publication import publication_manifest
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.resource_store import ResourceStore


def q(value, unit="second"):
    return QuantityValue(value, si_catalog().unit("foundation.units.si:" + unit))


def ref(name):
    return ResourceReference(name, sha256(name.encode()).hexdigest())


def records():
    support = UniformSupport(
        "space", "frame", "axis", "x", q(0, "meter"), q(0.1, "meter"), 11, ref("x")
    )
    interpretation = FieldInterpretation(
        "field", ref("support"), q(1, "kelvin").unit, QuantityKind.INTERVAL
    )
    chunk = SampleChunk(
        ref("samples"), TemporalPosition(q(0), 0, 0), TemporalPosition(q(1), 10, 10), 11, 11
    )
    series = FieldSeries(ref("interpretation"), "a" * 64, (chunk,))
    checkpoint = DiffusionCheckpoint(
        "b" * 64,
        ref("interpretation"),
        ref("state"),
        ref("series"),
        chunk.last,
        "numpy:2.5.3;scipy:1.18.1",
        "c" * 64,
        11,
        20,
    )
    return support, interpretation, chunk.first, chunk, series, checkpoint


def test_field_metadata_v1_golden():
    fixture = json.loads((Path(__file__).parent / "fixtures/field_contracts_v1.json").read_text())
    assert {type(r).__name__: sha256(encode_record(r)).hexdigest() for r in records()} == fixture[
        "metadata_sha256"
    ]


@pytest.mark.parametrize("record", records())
def test_field_metadata_round_trip_is_canonical_and_closed(record):
    payload = encode_record(record)
    assert decode_record(payload, type(record)) == record
    assert encode_record(decode_record(payload, type(record))) == payload
    invalid = json.loads(payload)
    invalid["value"]["fields"]["guessed"] = 1
    with pytest.raises(ValueError, match="fields"):
        decode_record(canonical_data_bytes(invalid), type(record))
    invalid.pop("version")
    with pytest.raises(ValueError):
        decode_record(canonical_data_bytes(invalid), type(record))
    with pytest.raises(ValueError, match="canonical"):
        decode_record(payload + b"\n", type(record))


@pytest.mark.parametrize(
    "changes",
    [
        {"step": -1},
        {"step": True},
        {"sample": 1.5},
        {"time": 1.0},
        {"time": q(-1)},
    ],
)
def test_temporal_position_rejects_ambiguous_or_invalid_cursors(changes):
    with pytest.raises(ValueError):
        replace(TemporalPosition(q(1), 1, 1), **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"association": "cell"},
        {"dtype": "float32"},
        {"quantity_kind": "interval"},
        {"mask_policy": "guess"},
        {"unit": "kelvin"},
        {"component_id": ""},
    ],
)
def test_interpretation_never_guesses_missing_or_unsupported_metadata(changes):
    with pytest.raises(ValueError):
        replace(records()[1], **changes)


def test_series_rejects_gaps_overlap_wrong_units_and_unowned_prefix():
    chunk = records()[3]
    for first in (replace(chunk.first, sample=5), replace(chunk.first, time=q(0, "meter"))):
        with pytest.raises(ValueError):
            replace(chunk, first=first)
    with pytest.raises(ValueError):
        replace(records()[4], chunks=(chunk, chunk))
    with pytest.raises(ValueError):
        replace(records()[4], prefix=ref("prefix"))
    with pytest.raises(ValueError):
        replace(records()[5], next_sample_step=10)


def test_space_versions_and_exact_published_field_dependency_closure():
    registry = builtin_registry()
    assert registry.get("foundation.space", "1") == space_bundle()
    assert registry.get("foundation.space", "2").required_bundles == (
        BundleReference("foundation.math", "2"),
    )
    manifest = publication_manifest(registry, "foundation.fields", "1")
    assert manifest.references
    registry.validate_publication_closure(BundleReference("foundation.space", "1"))
    with pytest.raises(ValueError, match="Ambiguous"):
        registry.register(replace(registry.get("foundation.fields", "1"), id="private.fields"))


def test_diffusivity_units_use_the_shared_algebra():
    catalog = field_catalog()
    target = catalog.unit("foundation.fields.units:square_meter_per_second")
    source = catalog.unit("foundation.fields.units:square_millimeter_per_millisecond")
    assert UnitAlgebra(catalog).convert(
        QuantityValue(100.0, source), target
    ).magnitude == pytest.approx(0.1)


def test_nested_resource_closure_copies_without_the_producer_store(tmp_path):
    source = ResourceStore(tmp_path / "producer")
    array = source.put(b"fixture-array", "application/octet-stream", logical_type=ARRAY_TYPE)
    support = replace(records()[0], coordinates=array.reference)
    support_ref = source.put(
        encode_record(support), "application/json", logical_type=SUPPORT_TYPE
    ).reference
    interpretation = replace(records()[1], support=support_ref)
    interpretation_ref = source.put(
        encode_record(interpretation), "application/json", logical_type=INTERPRETATION_TYPE
    ).reference
    chunk = replace(records()[3], resource=array.reference)
    series = replace(records()[4], interpretation=interpretation_ref, chunks=(chunk,))
    root = source.put(encode_record(series), "application/json", logical_type=SERIES_TYPE).reference
    registry = builtin_registry()
    closure = resource_closure((root,), source, registry.resource_interpretation)
    assert set(closure) == {array.reference, support_ref, interpretation_ref, root}
    assert closure[-1] == root
    target = ResourceStore(tmp_path / "consumer")
    for reference in closure:
        target.import_reference(source, reference)
    assert resource_closure((root,), target, registry.resource_interpretation) == closure
    assert decode_record(target.read(root), FieldSeries) == series
    missing = ResourceStore(tmp_path / "incomplete")
    missing.import_reference(source, root)
    with pytest.raises((FileNotFoundError, ValueError)):
        resource_closure((root,), missing, registry.resource_interpretation)


def test_closure_checks_child_type_size_cycles_and_hashes(tmp_path):
    store = ResourceStore(tmp_path)
    logical = ResourceLogicalTypeReference("org.example.resource", "1")
    child = store.put(b"child", "text/plain", logical_type=logical)
    parent = store.put(b"parent", "text/plain", logical_type=logical)

    def decoder(data):
        return (ResourceDependency(child.reference, logical, 999),) if data == b"parent" else ()

    with pytest.raises(ValueError, match="type/size"):
        resource_closure(
            (parent.reference,), store, lambda _: ResourceInterpretation(logical, decoder)
        )
    with pytest.raises(ValueError, match="cycle"):
        resource_closure(
            (parent.reference,),
            store,
            lambda _: ResourceInterpretation(
                logical, lambda _: (ResourceDependency(parent.reference, logical),)
            ),
        )
    with pytest.raises(ValueError, match="metadata"):
        resource_closure(
            (parent.reference,), store, lambda _: ResourceInterpretation(logical, decoder, 1)
        )
