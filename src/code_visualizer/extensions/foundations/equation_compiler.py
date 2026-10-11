"""Checked scalar relations lowered to a scaled linear system, never Python source.

SymPy objects are private disposable values. Only supported canonical expression
nodes construct them; no author string is parsed or evaluated by a library.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Any

from code_visualizer.domain.intentional import DomainModel, IntentionalNode
from code_visualizer.domain.values import Dimension, QuantityValue, UnitReference
from code_visualizer.extensions.foundations.equations import MAX_EQUATIONS, MAX_UNKNOWNS
from code_visualizer.extensions.foundations.math import identity
from code_visualizer.extensions.foundations.unit_algebra import (
    QuantityKind,
    UnitAlgebra,
    UnitForm,
    dimension_product,
    residual_kind,
    result_kind,
)
from code_visualizer.extensions.foundations.units import UnitCatalog, UnitError


class EquationError(ValueError):
    def __init__(self, code: str, message: str, semantic_id: str = "") -> None:
        self.code, self.semantic_id = code, semantic_id
        super().__init__(message)


def real(value: object, semantic_id: str = "") -> float:
    if type(value) not in (int, float):
        raise EquationError(
            "EQUATION_REAL_REQUIRED", "A finite real scalar is required", semantic_id
        )
    assert isinstance(value, (int, float))
    try:
        number = float(value)
    except OverflowError as exc:
        raise EquationError(
            "EQUATION_NUMERIC_RANGE", "Scalar exceeds numerical range", semantic_id
        ) from exc
    if not math.isfinite(number):
        raise EquationError(
            "EQUATION_NUMERIC_RANGE", "Nonfinite numbers are not supported", semantic_id
        )
    return number


@dataclass(frozen=True, slots=True)
class Variable:
    id: str
    name: str
    scale: QuantityValue
    kind: QuantityKind


@dataclass(frozen=True, slots=True)
class Residual:
    id: str
    equation_id: str
    name: str
    scale: QuantityValue
    base_scale: float
    unit_scale: float
    origins: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LinearSystem:
    request_id: str
    variables: tuple[Variable, ...]
    residuals: tuple[Residual, ...]
    matrix: tuple[tuple[float, ...], ...]
    right: tuple[float, ...]
    rank_tolerance: float
    residual_tolerance: float
    condition_limit: float


@dataclass(frozen=True, slots=True)
class _Coefficient:
    id: str
    nominal: QuantityValue
    kind: QuantityKind
    symbol: Any


@dataclass(frozen=True, slots=True)
class _NonzeroDenominator:
    """Authored domain condition, independent of the simplified linear system.

    The denominator is in the compiler's normalized units. Conditions are kept
    in expression traversal order, so nested divisions retain their own origin
    and are checked before a containing operation can obscure the failure.
    """

    number: Any
    semantic_id: str

    def check(self, substitutions: Mapping[Any, Any]) -> None:
        if self.number.xreplace(substitutions) == 0:
            raise EquationError(
                "EQUATION_DIVISION_BY_ZERO", "The known denominator is zero", self.semantic_id
            )


@dataclass(frozen=True, slots=True)
class LinearFamily:
    """Disposable checked equations with explicitly nominated known coefficients.

    Bindings replace finite quantities, never unknowns, topology or author state.
    Private SymPy expressions are constructed by the ordinary compiler; no source
    parsing, lambdify/eval, persisted callbacks or mutable solver cache is involved.
    Authored domain conditions survive simplification and apply to every binding,
    including coefficients which disappear from the numerical matrix.
    """

    nominal: LinearSystem
    _coefficients: tuple[_Coefficient, ...]
    _matrix: tuple[tuple[Any, ...], ...]
    _right: tuple[Any, ...]
    _catalog: UnitCatalog
    _denominators: tuple[_NonzeroDenominator, ...]

    @property
    def coefficient_ids(self) -> tuple[str, ...]:
        return tuple(item.id for item in self._coefficients)

    def bind(self, values: Mapping[str, QuantityValue]) -> LinearSystem:
        from sympy import Rational  # type: ignore[import-untyped]

        if set(values) != set(self.coefficient_ids):
            raise EquationError(
                "EQUATION_COEFFICIENT_BINDING",
                "Every nominated coefficient requires exactly one explicit binding",
                self.nominal.request_id,
            )
        algebra = UnitAlgebra(self._catalog)
        substitutions = {}
        for item in self._coefficients:
            value = values[item.id]
            if not isinstance(value, QuantityValue):
                raise EquationError(
                    "EQUATION_UNIT_REQUIRED", "A coefficient requires a quantity", item.id
                )
            try:
                converted = algebra.convert(value, item.nominal.unit, kind=item.kind)
                # Use the same exact decimal-to-rational boundary as nominal
                # compilation after the existing quantity adapter normalizes it.
                substitutions[item.symbol] = Rational(str(real(converted.magnitude, item.id)))
            except UnitError as exc:
                raise EquationError(exc.issue.code, exc.issue.message, item.id) from exc

        for condition in self._denominators:
            condition.check(substitutions)

        def number(expression: Any) -> float:
            try:
                return real(float(expression.xreplace(substitutions)), self.nominal.request_id)
            except (TypeError, ValueError, OverflowError, ZeroDivisionError) as exc:
                raise EquationError(
                    "EQUATION_NUMERIC_RANGE",
                    "Bound coefficients do not form a finite real linear system",
                    self.nominal.request_id,
                ) from exc

        return replace(
            self.nominal,
            matrix=tuple(tuple(number(value) for value in row) for row in self._matrix),
            right=tuple(number(value) for value in self._right),
        )


@dataclass(frozen=True, slots=True)
class _Expression:
    number: Any  # Third-party SymPy expression, confined to this derived compiler.
    dimension: Dimension
    factors: tuple[tuple[UnitReference, Fraction], ...]
    kind: QuantityKind
    origins: frozenset[str]


class EquationCompiler:
    def __init__(
        self, model: DomainModel, catalog: UnitCatalog, coefficient_ids: tuple[str, ...] = ()
    ) -> None:
        try:
            import sympy
        except ImportError as exc:
            raise EquationError(
                "SCIENCE_DEPENDENCY_MISSING", "Install the science extra to solve equations"
            ) from exc
        self.sp = sympy
        self.model = model
        self.nodes = {node.id: node for node in model.nodes}
        self.algebra = UnitAlgebra(catalog)
        self.symbols: dict[str, _Expression] = {}
        self.used: set[str] = set()
        self.remaining = 50_000
        if len(coefficient_ids) > MAX_EQUATIONS or len(set(coefficient_ids)) != len(
            coefficient_ids
        ):
            raise EquationError(
                "EQUATION_COEFFICIENT_BINDING",
                "Coefficient identities must be distinct and bounded",
            )
        self.coefficients: dict[str, _Coefficient] = {}
        self.coefficients_used: set[str] = set()
        for index, node_id in enumerate(sorted(coefficient_ids)):
            node = self.node(node_id)
            if node.concept_id != identity("QuantityLiteral"):
                raise EquationError(
                    "EQUATION_COEFFICIENT_BINDING",
                    "Only a known quantity literal can be a trial coefficient",
                    node.id,
                )
            self.coefficients[node.id] = _Coefficient(
                node.id,
                self.quantity(node, "value"),
                self.kind(node),
                self.sp.Symbol(f"cv_coefficient_{index}", real=True),
            )
        self.family_matrix: tuple[tuple[Any, ...], ...] = ()
        self.family_right: tuple[Any, ...] = ()
        self.denominators: list[_NonzeroDenominator] = []
        self.nominal_substitutions = {
            item.symbol: self.sp.Rational(str(real(item.nominal.magnitude, item.id)))
            for item in self.coefficients.values()
        }

    def node(self, node_id: str) -> IntentionalNode:
        if node_id not in self.nodes:
            raise EquationError(
                "EQUATION_REFERENCE", "This solve requires a local mathematical object", node_id
            )
        return self.nodes[node_id]

    def one(self, node: IntentionalNode, field: str, *, child: bool = False) -> IntentionalNode:
        role = node.concept_id + ":" + field
        ids = node.child_ids(role) if child else node.reference_ids(role)
        if len(ids) != 1:
            raise EquationError("EQUATION_INCOMPLETE", f"{field} requires one object", node.id)
        return self.node(ids[0])

    def kind(self, node: IntentionalNode) -> QuantityKind:
        value = node.property(node.concept_id + ":quantity_kind")
        if value is not None and not isinstance(value, str):
            raise EquationError("EQUATION_QUANTITY_KIND", "Quantity kind must be text", node.id)
        try:
            return QuantityKind("linear" if value is None else value)
        except ValueError as exc:
            raise EquationError("EQUATION_QUANTITY_KIND", "Unknown quantity kind", node.id) from exc

    def quantity(
        self, node: IntentionalNode, field: str, *, positive: bool = False
    ) -> QuantityValue:
        value = node.property(node.concept_id + ":" + field)
        if not isinstance(value, QuantityValue):
            raise EquationError(
                "EQUATION_UNIT_REQUIRED", f"{field} needs an explicit quantity and unit", node.id
            )
        magnitude = real(value.magnitude, node.id)
        if positive and magnitude <= 0:
            raise EquationError(
                "EQUATION_SCALE", "Characteristic scales must be strictly positive", node.id
            )
        return value

    def unit_form(self, unit: UnitReference, kind: QuantityKind, node_id: str) -> UnitForm:
        try:
            return self.algebra.form(unit, kind)
        except UnitError as exc:
            raise EquationError(exc.issue.code, exc.issue.message, node_id) from exc

    def value(self, quantity: QuantityValue, kind: QuantityKind, node_id: str) -> _Expression:
        form = self.unit_form(quantity.unit, kind, node_id)
        number = self.sp.Rational(str(real(quantity.magnitude, node_id)))
        number = number * self.sp.Rational(str(form.scale)) + self.sp.Rational(str(form.offset))
        return _Expression(number, form.dimension, form.factors, kind, frozenset((node_id,)))

    def expression(self, node: IntentionalNode, path: tuple[str, ...] = ()) -> _Expression:
        try:
            return self._expression(node, path)
        except UnitError as exc:
            # Recursive expression calls attribute a failure to its innermost
            # authored operation, before a parent can replace that origin.
            raise EquationError(exc.issue.code, exc.issue.message, node.id) from exc

    def _expression(self, node: IntentionalNode, path: tuple[str, ...]) -> _Expression:
        self.remaining -= 1
        if self.remaining < 0 or len(path) > 96 or node.id in path:
            raise EquationError(
                "EQUATION_COMPLEXITY", "Expression exceeds the structural work bound", node.id
            )
        concept = node.concept_id
        if concept == identity("Literal"):
            number = self.sp.Rational(str(real(node.property(concept + ":value"), node.id)))
            return _Expression(number, Dimension(), (), QuantityKind.LINEAR, frozenset((node.id,)))
        if concept == identity("QuantityLiteral"):
            if node.id in self.coefficients:
                item = self.coefficients[node.id]
                form = self.unit_form(item.nominal.unit, item.kind, node.id)
                self.coefficients_used.add(node.id)
                return _Expression(
                    item.symbol * self.sp.Rational(str(form.scale))
                    + self.sp.Rational(str(form.offset)),
                    form.dimension,
                    form.factors,
                    item.kind,
                    frozenset((node.id,)),
                )
            return self.value(self.quantity(node, "value"), self.kind(node), node.id)
        if concept == identity("SymbolReference"):
            symbol = self.one(node, "symbol")
            self.used.add(symbol.id)
            if symbol.id not in self.symbols:
                raise EquationError(
                    "EQUATION_UNBOUND_SYMBOL",
                    "Every used symbol must be explicitly known or unknown",
                    symbol.id,
                )
            value = self.symbols[symbol.id]
            return _Expression(
                value.number, value.dimension, value.factors, value.kind, value.origins | {node.id}
            )
        if concept != identity("OperatorApplication"):
            raise EquationError(
                "EQUATION_UNSUPPORTED_EXPRESSION",
                "The linear adapter supports real scalar algebra only",
                node.id,
            )
        operator = node.property(concept + ":operator")
        arity = {"add": 2, "subtract": 2, "multiply": 2, "divide": 2, "negate": 1}
        if not isinstance(operator, str) or operator not in arity:
            raise EquationError(
                "EQUATION_UNSUPPORTED_OPERATOR",
                "Operator is outside the declared linear adapter",
                node.id,
            )
        ids = node.child_ids(concept + ":operands")
        if len(ids) != arity[operator] or node.reference_ids(concept + ":bound_symbols"):
            raise EquationError(
                "EQUATION_OPERATOR_ARITY", "Invalid operands or bound symbols", node.id
            )
        values = tuple(self.expression(self.node(item), (*path, node.id)) for item in ids)
        left = values[0]
        origins = frozenset((node.id,)).union(*(item.origins for item in values))
        if operator == "negate":
            return _Expression(
                -left.number,
                left.dimension,
                left.factors,
                result_kind(operator, left.kind, left_dimension=left.dimension),
                origins,
            )
        right = values[1]
        kind = result_kind(
            operator,
            left.kind,
            right.kind,
            left_dimension=left.dimension,
            right_dimension=right.dimension,
        )
        if operator in ("add", "subtract"):
            self.compatible(left, right, node.id)
            number = left.number + right.number if operator == "add" else left.number - right.number
            return _Expression(number, left.dimension, left.factors, kind, origins)
        coefficient_symbols = {item.symbol for item in self.coefficients.values()}
        left_unknowns = left.number.free_symbols - coefficient_symbols
        right_unknowns = right.number.free_symbols - coefficient_symbols
        if operator == "multiply" and left_unknowns and right_unknowns:
            raise EquationError(
                "EQUATION_NONLINEAR",
                "Products of requested unknowns require a nonlinear backend",
                node.id,
            )
        if operator == "divide":
            if right_unknowns:
                raise EquationError(
                    "EQUATION_NONLINEAR",
                    "An unknown denominator is outside the linear contract",
                    node.id,
                )
            condition = _NonzeroDenominator(right.number, node.id)
            condition.check(self.nominal_substitutions)
            self.denominators.append(condition)
        power = Fraction(-1 if operator == "divide" else 1)
        dimension = dimension_product(((left.dimension, Fraction(1)), (right.dimension, power)))
        factors = dict(left.factors)
        for atom, exponent in right.factors:
            factors[atom] = factors.get(atom, Fraction()) + exponent * power
        combined = tuple(
            sorted(
                ((atom, exponent) for atom, exponent in factors.items() if exponent),
                key=lambda item: (item[0].id, item[0].version),
            )
        )
        number = left.number / right.number if operator == "divide" else left.number * right.number
        return _Expression(number, dimension, combined, kind, origins)

    @staticmethod
    def compatible(left: _Expression, right: _Expression, node_id: str) -> None:
        if left.dimension != right.dimension:
            raise EquationError(
                "EQUATION_DIMENSION_MISMATCH",
                "Relation operands have incompatible physical dimensions",
                node_id,
            )
        if left.factors != right.factors:
            raise EquationError(
                "UNIT_CONVERSION_UNAVAILABLE",
                "Relation requires a declared unit conversion/product path",
                node_id,
            )

    @classmethod
    def relation_kind(cls, left: _Expression, right: _Expression, node_id: str) -> QuantityKind:
        cls.compatible(left, right, node_id)
        try:
            return residual_kind(left.kind, right.kind)
        except UnitError as exc:
            raise EquationError(exc.issue.code, exc.issue.message, node_id) from exc

    def compile(self, request_id: str | None = None) -> LinearSystem:
        requests = tuple(
            node
            for node in self.model.nodes
            if node.concept_id == identity("SolveRequest")
            and (request_id is None or node.id == request_id)
        )
        if len(requests) != 1:
            raise EquationError(
                "EQUATION_REQUEST_AMBIGUOUS",
                "Select exactly one canonical solve request",
                self.model.id,
            )
        request = requests[0]
        if request.property(request.concept_id + ":problem_class") not in (None, "linear"):
            raise EquationError(
                "EQUATION_PROBLEM_UNSUPPORTED",
                "This backend solves finite scalar linear systems only",
                request.id,
            )
        unknown_ids = request.reference_ids(request.concept_id + ":unknowns")
        if not 1 <= len(unknown_ids) <= MAX_UNKNOWNS or len(set(unknown_ids)) != len(unknown_ids):
            raise EquationError(
                "EQUATION_UNKNOWNS",
                "Select a bounded nonempty set of distinct unknown symbols",
                request.id,
            )
        variables, symbols = [], []
        for index, node_id in enumerate(sorted(unknown_ids)):
            node = self.node(node_id)
            if node.concept_id != identity("Symbol") or node.reference_ids(
                identity("Symbol", "binding")
            ):
                raise EquationError(
                    "EQUATION_BINDING_CONFLICT",
                    "Unknowns require scalar declarations without legacy bindings",
                    node.id,
                )
            scale, kind = self.quantity(node, "scale", positive=True), self.kind(node)
            form = self.unit_form(scale.unit, kind, node.id)
            symbol = self.sp.Symbol(f"cv_unknown_{index}", real=True)
            symbols.append(symbol)
            self.symbols[node.id] = _Expression(
                symbol * self.sp.Rational(str(form.scale)) + self.sp.Rational(str(form.offset)),
                form.dimension,
                form.factors,
                kind,
                frozenset((node.id,)),
            )
            variables.append(
                Variable(
                    node.id, str(node.property(identity("Symbol", "name")) or node.id), scale, kind
                )
            )
        for binding_id in request.child_ids(request.concept_id + ":bindings"):
            binding = self.node(binding_id)
            node = self.one(binding, "symbol")
            if node.id in self.symbols or node.reference_ids(identity("Symbol", "binding")):
                raise EquationError(
                    "EQUATION_BINDING_CONFLICT",
                    "Known and unknown bindings must be unique and explicit",
                    node.id,
                )
            scale, kind = self.quantity(node, "scale", positive=True), self.kind(node)
            value = self.algebra.convert(self.quantity(binding, "value"), scale.unit, kind=kind)
            expression = self.value(value, kind, node.id)
            self.symbols[node.id] = _Expression(
                expression.number,
                expression.dimension,
                expression.factors,
                kind,
                expression.origins | {binding.id},
            )
        relation_ids = request.child_ids(request.concept_id + ":relations")
        if not 1 <= len(relation_ids) <= MAX_EQUATIONS:
            raise EquationError(
                "EQUATION_RELATIONS", "Select a bounded nonempty equation set", request.id
            )
        expressions, residuals = [], []
        seen: set[str] = set()
        for relation_id in sorted(relation_ids):
            use = self.node(relation_id)
            equation = self.one(use, "equation")
            if equation.id in seen:
                raise EquationError(
                    "EQUATION_DUPLICATE_RELATION",
                    "A relation may occur only once in a solve",
                    equation.id,
                )
            seen.add(equation.id)
            left = self.expression(self.one(equation, "left", child=True))
            right = self.expression(self.one(equation, "right", child=True))
            kind = self.relation_kind(left, right, equation.id)
            scale = self.quantity(use, "residual_scale", positive=True)
            form = self.unit_form(scale.unit, kind, use.id)
            self.compatible(
                left, _Expression(0, form.dimension, form.factors, kind, frozenset()), use.id
            )
            origins = tuple(sorted(left.origins | right.origins | {use.id, equation.id}))
            residuals.append(
                Residual(
                    use.id,
                    equation.id,
                    str(equation.property(identity("Equation", "name")) or equation.id),
                    scale,
                    real(scale.magnitude) * form.scale,
                    form.scale,
                    origins,
                )
            )
            expressions.append(left.number - right.number)
        unused = set(self.symbols) - self.used
        if unused:
            raise EquationError(
                "EQUATION_UNUSED_BINDING",
                "A selected symbol does not occur in the selected relations",
                sorted(unused)[0],
            )
        matrix, right = self.sp.linear_eq_to_matrix(expressions, symbols)
        if set(self.coefficients) != self.coefficients_used:
            raise EquationError(
                "EQUATION_UNUSED_COEFFICIENT",
                "A coefficient is outside the selected solve",
                sorted(set(self.coefficients) - self.coefficients_used)[0],
            )
        self.family_matrix = tuple(
            tuple(matrix[row, col] for col in range(len(variables)))
            for row in range(len(residuals))
        )
        self.family_right = tuple(right[row] for row in range(len(residuals)))
        substitutions = self.nominal_substitutions
        rows = tuple(
            tuple(
                real(float(matrix[row, col].xreplace(substitutions)), request.id)
                for col in range(len(variables))
            )
            for row in range(len(residuals))
        )
        rhs = tuple(
            real(float(right[row].xreplace(substitutions)), request.id)
            for row in range(len(residuals))
        )
        policies = []
        for field, default in (
            ("rank_tolerance", 1e-12),
            ("residual_tolerance", 1e-9),
            ("condition_limit", 1e12),
        ):
            raw = request.property(request.concept_id + ":" + field)
            policies.append(real(default if raw is None else raw, request.id))
        if not (0 < policies[0] < 1 and 0 < policies[1] < 1 and policies[2] >= 1):
            raise EquationError(
                "EQUATION_NUMERICAL_POLICY",
                "Tolerances must be between zero and one; condition limit at least one",
                request.id,
            )
        return LinearSystem(request.id, tuple(variables), tuple(residuals), rows, rhs, *policies)


def compile_equations(
    model: DomainModel, dependencies: tuple[DomainModel, ...], request_id: str | None = None
) -> LinearSystem:
    try:
        return EquationCompiler(model, UnitCatalog.from_models(dependencies)).compile(request_id)
    except UnitError as exc:
        raise EquationError(
            exc.issue.code, exc.issue.message, exc.issue.object_id or model.id
        ) from exc


def compile_equation_family(
    model: DomainModel,
    dependencies: tuple[DomainModel, ...],
    coefficient_ids: tuple[str, ...],
    request_id: str | None = None,
) -> LinearFamily:
    """Prepare a linear family once; binding never rebuilds canonical intentions."""
    try:
        catalog = UnitCatalog.from_models(dependencies)
        compiler = EquationCompiler(model, catalog, coefficient_ids)
        nominal = compiler.compile(request_id)
        return LinearFamily(
            nominal,
            tuple(compiler.coefficients.values()),
            compiler.family_matrix,
            compiler.family_right,
            catalog,
            tuple(compiler.denominators),
        )
    except UnitError as exc:
        raise EquationError(
            exc.issue.code, exc.issue.message, exc.issue.object_id or model.id
        ) from exc
