"""Exact unit products and checked quantity operations over the canonical catalog.

Pint is a worker adapter. Its registry receives only internally generated names
and an already authorized conversion; it never supplies domain permissions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import StrEnum
from fractions import Fraction
from functools import cache

from code_visualizer.domain.identifiers import (
    validate_contract_version,
    validate_global_contract_id,
)
from code_visualizer.domain.intentional import (
    BundleReference,
    ConceptDefinition,
    DomainModel,
    DomainSchema,
    DomainWorkspace,
    PropertyDefinition,
    RoleDefinition,
    ValueKind,
)
from code_visualizer.domain.intentional_validation import validate_domain_workspace
from code_visualizer.domain.values import Dimension, DimensionPower, QuantityValue, UnitReference
from code_visualizer.extensions.foundations.units import (
    UnitCatalog,
    UnitDefinition,
    UnitError,
    UnitFactor,
    UnitProduct,
)

BUNDLE = BundleReference("foundation.units.algebra", "1")
PREFIX = BUNDLE.id + ":"
SCHEMA_ID = PREFIX + "schema"
MAX_UNIT_FACTORS = 64


class QuantityKind(StrEnum):
    LINEAR = "linear"
    POINT = "point"
    INTERVAL = "interval"
    CYCLIC_FREQUENCY = "cyclic_frequency"
    ANGULAR_FREQUENCY = "angular_frequency"
    LOGARITHMIC = "logarithmic"


def _require_supported_kinds(*kinds: QuantityKind | None, object_id: str = "") -> None:
    if any(
        kind
        in (
            QuantityKind.CYCLIC_FREQUENCY,
            QuantityKind.ANGULAR_FREQUENCY,
            QuantityKind.LOGARITHMIC,
        )
        for kind in kinds
    ):
        raise UnitError(
            "UNIT_KIND_UNSUPPORTED",
            "Frequency/logarithmic kinds need an explicit supported operator",
            object_id,
        )


def identity(concept: str, field: str | None = None) -> str:
    return PREFIX + concept + (":" + field if field else "")


@cache
def algebra_schema() -> DomainSchema:
    def prop(concept: str, field: str, kind: ValueKind = ValueKind.STRING) -> PropertyDefinition:
        return PropertyDefinition(
            identity(concept, field), field.replace("_", " ").title(), kind, True
        )

    def factors(concept: str) -> tuple[RoleDefinition, ...]:
        return (
            RoleDefinition(
                identity(concept, "factors"), "Factors", (identity("Factor"),), 0, MAX_UNIT_FACTORS
            ),
        )

    return DomainSchema(
        SCHEMA_ID,
        BUNDLE.id,
        BUNDLE.version,
        (
            ConceptDefinition(
                identity("Factor"),
                "Unit factor",
                (
                    prop("Factor", "measure", ValueKind.QUANTITY),
                    prop("Factor", "numerator", ValueKind.INTEGER),
                    prop("Factor", "denominator", ValueKind.INTEGER),
                    PropertyDefinition(
                        identity("Factor", "interval"),
                        "Temperature interval",
                        ValueKind.BOOLEAN,
                        default=False,
                    ),
                ),
            ),
            ConceptDefinition(
                identity("ProductUnit"),
                "Product unit",
                tuple(
                    prop("ProductUnit", field)
                    for field in ("name", "symbol", "contract_id", "version")
                ),
                factors("ProductUnit"),
                display_property_id=identity("ProductUnit", "name"),
            ),
            ConceptDefinition(
                identity("UnitEquation"),
                "Unit equation",
                (prop("UnitEquation", "name"), prop("UnitEquation", "unit", ValueKind.QUANTITY)),
                factors("UnitEquation"),
                display_property_id=identity("UnitEquation", "name"),
                description="One named unit equals the product of the declared factor measures.",
            ),
        ),
        BUNDLE,
        "Versioned products of quantities and exact rational unit powers.",
    )


def dimension_product(factors: tuple[tuple[Dimension, Fraction], ...]) -> Dimension:
    powers: dict[str, Fraction] = {}
    for dimension, exponent in factors:
        for power in dimension.powers:
            powers[power.basis_id] = (
                powers.get(power.basis_id, Fraction()) + Fraction(power.exponent) * exponent
            )
    return Dimension(
        tuple(DimensionPower(basis, power) for basis, power in sorted(powers.items()) if power)
    )


def _real(value: object) -> float:
    if type(value) not in (int, float):
        raise UnitError(
            "UNIT_REAL_REQUIRED", "This algebra adapter requires real scalar magnitudes"
        )
    assert isinstance(value, (int, float))
    try:
        result = float(value)
    except OverflowError as exc:
        raise UnitError("UNIT_NUMERIC_RANGE", "Magnitude is outside the numerical range") from exc
    if not math.isfinite(result):
        raise UnitError("UNIT_NUMERIC_RANGE", "Magnitude must be finite")
    return result


def extend_unit_catalog(base: UnitCatalog, models: tuple[DomainModel, ...]) -> UnitCatalog:
    selected = tuple(model for model in models if model.schema_id == SCHEMA_ID)
    if not selected:
        return base
    issues = validate_domain_workspace(DomainWorkspace((algebra_schema(),), selected))
    if issues:
        raise UnitError(issues[0].code, issues[0].message, issues[0].object_id)
    nodes = {node.id: node for model in selected for node in model.nodes}
    units = list(base.units)
    products: list[UnitProduct] = []
    for node in sorted(nodes.values(), key=lambda item: item.id):
        if node.concept_id not in (identity("ProductUnit"), identity("UnitEquation")):
            continue
        factors: list[UnitFactor] = []
        for child_id in node.child_ids(node.concept_id + ":factors"):
            child = nodes[child_id]
            measure = child.property(identity("Factor", "measure"))
            numerator, denominator = (
                child.property(identity("Factor", field)) for field in ("numerator", "denominator")
            )
            if not isinstance(measure, QuantityValue) or _real(measure.magnitude) <= 0:
                raise UnitError(
                    "UNIT_FACTOR_MEASURE", "Unit factors require positive finite measures", child.id
                )
            if (
                type(numerator) is not int
                or type(denominator) is not int
                or not 1 <= denominator <= 32767
                or not -32768 <= numerator <= 32767
                or not numerator
            ):
                raise UnitError(
                    "UNIT_FACTOR_POWER",
                    "Unit factor requires a bounded nonzero rational power",
                    child.id,
                )
            exponent = Fraction(numerator, denominator)
            if (exponent.numerator, exponent.denominator) != (numerator, denominator):
                raise UnitError("UNIT_FACTOR_POWER", "Unit factor power must be reduced", child.id)
            factors.append(
                UnitFactor(
                    measure, exponent, child.property(identity("Factor", "interval")) is True
                )
            )
        dimension = dimension_product(
            tuple((factor.measure.unit.dimension, factor.exponent) for factor in factors)
        )
        if node.concept_id == identity("ProductUnit"):
            values = tuple(
                node.property(node.concept_id + ":" + name)
                for name in ("contract_id", "version", "name", "symbol")
            )
            if any(not isinstance(item, str) or not item for item in values):
                raise UnitError(
                    "UNIT_REQUIRED_PROPERTY",
                    "Product unit requires identity, version, name and symbol",
                    node.id,
                )
            contract_id, version, name, symbol = values
            assert (
                isinstance(contract_id, str)
                and isinstance(version, str)
                and isinstance(name, str)
                and isinstance(symbol, str)
            )
            validate_global_contract_id(contract_id)
            validate_contract_version(version)
            unit = UnitReference(contract_id, version, dimension)
            if any(
                (item.reference.id, item.reference.version) == (unit.id, unit.version)
                for item in units
            ):
                raise UnitError(
                    "UNIT_DUPLICATE_CONTRACT", "Product unit redefines a registered unit", node.id
                )
            units.append(UnitDefinition(node.id, unit, name, symbol))
        else:
            quantity = node.property(identity("UnitEquation", "unit"))
            if not isinstance(quantity, QuantityValue) or _real(quantity.magnitude) != 1:
                raise UnitError(
                    "UNIT_EQUATION_TARGET",
                    "A unit equation defines exactly one target unit",
                    node.id,
                )
            unit = quantity.unit
            if dimension != unit.dimension:
                raise UnitError(
                    "UNIT_DIMENSION_MISMATCH", "Unit equation changes its target dimension", node.id
                )
        if any(item.unit == unit for item in products):
            raise UnitError(
                "UNIT_PRODUCT_AMBIGUOUS", "One unit has more than one product definition", node.id
            )
        products.append(UnitProduct(node.id, unit, tuple(factors)))
    catalog = replace(
        base,
        units=tuple(sorted(units, key=lambda item: (item.reference.id, item.reference.version))),
        products=tuple(products),
    )
    for product in catalog.products:
        catalog.validate_reference(product.unit)
        for factor in product.factors:
            catalog.validate_reference(factor.measure.unit)
    algebra = UnitAlgebra(catalog)
    for product in products:
        algebra.form(product.unit)
    return catalog


@dataclass(frozen=True, slots=True)
class UnitForm:
    dimension: Dimension
    factors: tuple[tuple[UnitReference, Fraction], ...]
    scale: float = 1.0
    offset: float = 0.0


class UnitAlgebra:
    def __init__(self, catalog: UnitCatalog, *, context: str | None = None) -> None:
        self.catalog = catalog
        self.context = context
        self._products = {item.unit: item for item in catalog.products}
        self._forms: dict[tuple[UnitReference, QuantityKind], UnitForm] = {}

    def _component(self, unit: UnitReference) -> tuple[UnitReference, ...]:
        pending, visited = [unit], set()
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            for edge in self.catalog.conversions:
                if edge.context in (None, self.context):
                    if edge.source == current:
                        pending.append(edge.target)
                    elif edge.target == current:
                        pending.append(edge.source)
        return tuple(sorted(visited, key=lambda item: (item.id, item.version)))

    def form(self, unit: UnitReference, kind: QuantityKind = QuantityKind.LINEAR) -> UnitForm:
        return self._form(unit, kind, ())

    def _form(
        self, unit: UnitReference, kind: QuantityKind, path: tuple[UnitReference, ...]
    ) -> UnitForm:
        self.catalog.validate_reference(unit)
        _require_supported_kinds(kind, object_id=unit.id)
        cached = self._forms.get((unit, kind))
        if cached is not None:
            return cached
        if unit in path or len(path) >= MAX_UNIT_FACTORS:
            raise UnitError(
                "UNIT_PRODUCT_CYCLE",
                "Unit definitions contain a cycle or exceed the expansion bound",
                unit.id,
            )
        component = self._component(unit)
        expanded = tuple(item for item in component if item in self._products)
        if len(expanded) > 1:
            raise UnitError(
                "UNIT_PRODUCT_AMBIGUOUS",
                "A conversion component has multiple product definitions",
                unit.id,
            )
        anchor = expanded[0] if expanded else component[0]
        scale, offset = self.catalog._coefficients(unit, anchor, context=self.context)
        if offset and kind is QuantityKind.LINEAR:
            raise UnitError(
                "UNIT_POINT_REQUIRES_KIND",
                "An affine quantity must explicitly be a point or interval",
                unit.id,
            )
        product = self._products.get(anchor)
        if product is None:
            result = UnitForm(
                unit.dimension,
                ((anchor, Fraction(1)),),
                float(scale),
                float(offset) if kind is QuantityKind.POINT else 0.0,
            )
        else:
            if offset or kind is QuantityKind.POINT:
                raise UnitError(
                    "UNIT_POINT_PRODUCT", "Affine points cannot be used in unit products", unit.id
                )
            powers: dict[UnitReference, Fraction] = {}
            numeric_scale = float(scale)
            for factor in product.factors:
                form = self._form(
                    factor.measure.unit,
                    QuantityKind.INTERVAL if factor.interval else QuantityKind.LINEAR,
                    (*path, unit),
                )
                numeric_scale *= (_real(factor.measure.magnitude) * form.scale) ** float(
                    factor.exponent
                )
                for atom, exponent in form.factors:
                    powers[atom] = powers.get(atom, Fraction()) + exponent * factor.exponent
            result = UnitForm(
                unit.dimension,
                tuple(
                    sorted(
                        ((atom, power) for atom, power in powers.items() if power),
                        key=lambda item: (item[0].id, item[0].version),
                    )
                ),
                numeric_scale,
            )
        if (
            not math.isfinite(result.scale)
            or result.scale <= 0
            or len(result.factors) > MAX_UNIT_FACTORS
        ):
            raise UnitError(
                "UNIT_NUMERIC_RANGE",
                "Unit expansion exceeds its numerical or structural bound",
                unit.id,
            )
        self._forms[unit, kind] = result
        return result

    def convert(
        self,
        quantity: QuantityValue,
        target: UnitReference,
        *,
        kind: QuantityKind = QuantityKind.LINEAR,
    ) -> QuantityValue:
        source_form, target_form = self.form(quantity.unit, kind), self.form(target, kind)
        if source_form.dimension != target_form.dimension:
            raise UnitError("UNIT_DIMENSION_MISMATCH", "Quantity dimensions differ", target.id)
        if source_form.factors != target_form.factors:
            raise UnitError(
                "UNIT_CONVERSION_UNAVAILABLE",
                "No declared unit-product/conversion path authorizes this conversion",
                target.id,
            )
        # There is no default Pint vocabulary, alias or prefix at this boundary.
        # The text below is generated solely from bounded numeric data and private names.
        try:
            import pint
        except ImportError as exc:
            raise UnitError(
                "SCIENCE_DEPENDENCY_MISSING",
                "Install the science extra to use the quantity adapter",
            ) from exc
        registry = pint.UnitRegistry(None)
        factors = []
        for index, (_atom, exponent) in enumerate(source_form.factors):
            registry.define(f"cv_atom_{index} = [cv_basis_{index}]")
            factors.append(f"cv_atom_{index} ** ({exponent.numerator} / {exponent.denominator})")
        expression = " * ".join(factors) or "dimensionless"
        for name, form in (("cv_source", source_form), ("cv_target", target_form)):
            definition = f"{name} = {form.scale!r} * ({expression})"
            if form.offset:
                definition += f"; offset: {form.offset!r}"
            registry.define(definition)
        value = registry.Quantity(_real(quantity.magnitude), "cv_source").to("cv_target").magnitude
        return QuantityValue(_real(value), target)


def result_kind(
    operator: str,
    left: QuantityKind,
    right: QuantityKind | None = None,
    *,
    left_dimension: Dimension | None = None,
    right_dimension: Dimension | None = None,
) -> QuantityKind:
    """Infer arithmetic kind; interval scaling requires the scalar's actual dimension.

    Dimension and declared unit-factor compatibility are checked by the caller.
    Missing dimensional context is not permission to treat an operand as a scalar.
    """
    _require_supported_kinds(left, right)
    if operator == "subtract" and left is right is QuantityKind.POINT:
        return QuantityKind.INTERVAL
    if operator in ("add", "subtract"):
        if left is QuantityKind.POINT and right is QuantityKind.INTERVAL:
            return QuantityKind.POINT
        if operator == "add" and left is QuantityKind.INTERVAL and right is QuantityKind.POINT:
            return QuantityKind.POINT
        if left is right and left is not QuantityKind.POINT:
            return left
        raise UnitError(
            "UNIT_KIND_MISMATCH",
            "Addition/subtraction requires compatible linear quantities, points or intervals",
        )
    if left is QuantityKind.POINT or right is QuantityKind.POINT:
        raise UnitError(
            "UNIT_POINT_OPERATION", "Affine points cannot be multiplied, divided or negated"
        )
    if (
        operator in ("multiply", "divide")
        and left is QuantityKind.INTERVAL
        and right is QuantityKind.LINEAR
    ):
        scalar_dimension = right_dimension
    elif operator == "multiply" and left is QuantityKind.LINEAR and right is QuantityKind.INTERVAL:
        scalar_dimension = left_dimension
    else:
        return left if right is None else QuantityKind.LINEAR
    if scalar_dimension is None:
        raise UnitError(
            "UNIT_DIMENSION_REQUIRED",
            "Interval scaling requires the linear operand's explicit dimension",
        )
    return QuantityKind.INTERVAL if not scalar_dimension.powers else QuantityKind.LINEAR


def residual_kind(left: QuantityKind, right: QuantityKind) -> QuantityKind:
    """Equality compares like kinds; a difference between points is an interval.

    This is deliberately symmetric and distinct from arithmetic translation.
    The caller must also establish dimension and declared unit compatibility.
    """
    _require_supported_kinds(left, right)
    if left is not right:
        raise UnitError(
            "UNIT_KIND_MISMATCH", "Equality requires the same quantity kind on both sides"
        )
    if left is QuantityKind.POINT:
        return QuantityKind.INTERVAL
    return left
