"""The versioned SI vocabulary is one ordinary foundation.units DomainModel."""

from __future__ import annotations

from fractions import Fraction
from functools import cache
from typing import TYPE_CHECKING

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
from code_visualizer.domain.values import CanonicalValue, QuantityValue, UnitReference
from code_visualizer.extensions.foundations.units import (
    BUNDLE as UNITS_BUNDLE,
)
from code_visualizer.extensions.foundations.units import (
    SCHEMA_ID,
    UnitCatalog,
    UnitError,
    identity,
)

if TYPE_CHECKING:
    from code_visualizer.extensions.registry import DomainExtensionBundle

BUNDLE = BundleReference("foundation.units.si", "1")
MODEL_ID = "foundation.units.si:catalog"


@cache
def si_model() -> DomainModel:
    """Return immutable reference intentions; no parallel imperative unit table.

    Stable contract IDs are explicit properties, independent of local object IDs.
    Prefix examples are finite vocabulary members, not an implicit prefix parser.
    """
    nodes: list[IntentionalNode] = []

    def local(name: str) -> str:
        return "si-v1:" + name

    def values(concept: str, **properties: str | int | float) -> tuple[PropertyValue, ...]:
        return tuple(
            PropertyValue(identity(concept, key), value) for key, value in properties.items()
        )

    def named(concept: str, member: str, name: str) -> tuple[PropertyValue, ...]:
        return values(
            concept, name=name, contract_id=BUNDLE.id + ":" + member, version=BUNDLE.version
        )

    bases = (
        "length",
        "mass",
        "time",
        "electric_current",
        "temperature",
        "amount",
        "luminous_intensity",
    )
    for basis in bases:
        nodes.append(
            IntentionalNode(
                local("basis:" + basis),
                identity("DimensionBasis"),
                named("DimensionBasis", "basis." + basis, basis.replace("_", " ").title()),
            )
        )
    unit_ids: list[str] = []

    def unit(member: str, symbol: str, **powers: int) -> None:
        factors: list[str] = []
        for basis, exponent in sorted(powers.items()):
            factor_id = local(member + ":dimension:" + basis)
            factors.append(factor_id)
            nodes.append(
                IntentionalNode(
                    factor_id,
                    identity("DimensionFactor"),
                    values("DimensionFactor", exponent=exponent),
                    references=(
                        RoleBinding(
                            identity("DimensionFactor", "basis"), (local("basis:" + basis),)
                        ),
                    ),
                )
            )
        unit_id = local("unit:" + member)
        unit_ids.append(unit_id)
        nodes.append(
            IntentionalNode(
                unit_id,
                identity("UnitDefinition"),
                (
                    *named("UnitDefinition", member, member.replace("_", " ")),
                    *values("UnitDefinition", symbol=symbol),
                ),
                (RoleBinding(identity("UnitDefinition", "dimension"), tuple(factors)),),
            )
        )

    unit("one", "1")
    unit("meter", "m", length=1)
    unit("kilogram", "kg", mass=1)
    unit("second", "s", time=1)
    unit("ampere", "A", electric_current=1)
    unit("kelvin", "K", temperature=1)
    unit("mole", "mol", amount=1)
    unit("candela", "cd", luminous_intensity=1)
    unit("hertz", "Hz", time=-1)
    unit("newton", "N", mass=1, length=1, time=-2)
    unit("pascal", "Pa", mass=1, length=-1, time=-2)
    unit("joule", "J", mass=1, length=2, time=-2)
    unit("watt", "W", mass=1, length=2, time=-3)
    unit("coulomb", "C", electric_current=1, time=1)
    unit("volt", "V", mass=1, length=2, time=-3, electric_current=-1)
    unit("ohm", "ohm", mass=1, length=2, time=-3, electric_current=-2)
    unit("farad", "F", mass=-1, length=-2, time=4, electric_current=2)
    unit("weber", "Wb", mass=1, length=2, time=-2, electric_current=-1)
    unit("tesla", "T", mass=1, time=-2, electric_current=-1)
    unit("henry", "H", mass=1, length=2, time=-2, electric_current=-2)
    unit("degree_celsius", "degC", temperature=1)
    unit("millimeter", "mm", length=1)
    unit("centimeter", "cm", length=1)
    unit("kilometer", "km", length=1)
    unit("gram", "g", mass=1)
    unit("millisecond", "ms", time=1)
    unit("milliampere", "mA", electric_current=1)
    unit("millivolt", "mV", mass=1, length=2, time=-3, electric_current=-1)
    conversions: list[str] = []

    def conversion(source: str, target: str, scale: int | float, offset: int | float = 0) -> None:
        node_id = local("conversion:" + source + ":" + target)
        conversions.append(node_id)
        nodes.append(
            IntentionalNode(
                node_id,
                identity("Conversion"),
                values("Conversion", name=source + " to " + target, scale=scale, offset=offset),
                references=(
                    RoleBinding(identity("Conversion", "source"), (local("unit:" + source),)),
                    RoleBinding(identity("Conversion", "target"), (local("unit:" + target),)),
                ),
            )
        )

    conversion("millimeter", "meter", 0.001)
    conversion("centimeter", "meter", 0.01)
    conversion("kilometer", "meter", 1000)
    conversion("gram", "kilogram", 0.001)
    conversion("millisecond", "second", 0.001)
    conversion("milliampere", "ampere", 0.001)
    conversion("millivolt", "volt", 0.001)
    conversion("degree_celsius", "kelvin", 1, 273.15)
    root_id = local("system")
    nodes.append(
        IntentionalNode(
            root_id,
            identity("UnitSystem"),
            named("UnitSystem", "system", "International System of Units (SI)"),
            (
                RoleBinding(
                    identity("UnitSystem", "bases"),
                    tuple(local("basis:" + basis) for basis in bases),
                ),
                RoleBinding(identity("UnitSystem", "units"), tuple(unit_ids)),
                RoleBinding(identity("UnitSystem", "conversions"), tuple(conversions)),
            ),
        )
    )
    return DomainModel(
        MODEL_ID,
        SCHEMA_ID,
        "1",
        (root_id,),
        tuple(sorted(nodes, key=lambda node: node.id)),
        "SI units, version 1",
    )


@cache
def si_catalog() -> UnitCatalog:
    return UnitCatalog.from_models((si_model(),))


def si_contracts() -> tuple[ContractDefinition, ...]:
    result: list[ContractDefinition] = []
    for node in si_model().nodes:
        kind = {
            identity("DimensionBasis"): ContractKind.DIMENSION_BASIS,
            identity("UnitDefinition"): ContractKind.UNIT,
        }.get(node.concept_id)
        if kind is not None:
            contract_id = node.property(node.concept_id + ":contract_id")
            version = node.property(node.concept_id + ":version")
            assert isinstance(contract_id, str) and isinstance(version, str)
            result.append(ContractDefinition(kind, contract_id, version))
    return tuple(sorted(result))


def validate_si_reference(reference: UnitReference) -> tuple[DomainIssue, ...]:
    if not reference.id.startswith(BUNDLE.id + ":"):
        return ()
    try:
        si_catalog().validate_reference(reference)
    except UnitError as exc:
        return (exc.issue,)
    return ()


def validate_si_value(value: CanonicalValue) -> None:
    if isinstance(value, QuantityValue):
        issues = validate_si_reference(value.unit)
        if issues:
            issue = issues[0]
            raise UnitError(issue.code, issue.message, issue.object_id)


def validate_si_workspace(project: Project) -> tuple[DomainIssue, ...]:
    issues: list[DomainIssue] = []
    values = (
        *(
            (node.id, prop.property_id, prop.value)
            for model in project.domain_workspace.models
            for node in model.nodes
            for prop in node.properties
        ),
        *(
            (prop.id, "default", prop.default)
            for schema in project.domain_workspace.schemas
            for concept in schema.concepts
            for prop in concept.properties
            if prop.default is not None
        ),
        *(
            (prop.id, "choices", value)
            for schema in project.domain_workspace.schemas
            for concept in schema.concepts
            for prop in concept.properties
            for value in prop.choices
        ),
    )
    for object_id, field, value in values:
        if isinstance(value, QuantityValue):
            issues.extend(
                DomainIssue(issue.code, issue.message, object_id, field, issue.incomplete)
                for issue in validate_si_reference(value.unit)
            )
    models = tuple(
        model for model in project.domain_workspace.models if model.schema_id == SCHEMA_ID
    )
    if models:
        try:
            catalog = UnitCatalog.from_models(models)
            expected = {unit.reference: unit for unit in si_catalog().units}
            for unit in catalog.units:
                if not unit.reference.id.startswith(BUNDLE.id + ":"):
                    continue
                si_catalog().validate_reference(unit.reference)
                definition = expected[unit.reference]
                if (unit.name, unit.symbol) != (definition.name, definition.symbol):
                    raise UnitError(
                        "UNIT_IMMUTABLE_DEFINITION",
                        "A published SI unit definition cannot be redefined",
                        unit.node_id,
                    )
            for conversion in catalog.conversions:
                if conversion.source in expected and conversion.target in expected:
                    coefficients = si_catalog()._coefficients(conversion.source, conversion.target)
                    if coefficients != (
                        Fraction(str(conversion.scale)),
                        Fraction(str(conversion.offset)),
                    ):
                        raise UnitError(
                            "UNIT_IMMUTABLE_CONVERSION",
                            "A conversion cannot redefine published SI units",
                            conversion.node_id,
                        )
            bases = {
                node.property(identity("DimensionBasis", "contract_id")): node.properties
                for node in si_model().nodes
                if node.concept_id == identity("DimensionBasis")
            }
            for model in models:
                for node in model.nodes:
                    if node.concept_id != identity("DimensionBasis"):
                        continue
                    contract = node.property(identity("DimensionBasis", "contract_id"))
                    if (
                        isinstance(contract, str)
                        and contract.startswith(BUNDLE.id + ":")
                        and (contract not in bases or set(node.properties) != set(bases[contract]))
                    ):
                        raise UnitError(
                            "UNIT_IMMUTABLE_BASIS",
                            "A published SI dimension basis cannot be redefined",
                            node.id,
                        )
        except UnitError as exc:
            issues.append(exc.issue)
    return tuple(issues)


def si_bundle() -> DomainExtensionBundle:
    from code_visualizer.extensions.publication import FIRST_PARTY_PUBLICATION
    from code_visualizer.extensions.registry import DomainExtensionBundle

    return DomainExtensionBundle(
        BUNDLE.id,
        BUNDLE.version,
        required_bundles=(UNITS_BUNDLE,),
        reference_models=(si_model(),),
        publication=FIRST_PARTY_PUBLICATION,
        contracts=si_contracts(),
        workspace_validators=(validate_si_workspace,),
        canonical_value_validators=(validate_si_value,),
    )
