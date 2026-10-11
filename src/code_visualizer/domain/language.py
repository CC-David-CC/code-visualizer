"""Inert authoring language for schema-scoped rules, notations, and program templates.

Queries inspect domain snapshots at build time. Runtime expressions and statement
templates describe the typed program to generate; they never run while authoring.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from code_visualizer.domain.notation import NotationDefinition
from code_visualizer.domain.program_kinds import TransferKind
from code_visualizer.domain.transformation import TransformationDefinition


class QueryUnaryOperator(StrEnum):
    NOT = "not"
    COUNT = "count"
    FIRST = "first"


class QueryBinaryOperator(StrEnum):
    EQUAL = "equal"
    NOT_EQUAL = "not_equal"
    LESS = "less"
    LESS_EQUAL = "less_equal"
    GREATER = "greater"
    GREATER_EQUAL = "greater_equal"
    AND = "and"
    OR = "or"
    IN = "in"
    ADD = "add"


@dataclass(frozen=True, slots=True)
class QueryLiteral:
    id: str
    value: str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class QueryVariable:
    id: str
    binding_id: str


@dataclass(frozen=True, slots=True)
class QueryNodes:
    id: str
    concept_id: str
    roots_only: bool = False


@dataclass(frozen=True, slots=True)
class QueryRole:
    id: str
    source: Query
    role_id: str


@dataclass(frozen=True, slots=True)
class QueryProperty:
    id: str
    source: Query
    property_id: str


@dataclass(frozen=True, slots=True)
class QueryIdentity:
    id: str
    source: Query


@dataclass(frozen=True, slots=True)
class QueryUnary:
    id: str
    operator: QueryUnaryOperator
    operand: Query


@dataclass(frozen=True, slots=True)
class QueryBinary:
    id: str
    operator: QueryBinaryOperator
    left: Query
    right: Query


@dataclass(frozen=True, slots=True)
class QueryTuple:
    id: str
    items: tuple[Query, ...] = ()


@dataclass(frozen=True, slots=True)
class QueryMap:
    id: str
    collection: Query
    binding_id: str
    value: Query


@dataclass(frozen=True, slots=True)
class QueryFilter:
    id: str
    collection: Query
    binding_id: str
    predicate: Query


@dataclass(frozen=True, slots=True)
class QueryAll:
    id: str
    collection: Query
    binding_id: str
    predicate: Query


@dataclass(frozen=True, slots=True)
class QueryUnique:
    id: str
    collection: Query
    binding_id: str
    key: Query


@dataclass(frozen=True, slots=True)
class QueryHole:
    id: str
    label: str = "Choose a query"


type Query = (
    QueryLiteral
    | QueryVariable
    | QueryNodes
    | QueryRole
    | QueryProperty
    | QueryIdentity
    | QueryUnary
    | QueryBinary
    | QueryTuple
    | QueryMap
    | QueryFilter
    | QueryAll
    | QueryUnique
    | QueryHole
)


class RuntimeBinaryOperator(StrEnum):
    EQUAL = "equal"
    NOT_EQUAL = "not_equal"
    LESS = "less"
    LESS_EQUAL = "less_equal"
    GREATER = "greater"
    GREATER_EQUAL = "greater_equal"
    AND = "and"
    OR = "or"
    IN = "in"
    ADD = "add"
    SUBTRACT = "subtract"
    MULTIPLY = "multiply"
    DIVIDE = "divide"
    MODULO = "modulo"


class RuntimeBuiltin(StrEnum):
    RANGE = "range"
    LENGTH = "len"
    STRING = "str"
    VALUE_ERROR = "ValueError"


@dataclass(frozen=True, slots=True)
class RuntimeLiteral:
    id: str
    query: Query


@dataclass(frozen=True, slots=True)
class RuntimeVariable:
    id: str
    symbol_id: str


@dataclass(frozen=True, slots=True)
class RuntimeBinary:
    id: str
    operator: RuntimeBinaryOperator
    left: RuntimeExpression
    right: RuntimeExpression


@dataclass(frozen=True, slots=True)
class RuntimeCall:
    id: str
    builtin: RuntimeBuiltin
    arguments: tuple[RuntimeExpression, ...] = ()


@dataclass(frozen=True, slots=True)
class RuntimeHole:
    id: str
    label: str = "Choose a runtime expression"


type RuntimeExpression = (
    RuntimeLiteral | RuntimeVariable | RuntimeBinary | RuntimeCall | RuntimeHole
)


@dataclass(frozen=True, slots=True)
class TemplateSymbol:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class TemplateParameter:
    id: str
    name: str
    default: RuntimeExpression | None = None


@dataclass(frozen=True, slots=True)
class TemplateExpand:
    id: str
    collection: Query
    binding_id: str
    body: tuple[StatementTemplate, ...] = ()


@dataclass(frozen=True, slots=True)
class TemplateWhen:
    id: str
    predicate: Query
    body: tuple[StatementTemplate, ...] = ()


@dataclass(frozen=True, slots=True)
class TemplateLet:
    id: str
    binding_id: str
    value: Query
    body: tuple[StatementTemplate, ...] = ()


@dataclass(frozen=True, slots=True)
class TemplateAssignment:
    id: str
    symbol_id: str
    value: RuntimeExpression
    origins: tuple[Query, ...] = ()


@dataclass(frozen=True, slots=True)
class TemplateOutput:
    id: str
    value: RuntimeExpression
    origins: tuple[Query, ...] = ()


@dataclass(frozen=True, slots=True)
class TemplateIf:
    id: str
    condition: RuntimeExpression
    true_body: tuple[StatementTemplate, ...] = ()
    false_body: tuple[StatementTemplate, ...] = ()
    origins: tuple[Query, ...] = ()


@dataclass(frozen=True, slots=True)
class TemplateFor:
    id: str
    symbol_id: str
    iterable: RuntimeExpression
    body: tuple[StatementTemplate, ...] = ()
    origins: tuple[Query, ...] = ()


@dataclass(frozen=True, slots=True)
class TemplateTransfer:
    id: str
    kind: TransferKind
    value: RuntimeExpression | None = None
    origins: tuple[Query, ...] = ()


@dataclass(frozen=True, slots=True)
class TemplateHole:
    id: str
    label: str = "Choose a statement template"


type StatementTemplate = (
    TemplateExpand
    | TemplateWhen
    | TemplateLet
    | TemplateAssignment
    | TemplateOutput
    | TemplateIf
    | TemplateFor
    | TemplateTransfer
    | TemplateHole
)


@dataclass(frozen=True, slots=True)
class FunctionTemplate:
    id: str
    source: Query
    binding_id: str
    identifier_prefix: str = "run"
    display_name: Query | None = None
    parameters: tuple[TemplateParameter, ...] = ()
    symbols: tuple[TemplateSymbol, ...] = ()
    body: tuple[StatementTemplate, ...] = ()
    entrypoint: bool = True


@dataclass(frozen=True, slots=True)
class ValidatorDefinition:
    id: str
    concept_id: str
    binding_id: str
    predicate: Query
    message: str
    code: str = "DOMAIN_RULE"


@dataclass(frozen=True, slots=True)
class DomainPropertyTemplate:
    id: str
    property_id: str
    value: Query


@dataclass(frozen=True, slots=True)
class DomainRoleTemplate:
    id: str
    role_id: str
    target_template_id: str
    sources: Query


@dataclass(frozen=True, slots=True)
class DomainNodeTemplate:
    id: str
    source: Query
    binding_id: str
    concept_id: str
    properties: tuple[DomainPropertyTemplate, ...] = ()
    children: tuple[DomainRoleTemplate, ...] = ()
    references: tuple[DomainRoleTemplate, ...] = ()
    root: bool = True
    origins: tuple[Query, ...] = ()


@dataclass(frozen=True, slots=True)
class DomainTemplate:
    id: str
    target_schema_id: str
    target_schema_version: str
    nodes: tuple[DomainNodeTemplate, ...] = ()


@dataclass(frozen=True, slots=True)
class AuthoredTransformation:
    definition: TransformationDefinition
    functions: tuple[FunctionTemplate, ...] = ()
    domain: DomainTemplate | None = None


@dataclass(frozen=True, slots=True)
class AuthoredDomainLanguage:
    id: str
    schema_id: str
    schema_version: str
    version: str = "1"
    title: str = ""
    notations: tuple[NotationDefinition, ...] = ()
    validators: tuple[ValidatorDefinition, ...] = ()
    transformations: tuple[AuthoredTransformation, ...] = ()
    syntax_version: int = 2
