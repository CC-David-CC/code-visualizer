"""Temporary resource ownership borrows verified inputs without publishing build artifacts."""

import json
from dataclasses import replace

import pytest

from code_visualizer.domain.resources import ResourceLogicalTypeReference, TensorDescriptor
from code_visualizer.domain.values import TensorDType
from code_visualizer.persistence import resource_store
from code_visualizer.persistence.resource_store import ResourceStore


def _metadata(store, reference):
    return store.root / "descriptors" / (reference.id.removeprefix("resource:") + ".json")


def _files(root):
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_readthrough_verifies_inputs_without_copying_or_enumerating_them(tmp_path):
    inputs = ResourceStore(tmp_path / "authored")
    descriptor = inputs.put(
        b"1234",
        "application/octet-stream",
        tensor=TensorDescriptor(TensorDType.UINT8, (4,)),
        logical_type=ResourceLogicalTypeReference("org.example.samples", "3"),
    )
    original = _files(inputs.root)
    local = ResourceStore(tmp_path / "temporary", inputs=inputs)
    assert local.inputs is inputs
    assert local.describe(descriptor.reference) == descriptor
    assert local.verified_path(descriptor.reference) == inputs.verified_path(descriptor.reference)
    assert local.read(descriptor.reference) == b"1234"
    assert local.descriptors() == ()
    assert not local.root.exists(), "Reading an input must not materialize a local copy"

    output = local.put(b"build artifact", "text/plain")
    assert local.descriptors() == (output,)
    assert local.read(output.reference) == b"build artifact"
    assert _files(inputs.root) == original
    assert inputs.descriptors() == (descriptor,)
    with pytest.raises(FileNotFoundError):
        inputs.describe(output.reference)
    with pytest.raises(AttributeError):
        local.inputs = None


@pytest.mark.parametrize("damage", ("missing", "corrupt"))
def test_present_local_descriptor_never_falls_back_from_missing_or_corrupt_local_bytes(
    tmp_path, damage
):
    inputs = ResourceStore(tmp_path / "authored")
    descriptor = inputs.put(b"original", "text/plain")
    local = ResourceStore(tmp_path / "temporary", inputs=inputs)
    assert local.import_reference(inputs, descriptor.reference) == descriptor
    path = local.verified_path(descriptor.reference)
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(b"tampered")
    assert local.describe(descriptor.reference) == descriptor
    error = FileNotFoundError if damage == "missing" else ValueError
    with pytest.raises(error):
        local.verified_path(descriptor.reference)
    with pytest.raises(error):
        local.read(descriptor.reference)
    assert inputs.read(descriptor.reference) == b"original"


@pytest.mark.parametrize("damage", ("invalid-json", "changed-contract"))
def test_present_local_descriptor_corruption_never_falls_back(tmp_path, damage):
    inputs = ResourceStore(tmp_path / "authored")
    descriptor = inputs.put(b"original", "text/plain")
    local = ResourceStore(tmp_path / "temporary", inputs=inputs)
    local.import_reference(inputs, descriptor.reference)
    metadata = _metadata(local, descriptor.reference)
    if damage == "invalid-json":
        metadata.write_text("{broken", encoding="utf-8")
    else:
        value = json.loads(metadata.read_bytes())
        value["media_type"] = "application/changed"
        metadata.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError):
        local.describe(descriptor.reference)
    with pytest.raises(ValueError):
        local.read(descriptor.reference)
    assert inputs.describe(descriptor.reference) == descriptor


def test_descriptor_disappearance_after_owner_selection_does_not_retry_input(tmp_path, monkeypatch):
    inputs = ResourceStore(tmp_path / "authored")
    descriptor = inputs.put(b"original", "text/plain")
    local = ResourceStore(tmp_path / "temporary", inputs=inputs)
    local.import_reference(inputs, descriptor.reference)
    metadata = _metadata(local, descriptor.reference)
    original_read = resource_store.read_bounded

    def lose_local_record(path, limit):
        if path == metadata:
            raise FileNotFoundError("Local descriptor disappeared after its owner was selected")
        return original_read(path, limit)

    monkeypatch.setattr(resource_store, "read_bounded", lose_local_record)
    with pytest.raises(FileNotFoundError, match="owner was selected"):
        local.describe(descriptor.reference)
    assert inputs.read(descriptor.reference) == b"original"


def test_content_hash_does_not_merge_distinct_resource_contracts(tmp_path):
    inputs = ResourceStore(tmp_path / "authored")
    first = inputs.put(b"same bytes", "text/plain")
    local = ResourceStore(tmp_path / "temporary", inputs=inputs)
    second = local.put(b"same bytes", "application/octet-stream")
    assert first.content_hash == second.content_hash and first.id != second.id
    assert local.describe(first.reference) == first
    assert local.describe(second.reference) == second
    assert local.descriptors() == (second,)
    with pytest.raises(ValueError, match="identity mismatch"):
        local.describe(replace(first.reference, content_hash="0" * 64))


def test_local_descriptor_inventory_never_resolves_misnamed_records_from_inputs(tmp_path):
    inputs = ResourceStore(tmp_path / "authored")
    descriptor = inputs.put(b"original", "text/plain")
    local = ResourceStore(tmp_path / "temporary", inputs=inputs)
    metadata = local.root / "descriptors" / ("0" * 64 + ".json")
    metadata.parent.mkdir(parents=True)
    metadata.write_bytes(_metadata(inputs, descriptor.reference).read_bytes())
    assert local.describe(descriptor.reference) == descriptor
    with pytest.raises(ValueError, match="filename or identity mismatch"):
        local.descriptors()


@pytest.mark.parametrize("typed", (False, True))
def test_explicit_import_preserves_exact_descriptor_and_owns_independent_bytes(tmp_path, typed):
    inputs = ResourceStore(tmp_path / "authored")
    descriptor = inputs.put(
        b"1234",
        "application/octet-stream",
        tensor=TensorDescriptor(TensorDType.UINT8, (4,)),
        logical_type=ResourceLogicalTypeReference("org.example.samples", "3") if typed else None,
    )
    borrowed = ResourceStore(tmp_path / "scratch", inputs=inputs)
    output = ResourceStore(tmp_path / "published")
    assert output.import_reference(borrowed, descriptor.reference) == descriptor
    assert (
        _metadata(output, descriptor.reference).read_bytes()
        == _metadata(inputs, descriptor.reference).read_bytes()
    )
    assert output.inputs is None
    assert borrowed.descriptors() == ()
    assert str(inputs.root).encode() not in _metadata(output, descriptor.reference).read_bytes()
    inputs.verified_path(descriptor.reference).write_bytes(b"bad!")
    with pytest.raises(ValueError):
        borrowed.read(descriptor.reference)
    assert ResourceStore(tmp_path / "published").read(descriptor.reference) == b"1234"


def test_import_rechecks_verified_source_bytes_before_publishing_descriptor(tmp_path, monkeypatch):
    inputs = ResourceStore(tmp_path / "authored")
    descriptor = inputs.put(b"original", "text/plain")
    output = ResourceStore(tmp_path / "published")
    original_path = inputs.verified_path

    def change_after_verification(reference):
        path = original_path(reference)
        path.write_bytes(b"tampered")
        return path

    monkeypatch.setattr(inputs, "verified_path", change_after_verification)
    with pytest.raises(ValueError, match="declared content hash"):
        output.import_reference(inputs, descriptor.reference)
    assert output.descriptors() == ()
    assert not tuple((output.root / "staging").iterdir())


def test_writable_store_cannot_overlap_a_readonly_input_root(tmp_path):
    inputs = ResourceStore(tmp_path / "authored")
    with pytest.raises(ValueError, match="overlap"):
        ResourceStore(tmp_path / "authored", inputs=inputs)
    with pytest.raises(ValueError, match="overlap"):
        ResourceStore(inputs.root / "nested", inputs=inputs)
    child = ResourceStore(inputs.root / "nested")
    with pytest.raises(ValueError, match="overlap"):
        ResourceStore(tmp_path / "authored", inputs=child)
