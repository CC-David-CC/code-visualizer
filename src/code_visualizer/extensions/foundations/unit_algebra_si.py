"""Released SI product relations are ordinary intentions, separate from SI v1 bytes."""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
from functools import cache

from code_visualizer.domain.identifiers import ContractDefinition, ContractKind
from code_visualizer.domain.intentional import (
    BundleReference,
    DomainIssue,
    DomainModel,
    IntentionalNode,
    PropertyValue,
    RoleBinding,
)
from code_visualizer.domain.project import Project
from code_visualizer.domain.values import CanonicalValue, QuantityValue
from code_visualizer.extensions.foundations.unit_algebra import BUNDLE as ALGEBRA_BUNDLE
from code_visualizer.extensions.foundations.unit_algebra import (
    SCHEMA_ID,
    algebra_schema,
    identity,
)
from code_visualizer.extensions.foundations.units import UnitCatalog, UnitError
from code_visualizer.extensions.foundations.units_si import BUNDLE as SI_BUNDLE
from code_visualizer.extensions.foundations.units_si import si_catalog, si_model
from code_visualizer.extensions.publication import FIRST_PARTY_PUBLICATION
from code_visualizer.extensions.registry import DomainExtensionBundle

BUNDLE = BundleReference("foundation.units.algebra.si", "1")
MODEL_ID = BUNDLE.id + ":catalog"


@cache
def algebra_si_model() -> DomainModel:
    nodes: list[IntentionalNode] = []
    roots: list[str] = []
    catalog = si_catalog()

    def values(concept: str, **fields: CanonicalValue) -> tuple[PropertyValue, ...]:
        return tuple(
            PropertyValue(identity(concept, field), value) for field, value in fields.items()
        )

    def definition(
        name: str,
        factors: tuple[tuple[str, int | Fraction, int | float], ...],
        symbol: str | None = None,
    ) -> None:
        concept = "ProductUnit" if symbol is not None else "UnitEquation"
        node_id = BUNDLE.id + ":" + name
        children = []
        for index, (unit_name, power, magnitude) in enumerate(factors):
            factor_id = node_id + f":factor:{index}"
            children.append(factor_id)
            exponent = Fraction(power)
            nodes.append(
                IntentionalNode(
                    factor_id,
                    identity("Factor"),
                    values(
                        "Factor",
                        measure=QuantityValue(
                            magnitude, catalog.unit(SI_BUNDLE.id + ":" + unit_name)
                        ),
                        numerator=exponent.numerator,
                        denominator=exponent.denominator,
                    ),
                )
            )
        properties = values(concept, name=name.replace("_", " "))
        if symbol is not None:
            properties += values(
                concept, symbol=symbol, contract_id=node_id, version=BUNDLE.version
            )
        else:
            properties += values(
                concept, unit=QuantityValue(1, catalog.unit(SI_BUNDLE.id + ":" + name))
            )
        nodes.append(
            IntentionalNode(
                node_id,
                identity(concept),
                properties,
                (RoleBinding(identity(concept, "factors"), tuple(children)),),
            )
        )
        roots.append(node_id)

    # The existing SI model is untouched. These explicit new equations authorize
    # products; merely sharing a physical dimension still authorizes nothing.
    definition("one", ())
    definition("hertz", (("second", -1, 1),))
    definition("newton", (("kilogram", 1, 1), ("meter", 1, 1), ("second", -2, 1)))
    definition("volt", (("newton", 1, 1), ("meter", 1, 1), ("ampere", -1, 1), ("second", -1, 1)))
    definition("ohm", (("volt", 1, 1), ("ampere", -1, 1)))
    definition("kiloohm", (("ohm", 1, 1000),), "kOhm")
    definition("newton_per_meter", (("newton", 1, 1), ("meter", -1, 1)), "N/m")
    definition("newton_per_millimeter", (("newton", 1, 1), ("millimeter", -1, 1)), "N/mm")
    definition("volt_per_root_hertz", (("volt", 1, 1), ("hertz", Fraction(-1, 2), 1)), "V/sqrt(Hz)")
    return DomainModel(
        MODEL_ID,
        SCHEMA_ID,
        "1",
        tuple(roots),
        tuple(sorted(nodes, key=lambda node: node.id)),
        "SI unit products",
    )


@cache
def algebra_si_catalog() -> UnitCatalog:
    return UnitCatalog.from_models((si_model(), algebra_si_model()))


def validate_algebra(project: Project, model: DomainModel) -> tuple[DomainIssue, ...]:
    models = (*(item for item in project.domain_workspace.models if item.id != model.id), model)
    try:
        UnitCatalog.from_models(models)
    except (UnitError, ValueError, OverflowError) as exc:
        return (
            exc.issue
            if isinstance(exc, UnitError)
            else DomainIssue("UNIT_ALGEBRA_INVALID", str(exc), model.id, incomplete=True),
        )
    return ()


def validate_algebra_si_value(value: CanonicalValue) -> None:
    if isinstance(value, QuantityValue) and value.unit.id.startswith(BUNDLE.id + ":"):
        algebra_si_catalog().validate_reference(value.unit)


def validate_algebra_si_workspace(project: Project) -> tuple[DomainIssue, ...]:
    if not any(model.schema_id == SCHEMA_ID for model in project.domain_workspace.models):
        return ()
    try:
        catalog = UnitCatalog.from_models(project.domain_workspace.models)
        expected = algebra_si_catalog()
        products = {item.unit: item.factors for item in expected.products}
        units = {item.reference: replace(item, node_id="") for item in expected.units}
        for product in catalog.products:
            if (
                product.unit.id.startswith((SI_BUNDLE.id + ":", BUNDLE.id + ":"))
                and products.get(product.unit) != product.factors
            ):
                raise UnitError(
                    "UNIT_IMMUTABLE_PRODUCT",
                    "Published SI product relationships cannot be redefined",
                    product.node_id,
                )
        for unit in catalog.units:
            if unit.reference.id.startswith(BUNDLE.id + ":") and units.get(
                unit.reference
            ) != replace(unit, node_id=""):
                raise UnitError(
                    "UNIT_IMMUTABLE_DEFINITION",
                    "Published SI product units cannot be redefined",
                    unit.node_id,
                )
    except (UnitError, ValueError) as exc:
        return (
            exc.issue
            if isinstance(exc, UnitError)
            else DomainIssue("UNIT_ALGEBRA_INVALID", str(exc), MODEL_ID, incomplete=True),
        )
    return ()


def algebra_bundle() -> DomainExtensionBundle:
    return DomainExtensionBundle(
        ALGEBRA_BUNDLE.id,
        ALGEBRA_BUNDLE.version,
        schemas=(algebra_schema(),),
        validators=(validate_algebra,),
        required_bundles=(BundleReference("foundation.units", "1"),),
        publication=FIRST_PARTY_PUBLICATION,
    )


def algebra_si_bundle() -> DomainExtensionBundle:
    contracts = tuple(
        ContractDefinition(ContractKind.UNIT, unit.reference.id, unit.reference.version)
        for unit in algebra_si_catalog().units
        if unit.reference.id.startswith(BUNDLE.id + ":")
    )
    return DomainExtensionBundle(
        BUNDLE.id,
        BUNDLE.version,
        required_bundles=(ALGEBRA_BUNDLE, SI_BUNDLE),
        reference_models=(algebra_si_model(),),
        contracts=contracts,
        workspace_validators=(validate_algebra_si_workspace,),
        canonical_value_validators=(validate_algebra_si_value,),
        publication=FIRST_PARTY_PUBLICATION,
    )
