"""Domain serialization retains one field inventory and bounded record lifetimes."""

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from code_visualizer.domain.intentional import (
    BundleReference,
    ConceptDefinition,
    ConstraintDefinition,
    ConstraintKind,
    DomainModel,
    DomainSchema,
    DomainWorkspace,
    IntentionalNode,
    PropertyDefinition,
    PropertyValue,
    RoleBinding,
    RoleDefinition,
    ValueKind,
)
from code_visualizer.domain.language import AuthoredDomainLanguage
from code_visualizer.domain.values import (
    MAX_INLINE_BYTES,
    ComplexValue,
    Dimension,
    DimensionPower,
    QuantityValue,
    ResourceReference,
    TensorDType,
    TensorValue,
    UnitReference,
    ValueConstraints,
)
from code_visualizer.persistence import intentional
from code_visualizer.persistence.canonical import canonical_data_bytes, json_stream_chunks


def _rich_workspace():
    dimension = Dimension((DimensionPower("org.example.dimension:length", 1),))
    unit = UnitReference("org.example.units:step", "3", dimension)
    samples = (
        (ValueKind.STRING, '\u03bb\n"\\'),
        (ValueKind.BOOLEAN, False),
        (ValueKind.INTEGER, 1 << 128),
        (ValueKind.NUMBER, -0.0),
        (ValueKind.COMPLEX, ComplexValue(1.25, -2.5)),
        (ValueKind.QUANTITY, QuantityValue(ComplexValue(0.0, 1.0), unit)),
        (ValueKind.TENSOR, TensorValue(TensorDType.FLOAT64, (1, 2), (1.0, -0.0))),
        (ValueKind.RESOURCE, ResourceReference("resource:sample", "a" * 64)),
    )
    properties = tuple(
        PropertyDefinition(
            f"property:{index}",
            f"Property {index}",
            kind,
            True,
            value,
            (value,),
            -4.5 if kind is ValueKind.NUMBER else None,
            8.5 if kind is ValueKind.NUMBER else None,
            ValueConstraints(dimension=dimension)
            if kind is ValueKind.QUANTITY
            else ValueConstraints(tensor_dtype=TensorDType.FLOAT64, tensor_shape=(None, 2))
            if kind is ValueKind.TENSOR
            else ValueConstraints(),
        )
        for index, (kind, value) in enumerate(samples)
    )
    concept = ConceptDefinition(
        "sample",
        "Sample",
        properties,
        (RoleDefinition("owned", "Children", ("sample",), 0, None, True),),
        (RoleDefinition("linked", "References", ("sample",), 0, 2, False),),
        (
            ConstraintDefinition("named", ConstraintKind.NONEMPTY, "property:0"),
            ConstraintDefinition("unique", ConstraintKind.UNIQUE_PROPERTY, "property:0", "owned"),
        ),
        "property:0",
        "Rich schema data",
    )
    bundle = BundleReference("org.example.sample", "3")
    schema = DomainSchema("schema", "org.example.sample", "3", (concept,), bundle, "Description")
    values = tuple(
        PropertyValue(f"property:{index}", value) for index, (_, value) in enumerate(samples)
    )
    child = IntentionalNode(
        "child", "sample", values, references=(RoleBinding("linked", ("root",)),)
    )
    root = IntentionalNode("root", "sample", values, (RoleBinding("owned", ("child",)),))
    model = DomainModel("model", schema.id, schema.version, (root.id,), (root, child), "Workspace")
    language = AuthoredDomainLanguage("language", schema.id, schema.version, "7", "Authored data")
    return DomainWorkspace((schema,), (model,), (bundle,), (language,))


def test_rich_domain_stream_preserves_pre_streaming_field_inventory_and_hash():
    workspace = _rich_workspace()
    expected = json.loads(
        (Path(__file__).parent / "fixtures" / "intentional_stream_golden.json").read_bytes()
    )
    chunks = tuple(json_stream_chunks(intentional.domain_workspace_stream(workspace)))
    assert intentional.domain_workspace_to_data(workspace) == expected
    assert b"".join(chunks) == canonical_data_bytes(expected)
    assert sha256(b"".join(chunks)).digest() == sha256(canonical_data_bytes(expected)).digest()
    assert intentional.domain_workspace_from_data(json.loads(b"".join(chunks))) == workspace
    assert all(0 < len(chunk) <= 64 * 1024 for chunk in chunks)


def test_checked_in_domain_contents_preserve_existing_json_semantics():
    path = Path(__file__).parents[1] / "examples/projects/17-traffic-light/project.json"
    expected = json.loads(path.read_bytes())["domain_workspace"]
    workspace = intentional.domain_workspace_from_data(expected)
    encoded = b"".join(json_stream_chunks(intentional.domain_workspace_stream(workspace)))
    assert encoded == canonical_data_bytes(expected)


def test_large_model_stream_yields_before_visiting_all_nodes(monkeypatch):
    nodes = tuple(
        IntentionalNode(f"node:{index}", "sample", (PropertyValue("value", index),))
        for index in range(5000)
    )
    model = DomainModel("large", "schema", "1", tuple(node.id for node in nodes), nodes)
    expected = canonical_data_bytes(intentional.domain_model_to_data(model))
    visited = []
    original = intentional.intentional_node_stream

    def visit(node):
        visited.append(node.id)
        return original(node)

    monkeypatch.setattr(intentional, "intentional_node_stream", visit)
    chunks = json_stream_chunks(intentional.domain_model_stream(model))
    first = next(chunks)
    assert 0 < len(visited) < len(nodes)
    encoded = first + b"".join(chunks)
    assert visited == [node.id for node in nodes]
    assert encoded == expected
    assert intentional.domain_model_from_data(json.loads(encoded)) == model


@pytest.mark.parametrize("owner", ("node", "schema"))
def test_single_large_property_owner_streams_values_without_materializing_its_array(
    owner, monkeypatch
):
    count = 5000
    if owner == "node":
        node = IntentionalNode(
            "node", "sample", tuple(PropertyValue(f"property:{i}", i) for i in range(count))
        )
        model = DomainModel("model", "schema", "1", (node.id,), (node,))
        workspace = DomainWorkspace(models=(model,))
    else:
        properties = tuple(
            PropertyDefinition(f"property:{i}", f"Property {i}", ValueKind.INTEGER, default=i)
            for i in range(count)
        )
        schema = DomainSchema(
            "schema",
            "org.example.sample",
            "1",
            (ConceptDefinition("sample", "Sample", properties),),
        )
        workspace = DomainWorkspace(schemas=(schema,))
    expected = canonical_data_bytes(intentional.domain_workspace_to_data(workspace))
    visited = []
    original = intentional.canonical_value_to_data

    def encode(value):
        visited.append(value)
        return original(value)

    monkeypatch.setattr(intentional, "canonical_value_to_data", encode)
    chunks = json_stream_chunks(intentional.domain_workspace_stream(workspace))
    first = next(chunks)
    assert 0 < len(visited) < count
    encoded = first + b"".join(chunks)
    assert visited == list(range(count))
    assert encoded == expected


def test_large_role_bindings_keep_order_and_bounded_leaf_output():
    ids = tuple(f"child:{index}" for index in range(10000))
    node = IntentionalNode(
        "root",
        "sample",
        (PropertyValue("text", "\u03bb" * (MAX_INLINE_BYTES // 2)),),
        (RoleBinding("owned", ids),),
        (RoleBinding("linked", tuple(reversed(ids))),),
    )
    chunks = tuple(json_stream_chunks(intentional.intentional_node_stream(node)))
    assert all(0 < len(chunk) <= 64 * 1024 for chunk in chunks)
    assert b"".join(chunks) == canonical_data_bytes(intentional.intentional_node_to_data(node))
    assert intentional.intentional_node_from_data(json.loads(b"".join(chunks))) == node
    invalid = replace(node, properties=(PropertyValue("text", "x" * (MAX_INLINE_BYTES + 1)),))
    with pytest.raises(ValueError):
        tuple(json_stream_chunks(intentional.intentional_node_stream(invalid)))
    with pytest.raises(ValueError):
        intentional.intentional_node_to_data(invalid)
