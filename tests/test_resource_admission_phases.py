"""Host contract checks are inert; worker validation owns executable interpretation."""

from dataclasses import replace

import pytest

from code_visualizer.application.resource_admission import (
    check_resource_descriptor,
    check_value_contracts,
    validate_resource_descriptor,
    validate_value_contracts,
)
from code_visualizer.domain.resources import TensorDescriptor
from code_visualizer.domain.values import Dimension, DimensionPower, QuantityValue, TensorDType
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.foundations.units_si import si_catalog
from code_visualizer.generation.transformation import TransformationError
from code_visualizer.persistence.resource_store import ResourceStore


def test_host_value_and_resource_checks_never_run_registered_callbacks(tmp_path, monkeypatch):
    registry = builtin_registry()
    unit = si_catalog().unit("foundation.units.si:meter")
    quantity = QuantityValue(3.0, unit)
    descriptor = ResourceStore(tmp_path).put(
        b"\x00" * 4,
        "application/octet-stream",
        tensor=TensorDescriptor(TensorDType.FLOAT32, (1,), unit=unit),
    )
    calls = []

    def validate(value):
        calls.append(value)
        raise ValueError("worker-only behavior")

    monkeypatch.setattr(registry, "validate_value", validate)
    check_value_contracts(quantity, registry)
    check_resource_descriptor(descriptor, registry)
    assert calls == []
    with pytest.raises(ValueError, match="worker-only"):
        validate_value_contracts(quantity, registry)
    with pytest.raises(ValueError, match="worker-only"):
        validate_resource_descriptor(descriptor, registry)
    assert len(calls) == 2


@pytest.mark.parametrize("missing", ("unit", "basis"))
def test_inert_checks_reject_unknown_public_unit_and_dimension_references(missing):
    registry = builtin_registry()
    unit = si_catalog().unit("foundation.units.si:meter")
    if missing == "unit":
        unit = replace(unit, id="org.example.missing:unit")
    else:
        unit = replace(unit, dimension=Dimension((DimensionPower("org.example.missing:basis", 1),)))
    with pytest.raises(TransformationError) as error:
        check_value_contracts(QuantityValue(1.0, unit), registry)
    assert error.value.code == "RESOURCE_VALUE_CONTRACT_UNAVAILABLE"


def test_worker_validation_retains_dimensional_meaning_beyond_reference_presence():
    registry = builtin_registry()
    meter = si_catalog().unit("foundation.units.si:meter")
    second = si_catalog().unit("foundation.units.si:second")
    forged = QuantityValue(1.0, replace(meter, dimension=second.dimension))
    check_value_contracts(forged, registry)  # Both immutable public identities exist.
    with pytest.raises(ValueError):
        validate_value_contracts(forged, registry)
