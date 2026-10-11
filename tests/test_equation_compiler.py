"""P3 shared relation boundary, independent of any electrical interpretation."""

from dataclasses import replace

import pytest

from code_visualizer.application.domain_commands import PutDomainSchema
from code_visualizer.application.domain_installation import bundle_installation, schema_installation
from code_visualizer.domain.intentional import (
    BundleReference,
    DomainModel,
    DomainWorkspace,
    IntentionalNode,
    PropertyValue,
    RoleBinding,
)
from code_visualizer.domain.intentional_validation import validate_domain_workspace
from code_visualizer.domain.project import Project
from code_visualizer.domain.values import QuantityValue
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.foundations.equation_backend import solve_linear
from code_visualizer.extensions.foundations.equation_compiler import (
    EquationError,
    compile_equations,
)
from code_visualizer.extensions.foundations.equations import BUNDLE, equation_schema
from code_visualizer.extensions.foundations.math import SCHEMA_ID, identity
from code_visualizer.extensions.foundations.unit_algebra_si import (
    algebra_si_catalog,
    algebra_si_model,
)
from code_visualizer.extensions.foundations.units_si import si_model
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.serialization import normalized_project_json


def quantity(value, name="one"):
    namespace = (
        "foundation.units.algebra.si"
        if name in {"kiloohm", "newton_per_meter", "newton_per_millimeter", "volt_per_root_hertz"}
        else "foundation.units.si"
    )
    return QuantityValue(value, algebra_si_catalog().unit(namespace + ":" + name))


class EquationCase:
    def __init__(self):
        self.nodes = []
        self.symbols = []
        self.equations = []
        self.bindings = []
        self.relations = []

    def node(self, key, concept, properties=(), children=(), references=()):
        node = IntentionalNode(
            key,
            identity(concept),
            tuple(PropertyValue(identity(concept, field), value) for field, value in properties),
            tuple(
                RoleBinding(identity(concept, field), tuple(values)) for field, values in children
            ),
            tuple(
                RoleBinding(identity(concept, field), tuple(values)) for field, values in references
            ),
        )
        self.nodes.append(node)
        return key

    def symbol(self, key, scale=None, kind="linear"):
        properties = [("name", key), ("quantity_kind", kind)]
        if scale is not None:
            properties.append(("scale", scale))
        self.symbols.append(self.node(key, "Symbol", properties))
        return key

    def ref(self, key, symbol):
        return self.node(key, "SymbolReference", references=(("symbol", (symbol,)),))

    def value(self, key, value, kind="linear"):
        if isinstance(value, QuantityValue):
            return self.node(key, "QuantityLiteral", (("value", value), ("quantity_kind", kind)))
        return self.node(key, "Literal", (("value", value),))

    def op(self, key, operator, *operands):
        return self.node(
            key, "OperatorApplication", (("operator", operator),), (("operands", operands),)
        )

    def equation(self, key, left, right, scale=None):
        self.equations.append(
            self.node(key, "Equation", (("name", key),), (("left", (left,)), ("right", (right,))))
        )
        self.relations.append(
            self.node(
                key + ":use",
                "RelationUse",
                (("residual_scale", scale or quantity(1)),),
                references=(("equation", (key,)),),
            )
        )

    def bind(self, symbol, value):
        self.bindings.append(
            self.node(
                symbol + ":known",
                "Binding",
                (("value", value),),
                references=(("symbol", (symbol,)),),
            )
        )

    def model(self, unknowns, **policy):
        nodes = list(self.nodes)
        self.node(
            "request",
            "SolveRequest",
            (("name", "Solve"), *policy.items()),
            (("bindings", self.bindings), ("relations", self.relations)),
            (("unknowns", unknowns),),
        )
        self.node(
            "problem",
            "Problem",
            (("name", "Equation problem"),),
            (("symbols", self.symbols), ("equations", self.equations), ("requests", ("request",))),
            (("unit_definitions", (*si_model().roots, *algebra_si_model().roots)),),
        )
        result = DomainModel(
            "math-model", SCHEMA_ID, "2", ("problem",), tuple(self.nodes), "Shared equations"
        )
        self.nodes = nodes
        return result


def equation_project(model):
    closure = builtin_registry().bundle_closure(BUNDLE)
    return Project(
        "equations-project",
        "Equations",
        (),
        domain_workspace=DomainWorkspace(
            tuple(schema for bundle in closure for schema in bundle.schemas),
            (model, *(item for bundle in closure for item in bundle.reference_models)),
            tuple(BundleReference(bundle.id, bundle.version) for bundle in closure),
        ),
    )


def system(model):
    pytest.importorskip("sympy")
    pytest.importorskip("pint")
    project = equation_project(model)
    assert not validate_domain_workspace(project.domain_workspace)
    return compile_equations(
        model, tuple(item for item in project.domain_workspace.models if item.id != model.id)
    )


def solve(model):
    pytest.importorskip("numpy")
    compiled = system(model)
    result = solve_linear(compiled)
    return (
        dict(zip((item.id for item in compiled.variables), result.values, strict=True)),
        compiled,
        result,
    )


def spring_case(length_unit="meter", stiffness_unit="newton_per_meter"):
    case = EquationCase()
    for symbol, scale in (
        ("F", quantity(1, "newton")),
        ("k", quantity(1, stiffness_unit)),
        ("x", quantity(1, length_unit)),
    ):
        case.symbol(symbol, scale)
    case.equation(
        "hooke",
        case.ref("force", "F"),
        case.op("product", "multiply", case.ref("stiffness", "k"), case.ref("displacement", "x")),
        quantity(1, "newton"),
    )
    return case


def test_two_requested_unknowns_share_one_unchanged_relation():
    first = spring_case()
    first.bind("F", quantity(10, "newton"))
    first.bind("k", quantity(200, "newton_per_meter"))
    model = first.model(("x",))
    values, _compiled, residuals = solve(model)
    assert values == pytest.approx({"x": 0.05})
    assert max(map(abs, residuals.normalized_residuals)) < 1e-12
    second = spring_case()
    second.bind("x", quantity(50, "millimeter"))
    second.bind("k", quantity(0.2, "newton_per_millimeter"))
    inverse = second.model(("F",))
    assert model.node("hooke") == inverse.node("hooke")
    assert solve(inverse)[0] == pytest.approx({"F": 10})
    assert project_from_json(normalized_project_json(equation_project(model))) == equation_project(
        model
    )


@pytest.mark.parametrize(
    ("length", "stiffness", "expected"),
    (("meter", "newton_per_meter", 0.05), ("millimeter", "newton_per_millimeter", 50)),
)
def test_scales_and_output_units_do_not_change_physical_relation(length, stiffness, expected):
    case = spring_case(length, stiffness)
    case.bind("F", quantity(10, "newton"))
    case.bind("k", quantity(200, "newton_per_meter"))
    assert solve(case.model(("x",)))[0]["x"] == pytest.approx(expected)


def scalar_system(matrix, rhs, column_scales=None, row_scales=None):
    case = EquationCase()
    count = len(matrix[0])
    column_scales = column_scales or [1] * count
    row_scales = row_scales or [1] * len(matrix)
    for col in range(count):
        case.symbol(f"x{col}", quantity(column_scales[col]))
    for row, (coefficients, value) in enumerate(zip(matrix, rhs, strict=True)):
        terms = [
            case.op(
                f"r{row}c{col}",
                "multiply",
                case.value(f"a{row}:{col}", coefficient),
                case.ref(f"s{row}:{col}", f"x{col}"),
            )
            for col, coefficient in enumerate(coefficients)
        ]
        left = terms[0]
        for index, term in enumerate(terms[1:]):
            left = case.op(f"sum{row}:{index}", "add", left, term)
        case.equation(f"e{row}", left, case.value(f"b{row}", value), quantity(row_scales[row]))
    return case.model(tuple(f"x{col}" for col in range(count)))


@pytest.mark.parametrize(
    ("matrix", "rhs", "code"),
    (
        (((1, 1), (2, 2)), (1, 3), "EQUATION_INCONSISTENT"),
        (((1, 1), (2, 2)), (1, 2), "EQUATION_SINGULAR"),
        (((1, 1),), (1,), "EQUATION_UNDERDETERMINED"),
        (((0,),), (1,), "EQUATION_INCONSISTENT"),
    ),
)
def test_no_arbitrary_answer_for_invalid_linear_system(matrix, rhs, code):
    with pytest.raises(EquationError) as error:
        solve(scalar_system(matrix, rhs))
    assert error.value.code == code


def test_full_rank_overdetermined_system_and_declared_numerical_scaling():
    first = scalar_system(((2, 1), (1, -1), (3, 0)), (5, 1, 6))
    second = scalar_system(
        ((2e9, 1e9), (1e-9, -1e-9), (3, 0)), (5e9, 1e-9, 6), (10, 0.1), (1e9, 1e-9, 1)
    )
    values, _, answer = solve(first)
    rescaled, compiled, second_answer = solve(second)
    assert values == pytest.approx({"x0": 2, "x1": 1})
    assert rescaled == pytest.approx(values)
    assert second_answer.scaled_matrix[0] == pytest.approx((20, 0.1))
    assert compiled.residuals[1].base_scale == 1e-9
    assert answer.rank == second_answer.rank == 2
    assert max(map(abs, second_answer.normalized_residuals)) < 1e-9


def test_ill_conditioned_full_rank_system_is_diagnosed():
    model = scalar_system(((1, 0), (0, 1e-8)), (1, 1e-8))
    request = model.node("request")
    model = replace(
        model,
        nodes=tuple(
            replace(
                node,
                properties=(
                    *request.properties,
                    PropertyValue(identity("SolveRequest", "condition_limit"), 1e6),
                ),
            )
            if node.id == request.id
            else node
            for node in model.nodes
        ),
    )
    with pytest.raises(EquationError) as error:
        solve(model)
    assert error.value.code == "EQUATION_ILL_CONDITIONED"


@pytest.mark.parametrize(
    "failure", ("missing_unit", "unbound", "conflict", "wrong_dimension", "nonlinear", "dae")
)
def test_explicit_solve_contract_rejects_predictable_failures(failure):
    case = spring_case()
    if failure == "missing_unit":
        case.nodes = [
            replace(
                node,
                properties=tuple(
                    prop
                    for prop in node.properties
                    if prop.property_id != identity("Symbol", "scale")
                ),
            )
            if node.id == "x"
            else node
            for node in case.nodes
        ]
    if failure not in ("unbound", "nonlinear"):
        case.bind("F", quantity(10, "newton"))
    case.bind("k", quantity(200, "volt" if failure == "wrong_dimension" else "newton_per_meter"))
    if failure == "conflict":
        case.bind("x", quantity(0.05, "meter"))
    if failure == "nonlinear":
        case.bindings.clear()
        case.nodes = [node for node in case.nodes if node.id != "k:known"]
        case.bind("F", quantity(10, "newton"))
    model = case.model(
        ("x", "k") if failure == "nonlinear" else ("x",),
        problem_class="dae" if failure == "dae" else "linear",
    )
    with pytest.raises(EquationError) as error:
        system(model)
    assert (
        error.value.code
        == {
            "missing_unit": "EQUATION_UNIT_REQUIRED",
            "unbound": "EQUATION_UNBOUND_SYMBOL",
            "conflict": "EQUATION_BINDING_CONFLICT",
            "wrong_dimension": "UNIT_DIMENSION_MISMATCH",
            "nonlinear": "EQUATION_NONLINEAR",
            "dae": "EQUATION_PROBLEM_UNSUPPORTED",
        }[failure]
    )


def test_affine_points_and_intervals_keep_their_different_meanings():
    case = EquationCase()
    case.symbol("T", quantity(1, "degree_celsius"), "point")
    case.symbol("initial", quantity(1, "kelvin"), "point")
    case.symbol("change", quantity(1, "kelvin"), "interval")
    case.bind("initial", quantity(293.15, "kelvin"))
    case.bind("change", quantity(10, "kelvin"))
    case.equation(
        "temperature",
        case.ref("out", "T"),
        case.op("sum", "add", case.ref("in", "initial"), case.ref("delta", "change")),
        quantity(1, "kelvin"),
    )
    assert solve(case.model(("T",)))[0] == pytest.approx({"T": 30})


@pytest.mark.parametrize("kind", ("cyclic_frequency", "angular_frequency", "logarithmic"))
def test_distinct_quantity_kinds_are_not_erased_into_dimensions(kind):
    case = EquationCase()
    case.symbol("x", quantity(1, "hertz"), kind)
    case.equation(
        "relation",
        case.ref("x-ref", "x"),
        case.value("literal", quantity(10, "hertz"), kind),
        quantity(1, "hertz"),
    )
    with pytest.raises(EquationError) as error:
        system(case.model(("x",)))
    assert error.value.code == "UNIT_KIND_UNSUPPORTED"


def test_math_version_installation_and_notations_respect_exact_bundle():
    registry = builtin_registry()
    for version in ("1", "2"):
        commands = bundle_installation(
            DomainWorkspace(), registry, BundleReference("foundation.math", version)
        )
        schemas = [command.schema for command in commands if isinstance(command, PutDomainSchema)]
        assert next(schema for schema in schemas if schema.id == SCHEMA_ID).version == version
        notations = registry.notations_for(SCHEMA_ID, version)
        assert len(notations) == 3
        assert all(("v2" in notation.id) == (version == "2") for notation in notations)
    assert equation_schema().version == "2"
    available = tuple(schema for bundle in registry.bundles() for schema in bundle.schemas)
    with pytest.raises(ValueError, match="explicit available schema version"):
        schema_installation(DomainWorkspace(), available, SCHEMA_ID, registry=registry)
    selected = schema_installation(
        DomainWorkspace(), available, SCHEMA_ID, version="2", registry=registry
    )
    assert next(item for item in selected if item.id == SCHEMA_ID).version == "2"


def test_operator_text_is_data_and_never_an_expression_parser_input(tmp_path):
    destination = tmp_path / "must-not-exist"
    case = EquationCase()
    case.symbol("x", quantity(1))
    text = f"__import__('pathlib').Path({str(destination)!r}).write_text('executed')"
    case.equation("unsafe", case.op("text", text, case.ref("x-ref", "x")), case.value("zero", 0))
    with pytest.raises(EquationError) as error:
        system(case.model(("x",)))
    assert error.value.code == "EQUATION_UNSUPPORTED_OPERATOR"
    assert not destination.exists()
