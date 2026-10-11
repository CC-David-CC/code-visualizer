"""Schema-aware checks for inert authored language values; no interpretation or I/O."""

from __future__ import annotations

import keyword
import math
from dataclasses import dataclass, fields, is_dataclass

from code_visualizer.domain import language as lang
from code_visualizer.domain.intentional import DomainIssue, DomainSchema, ValueKind
from code_visualizer.domain.language_structure import validate_language_slots
from code_visualizer.domain.notation import NotationField
from code_visualizer.domain.program_kinds import TransferKind
from code_visualizer.domain.transformation import PROGRAM_REPRESENTATION, Representation

MAX_LANGUAGE_NODES = 10_000
MAX_LANGUAGE_DEPTH = 64


@dataclass(frozen=True, slots=True)
class QueryType:
    kind: str
    concept_ids: tuple[str, ...] = ()
    element: QueryType | None = None


UNKNOWN = QueryType("unknown")
BOOLEAN = QueryType("boolean")
STRING = QueryType("string")
NUMBER = QueryType("number")


def language_structure_issues(language: lang.AuthoredDomainLanguage) -> tuple[DomainIssue, ...]:
    """Bound recursive interpretation and reject aliasing of authored syntax identities."""

    try:
        validate_language_slots(language)
    except ValueError as exc:
        return (DomainIssue("DOMAIN_LANGUAGE_STRUCTURE", str(exc), language.id),)
    pending: list[tuple[object, int]] = [(language, 0)]
    identities: set[str] = set()
    count = 0
    issues: list[DomainIssue] = []
    while pending:
        value, depth = pending.pop()
        if depth > MAX_LANGUAGE_DEPTH:
            return (DomainIssue("LANGUAGE_DEPTH", "Authoring tree exceeds 64 levels", language.id),)
        if isinstance(value, tuple):
            pending.extend((item, depth + 1) for item in value)
        elif is_dataclass(value) and not isinstance(value, type):
            count += 1
            if count > MAX_LANGUAGE_NODES:
                return (
                    DomainIssue("LANGUAGE_SIZE", "Authoring tree exceeds 10000 nodes", language.id),
                )
            identity = getattr(value, "id", None)
            # Column IDs are local to an existing NotationDefinition contract.
            if isinstance(identity, str) and type(value).__module__ == lang.__name__:
                if not identity or identity in identities:
                    issues.append(
                        DomainIssue(
                            "LANGUAGE_ID",
                            "Language syntax IDs must be unique and nonempty",
                            identity or language.id,
                        )
                    )
                identities.add(identity)
            pending.extend((getattr(value, item.name), depth + 1) for item in fields(value))
    return tuple(issues)


class LanguageTypeChecker:
    def __init__(self, schema: DomainSchema, schemas: tuple[DomainSchema, ...] = ()) -> None:
        self.schema = schema
        self.concepts = {
            concept.id: concept for current in (*schemas, schema) for concept in current.concepts
        }
        self.issues: list[DomainIssue] = []

    def issue(self, code: str, message: str, identity: str, *, incomplete: bool = False) -> None:
        self.issues.append(DomainIssue(code, message, identity, incomplete=incomplete))

    def require(self, actual: QueryType, expected: str, identity: str) -> None:
        if actual.kind not in {expected, "unknown"}:
            self.issue("LANGUAGE_TYPE", f"Expected {expected}, found {actual.kind}", identity)

    def bind(
        self, environment: dict[str, QueryType], identity: str, value: QueryType, owner: str
    ) -> dict[str, QueryType]:
        if not identity or identity in environment:
            self.issue(
                "LANGUAGE_BINDING",
                "Binding IDs must be nonempty and may not shadow another binding",
                owner,
            )
        return {**environment, identity: value}

    def query(self, value: lang.Query, environment: dict[str, QueryType]) -> QueryType:
        if isinstance(value, lang.QueryHole):
            self.issue("LANGUAGE_HOLE", value.label, value.id, incomplete=True)
            return UNKNOWN
        if isinstance(value, lang.QueryLiteral):
            literal = value.value
            if literal is None:
                return QueryType("null")
            if type(literal) is bool:
                return BOOLEAN
            if type(literal) in {int, float}:
                if isinstance(literal, float) and not math.isfinite(literal):
                    self.issue("LANGUAGE_LITERAL", "Numeric literals must be finite", value.id)
                return NUMBER
            if isinstance(literal, str):
                if len(literal) > 1_000_000:
                    self.issue(
                        "LANGUAGE_LITERAL", "Literal exceeds one million characters", value.id
                    )
                return STRING
            self.issue("LANGUAGE_LITERAL", "Only scalar literal values are supported", value.id)
            return UNKNOWN
        if isinstance(value, lang.QueryVariable):
            if value.binding_id not in environment:
                self.issue("LANGUAGE_BINDING", "Query refers to an unbound identity", value.id)
            return environment.get(value.binding_id, UNKNOWN)
        if isinstance(value, lang.QueryNodes):
            if self.schema.concept(value.concept_id) is None:
                self.issue(
                    "LANGUAGE_CONCEPT", "Query names a concept outside its source schema", value.id
                )
            return QueryType("sequence", element=QueryType("node", (value.concept_id,)))
        if isinstance(value, (lang.QueryRole, lang.QueryProperty, lang.QueryIdentity)):
            source = self.query(value.source, environment)
            self.require(source, "node", value.id)
            if isinstance(value, lang.QueryIdentity):
                return STRING
            concepts = tuple(self.concepts.get(identity) for identity in source.concept_ids)
            if any(concept is None for concept in concepts):
                self.issue(
                    "LANGUAGE_SCOPE",
                    "Query reference target requires its schema in the input workspace",
                    value.id,
                )
            if isinstance(value, lang.QueryProperty):
                properties = tuple(
                    concept.property(value.property_id)
                    for concept in concepts
                    if concept is not None
                )
                if any(prop is None for prop in properties):
                    self.issue(
                        "LANGUAGE_PROPERTY",
                        "Property is not defined on every possible source concept",
                        value.id,
                    )
                kinds = {prop.value_kind.value for prop in properties if prop is not None}
                kinds = {"number" if item == "integer" else item for item in kinds}
                if len(kinds) > 1:
                    self.issue(
                        "LANGUAGE_TYPE",
                        "Property has incompatible types on its source concepts",
                        value.id,
                    )
                return QueryType(next(iter(kinds))) if len(kinds) == 1 else UNKNOWN
            roles = tuple(
                concept.role(value.role_id) for concept in concepts if concept is not None
            )
            if any(role is None for role in roles):
                self.issue(
                    "LANGUAGE_ROLE",
                    "Role is not defined on every possible source concept",
                    value.id,
                )
            allowed = tuple(
                sorted(
                    {
                        identity
                        for role in roles
                        if role is not None
                        for identity in role.allowed_concept_ids
                    }
                )
            )
            return QueryType("sequence", element=QueryType("node", allowed))
        if isinstance(value, lang.QueryTuple):
            types = tuple(self.query(item, environment) for item in value.items)
            element = types[0] if types and all(item == types[0] for item in types) else UNKNOWN
            return QueryType("sequence", element=element)
        if isinstance(value, lang.QueryUnary):
            operand = self.query(value.operand, environment)
            if value.operator is lang.QueryUnaryOperator.NOT:
                self.require(operand, "boolean", value.id)
                return BOOLEAN
            self.require(operand, "sequence", value.id)
            return (
                NUMBER
                if value.operator is lang.QueryUnaryOperator.COUNT
                else operand.element or UNKNOWN
            )
        if isinstance(value, lang.QueryBinary):
            left = self.query(value.left, environment)
            right = self.query(value.right, environment)
            if value.operator in {lang.QueryBinaryOperator.AND, lang.QueryBinaryOperator.OR}:
                self.require(left, "boolean", value.id)
                self.require(right, "boolean", value.id)
            elif value.operator is lang.QueryBinaryOperator.IN:
                self.require(right, "sequence", value.id)
            elif value.operator is lang.QueryBinaryOperator.ADD:
                if left.kind not in {
                    "number",
                    "string",
                    "sequence",
                    "unknown",
                } or right.kind not in {left.kind, "unknown"}:
                    self.issue(
                        "LANGUAGE_TYPE",
                        "Addition requires two numbers, strings, or sequences of the same type",
                        value.id,
                    )
                return left
            elif value.operator not in {
                lang.QueryBinaryOperator.EQUAL,
                lang.QueryBinaryOperator.NOT_EQUAL,
            }:
                if left.kind not in {"number", "string", "unknown"} or right.kind not in {
                    left.kind,
                    "unknown",
                }:
                    self.issue(
                        "LANGUAGE_TYPE",
                        "Ordered comparison requires compatible numbers or strings",
                        value.id,
                    )
            return BOOLEAN
        if isinstance(value, (lang.QueryMap, lang.QueryFilter, lang.QueryAll, lang.QueryUnique)):
            collection = self.query(value.collection, environment)
            self.require(collection, "sequence", value.id)
            bound = self.bind(
                environment, value.binding_id, collection.element or UNKNOWN, value.id
            )
            if isinstance(value, lang.QueryMap):
                return QueryType("sequence", element=self.query(value.value, bound))
            if isinstance(value, lang.QueryUnique):
                self.query(value.key, bound)
                return BOOLEAN
            self.require(self.query(value.predicate, bound), "boolean", value.id)
            return collection if isinstance(value, lang.QueryFilter) else BOOLEAN

    def runtime(
        self, value: lang.RuntimeExpression, environment: dict[str, QueryType], symbols: set[str]
    ) -> None:
        if isinstance(value, lang.RuntimeHole):
            self.issue("LANGUAGE_HOLE", value.label, value.id, incomplete=True)
        elif isinstance(value, lang.RuntimeLiteral):
            shape = self.query(value.query, environment)
            while shape.kind == "sequence" and shape.element is not None:
                shape = shape.element
            if shape.kind not in {"string", "number", "boolean", "null", "unknown"}:
                self.issue(
                    "LANGUAGE_TYPE",
                    "Python runtime literals require scalar values; lower compound "
                    "domain values through an explicit domain transformation",
                    value.id,
                )
        elif isinstance(value, lang.RuntimeVariable):
            if value.symbol_id not in symbols:
                self.issue(
                    "LANGUAGE_SYMBOL",
                    "Runtime expression refers to an undeclared template symbol",
                    value.id,
                )
        elif isinstance(value, lang.RuntimeBinary):
            self.runtime(value.left, environment, symbols)
            self.runtime(value.right, environment, symbols)
        elif isinstance(value, lang.RuntimeCall):
            if value.builtin is lang.RuntimeBuiltin.RANGE:
                valid_arity = 1 <= len(value.arguments) <= 3
            elif value.builtin in {
                lang.RuntimeBuiltin.LENGTH,
                lang.RuntimeBuiltin.STRING,
                lang.RuntimeBuiltin.VALUE_ERROR,
            }:
                valid_arity = len(value.arguments) == 1
            else:
                valid_arity = False
            if not valid_arity:
                self.issue(
                    "LANGUAGE_CALL",
                    "Built-in call has an unsupported operation or argument count",
                    value.id,
                )
            for argument in value.arguments:
                self.runtime(argument, environment, symbols)

    def statements(
        self,
        body: tuple[lang.StatementTemplate, ...],
        environment: dict[str, QueryType],
        symbols: set[str],
        *,
        loop: bool = False,
    ) -> None:
        for statement in body:
            if isinstance(statement, lang.TemplateHole):
                self.issue("LANGUAGE_HOLE", statement.label, statement.id, incomplete=True)
            elif isinstance(statement, lang.TemplateExpand):
                collection = self.query(statement.collection, environment)
                self.require(collection, "sequence", statement.id)
                self.require(collection.element or UNKNOWN, "node", statement.id)
                bound = self.bind(
                    environment, statement.binding_id, collection.element or UNKNOWN, statement.id
                )
                self.statements(statement.body, bound, symbols, loop=loop)
            elif isinstance(statement, lang.TemplateLet):
                bound = self.bind(
                    environment,
                    statement.binding_id,
                    self.query(statement.value, environment),
                    statement.id,
                )
                self.statements(statement.body, bound, symbols, loop=loop)
            elif isinstance(statement, lang.TemplateWhen):
                self.require(self.query(statement.predicate, environment), "boolean", statement.id)
                self.statements(statement.body, environment, symbols, loop=loop)
            else:
                for origin in statement.origins:
                    shape = self.query(origin, environment)
                    if shape.kind == "sequence":
                        shape = shape.element or UNKNOWN
                    self.require(shape, "node", origin.id)
                if (
                    isinstance(statement, (lang.TemplateAssignment, lang.TemplateFor))
                    and statement.symbol_id not in symbols
                ):
                    self.issue(
                        "LANGUAGE_SYMBOL",
                        "Statement target is not a declared template symbol",
                        statement.id,
                    )
                if isinstance(statement, (lang.TemplateAssignment, lang.TemplateOutput)):
                    self.runtime(statement.value, environment, symbols)
                elif isinstance(statement, lang.TemplateFor):
                    self.runtime(statement.iterable, environment, symbols)
                    self.statements(statement.body, environment, symbols, loop=True)
                elif isinstance(statement, lang.TemplateIf):
                    self.runtime(statement.condition, environment, symbols)
                    self.statements(statement.true_body, environment, symbols, loop=loop)
                    self.statements(statement.false_body, environment, symbols, loop=loop)
                elif isinstance(statement, lang.TemplateTransfer):
                    if statement.kind not in {
                        TransferKind.CONTINUE,
                        TransferKind.BREAK,
                        TransferKind.RETURN,
                        TransferKind.RAISE,
                    }:
                        self.issue(
                            "LANGUAGE_TRANSFER",
                            "This template language supports continue, break, return, and raise",
                            statement.id,
                        )
                    if statement.kind in {TransferKind.CONTINUE, TransferKind.BREAK}:
                        if not loop:
                            self.issue(
                                "LANGUAGE_CONTROL",
                                "Loop transfer requires an enclosing runtime loop",
                                statement.id,
                            )
                        if statement.value is not None:
                            self.issue(
                                "LANGUAGE_CONTROL",
                                "Loop transfer cannot carry a value",
                                statement.id,
                            )
                    if statement.kind is TransferKind.RAISE and statement.value is None:
                        self.issue(
                            "LANGUAGE_CONTROL", "Raise requires an exception value", statement.id
                        )
                    if statement.value is not None:
                        self.runtime(statement.value, environment, symbols)

    def notation_field(
        self, field: NotationField, concept_ids: tuple[str, ...], identity: str
    ) -> None:
        current = concept_ids
        for role_id in field.reference_role_ids:
            roles = tuple(
                next((role for role in concept.reference_roles if role.id == role_id), None)
                if (concept := self.schema.concept(concept_id))
                else None
                for concept_id in current
            )
            if not roles or any(role is None for role in roles):
                self.issue(
                    "LANGUAGE_NOTATION",
                    "Notation path requires a reference role on every source concept",
                    identity,
                )
                return
            current = tuple(
                sorted({target for role in roles if role for target in role.allowed_concept_ids})
            )
        if field.property_id is not None and any(
            concept is None or concept.property(field.property_id) is None
            for concept in (self.schema.concept(concept_id) for concept_id in current)
        ):
            self.issue(
                "LANGUAGE_NOTATION",
                "Notation property does not exist on every path target",
                identity,
            )


def validate_authored_language(
    language: lang.AuthoredDomainLanguage,
    schema: DomainSchema,
    *,
    schemas: tuple[DomainSchema, ...] = (),
) -> tuple[DomainIssue, ...]:
    issues = language_structure_issues(language)
    if issues:
        return issues
    checker = LanguageTypeChecker(schema, schemas)
    if language.syntax_version not in {1, 2}:
        checker.issue(
            "DOMAIN_LANGUAGE_VERSION",
            "The authored syntax version is unavailable; data is preserved",
            language.id,
            incomplete=True,
        )
    if not language.version:
        checker.issue(
            "LANGUAGE_VERSION", "An authored language requires a version identity", language.id
        )
    if (language.schema_id, language.schema_version) != (schema.id, schema.version):
        checker.issue(
            "LANGUAGE_SCHEMA",
            "Authoring rules must pin their exact source schema identity and version",
            language.id,
        )
    for notation in language.notations:
        if notation.body is not None:
            if language.syntax_version < 2:
                checker.issue(
                    "LANGUAGE_SYNTAX_UPGRADE",
                    "Composed notations require syntax version 2",
                    notation.id,
                )
            from code_visualizer.domain.notation_validation import validate_composed_notation

            checker.issues.extend(
                validate_composed_notation(
                    notation.body,
                    schema,
                    schemas=schemas,
                )
            )
        if notation.schema_id != schema.id:
            checker.issue(
                "LANGUAGE_NOTATION",
                "Authored notation must explicitly name its owning schema",
                notation.id,
            )
        selected = notation.concept_ids or tuple(concept.id for concept in schema.concepts)
        if any(schema.concept(identity) is None for identity in selected):
            checker.issue("LANGUAGE_NOTATION", "Notation selects an unknown concept", notation.id)
        for column in notation.columns:
            checker.notation_field(column.field, selected, notation.id)
        for rule in notation.node_rules:
            if schema.concept(rule.concept_id) is None:
                checker.issue(
                    "LANGUAGE_NOTATION", "Notation node rule names an unknown concept", notation.id
                )
            if rule.label_property_id:
                checker.notation_field(
                    NotationField(rule.label_property_id), (rule.concept_id,), notation.id
                )
            for field in rule.label_fields:
                checker.notation_field(field, (rule.concept_id,), notation.id)
        for edge in notation.edge_rules:
            for role_id in (edge.source_role_id, edge.target_role_id):
                checker.notation_field(
                    NotationField(reference_role_ids=(role_id,)), (edge.concept_id,), notation.id
                )
            for field in edge.label_fields:
                checker.notation_field(field, (edge.concept_id,), notation.id)
    for validator in language.validators:
        if schema.concept(validator.concept_id) is None:
            checker.issue("LANGUAGE_CONCEPT", "Validator names an unknown concept", validator.id)
        environment = checker.bind(
            {}, validator.binding_id, QueryType("node", (validator.concept_id,)), validator.id
        )
        checker.require(checker.query(validator.predicate, environment), "boolean", validator.id)
        if not validator.message or not validator.code:
            checker.issue(
                "LANGUAGE_DIAGNOSTIC",
                "A validator needs a diagnostic code and message",
                validator.id,
            )
    keys: set[str] = set()
    for recipe in language.transformations:
        definition = recipe.definition
        if not definition.id or not definition.version or definition.key in keys:
            checker.issue(
                "LANGUAGE_TRANSFORM_ID",
                "Transformation identities must be unique and versioned",
                language.id,
            )
        keys.add(definition.key)
        if definition.source != Representation(schema.namespace, schema.version):
            checker.issue(
                "LANGUAGE_REPRESENTATION",
                "Templates require their exact schema representation as source",
                definition.id,
            )
        if recipe.domain is not None:
            if language.syntax_version < 2:
                checker.issue(
                    "LANGUAGE_SYNTAX_UPGRADE",
                    "Domain templates require syntax version 2",
                    definition.id,
                )
            if recipe.functions:
                checker.issue(
                    "LANGUAGE_OUTPUT",
                    "Choose either domain output or program functions",
                    definition.id,
                )
            target = next(
                (
                    item
                    for item in (*schemas, schema)
                    if (item.id, item.version)
                    == (recipe.domain.target_schema_id, recipe.domain.target_schema_version)
                ),
                None,
            )
            if target is None:
                checker.issue(
                    "LANGUAGE_TARGET_SCHEMA",
                    "Target schema identity and version are unavailable",
                    recipe.domain.id,
                    incomplete=True,
                )
            elif definition.target != Representation(target.namespace, target.version):
                checker.issue(
                    "LANGUAGE_REPRESENTATION",
                    "Domain output must match its target schema representation",
                    definition.id,
                )
            else:
                _validate_domain_template(checker, recipe.domain, target)
            continue
        if definition.target != PROGRAM_REPRESENTATION:
            checker.issue(
                "LANGUAGE_REPRESENTATION",
                "Function templates require ProgramModel as target",
                definition.id,
            )
        if not recipe.functions:
            checker.issue(
                "LANGUAGE_HOLE", "Add a function template", definition.id, incomplete=True
            )
        for function in recipe.functions:
            collection = checker.query(function.source, {})
            checker.require(collection, "sequence", function.id)
            checker.require(collection.element or UNKNOWN, "node", function.id)
            environment = checker.bind(
                {}, function.binding_id, collection.element or UNKNOWN, function.id
            )
            if not function.identifier_prefix.isidentifier() or keyword.iskeyword(
                function.identifier_prefix
            ):
                checker.issue(
                    "LANGUAGE_IDENTIFIER",
                    "Function prefix must be a Python identifier",
                    function.id,
                )
            if function.display_name is not None:
                checker.require(
                    checker.query(function.display_name, environment), "string", function.id
                )
            symbols: tuple[lang.TemplateParameter | lang.TemplateSymbol, ...] = (
                *function.parameters,
                *function.symbols,
            )
            names = [symbol.name for symbol in symbols]
            reserved = {"print", *(item.value for item in lang.RuntimeBuiltin)}
            if len(set(names)) != len(names) or any(
                not name.isidentifier() or keyword.iskeyword(name) or name in reserved
                for name in names
            ):
                checker.issue(
                    "LANGUAGE_SYMBOL",
                    "Template symbols need unique Python names "
                    "that do not shadow runtime built-ins",
                    function.id,
                )
            symbol_ids = {symbol.id for symbol in symbols}
            default_seen = False
            for parameter in function.parameters:
                if parameter.default is not None:
                    default_seen = True
                    checker.runtime(parameter.default, environment, set())
                elif default_seen:
                    checker.issue(
                        "LANGUAGE_PARAMETER",
                        "Required parameters must precede default parameters",
                        parameter.id,
                    )
            checker.statements(function.body, environment, symbol_ids)
    return tuple(checker.issues)


def _validate_domain_template(
    checker: LanguageTypeChecker, template: lang.DomainTemplate, target: DomainSchema
) -> None:
    if not template.nodes:
        checker.issue("LANGUAGE_HOLE", "Add a target node template", template.id, incomplete=True)
    by_id = {node.id: node for node in template.nodes}
    selections: dict[str, QueryType] = {}
    for node in template.nodes:
        selected = checker.query(node.source, {})
        checker.require(selected, "sequence", node.id)
        checker.require(selected.element or UNKNOWN, "node", node.id)
        selections[node.id] = selected.element or UNKNOWN
    for node in template.nodes:
        environment = checker.bind({}, node.binding_id, selections[node.id], node.id)
        concept = target.concept(node.concept_id)
        if concept is None:
            checker.issue(
                "LANGUAGE_TARGET_CONCEPT",
                "Node template selects an unknown target concept",
                node.id,
            )
            continue
        property_ids = [item.property_id for item in node.properties]
        if len(property_ids) != len(set(property_ids)):
            checker.issue(
                "LANGUAGE_TARGET_PROPERTY", "A target property can only be assigned once", node.id
            )
        for prop in node.properties:
            definition = concept.property(prop.property_id)
            actual = checker.query(prop.value, environment)
            if definition is None:
                checker.issue(
                    "LANGUAGE_TARGET_PROPERTY",
                    "Property does not belong to target concept",
                    prop.id,
                )
            else:
                expected = (
                    "number"
                    if definition.value_kind in {ValueKind.NUMBER, ValueKind.INTEGER}
                    else definition.value_kind.value
                )
                if actual.kind != "null":
                    checker.require(actual, expected, prop.id)
        for containment, bindings in ((True, node.children), (False, node.references)):
            role_ids = [item.role_id for item in bindings]
            if len(role_ids) != len(set(role_ids)):
                checker.issue(
                    "LANGUAGE_TARGET_ROLE", "A target role can only be assigned once", node.id
                )
            roles = concept.containment_roles if containment else concept.reference_roles
            for binding in bindings:
                role = next((item for item in roles if item.id == binding.role_id), None)
                recipient = by_id.get(binding.target_template_id)
                sources = checker.query(binding.sources, environment)
                checker.require(sources, "sequence", binding.id)
                checker.require(sources.element or UNKNOWN, "node", binding.id)
                if role is None or recipient is None:
                    checker.issue(
                        "LANGUAGE_TARGET_ROLE",
                        "Role and target node template must exist",
                        binding.id,
                    )
                elif recipient.concept_id not in role.allowed_concept_ids:
                    checker.issue(
                        "LANGUAGE_TARGET_ROLE",
                        "Target node concept is illegal for this role",
                        binding.id,
                    )
                elif sources.element is not None and sources.element.kind == "node":
                    allowed = selections[recipient.id].concept_ids
                    if any(identity not in allowed for identity in sources.element.concept_ids):
                        checker.issue(
                            "LANGUAGE_TARGET_SOURCE",
                            "Reference source objects are not selected by the target node template",
                            binding.id,
                        )
        for origin in node.origins:
            result = checker.query(origin, environment)
            checker.require(
                result.element or UNKNOWN if result.kind == "sequence" else result,
                "node",
                origin.id,
            )
