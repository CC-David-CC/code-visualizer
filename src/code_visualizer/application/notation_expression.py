"""Readable notation expressions compile directly into the one typed visual AST.

The parser accepts a closed call grammar. Python's parser supplies tokenization only;
names, attributes, operators, imports and arbitrary calls are never evaluated.
"""

from __future__ import annotations

import ast
import math
from dataclasses import dataclass
from typing import cast
from uuid import uuid4

from code_visualizer.domain import notation_syntax as v
from code_visualizer.domain.intentional import ConceptDefinition, DomainSchema, DomainWorkspace
from code_visualizer.domain.notation_validation import validate_composed_notation


class NotationExpressionError(ValueError):
    """A readable expression cannot resolve to a valid typed notation."""


@dataclass(frozen=True)
class _Binding:
    identity: str
    concepts: tuple[ConceptDefinition, ...]


type _Environment = dict[str, _Binding]
type _Scalar = str | int | float | bool | None


def _literal(node: ast.AST) -> _Scalar | tuple[_Scalar, ...]:
    if isinstance(node, ast.Constant) and type(node.value) in {str, int, float, bool, type(None)}:
        return cast(_Scalar, node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        value = _literal(node.operand)
        if type(value) in {int, float}:
            return -cast(int | float, value)
    if isinstance(node, (ast.Tuple, ast.List)):
        items = tuple(_literal(item) for item in node.elts)
        if all(not isinstance(item, tuple) for item in items):
            return cast(tuple[_Scalar, ...], items)
    raise NotationExpressionError("Use a literal value or a supported notation constructor")


class _Call:
    def __init__(self, node: ast.AST, positional: tuple[str, ...], allowed: tuple[str, ...] = ()):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            raise NotationExpressionError("Expected a named notation constructor")
        if len(node.args) > len(positional):
            raise NotationExpressionError(f"Too many arguments for {node.func.id}")
        self.values = dict(zip(positional, node.args, strict=False))
        for keyword in node.keywords:
            if keyword.arg is None or keyword.arg not in (*positional, *allowed):
                raise NotationExpressionError(f"Unknown option {keyword.arg!r} for {node.func.id}")
            if keyword.arg in self.values:
                raise NotationExpressionError(f"Repeated argument {keyword.arg!r}")
            self.values[keyword.arg] = keyword.value

    def node(self, name: str) -> ast.AST:
        if name not in self.values:
            raise NotationExpressionError(f"Missing argument {name!r}")
        return self.values[name]

    def string(self, name: str, default: str | None = None) -> str:
        value = _literal(self.values[name]) if name in self.values else default
        if not isinstance(value, str):
            raise NotationExpressionError(f"{name!r} requires text")
        return value

    def boolean(self, name: str, default: bool) -> bool:
        value = _literal(self.values[name]) if name in self.values else default
        if type(value) is not bool:
            raise NotationExpressionError(f"{name!r} requires True or False")
        return value

    def number(self, name: str, default: float) -> float:
        value = _literal(self.values[name]) if name in self.values else default
        if type(value) not in {int, float} or not math.isfinite(cast(float, value)):
            raise NotationExpressionError(f"{name!r} requires a finite number")
        return float(cast(float, value))


def _identity(kind: type[object], previous: object) -> str:
    return (
        str(getattr(previous, "id", None)) if type(previous) is kind else f"notation:{uuid4().hex}"
    )


def _child(previous: object, name: str) -> object:
    return getattr(previous, name, None)


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id
    raise NotationExpressionError("Expected a notation constructor such as row(), text() or each()")


class _Parser:
    def __init__(self, schema: DomainSchema, workspace: DomainWorkspace | None):
        self.schema = schema
        self.workspace = workspace or DomainWorkspace((schema,))

    def binding(self, name: str, environment: _Environment) -> _Binding:
        if name not in environment:
            raise NotationExpressionError(f"Unknown object alias {name!r}")
        return environment[name]

    def schema_named(self, name: str, version: str | None) -> DomainSchema:
        matches = tuple(
            item
            for item in self.workspace.schemas
            if name in {item.id, item.namespace} and (version is None or item.version == version)
        )
        if len(matches) != 1:
            raise NotationExpressionError(
                f"Schema {name!r} is unavailable or ambiguous; use its ID and version"
            )
        return matches[0]

    def member(self, binding: _Binding, name: str, *, role: bool = False) -> str:
        members = {
            item.id: item
            for concept in binding.concepts
            for item in (
                (*concept.containment_roles, *concept.reference_roles)
                if role
                else concept.properties
            )
        }
        if name in members:
            return name
        matches = [item.id for item in members.values() if item.name == name]
        if len(matches) != 1:
            raise NotationExpressionError(
                f"{'Role' if role else 'Property'} {name!r} is unavailable or ambiguous; "
                "use its stable ID"
            )
        return matches[0]

    def role_target(self, binding: _Binding, role_id: str) -> _Binding:
        ids = {
            target
            for concept in binding.concepts
            for role in (*concept.containment_roles, *concept.reference_roles)
            if role.id == role_id
            for target in role.allowed_concept_ids
        }
        return _Binding(
            binding.identity,
            tuple(
                concept
                for schema in self.workspace.schemas
                for concept in schema.concepts
                if concept.id in ids
            ),
        )

    def incoming_role(
        self, binding: _Binding, name: str
    ) -> tuple[str, tuple[ConceptDefinition, ...]]:
        targets = {concept.id for concept in binding.concepts}
        candidates = tuple(
            (concept, role)
            for schema in self.workspace.schemas
            for concept in schema.concepts
            for role in (*concept.containment_roles, *concept.reference_roles)
            if targets & set(role.allowed_concept_ids)
        )
        exact = tuple((concept, role) for concept, role in candidates if role.id == name)
        matches = exact or tuple(
            (concept, role) for concept, role in candidates if role.name == name
        )
        identities = {role.id for _, role in matches}
        if len(identities) != 1:
            raise NotationExpressionError(f"Incoming role {name!r} is unavailable or ambiguous")
        return next(iter(identities)), tuple(concept for concept, _ in matches)

    def numeric(self, node: ast.AST, environment: _Environment, previous: object) -> v.VisualNumber:
        identity = _identity(v.VisualNumber, previous)
        if not isinstance(node, ast.Call):
            value = _literal(node)
            if type(value) not in {int, float}:
                raise NotationExpressionError(
                    "A coordinate requires a number or number(alias, property)"
                )
            return v.VisualNumber(identity, float(cast(float, value)))
        if _name(node) != "number":
            raise NotationExpressionError("Use number(alias, property, scale=..., offset=...)")
        call = _Call(node, ("alias", "property"), ("scale", "offset", "value"))
        binding = self.binding(call.string("alias"), environment)
        prop = self.member(binding, call.string("property")) if "property" in call.values else None
        return v.VisualNumber(
            identity,
            call.number("value", 0),
            binding.identity,
            prop,
            call.number("scale", 1),
            call.number("offset", 0),
        )

    def visual(self, node: ast.AST, environment: _Environment, previous: object = None) -> v.Visual:
        name = _name(node)
        if name in {"row", "column", "wrap", "positioned"}:
            assert isinstance(node, ast.Call)
            call = _Call(
                ast.Call(func=node.func, args=[], keywords=node.keywords),
                (),
                ("gap", "padding", "wrap_width"),
            )
            old_children = previous.children if isinstance(previous, v.VisualGroup) else ()
            return v.VisualGroup(
                _identity(v.VisualGroup, previous),
                v.VisualLayout(name),
                tuple(
                    self.visual(
                        item,
                        environment,
                        old_children[index] if index < len(old_children) else None,
                    )
                    for index, item in enumerate(node.args)
                ),
                call.number("gap", 8),
                call.number("padding", 0),
                call.number("wrap_width", 600),
            )
        if name == "text":
            call = _Call(node, ("text",), ("font_size", "strong", "color"))
            return v.VisualText(
                _identity(v.VisualText, previous),
                call.string("text"),
                call.number("font_size", 14),
                call.boolean("strong", False),
                call.string("color", "#172033"),
            )
        if name == "hole":
            call = _Call(node, ("label",))
            return v.VisualHole(
                _identity(v.VisualHole, previous),
                call.string("label", "Choose a visual or textual element"),
            )
        if name == "field":
            call = _Call(node, ("alias", "property"), ("through", "editable", "font_size"))
            binding = self.binding(call.string("alias"), environment)
            target = binding
            roles = []
            if "through" in call.values:
                names = _literal(call.node("through"))
                names = (names,) if isinstance(names, str) else names
                if not isinstance(names, tuple) or not all(isinstance(item, str) for item in names):
                    raise NotationExpressionError(
                        "through requires a role name or tuple of role names"
                    )
                for role_name in names:
                    role_id = self.member(target, cast(str, role_name), role=True)
                    roles.append(role_id)
                    target = self.role_target(target, role_id)
            prop = (
                self.member(target, call.string("property")) if "property" in call.values else None
            )
            return v.VisualField(
                _identity(v.VisualField, previous),
                binding.identity,
                prop,
                tuple(roles),
                call.boolean("editable", True),
                call.number("font_size", 14),
            )
        if name in {"each", "related", "repeat_hole"}:
            return self.repeat(node, environment, previous)
        if name == "box":
            call = _Call(node, ("body",), ("shape", "padding", "fill", "stroke", "width", "height"))
            return v.VisualBox(
                _identity(v.VisualBox, previous),
                self.visual(call.node("body"), environment, _child(previous, "body")),
                v.VisualShape(call.string("shape", "rounded")),
                call.number("padding", 12),
                call.string("fill", "#edf3fc"),
                call.string("stroke", "#536b91"),
                self.numeric(call.node("width"), environment, _child(previous, "width"))
                if "width" in call.values
                else None,
                self.numeric(call.node("height"), environment, _child(previous, "height"))
                if "height" in call.values
                else None,
            )
        if name == "at":
            call = _Call(node, ("x", "y", "body"))
            return v.VisualPosition(
                _identity(v.VisualPosition, previous),
                self.visual(call.node("body"), environment, _child(previous, "body")),
                self.numeric(call.node("x"), environment, _child(previous, "x")),
                self.numeric(call.node("y"), environment, _child(previous, "y")),
            )
        if name == "fraction":
            call = _Call(node, ("numerator", "denominator"))
            return v.VisualFraction(
                _identity(v.VisualFraction, previous),
                self.visual(call.node("numerator"), environment, _child(previous, "numerator")),
                self.visual(call.node("denominator"), environment, _child(previous, "denominator")),
            )
        if name in {"superscript", "subscript"}:
            call = _Call(node, ("base", "script"))
            return v.VisualScript(
                _identity(v.VisualScript, previous),
                self.visual(call.node("base"), environment, _child(previous, "base")),
                self.visual(call.node("script"), environment, _child(previous, "script")),
                v.ScriptPosition.SUPER if name == "superscript" else v.ScriptPosition.SUB,
            )
        if name == "connect":
            call = _Call(node, ("source", "target"), ("label", "arrow", "stroke"))
            return v.VisualConnector(
                _identity(v.VisualConnector, previous),
                self.binding(call.string("source"), environment).identity,
                self.binding(call.string("target"), environment).identity,
                call.string("label", ""),
                call.boolean("arrow", True),
                call.string("stroke", "#536b91"),
            )
        if name == "when":
            call = _Call(
                node, ("alias", "property", "operator", "expected", "body"), ("otherwise",)
            )
            binding = self.binding(call.string("alias"), environment)
            expected = _literal(call.node("expected"))
            if isinstance(expected, tuple):
                raise NotationExpressionError("A condition compares a scalar value")
            prop_value = _literal(call.node("property"))
            prop = None if prop_value is None else self.member(binding, call.string("property"))
            predicate = v.VisualPredicate(
                _identity(v.VisualPredicate, _child(previous, "predicate")),
                binding.identity,
                prop,
                v.VisualComparison(call.string("operator")),
                expected,
            )
            return v.VisualConditional(
                _identity(v.VisualConditional, previous),
                predicate,
                self.visual(call.node("body"), environment, _child(previous, "body")),
                self.visual(call.node("otherwise"), environment, _child(previous, "otherwise"))
                if "otherwise" in call.values
                else None,
            )
        if name == "path":
            assert isinstance(node, ast.Call)
            call = _Call(
                ast.Call(func=node.func, args=[], keywords=node.keywords),
                (),
                ("closed", "stroke", "fill"),
            )
            points = []
            old_points = previous.points if isinstance(previous, v.VisualPath) else ()
            for index, item in enumerate(node.args):
                if _name(item) != "point":
                    raise NotationExpressionError("path contains point(x, y) values")
                point = _Call(item, ("x", "y"))
                old = old_points[index] if index < len(old_points) else None
                points.append(
                    v.VisualPoint(
                        _identity(v.VisualPoint, old),
                        self.numeric(point.node("x"), environment, _child(old, "x")),
                        self.numeric(point.node("y"), environment, _child(old, "y")),
                    )
                )
            return v.VisualPath(
                _identity(v.VisualPath, previous),
                tuple(points),
                call.boolean("closed", False),
                call.string("stroke", "#536b91"),
                call.string("fill", "transparent"),
            )
        raise NotationExpressionError(f"Unknown notation constructor {name!r}")

    def repeat(self, node: ast.AST, environment: _Environment, previous: object) -> v.VisualRepeat:
        name = _name(node)
        old_query = _child(previous, "query")
        query: v.NotationQuery
        if name == "each":
            call = _Call(
                node,
                ("concept", "alias", "body"),
                ("scope", "schema", "version", "model", "roots", "layout", "gap"),
            )
            schema = (
                self.schema_named(
                    call.string("schema"),
                    call.string("version") if "version" in call.values else None,
                )
                if "schema" in call.values
                else self.schema
            )
            concept_name = call.string("concept")
            concepts = (
                tuple(item for item in schema.concepts if concept_name in {item.name, item.id})
                if concept_name
                else schema.concepts
            )
            if concept_name and len(concepts) != 1:
                raise NotationExpressionError(
                    f"Concept {concept_name!r} is unavailable or ambiguous"
                )
            scope = call.string("scope", "model")
            if scope not in {"model", "workspace"}:
                raise NotationExpressionError("scope must be 'model' or 'workspace'")
            query = v.NotationObjects(
                _identity(v.NotationObjects, old_query),
                concepts[0].id if concept_name else "",
                schema.id if "schema" in call.values else None,
                schema.version if "schema" in call.values else None,
                call.string("model") if "model" in call.values else None,
                scope == "workspace",
                call.boolean("roots", False),
            )
        elif name == "related":
            call = _Call(
                node,
                ("source", "kind", "alias", "body"),
                ("role", "label", "incoming", "layout", "gap"),
            )
            source = self.binding(call.string("source"), environment)
            incoming = call.boolean("incoming", False)
            role = None
            concepts = tuple(
                concept for schema in self.workspace.schemas for concept in schema.concepts
            )
            if "role" in call.values:
                if incoming:
                    role, concepts = self.incoming_role(source, call.string("role"))
                else:
                    role = self.member(source, call.string("role"), role=True)
                    concepts = self.role_target(source, role).concepts
            kind = call.string("kind", "")
            query = v.NotationRelated(
                _identity(v.NotationRelated, old_query),
                source.identity,
                role,
                kind or None,
                call.string("label") if "label" in call.values else None,
                incoming,
            )
        else:
            call = _Call(node, ("alias", "body"), ("label", "layout", "gap"))
            query = v.NotationQueryHole(
                _identity(v.NotationQueryHole, old_query),
                call.string("label", "Choose objects to display"),
            )
            concepts = self.schema.concepts
        alias = call.string("alias")
        if not alias or alias in environment:
            raise NotationExpressionError(
                "An object alias must be nonempty and cannot shadow another alias"
            )
        binding = _Binding(
            previous.binding_id
            if isinstance(previous, v.VisualRepeat)
            else f"binding:{uuid4().hex}",
            concepts,
        )
        nested = {**environment, alias: binding, "self": _Binding("self", concepts)}
        return v.VisualRepeat(
            _identity(v.VisualRepeat, previous),
            query,
            binding.identity,
            self.visual(call.node("body"), nested, _child(previous, "body")),
            alias,
            v.VisualLayout(call.string("layout", "column")),
            call.number("gap", 8),
        )


def parse_notation_expression(
    text: str,
    schema: DomainSchema,
    workspace: DomainWorkspace | None = None,
    existing: v.Visual | None = None,
) -> v.Visual:
    """Compile checked readable syntax, retaining IDs of matching structural slots."""

    if len(text) > 100_000:
        raise NotationExpressionError("Notation expression exceeds its text budget")
    try:
        tree = ast.parse(text.strip(), mode="eval")
        pending: list[tuple[ast.AST, int]] = [(tree, 0)]
        count = 0
        while pending:
            item, depth = pending.pop()
            count += 1
            if count > 20_000 or depth > 64:
                raise NotationExpressionError("Notation expression exceeds its structural budget")
            pending.extend((child, depth + 1) for child in ast.iter_child_nodes(item))
        result = _Parser(schema, workspace).visual(
            tree.body, {"self": _Binding("self", schema.concepts)}, existing
        )
    except (SyntaxError, RecursionError) as error:
        raise NotationExpressionError(f"Invalid notation expression: {error}") from error
    findings = validate_composed_notation(result, schema, workspace)
    blocking = tuple(item for item in findings if item.code != "NOTATION_HOLE")
    if blocking:
        raise NotationExpressionError(blocking[0].message)
    return result


def _call(name: str, values: tuple[str, ...] = (), **options: object) -> str:
    defaults: dict[str, object] = {
        "font_size": 14.0,
        "strong": False,
        "editable": True,
        "color": "#172033",
        "shape": "rounded",
        "stroke": "#536b91",
        "arrow": True,
        "closed": False,
        "through": (),
        "scale": 1.0,
        "offset": 0.0,
        "value": 0.0,
        "gap": 8.0,
        "wrap_width": 600.0,
        "roots": False,
        "scope": "model",
        "layout": "column",
        "incoming": False,
        "padding": 12.0 if name == "box" else 0.0,
        "fill": "#edf3fc" if name == "box" else "transparent",
    }
    if name == "connect":
        defaults["label"] = ""
    parts = (
        *values,
        *(
            f"{key}={value!r}"
            for key, value in options.items()
            if key not in defaults or value != defaults[key]
        ),
    )
    compact = f"{name}({', '.join(parts)})"
    if len(compact) <= 100 and "\n" not in compact:
        return compact
    return name + "(\n" + ",\n".join("  " + part.replace("\n", "\n  ") for part in parts) + "\n)"


class _Formatter(_Parser):
    def alias(self, identity: str, environment: _Environment) -> str:
        return next(
            (name for name, binding in environment.items() if binding.identity == identity),
            identity,
        )

    def member_name(self, binding: _Binding, identity: str, *, role: bool = False) -> str:
        members = {
            item.id: item
            for concept in binding.concepts
            for item in (
                (*concept.containment_roles, *concept.reference_roles)
                if role
                else concept.properties
            )
        }
        item = members.get(identity)
        if item is None:
            return identity
        matches = {value.id for value in members.values() if value.name == item.name}
        return item.name if len(matches) == 1 else identity

    def numeric_text(self, value: v.VisualNumber, environment: _Environment) -> str:
        if (
            value.property_id is None
            and value.binding_id == "self"
            and value.scale == 1
            and value.offset == 0
        ):
            return repr(value.value)
        alias = self.alias(value.binding_id, environment)
        binding = environment.get(alias, _Binding(value.binding_id, ()))
        args: tuple[str, ...] = (repr(alias),)
        if value.property_id is not None:
            args += (repr(self.member_name(binding, value.property_id)),)
        return _call("number", args, scale=value.scale, offset=value.offset, value=value.value)

    def visual_text(self, value: v.Visual, environment: _Environment) -> str:
        if isinstance(value, v.VisualText):
            return _call(
                "text",
                (repr(value.text),),
                font_size=value.font_size,
                strong=value.strong,
                color=value.color,
            )
        if isinstance(value, v.VisualHole):
            return _call("hole", (repr(value.label),))
        if isinstance(value, v.VisualField):
            alias = self.alias(value.binding_id, environment)
            binding = environment.get(alias, _Binding(value.binding_id, ()))
            roles = []
            for identity in value.reference_role_ids:
                roles.append(self.member_name(binding, identity, role=True))
                binding = self.role_target(binding, identity)
            args: tuple[str, ...] = (repr(alias),)
            if value.property_id is not None:
                args += (repr(self.member_name(binding, value.property_id)),)
            return _call(
                "field",
                args,
                through=tuple(roles),
                editable=value.editable,
                font_size=value.font_size,
            )
        if isinstance(value, v.VisualGroup):
            return _call(
                value.layout.value,
                tuple(self.visual_text(item, environment) for item in value.children),
                gap=value.gap,
                padding=value.padding,
                wrap_width=value.wrap_width,
            )
        if isinstance(value, v.VisualRepeat):
            return self.repeat_text(value, environment)
        if isinstance(value, v.VisualBox):
            result = _call(
                "box",
                (self.visual_text(value.body, environment),),
                shape=value.shape.value,
                padding=value.padding,
                fill=value.fill,
                stroke=value.stroke,
            )
            sizes = [
                f"{name}={self.numeric_text(item, environment)}"
                for name, item in (("width", value.width), ("height", value.height))
                if item is not None
            ]
            return result[:-1] + (", " + ", ".join(sizes) if sizes else "") + ")"
        if isinstance(value, v.VisualPosition):
            return _call(
                "at",
                (
                    self.numeric_text(value.x, environment),
                    self.numeric_text(value.y, environment),
                    self.visual_text(value.body, environment),
                ),
            )
        if isinstance(value, v.VisualFraction):
            return _call(
                "fraction",
                (
                    self.visual_text(value.numerator, environment),
                    self.visual_text(value.denominator, environment),
                ),
            )
        if isinstance(value, v.VisualScript):
            return _call(
                "superscript" if value.position == v.ScriptPosition.SUPER else "subscript",
                (
                    self.visual_text(value.base, environment),
                    self.visual_text(value.script, environment),
                ),
            )
        if isinstance(value, v.VisualConnector):
            return _call(
                "connect",
                (
                    repr(self.alias(value.source_binding_id, environment)),
                    repr(self.alias(value.target_binding_id, environment)),
                ),
                label=value.label,
                arrow=value.arrow,
                stroke=value.stroke,
            )
        if isinstance(value, v.VisualConditional):
            predicate = value.predicate
            alias = self.alias(predicate.binding_id, environment)
            binding = environment.get(alias, _Binding(predicate.binding_id, ()))
            prop = (
                self.member_name(binding, predicate.property_id)
                if predicate.property_id is not None
                else None
            )
            result = _call(
                "when",
                (
                    repr(alias),
                    repr(prop),
                    repr(predicate.operator.value),
                    repr(predicate.expected),
                    self.visual_text(value.body, environment),
                ),
            )
            return (
                result
                if value.otherwise is None
                else result[:-1]
                + ", otherwise="
                + self.visual_text(value.otherwise, environment)
                + ")"
            )
        if isinstance(value, v.VisualPath):
            return _call(
                "path",
                tuple(
                    _call(
                        "point",
                        (
                            self.numeric_text(point.x, environment),
                            self.numeric_text(point.y, environment),
                        ),
                    )
                    for point in value.points
                ),
                closed=value.closed,
                stroke=value.stroke,
                fill=value.fill,
            )
        raise NotationExpressionError("Unsupported visual record")

    def repeat_text(self, value: v.VisualRepeat, environment: _Environment) -> str:
        query = value.query
        args: tuple[str, ...]
        options: dict[str, object] = {"layout": value.layout.value, "gap": value.gap}
        if isinstance(query, v.NotationObjects):
            schema = self.workspace.schema(query.schema_id) if query.schema_id else self.schema
            schema = schema or self.schema
            concept = schema.concept(query.concept_id)
            concepts = (concept,) if concept is not None else schema.concepts
            label = (
                concept.name
                if concept is not None
                and sum(item.name == concept.name for item in schema.concepts) == 1
                else query.concept_id
            )
            args = (repr(label), repr(value.binding_name))
            name = "each"
            options.update(
                scope="workspace" if query.workspace else "model", roots=query.roots_only
            )
            if query.schema_id is not None:
                matches = [
                    item
                    for item in self.workspace.schemas
                    if item.namespace == schema.namespace and item.version == schema.version
                ]
                options.update(
                    schema=schema.namespace if len(matches) == 1 else schema.id,
                    version=query.schema_version,
                )
            if query.model_id is not None:
                options["model"] = query.model_id
        elif isinstance(query, v.NotationRelated):
            alias = self.alias(query.source_binding_id, environment)
            source = environment.get(alias, _Binding(query.source_binding_id, ()))
            concepts = tuple(
                concept for schema in self.workspace.schemas for concept in schema.concepts
            )
            if query.role_id:
                concepts = (
                    self.incoming_role(source, query.role_id)[1]
                    if query.incoming
                    else self.role_target(source, query.role_id).concepts
                )
            args = (repr(alias), repr(query.relation_kind or ""), repr(value.binding_name))
            name = "related"
            options["incoming"] = query.incoming
            if query.role_id is not None:
                role_owner = _Binding(source.identity, concepts) if query.incoming else source
                options["role"] = self.member_name(role_owner, query.role_id, role=True)
            if query.relation_label is not None:
                options["label"] = query.relation_label
        else:
            name = "repeat_hole"
            args = (repr(value.binding_name),)
            concepts = self.schema.concepts
            options["label"] = query.label
        nested = {
            **environment,
            value.binding_name: _Binding(value.binding_id, concepts),
            "self": _Binding("self", concepts),
        }
        return _call(name, (*args, self.visual_text(value.body, nested)), **options)


def format_notation_expression(
    visual: v.Visual,
    schema: DomainSchema,
    workspace: DomainWorkspace | None = None,
) -> str:
    """Render editable text from canonical syntax; the text is never persisted separately."""

    return _Formatter(schema, workspace).visual_text(
        visual, {"self": _Binding("self", schema.concepts)}
    )
