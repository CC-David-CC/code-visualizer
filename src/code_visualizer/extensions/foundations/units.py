"""Ordinary unit-definition intentions and their disposable conversion index.

The kernel knows dimension contracts, never SI, unit symbols, or conversion rules.
All conversion meaning below comes from immutable, schema-validated model data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from functools import cache
from typing import TYPE_CHECKING

from code_visualizer.domain.identifiers import (
    validate_contract_version,
    validate_global_contract_id,
)
from code_visualizer.domain.intentional import (
    BundleReference,
    ConceptDefinition,
    DomainIssue,
    DomainModel,
    DomainSchema,
    DomainWorkspace,
    IntentionalNode,
    PropertyDefinition,
    RoleDefinition,
    ValueKind,
)
from code_visualizer.domain.intentional_validation import validate_domain_workspace
from code_visualizer.domain.notation import NotationDefinition, NotationKind
from code_visualizer.domain.project import Project
from code_visualizer.domain.values import (
    ComplexValue,
    Dimension,
    DimensionPower,
    QuantityValue,
    UnitReference,
)

if TYPE_CHECKING:
    from code_visualizer.extensions.registry import DomainExtensionBundle

PREFIX = "foundation.units:"
SCHEMA_ID = PREFIX + "schema"
BUNDLE = BundleReference("foundation.units", "1")


def identity(concept: str, field: str | None = None) -> str:
    return PREFIX + concept + (":" + field if field else "")


@cache
def units_schema() -> DomainSchema:
    def property_(
        concept: str, name: str, kind: ValueKind = ValueKind.STRING
    ) -> PropertyDefinition:
        return PropertyDefinition(
            identity(concept, name), name.replace("_", " ").title(), kind, True
        )

    def named(concept: str) -> tuple[PropertyDefinition, ...]:
        return tuple(property_(concept, name) for name in ("name", "contract_id", "version"))

    def role(
        concept: str, name: str, target: str, minimum: int = 0, maximum: int | None = None
    ) -> RoleDefinition:
        return RoleDefinition(
            identity(concept, name), name.title(), (identity(target),), minimum, maximum
        )

    return DomainSchema(
        SCHEMA_ID,
        BUNDLE.id,
        BUNDLE.version,
        (
            ConceptDefinition(
                identity("DimensionBasis"),
                "Dimension basis",
                named("DimensionBasis"),
                display_property_id=identity("DimensionBasis", "name"),
            ),
            ConceptDefinition(
                identity("DimensionFactor"),
                "Dimension factor",
                (
                    PropertyDefinition(
                        identity("DimensionFactor", "exponent"),
                        "Exponent",
                        ValueKind.INTEGER,
                        True,
                        minimum=-32768,
                        maximum=32767,
                    ),
                ),
                reference_roles=(role("DimensionFactor", "basis", "DimensionBasis", 1, 1),),
            ),
            ConceptDefinition(
                identity("UnitDefinition"),
                "Unit definition",
                (*named("UnitDefinition"), property_("UnitDefinition", "symbol")),
                (role("UnitDefinition", "dimension", "DimensionFactor", 0, 16),),
                display_property_id=identity("UnitDefinition", "name"),
            ),
            ConceptDefinition(
                identity("Conversion"),
                "Affine conversion",
                (
                    property_("Conversion", "name"),
                    property_("Conversion", "scale", ValueKind.NUMBER),
                    property_("Conversion", "offset", ValueKind.NUMBER),
                    PropertyDefinition(identity("Conversion", "context"), "Context"),
                ),
                reference_roles=(
                    role("Conversion", "source", "UnitDefinition", 1, 1),
                    role("Conversion", "target", "UnitDefinition", 1, 1),
                ),
                display_property_id=identity("Conversion", "name"),
                description="target = source * scale + offset; inverse is derived when requested.",
            ),
            ConceptDefinition(
                identity("UnitSystem"),
                "Unit system",
                named("UnitSystem"),
                (
                    role("UnitSystem", "bases", "DimensionBasis"),
                    role("UnitSystem", "units", "UnitDefinition", 1),
                    role("UnitSystem", "conversions", "Conversion"),
                ),
                display_property_id=identity("UnitSystem", "name"),
            ),
        ),
        BUNDLE,
        "Versioned dimensions, unit definitions and explicit affine conversion contexts.",
    )


class UnitError(ValueError):
    """An explicit, portable domain diagnostic; never a guessed conversion."""

    def __init__(self, code: str, message: str, object_id: str = "") -> None:
        super().__init__(message)
        self.issue = DomainIssue(code, message, object_id, incomplete=True)


@dataclass(frozen=True, slots=True)
class UnitDefinition:
    node_id: str
    reference: UnitReference
    name: str
    symbol: str


@dataclass(frozen=True, slots=True)
class Conversion:
    node_id: str
    source: UnitReference
    target: UnitReference
    scale: int | float
    offset: int | float
    context: str | None = None


@dataclass(frozen=True, slots=True)
class UnitFactor:
    """Derived factor of a declared unit equation, never a second unit definition."""

    measure: QuantityValue
    exponent: Fraction
    interval: bool = False


@dataclass(frozen=True, slots=True)
class UnitProduct:
    node_id: str
    unit: UnitReference
    factors: tuple[UnitFactor, ...]


def _text(node: IntentionalNode, field: str) -> str:
    value = node.property(node.concept_id + ":" + field)
    if not isinstance(value, str) or not value.strip():
        raise UnitError("UNIT_REQUIRED_PROPERTY", f"A unit definition requires {field}", node.id)
    return value


def _target(
    node: IntentionalNode, field: str, nodes: dict[str, IntentionalNode]
) -> IntentionalNode:
    targets = node.reference_ids(node.concept_id + ":" + field)
    if len(targets) != 1 or targets[0] not in nodes:
        raise UnitError("UNIT_REFERENCE", f"A conversion requires one resolved {field}", node.id)
    return nodes[targets[0]]


def _number(node: IntentionalNode, field: str) -> int | float:
    value = node.property(node.concept_id + ":" + field)
    if type(value) not in (int, float):
        raise UnitError("UNIT_COEFFICIENT", f"Conversion {field} must be a real number", node.id)
    assert isinstance(value, (int, float))
    return value


@dataclass(frozen=True, slots=True)
class UnitCatalog:
    """Read-only derived index. Model data remains the sole definition owner."""

    units: tuple[UnitDefinition, ...]
    conversions: tuple[Conversion, ...]
    products: tuple[UnitProduct, ...] = ()

    @classmethod
    def from_models(cls, models: tuple[DomainModel, ...]) -> UnitCatalog:
        selected = tuple(model for model in models if model.schema_id == SCHEMA_ID)
        issues = validate_domain_workspace(DomainWorkspace((units_schema(),), selected))
        if issues:
            issue = issues[0]
            raise UnitError(issue.code, issue.message, issue.object_id)
        nodes = {node.id: node for model in selected for node in model.nodes}
        public: dict[tuple[str, str], str] = {}
        bases: dict[str, str] = {}
        for node in sorted(nodes.values(), key=lambda node: node.id):
            if node.concept_id not in {
                identity("DimensionBasis"),
                identity("UnitDefinition"),
                identity("UnitSystem"),
            }:
                continue
            key = (_text(node, "contract_id"), _text(node, "version"))
            try:
                validate_global_contract_id(key[0])
                validate_contract_version(key[1])
            except ValueError as exc:
                raise UnitError("UNIT_CONTRACT_ID", str(exc), node.id) from exc
            if key in public:
                raise UnitError(
                    "UNIT_DUPLICATE_CONTRACT", f"Duplicate unit contract {key!r}", node.id
                )
            public[key] = node.id
            if node.concept_id == identity("DimensionBasis"):
                if key[0] in bases.values():
                    raise UnitError(
                        "UNIT_BASIS_VERSION",
                        "A dimension basis identity is immutable; "
                        "a changed basis requires a different identity",
                        node.id,
                    )
                bases[node.id] = key[0]
        units: list[UnitDefinition] = []
        for node in sorted(nodes.values(), key=lambda node: node.id):
            if node.concept_id != identity("UnitDefinition"):
                continue
            powers: list[DimensionPower] = []
            for factor_id in node.child_ids(identity("UnitDefinition", "dimension")):
                factor = nodes[factor_id]
                basis = _target(factor, "basis", nodes)
                exponent = factor.property(identity("DimensionFactor", "exponent"))
                if type(exponent) is not int or not exponent:
                    raise UnitError(
                        "UNIT_DIMENSION_EXPONENT", "Dimension exponents must be nonzero", factor.id
                    )
                powers.append(DimensionPower(bases[basis.id], exponent))
            try:
                dimension = Dimension(tuple(sorted(powers, key=lambda power: power.basis_id)))
            except ValueError as exc:
                raise UnitError("UNIT_DIMENSION", str(exc), node.id) from exc
            units.append(
                UnitDefinition(
                    node.id,
                    UnitReference(_text(node, "contract_id"), _text(node, "version"), dimension),
                    _text(node, "name"),
                    _text(node, "symbol"),
                )
            )
        unit_nodes = {unit.node_id: unit.reference for unit in units}
        conversions: list[Conversion] = []
        for node in sorted(nodes.values(), key=lambda node: node.id):
            if node.concept_id != identity("Conversion"):
                continue
            source = unit_nodes[_target(node, "source", nodes).id]
            target = unit_nodes[_target(node, "target", nodes).id]
            if source.dimension != target.dimension:
                raise UnitError(
                    "UNIT_DIMENSION_MISMATCH",
                    "Affine conversion requires identical declared dimensions",
                    node.id,
                )
            scale, offset = _number(node, "scale"), _number(node, "offset")
            if scale == 0:
                raise UnitError(
                    "UNIT_CONVERSION_SCALE", "Conversion scale must be nonzero", node.id
                )
            context = node.property(identity("Conversion", "context"))
            if context is not None and (not isinstance(context, str) or not context.strip()):
                raise UnitError(
                    "UNIT_CONVERSION_CONTEXT", "Context must be an explicit identity", node.id
                )
            assert isinstance(context, str) or context is None
            if context is not None:
                try:
                    validate_global_contract_id(context)
                except ValueError as exc:
                    raise UnitError("UNIT_CONVERSION_CONTEXT", str(exc), node.id) from exc
            conversions.append(Conversion(node.id, source, target, scale, offset, context))
        result = cls(
            tuple(sorted(units, key=lambda unit: (unit.reference.id, unit.reference.version))),
            tuple(conversions),
        )
        result._validate_paths()
        from code_visualizer.extensions.foundations.unit_algebra import extend_unit_catalog

        return extend_unit_catalog(result, models)

    def unit(self, contract_id: str, version: str = "1") -> UnitReference:
        matches = [
            unit.reference
            for unit in self.units
            if (unit.reference.id, unit.reference.version) == (contract_id, version)
        ]
        if len(matches) != 1:
            raise UnitError(
                "UNIT_DEFINITION_MISSING",
                f"Unit {contract_id}@{version} is unavailable",
                contract_id,
            )
        return matches[0]

    def validate_reference(self, reference: UnitReference) -> None:
        actual = self.unit(reference.id, reference.version)
        if actual.dimension != reference.dimension:
            raise UnitError(
                "UNIT_REFERENCE_DIMENSION",
                "Unit identity/version has a different registered dimension",
                reference.id,
            )

    def _validate_paths(self) -> None:
        # Each applicable undirected conversion graph must be a forest. This
        # rejects conflicting and redundant paths, including duplicate edges,
        # before traversal and without relying on floating-point equivalence.
        contexts = {None, *(item.context for item in self.conversions)}
        for context in sorted(contexts, key=lambda item: item or ""):
            parents: dict[UnitReference, UnitReference] = {}

            def root(
                unit: UnitReference, links: dict[UnitReference, UnitReference] = parents
            ) -> UnitReference:
                while unit in links:
                    unit = links[unit]
                return unit

            for edge in self.conversions:
                if edge.context not in (None, context):
                    continue
                source, target = root(edge.source), root(edge.target)
                if source == target:
                    raise UnitError(
                        "UNIT_CONVERSION_AMBIGUOUS",
                        "Conversion paths must be unique; "
                        "cyclic or redundant conversion declarations are ambiguous",
                        edge.node_id,
                    )
                parents[source] = target

    def convert(
        self, quantity: QuantityValue, target: UnitReference, *, context: str | None = None
    ) -> QuantityValue:
        if context is not None:
            try:
                validate_global_contract_id(context)
            except ValueError as exc:
                raise UnitError("UNIT_CONVERSION_CONTEXT", str(exc), target.id) from exc
        self.validate_reference(quantity.unit)
        self.validate_reference(target)
        if quantity.unit.dimension != target.dimension:
            raise UnitError(
                "UNIT_DIMENSION_MISMATCH", "Units have different declared dimensions", target.id
            )
        if quantity.unit == target:
            return quantity
        scale, offset = self._coefficients(quantity.unit, target, context=context)
        return _apply(quantity, target, scale, offset)

    def _coefficients(
        self, source: UnitReference, target: UnitReference, *, context: str | None = None
    ) -> tuple[Fraction, Fraction]:
        pending = [(source, Fraction(1), Fraction(0))]
        visited: set[UnitReference] = set()
        while pending:
            source, accumulated_scale, accumulated_offset = pending.pop()
            if source in visited:
                continue
            visited.add(source)
            if source == target:
                return accumulated_scale, accumulated_offset
            for edge in reversed(self.conversions):
                if edge.context not in (None, context):
                    continue
                scale, offset = Fraction(str(edge.scale)), Fraction(str(edge.offset))
                if edge.source == source:
                    destination = edge.target
                elif edge.target == source:
                    destination, scale, offset = edge.source, 1 / scale, -offset / scale
                else:
                    continue
                pending.append(
                    (destination, accumulated_scale * scale, accumulated_offset * scale + offset)
                )
        raise UnitError(
            "UNIT_CONVERSION_UNAVAILABLE",
            "No declared conversion in the selected "
            "context; dimension equality alone does not define a conversion",
            target.id,
        )


def _apply(
    quantity: QuantityValue, target: UnitReference, scale: Fraction, offset: Fraction
) -> QuantityValue:
    value = quantity.magnitude
    try:
        if isinstance(value, ComplexValue):
            if offset:
                raise UnitError(
                    "UNIT_COMPLEX_OFFSET_UNSUPPORTED",
                    "An offset conversion requires a real magnitude",
                    target.id,
                )
            result: int | float | ComplexValue = ComplexValue(
                float(Fraction(str(value.real)) * scale),
                float(Fraction(str(value.imaginary)) * scale),
            )
        else:
            number = Fraction(str(value)) * scale + offset
            result = (
                number.numerator
                if type(value) is int and number.denominator == 1
                else float(number)
            )
            if isinstance(result, float) and not math.isfinite(result):
                raise OverflowError("Converted magnitude is outside finite real range")
        return QuantityValue(result, target)
    except (ValueError, OverflowError) as exc:
        if isinstance(exc, UnitError):
            raise
        raise UnitError("UNIT_NUMERIC_RANGE", str(exc), target.id) from exc


def validate_units(project: Project, model: DomainModel) -> tuple[DomainIssue, ...]:
    # Include a disposable model supplied by transformation validation, replacing
    # the same identity from the snapshot rather than validating a stale copy.
    models = (
        *(
            item
            for item in project.domain_workspace.models
            if item.schema_id == SCHEMA_ID and item.id != model.id
        ),
        model,
    )
    try:
        UnitCatalog.from_models(models)
    except UnitError as exc:
        return (exc.issue,)
    return ()


def units_bundle() -> DomainExtensionBundle:
    from code_visualizer.extensions.publication import FIRST_PARTY_PUBLICATION
    from code_visualizer.extensions.registry import DomainExtensionBundle

    return DomainExtensionBundle(
        BUNDLE.id,
        BUNDLE.version,
        schemas=(units_schema(),),
        publication=FIRST_PARTY_PUBLICATION,
        validators=(validate_units,),
        notations=(
            NotationDefinition(
                PREFIX + "notation:hierarchy",
                "Units and conversion rules",
                NotationKind.TREE_FORM,
                schema_id=SCHEMA_ID,
            ),
        ),
    )
