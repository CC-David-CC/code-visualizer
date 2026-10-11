"""One canonical, typed, renderable Python expression tree.

Valid Python is stored exactly once as immutable syntax nodes. Python text is a
derived rendering of that tree. Text that cannot yet be parsed is represented by
``UnparsedPythonExpression`` and remains a legitimate, explicitly incomplete editing
state.

Expression-node identity obeys one strict law: the same ID denotes the same semantic
object. A parse therefore allocates fresh IDs for the complete provisional tree. A
future tree reconciler may retain old IDs only for nodes it can prove correspond.
"""

from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from types import EllipsisType
from uuid import uuid4


class ExpressionContext(StrEnum):
    LOAD = "load"
    STORE = "store"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class ExpressionScalar:
    """Lossless, JSON-safe representation of a Python AST scalar field."""

    kind: str
    value: str


@dataclass(frozen=True, slots=True)
class UnparsedPythonExpression:
    """Authored expression text that is not yet a complete typed Python tree."""

    id: str
    source: str
    reason: str = "unsupported Python expression"


@dataclass(frozen=True, slots=True)
class SymbolReferenceExpression:
    id: str
    name: str
    symbol_id: str | None
    context: ExpressionContext = ExpressionContext.LOAD


@dataclass(frozen=True, slots=True)
class LiteralExpression:
    id: str
    value: ExpressionScalar
    literal_kind: str | None = None


@dataclass(frozen=True, slots=True)
class AttributeExpression:
    id: str
    value: ExpressionNode
    attribute: str
    context: ExpressionContext = ExpressionContext.LOAD


@dataclass(frozen=True, slots=True)
class SubscriptExpression:
    id: str
    value: ExpressionNode
    index: ExpressionNode
    context: ExpressionContext = ExpressionContext.LOAD


@dataclass(frozen=True, slots=True)
class BinaryExpression:
    id: str
    left: ExpressionNode
    operator: str
    right: ExpressionNode


@dataclass(frozen=True, slots=True)
class ExpressionKeyword:
    id: str
    name: str | None
    value: ExpressionNode


@dataclass(frozen=True, slots=True)
class CallExpression:
    id: str
    callee: ExpressionNode
    arguments: tuple[ExpressionNode, ...] = ()
    keywords: tuple[ExpressionKeyword, ...] = ()


@dataclass(frozen=True, slots=True)
class ArgumentListExpression:
    """Typed call arguments without a fabricated callable in canonical state."""

    id: str
    arguments: tuple[ExpressionNode, ...] = ()
    keywords: tuple[ExpressionKeyword, ...] = ()


@dataclass(frozen=True, slots=True)
class AssignmentTargetsExpression:
    """One or more chained assignment targets, in authored assignment order."""

    id: str
    targets: tuple[ExpressionNode, ...]


@dataclass(frozen=True, slots=True)
class ExpressionList:
    items: tuple[ExpressionValue, ...] = ()


@dataclass(frozen=True, slots=True)
class ExpressionField:
    name: str
    value: ExpressionValue


@dataclass(frozen=True, slots=True)
class CompositeExpression:
    """Complete structural carrier for Python AST forms without a bespoke node."""

    id: str
    python_kind: str
    fields: tuple[ExpressionField, ...] = ()


type ExpressionNode = (
    UnparsedPythonExpression
    | SymbolReferenceExpression
    | LiteralExpression
    | AttributeExpression
    | SubscriptExpression
    | BinaryExpression
    | CallExpression
    | ArgumentListExpression
    | AssignmentTargetsExpression
    | CompositeExpression
)
type ExpressionValue = ExpressionNode | ExpressionScalar | ExpressionList
type SymbolResolver = Callable[[str, ExpressionContext], str | None]
type ExpressionMapper = Callable[[ExpressionNode], ExpressionNode]
type PythonScalar = str | bytes | bool | int | float | complex | EllipsisType | None


class ExpressionIdentityError(ValueError):
    """A transformation tried to reuse an ID for a different semantic object."""


_BINARY_OPERATORS: dict[type[ast.operator], str] = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.MatMult: "@",
    ast.Div: "/",
    ast.FloorDiv: "//",
    ast.Mod: "%",
    ast.Pow: "**",
    ast.LShift: "<<",
    ast.RShift: ">>",
    ast.BitOr: "|",
    ast.BitXor: "^",
    ast.BitAnd: "&",
}
_AST_BINARY_OPERATORS = {label: node_type for node_type, label in _BINARY_OPERATORS.items()}
_AUXILIARY_KINDS = frozenset(
    {
        "Load",
        "Store",
        "Del",
        "And",
        "Or",
        "Add",
        "Sub",
        "Mult",
        "MatMult",
        "Div",
        "FloorDiv",
        "Mod",
        "Pow",
        "LShift",
        "RShift",
        "BitOr",
        "BitXor",
        "BitAnd",
        "Invert",
        "Not",
        "UAdd",
        "USub",
        "Eq",
        "NotEq",
        "Lt",
        "LtE",
        "Gt",
        "GtE",
        "Is",
        "IsNot",
        "In",
        "NotIn",
    }
)
_SCALAR_KINDS = frozenset({"none", "ellipsis", "bool", "int", "float", "complex", "str", "bytes"})


def _node_id(parse_identity: str, path: str) -> str:
    """Identify a node only within one parse generation.

    The generation namespace, not the structural path, decides continuity over time.
    A normal edit receives a fresh namespace, so occupying an old path can never grant
    an old identity. The path merely supplies deterministic uniqueness inside that one
    provisional tree.
    """

    digest = hashlib.sha256(path.encode("utf-8")).hexdigest()
    return f"{parse_identity}:node:{digest}"


def _context(value: ast.expr_context) -> ExpressionContext:
    if isinstance(value, ast.Store):
        return ExpressionContext.STORE
    if isinstance(value, ast.Del):
        return ExpressionContext.DELETE
    return ExpressionContext.LOAD


def _ast_context(value: ExpressionContext) -> ast.expr_context:
    if value is ExpressionContext.STORE:
        return ast.Store()
    if value is ExpressionContext.DELETE:
        return ast.Del()
    return ast.Load()


def _scalar_from_python(value: object) -> ExpressionScalar:
    if value is None:
        return ExpressionScalar("none", "")
    if value is Ellipsis:
        return ExpressionScalar("ellipsis", "")
    if isinstance(value, bool):
        return ExpressionScalar("bool", "1" if value else "0")
    if isinstance(value, int):
        return ExpressionScalar("int", str(value))
    if isinstance(value, float):
        return ExpressionScalar("float", value.hex())
    if isinstance(value, complex):
        return ExpressionScalar("complex", f"{value.real.hex()},{value.imag.hex()}")
    if isinstance(value, str):
        return ExpressionScalar("str", value)
    if isinstance(value, bytes):
        return ExpressionScalar("bytes", value.hex())
    raise ValueError(f"unsupported Python AST scalar {type(value).__name__}")


def _scalar_to_python(value: ExpressionScalar) -> PythonScalar:
    if value.kind == "none":
        return None
    if value.kind == "ellipsis":
        return Ellipsis
    if value.kind == "bool":
        if value.value not in {"0", "1"}:
            raise ValueError("Boolean expression scalar must be 0 or 1")
        return value.value == "1"
    if value.kind == "int":
        return int(value.value)
    if value.kind == "float":
        return float.fromhex(value.value)
    if value.kind == "complex":
        real, separator, imaginary = value.value.partition(",")
        if not separator:
            raise ValueError("Complex expression scalar is invalid")
        return complex(float.fromhex(real), float.fromhex(imaginary))
    if value.kind == "str":
        return value.value
    if value.kind == "bytes":
        return bytes.fromhex(value.value)
    raise ValueError(f"unknown expression scalar kind {value.kind!r}")


def _operator(value: ast.operator) -> str:
    return _BINARY_OPERATORS.get(type(value), type(value).__name__)


def _convert_value(
    value: object,
    expression_id: str,
    path: str,
    resolve_symbol: SymbolResolver,
) -> ExpressionValue:
    if isinstance(value, ast.AST):
        return _convert(value, expression_id, path, resolve_symbol)
    if isinstance(value, list):
        return ExpressionList(
            tuple(
                _convert_value(item, expression_id, f"{path}[{index}]", resolve_symbol)
                for index, item in enumerate(value)
            )
        )
    return _scalar_from_python(value)


def _convert(
    value: ast.AST,
    expression_id: str,
    path: str,
    resolve_symbol: SymbolResolver,
) -> ExpressionNode:
    node_id = _node_id(expression_id, path)
    if isinstance(value, ast.Name):
        context = _context(value.ctx)
        return SymbolReferenceExpression(
            node_id,
            value.id,
            resolve_symbol(value.id, context),
            context,
        )
    if isinstance(value, ast.Constant):
        return LiteralExpression(node_id, _scalar_from_python(value.value), value.kind)
    if isinstance(value, ast.Attribute):
        return AttributeExpression(
            node_id,
            _convert(value.value, expression_id, f"{path}.value", resolve_symbol),
            value.attr,
            _context(value.ctx),
        )
    if isinstance(value, ast.Subscript):
        return SubscriptExpression(
            node_id,
            _convert(value.value, expression_id, f"{path}.value", resolve_symbol),
            _convert(value.slice, expression_id, f"{path}.slice", resolve_symbol),
            _context(value.ctx),
        )
    if isinstance(value, ast.BinOp):
        return BinaryExpression(
            node_id,
            _convert(value.left, expression_id, f"{path}.left", resolve_symbol),
            _operator(value.op),
            _convert(value.right, expression_id, f"{path}.right", resolve_symbol),
        )
    if isinstance(value, ast.Call):
        return CallExpression(
            node_id,
            _convert(value.func, expression_id, f"{path}.func", resolve_symbol),
            tuple(
                _convert(item, expression_id, f"{path}.args[{index}]", resolve_symbol)
                for index, item in enumerate(value.args)
            ),
            tuple(
                ExpressionKeyword(
                    _node_id(expression_id, f"{path}.keywords[{index}]"),
                    item.arg,
                    _convert(
                        item.value,
                        expression_id,
                        f"{path}.keywords[{index}].value",
                        resolve_symbol,
                    ),
                )
                for index, item in enumerate(value.keywords)
            ),
        )

    def field_value(field_name: str, raw: object) -> ExpressionValue:
        capture = isinstance(value, (ast.MatchAs, ast.MatchStar)) and field_name == "name"
        capture = capture or (isinstance(value, ast.MatchMapping) and field_name == "rest")
        if capture and isinstance(raw, str):
            return SymbolReferenceExpression(
                _node_id(expression_id, f"{path}.{field_name}"),
                raw,
                resolve_symbol(raw, ExpressionContext.STORE),
                ExpressionContext.STORE,
            )
        return _convert_value(raw, expression_id, f"{path}.{field_name}", resolve_symbol)

    return CompositeExpression(
        node_id,
        type(value).__name__,
        tuple(
            ExpressionField(
                field_name,
                field_value(field_name, raw),
            )
            for field_name, raw in ast.iter_fields(value)
        ),
    )


def expression_tree_from_ast(
    expression_id: str,
    value: ast.AST,
    *,
    identity_namespace: str | None = None,
) -> ExpressionNode:
    """Admit a parsed Python syntax node at an explicit text/import boundary."""
    parse_identity = f"{expression_id}:parse:{identity_namespace or uuid4().hex}"
    return _convert(value, parse_identity, "root", lambda _name, _context: None)


def parse_expression_tree(
    expression_id: str,
    source: str,
    *,
    mode: str = "eval",
    resolve_symbol: SymbolResolver | None = None,
    identity_namespace: str | None = None,
) -> ExpressionNode:
    """Parse authored text once with a fresh provisional identity generation.

    ``identity_namespace`` is reserved for deterministic first construction. Edit
    commands omit it and therefore cannot reuse an earlier tree's IDs.
    """

    resolver = resolve_symbol or (lambda _name, _context: None)
    parse_identity = f"{expression_id}:parse:{identity_namespace or uuid4().hex}"
    try:
        if mode == "target":
            statement = ast.parse(f"{source} = None", mode="exec").body[0]
            if not isinstance(statement, ast.Assign):
                raise ValueError("target did not produce an assignment")
            if len(statement.targets) == 1:
                root: ast.AST = statement.targets[0]
            else:
                return AssignmentTargetsExpression(
                    _node_id(parse_identity, "root"),
                    tuple(
                        _convert(
                            target,
                            parse_identity,
                            f"root.targets[{index}]",
                            resolver,
                        )
                        for index, target in enumerate(statement.targets)
                    ),
                )
        elif mode == "arguments":
            call = ast.parse(f"__code_visualizer_call__({source})", mode="eval").body
            if not isinstance(call, ast.Call):
                raise ValueError("argument list did not produce a call")
            converted = _convert(call, parse_identity, "root", resolver)
            if not isinstance(converted, CallExpression):
                raise ValueError("argument list did not produce a typed call")
            return ArgumentListExpression(
                converted.id,
                converted.arguments,
                converted.keywords,
            )
        elif mode == "names":
            declaration = ast.parse(f"global {source}").body[0]
            if not isinstance(declaration, ast.Global):
                raise ValueError("expected a comma-separated identifier list")
            return ArgumentListExpression(
                _node_id(parse_identity, "root"),
                tuple(
                    SymbolReferenceExpression(
                        _node_id(parse_identity, f"root.names[{index}]"),
                        name,
                        resolver(name, ExpressionContext.LOAD),
                        ExpressionContext.LOAD,
                    )
                    for index, name in enumerate(declaration.names)
                ),
            )
        elif mode == "delete":
            deletion = ast.parse(f"del {source}").body[0]
            if not isinstance(deletion, ast.Delete):
                raise ValueError("expected deletion targets")
            root = (
                deletion.targets[0]
                if len(deletion.targets) == 1
                else ast.Tuple(
                    elts=deletion.targets,
                    ctx=ast.Del(),
                )
            )
        elif mode == "pattern":
            match = ast.parse(f"match None:\n    case {source}:\n        pass").body[0]
            assert isinstance(match, ast.Match)
            if len(match.cases) != 1 or match.cases[0].guard is not None:
                raise ValueError("expected one pattern without a guard")
            root = match.cases[0].pattern
        elif mode == "exec":
            root = ast.parse(source, mode="exec", type_comments=True)
            if root.type_ignores:
                raise ValueError(
                    "Type-ignore directives require source anchors that are not supported; "
                    "the original suite is preserved without changing its typing meaning"
                )
        else:
            root = ast.parse(source, mode="eval").body
        return _convert(root, parse_identity, "root", resolver)
    except (SyntaxError, TypeError, ValueError) as exc:
        detail = exc.msg if isinstance(exc, SyntaxError) else str(exc)
        return UnparsedPythonExpression(
            _node_id(parse_identity, "root"),
            source,
            f"Invalid Python: {detail}",
        )


def _value_to_ast(value: ExpressionValue) -> object:
    if isinstance(value, ExpressionScalar):
        return _scalar_to_python(value)
    if isinstance(value, ExpressionList):
        return [_value_to_ast(item) for item in value.items]
    return _node_to_ast(value)


def _node_to_expr(value: ExpressionNode) -> ast.expr:
    node = _node_to_ast(value)
    if not isinstance(node, ast.expr):
        raise ValueError(f"{expression_node_kind(value)} is not a Python expression")
    return node


def _node_to_ast(value: ExpressionNode) -> ast.AST:
    if isinstance(value, UnparsedPythonExpression):
        raise ValueError("Unparsed Python has no typed AST")
    if isinstance(value, SymbolReferenceExpression):
        return ast.Name(id=value.name, ctx=_ast_context(value.context))
    if isinstance(value, LiteralExpression):
        return ast.Constant(
            value=_scalar_to_python(value.value),
            kind=value.literal_kind,
        )
    if isinstance(value, AttributeExpression):
        return ast.Attribute(
            value=_node_to_expr(value.value),
            attr=value.attribute,
            ctx=_ast_context(value.context),
        )
    if isinstance(value, SubscriptExpression):
        return ast.Subscript(
            value=_node_to_expr(value.value),
            slice=_node_to_expr(value.index),
            ctx=_ast_context(value.context),
        )
    if isinstance(value, BinaryExpression):
        operator_type = _AST_BINARY_OPERATORS.get(value.operator)
        if operator_type is None:
            raise ValueError(f"unknown binary operator {value.operator!r}")
        return ast.BinOp(
            left=_node_to_expr(value.left),
            op=operator_type(),
            right=_node_to_expr(value.right),
        )
    if isinstance(value, CallExpression):
        return ast.Call(
            func=_node_to_expr(value.callee),
            args=[_node_to_expr(item) for item in value.arguments],
            keywords=[
                ast.keyword(arg=item.name, value=_node_to_expr(item.value))
                for item in value.keywords
            ],
        )
    if isinstance(value, (ArgumentListExpression, AssignmentTargetsExpression)):
        raise ValueError(f"{type(value).__name__} requires role-aware rendering")
    node_type = getattr(ast, value.python_kind, None)
    if not isinstance(node_type, type) or not issubclass(node_type, ast.AST):
        raise ValueError(f"unknown Python AST node {value.python_kind!r}")
    fields: dict[str, object] = {}
    for field in value.fields:
        if field.name in fields:
            raise ValueError(f"duplicate Python AST field {field.name!r}")
        fields[field.name] = (
            field.value.name
            if value.python_kind in {"MatchAs", "MatchStar", "MatchMapping"}
            and field.name in {"name", "rest"}
            and isinstance(field.value, SymbolReferenceExpression)
            else _value_to_ast(field.value)
        )
    try:
        return node_type(**fields)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {value.python_kind} expression node: {exc}") from exc


def _unparse(value: ast.AST) -> str:
    ast.fix_missing_locations(value)
    return ast.unparse(value)


def render_expression_tree(value: ExpressionNode) -> str:
    """Derive normalized Python text from the one canonical expression tree."""

    if isinstance(value, UnparsedPythonExpression):
        return value.source
    if isinstance(value, ArgumentListExpression):
        parts = [_unparse(_node_to_ast(item)) for item in value.arguments]
        parts.extend(
            (
                f"{item.name}={_unparse(_node_to_ast(item.value))}"
                if item.name is not None
                else f"**{_unparse(_node_to_ast(item.value))}"
            )
            for item in value.keywords
        )
        return ", ".join(parts)
    if isinstance(value, AssignmentTargetsExpression):
        return " = ".join(_unparse(_node_to_ast(item)) for item in value.targets)
    return _unparse(_node_to_ast(value))


def _value_children(name: str, value: ExpressionValue) -> list[tuple[str, ExpressionNode]]:
    if isinstance(value, ExpressionScalar):
        return []
    if isinstance(value, ExpressionList):
        result: list[tuple[str, ExpressionNode]] = []
        for index, item in enumerate(value.items):
            result.extend(_value_children(f"{name}[{index}]", item))
        return result
    if isinstance(value, CompositeExpression) and value.python_kind in _AUXILIARY_KINDS:
        return []
    return [(name, value)]


def expression_children(value: ExpressionNode) -> tuple[tuple[str, ExpressionNode], ...]:
    if isinstance(value, AttributeExpression):
        return (("value", value.value),)
    if isinstance(value, SubscriptExpression):
        return (("value", value.value), ("index", value.index))
    if isinstance(value, BinaryExpression):
        return (("left", value.left), ("right", value.right))
    if isinstance(value, (CallExpression, ArgumentListExpression)):
        prefix = (("callee", value.callee),) if isinstance(value, CallExpression) else ()
        return (
            *prefix,
            *((f"argument[{index}]", item) for index, item in enumerate(value.arguments)),
            *(
                (item.name or f"keyword[{index}]", item.value)
                for index, item in enumerate(value.keywords)
            ),
        )
    if isinstance(value, AssignmentTargetsExpression):
        return tuple((f"target[{index}]", item) for index, item in enumerate(value.targets))
    if isinstance(value, CompositeExpression):
        result: list[tuple[str, ExpressionNode]] = []
        for field in value.fields:
            result.extend(_value_children(field.name, field.value))
        return tuple(result)
    return ()


def expression_identity_ids(value: ExpressionNode) -> tuple[str, ...]:
    """Return every identity owned by an expression tree, including keywords."""

    result = [value.id]
    if isinstance(value, (CallExpression, ArgumentListExpression)):
        result.extend(item.id for item in value.keywords)
    for _field, child in expression_children(value):
        result.extend(expression_identity_ids(child))
    return tuple(result)


def expression_node_kind(value: ExpressionNode) -> str:
    if isinstance(value, CompositeExpression):
        return value.python_kind
    if isinstance(value, ArgumentListExpression):
        return "arguments"
    if isinstance(value, AssignmentTargetsExpression):
        return "assignment_targets"
    return type(value).__name__.removesuffix("Expression")


def expression_node_label(value: ExpressionNode) -> str:
    if isinstance(value, UnparsedPythonExpression):
        return value.source
    if isinstance(value, SymbolReferenceExpression):
        return value.name
    if isinstance(value, AttributeExpression):
        return value.attribute
    if isinstance(value, SubscriptExpression):
        return "subscript"
    if isinstance(value, BinaryExpression):
        return value.operator
    if isinstance(value, CallExpression):
        return "call"
    if isinstance(value, ArgumentListExpression):
        return "arguments"
    if isinstance(value, AssignmentTargetsExpression):
        return "chained targets"
    try:
        rendered = render_expression_tree(value)
    except ValueError:
        rendered = expression_node_kind(value)
    return " ".join(rendered.split())[:240] or expression_node_kind(value)


def _scalar_to_data(value: ExpressionScalar) -> dict[str, object]:
    return {"kind": value.kind, "value": value.value}


def _scalar_from_data(value: object) -> ExpressionScalar:
    data = _node_mapping(value)
    kind = _required_string(data, "kind")
    raw = data.get("value")
    if kind not in _SCALAR_KINDS or not isinstance(raw, str):
        raise ValueError("expression scalar is invalid")
    result = ExpressionScalar(kind, raw)
    _scalar_to_python(result)
    return result


def _value_to_data(value: ExpressionValue) -> dict[str, object]:
    if isinstance(value, ExpressionScalar):
        return {"value_kind": "scalar", "value": _scalar_to_data(value)}
    if isinstance(value, ExpressionList):
        return {
            "items": [_value_to_data(item) for item in value.items],
            "value_kind": "list",
        }
    return {"value_kind": "node", "value": expression_node_to_data(value)}


def expression_node_to_data(value: ExpressionNode) -> dict[str, object]:
    if isinstance(value, UnparsedPythonExpression):
        return {
            "id": value.id,
            "kind": "unparsed",
            "reason": value.reason,
            "source": value.source,
        }
    if isinstance(value, SymbolReferenceExpression):
        return {
            "context": value.context.value,
            "id": value.id,
            "kind": "symbol",
            "name": value.name,
            "symbol_id": value.symbol_id,
        }
    if isinstance(value, LiteralExpression):
        return {
            "id": value.id,
            "kind": "literal",
            "literal_kind": value.literal_kind,
            "value": _scalar_to_data(value.value),
        }
    if isinstance(value, AttributeExpression):
        return {
            "attribute": value.attribute,
            "context": value.context.value,
            "id": value.id,
            "kind": "attribute",
            "value": expression_node_to_data(value.value),
        }
    if isinstance(value, SubscriptExpression):
        return {
            "context": value.context.value,
            "id": value.id,
            "index": expression_node_to_data(value.index),
            "kind": "subscript",
            "value": expression_node_to_data(value.value),
        }
    if isinstance(value, BinaryExpression):
        return {
            "id": value.id,
            "kind": "binary",
            "left": expression_node_to_data(value.left),
            "operator": value.operator,
            "right": expression_node_to_data(value.right),
        }
    if isinstance(value, (CallExpression, ArgumentListExpression)):
        result: dict[str, object] = {
            "arguments": [expression_node_to_data(item) for item in value.arguments],
            "id": value.id,
            "keywords": [
                {
                    "id": item.id,
                    "name": item.name,
                    "value": expression_node_to_data(item.value),
                }
                for item in value.keywords
            ],
            "kind": "call" if isinstance(value, CallExpression) else "arguments",
        }
        if isinstance(value, CallExpression):
            result["callee"] = expression_node_to_data(value.callee)
        return result
    if isinstance(value, AssignmentTargetsExpression):
        return {
            "id": value.id,
            "kind": "assignment_targets",
            "targets": [expression_node_to_data(item) for item in value.targets],
        }
    return {
        "fields": [
            {"name": item.name, "value": _value_to_data(item.value)} for item in value.fields
        ],
        "id": value.id,
        "kind": "composite",
        "python_kind": value.python_kind,
    }


def _required_string(data: Mapping[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"expression node {key} must be non-empty text")
    return value


def _node_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("expression node must be an object")
    return value


def _node_array(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"expression node {field} must be an array")
    return value


def _decoded_context(data: Mapping[str, object]) -> ExpressionContext:
    try:
        return ExpressionContext(_required_string(data, "context"))
    except ValueError as exc:
        raise ValueError("expression node context is invalid") from exc


def _value_from_data(value: object) -> ExpressionValue:
    data = _node_mapping(value)
    kind = _required_string(data, "value_kind")
    if kind == "scalar":
        return _scalar_from_data(data.get("value"))
    if kind == "list":
        return ExpressionList(
            tuple(_value_from_data(item) for item in _node_array(data.get("items"), "items"))
        )
    if kind == "node":
        return expression_node_from_data(data.get("value"))
    raise ValueError(f"unknown expression value kind {kind!r}")


def _keywords_from_data(data: Mapping[str, object]) -> tuple[ExpressionKeyword, ...]:
    keywords: list[ExpressionKeyword] = []
    for raw in _node_array(data.get("keywords", []), "keywords"):
        item = _node_mapping(raw)
        name = item.get("name")
        if name is not None and not isinstance(name, str):
            raise ValueError("expression keyword name must be text or null")
        keywords.append(
            ExpressionKeyword(
                _required_string(item, "id"),
                name,
                expression_node_from_data(item.get("value")),
            )
        )
    return tuple(keywords)


def expression_node_from_data(value: object) -> ExpressionNode:
    data = _node_mapping(value)
    kind = _required_string(data, "kind")
    node_id = _required_string(data, "id")
    if kind == "unparsed":
        source = data.get("source", "")
        reason = data.get("reason", "unsupported Python expression")
        if not isinstance(source, str) or not isinstance(reason, str):
            raise ValueError("unparsed expression source and reason must be text")
        return UnparsedPythonExpression(node_id, source, reason)
    if kind == "symbol":
        symbol_id = data.get("symbol_id")
        if symbol_id is not None and not isinstance(symbol_id, str):
            raise ValueError("expression node symbol_id must be text or null")
        return SymbolReferenceExpression(
            node_id,
            _required_string(data, "name"),
            symbol_id,
            _decoded_context(data),
        )
    if kind == "literal":
        literal_kind = data.get("literal_kind")
        if literal_kind is not None and not isinstance(literal_kind, str):
            raise ValueError("literal_kind must be text or null")
        return LiteralExpression(node_id, _scalar_from_data(data.get("value")), literal_kind)
    if kind == "attribute":
        return AttributeExpression(
            node_id,
            expression_node_from_data(data.get("value")),
            _required_string(data, "attribute"),
            _decoded_context(data),
        )
    if kind == "subscript":
        return SubscriptExpression(
            node_id,
            expression_node_from_data(data.get("value")),
            expression_node_from_data(data.get("index")),
            _decoded_context(data),
        )
    if kind == "binary":
        return BinaryExpression(
            node_id,
            expression_node_from_data(data.get("left")),
            _required_string(data, "operator"),
            expression_node_from_data(data.get("right")),
        )
    if kind in {"call", "arguments"}:
        arguments = tuple(
            expression_node_from_data(item)
            for item in _node_array(data.get("arguments", []), "arguments")
        )
        keywords = _keywords_from_data(data)
        if kind == "arguments":
            return ArgumentListExpression(node_id, arguments, keywords)
        return CallExpression(
            node_id,
            expression_node_from_data(data.get("callee")),
            arguments,
            keywords,
        )
    if kind == "assignment_targets":
        targets = tuple(
            expression_node_from_data(item)
            for item in _node_array(data.get("targets", []), "targets")
        )
        if len(targets) < 2:
            raise ValueError("assignment_targets must contain at least two targets")
        return AssignmentTargetsExpression(node_id, targets)
    if kind == "composite":
        fields: list[ExpressionField] = []
        names: set[str] = set()
        for raw in _node_array(data.get("fields", []), "fields"):
            item = _node_mapping(raw)
            name = _required_string(item, "name")
            if name in names:
                raise ValueError(f"duplicate expression field {name!r}")
            names.add(name)
            fields.append(
                ExpressionField(
                    name,
                    _value_from_data(item.get("value")),
                )
            )
        result = CompositeExpression(
            node_id,
            _required_string(data, "python_kind"),
            tuple(fields),
        )
        _node_to_ast(result)
        return result
    raise ValueError(f"unknown expression node kind {kind!r}")


def _map_value(value: ExpressionValue, mapper: ExpressionMapper) -> ExpressionValue:
    if isinstance(value, ExpressionScalar):
        return value
    if isinstance(value, ExpressionList):
        return replace(value, items=tuple(_map_value(item, mapper) for item in value.items))
    return map_expression_tree(value, mapper)


def _identity_compatible(before: ExpressionNode, after: ExpressionNode) -> bool:
    """Return whether a mapper may truthfully retain ``before.id``.

    Text reparsing never reaches this function: it allocates an entirely fresh tree.
    This guard protects the smaller set of deliberate transformations such as stable
    symbol rename and rebinding. Anything the guard cannot recognize as the same node
    occurrence must use a fresh ID.
    """

    if type(before) is not type(after):
        return False
    if isinstance(before, UnparsedPythonExpression):
        assert isinstance(after, UnparsedPythonExpression)
        return before.source == after.source and before.reason == after.reason
    if isinstance(before, SymbolReferenceExpression):
        assert isinstance(after, SymbolReferenceExpression)
        if before.context is not after.context:
            return False
        if before.name == after.name:
            return True
        return before.symbol_id is not None and before.symbol_id == after.symbol_id
    if isinstance(before, AttributeExpression):
        assert isinstance(after, AttributeExpression)
        return before.context is after.context
    if isinstance(before, SubscriptExpression):
        assert isinstance(after, SubscriptExpression)
        return before.context is after.context
    if isinstance(before, BinaryExpression):
        assert isinstance(after, BinaryExpression)
        return before.operator == after.operator
    if isinstance(before, CompositeExpression):
        assert isinstance(after, CompositeExpression)
        return before.python_kind == after.python_kind
    return True


def _require_truthful_mapped_identity(
    before: ExpressionNode,
    after: ExpressionNode,
) -> ExpressionNode:
    if before.id == after.id and not _identity_compatible(before, after):
        raise ExpressionIdentityError(
            f"Expression node {before.id!r} cannot retain its ID across "
            f"{expression_node_kind(before)!r} to {expression_node_kind(after)!r} "
            "semantic replacement"
        )
    return after


def map_expression_tree(value: ExpressionNode, mapper: ExpressionMapper) -> ExpressionNode:
    """Map a tree while rejecting any falsely retained node identity."""

    if isinstance(value, AttributeExpression):
        value = replace(value, value=map_expression_tree(value.value, mapper))
    elif isinstance(value, SubscriptExpression):
        value = replace(
            value,
            value=map_expression_tree(value.value, mapper),
            index=map_expression_tree(value.index, mapper),
        )
    elif isinstance(value, BinaryExpression):
        value = replace(
            value,
            left=map_expression_tree(value.left, mapper),
            right=map_expression_tree(value.right, mapper),
        )
    elif isinstance(value, (CallExpression, ArgumentListExpression)):
        arguments = tuple(map_expression_tree(item, mapper) for item in value.arguments)
        keywords = tuple(
            replace(item, value=map_expression_tree(item.value, mapper)) for item in value.keywords
        )
        if isinstance(value, CallExpression):
            value = replace(
                value,
                callee=map_expression_tree(value.callee, mapper),
                arguments=arguments,
                keywords=keywords,
            )
        else:
            value = replace(value, arguments=arguments, keywords=keywords)
    elif isinstance(value, AssignmentTargetsExpression):
        value = replace(
            value,
            targets=tuple(map_expression_tree(item, mapper) for item in value.targets),
        )
    elif isinstance(value, CompositeExpression):
        value = replace(
            value,
            fields=tuple(
                replace(item, value=_map_value(item.value, mapper)) for item in value.fields
            ),
        )
    return _require_truthful_mapped_identity(value, mapper(value))


def _identity_free_data(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _identity_free_data(item) for key, item in value.items() if key != "id"}
    if isinstance(value, list):
        return [_identity_free_data(item) for item in value]
    return value


def _semantic_fingerprint(value: ExpressionNode) -> str:
    return json.dumps(
        _identity_free_data(expression_node_to_data(value)),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _shallow_value_identity(value: ExpressionValue) -> tuple[object, ...]:
    if isinstance(value, ExpressionScalar):
        return ("scalar", value.kind, value.value)
    if isinstance(value, ExpressionList):
        return (
            "list",
            tuple(_shallow_value_identity(item) for item in value.items),
        )
    if isinstance(value, CompositeExpression) and value.python_kind in _AUXILIARY_KINDS:
        return (
            "auxiliary",
            value.python_kind,
            tuple((field.name, _shallow_value_identity(field.value)) for field in value.fields),
        )
    return ("child", expression_node_kind(value))


def _shallow_identity(value: ExpressionNode) -> tuple[object, ...]:
    """Describe only the intrinsic semantics of one expression occurrence."""

    if isinstance(value, UnparsedPythonExpression):
        return (type(value), value.source, value.reason)
    if isinstance(value, SymbolReferenceExpression):
        return (type(value), value.name, value.symbol_id, value.context)
    if isinstance(value, LiteralExpression):
        return (type(value), value.value, value.literal_kind)
    if isinstance(value, AttributeExpression):
        return (type(value), value.attribute, value.context)
    if isinstance(value, SubscriptExpression):
        return (type(value), value.context)
    if isinstance(value, BinaryExpression):
        return (type(value), value.operator)
    if isinstance(value, CompositeExpression):
        fields = tuple((field.name, _shallow_value_identity(field.value)) for field in value.fields)
        return (type(value), value.python_kind, fields)
    return (type(value),)


def _walk_expression(value: ExpressionNode) -> tuple[ExpressionNode, ...]:
    result = [value]
    for _field, child in expression_children(value):
        result.extend(_walk_expression(child))
    return tuple(result)


def reconcile_expression_trees(
    previous: ExpressionNode,
    provisional: ExpressionNode,
) -> ExpressionNode:
    """Conservatively transfer identities from an old tree to a fresh parse.

    Exact subtrees are matched only when unique across both trees. Once such an
    anchor is proven, its ordered descendants are proven too. For a changed whole
    expression, the root and fixed named child roles may persist only when their
    intrinsic node semantics agree. Ambiguous list-item correspondence remains fresh.
    """

    old_nodes = _walk_expression(previous)
    new_nodes = _walk_expression(provisional)
    old_by_fingerprint: dict[str, list[ExpressionNode]] = {}
    new_by_fingerprint: dict[str, list[ExpressionNode]] = {}
    for node in old_nodes:
        old_by_fingerprint.setdefault(_semantic_fingerprint(node), []).append(node)
    for node in new_nodes:
        new_by_fingerprint.setdefault(_semantic_fingerprint(node), []).append(node)

    node_ids: dict[str, str] = {}
    keyword_ids: dict[str, str] = {}
    used_old: set[str] = set()
    used_new: set[str] = set()

    def pair_exact(old: ExpressionNode, new: ExpressionNode) -> bool:
        if old.id in used_old or new.id in used_new:
            return old.id in used_old and node_ids.get(new.id) == old.id
        if _semantic_fingerprint(old) != _semantic_fingerprint(new):
            return False
        node_ids[new.id] = old.id
        used_old.add(old.id)
        used_new.add(new.id)
        old_children = expression_children(old)
        new_children = expression_children(new)
        if tuple(field for field, _child in old_children) != tuple(
            field for field, _child in new_children
        ):
            raise ExpressionIdentityError("Equal expression fingerprints disagree structurally")
        for (_old_field, old_child), (_new_field, new_child) in zip(
            old_children,
            new_children,
            strict=True,
        ):
            if not pair_exact(old_child, new_child):
                raise ExpressionIdentityError("Equal expression subtree could not be reconciled")
        if isinstance(old, (CallExpression, ArgumentListExpression)) and isinstance(
            new, (CallExpression, ArgumentListExpression)
        ):
            for old_keyword, new_keyword in zip(old.keywords, new.keywords, strict=True):
                keyword_ids[new_keyword.id] = old_keyword.id
        return True

    exact_candidates: list[tuple[int, ExpressionNode, ExpressionNode]] = []
    for fingerprint, old_matches in old_by_fingerprint.items():
        new_matches = new_by_fingerprint.get(fingerprint, ())
        if len(old_matches) == len(new_matches) == 1:
            old = old_matches[0]
            new = new_matches[0]
            exact_candidates.append((len(_walk_expression(old)), old, new))
    for _size, old, new in sorted(exact_candidates, key=lambda item: item[0], reverse=True):
        pair_exact(old, new)

    def pair_changed(old: ExpressionNode, new: ExpressionNode) -> None:
        if old.id in used_old or new.id in used_new:
            return
        if _shallow_identity(old) != _shallow_identity(new):
            return
        node_ids[new.id] = old.id
        used_old.add(old.id)
        used_new.add(new.id)
        old_fields: dict[str, list[ExpressionNode]] = {}
        new_fields: dict[str, list[ExpressionNode]] = {}
        for field, child in expression_children(old):
            old_fields.setdefault(field, []).append(child)
        for field, child in expression_children(new):
            new_fields.setdefault(field, []).append(child)
        for field in old_fields.keys() & new_fields.keys():
            if "[" in field or len(old_fields[field]) != 1 or len(new_fields[field]) != 1:
                continue
            pair_changed(old_fields[field][0], new_fields[field][0])
        if isinstance(old, (CallExpression, ArgumentListExpression)) and isinstance(
            new, (CallExpression, ArgumentListExpression)
        ):
            old_keywords: dict[str, list[ExpressionKeyword]] = {}
            new_keywords: dict[str, list[ExpressionKeyword]] = {}
            for item in old.keywords:
                if item.name is not None:
                    old_keywords.setdefault(item.name, []).append(item)
            for item in new.keywords:
                if item.name is not None:
                    new_keywords.setdefault(item.name, []).append(item)
            for name in old_keywords.keys() & new_keywords.keys():
                if len(old_keywords[name]) == len(new_keywords[name]) == 1:
                    keyword_ids[new_keywords[name][0].id] = old_keywords[name][0].id

    if previous.id not in used_old and provisional.id not in used_new:
        pair_changed(previous, provisional)

    def apply_identity(node: ExpressionNode) -> ExpressionNode:
        replacement_id = node_ids.get(node.id, node.id)
        if isinstance(node, (CallExpression, ArgumentListExpression)):
            return replace(
                node,
                id=replacement_id,
                keywords=tuple(
                    replace(item, id=keyword_ids.get(item.id, item.id)) for item in node.keywords
                ),
            )
        return replace(node, id=replacement_id)

    return map_expression_tree(provisional, apply_identity)
