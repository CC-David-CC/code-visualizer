"""Physical unit meaning comes from declared intentions, not a library registry."""

from dataclasses import replace
from fractions import Fraction

import pytest
from test_foundation_units import _custom_model

from code_visualizer.domain.intentional import (
    DomainModel,
    DomainWorkspace,
    IntentionalNode,
    PropertyValue,
    RoleBinding,
)
from code_visualizer.domain.project import Project
from code_visualizer.domain.values import Dimension, QuantityValue, UnitReference
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.foundations.unit_algebra import (
    SCHEMA_ID,
    QuantityKind,
    UnitAlgebra,
    algebra_schema,
    identity,
    result_kind,
)
from code_visualizer.extensions.foundations.unit_algebra_si import (
    BUNDLE,
    algebra_si_catalog,
    algebra_si_model,
    validate_algebra_si_workspace,
)
from code_visualizer.extensions.foundations.units import UnitCatalog, UnitError, units_schema
from code_visualizer.extensions.foundations.units_si import si_model
from code_visualizer.extensions.publication import publication_manifest
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.serialization import normalized_project_json


def unit(name):
    prefix = (
        BUNDLE.id
        if name in {"kiloohm", "newton_per_meter", "newton_per_millimeter", "volt_per_root_hertz"}
        else "foundation.units.si"
    )
    return algebra_si_catalog().unit(prefix + ":" + name)


@pytest.mark.parametrize(
    "source,target,magnitude,expected",
    [
        ("kiloohm", "ohm", 2.2, 2200),
        ("milliampere", "ampere", 3, 0.003),
        ("millimeter", "meter", 50, 0.05),
        ("newton_per_millimeter", "newton_per_meter", 0.2, 200),
    ],
)
def test_explicit_scaled_and_compound_units_use_the_checked_pint_adapter(
    source, target, magnitude, expected
):
    pytest.importorskip("pint")
    result = UnitAlgebra(algebra_si_catalog()).convert(
        QuantityValue(magnitude, unit(source)), unit(target)
    )
    assert result.unit == unit(target) and result.magnitude == pytest.approx(expected, rel=1e-12)


def test_no_declared_conversion_means_no_pint_authority(monkeypatch):
    pint = pytest.importorskip("pint")
    custom = _custom_model()
    custom = replace(
        custom,
        roots=("custom:inch",),
        nodes=tuple(node for node in custom.nodes if node.id != "custom:conversion"),
    )
    catalog = UnitCatalog.from_models((si_model(), algebra_si_model(), custom))

    def forbidden(*args, **kwargs):
        pytest.fail("An unauthorized conversion reached Pint")

    monkeypatch.setattr(pint, "UnitRegistry", forbidden)
    with pytest.raises(UnitError) as caught:
        UnitAlgebra(catalog).convert(
            QuantityValue(1, catalog.unit("org.example.units:inch")), unit("meter")
        )
    assert caught.value.issue.code == "UNIT_CONVERSION_UNAVAILABLE"
    with pytest.raises(UnitError, match="unavailable"):
        UnitAlgebra(catalog).form(replace(unit("meter"), version="999"))


def test_voltage_is_not_a_resistance_even_when_numeric_values_match():
    with pytest.raises(UnitError) as caught:
        UnitAlgebra(algebra_si_catalog()).convert(QuantityValue(1, unit("volt")), unit("ohm"))
    assert caught.value.issue.code == "UNIT_DIMENSION_MISMATCH"


def test_temperature_point_and_interval_conversions_remain_distinct():
    pytest.importorskip("pint")
    algebra = UnitAlgebra(algebra_si_catalog())
    value = QuantityValue(20, unit("degree_celsius"))
    assert algebra.convert(
        value, unit("kelvin"), kind=QuantityKind.POINT
    ).magnitude == pytest.approx(293.15)
    assert algebra.convert(
        value, unit("kelvin"), kind=QuantityKind.INTERVAL
    ).magnitude == pytest.approx(20)
    with pytest.raises(UnitError, match="point or interval"):
        algebra.form(unit("kelvin"))


@pytest.mark.parametrize(
    "operator,left,right,expected",
    [
        ("subtract", QuantityKind.POINT, QuantityKind.POINT, QuantityKind.INTERVAL),
        ("add", QuantityKind.POINT, QuantityKind.INTERVAL, QuantityKind.POINT),
        ("add", QuantityKind.INTERVAL, QuantityKind.POINT, QuantityKind.POINT),
        ("subtract", QuantityKind.POINT, QuantityKind.INTERVAL, QuantityKind.POINT),
        ("add", QuantityKind.INTERVAL, QuantityKind.INTERVAL, QuantityKind.INTERVAL),
    ],
)
def test_legal_affine_arithmetic(operator, left, right, expected):
    assert result_kind(operator, left, right) is expected


@pytest.mark.parametrize(
    "operator,left,right",
    [
        ("add", QuantityKind.POINT, QuantityKind.POINT),
        ("subtract", QuantityKind.INTERVAL, QuantityKind.POINT),
        ("multiply", QuantityKind.POINT, QuantityKind.LINEAR),
        ("divide", QuantityKind.LINEAR, QuantityKind.POINT),
        ("negate", QuantityKind.POINT, None),
        ("add", QuantityKind.CYCLIC_FREQUENCY, QuantityKind.ANGULAR_FREQUENCY),
        ("multiply", QuantityKind.LOGARITHMIC, QuantityKind.LINEAR),
    ],
)
def test_ambiguous_or_unsupported_arithmetic_rejects(operator, left, right):
    with pytest.raises(UnitError):
        result_kind(operator, left, right)


def test_voltage_noise_density_and_unit_intentions_round_trip():
    noise = unit("volt_per_root_hertz")
    assert next(
        power.exponent for power in noise.dimension.powers if power.basis_id.endswith("time")
    ) == Fraction(-5, 2)
    workspace = DomainWorkspace(
        (units_schema(), algebra_schema()), (si_model(), algebra_si_model())
    )
    project = Project("units:p3", "Unit algebra", (), domain_workspace=workspace)
    encoded = normalized_project_json(project)
    assert normalized_project_json(project_from_json(encoded)) == encoded
    assert UnitAlgebra(algebra_si_catalog()).form(unit("one")).factors == ()
    with pytest.raises(UnitError):
        UnitAlgebra(algebra_si_catalog()).form(UnitReference("org.missing:one", "1", Dimension()))


def test_published_products_have_exact_dependency_closure():
    manifest = publication_manifest(builtin_registry(), BUNDLE.id, BUNDLE.version)
    assert any(item.id == "foundation.units.si" for item in manifest.dependencies)
    assert any(item.id == "foundation.units.si:volt" for item in manifest.references)
    assert any(item.id == "foundation.units.si:basis.time" for item in manifest.references)


def test_released_si_products_cannot_be_redefined():
    model = algebra_si_model()
    factor_id = BUNDLE.id + ":ohm:factor:0"
    node = model.node(factor_id)
    changed = replace(
        node,
        properties=tuple(
            replace(prop, value=QuantityValue(2, unit("volt")))
            if prop.property_id == identity("Factor", "measure")
            else prop
            for prop in node.properties
        ),
    )
    model = replace(
        model, nodes=tuple(changed if item.id == factor_id else item for item in model.nodes)
    )
    project = Project(
        "units",
        "Units",
        (),
        domain_workspace=DomainWorkspace((units_schema(), algebra_schema()), (si_model(), model)),
    )
    assert {issue.code for issue in validate_algebra_si_workspace(project)} == {
        "UNIT_IMMUTABLE_PRODUCT"
    }


def test_unit_definition_cycle_rejects_before_library_use():
    reference = UnitReference("org.example.units:cycle", "1", Dimension())
    factor = IntentionalNode(
        "factor",
        identity("Factor"),
        (
            PropertyValue(identity("Factor", "measure"), QuantityValue(1, reference)),
            PropertyValue(identity("Factor", "numerator"), 1),
            PropertyValue(identity("Factor", "denominator"), 1),
        ),
    )
    product = IntentionalNode(
        "unit",
        identity("ProductUnit"),
        tuple(
            PropertyValue(identity("ProductUnit", key), value)
            for key, value in {
                "name": "cycle",
                "symbol": "c",
                "contract_id": reference.id,
                "version": "1",
            }.items()
        ),
        (RoleBinding(identity("ProductUnit", "factors"), (factor.id,)),),
    )
    model = DomainModel("cycle", SCHEMA_ID, "1", (product.id,), (product, factor))
    with pytest.raises(UnitError) as caught:
        UnitCatalog.from_models((model,))
    assert caught.value.issue.code == "UNIT_PRODUCT_CYCLE"
