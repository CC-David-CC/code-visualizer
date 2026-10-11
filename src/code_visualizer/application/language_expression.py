"""Checked, readable expressions over the existing authored query values."""

from __future__ import annotations

import ast
import keyword
import re
from dataclasses import dataclass, fields, is_dataclass
from typing import cast
from uuid import uuid4

from code_visualizer.domain import language as l
from code_visualizer.domain.intentional import DomainSchema
from code_visualizer.domain.language_validation import LanguageTypeChecker, QueryType


class QueryExpressionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class QueryExpressionBinding:
    id: str
    name: str
    concept_ids: tuple[str, ...] = ()
    value_type: QueryType | None = None

    @property
    def shape(self) -> QueryType:
        return self.value_type or QueryType("node", self.concept_ids)


type _Environment = dict[str, QueryExpressionBinding]


_BINARY = {
    ast.Eq: l.QueryBinaryOperator.EQUAL,
    ast.NotEq: l.QueryBinaryOperator.NOT_EQUAL,
    ast.Lt: l.QueryBinaryOperator.LESS,
    ast.LtE: l.QueryBinaryOperator.LESS_EQUAL,
    ast.Gt: l.QueryBinaryOperator.GREATER,
    ast.GtE: l.QueryBinaryOperator.GREATER_EQUAL,
    ast.And: l.QueryBinaryOperator.AND,
    ast.Or: l.QueryBinaryOperator.OR,
    ast.In: l.QueryBinaryOperator.IN,
    ast.Add: l.QueryBinaryOperator.ADD,
}
_OPERATOR_TEXT = {
    l.QueryBinaryOperator.EQUAL: "==",
    l.QueryBinaryOperator.NOT_EQUAL: "!=",
    l.QueryBinaryOperator.LESS: "<",
    l.QueryBinaryOperator.LESS_EQUAL: "<=",
    l.QueryBinaryOperator.GREATER: ">",
    l.QueryBinaryOperator.GREATER_EQUAL: ">=",
    l.QueryBinaryOperator.AND: "and",
    l.QueryBinaryOperator.OR: "or",
    l.QueryBinaryOperator.IN: "in",
    l.QueryBinaryOperator.ADD: "+",
}
_COLLECTIONS: dict[
    str, type[l.QueryMap] | type[l.QueryFilter] | type[l.QueryAll] | type[l.QueryUnique]
] = {
    "map": l.QueryMap,
    "where": l.QueryFilter,
    "every": l.QueryAll,
    "unique": l.QueryUnique,
}


def _identity(kind: type[object], previous: object) -> str:
    return str(getattr(previous, "id", None)) if type(previous) is kind else f"query:{uuid4().hex}"


def _old(previous: object, name: str) -> object:
    return getattr(previous, name, None)


def _environment(bindings: tuple[QueryExpressionBinding, ...]) -> _Environment:
    if len({item.id for item in bindings}) != len(bindings) or len(
        {item.name for item in bindings}
    ) != len(bindings):
        raise QueryExpressionError("Query bindings must have unique identities and names")
    if any(not item.id or not item.name for item in bindings):
        raise QueryExpressionError("Query bindings need nonempty identities and names")
    return {item.name: item for item in bindings}


def infer_query_type(
    query: l.Query, schema: DomainSchema, bindings: tuple[QueryExpressionBinding, ...] = ()
) -> QueryType:
    checker = LanguageTypeChecker(schema)
    return checker.query(query, {item.id: item.shape for item in bindings})


def infer_query_concepts(
    query: l.Query, schema: DomainSchema, bindings: tuple[QueryExpressionBinding, ...] = ()
) -> tuple[str, ...]:
    shape = infer_query_type(query, schema, bindings)
    while shape.kind == "sequence" and shape.element is not None:
        shape = shape.element
    return shape.concept_ids


def _literal_text(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    raise QueryExpressionError("Expected a quoted concept, member, or binding name")


def _call_arguments(
    node: ast.Call, count: int, *, keywords: tuple[str, ...] = ()
) -> dict[str, ast.AST]:
    if len(node.args) != count or any(isinstance(item, ast.Starred) for item in node.args):
        raise QueryExpressionError(f"This query constructor requires {count} positional arguments")
    options: dict[str, ast.AST] = {}
    for item in node.keywords:
        if item.arg is None or item.arg not in keywords or item.arg in options:
            raise QueryExpressionError("Unknown, unpacked, or repeated query option")
        options[item.arg] = item.value
    return options


class _Parser:
    def __init__(self, schema: DomainSchema):
        self.schema = schema

    def shape(self, query: l.Query, environment: _Environment) -> QueryType:
        return infer_query_type(query, self.schema, tuple(environment.values()))

    def member(
        self, source: l.Query, name: str, environment: _Environment, kind: str | None = None
    ) -> tuple[str, str]:
        shape = self.shape(source, environment)
        if shape.kind != "node":
            raise QueryExpressionError(
                "Property and role access requires one domain object; use first() for a role"
            )
        members = {
            (member.id, category): member
            for concept_id in shape.concept_ids
            if (concept := self.schema.concept(concept_id)) is not None
            for category, values in (
                ("property", concept.properties),
                ("role", (*concept.containment_roles, *concept.reference_roles)),
            )
            if kind is None or category == kind
            for member in values
        }
        exact = tuple(key for key in members if key[0] == name)
        matches = exact or tuple(key for key, value in members.items() if value.name == name)
        if len(matches) != 1:
            raise QueryExpressionError(
                f"Member {name!r} is unavailable or ambiguous; use prop()/role() and its ID"
            )
        return matches[0]

    def query(self, node: ast.AST, environment: _Environment, previous: object = None) -> l.Query:
        if isinstance(node, ast.Constant) and type(node.value) in {
            str,
            int,
            float,
            bool,
            type(None),
        }:
            return l.QueryLiteral(
                _identity(l.QueryLiteral, previous),
                cast(str | int | float | bool | None, node.value),
            )
        if isinstance(node, ast.Name):
            binding = environment.get(node.id)
            if binding is None:
                raise QueryExpressionError(f"Unknown query binding {node.id!r}")
            return l.QueryVariable(_identity(l.QueryVariable, previous), binding.id)
        if isinstance(node, ast.UnaryOp):
            if (
                isinstance(node.op, ast.USub)
                and isinstance(node.operand, ast.Constant)
                and type(node.operand.value) in {int, float}
            ):
                return l.QueryLiteral(
                    _identity(l.QueryLiteral, previous), -cast(int | float, node.operand.value)
                )
            if isinstance(node.op, ast.Not):
                return l.QueryUnary(
                    _identity(l.QueryUnary, previous),
                    l.QueryUnaryOperator.NOT,
                    self.query(node.operand, environment, _old(previous, "operand")),
                )
            raise QueryExpressionError("Only not and signed numeric literals are supported")
        if isinstance(node, (ast.Tuple, ast.List)):
            old_items = previous.items if isinstance(previous, l.QueryTuple) else ()
            return l.QueryTuple(
                _identity(l.QueryTuple, previous),
                tuple(
                    self.query(
                        item, environment, old_items[index] if index < len(old_items) else None
                    )
                    for index, item in enumerate(node.elts)
                ),
            )
        if isinstance(node, ast.Attribute):
            source = self.query(node.value, environment, _old(previous, "source"))
            member_id, kind = self.member(source, node.attr, environment)
            return (
                l.QueryProperty(_identity(l.QueryProperty, previous), source, member_id)
                if kind == "property"
                else l.QueryRole(_identity(l.QueryRole, previous), source, member_id)
            )
        if isinstance(node, ast.BoolOp):
            # Binary nesting keeps the same ownership and identities as QueryBinary.
            if len(node.values) > 64:
                raise QueryExpressionError("Boolean chain exceeds the query depth budget")
            if len(node.values) > 2:
                node = ast.BoolOp(node.op, [ast.BoolOp(node.op, node.values[:-1]), node.values[-1]])
            return l.QueryBinary(
                _identity(l.QueryBinary, previous),
                _BINARY[type(node.op)],
                self.query(node.values[0], environment, _old(previous, "left")),
                self.query(node.values[1], environment, _old(previous, "right")),
            )
        if isinstance(node, (ast.BinOp, ast.Compare)):
            operator: ast.operator | ast.cmpop
            if isinstance(node, ast.Compare):
                if len(node.ops) != 1:
                    raise QueryExpressionError(
                        "Write chained comparisons as separate comparisons joined by and"
                    )
                operator, left, right = node.ops[0], node.left, node.comparators[0]
            else:
                operator, left, right = node.op, node.left, node.right
            if type(operator) not in _BINARY:
                raise QueryExpressionError("This operator is not part of the domain query language")
            return l.QueryBinary(
                _identity(l.QueryBinary, previous),
                _BINARY[type(operator)],
                self.query(left, environment, _old(previous, "left")),
                self.query(right, environment, _old(previous, "right")),
            )
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            return self.call(node, node.func.id, environment, previous)
        raise QueryExpressionError(
            "Use domain members, scalar values, operators, or supported query constructors"
        )

    def call(
        self, node: ast.Call, name: str, environment: _Environment, previous: object
    ) -> l.Query:
        if name == "hole":
            _call_arguments(node, 1)
            return l.QueryHole(_identity(l.QueryHole, previous), _literal_text(node.args[0]))
        if name == "binding":
            _call_arguments(node, 1)
            identity = _literal_text(node.args[0])
            binding_matches = tuple(
                item for item in environment.values() if identity in {item.id, item.name}
            )
            if len(binding_matches) != 1:
                raise QueryExpressionError("Binding identity is unavailable or ambiguous")
            return l.QueryVariable(_identity(l.QueryVariable, previous), binding_matches[0].id)
        if name == "nodes":
            options = _call_arguments(node, 1, keywords=("roots",))
            label = _literal_text(node.args[0])
            exact = tuple(item for item in self.schema.concepts if item.id == label)
            matches = exact or tuple(item for item in self.schema.concepts if item.name == label)
            if len(matches) != 1:
                raise QueryExpressionError(f"Concept {label!r} is unavailable or ambiguous")
            roots = False
            if "roots" in options:
                value = options["roots"]
                if not isinstance(value, ast.Constant) or type(value.value) is not bool:
                    raise QueryExpressionError("roots requires True or False")
                roots = value.value
            return l.QueryNodes(_identity(l.QueryNodes, previous), matches[0].id, roots)
        if name in {"prop", "role"}:
            _call_arguments(node, 2)
            source = self.query(node.args[0], environment, _old(previous, "source"))
            identity, _ = self.member(
                source,
                _literal_text(node.args[1]),
                environment,
                "property" if name == "prop" else "role",
            )
            return (
                l.QueryProperty(_identity(l.QueryProperty, previous), source, identity)
                if name == "prop"
                else l.QueryRole(_identity(l.QueryRole, previous), source, identity)
            )
        if name in {"first", "count", "identity"}:
            _call_arguments(node, 1)
            child = "source" if name == "identity" else "operand"
            source = self.query(node.args[0], environment, _old(previous, child))
            if name == "identity":
                return l.QueryIdentity(_identity(l.QueryIdentity, previous), source)
            return l.QueryUnary(
                _identity(l.QueryUnary, previous),
                l.QueryUnaryOperator.FIRST if name == "first" else l.QueryUnaryOperator.COUNT,
                source,
            )
        if name in _COLLECTIONS:
            _call_arguments(node, 3)
            collection = self.query(node.args[0], environment, _old(previous, "collection"))
            shape = self.shape(collection, environment)
            if shape.kind != "sequence":
                raise QueryExpressionError("Collection queries require a collection")
            alias = _literal_text(node.args[1])
            if not alias or alias in environment:
                raise QueryExpressionError(
                    "Local query aliases must be nonempty and cannot shadow another binding"
                )
            kind = _COLLECTIONS[name]
            binding_id = (
                previous.binding_id
                if type(previous) is kind
                and isinstance(previous, (l.QueryMap, l.QueryFilter, l.QueryAll, l.QueryUnique))
                else f"query:binding:{alias}:{uuid4().hex}"
            )
            nested = {
                **environment,
                alias: QueryExpressionBinding(
                    binding_id, alias, value_type=shape.element or QueryType("unknown")
                ),
            }
            child = "value" if name == "map" else "key" if name == "unique" else "predicate"
            body = self.query(node.args[2], nested, _old(previous, child))
            return kind(_identity(kind, previous), collection, binding_id, body)
        raise QueryExpressionError(f"Unknown query constructor {name!r}")


def parse_query_expression(
    text: str,
    schema: DomainSchema,
    bindings: tuple[QueryExpressionBinding, ...] = (),
    existing: l.Query | None = None,
) -> l.Query:
    """Parse and type-check a draft without executing code or modifying authority."""

    if len(text) > 100_000:
        raise QueryExpressionError("Query text exceeds its budget")
    environment = _environment(bindings)
    try:
        tree = ast.parse(text.strip(), mode="eval")
        pending: list[tuple[ast.AST, int]] = [(tree, 0)]
        count = 0
        while pending:
            item, depth = pending.pop()
            count += 1
            if count > 10_000 or depth > 64:
                raise QueryExpressionError("Query expression exceeds its structural budget")
            pending.extend((child, depth + 1) for child in ast.iter_child_nodes(item))
        result = _Parser(schema).query(tree.body, environment, existing)
    except (SyntaxError, RecursionError) as error:
        raise QueryExpressionError(f"Invalid query expression: {error}") from error
    owned: list[tuple[object, int]] = [(result, 0)]
    while owned:
        value, depth = owned.pop()
        if depth > 64:
            raise QueryExpressionError("Query output exceeds its structural depth budget")
        if isinstance(value, tuple):
            owned.extend((item, depth + 1) for item in value)
        elif is_dataclass(value) and not isinstance(value, type):
            owned.extend((getattr(value, field.name), depth + 1) for field in fields(value))
    checker = LanguageTypeChecker(schema)
    checker.query(result, {item.id: item.shape for item in bindings})
    issues = tuple(item for item in checker.issues if item.code != "LANGUAGE_HOLE")
    if issues:
        raise QueryExpressionError(issues[0].message)
    return result


def _alias(identity: str, environment: _Environment) -> str:
    parts = identity.split(":")
    raw = parts[-2] if len(parts) > 1 and re.fullmatch(r"[a-f0-9]{32}", parts[-1]) else parts[-1]
    candidate = re.sub(r"\W", "_", raw)
    if not candidate.isidentifier() or keyword.iskeyword(candidate):
        candidate = "item"
    name = candidate
    index = 2
    while name in environment:
        name = f"{candidate}{index}"
        index += 1
    return name


class _Formatter(_Parser):
    def query_text(self, query: l.Query, environment: _Environment) -> str:
        if isinstance(query, l.QueryLiteral):
            return repr(query.value)
        if isinstance(query, l.QueryHole):
            return f"hole({query.label!r})"
        if isinstance(query, l.QueryVariable):
            name = next(
                (item.name for item in environment.values() if item.id == query.binding_id), None
            )
            if name is None:
                return f"binding({query.binding_id!r})"
            return (
                name
                if name.isidentifier() and not keyword.iskeyword(name)
                else f"binding({name!r})"
            )
        if isinstance(query, l.QueryNodes):
            concept = self.schema.concept(query.concept_id)
            name = (
                concept.name
                if concept and sum(item.name == concept.name for item in self.schema.concepts) == 1
                else query.concept_id
            )
            return f"nodes({name!r}" + (", roots=True)" if query.roots_only else ")")
        if isinstance(query, (l.QueryRole, l.QueryProperty)):
            source = self.query_text(query.source, environment)
            shape = self.shape(query.source, environment)
            kind = "role" if isinstance(query, l.QueryRole) else "property"
            identity = query.role_id if isinstance(query, l.QueryRole) else query.property_id
            members = {
                item.id: item
                for concept_id in shape.concept_ids
                if (concept := self.schema.concept(concept_id)) is not None
                for item in (
                    (*concept.containment_roles, *concept.reference_roles)
                    if kind == "role"
                    else concept.properties
                )
            }
            member = members.get(identity)
            name = (
                member.name
                if member and sum(item.name == member.name for item in members.values()) == 1
                else identity
            )
            try:
                unambiguous = self.member(query.source, name, environment) == (identity, kind)
            except QueryExpressionError:
                unambiguous = False
            if name.isidentifier() and not keyword.iskeyword(name) and unambiguous:
                return f"{source}.{name}"
            constructor = "role" if kind == "role" else "prop"
            return f"{constructor}({source}, {name!r})"
        if isinstance(query, l.QueryIdentity):
            return f"identity({self.query_text(query.source, environment)})"
        if isinstance(query, l.QueryUnary):
            operand = self.query_text(query.operand, environment)
            return (
                f"(not {operand})"
                if query.operator == l.QueryUnaryOperator.NOT
                else f"{query.operator.value}({operand})"
            )
        if isinstance(query, l.QueryBinary):
            return (
                f"({self.query_text(query.left, environment)} "
                f"{_OPERATOR_TEXT[query.operator]} {self.query_text(query.right, environment)})"
            )
        if isinstance(query, l.QueryTuple):
            return "[" + ", ".join(self.query_text(item, environment) for item in query.items) + "]"
        if isinstance(query, (l.QueryMap, l.QueryFilter, l.QueryAll, l.QueryUnique)):
            collection = self.query_text(query.collection, environment)
            shape = self.shape(query.collection, environment)
            alias = _alias(query.binding_id, environment)
            nested = {
                **environment,
                alias: QueryExpressionBinding(
                    query.binding_id, alias, value_type=shape.element or QueryType("unknown")
                ),
            }
            name = next(name for name, kind in _COLLECTIONS.items() if type(query) is kind)
            child = (
                query.value
                if isinstance(query, l.QueryMap)
                else query.key
                if isinstance(query, l.QueryUnique)
                else query.predicate
            )
            body = self.query_text(child, nested)
            result = f"{name}({collection}, {alias!r}, {body})"
            return (
                result
                if len(result) < 100 and "\n" not in result
                else f"{name}(\n  {collection}, {alias!r},\n  " + body.replace("\n", "\n  ") + "\n)"
            )
        raise QueryExpressionError("Unsupported query record")


def format_query_expression(
    query: l.Query, schema: DomainSchema, bindings: tuple[QueryExpressionBinding, ...] = ()
) -> str:
    """Project typed syntax into an editor buffer; no duplicate source text is saved."""

    return _Formatter(schema).query_text(query, _environment(bindings))
