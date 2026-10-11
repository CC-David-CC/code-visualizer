"""Translate explicit DRAKON import/edit input and project canonical functions as DRAKON.

Executable ownership and generic program operations remain in domain.program.
"""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, replace

from code_visualizer.domain.drakon import (
    Action,
    Assignment,
    Call,
    Case,
    ContextItem,
    Delay,
    DrakonAtom,
    DrakonDiagram,
    End,
    ExceptionHandler,
    Header,
    If,
    Input,
    Loop,
    Note,
    Output,
    Parallel,
    ParallelBranch,
    Period,
    RealtimeProcess,
    Select,
    Sequence,
    Silhouette,
    SilhouetteBranch,
    SimpleStatement,
    StartTimer,
    Synchronizer,
    Transfer,
    Try,
    With,
    nested_sequences,
)
from code_visualizer.domain.expression import (
    ExpressionContext,
    ExpressionNode,
    SymbolReferenceExpression,
    expression_children,
    reconcile_expression_trees,
)
from code_visualizer.domain.program import (
    ExpressionRole,
    ProgramAction,
    ProgramAssignment,
    ProgramCall,
    ProgramCase,
    ProgramContextItem,
    ProgramDelay,
    ProgramExceptionHandler,
    ProgramExpression,
    ProgramFunction,
    ProgramIf,
    ProgramInput,
    ProgramLoop,
    ProgramModel,
    ProgramNote,
    ProgramOutput,
    ProgramParallel,
    ProgramParallelBranch,
    ProgramParameter,
    ProgramPeriod,
    ProgramRealtimeProcess,
    ProgramSelect,
    ProgramSequence,
    ProgramSilhouette,
    ProgramSilhouetteBranch,
    ProgramSimpleStatement,
    ProgramStartTimer,
    ProgramStatement,
    ProgramSymbol,
    ProgramSymbolKind,
    ProgramSynchronizer,
    ProgramTransfer,
    ProgramTry,
    ProgramWith,
    make_program_expression,
    program_expressions,
)
from code_visualizer.domain.program_index import ProgramFunctionLocation
from code_visualizer.domain.program_kinds import (
    LoopKind,
    SelectMode,
    SimpleKind,
)
from code_visualizer.domain.program_ownership import place_program_function
from code_visualizer.domain.program_signatures import FunctionSpec, ParameterSpec
from code_visualizer.domain.projection import DrakonViewDefinition


@dataclass(frozen=True, slots=True)
class ProgramPromotion:
    model: ProgramModel
    drakon_views: tuple[DrakonViewDefinition, ...]


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _target_names(source: str) -> tuple[str, ...]:
    try:
        statement = ast.parse(f"{source} = None", mode="exec").body[0]
    except SyntaxError:
        return ()
    target = statement.targets[0] if isinstance(statement, ast.Assign) else None
    if target is None:
        return ()
    result: list[str] = []
    for node in ast.walk(target):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            result.append(node.id)
    return tuple(dict.fromkeys(result))


class _FunctionBuilder:
    def __init__(
        self,
        previous: ProgramFunction | None,
        previous_symbols: tuple[ProgramSymbol, ...],
        function_id: str,
        deterministic: bool = False,
    ) -> None:
        self.function_id = function_id
        self.deterministic = deterministic
        self.previous = previous
        self.symbols: list[ProgramSymbol] = []
        self._previous_symbols = previous_symbols
        self._symbols_by_name: dict[str, ProgramSymbol] = {}
        self._previous_expressions = (
            {item.id: item for item in program_expressions(previous)}
            if previous is not None
            else {}
        )
        self._claimed_parameter_ids: set[str] = set()
        self._retained_parameter_ids: set[str] = set()

    def _resolve_symbol(self, name: str, _context: ExpressionContext) -> str | None:
        symbol = self._symbols_by_name.get(name)
        return None if symbol is None else symbol.id

    def _expression(
        self,
        owner_id: str,
        field: str,
        source: str,
        role: ExpressionRole,
    ) -> ProgramExpression:
        expression_id = f"expression:{owner_id}:{field}"
        previous = self._previous_expressions.get(expression_id)
        if (
            previous is not None
            and previous.role is role
            and previous.source == source
            and self._bindings_still_match(previous.tree)
        ):
            return previous
        provisional = make_program_expression(
            owner_id,
            field,
            source,
            role,
            resolve_symbol=self._resolve_symbol,
            identity_namespace="initial" if self.previous is None or self.deterministic else None,
        )
        if previous is not None and previous.role is role:
            return replace(
                provisional,
                tree=reconcile_expression_trees(previous.tree, provisional.tree),
            )
        return provisional

    def _bindings_still_match(self, tree: ExpressionNode) -> bool:
        if isinstance(tree, SymbolReferenceExpression) and (
            tree.symbol_id != self._resolve_symbol(tree.name, tree.context)
        ):
            return False
        return all(self._bindings_still_match(child) for _field, child in expression_children(tree))

    def build(self, function: FunctionSpec, sequence: Sequence | None = None) -> ProgramFunction:
        function_id = self.function_id
        old_function_symbol = next(
            (
                item
                for item in self._previous_symbols
                if item.owner_id == function_id and item.kind is ProgramSymbolKind.FUNCTION
            ),
            None,
        )
        function_symbol = ProgramSymbol(
            old_function_symbol.id
            if old_function_symbol is not None
            else _stable_id("symbol", function_id, "function"),
            function.identifier,
            ProgramSymbolKind.FUNCTION,
            function_id,
            function_id,
        )
        self.symbols.append(function_symbol)
        previous_parameters = self.previous.parameters if self.previous is not None else ()
        self._retained_parameter_ids = {
            old.id
            for old in previous_parameters
            for parameter in function.parameters
            if old.name == parameter.name and old.kind is parameter.kind
        }
        parameters = tuple(
            self._parameter(item, index) for index, item in enumerate(function.parameters)
        )
        if sequence is not None:
            self._declare_sequence(sequence)
            body = self._sequence(sequence)
        elif self.previous is not None:
            body = self.previous.body
        else:
            raise ValueError("A new function requires an explicit body")
        return ProgramFunction(
            function_id,
            function_symbol.id,
            function.identifier,
            function.display_name,
            function.kind,
            parameters,
            (
                self._expression(
                    function_id,
                    "return_annotation",
                    function.return_annotation,
                    ExpressionRole.RETURN_ANNOTATION,
                )
                if function.return_annotation is not None
                else None
            ),
            tuple(
                self._expression(
                    function_id,
                    f"decorator[{index}]",
                    source,
                    ExpressionRole.DECORATOR,
                )
                for index, source in enumerate(function.decorators)
            ),
            function.docstring,
            function.method_kind,
            body,
            self.previous.type_parameters if self.previous is not None else (),
        )

    def _parameter(self, value: ParameterSpec, index: int) -> ProgramParameter:
        previous = self.previous.parameters if self.previous is not None else ()
        exact = next(
            (
                item
                for item in previous
                if item.name == value.name
                and item.kind is value.kind
                and item.id not in self._claimed_parameter_ids
            ),
            None,
        )
        positional = previous[index] if index < len(previous) else None
        if positional is not None and positional.id in (
            self._claimed_parameter_ids | self._retained_parameter_ids
        ):
            positional = None
        prior = exact or positional
        parameter_id = (
            prior.id
            if prior is not None
            else _stable_id("parameter", self.function_id, str(index), value.name)
        )
        self._claimed_parameter_ids.add(parameter_id)
        old_symbol = (
            next(
                (item for item in self._previous_symbols if item.id == prior.symbol_id),
                None,
            )
            if prior is not None
            else None
        )
        symbol = ProgramSymbol(
            old_symbol.id
            if old_symbol is not None
            else _stable_id("symbol", self.function_id, parameter_id),
            value.name,
            ProgramSymbolKind.PARAMETER,
            self.function_id,
            parameter_id,
        )
        self.symbols.append(symbol)
        self._symbols_by_name[value.name] = symbol
        return ProgramParameter(
            parameter_id,
            symbol.id,
            value.name,
            value.kind,
            (
                self._expression(
                    parameter_id,
                    "annotation",
                    value.annotation,
                    ExpressionRole.ANNOTATION,
                )
                if value.annotation is not None
                else None
            ),
            (
                self._expression(
                    parameter_id,
                    "default",
                    value.default,
                    ExpressionRole.DEFAULT,
                )
                if value.default is not None
                else None
            ),
        )

    def _written_symbols(self, statement_id: str, target: str) -> tuple[str, ...]:
        result: list[str] = []
        for name in _target_names(target):
            existing = self._symbols_by_name.get(name)
            if existing is None:
                declaration_id = statement_id
                prior = next(
                    (
                        item
                        for item in self._previous_symbols
                        if item.owner_id == self.function_id
                        and item.kind is ProgramSymbolKind.LOCAL
                        and item.name == name
                    ),
                    None,
                )
                if prior is None:
                    prior = next(
                        (
                            item
                            for item in self._previous_symbols
                            if item.owner_id == self.function_id
                            and item.kind is ProgramSymbolKind.LOCAL
                            and item.declaration_id == declaration_id
                            and item.id not in {symbol.id for symbol in self.symbols}
                        ),
                        None,
                    )
                existing = ProgramSymbol(
                    prior.id
                    if prior is not None
                    else _stable_id("symbol", self.function_id, declaration_id, name),
                    name,
                    ProgramSymbolKind.LOCAL,
                    self.function_id,
                    declaration_id,
                )
                self.symbols.append(existing)
                self._symbols_by_name[name] = existing
            result.append(existing.id)
        return tuple(result)

    def _declare_sequence(self, sequence: Sequence) -> None:
        # Python locals have function scope even when their first write is nested
        # or follows a read. Bind those names before parsing any expression tree.
        for atom in sequence.atoms:
            if isinstance(atom, (Assignment, Input)):
                self._written_symbols(atom.id, atom.target)
            elif isinstance(atom, Call):
                self._written_symbols(atom.id, atom.result_target or "")
            elif isinstance(atom, Loop) and atom.loop_kind in {
                LoopKind.FOR,
                LoopKind.ASYNC_FOR,
                LoopKind.TREE_DFS,
                LoopKind.TREE_BFS,
            }:
                self._written_symbols(atom.id, atom.target)
            elif isinstance(atom, With):
                for context in atom.contexts:
                    self._written_symbols(context.id, context.target or "")
            elif isinstance(atom, Try):
                for handler in atom.handlers:
                    self._written_symbols(handler.id, handler.name or "")
            elif isinstance(atom, Action):
                try:
                    tree = ast.parse(atom.source)
                except SyntaxError:
                    continue
                names = tuple(
                    dict.fromkeys(
                        node.id
                        for node in ast.walk(tree)
                        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
                    )
                )
                self._written_symbols(atom.id, ", ".join(names))
            elif isinstance(atom, Select) and atom.mode is SelectMode.MATCH:
                for case in atom.cases:
                    try:
                        tree = ast.parse(f"match None:\n    case {case.pattern}:\n        pass")
                    except SyntaxError:
                        continue
                    names = tuple(
                        dict.fromkeys(
                            name
                            for node in ast.walk(tree)
                            if isinstance(node, (ast.MatchAs, ast.MatchStar, ast.MatchMapping))
                            if (name := getattr(node, "name", getattr(node, "rest", None)))
                        )
                    )
                    self._written_symbols(case.id, ", ".join(names))
            for nested in nested_sequences(atom):
                self._declare_sequence(nested)

    def _sequence(self, sequence: Sequence) -> ProgramSequence:
        return ProgramSequence(
            sequence.id,
            tuple(self._statement(item) for item in sequence.atoms),
        )

    def _statement(self, atom: DrakonAtom) -> ProgramStatement:
        if isinstance(atom, Assignment):
            written_symbols = self._written_symbols(atom.id, atom.target)
            return ProgramAssignment(
                atom.id,
                self._expression(atom.id, "target", atom.target, ExpressionRole.TARGET),
                self._expression(atom.id, "value", atom.value, ExpressionRole.VALUE),
                (
                    self._expression(
                        atom.id,
                        "annotation",
                        atom.annotation,
                        ExpressionRole.ANNOTATION,
                    )
                    if atom.annotation is not None
                    else None
                ),
                atom.operator,
                written_symbols,
            )
        if isinstance(atom, Output):
            return ProgramOutput(
                atom.id,
                self._expression(
                    atom.id,
                    "expression",
                    atom.expression,
                    ExpressionRole.EXPRESSION,
                ),
                (
                    self._expression(
                        atom.id,
                        "destination",
                        atom.destination,
                        ExpressionRole.DESTINATION,
                    )
                    if atom.destination is not None
                    else None
                ),
                (
                    self._expression(atom.id, "end", atom.end, ExpressionRole.END)
                    if atom.end is not None
                    else None
                ),
            )
        if isinstance(atom, Call):
            written_symbols = self._written_symbols(atom.id, atom.result_target or "")
            target = (
                self._expression(
                    atom.id,
                    "result_target",
                    atom.result_target,
                    ExpressionRole.TARGET,
                )
                if atom.result_target is not None
                else None
            )
            return ProgramCall(
                atom.id,
                self._expression(atom.id, "expression", atom.expression, ExpressionRole.CALL),
                self._expression(atom.id, "arguments", atom.arguments, ExpressionRole.ARGUMENTS),
                atom.awaited,
                target,
                atom.target_diagram_id,
                written_symbols,
            )
        if isinstance(atom, If):
            return ProgramIf(
                atom.id,
                self._expression(atom.id, "condition", atom.condition, ExpressionRole.CONDITION),
                self._sequence(atom.true_branch),
                self._sequence(atom.false_branch),
                atom.preferred_truth,
            )
        if isinstance(atom, Action):
            return self._action(atom)
        if isinstance(atom, Transfer):
            return self._transfer(atom)
        if isinstance(atom, SimpleStatement):
            return self._simple_statement(atom)
        if isinstance(atom, Input):
            return self._input(atom)
        if isinstance(atom, Delay):
            return self._delay(atom)
        if isinstance(atom, StartTimer):
            return self._start_timer(atom)
        if isinstance(atom, Period):
            return self._period(atom)
        if isinstance(atom, RealtimeProcess):
            return self._realtime_process(atom)
        if isinstance(atom, Note):
            return self._note(atom)
        if isinstance(atom, Select):
            return self._select(atom)
        if isinstance(atom, Loop):
            return self._loop(atom)
        if isinstance(atom, With):
            return self._with(atom)
        if isinstance(atom, Try):
            return self._try(atom)
        if isinstance(atom, Synchronizer):
            return self._synchronizer(atom)
        if isinstance(atom, Parallel):
            return self._parallel(atom)
        if isinstance(atom, Silhouette):
            return self._silhouette(atom)
        raise TypeError(f"Unsupported DRAKON atom: {type(atom).__name__}")

    def _action(self, atom: Action) -> ProgramAction:
        return ProgramAction(
            atom.id,
            self._expression(atom.id, "source", atom.source, ExpressionRole.STATEMENTS),
        )

    def _transfer(self, atom: Transfer) -> ProgramTransfer:
        return ProgramTransfer(
            atom.id,
            atom.transfer_kind,
            self._expression(atom.id, "expression", atom.expression, ExpressionRole.EXPRESSION)
            if atom.expression
            else None,
            self._expression(atom.id, "cause", atom.cause, ExpressionRole.EXPRESSION)
            if atom.cause
            else None,
        )

    def _simple_statement(self, atom: SimpleStatement) -> ProgramSimpleStatement:
        return ProgramSimpleStatement(
            atom.id,
            atom.statement_kind,
            self._expression(
                atom.id,
                "source",
                atom.source,
                (
                    ExpressionRole.STATEMENTS
                    if atom.statement_kind is SimpleKind.PASS
                    else ExpressionRole.NAMES
                    if atom.statement_kind in {SimpleKind.GLOBAL, SimpleKind.NONLOCAL}
                    else ExpressionRole.DELETE
                    if atom.statement_kind is SimpleKind.DELETE
                    else ExpressionRole.EXPRESSION
                ),
            ),
            self._expression(atom.id, "secondary", atom.secondary, ExpressionRole.EXPRESSION)
            if atom.secondary
            else None,
        )

    def _input(self, atom: Input) -> ProgramInput:
        self._written_symbols(atom.id, atom.target or "")
        return ProgramInput(
            atom.id,
            self._expression(atom.id, "target", atom.target, ExpressionRole.TARGET),
            self._expression(atom.id, "prompt", atom.prompt, ExpressionRole.EXPRESSION),
            self._expression(atom.id, "converter", atom.converter, ExpressionRole.EXPRESSION)
            if atom.converter
            else None,
            self._expression(atom.id, "annotation", atom.annotation, ExpressionRole.ANNOTATION)
            if atom.annotation
            else None,
        )

    def _delay(self, atom: Delay) -> ProgramDelay:
        return ProgramDelay(
            atom.id,
            self._expression(atom.id, "seconds", atom.seconds, ExpressionRole.EXPRESSION),
            atom.asynchronous,
        )

    def _start_timer(self, atom: StartTimer) -> ProgramStartTimer:
        return ProgramStartTimer(
            atom.id,
            atom.timer,
        )

    def _period(self, atom: Period) -> ProgramPeriod:
        return ProgramPeriod(
            atom.id,
            atom.timer,
            self._expression(atom.id, "seconds", atom.seconds, ExpressionRole.EXPRESSION),
            atom.asynchronous,
        )

    def _realtime_process(self, atom: RealtimeProcess) -> ProgramRealtimeProcess:
        return ProgramRealtimeProcess(
            atom.id,
            self._expression(atom.id, "call", atom.call, ExpressionRole.CALL),
            atom.awaited,
        )

    def _note(self, atom: Note) -> ProgramNote:
        return ProgramNote(
            atom.id,
            atom.text,
            atom.placement,
        )

    def _case(self, atom: Case) -> ProgramCase:
        return ProgramCase(
            atom.id,
            atom.label,
            self._sequence(atom.body),
            self._expression(atom.id, "condition", atom.condition, ExpressionRole.CONDITION),
            self._expression(atom.id, "pattern", atom.pattern, ExpressionRole.PATTERN),
            self._expression(atom.id, "guard", atom.guard, ExpressionRole.CONDITION)
            if atom.guard
            else None,
            atom.is_default,
        )

    def _select(self, atom: Select) -> ProgramSelect:
        return ProgramSelect(
            atom.id,
            self._expression(atom.id, "expression", atom.expression, ExpressionRole.EXPRESSION),
            tuple(self._case(item) for item in atom.cases),
            atom.mode,
            atom.preferred_case_id,
        )

    def _loop(self, atom: Loop) -> ProgramLoop:
        self._written_symbols(atom.id, atom.target or "")
        return ProgramLoop(
            atom.id,
            atom.loop_kind,
            self._sequence(atom.body),
            self._sequence(atom.else_body),
            self._expression(atom.id, "condition", atom.condition, ExpressionRole.CONDITION),
            self._expression(atom.id, "target", atom.target, ExpressionRole.TARGET),
            self._expression(atom.id, "iterable", atom.iterable, ExpressionRole.EXPRESSION),
            self._expression(atom.id, "children", atom.children, ExpressionRole.EXPRESSION),
            self._expression(
                atom.id, "delay_seconds", atom.delay_seconds, ExpressionRole.EXPRESSION
            ),
        )

    def _context_item(self, atom: ContextItem) -> ProgramContextItem:
        self._written_symbols(atom.id, atom.target or "")
        return ProgramContextItem(
            atom.id,
            self._expression(atom.id, "expression", atom.expression, ExpressionRole.EXPRESSION),
            self._expression(atom.id, "target", atom.target, ExpressionRole.TARGET)
            if atom.target
            else None,
        )

    def _with(self, atom: With) -> ProgramWith:
        return ProgramWith(
            atom.id,
            tuple(self._context_item(item) for item in atom.contexts),
            self._sequence(atom.body),
            atom.asynchronous,
        )

    def _exception_handler(self, atom: ExceptionHandler) -> ProgramExceptionHandler:
        self._written_symbols(atom.id, atom.name or "")
        return ProgramExceptionHandler(
            atom.id,
            self._expression(atom.id, "exception", atom.exception, ExpressionRole.EXPRESSION)
            if atom.exception
            else None,
            self._expression(atom.id, "name", atom.name, ExpressionRole.TARGET)
            if atom.name
            else None,
            self._sequence(atom.body),
        )

    def _try(self, atom: Try) -> ProgramTry:
        return ProgramTry(
            atom.id,
            self._sequence(atom.body),
            tuple(self._exception_handler(item) for item in atom.handlers),
            self._sequence(atom.else_body),
            self._sequence(atom.finally_body),
            atom.except_star,
        )

    def _synchronizer(self, atom: Synchronizer) -> ProgramSynchronizer:
        return ProgramSynchronizer(
            atom.id,
            atom.timer,
            self._expression(atom.id, "deadline", atom.deadline, ExpressionRole.EXPRESSION),
            self._sequence(atom.on_time),
            self._sequence(atom.on_timeout),
            atom.preferred_on_time,
        )

    def _parallel_branch(self, atom: ParallelBranch) -> ProgramParallelBranch:
        return ProgramParallelBranch(
            atom.id,
            atom.name,
            self._sequence(atom.body),
        )

    def _parallel(self, atom: Parallel) -> ProgramParallel:
        return ProgramParallel(
            atom.id,
            tuple(self._parallel_branch(item) for item in atom.branches),
            atom.mode,
        )

    def _silhouette_branch(self, atom: SilhouetteBranch) -> ProgramSilhouetteBranch:
        return ProgramSilhouetteBranch(
            atom.id,
            atom.name,
            self._sequence(atom.body),
            atom.target_branch_id,
        )

    def _silhouette(self, atom: Silhouette) -> ProgramSilhouette:
        return ProgramSilhouette(
            atom.id,
            atom.display_name,
            atom.identifier,
            tuple(self._silhouette_branch(item) for item in atom.branches),
            atom.initial_branch_id,
        )


def promote_program_from_drakon(
    diagrams: tuple[DrakonDiagram, ...],
    previous: ProgramModel | None = None,
    previous_views: tuple[DrakonViewDefinition, ...] = (),
    *,
    deterministic: bool = False,
) -> ProgramPromotion:
    """Translate DRAKON editor input into complete canonical functions."""

    prior = previous or ProgramModel()
    prior_functions = {item.id: item for item in prior.functions}
    functions: list[ProgramFunction] = []
    symbols: list[ProgramSymbol] = []
    views: list[DrakonViewDefinition] = []
    owned = prior
    for diagram in diagrams:
        old_view = next((item for item in previous_views if item.document_id == diagram.id), None)
        function_id = old_view.function_id if old_view is not None else diagram.id
        builder = _FunctionBuilder(
            prior_functions.get(function_id),
            prior.symbols,
            function_id,
            deterministic,
        )
        function = builder.build(diagram.header.function, diagram.body)
        spec = diagram.header.function
        owned = place_program_function(
            owned,
            function.id,
            spec.module,
            spec.owning_class,
            identity_namespace=(diagrams[0].id if diagrams and deterministic else None),
        )
        functions.append(function)
        symbols.extend(builder.symbols)
        views.append(
            DrakonViewDefinition(
                diagram.id,
                function.id,
                diagram.title,
                old_view.header_id if old_view is not None else diagram.header.id,
                old_view.end_id if old_view is not None else diagram.end.id,
            )
        )
    return ProgramPromotion(
        replace(owned, functions=tuple(functions), symbols=tuple(symbols)), tuple(views)
    )


def program_statement_from_drakon(
    atom: DrakonAtom,
    function: ProgramFunction,
    model: ProgramModel,
) -> ProgramStatement:
    """Translate only a gesture's supplied subtree using canonical identity context.

    This input adapter never reads or constructs an enclosing DRAKON document.
    Program commands own insertion, declaration reconciliation, and projection refresh.
    """
    builder = _FunctionBuilder(function, model.symbols, function.id)
    builder._symbols_by_name = {
        item.name: item
        for item in model.symbols
        if item.owner_id == function.id and item.kind is not ProgramSymbolKind.FUNCTION
    }
    builder._declare_sequence(Sequence(function.body.id, (atom,)))
    return builder._statement(atom)


def program_signature_from_spec(
    spec: FunctionSpec,
    function: ProgramFunction,
    model: ProgramModel,
) -> tuple[ProgramFunction, tuple[ProgramSymbol, ...]]:
    """Translate signature input while retaining the existing canonical body."""
    builder = _FunctionBuilder(function, model.symbols, function.id)
    locals_ = tuple(
        item
        for item in model.symbols
        if item.owner_id == function.id and item.kind is ProgramSymbolKind.LOCAL
    )
    builder.symbols.extend(locals_)
    builder._symbols_by_name = {item.name: item for item in locals_}
    updated = builder.build(spec)
    return updated, tuple(builder.symbols)


def parameter_spec(value: ProgramParameter) -> ParameterSpec:
    return ParameterSpec(
        value.name,
        value.kind,
        value.annotation.source if value.annotation is not None else None,
        value.default.source if value.default is not None else None,
    )


def function_spec(
    value: ProgramFunction,
    model: ProgramModel,
    *,
    locations: Mapping[str, ProgramFunctionLocation] | None = None,
) -> FunctionSpec:
    location = locations.get(value.id) if locations is not None else None
    return FunctionSpec(
        value.identifier,
        value.display_name,
        value.kind,
        tuple(parameter_spec(item) for item in value.parameters),
        value.return_annotation.source if value.return_annotation is not None else None,
        tuple(item.source for item in value.decorators),
        value.docstring,
        location.module.path if location is not None else model.module_path_for(value.id),
        location.class_name if location is not None else model.class_name_for(value.id),
        value.method_kind,
    )


def drakon_sequence(value: ProgramSequence) -> Sequence:
    return Sequence(value.id, tuple(drakon_atom(item) for item in value.statements))


def drakon_atom(statement: ProgramStatement) -> DrakonAtom:
    """Render a structural editor value using canonical semantics alone."""
    if isinstance(statement, ProgramAssignment):
        return Assignment(
            statement.id,
            statement.target.source,
            statement.value.source,
            statement.annotation.source if statement.annotation else None,
            statement.operator,
        )
    if isinstance(statement, ProgramOutput):
        return Output(
            statement.id,
            statement.expression.source,
            statement.destination.source if statement.destination else None,
            statement.end.source if statement.end else None,
        )
    if isinstance(statement, ProgramCall):
        return Call(
            statement.id,
            statement.expression.source,
            statement.awaited,
            statement.result_target.source if statement.result_target else None,
            statement.target_function_id,
            statement.arguments.source,
        )
    if isinstance(statement, ProgramIf):
        return If(
            statement.id,
            statement.condition.source,
            drakon_sequence(statement.true_branch),
            drakon_sequence(statement.false_branch),
            statement.preferred_truth,
        )
    if isinstance(statement, ProgramAction):
        return _drakon_action(statement)
    if isinstance(statement, ProgramTransfer):
        return _drakon_transfer(statement)
    if isinstance(statement, ProgramSimpleStatement):
        return _drakon_simple_statement(statement)
    if isinstance(statement, ProgramInput):
        return _drakon_input(statement)
    if isinstance(statement, ProgramDelay):
        return _drakon_delay(statement)
    if isinstance(statement, ProgramStartTimer):
        return _drakon_start_timer(statement)
    if isinstance(statement, ProgramPeriod):
        return _drakon_period(statement)
    if isinstance(statement, ProgramRealtimeProcess):
        return _drakon_realtime_process(statement)
    if isinstance(statement, ProgramNote):
        return _drakon_note(statement)
    if isinstance(statement, ProgramSelect):
        return _drakon_select(statement)
    if isinstance(statement, ProgramLoop):
        return _drakon_loop(statement)
    if isinstance(statement, ProgramWith):
        return _drakon_with(statement)
    if isinstance(statement, ProgramTry):
        return _drakon_try(statement)
    if isinstance(statement, ProgramSynchronizer):
        return _drakon_synchronizer(statement)
    if isinstance(statement, ProgramParallel):
        return _drakon_parallel(statement)
    if isinstance(statement, ProgramSilhouette):
        return _drakon_silhouette(statement)
    raise TypeError(f"Unsupported program statement: {type(statement).__name__}")


def _drakon_action(value: ProgramAction) -> Action:
    return Action(
        value.id,
        value.source.source,
    )


def _drakon_transfer(value: ProgramTransfer) -> Transfer:
    return Transfer(
        value.id,
        value.transfer_kind,
        value.expression.source if value.expression is not None else "",
        value.cause.source if value.cause is not None else None,
    )


def _drakon_simple_statement(value: ProgramSimpleStatement) -> SimpleStatement:
    return SimpleStatement(
        value.id,
        value.statement_kind,
        value.source.source,
        value.secondary.source if value.secondary is not None else None,
    )


def _drakon_input(value: ProgramInput) -> Input:
    return Input(
        value.id,
        value.target.source,
        value.prompt.source,
        value.converter.source if value.converter is not None else None,
        value.annotation.source if value.annotation is not None else None,
    )


def _drakon_delay(value: ProgramDelay) -> Delay:
    return Delay(
        value.id,
        value.seconds.source,
        value.asynchronous,
    )


def _drakon_start_timer(value: ProgramStartTimer) -> StartTimer:
    return StartTimer(
        value.id,
        value.timer,
    )


def _drakon_period(value: ProgramPeriod) -> Period:
    return Period(
        value.id,
        value.timer,
        value.seconds.source,
        value.asynchronous,
    )


def _drakon_realtime_process(value: ProgramRealtimeProcess) -> RealtimeProcess:
    return RealtimeProcess(
        value.id,
        value.call.source,
        value.awaited,
    )


def _drakon_note(value: ProgramNote) -> Note:
    return Note(
        value.id,
        value.text,
        value.placement,
    )


def _drakon_case(value: ProgramCase) -> Case:
    return Case(
        value.id,
        value.label,
        drakon_sequence(value.body),
        value.condition.source,
        value.pattern.source,
        value.guard.source if value.guard is not None else None,
        value.is_default,
    )


def _drakon_select(value: ProgramSelect) -> Select:
    return Select(
        value.id,
        value.expression.source,
        tuple(_drakon_case(item) for item in value.cases),
        value.mode,
        value.preferred_case_id,
    )


def _drakon_loop(value: ProgramLoop) -> Loop:
    return Loop(
        value.id,
        value.loop_kind,
        drakon_sequence(value.body),
        drakon_sequence(value.else_body),
        value.condition.source,
        value.target.source,
        value.iterable.source,
        value.children.source,
        value.delay_seconds.source,
    )


def _drakon_context_item(value: ProgramContextItem) -> ContextItem:
    return ContextItem(
        value.id,
        value.expression.source,
        value.target.source if value.target is not None else None,
    )


def _drakon_with(value: ProgramWith) -> With:
    return With(
        value.id,
        tuple(_drakon_context_item(item) for item in value.contexts),
        drakon_sequence(value.body),
        value.asynchronous,
    )


def _drakon_exception_handler(value: ProgramExceptionHandler) -> ExceptionHandler:
    return ExceptionHandler(
        value.id,
        value.exception.source if value.exception is not None else "",
        value.name.source if value.name is not None else None,
        drakon_sequence(value.body),
    )


def _drakon_try(value: ProgramTry) -> Try:
    return Try(
        value.id,
        drakon_sequence(value.body),
        tuple(_drakon_exception_handler(item) for item in value.handlers),
        drakon_sequence(value.else_body),
        drakon_sequence(value.finally_body),
        value.except_star,
    )


def _drakon_synchronizer(value: ProgramSynchronizer) -> Synchronizer:
    return Synchronizer(
        value.id,
        value.timer,
        value.deadline.source,
        drakon_sequence(value.on_time),
        drakon_sequence(value.on_timeout),
        value.preferred_on_time,
    )


def _drakon_parallel_branch(value: ProgramParallelBranch) -> ParallelBranch:
    return ParallelBranch(
        value.id,
        value.name,
        drakon_sequence(value.body),
    )


def _drakon_parallel(value: ProgramParallel) -> Parallel:
    return Parallel(
        value.id,
        tuple(_drakon_parallel_branch(item) for item in value.branches),
        value.mode,
    )


def _drakon_silhouette_branch(value: ProgramSilhouetteBranch) -> SilhouetteBranch:
    return SilhouetteBranch(
        value.id,
        value.name,
        drakon_sequence(value.body),
        value.target_branch_id,
    )


def _drakon_silhouette(value: ProgramSilhouette) -> Silhouette:
    return Silhouette(
        value.id,
        value.display_name,
        value.identifier,
        tuple(_drakon_silhouette_branch(item) for item in value.branches),
        value.initial_branch_id,
    )


def drakon_from_program(
    function: ProgramFunction,
    view: DrakonViewDefinition,
    template: DrakonDiagram | None = None,
    *,
    model: ProgramModel,
    locations: Mapping[str, ProgramFunctionLocation] | None = None,
) -> DrakonDiagram:
    """Project a function; the optional template contributes presentation metadata."""
    return DrakonDiagram(
        view.document_id,
        view.title,
        Header(view.header_id, function_spec(function, model, locations=locations)),
        drakon_sequence(function.body),
        End(view.end_id),
        template.description if template is not None else "",
        template.extensions if template is not None else (),
    )
