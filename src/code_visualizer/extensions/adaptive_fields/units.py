"""Ordinary published unit intentions for cell measures and conserved concentrations."""

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
from code_visualizer.extensions.fields.units import unit_model as field_units
from code_visualizer.extensions.foundations.unit_algebra import SCHEMA_ID, identity
from code_visualizer.extensions.foundations.unit_algebra_si import algebra_si_model
from code_visualizer.extensions.foundations.units import UnitCatalog
from code_visualizer.extensions.foundations.units_si import si_catalog, si_model
from code_visualizer.extensions.publication import FIRST_PARTY_PUBLICATION
from code_visualizer.extensions.registry import DomainExtensionBundle

BUNDLE = BundleReference("foundation.adaptive_fields.units", "1")


@cache
def unit_model() -> DomainModel:
    nodes, roots = [], []
    definitions = (
        ("square_meter", (("meter", 2),)),
        ("square_centimeter", (("centimeter", 2),)),
        ("kilogram_per_cubic_meter", (("kilogram", 1), ("meter", -3))),
        ("gram_per_cubic_centimeter", (("gram", 1), ("centimeter", -3))),
    )
    for name, factors in definitions:
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
        BUNDLE.id + ":catalog",
        SCHEMA_ID,
        "1",
        tuple(roots),
        tuple(nodes),
        "Adaptive field measures",
    )


@cache
def catalog() -> UnitCatalog:
    return UnitCatalog.from_models((si_model(), algebra_si_model(), field_units(), unit_model()))


def quantity(value: float, unit: str = "second") -> QuantityValue:
    if unit in (
        "square_meter",
        "square_centimeter",
        "kilogram_per_cubic_meter",
        "gram_per_cubic_centimeter",
    ):
        namespace = BUNDLE.id
    elif unit.startswith("square_"):
        namespace = "foundation.fields.units"
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
        required_bundles=(BundleReference("foundation.fields.units", "1"),),
        publication=FIRST_PARTY_PUBLICATION,
        contracts=tuple(
            ContractDefinition(ContractKind.UNIT, root, "1") for root in unit_model().roots
        ),
        canonical_value_validators=(validate_value,),
    )
