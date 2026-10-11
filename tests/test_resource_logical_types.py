"""Resource interpretations have exact public identities without changing bulk bytes."""

from dataclasses import replace
from hashlib import sha256

import pytest
from google.protobuf.descriptor_pb2 import DescriptorProto

from code_visualizer.application.worker_transport import (
    export_resource_stream,
    import_resource_stream,
)
from code_visualizer.domain.resources import (
    TERMINAL_LOGICAL_TYPE,
    DataResource,
    ResourceLogicalTypeReference,
)
from code_visualizer.domain.values import ResourceReference
from code_visualizer.execution.backends import ProducedResource
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.resource_store import ResourceStore, resource_identity
from code_visualizer.persistence.resources import resource_from_data, resource_to_data
from code_visualizer.protocol.resources import resource_from_proto, resource_to_proto
from code_visualizer.protocol.v1 import resource_pb2
from code_visualizer.protocol.validation import ProtocolBoundaryError


@pytest.mark.parametrize(
    "identity",
    [
        "field",
        "spice",
        "org..example",
        "Org.example.field",
        "org.example.field@1",
        "org.example:field:sample",
        "org.example.field ",
        "org." + "a" * 252,
    ],
)
def test_logical_type_requires_a_public_qualified_identity(identity):
    with pytest.raises(ValueError, match="Global contract"):
        ResourceLogicalTypeReference(identity, "1")


@pytest.mark.parametrize("version", ["", "1@2", "1/2", "1\n", "a" * 65, 1, None])
def test_logical_type_requires_an_explicit_separate_version(version):
    with pytest.raises(ValueError, match="version"):
        ResourceLogicalTypeReference("org.example.field", version)


@pytest.mark.parametrize("logical_type", ["", "field", "computation-terminal@1", {}, 1])
def test_resource_and_backend_output_reject_opaque_or_untyped_logical_types(logical_type, tmp_path):
    with pytest.raises(ValueError, match="typed public reference"):
        DataResource("object", "a" * 64, 0, "application/octet-stream", logical_type=logical_type)
    with pytest.raises(ValueError, match="typed public reference"):
        ProducedResource("output", b"", "application/octet-stream", logical_type=logical_type)
    store = ResourceStore(tmp_path)
    with pytest.raises(ValueError, match="typed public reference"):
        store.put(b"data", "application/octet-stream", logical_type=logical_type)
    assert not store.root.exists(), "Invalid metadata must fail before staging any bytes"


@pytest.mark.parametrize(
    "logical_type",
    [
        None,
        TERMINAL_LOGICAL_TYPE,
        ResourceLogicalTypeReference("org.example.field", "2"),
    ],
)
def test_logical_type_roundtrip_is_lossless_and_version_explicit(logical_type, tmp_path):
    descriptor = ResourceStore(tmp_path).put(
        b"payload", "application/octet-stream", logical_type=logical_type
    )
    native = resource_to_data(descriptor)
    wire = resource_to_proto(descriptor)
    assert native["version"] == wire.schema_version == (1 if logical_type is None else 2)
    if logical_type is None:
        assert native["logical_type"] == ""
        assert not wire.HasField("logical_type_reference")
    else:
        assert native["logical_type"] == {"id": logical_type.id, "version": logical_type.version}
        assert (wire.logical_type_reference.id, wire.logical_type_reference.version) == (
            logical_type.id,
            logical_type.version,
        )
    assert resource_from_data(native) == descriptor
    binary = wire.SerializeToString(deterministic=True)
    restored = resource_from_proto(resource_pb2.DataResource.FromString(binary))
    assert restored == descriptor
    assert resource_to_proto(restored).SerializeToString(deterministic=True) == binary


def _legacy_descriptor(payload, logical_type=""):
    data = {
        "version": 1,
        "content_hash": sha256(payload).hexdigest(),
        "byte_size": len(payload),
        "media_type": "application/octet-stream",
        "tensor": None,
        "logical_type": logical_type,
    }
    return {"id": "resource:" + sha256(canonical_data_bytes(data)).hexdigest(), **data}


def test_untyped_legacy_descriptor_keeps_exact_bytes_identity_and_wire_tags(tmp_path):
    payload = b"previously authored resource"
    legacy = _legacy_descriptor(payload)
    descriptor = resource_from_data(legacy)
    assert descriptor.logical_type is None
    assert resource_identity(descriptor) == legacy["id"]
    assert canonical_data_bytes(resource_to_data(descriptor)) == canonical_data_bytes(legacy)
    store = ResourceStore(tmp_path)
    assert store.put(payload, descriptor.media_type) == descriptor
    assert store.describe(descriptor.reference) == descriptor
    assert store.read(descriptor.reference) == payload
    wire = resource_to_proto(descriptor)
    assert wire.schema_version == 1
    # Existing tags 1..6 remain stable and field7 is not recycled as a message.
    definition = DescriptorProto()
    resource_pb2.DataResource.DESCRIPTOR.CopyToProto(definition)
    assert "logical_type" in definition.reserved_name
    assert any(span.start <= 7 < span.end for span in definition.reserved_range)
    assert (
        next(field.number for field in definition.field if field.name == "logical_type_reference")
        == 8
    )


@pytest.mark.parametrize("legacy_type", ["field", "computation-terminal@1", "org.example.field"])
def test_nonempty_legacy_logical_type_is_not_assigned_an_invented_version(tmp_path, legacy_type):
    legacy = _legacy_descriptor(b"legacy", legacy_type)
    encoded = canonical_data_bytes(legacy)
    store = ResourceStore(tmp_path)
    path = store._path("descriptors/" + legacy["id"].removeprefix("resource:") + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    reference = ResourceReference(legacy["id"], legacy["content_hash"])
    with pytest.raises(ValueError, match="unversioned"):
        store.describe(reference)
    assert path.read_bytes() == encoded, (
        "Rejected metadata must remain available for explicit migration"
    )
    # Old binaries using string tag7 are unknown fields, never silently mapped to v2.
    legacy_wire = resource_to_proto(DataResource("old", "a" * 64, 0, "application/octet-stream"))
    field_value = legacy_type.encode("ascii")
    binary = legacy_wire.SerializeToString() + bytes((58, len(field_value))) + field_value
    with pytest.raises(ProtocolBoundaryError) as caught:
        resource_from_proto(resource_pb2.DataResource.FromString(binary))
    assert caught.value.code == "PROTOCOL_UNKNOWN_FIELD"


def test_typed_descriptors_cannot_be_downgraded_or_have_their_type_silently_removed():
    typed = DataResource(
        "object",
        "a" * 64,
        0,
        "application/octet-stream",
        logical_type=ResourceLogicalTypeReference("org.example.field", "1"),
    )
    native = resource_to_data(typed)
    with pytest.raises(ValueError, match="unversioned"):
        resource_from_data({**native, "version": 1})
    for erased in (None, "", {}, {"id": "org.example.field"}):
        with pytest.raises(ValueError):
            resource_from_data({**native, "logical_type": erased})
    wire = resource_to_proto(typed)
    wire.schema_version = 1
    with pytest.raises(ValueError, match="version 2"):
        resource_from_proto(wire)
    wire.schema_version = 2
    wire.ClearField("logical_type_reference")
    with pytest.raises(ValueError, match="requires a typed"):
        resource_from_proto(wire)
    for version in (0, 3):
        wire.schema_version = version
        with pytest.raises(ProtocolBoundaryError, match="versions are 1 and 2"):
            resource_from_proto(wire)
    with pytest.raises(ValueError, match="descriptor version"):
        resource_from_data({**native, "version": 3})


def test_typed_logical_reference_rejects_unknown_nested_data():
    descriptor = DataResource(
        "object", "a" * 64, 0, "application/octet-stream", logical_type=TERMINAL_LOGICAL_TYPE
    )
    native = resource_to_data(descriptor)
    with pytest.raises(ValueError, match="Unknown fields"):
        resource_from_data(
            {
                **native,
                "logical_type": {
                    "id": TERMINAL_LOGICAL_TYPE.id,
                    "version": "1",
                    "expression": "payload",
                },
            }
        )
    wire = resource_to_proto(descriptor)
    reference = wire.logical_type_reference
    reference.ParseFromString(reference.SerializeToString() + b"\xa0\x06\x01")
    with pytest.raises(ProtocolBoundaryError, match="fields"):
        resource_from_proto(wire)


def test_logical_type_versions_change_descriptor_identity_not_bulk_content(tmp_path):
    store = ResourceStore(tmp_path)
    one = ResourceLogicalTypeReference("org.example.field", "1")
    two = replace(one, version="2")
    descriptors = [
        store.put(b"samples", "application/octet-stream", logical_type=kind)
        for kind in (None, one, two)
    ]
    assert len({descriptor.id for descriptor in descriptors}) == 3
    assert len({descriptor.content_hash for descriptor in descriptors}) == 1
    assert len({store.verified_path(descriptor.reference) for descriptor in descriptors}) == 1


def test_chunked_transfer_preserves_unknown_but_well_formed_logical_type_contract(tmp_path):
    sender, receiver = ResourceStore(tmp_path / "sender"), ResourceStore(tmp_path / "receiver")
    logical_type = ResourceLogicalTypeReference("org.example.field", "17")
    descriptor = sender.put(
        b"field-samples" * 100000, "application/octet-stream", logical_type=logical_type
    )
    import_resource_stream(
        receiver,
        descriptor.reference,
        export_resource_stream(sender, descriptor.reference, "transfer"),
        max_resource_bytes=descriptor.byte_size,
    )
    assert receiver.describe(descriptor.reference) == descriptor
    assert receiver.describe(descriptor.reference).logical_type == logical_type
    assert receiver.read(descriptor.reference) == sender.read(descriptor.reference)
