"""Reject impossible nested value variants before traversing attacker-controlled trees."""

import pytest

from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.values import canonical_value_from_data


@pytest.mark.parametrize(
    "case", ("int-real", "real-zero", "complex-zero", "quantity", "tensor-zero")
)
def test_undo_redo_preserves_numeric_representation_even_when_python_values_compare_equal(case):
    from code_visualizer.application.authority import ProjectAuthority
    from code_visualizer.application.domain_commands import SetDomainProperty
    from code_visualizer.application.messages import CommandAccepted
    from code_visualizer.domain.intentional import (
        ConceptDefinition,
        DomainModel,
        DomainSchema,
        DomainWorkspace,
        IntentionalNode,
        PropertyDefinition,
        PropertyValue,
        ValueKind,
    )
    from code_visualizer.domain.project import Project
    from code_visualizer.domain.values import (
        ComplexValue,
        Dimension,
        QuantityValue,
        TensorDType,
        TensorValue,
        UnitReference,
    )
    from code_visualizer.persistence.canonical import canonical_data_bytes
    from code_visualizer.persistence.values import canonical_value_to_data
    from code_visualizer.sdk.client import CodeVisualizerClient

    unit = UnitReference("unit", "1", Dimension())
    kind, before, after = {
        "int-real": (ValueKind.NUMBER, 1, 1.0),
        "real-zero": (ValueKind.NUMBER, -0.0, 0.0),
        "complex-zero": (ValueKind.COMPLEX, ComplexValue(-0.0, 1.0), ComplexValue(0.0, 1.0)),
        "quantity": (ValueKind.QUANTITY, QuantityValue(1, unit), QuantityValue(1.0, unit)),
        "tensor-zero": (
            ValueKind.TENSOR,
            TensorValue(TensorDType.FLOAT64, (1,), (-0.0,)),
            TensorValue(TensorDType.FLOAT64, (1,), (0.0,)),
        ),
    }[case]
    assert before == after

    def encode(value):
        return canonical_data_bytes(canonical_value_to_data(value))

    assert encode(before) != encode(after)
    schema = DomainSchema(
        "schema",
        "example.numeric",
        "1",
        (ConceptDefinition("concept", "Sample", (PropertyDefinition("value", "Value", kind),)),),
    )
    model = DomainModel(
        "model",
        "schema",
        "1",
        ("node",),
        (IntentionalNode("node", "concept", (PropertyValue("value", before),)),),
    )
    authority = ProjectAuthority(
        Project(
            "project", "Numeric values", (), domain_workspace=DomainWorkspace((schema,), (model,))
        )
    )
    client = CodeVisualizerClient(authority, actor_id="author")

    def stored():
        return encode(authority.snapshot().domain_workspace.node("node").property("value"))

    try:
        assert isinstance(
            client.submit(SetDomainProperty("model", "node", "value", after)), CommandAccepted
        )
        assert stored() == encode(after)
        assert isinstance(client.undo(), CommandAccepted)
        assert stored() == encode(before)
        assert isinstance(client.redo(), CommandAccepted)
        assert stored() == encode(after)
    finally:
        client.close()


@pytest.mark.parametrize("kind", ("quantity", "tensor"))
def test_impossible_nested_values_reject_at_the_outer_contract(kind):
    # A closed scalar/complex element grammar never needs to visit these descendants.
    # RecursionError is not an admission error and bypasses the command's ValueError guard.
    payload = 1
    for _ in range(1200):
        if kind == "quantity":
            payload = {
                "$value": "quantity",
                "version": 1,
                "magnitude": payload,
                "unit": {"id": "unit", "version": "1", "dimension": {"powers": []}},
            }
        else:
            payload = {
                "$value": "tensor",
                "version": 1,
                "dtype": "int64",
                "shape": [1],
                "elements": [payload],
            }
    with pytest.raises(ValueError):
        canonical_value_from_data(payload)


def test_immutable_writer_rejects_size_mismatch_before_reading_existing_payload(
    tmp_path, monkeypatch
):
    target = tmp_path / "descriptor.json"
    target.write_bytes(b"x" * 200_000)
    original = type(target).read_bytes

    def read_bytes(path):
        assert path != target, "An oversized existing record must not be read into memory"
        return original(path)

    monkeypatch.setattr(type(target), "read_bytes", read_bytes)
    with pytest.raises(ValueError):
        ResourceStore._write_immutable(target, b"small immutable record")


@pytest.mark.parametrize("field", ("default", "choices"))
def test_schema_numeric_representation_edits_undo_and_redo_exact_native_json(field):
    from dataclasses import replace

    from code_visualizer.application.authority import ProjectAuthority
    from code_visualizer.application.domain_commands import PutDomainPropertyDefinition
    from code_visualizer.application.messages import CommandAccepted
    from code_visualizer.domain.intentional import (
        ConceptDefinition,
        DomainSchema,
        DomainWorkspace,
        PropertyDefinition,
        ValueKind,
    )
    from code_visualizer.domain.project import Project
    from code_visualizer.persistence.serialization import normalized_project_json
    from code_visualizer.sdk.client import CodeVisualizerClient

    definition = PropertyDefinition("value", "Value", ValueKind.NUMBER, default=1, choices=(1,))
    edited = (
        replace(definition, default=1.0)
        if field == "default"
        else replace(definition, choices=(1.0,))
    )
    schema = DomainSchema(
        "schema", "example.schema", "1", (ConceptDefinition("concept", "Sample", (definition,)),)
    )
    authority = ProjectAuthority(
        Project("project", "Schema numeric values", (), domain_workspace=DomainWorkspace((schema,)))
    )
    client = CodeVisualizerClient(authority, actor_id="author")
    before = normalized_project_json(authority.snapshot())
    try:
        assert isinstance(
            client.submit(PutDomainPropertyDefinition("schema", "concept", edited)), CommandAccepted
        )
        # Revision changes are normal; compare canonical contents at one revision.
        after = normalized_project_json(replace(authority.snapshot(), revision=0))
        assert before != after
        assert isinstance(client.undo(), CommandAccepted)
        assert normalized_project_json(replace(authority.snapshot(), revision=0)) == before
        assert isinstance(client.redo(), CommandAccepted)
        assert normalized_project_json(replace(authority.snapshot(), revision=0)) == after
    finally:
        client.close()
