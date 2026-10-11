"""Versioned dimension extensions preserve released native and wire encodings."""

from dataclasses import replace
from fractions import Fraction

import pytest
from test_canonical_values_resources import value_project

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.domain_commands import SetDomainProperty
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.domain.intentional import ValueKind
from code_visualizer.domain.values import Dimension, DimensionPower, QuantityValue, UnitReference
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.serialization import normalized_project_json
from code_visualizer.persistence.store import ProjectStore
from code_visualizer.persistence.values import (
    canonical_value_from_data,
    canonical_value_to_data,
    dimension_from_data,
    dimension_to_data,
)
from code_visualizer.protocol.v1 import value_pb2 as wire
from code_visualizer.protocol.values import (
    canonical_value_from_proto,
    canonical_value_to_proto,
    dimension_from_proto,
    dimension_to_proto,
)
from code_visualizer.sdk import CodeVisualizerClient


def fractional_quantity():
    # Voltage noise density: M L^2 T^(-5/2) I^(-1).
    dimension = Dimension(
        tuple(
            DimensionPower("org.example.si:" + basis, power)
            for basis, power in (
                ("current", -1),
                ("length", 2),
                ("mass", 1),
                ("time", Fraction(-5, 2)),
            )
        )
    )
    return QuantityValue(
        1.25, UnitReference("org.example.noise:volt_per_root_hertz", "1", dimension)
    )


def test_integer_encoding_and_normalized_integral_power_remain_identical():
    dimension = Dimension((DimensionPower("time", Fraction(-6, 3)),))
    assert type(dimension.powers[0].exponent) is int
    old_native = {"powers": [{"basis_id": "time", "exponent": -2}]}
    old_wire = wire.Dimension(powers=[wire.DimensionPower(basis_id="time", exponent=-2)])
    assert dimension_to_data(dimension) == old_native
    assert dimension_from_data(old_native) == dimension
    assert dimension_to_proto(dimension).SerializeToString(
        deterministic=True
    ) == old_wire.SerializeToString(deterministic=True)
    assert dimension_from_proto(old_wire) == dimension


def test_fractional_quantity_round_trips_with_an_explicit_version():
    quantity = fractional_quantity()
    native = canonical_value_to_data(quantity)
    assert native["version"] == 2 and native["unit"]["dimension"]["version"] == 2
    assert canonical_value_from_data(native) == quantity
    message = canonical_value_to_proto(quantity)
    assert message.schema_version == 2 and message.quantity.unit.dimension.schema_version == 2
    restored = canonical_value_from_proto(
        wire.CanonicalValue.FromString(message.SerializeToString(deterministic=True))
    )
    assert restored == quantity
    assert canonical_value_to_proto(restored) == message
    with pytest.raises(ValueError, match="version"):
        canonical_value_from_data({**native, "version": 1})
    message.schema_version = 1
    with pytest.raises(ValueError, match="version"):
        canonical_value_from_proto(message)


@pytest.mark.parametrize("power", [0, True, 0.5, float("inf"), 32768, Fraction(1, 32768)])
def test_powers_are_exact_nonzero_and_bounded(power):
    with pytest.raises(ValueError):
        DimensionPower("basis", power)


@pytest.mark.parametrize(
    "numerator,denominator", [(2, 4), (1, 0), (1, -2), (0, 2), (2, 2), (40000, 3)]
)
def test_noncanonical_rational_wire_and_native_encodings_reject(numerator, denominator):
    with pytest.raises(ValueError):
        dimension_from_data(
            {
                "version": 2,
                "powers": [
                    {"basis_id": "time", "numerator": numerator, "denominator": denominator}
                ],
            }
        )
    with pytest.raises(ValueError):
        dimension_from_proto(
            wire.Dimension(
                schema_version=2,
                rational_powers=[
                    wire.RationalDimensionPower(
                        basis_id="time", numerator=numerator, denominator=denominator
                    )
                ],
            )
        )


def test_mixed_dimension_encodings_reject():
    message = dimension_to_proto(fractional_quantity().unit.dimension)
    message.powers.add(basis_id="other", exponent=1)
    with pytest.raises(ValueError, match="legacy"):
        dimension_from_proto(message)
    message.ClearField("powers")
    message.schema_version = 0
    with pytest.raises(ValueError, match="version"):
        dimension_from_proto(message)


def test_fractional_properties_keep_identity_journal_and_native_undo(tmp_path):
    quantity = fractional_quantity()
    project = value_project(ValueKind.QUANTITY, quantity)
    store = ProjectStore(tmp_path / "project")
    store.initialize(project)
    authority = ProjectAuthority(project, store=store)
    client = CodeVisualizerClient(authority, actor_id="p3")
    changed = replace(quantity, magnitude=2.5)
    assert isinstance(
        client.submit(SetDomainProperty("model", "sample", "value", changed)), CommandAccepted
    )
    assert isinstance(client.undo(), CommandAccepted)
    assert authority.snapshot().domain_workspace.node("sample").property("value") == quantity
    assert isinstance(client.redo(), CommandAccepted)
    encoded = normalized_project_json(authority.snapshot())
    assert normalized_project_json(project_from_json(encoded)) == encoded
    recovered = store.recover()
    assert recovered.domain_workspace.node("sample").property("value") == changed
