"""CAD measurement units are ordinary published foundation unit intentions."""

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

BUNDLE = BundleReference("code_visualizer.cad.units", "1")


@cache
def measurement_units() -> DomainModel:
    nodes, roots = [], []
    for name, power, symbol in (("square_meter", 2, "m²"), ("cubic_meter", 3, "m³")):
        node_id = BUNDLE.id + ":" + name
        factor_id = node_id + ":factor"
        nodes.append(
            IntentionalNode(
                factor_id,
                identity("Factor"),
                (
                    PropertyValue(
                        identity("Factor", "measure"),
                        QuantityValue(1, si_catalog().unit("foundation.units.si:meter")),
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
                    PropertyValue(identity("ProductUnit", field), value)
                    for field, value in (
                        ("name", name),
                        ("symbol", symbol),
                        ("contract_id", node_id),
                        ("version", "1"),
                    )
                ),
                (RoleBinding(identity("ProductUnit", "factors"), (factor_id,)),),
            )
        )
        roots.append(node_id)
    return DomainModel(
        BUNDLE.id + ":catalog", SCHEMA_ID, "1", tuple(roots), tuple(nodes), "CAD measurement units"
    )


@cache
def cad_catalog() -> UnitCatalog:
    return UnitCatalog.from_models((si_model(), algebra_si_model(), measurement_units()))


def validate_value(value: CanonicalValue) -> None:
    if isinstance(value, QuantityValue) and value.unit.id.startswith(BUNDLE.id + ":"):
        cad_catalog().validate_reference(value.unit)


def units_bundle() -> DomainExtensionBundle:
    return DomainExtensionBundle(
        BUNDLE.id,
        BUNDLE.version,
        reference_models=(measurement_units(),),
        publication=FIRST_PARTY_PUBLICATION,
        required_bundles=(BundleReference("foundation.units.algebra.si", "1"),),
        contracts=tuple(
            ContractDefinition(ContractKind.UNIT, BUNDLE.id + ":" + name, "1")
            for name in ("square_meter", "cubic_meter")
        ),
        canonical_value_validators=(validate_value,),
    )
