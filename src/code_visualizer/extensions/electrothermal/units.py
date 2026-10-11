"""Thermal coefficients are ordinary published product-unit intentions."""

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
from code_visualizer.extensions.foundations.unit_algebra import SCHEMA_ID, identity
from code_visualizer.extensions.foundations.unit_algebra_si import algebra_si_model
from code_visualizer.extensions.foundations.units import UnitCatalog
from code_visualizer.extensions.foundations.units_si import si_catalog, si_model
from code_visualizer.extensions.publication import FIRST_PARTY_PUBLICATION
from code_visualizer.extensions.registry import DomainExtensionBundle

BUNDLE = BundleReference("org.codevisualizer.electrothermal.units", "1")
PRODUCTS = (
    ("per_kelvin", (("kelvin", -1),)),
    ("joule_per_kelvin", (("joule", 1), ("kelvin", -1))),
    ("watt_per_kelvin", (("watt", 1), ("kelvin", -1))),
    ("watt_per_square_meter", (("watt", 1), ("meter", -2))),
)


@cache
def unit_model() -> DomainModel:
    nodes, roots = [], []
    for name, factors in PRODUCTS:
        node_id = BUNDLE.id + ":" + name
        children = []
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
        BUNDLE.id + ":catalog", SCHEMA_ID, "1", tuple(roots), tuple(nodes), "Lumped thermal units"
    )


@cache
def thermal_catalog() -> UnitCatalog:
    return UnitCatalog.from_models((si_model(), algebra_si_model(), unit_model()))


def quantity(value: float, unit: str = "second") -> QuantityValue:
    namespace = BUNDLE.id if unit in {name for name, _ in PRODUCTS} else "foundation.units.si"
    return QuantityValue(value, thermal_catalog().unit(namespace + ":" + unit))


def validate_value(value: CanonicalValue) -> None:
    if isinstance(value, QuantityValue) and value.unit.id.startswith(BUNDLE.id + ":"):
        thermal_catalog().validate_reference(value.unit)


def units_bundle() -> DomainExtensionBundle:
    return DomainExtensionBundle(
        BUNDLE.id,
        "1",
        reference_models=(unit_model(),),
        publication=FIRST_PARTY_PUBLICATION,
        required_bundles=(BundleReference("foundation.units.algebra.si", "1"),),
        contracts=tuple(
            ContractDefinition(ContractKind.UNIT, node_id, "1") for node_id in unit_model().roots
        ),
        canonical_value_validators=(validate_value,),
    )
