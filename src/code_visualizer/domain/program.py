"""Canonical Python-program semantics, independent of its editable presentations.

Every statement and nested expression lives here. DRAKON documents are editable
projections; no program operation needs a presentation payload to recover semantics.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, fields, is_dataclass, replace
from enum import StrEnum
from typing import cast

from code_visualizer.domain.expression import (
    ExpressionContext,
    ExpressionNode,
    parse_expression_tree,
    render_expression_tree,
)
from code_visualizer.domain.invocation_arguments import (
    EMPTY_INVOCATION_ARGUMENTS,
    ConfiguredArguments,
)
from code_visualizer.domain.program_kinds import (
    CallableKind,
    LoopKind,
    MethodKind,
    NotePlacement,
    ParallelMode,
    ParameterKind,
    ProgramModuleKind,
    SelectMode,
    SimpleKind,
    TransferKind,
)


class ExpressionRole(StrEnum):
    VALUE = "value"
    TARGET = "target"
    CONDITION = "condition"
    CALL = "call"
    ARGUMENTS = "arguments"
    ANNOTATION = "annotation"
    DEFAULT = "default"
    DECORATOR = "decorator"
    RETURN_ANNOTATION = "return_annotation"
    EXPRESSION = "expression"
    DESTINATION = "destination"
    END = "end"
    STATEMENTS = "statements"
    PATTERN = "pattern"
    NAMES = "names"
    DELETE = "delete"


class ProgramSymbolKind(StrEnum):
    FUNCTION = "function"
    PARAMETER = "parameter"
    LOCAL = "local"


@dataclass(frozen=True, slots=True)
class ProgramExpression:
    id: str
    role: ExpressionRole
    tree: ExpressionNode

    @property
    def source(self) -> str:
        """Normalized Python derived from the canonical tree; never persisted state."""

        return render_expression_tree(self.tree)


@dataclass(frozen=True, slots=True)
class ProgramSymbol:
    """A rename-stable symbol identity independent of its current Python spelling."""

    id: str
    name: str
    kind: ProgramSymbolKind
    owner_id: str
    declaration_id: str


@dataclass(frozen=True, slots=True)
class ProgramParameter:
    id: str
    symbol_id: str
    name: str
    kind: ParameterKind = ParameterKind.POSITIONAL_OR_KEYWORD
    annotation: ProgramExpression | None = None
    default: ProgramExpression | None = None


@dataclass(frozen=True, slots=True)
class ProgramAssignment:
    id: str
    target: ProgramExpression
    value: ProgramExpression
    annotation: ProgramExpression | None = None
    operator: str = "="
    written_symbol_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProgramOutput:
    id: str
    expression: ProgramExpression
    destination: ProgramExpression | None = None
    end: ProgramExpression | None = None


@dataclass(frozen=True, slots=True)
class ProgramCall:
    id: str
    expression: ProgramExpression
    arguments: ProgramExpression
    awaited: bool = False
    result_target: ProgramExpression | None = None
    target_function_id: str | None = None
    written_symbol_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProgramSequence:
    id: str
    statements: tuple[ProgramStatement, ...] = ()


@dataclass(frozen=True, slots=True)
class ProgramIf:
    id: str
    condition: ProgramExpression
    true_branch: ProgramSequence
    false_branch: ProgramSequence
    preferred_truth: bool = True


@dataclass(frozen=True, slots=True)
class ProgramAction:
    id: str
    source: ProgramExpression


@dataclass(frozen=True, slots=True)
class ProgramTransfer:
    id: str
    transfer_kind: TransferKind
    expression: ProgramExpression | None
    cause: ProgramExpression | None


@dataclass(frozen=True, slots=True)
class ProgramSimpleStatement:
    id: str
    statement_kind: SimpleKind
    source: ProgramExpression
    secondary: ProgramExpression | None


@dataclass(frozen=True, slots=True)
class ProgramInput:
    id: str
    target: ProgramExpression
    prompt: ProgramExpression
    converter: ProgramExpression | None
    annotation: ProgramExpression | None


@dataclass(frozen=True, slots=True)
class ProgramDelay:
    id: str
    seconds: ProgramExpression
    asynchronous: bool


@dataclass(frozen=True, slots=True)
class ProgramStartTimer:
    id: str
    timer: str


@dataclass(frozen=True, slots=True)
class ProgramPeriod:
    id: str
    timer: str
    seconds: ProgramExpression
    asynchronous: bool


@dataclass(frozen=True, slots=True)
class ProgramRealtimeProcess:
    id: str
    call: ProgramExpression
    awaited: bool


@dataclass(frozen=True, slots=True)
class ProgramNote:
    id: str
    text: str
    placement: NotePlacement


@dataclass(frozen=True, slots=True)
class ProgramCase:
    id: str
    label: str
    body: ProgramSequence
    condition: ProgramExpression
    pattern: ProgramExpression
    guard: ProgramExpression | None
    is_default: bool


@dataclass(frozen=True, slots=True)
class ProgramSelect:
    id: str
    expression: ProgramExpression
    cases: tuple[ProgramCase, ...]
    mode: SelectMode
    preferred_case_id: str | None


@dataclass(frozen=True, slots=True)
class ProgramLoop:
    id: str
    loop_kind: LoopKind
    body: ProgramSequence
    else_body: ProgramSequence
    condition: ProgramExpression
    target: ProgramExpression
    iterable: ProgramExpression
    children: ProgramExpression
    delay_seconds: ProgramExpression


@dataclass(frozen=True, slots=True)
class ProgramContextItem:
    id: str
    expression: ProgramExpression
    target: ProgramExpression | None


@dataclass(frozen=True, slots=True)
class ProgramWith:
    id: str
    contexts: tuple[ProgramContextItem, ...]
    body: ProgramSequence
    asynchronous: bool


@dataclass(frozen=True, slots=True)
class ProgramExceptionHandler:
    id: str
    exception: ProgramExpression | None
    name: ProgramExpression | None
    body: ProgramSequence


@dataclass(frozen=True, slots=True)
class ProgramTry:
    id: str
    body: ProgramSequence
    handlers: tuple[ProgramExceptionHandler, ...]
    else_body: ProgramSequence
    finally_body: ProgramSequence
    except_star: bool


@dataclass(frozen=True, slots=True)
class ProgramSynchronizer:
    id: str
    timer: str
    deadline: ProgramExpression
    on_time: ProgramSequence
    on_timeout: ProgramSequence
    preferred_on_time: bool


@dataclass(frozen=True, slots=True)
class ProgramParallelBranch:
    id: str
    name: str
    body: ProgramSequence


@dataclass(frozen=True, slots=True)
class ProgramParallel:
    id: str
    branches: tuple[ProgramParallelBranch, ...]
    mode: ParallelMode


@dataclass(frozen=True, slots=True)
class ProgramSilhouetteBranch:
    id: str
    name: str
    body: ProgramSequence
    target_branch_id: str | None


@dataclass(frozen=True, slots=True)
class ProgramSilhouette:
    id: str
    display_name: str
    identifier: str
    branches: tuple[ProgramSilhouetteBranch, ...]
    initial_branch_id: str


type ProgramStatement = (
    ProgramAssignment
    | ProgramOutput
    | ProgramCall
    | ProgramIf
    | ProgramAction
    | ProgramTransfer
    | ProgramSimpleStatement
    | ProgramInput
    | ProgramDelay
    | ProgramStartTimer
    | ProgramPeriod
    | ProgramRealtimeProcess
    | ProgramNote
    | ProgramSelect
    | ProgramLoop
    | ProgramWith
    | ProgramTry
    | ProgramSynchronizer
    | ProgramParallel
    | ProgramSilhouette
)


@dataclass(frozen=True, slots=True)
class ProgramFunction:
    id: str
    symbol_id: str
    identifier: str
    display_name: str
    kind: CallableKind
    parameters: tuple[ProgramParameter, ...]
    return_annotation: ProgramExpression | None
    decorators: tuple[ProgramExpression, ...]
    docstring: str | None
    method_kind: MethodKind | None
    body: ProgramSequence
    type_parameters: tuple[ExpressionNode, ...] = ()


@dataclass(frozen=True, slots=True)
class ProgramFunctionReference:
    """One owning declaration position for a function in the mature identity table."""

    function_id: str


@dataclass(frozen=True, slots=True)
class ProgramImport:
    id: str
    source: ProgramExpression


@dataclass(frozen=True, slots=True)
class ProgramTypeAlias:
    id: str
    source: ProgramExpression


@dataclass(frozen=True, slots=True)
class ProgramClass:
    id: str
    identifier: str
    body: tuple[ProgramDeclaration, ...] = ()
    arguments: ProgramExpression | None = None
    decorators: tuple[ProgramExpression, ...] = ()
    docstring: str | None = None
    type_parameters: tuple[ExpressionNode, ...] = ()


type ProgramDeclaration = (
    ProgramStatement | ProgramImport | ProgramTypeAlias | ProgramClass | ProgramFunctionReference
)


@dataclass(frozen=True, slots=True)
class ProgramModule:
    id: str
    path: str
    body: tuple[ProgramDeclaration, ...] = ()
    docstring: str = ""
    kind: ProgramModuleKind = ProgramModuleKind.MODULE


@dataclass(frozen=True, slots=True)
class ProgramEntryPoint:
    id: str
    callable_id: str | None = None
    arguments: ConfiguredArguments = EMPTY_INVOCATION_ARGUMENTS
    startup: tuple[ProgramDeclaration, ...] = ()


@dataclass(frozen=True, slots=True)
class ProgramModel:
    functions: tuple[ProgramFunction, ...] = ()
    symbols: tuple[ProgramSymbol, ...] = ()
    modules: tuple[ProgramModule, ...] = ()
    package: str = "app"
    entrypoint: ProgramEntryPoint | None = None

    def function(self, function_id: str) -> ProgramFunction | None:
        return next((item for item in self.functions if item.id == function_id), None)

    def symbol(self, symbol_id: str) -> ProgramSymbol | None:
        return next((item for item in self.symbols if item.id == symbol_id), None)

    def module(self, module_id: str) -> ProgramModule | None:
        return next((item for item in self.modules if item.id == module_id), None)

    def class_(self, class_id: str) -> ProgramClass | None:
        return next(
            (
                item
                for item in iter_program_nodes(self.modules)
                if isinstance(item, ProgramClass) and item.id == class_id
            ),
            None,
        )

    def owner_of(self, identity: str) -> ProgramModule | ProgramClass | None:
        def visit(owner: ProgramModule | ProgramClass) -> ProgramModule | ProgramClass | None:
            for item in owner.body:
                if (
                    isinstance(item, ProgramFunctionReference) and item.function_id == identity
                ) or getattr(item, "id", None) == identity:
                    return owner
                if isinstance(item, ProgramClass) and (found := visit(item)) is not None:
                    return found
                if not isinstance(item, (ProgramClass, ProgramFunctionReference)) and any(
                    getattr(node, "id", None) == identity for node in iter_program_nodes(item)
                ):
                    return owner
            return None

        return next(
            (owner for module in self.modules if (owner := visit(module)) is not None), None
        )

    def module_for(self, identity: str) -> ProgramModule | None:
        if (module := self.module(identity)) is not None:
            return module
        owner = self.owner_of(identity)
        if owner is None:
            containing_function = next(
                (
                    function
                    for function in self.functions
                    if any(
                        getattr(node, "id", None) == identity
                        for node in iter_program_nodes(function)
                    )
                ),
                None,
            )
            if containing_function is not None:
                owner = self.owner_of(containing_function.id)
        while isinstance(owner, ProgramClass):
            owner = self.owner_of(owner.id)
        return owner

    def class_for(self, identity: str) -> ProgramClass | None:
        owner = self.owner_of(identity)
        return owner if isinstance(owner, ProgramClass) else None

    def module_path_for(self, function_id: str) -> str:
        module = self.module_for(function_id)
        return module.path if module is not None else ""

    def class_name_for(self, function_id: str) -> str | None:
        names: list[str] = []
        owner = self.class_for(function_id)
        while owner is not None:
            names.append(owner.identifier)
            owner = self.class_for(owner.id)
        return ".".join(reversed(names)) if names else None

    @property
    def entrypoint_callable_id(self) -> str | None:
        return self.entrypoint.callable_id if self.entrypoint is not None else None

    @property
    def entrypoint_arguments(self) -> ConfiguredArguments:
        return (
            self.entrypoint.arguments if self.entrypoint is not None else EMPTY_INVOCATION_ARGUMENTS
        )


def make_program_expression(
    owner_id: str,
    field: str,
    source: str,
    role: ExpressionRole,
    *,
    resolve_symbol: Callable[[str, ExpressionContext], str | None] | None = None,
    identity_namespace: str | None = None,
) -> ProgramExpression:
    expression_id = f"expression:{owner_id}:{field}"
    mode = expression_parse_mode(role)
    return ProgramExpression(
        expression_id,
        role,
        parse_expression_tree(
            expression_id,
            source,
            mode=mode,
            resolve_symbol=resolve_symbol,
            identity_namespace=identity_namespace,
        ),
    )


def expression_parse_mode(role: ExpressionRole) -> str:
    return {
        ExpressionRole.TARGET: "target",
        ExpressionRole.ARGUMENTS: "arguments",
        ExpressionRole.STATEMENTS: "exec",
        ExpressionRole.PATTERN: "pattern",
        ExpressionRole.NAMES: "names",
        ExpressionRole.DELETE: "delete",
    }.get(role, "eval")


def iter_program_nodes(value: object) -> Iterator[object]:
    """Walk canonical ownership, treating expression trees as separate subgraphs."""
    if isinstance(value, tuple):
        for item in value:
            yield from iter_program_nodes(item)
    elif is_dataclass(value) and not isinstance(value, type):
        yield value
        if not isinstance(value, ProgramExpression):
            for field in fields(value):
                yield from iter_program_nodes(getattr(value, field.name))


def program_expressions(value: object) -> Iterator[ProgramExpression]:
    for node in iter_program_nodes(value):
        if isinstance(node, ProgramExpression):
            yield node


def program_node_id(value: object) -> str:
    identity = getattr(value, "id", None)
    if not isinstance(identity, str):
        raise TypeError(f"Expected a canonical identity on {type(value).__name__}")
    return identity


def map_program[T](
    value: T,
    *,
    expression_mapper: Callable[[ProgramExpression], ProgramExpression] | None = None,
    sequence_mapper: Callable[[ProgramSequence], ProgramSequence] | None = None,
) -> T:
    """Map canonical fields without reparsing or changing unrelated identities."""

    def visit(item: object) -> object:
        if isinstance(item, ProgramExpression):
            return expression_mapper(item) if expression_mapper is not None else item
        if isinstance(item, tuple):
            updated = tuple(visit(child) for child in item)
            return item if all(a is b for a, b in zip(item, updated, strict=True)) else updated
        if is_dataclass(item) and not isinstance(item, type):
            changes = {}
            for field in fields(item):
                old = getattr(item, field.name)
                new = visit(old)
                if new is not old:
                    changes[field.name] = new
            updated_item = replace(item, **changes) if changes else item
            if isinstance(updated_item, ProgramSequence) and sequence_mapper is not None:
                return sequence_mapper(updated_item)
            return updated_item
        return item

    return cast(T, visit(value))


def program_sequences(value: object) -> Iterator[ProgramSequence]:
    for node in iter_program_nodes(value):
        if isinstance(node, ProgramSequence):
            yield node


def program_statements(value: object) -> Iterator[ProgramStatement]:
    for sequence in program_sequences(value):
        yield from sequence.statements
