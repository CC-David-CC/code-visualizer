"""Published gas measures expressed through the existing unit algebra domain."""

from functools import cache

from code_visualizer.domain.identifiers import ContractDefinition, ContractKind
from code_visualizer.domain.intentional import (
    BundleReference,
    DomainModel,
    IntentionalNode,
    PropertyValue,
    RoleBinding,
)
from code_visualizer.domain.values import CanonicalValue, QuantityValue
from code_visualizer.extensions.adaptive_fields.units import unit_model as cell_units
from code_visualizer.extensions.fields.units import unit_model as field_units
from code_visualizer.extensions.foundations.unit_algebra import SCHEMA_ID, identity
from code_visualizer.extensions.foundations.unit_algebra_si import algebra_si_model
from code_visualizer.extensions.foundations.units import UnitCatalog
from code_visualizer.extensions.foundations.units_si import si_catalog, si_model
from code_visualizer.extensions.publication import FIRST_PARTY_PUBLICATION
from code_visualizer.extensions.registry import DomainExtensionBundle

BUNDLE = BundleReference("code_visualizer.hybrid_gas.units", "1")
FACTORS = (
    ("meter_per_second", (("meter", 1), ("second", -1))),
    ("kilogram_meter_per_second", (("kilogram", 1), ("meter", 1), ("second", -1))),
    ("momentum_per_volume", (("kilogram", 1), ("meter", -2), ("second", -1))),
    ("joule_per_cubic_meter", (("joule", 1), ("meter", -3))),
    ("pascal_second", (("pascal", 1), ("second", 1))),
    ("per_cubic_meter", (("meter", -3),)),
    ("joule_per_kelvin", (("joule", 1), ("kelvin", -1))),
)


@cache
def unit_model() -> DomainModel:
    nodes, roots = [], []
    for name, factors in FACTORS:
        node_id, children = BUNDLE.id + ":" + name, []
        for unit, power in factors:
            child = node_id + ":" + unit
            children.append(child)
            nodes.append(
                IntentionalNode(
                    child,
                    identity("Factor"),
                    (
                        PropertyValue(
                            identity("Factor", "measure"),
                            QuantityValue(1, si_catalog().unit("foundation.units.si:" + unit)),
                        ),
                        PropertyValue(identity("Factor", "numerator"), power),
                        PropertyValue(identity("Factor", "denominator"), 1),
                        PropertyValue(identity("Factor", "interval"), unit == "kelvin"),
                    ),
                )
            )
        nodes.append(
            IntentionalNode(
                node_id,
                identity("ProductUnit"),
                tuple(
                    PropertyValue(identity("ProductUnit", key), value)
                    for key, value in (
                        ("name", name),
                        ("symbol", name),
                        ("contract_id", node_id),
                        ("version", "1"),
                    )
                ),
                (RoleBinding(identity("ProductUnit", "factors"), tuple(children)),),
            )
        )
        roots.append(node_id)
    return DomainModel(
        BUNDLE.id + ":catalog", SCHEMA_ID, "1", tuple(roots), tuple(nodes), "Dilute gas measures"
    )


@cache
def catalog() -> UnitCatalog:
    return UnitCatalog.from_models(
        (si_model(), algebra_si_model(), field_units(), cell_units(), unit_model())
    )


def quantity(value: float, unit: str) -> QuantityValue:
    if unit in {name for name, _ in FACTORS}:
        namespace = BUNDLE.id
    elif unit in ("square_meter", "kilogram_per_cubic_meter"):
        namespace = "foundation.adaptive_fields.units"
    else:
        namespace = "foundation.units.si"
    return QuantityValue(value, catalog().unit(namespace + ":" + unit))


def validate_value(value: CanonicalValue) -> None:
    if isinstance(value, QuantityValue) and value.unit.id.startswith(BUNDLE.id + ":"):
        catalog().validate_reference(value.unit)


def units_bundle() -> DomainExtensionBundle:
    return DomainExtensionBundle(
        BUNDLE.id,
        "1",
        reference_models=(unit_model(),),
        required_bundles=(BundleReference("foundation.adaptive_fields.units", "1"),),
        publication=FIRST_PARTY_PUBLICATION,
        contracts=tuple(
            ContractDefinition(ContractKind.UNIT, root, "1") for root in unit_model().roots
        ),
        canonical_value_validators=(validate_value,),
    )
