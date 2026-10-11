"""Bounded interpretation of inert authoring rules into the existing typed program IR."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass

from code_visualizer.domain import language as lang
from code_visualizer.domain.expression import (
    BinaryExpression,
    CallExpression,
    CompositeExpression,
    ExpressionContext,
    ExpressionField,
    ExpressionList,
    ExpressionNode,
    ExpressionScalar,
    LiteralExpression,
    SymbolReferenceExpression,
)
from code_visualizer.domain.intentional import (
    DomainIssue,
    DomainModel,
    DomainSchema,
    DomainWorkspace,
    IntentionalNode,
    PropertyValue,
    RoleBinding,
)
from code_visualizer.domain.intentional_validation import validate_domain_workspace
from code_visualizer.domain.language_validation import validate_authored_language
from code_visualizer.domain.program import (
    ExpressionRole,
    ProgramAssignment,
    ProgramExpression,
    ProgramFunction,
    ProgramFunctionReference,
    ProgramIf,
    ProgramLoop,
    ProgramModel,
    ProgramModule,
    ProgramOutput,
    ProgramParameter,
    ProgramSequence,
    ProgramStatement,
    ProgramSymbol,
    ProgramSymbolKind,
    ProgramTransfer,
)
from code_visualizer.domain.program_kinds import CallableKind, LoopKind
from code_visualizer.domain.transformation import OriginLink, OriginMap, derived_id
from code_visualizer.domain.values import CanonicalValue, validate_canonical_value
from code_visualizer.generation.transformation import (
    RegisteredTransformation,
    TransformationError,
    TransformationInput,
    TransformationResult,
)

type QueryValue = CanonicalValue | IntentionalNode | tuple[QueryValue, ...] | None


class LanguageEvaluationError(TransformationError):
    def __init__(self, code: str, message: str, object_id: str) -> None:
        super().__init__(code, message)
        self.object_id = object_id


@dataclass(slots=True)
class EvaluationBudget:
    steps: int = 100_000
    max_collection: int = 20_000
    generated_nodes: int = 100_000
    max_text: int = 1_000_000

    def charge(self, identity: str, count: int = 1) -> None:
        self.steps -= count
        if self.steps < 0:
            raise LanguageEvaluationError(
                "LANGUAGE_BUDGET", "Authoring evaluation exceeded its operation budget", identity
            )

    def collection(self, count: int, identity: str) -> None:
        if count > self.max_collection:
            raise LanguageEvaluationError(
                "LANGUAGE_BUDGET", "Authoring collection exceeded its size budget", identity
            )


class _Queries:
    def __init__(
        self,
        schema: DomainSchema,
        model: DomainModel,
        budget: EvaluationBudget,
        workspace: DomainWorkspace | None = None,
    ) -> None:
        self.schema, self.model, self.budget = schema, model, budget
        self.concepts = {
            concept.id: concept
            for current in (workspace.schemas if workspace is not None else (schema,))
            for concept in current.concepts
        }
        self.concepts.update({concept.id: concept for concept in schema.concepts})
        self.nodes = {node.id: node for node in model.nodes}
        # Queries enumerate only their source model. Explicit references permit
        # traversal into the immutable input workspace, never a global lookup.
        available = (
            {node.id: node for current in workspace.models for node in current.nodes}
            if workspace is not None
            else {}
        )
        pending = list(self.nodes.values())
        while pending:
            current = pending.pop()
            for binding in (*current.children, *current.references):
                for identity in binding.node_ids:
                    if identity not in self.nodes and identity in available:
                        self.budget.charge(current.id)
                        self.nodes[identity] = available[identity]
                        pending.append(available[identity])
        self.budget.collection(len(self.nodes), model.id)

    def sequence(self, value: QueryValue, identity: str) -> tuple[QueryValue, ...]:
        if not isinstance(value, tuple):
            raise LanguageEvaluationError("LANGUAGE_TYPE", "Expected a collection", identity)
        self.budget.collection(len(value), identity)
        return value

    @staticmethod
    def boolean(value: QueryValue, identity: str) -> bool:
        if type(value) is not bool:
            raise LanguageEvaluationError("LANGUAGE_TYPE", "Expected a Boolean value", identity)
        return value

    @staticmethod
    def node(value: QueryValue, identity: str) -> IntentionalNode:
        if not isinstance(value, IntentionalNode):
            raise LanguageEvaluationError("LANGUAGE_TYPE", "Expected one domain object", identity)
        return value

    def evaluate(
        self, query: lang.Query, bindings: Mapping[str, QueryValue], depth: int = 0
    ) -> QueryValue:
        self.budget.charge(query.id)
        if depth > 64:
            raise LanguageEvaluationError(
                "LANGUAGE_DEPTH", "Query nesting exceeded 64 levels", query.id
            )

        def evaluate(value: lang.Query) -> QueryValue:
            return self.evaluate(value, bindings, depth + 1)

        if isinstance(query, lang.QueryHole):
            raise LanguageEvaluationError("LANGUAGE_HOLE", query.label, query.id)
        if isinstance(query, lang.QueryLiteral):
            if isinstance(query.value, float) and not math.isfinite(query.value):
                raise LanguageEvaluationError(
                    "LANGUAGE_LITERAL", "Numeric literals must be finite", query.id
                )
            if isinstance(query.value, str) and len(query.value) > self.budget.max_text:
                raise LanguageEvaluationError(
                    "LANGUAGE_BUDGET", "Text literal exceeded its size budget", query.id
                )
            return query.value
        if isinstance(query, lang.QueryVariable):
            if query.binding_id not in bindings:
                raise LanguageEvaluationError(
                    "LANGUAGE_BINDING", "Unbound query identity", query.id
                )
            return bindings[query.binding_id]
        if isinstance(query, lang.QueryNodes):
            self.budget.charge(query.id, len(self.model.nodes))
            roots = set(self.model.roots)
            result = tuple(
                node
                for node in sorted(self.model.nodes, key=lambda node: node.id)
                if node.concept_id == query.concept_id
                and (not query.roots_only or node.id in roots)
            )
            self.budget.collection(len(result), query.id)
            return result
        if isinstance(query, (lang.QueryProperty, lang.QueryRole, lang.QueryIdentity)):
            source = self.node(evaluate(query.source), query.id)
            if isinstance(query, lang.QueryIdentity):
                return source.id
            if isinstance(query, lang.QueryProperty):
                property_value = source.property(query.property_id)
                if isinstance(property_value, str) and len(property_value) > self.budget.max_text:
                    raise LanguageEvaluationError(
                        "LANGUAGE_BUDGET", "Property text exceeded its size budget", query.id
                    )
                return property_value
            concept = self.concepts.get(source.concept_id)
            role = concept.role(query.role_id) if concept else None
            if role is None:
                raise LanguageEvaluationError(
                    "LANGUAGE_ROLE", "Query role is absent from its source concept", query.id
                )
            assert concept is not None
            identifiers = (
                source.child_ids(role.id)
                if role in concept.containment_roles
                else source.reference_ids(role.id)
            )
            if not role.ordered:
                identifiers = tuple(sorted(identifiers))
            self.budget.collection(len(identifiers), query.id)
            self.budget.charge(query.id, len(identifiers))
            if any(identity not in self.nodes for identity in identifiers):
                raise LanguageEvaluationError(
                    "LANGUAGE_SCOPE",
                    "Query references must resolve in the supplied input workspace",
                    query.id,
                )
            return tuple(self.nodes[identity] for identity in identifiers)
        if isinstance(query, lang.QueryTuple):
            self.budget.collection(len(query.items), query.id)
            return tuple(evaluate(item) for item in query.items)
        if isinstance(query, lang.QueryUnary):
            operand = evaluate(query.operand)
            if query.operator is lang.QueryUnaryOperator.NOT:
                return not self.boolean(operand, query.id)
            sequence = self.sequence(operand, query.id)
            if query.operator is lang.QueryUnaryOperator.COUNT:
                return len(sequence)
            if query.operator is lang.QueryUnaryOperator.FIRST:
                if not sequence:
                    raise LanguageEvaluationError(
                        "LANGUAGE_EMPTY", "First requires a nonempty collection", query.id
                    )
                return sequence[0]
            raise LanguageEvaluationError("LANGUAGE_OPERATOR", "Unknown query operator", query.id)
        if isinstance(query, lang.QueryBinary):
            left = evaluate(query.left)
            if query.operator is lang.QueryBinaryOperator.AND:
                return self.boolean(left, query.id) and self.boolean(
                    evaluate(query.right), query.id
                )
            if query.operator is lang.QueryBinaryOperator.OR:
                return self.boolean(left, query.id) or self.boolean(evaluate(query.right), query.id)
            right = evaluate(query.right)
            if query.operator in {
                lang.QueryBinaryOperator.EQUAL,
                lang.QueryBinaryOperator.NOT_EQUAL,
            }:
                equal = _comparison_key(left) == _comparison_key(right)
                return equal if query.operator is lang.QueryBinaryOperator.EQUAL else not equal
            if query.operator is lang.QueryBinaryOperator.IN:
                members = self.sequence(right, query.id)
                self.budget.charge(query.id, len(members))
                return any(_comparison_key(left) == _comparison_key(item) for item in members)
            if query.operator is lang.QueryBinaryOperator.ADD:
                if isinstance(left, str) and isinstance(right, str):
                    if len(left) + len(right) > self.budget.max_text:
                        raise LanguageEvaluationError(
                            "LANGUAGE_BUDGET",
                            "Text concatenation exceeded its size budget",
                            query.id,
                        )
                    return left + right
                if isinstance(left, tuple) and isinstance(right, tuple):
                    self.budget.collection(len(left) + len(right), query.id)
                    return left + right
                if type(left) in {int, float} and type(right) in {int, float}:
                    assert isinstance(left, (int, float)) and isinstance(right, (int, float))
                    added = left + right
                    if isinstance(added, float) and not math.isfinite(added):
                        raise LanguageEvaluationError(
                            "LANGUAGE_NUMBER",
                            "Query arithmetic produced a nonfinite value",
                            query.id,
                        )
                    return added
                raise LanguageEvaluationError(
                    "LANGUAGE_TYPE", "Addition requires compatible values", query.id
                )
            if isinstance(left, str) and isinstance(right, str):
                comparison = (left > right) - (left < right)
            elif type(left) in {int, float} and type(right) in {int, float}:
                assert isinstance(left, (int, float)) and isinstance(right, (int, float))
                comparison = (left > right) - (left < right)
            else:
                raise LanguageEvaluationError(
                    "LANGUAGE_TYPE", "Ordered comparison requires numbers or strings", query.id
                )
            return {
                lang.QueryBinaryOperator.LESS: comparison < 0,
                lang.QueryBinaryOperator.LESS_EQUAL: comparison <= 0,
                lang.QueryBinaryOperator.GREATER: comparison > 0,
                lang.QueryBinaryOperator.GREATER_EQUAL: comparison >= 0,
            }[query.operator]
        if isinstance(query, (lang.QueryMap, lang.QueryFilter, lang.QueryAll, lang.QueryUnique)):
            collection = self.sequence(evaluate(query.collection), query.id)
            output: list[QueryValue] = []
            keys: set[object] = set()
            for item in collection:
                self.budget.charge(query.id)
                nested = {**bindings, query.binding_id: item}
                if isinstance(query, lang.QueryMap):
                    output.append(self.evaluate(query.value, nested, depth + 1))
                elif isinstance(query, lang.QueryUnique):
                    key = _comparison_key(self.evaluate(query.key, nested, depth + 1))
                    if key in keys:
                        return False
                    keys.add(key)
                else:
                    accepted = self.boolean(
                        self.evaluate(query.predicate, nested, depth + 1), query.id
                    )
                    if isinstance(query, lang.QueryAll) and not accepted:
                        return False
                    if accepted:
                        output.append(item)
            return True if isinstance(query, (lang.QueryUnique, lang.QueryAll)) else tuple(output)
        raise LanguageEvaluationError("LANGUAGE_QUERY", "Unsupported query node", query.id)


def _comparison_key(value: QueryValue) -> object:
    if isinstance(value, IntentionalNode):
        return ("node", value.id)
    if isinstance(value, tuple):
        return ("tuple", tuple(_comparison_key(item) for item in value))
    if type(value) in {int, float}:
        return ("number", value)
    return (type(value).__name__, value)


def evaluate_query(
    query: lang.Query,
    schema: DomainSchema,
    model: DomainModel,
    bindings: Mapping[str, QueryValue] | None = None,
    *,
    budget: EvaluationBudget | None = None,
    workspace: DomainWorkspace | None = None,
) -> QueryValue:
    return _Queries(schema, model, budget or EvaluationBudget(), workspace).evaluate(
        query, bindings or {}
    )


def validate_authored_model(
    language: lang.AuthoredDomainLanguage,
    schema: DomainSchema,
    model: DomainModel,
    *,
    schemas: tuple[DomainSchema, ...] = (),
    workspace: DomainWorkspace | None = None,
) -> tuple[DomainIssue, ...]:
    definition_issues = validate_authored_language(language, schema, schemas=schemas)
    if definition_issues:
        return definition_issues
    if (model.schema_id, model.schema_version) != (schema.id, schema.version):
        return (
            DomainIssue(
                "LANGUAGE_SCHEMA", "Validator source schema does not match its model", model.id
            ),
        )
    queries = _Queries(schema, model, EvaluationBudget(), workspace)
    issues: list[DomainIssue] = []
    try:
        for validator in language.validators:
            for node in sorted(model.nodes, key=lambda node: node.id):
                if node.concept_id != validator.concept_id:
                    continue
                accepted = queries.boolean(
                    queries.evaluate(validator.predicate, {validator.binding_id: node}),
                    validator.id,
                )
                if not accepted:
                    issues.append(
                        DomainIssue(
                            validator.code,
                            validator.message,
                            node.id,
                            validator.id,
                            incomplete=True,
                        )
                    )
    except LanguageEvaluationError as exc:
        issues.append(DomainIssue(exc.code, str(exc), exc.object_id, incomplete=True))
    return tuple(issues)


_BINARY = {
    lang.RuntimeBinaryOperator.ADD: "+",
    lang.RuntimeBinaryOperator.SUBTRACT: "-",
    lang.RuntimeBinaryOperator.MULTIPLY: "*",
    lang.RuntimeBinaryOperator.DIVIDE: "/",
    lang.RuntimeBinaryOperator.MODULO: "%",
}
_COMPARE = {
    lang.RuntimeBinaryOperator.EQUAL: "Eq",
    lang.RuntimeBinaryOperator.NOT_EQUAL: "NotEq",
    lang.RuntimeBinaryOperator.LESS: "Lt",
    lang.RuntimeBinaryOperator.LESS_EQUAL: "LtE",
    lang.RuntimeBinaryOperator.GREATER: "Gt",
    lang.RuntimeBinaryOperator.GREATER_EQUAL: "GtE",
    lang.RuntimeBinaryOperator.IN: "In",
}


class _ProgramBuilder:
    def __init__(
        self,
        schema: DomainSchema,
        snapshot: TransformationInput,
        recipe: lang.AuthoredTransformation,
    ) -> None:
        self.snapshot, self.recipe = snapshot, recipe
        self.budget = EvaluationBudget()
        assert isinstance(snapshot.value, DomainModel)
        self.queries = _Queries(
            schema, snapshot.value, self.budget, snapshot.project.domain_workspace
        )
        self.origins: dict[str, tuple[str, ...]] = {}
        self.symbols: dict[str, tuple[str, str]] = {}
        self.declarations: dict[str, str] = {}

    def identity(
        self, template_id: str, role: str, context: tuple[str, ...], origins: tuple[str, ...]
    ) -> str:
        result = derived_id(
            self.recipe.definition.key,
            json.dumps(context, separators=(",", ":")),
            f"{template_id}:{role}",
        )
        if result in self.origins:
            raise LanguageEvaluationError(
                "LANGUAGE_GENERATED_ID",
                "Template expansion generated the same object twice",
                template_id,
            )
        self.budget.generated_nodes -= 1
        if self.budget.generated_nodes < 0:
            raise LanguageEvaluationError(
                "LANGUAGE_BUDGET",
                "Template expansion exceeded its generated-node budget",
                template_id,
            )
        self.origins[result] = tuple(sorted(set(origins)))
        return result

    def literal(
        self,
        value: QueryValue,
        owner: str,
        role: str,
        context: tuple[str, ...],
        origins: tuple[str, ...],
    ) -> ExpressionNode:
        identity = self.identity(owner, role, context, origins)
        if isinstance(value, tuple):
            self.budget.collection(len(value), owner)
            return CompositeExpression(
                identity,
                "Tuple",
                (
                    ExpressionField(
                        "elts",
                        ExpressionList(
                            tuple(
                                self.literal(item, owner, f"{role}:item:{index}", context, origins)
                                for index, item in enumerate(value)
                            )
                        ),
                    ),
                    ExpressionField(
                        "ctx",
                        CompositeExpression(
                            self.identity(owner, f"{role}:context", context, origins), "Load"
                        ),
                    ),
                ),
            )
        if value is None:
            scalar = ExpressionScalar("none", "")
        elif type(value) is bool:
            scalar = ExpressionScalar("bool", "1" if value else "0")
        elif type(value) is int:
            scalar = ExpressionScalar("int", str(value))
        elif type(value) is float:
            assert isinstance(value, float)
            if not math.isfinite(value):
                raise LanguageEvaluationError(
                    "LANGUAGE_LITERAL", "Runtime literal must be finite", owner
                )
            scalar = ExpressionScalar("float", value.hex())
        elif isinstance(value, str):
            scalar = ExpressionScalar("str", value)
        else:
            raise LanguageEvaluationError(
                "LANGUAGE_LITERAL",
                "Select a scalar property or identity before emitting a runtime literal",
                owner,
            )
        return LiteralExpression(identity, scalar)

    def runtime(
        self,
        value: lang.RuntimeExpression,
        environment: Mapping[str, QueryValue],
        context: tuple[str, ...],
        origins: tuple[str, ...],
        role: str,
    ) -> ExpressionNode:
        self.budget.charge(value.id)
        if isinstance(value, lang.RuntimeLiteral):
            return self.literal(
                self.queries.evaluate(value.query, environment), value.id, role, context, origins
            )
        identity = self.identity(value.id, role, context, origins)
        if isinstance(value, lang.RuntimeVariable):
            symbol_id, name = self.symbols[value.symbol_id]
            return SymbolReferenceExpression(identity, name, symbol_id)
        if isinstance(value, lang.RuntimeBinary):
            left = self.runtime(value.left, environment, context, origins, role + ":left")
            right = self.runtime(value.right, environment, context, origins, role + ":right")
            if value.operator in _BINARY:
                return BinaryExpression(identity, left, _BINARY[value.operator], right)
            operator_id = self.identity(value.id, role + ":operator", context, origins)
            if value.operator in {lang.RuntimeBinaryOperator.AND, lang.RuntimeBinaryOperator.OR}:
                operator = "And" if value.operator is lang.RuntimeBinaryOperator.AND else "Or"
                return CompositeExpression(
                    identity,
                    "BoolOp",
                    (
                        ExpressionField("op", CompositeExpression(operator_id, operator)),
                        ExpressionField("values", ExpressionList((left, right))),
                    ),
                )
            return CompositeExpression(
                identity,
                "Compare",
                (
                    ExpressionField("left", left),
                    ExpressionField(
                        "ops",
                        ExpressionList(
                            (CompositeExpression(operator_id, _COMPARE[value.operator]),)
                        ),
                    ),
                    ExpressionField("comparators", ExpressionList((right,))),
                ),
            )
        if isinstance(value, lang.RuntimeCall):
            return CallExpression(
                identity,
                SymbolReferenceExpression(
                    self.identity(value.id, role + ":builtin", context, origins),
                    value.builtin.value,
                    None,
                ),
                tuple(
                    self.runtime(
                        argument, environment, context, origins, f"{role}:argument:{index}"
                    )
                    for index, argument in enumerate(value.arguments)
                ),
            )
        raise LanguageEvaluationError(
            "LANGUAGE_HOLE", "Complete the runtime expression before building", value.id
        )

    def expression(
        self,
        owner: str,
        field: str,
        value: lang.RuntimeExpression,
        environment: Mapping[str, QueryValue],
        context: tuple[str, ...],
        origins: tuple[str, ...],
        role: ExpressionRole = ExpressionRole.VALUE,
    ) -> ProgramExpression:
        identity = self.identity(owner, f"expression:{field}", context, origins)
        return ProgramExpression(
            identity, role, self.runtime(value, environment, context, origins, field)
        )

    def fixed_expression(
        self,
        owner: str,
        field: str,
        value: QueryValue,
        context: tuple[str, ...],
        origins: tuple[str, ...],
        role: ExpressionRole = ExpressionRole.VALUE,
    ) -> ProgramExpression:
        return ProgramExpression(
            self.identity(owner, f"expression:{field}", context, origins),
            role,
            self.literal(value, owner, f"fixed:{field}", context, origins),
        )

    def target(
        self, owner: str, symbol: str, context: tuple[str, ...], origins: tuple[str, ...]
    ) -> ProgramExpression:
        symbol_id, name = self.symbols[symbol]
        return ProgramExpression(
            self.identity(owner, "expression:target", context, origins),
            ExpressionRole.TARGET,
            SymbolReferenceExpression(
                self.identity(owner, "target", context, origins),
                name,
                symbol_id,
                ExpressionContext.STORE,
            ),
        )

    def emit(
        self,
        body: tuple[lang.StatementTemplate, ...],
        environment: Mapping[str, QueryValue],
        context: tuple[str, ...],
        inherited: tuple[str, ...],
    ) -> tuple[ProgramStatement, ...]:
        statements: list[ProgramStatement] = []
        for template in body:
            self.budget.charge(template.id)
            if isinstance(template, lang.TemplateExpand):
                values = self.queries.sequence(
                    self.queries.evaluate(template.collection, environment), template.id
                )
                for value in values:
                    node = self.queries.node(value, template.id)
                    statements.extend(
                        self.emit(
                            template.body,
                            {**environment, template.binding_id: node},
                            (*context, template.id, node.id),
                            (*inherited, node.id),
                        )
                    )
                continue
            if isinstance(template, lang.TemplateWhen):
                if self.queries.boolean(
                    self.queries.evaluate(template.predicate, environment), template.id
                ):
                    statements.extend(self.emit(template.body, environment, context, inherited))
                continue
            if isinstance(template, lang.TemplateLet):
                statements.extend(
                    self.emit(
                        template.body,
                        {
                            **environment,
                            template.binding_id: self.queries.evaluate(template.value, environment),
                        },
                        context,
                        inherited,
                    )
                )
                continue
            if isinstance(template, lang.TemplateHole):
                raise LanguageEvaluationError("LANGUAGE_HOLE", template.label, template.id)
            origins = list(inherited)
            for source in template.origins:
                resolved = self.queries.evaluate(source, environment)
                for value in resolved if isinstance(resolved, tuple) else (resolved,):
                    origins.append(self.queries.node(value, source.id).id)
            active = tuple(sorted(set(origins)))
            owner = self.identity(template.id, "statement", context, active)
            if isinstance(template, lang.TemplateAssignment):
                self.declarations.setdefault(template.symbol_id, owner)
                statements.append(
                    ProgramAssignment(
                        owner,
                        self.target(template.id, template.symbol_id, context, active),
                        self.expression(
                            template.id, "value", template.value, environment, context, active
                        ),
                        written_symbol_ids=(self.symbols[template.symbol_id][0],),
                    )
                )
            elif isinstance(template, lang.TemplateOutput):
                statements.append(
                    ProgramOutput(
                        owner,
                        self.expression(
                            template.id, "output", template.value, environment, context, active
                        ),
                    )
                )
            elif isinstance(template, lang.TemplateIf):
                statements.append(
                    ProgramIf(
                        owner,
                        self.expression(
                            template.id,
                            "condition",
                            template.condition,
                            environment,
                            context,
                            active,
                            ExpressionRole.CONDITION,
                        ),
                        ProgramSequence(
                            self.identity(template.id, "true-body", context, active),
                            self.emit(template.true_body, environment, context, active),
                        ),
                        ProgramSequence(
                            self.identity(template.id, "false-body", context, active),
                            self.emit(template.false_body, environment, context, active),
                        ),
                    )
                )
            elif isinstance(template, lang.TemplateFor):
                self.declarations.setdefault(template.symbol_id, owner)
                statements.append(
                    ProgramLoop(
                        owner,
                        LoopKind.FOR,
                        ProgramSequence(
                            self.identity(template.id, "loop-body", context, active),
                            self.emit(template.body, environment, context, active),
                        ),
                        ProgramSequence(self.identity(template.id, "loop-else", context, active)),
                        self.fixed_expression(
                            template.id,
                            "condition",
                            True,
                            context,
                            active,
                            ExpressionRole.CONDITION,
                        ),
                        self.target(template.id, template.symbol_id, context, active),
                        self.expression(
                            template.id, "iterable", template.iterable, environment, context, active
                        ),
                        self.fixed_expression(template.id, "children", None, context, active),
                        self.fixed_expression(template.id, "delay", 0, context, active),
                    )
                )
            elif isinstance(template, lang.TemplateTransfer):
                expression = (
                    self.expression(
                        template.id, "transfer", template.value, environment, context, active
                    )
                    if template.value is not None
                    else None
                )
                statements.append(ProgramTransfer(owner, template.kind, expression, None))
        return tuple(statements)

    def build(self) -> TransformationResult:
        functions: list[ProgramFunction] = []
        symbols: list[ProgramSymbol] = []
        entries: list[str] = []
        for template in self.recipe.functions:
            for source in self.queries.sequence(
                self.queries.evaluate(template.source, {}), template.id
            ):
                node = self.queries.node(source, template.id)
                environment: dict[str, QueryValue] = {template.binding_id: node}
                context, origins = (node.id,), (node.id,)
                function_id = self.identity(template.id, "function", context, origins)
                function_symbol = self.identity(template.id, "function-symbol", context, origins)
                name = f"{template.identifier_prefix}_{function_id.rsplit(':', 1)[-1][:12]}"
                declared_symbols: tuple[lang.TemplateParameter | lang.TemplateSymbol, ...] = (
                    *template.parameters,
                    *template.symbols,
                )
                self.symbols = {
                    symbol.id: (self.identity(symbol.id, "symbol", context, origins), symbol.name)
                    for symbol in declared_symbols
                }
                self.declarations = {}
                parameters: list[ProgramParameter] = []
                for parameter in template.parameters:
                    parameter_id = self.identity(parameter.id, "parameter", context, origins)
                    default = (
                        self.expression(
                            parameter.id,
                            "default",
                            parameter.default,
                            environment,
                            context,
                            origins,
                            ExpressionRole.DEFAULT,
                        )
                        if parameter.default
                        else None
                    )
                    parameters.append(
                        ProgramParameter(
                            parameter_id,
                            self.symbols[parameter.id][0],
                            parameter.name,
                            default=default,
                        )
                    )
                    symbols.append(
                        ProgramSymbol(
                            self.symbols[parameter.id][0],
                            parameter.name,
                            ProgramSymbolKind.PARAMETER,
                            function_id,
                            parameter_id,
                        )
                    )
                body = ProgramSequence(
                    self.identity(template.id, "body", context, origins),
                    self.emit(template.body, environment, context, origins),
                )
                display = (
                    self.queries.evaluate(template.display_name, environment)
                    if template.display_name
                    else name
                )
                if not isinstance(display, str):
                    raise LanguageEvaluationError(
                        "LANGUAGE_TYPE", "Function display name must be text", template.id
                    )
                functions.append(
                    ProgramFunction(
                        function_id,
                        function_symbol,
                        name,
                        display,
                        CallableKind.SYNC,
                        tuple(parameters),
                        None,
                        (),
                        "Generated from a project-authored domain transformation.",
                        None,
                        body,
                    )
                )
                symbols.append(
                    ProgramSymbol(
                        function_symbol, name, ProgramSymbolKind.FUNCTION, function_id, function_id
                    )
                )
                symbols.extend(
                    ProgramSymbol(
                        self.symbols[symbol.id][0],
                        symbol.name,
                        ProgramSymbolKind.LOCAL,
                        function_id,
                        self.declarations.get(symbol.id, function_id),
                    )
                    for symbol in template.symbols
                )
                if template.entrypoint:
                    entries.append(function_id)
        assert isinstance(self.snapshot.value, DomainModel)
        module_id = self.identity(
            self.recipe.definition.id,
            "module",
            (self.snapshot.value.id,),
            self.snapshot.value.roots,
        )
        program = ProgramModel(
            tuple(functions),
            tuple(symbols),
            (
                ProgramModule(
                    module_id,
                    "main",
                    tuple(ProgramFunctionReference(item.id) for item in functions),
                ),
            ),
            package=self.snapshot.project.program_model.package,
        )
        return TransformationResult(
            self.recipe.definition.target,
            program,
            OriginMap(
                self.snapshot.project.id,
                self.snapshot.project.revision,
                tuple(
                    OriginLink(identity, sources)
                    for identity, sources in sorted(self.origins.items())
                ),
            ),
            tuple(entries),
        )


class _DomainBuilder:
    """Allocate target identities, then resolve their roles without ordering dependencies."""

    def __init__(
        self,
        source: DomainSchema,
        target: DomainSchema,
        snapshot: TransformationInput,
        recipe: lang.AuthoredTransformation,
    ) -> None:
        assert isinstance(snapshot.value, DomainModel) and recipe.domain is not None
        self.target, self.snapshot, self.recipe = target, snapshot, recipe
        self.template, self.model = recipe.domain, snapshot.value
        self.budget = EvaluationBudget()
        self.queries = _Queries(source, self.model, self.budget, snapshot.project.domain_workspace)

    def build(self) -> TransformationResult:
        allocated: dict[tuple[str, str], str] = {}
        selected: list[tuple[lang.DomainNodeTemplate, IntentionalNode, str]] = []
        for template in self.template.nodes:
            values = self.queries.sequence(self.queries.evaluate(template.source, {}), template.id)
            for value in values:
                self.budget.charge(template.id)
                source = self.queries.node(value, template.id)
                key = (template.id, source.id)
                if key in allocated:
                    raise LanguageEvaluationError(
                        "LANGUAGE_GENERATED_ID",
                        "Node template selected the same source twice",
                        template.id,
                    )
                self.budget.generated_nodes -= 1
                if self.budget.generated_nodes < 0:
                    raise LanguageEvaluationError(
                        "LANGUAGE_BUDGET", "Domain output exceeds node budget", template.id
                    )
                identity = derived_id(
                    self.recipe.definition.key,
                    json.dumps((self.model.id, source.id), separators=(",", ":")),
                    template.id,
                )
                allocated[key] = identity
                selected.append((template, source, identity))
        nodes: list[IntentionalNode] = []
        roots: list[str] = []
        links: list[OriginLink] = []
        for template, source, identity in selected:
            environment: dict[str, QueryValue] = {template.binding_id: source}
            concept = self.target.concept(template.concept_id)
            assert concept is not None
            properties = {
                item.id: item.default for item in concept.properties if item.default is not None
            }
            for assignment in template.properties:
                value = self.queries.evaluate(assignment.value, environment)
                if value is None:
                    properties.pop(assignment.property_id, None)
                elif isinstance(value, (IntentionalNode, tuple)):
                    raise LanguageEvaluationError(
                        "LANGUAGE_TARGET_PROPERTY",
                        "Domain properties require bounded canonical values",
                        assignment.id,
                    )
                else:
                    validate_canonical_value(value)
                    properties[assignment.property_id] = value

            def bindings(
                values: tuple[lang.DomainRoleTemplate, ...], scope: dict[str, QueryValue]
            ) -> tuple[RoleBinding, ...]:
                result: list[RoleBinding] = []
                for binding in values:
                    target_ids: list[str] = []
                    queried = self.queries.sequence(
                        self.queries.evaluate(binding.sources, scope), binding.id
                    )
                    for value in queried:
                        self.budget.charge(binding.id)
                        selected_source = self.queries.node(value, binding.id)
                        target_id = allocated.get((binding.target_template_id, selected_source.id))
                        if target_id is None:
                            raise LanguageEvaluationError(
                                "LANGUAGE_TARGET_MISSING",
                                "Role references an object not emitted by its target template",
                                binding.id,
                            )
                        target_ids.append(target_id)
                    result.append(RoleBinding(binding.role_id, tuple(target_ids)))
                return tuple(result)

            nodes.append(
                IntentionalNode(
                    identity,
                    template.concept_id,
                    tuple(
                        PropertyValue(item.id, properties[item.id])
                        for item in concept.properties
                        if item.id in properties
                    ),
                    bindings(template.children, environment),
                    bindings(template.references, environment),
                )
            )
            if template.root:
                roots.append(identity)
            sources = {source.id}
            for origin in template.origins:
                resolved = self.queries.evaluate(origin, environment)
                sources.update(
                    self.queries.node(value, origin.id).id
                    for value in (resolved if isinstance(resolved, tuple) else (resolved,))
                )
            links.append(OriginLink(identity, tuple(sorted(sources))))
        model_id = derived_id(self.recipe.definition.key, self.model.id, self.template.id)
        model = DomainModel(
            model_id,
            self.target.id,
            self.target.version,
            tuple(roots),
            tuple(nodes),
            self.model.title,
        )
        findings = validate_domain_workspace(
            DomainWorkspace(self.snapshot.project.domain_workspace.schemas, (model,))
        )
        if findings:
            first = findings[0]
            raise LanguageEvaluationError(
                first.code, f"Invalid derived domain: {first.message}", first.object_id
            )
        links.append(OriginLink(model_id, (self.model.id,)))
        return TransformationResult(
            self.recipe.definition.target,
            model,
            OriginMap(
                self.snapshot.project.id,
                self.snapshot.project.revision,
                tuple(sorted(links, key=lambda item: item.generated_id)),
            ),
        )


def compile_authored_transformation(
    language: lang.AuthoredDomainLanguage,
    schema: DomainSchema,
    recipe: lang.AuthoredTransformation,
    *,
    schemas: tuple[DomainSchema, ...] = (),
) -> RegisteredTransformation:
    issues = validate_authored_language(language, schema, schemas=schemas)
    if issues:
        issue = issues[0]
        raise LanguageEvaluationError(issue.code, issue.message, issue.object_id)
    if recipe not in language.transformations:
        raise LanguageEvaluationError(
            "LANGUAGE_RECIPE", "Transformation is not owned by this language", recipe.definition.id
        )

    def transform(snapshot: TransformationInput) -> TransformationResult:
        if not isinstance(snapshot.value, DomainModel) or (
            snapshot.value.schema_id,
            snapshot.value.schema_version,
        ) != (schema.id, schema.version):
            raise LanguageEvaluationError(
                "LANGUAGE_SCHEMA",
                "Transformation received another schema's model",
                snapshot.model.id,
            )
        if snapshot.project.domain_workspace.schema(schema.id) != schema:
            raise LanguageEvaluationError(
                "LANGUAGE_SOURCE",
                "Templates require their unchanged source schema definition",
                snapshot.model.id,
            )
        diagnostics = validate_authored_model(
            language,
            schema,
            snapshot.value,
            schemas=schemas,
            workspace=snapshot.project.domain_workspace,
        )
        if diagnostics:
            issue = diagnostics[0]
            raise LanguageEvaluationError(issue.code, issue.message, issue.object_id)
        if recipe.domain is not None:
            target = next(
                item
                for item in (*schemas, schema)
                if (item.id, item.version)
                == (recipe.domain.target_schema_id, recipe.domain.target_schema_version)
            )
            if snapshot.project.domain_workspace.schema(target.id) != target:
                raise LanguageEvaluationError(
                    "LANGUAGE_TARGET_SCHEMA", "Target schema changed after compilation", target.id
                )
            return _DomainBuilder(schema, target, snapshot, recipe).build()
        return _ProgramBuilder(schema, snapshot, recipe).build()

    return RegisteredTransformation(
        recipe.definition,
        transform,
        schema_id=schema.id,
        schema_version=schema.version,
        target_schema_id=recipe.domain.target_schema_id if recipe.domain is not None else None,
        target_schema_version=recipe.domain.target_schema_version
        if recipe.domain is not None
        else None,
    )
