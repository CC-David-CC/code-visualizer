"""Pure, local operations over the canonical executable program graph."""

from __future__ import annotations

import hashlib
import keyword
from collections.abc import Callable, Iterator
from dataclasses import fields, is_dataclass, replace

from code_visualizer.domain.expression import (
    AttributeExpression,
    ExpressionContext,
    ExpressionNode,
    SymbolReferenceExpression,
    expression_children,
    map_expression_tree,
    parse_expression_tree,
    reconcile_expression_trees,
)
from code_visualizer.domain.program import (
    ExpressionRole,
    ProgramAssignment,
    ProgramCall,
    ProgramExpression,
    ProgramFunction,
    ProgramIf,
    ProgramModel,
    ProgramOutput,
    ProgramSequence,
    ProgramStatement,
    ProgramSymbol,
    ProgramSymbolKind,
    expression_parse_mode,
    iter_program_nodes,
    make_program_expression,
    map_program,
    program_expressions,
    program_node_id,
    program_sequences,
    program_statements,
)


class ProgramEditError(ValueError):
    """A canonical edit cannot be applied without violating local invariants."""


def require_identifier(value: str, *, label: str = "name") -> str:
    if not value.isidentifier() or keyword.iskeyword(value):
        raise ProgramEditError(f"{label} must be a valid non-keyword Python identifier")
    return value


def stable_symbol_id(function_id: str, declaration_id: str, name: str) -> str:
    digest = hashlib.sha256(f"{function_id}\0{declaration_id}\0{name}".encode()).hexdigest()[:24]
    return f"symbol_{digest}"


def iter_sequences(value: ProgramSequence) -> Iterator[ProgramSequence]:
    yield from program_sequences(value)


def iter_statements(value: ProgramSequence) -> Iterator[ProgramStatement]:
    yield from program_statements(value)


def find_sequence(value: ProgramFunction, sequence_id: str) -> ProgramSequence | None:
    return next((item for item in iter_sequences(value.body) if item.id == sequence_id), None)


def _replace_sequence_tree(
    current: ProgramSequence,
    replacement: ProgramSequence,
) -> tuple[ProgramSequence, bool]:
    found = any(item.id == replacement.id for item in program_sequences(current))
    return map_program(
        current,
        sequence_mapper=lambda item: replacement if item.id == replacement.id else item,
    ), found


def replace_sequence(value: ProgramFunction, replacement: ProgramSequence) -> ProgramFunction:
    body, found = _replace_sequence_tree(value.body, replacement)
    if not found:
        raise ProgramEditError(f"Program sequence {replacement.id!r} does not exist")
    return replace(value, body=body)


def replace_function(model: ProgramModel, function: ProgramFunction) -> ProgramModel:
    if model.function(function.id) is None:
        raise ProgramEditError(f"Program function {function.id!r} does not exist")
    return replace(
        model,
        functions=tuple(function if item.id == function.id else item for item in model.functions),
    )


def replace_statement(
    function: ProgramFunction,
    replacement: ProgramStatement,
) -> ProgramFunction:
    """Replace one statement in place while preserving every ordering boundary."""

    found = False

    def replace_in_sequence(sequence: ProgramSequence) -> ProgramSequence:
        nonlocal found
        statements: list[ProgramStatement] = []
        for statement in sequence.statements:
            if statement.id == replacement.id:
                statements.append(replacement)
                found = True
            else:
                statements.append(statement)
        return replace(sequence, statements=tuple(statements))

    updated = map_program(function, sequence_mapper=replace_in_sequence)
    if not found:
        raise ProgramEditError(f"Program statement {replacement.id!r} does not exist")
    return updated


def resolve_symbol(
    model: ProgramModel,
    function_id: str,
) -> Callable[[str, ExpressionContext], str | None]:
    local = {
        item.name: item.id
        for item in model.symbols
        if item.owner_id == function_id and item.kind is not ProgramSymbolKind.FUNCTION
    }
    global_functions = {
        item.name: item.id for item in model.symbols if item.kind is ProgramSymbolKind.FUNCTION
    }

    def resolve(name: str, _context: ExpressionContext) -> str | None:
        return local.get(name, global_functions.get(name))

    return resolve


def expression_symbol_ids(value: ProgramExpression) -> frozenset[str]:
    result: set[str] = set()

    def collect(node: ExpressionNode) -> None:
        if isinstance(node, SymbolReferenceExpression) and node.symbol_id is not None:
            result.add(node.symbol_id)
        for _field, child in expression_children(node):
            collect(child)

    collect(value.tree)
    return frozenset(result)


def _stored_names(value: ProgramExpression) -> tuple[str, ...]:
    result: list[str] = []

    def collect(node: ExpressionNode) -> None:
        if isinstance(node, SymbolReferenceExpression) and node.context is ExpressionContext.STORE:
            result.append(node.name)
        for _field, child in expression_children(node):
            collect(child)

    collect(value.tree)
    return tuple(dict.fromkeys(result))


def _new_local_symbols(
    model: ProgramModel,
    function_id: str,
    declaration_id: str,
    target_source: str | None,
) -> tuple[ProgramSymbol, ...]:
    if target_source is None:
        return ()
    provisional = make_program_expression(
        declaration_id,
        "target",
        target_source,
        ExpressionRole.TARGET,
        resolve_symbol=resolve_symbol(model, function_id),
    )
    existing = {
        item.name
        for item in model.symbols
        if item.owner_id == function_id and item.kind is not ProgramSymbolKind.FUNCTION
    }
    return tuple(
        ProgramSymbol(
            stable_symbol_id(function_id, declaration_id, name),
            require_identifier(name, label="assignment target"),
            ProgramSymbolKind.LOCAL,
            function_id,
            declaration_id,
        )
        for name in _stored_names(provisional)
        if name not in existing
    )


def statement_local_symbols(
    model: ProgramModel,
    function_id: str,
    statement: ProgramStatement,
) -> tuple[ProgramSymbol, ...]:
    """Declare stored names in a complete canonical subtree before binding it."""
    expanded = model
    added: list[ProgramSymbol] = []
    for node in iter_program_nodes(statement):
        if isinstance(node, ProgramExpression) or not is_dataclass(node) or isinstance(node, type):
            continue
        for field in fields(node):
            expression = getattr(node, field.name)
            if not isinstance(expression, ProgramExpression):
                continue
            names = _stored_names(expression)
            if not names:
                continue
            symbols = _new_local_symbols(
                expanded, function_id, program_node_id(node), ", ".join(names)
            )
            added.extend(symbols)
            expanded = replace(expanded, symbols=(*expanded.symbols, *symbols))
    return tuple(added)


def reconcile_function_locals(model: ProgramModel, function: ProgramFunction) -> ProgramModel:
    """Reconcile declarations after a structural edit, retaining surviving identities."""

    previous = tuple(
        item
        for item in model.symbols
        if item.owner_id == function.id and item.kind is ProgramSymbolKind.LOCAL
    )
    retained = tuple(item for item in model.symbols if item not in previous)
    candidate = replace(model, symbols=retained)
    generated: list[ProgramSymbol] = []
    for statement in function.body.statements:
        added = statement_local_symbols(candidate, function.id, statement)
        generated.extend(added)
        candidate = replace(candidate, symbols=(*candidate.symbols, *added))
    used: set[str] = set()
    surviving_names = {item.name for item in generated}
    reserved = {item.id for item in previous if item.name in surviving_names}
    reconciled: list[ProgramSymbol] = []
    for symbol in generated:
        match = next(
            (item for item in previous if item.id not in used and item.name == symbol.name),
            None,
        )
        if match is None:
            match = next(
                (
                    item
                    for item in previous
                    if item.id not in used
                    and item.id not in reserved
                    and item.declaration_id == symbol.declaration_id
                ),
                None,
            )
        if match is not None:
            symbol = replace(symbol, id=match.id)
        used.add(symbol.id)
        reconciled.append(symbol)
    replacements = {item.id: item for item in (*retained, *reconciled)}
    existing_ids = {item.id for item in model.symbols}
    return replace(
        model,
        symbols=(
            *(replacements[item.id] for item in model.symbols if item.id in replacements),
            *(item for item in reconciled if item.id not in existing_ids),
        ),
    )


def build_statement(
    model: ProgramModel,
    function_id: str,
    statement_id: str,
    statement_kind: str,
    *,
    target: str | None = None,
    value: str | None = None,
    annotation: str | None = None,
    operator: str = "=",
    expression: str | None = None,
    arguments: str = "",
    awaited: bool = False,
    result_target: str | None = None,
    target_function_id: str | None = None,
    destination: str | None = None,
    end: str | None = None,
    condition: str | None = None,
    preferred_truth: bool = True,
    true_sequence_id: str,
    false_sequence_id: str,
) -> tuple[ProgramStatement, tuple[ProgramSymbol, ...]]:
    if statement_kind not in {"assignment", "output", "call", "if"}:
        raise ProgramEditError("statement_kind must be assignment, output, call, or if")
    target_source = target if statement_kind == "assignment" else result_target
    new_symbols = _new_local_symbols(model, function_id, statement_id, target_source)
    expanded = replace(model, symbols=(*model.symbols, *new_symbols))
    resolver = resolve_symbol(expanded, function_id)

    def make(field: str, source: str, role: ExpressionRole) -> ProgramExpression:
        return make_program_expression(
            statement_id,
            field,
            source,
            role,
            resolve_symbol=resolver,
        )

    if statement_kind == "assignment":
        if target is None or value is None:
            raise ProgramEditError("canonical assignment requires target and value")
        if not operator:
            raise ProgramEditError("assignment operator must not be empty")
        target_expression = make("target", target, ExpressionRole.TARGET)
        assignment_statement = ProgramAssignment(
            statement_id,
            target_expression,
            make("value", value, ExpressionRole.VALUE),
            make("annotation", annotation, ExpressionRole.ANNOTATION)
            if annotation is not None
            else None,
            operator,
            tuple(
                item.symbol_id
                for item in _symbol_references(target_expression)
                if item.context is ExpressionContext.STORE and item.symbol_id is not None
            ),
        )
        return assignment_statement, new_symbols
    if statement_kind == "output":
        if expression is None:
            raise ProgramEditError("canonical output requires expression")
        return (
            ProgramOutput(
                statement_id,
                make("expression", expression, ExpressionRole.EXPRESSION),
                (
                    make("destination", destination, ExpressionRole.DESTINATION)
                    if destination is not None
                    else None
                ),
                make("end", end, ExpressionRole.END) if end is not None else None,
            ),
            (),
        )
    if statement_kind == "call":
        if expression is None:
            raise ProgramEditError("canonical call requires expression")
        if target_function_id is not None and expanded.function(target_function_id) is None:
            raise ProgramEditError(
                f"Target function {target_function_id!r} does not exist in ProgramModel"
            )
        call_target = (
            make("result_target", result_target, ExpressionRole.TARGET)
            if result_target is not None
            else None
        )
        call_statement = ProgramCall(
            statement_id,
            make("expression", expression, ExpressionRole.CALL),
            make("arguments", arguments, ExpressionRole.ARGUMENTS),
            awaited,
            call_target,
            target_function_id,
            tuple(
                item.symbol_id
                for item in _symbol_references(call_target)
                if item.context is ExpressionContext.STORE and item.symbol_id is not None
            )
            if call_target is not None
            else (),
        )
        return call_statement, new_symbols
    if condition is None:
        raise ProgramEditError("canonical if requires condition")
    return (
        ProgramIf(
            statement_id,
            make("condition", condition, ExpressionRole.CONDITION),
            ProgramSequence(true_sequence_id),
            ProgramSequence(false_sequence_id),
            preferred_truth,
        ),
        (),
    )


def _symbol_references(value: ProgramExpression | None) -> tuple[SymbolReferenceExpression, ...]:
    if value is None:
        return ()
    result: list[SymbolReferenceExpression] = []

    def collect(node: ExpressionNode) -> None:
        if isinstance(node, SymbolReferenceExpression):
            result.append(node)
        for _field, child in expression_children(node):
            collect(child)

    collect(value.tree)
    return tuple(result)


def iter_expressions(value: ProgramFunction) -> Iterator[ProgramExpression]:
    yield from program_expressions(value)


def map_function_expressions(
    value: ProgramFunction,
    mapper: Callable[[ProgramExpression], ProgramExpression],
) -> ProgramFunction:
    return map_program(value, expression_mapper=mapper)


def rebind_function_expressions(model: ProgramModel, value: ProgramFunction) -> ProgramFunction:
    """Re-resolve every expression after declarations or global names change."""

    resolver = resolve_symbol(model, value.id)

    def rebind(expression: ProgramExpression) -> ProgramExpression:
        def bind(node: ExpressionNode) -> ExpressionNode:
            if isinstance(node, SymbolReferenceExpression):
                return replace(
                    node,
                    symbol_id=resolver(node.name, node.context),
                )
            return node

        return replace(expression, tree=map_expression_tree(expression.tree, bind))

    return map_function_expressions(value, rebind)


def refresh_written_symbols(value: ProgramFunction) -> ProgramFunction:
    def refresh(sequence: ProgramSequence) -> ProgramSequence:
        statements: list[ProgramStatement] = []
        for statement in sequence.statements:
            if isinstance(statement, ProgramAssignment):
                statements.append(
                    replace(
                        statement,
                        written_symbol_ids=tuple(
                            item.symbol_id
                            for item in _symbol_references(statement.target)
                            if item.context is ExpressionContext.STORE
                            and item.symbol_id is not None
                        ),
                    )
                )
            elif isinstance(statement, ProgramCall):
                statements.append(
                    replace(
                        statement,
                        written_symbol_ids=(
                            tuple(
                                item.symbol_id
                                for item in _symbol_references(statement.result_target)
                                if item.context is ExpressionContext.STORE
                                and item.symbol_id is not None
                            )
                            if statement.result_target is not None
                            else ()
                        ),
                    )
                )
            else:
                statements.append(statement)
        return replace(sequence, statements=tuple(statements))

    return map_program(value, sequence_mapper=refresh)


def replace_expression_source(
    model: ProgramModel,
    function: ProgramFunction,
    expression_id: str,
    source: str,
) -> tuple[ProgramFunction, ProgramExpression]:
    previous = next((item for item in iter_expressions(function) if item.id == expression_id), None)
    if previous is None:
        raise ProgramEditError(f"Program expression {expression_id!r} does not exist")
    mode = expression_parse_mode(previous.role)
    provisional = parse_expression_tree(
        previous.id,
        source,
        mode=mode,
        resolve_symbol=resolve_symbol(model, function.id),
    )
    replacement = replace(
        previous,
        tree=reconcile_expression_trees(
            previous.tree,
            provisional,
        ),
    )
    return (
        map_function_expressions(
            function,
            lambda item: replacement if item.id == expression_id else item,
        ),
        previous,
    )


def replace_output_sources(
    model: ProgramModel,
    function: ProgramFunction,
    statement_id: str,
    *,
    expression: str,
    destination: str | None,
    end: str | None,
) -> ProgramFunction:
    """Apply one complete output edit without disturbing unrelated expression trees."""

    current = next(
        (
            statement
            for statement in iter_statements(function.body)
            if statement.id == statement_id and isinstance(statement, ProgramOutput)
        ),
        None,
    )
    if current is None:
        raise ProgramEditError(f"Program output {statement_id!r} does not exist")
    resolver = resolve_symbol(model, function.id)

    def expression_value(
        field: str,
        source: str | None,
        role: ExpressionRole,
        previous: ProgramExpression | None,
    ) -> ProgramExpression | None:
        if source is None:
            return None
        if previous is not None and previous.source == source:
            return previous
        provisional = make_program_expression(
            statement_id,
            field,
            source,
            role,
            resolve_symbol=resolver,
        )
        if previous is None:
            return provisional
        return replace(
            provisional,
            tree=reconcile_expression_trees(previous.tree, provisional.tree),
        )

    output_expression = expression_value(
        "expression",
        expression,
        ExpressionRole.EXPRESSION,
        current.expression,
    )
    assert output_expression is not None
    replacement = ProgramOutput(
        current.id,
        output_expression,
        expression_value(
            "destination",
            destination,
            ExpressionRole.DESTINATION,
            current.destination,
        ),
        expression_value("end", end, ExpressionRole.END, current.end),
    )
    return replace_statement(function, replacement)


def rename_symbol(
    model: ProgramModel,
    symbol: ProgramSymbol,
    new_name: str,
) -> ProgramModel:
    new_name = require_identifier(new_name, label="symbol name")
    if new_name == symbol.name:
        return model
    if any(
        item.id != symbol.id
        and item.owner_id == symbol.owner_id
        and item.name == new_name
        and item.kind is not ProgramSymbolKind.FUNCTION
        for item in model.symbols
    ):
        raise ProgramEditError(f"Symbol {new_name!r} already exists in this function")
    renamed_symbols = tuple(
        replace(item, name=new_name) if item.id == symbol.id else item for item in model.symbols
    )
    renamed_model = replace(model, symbols=renamed_symbols)
    functions: list[ProgramFunction] = []
    for function in model.functions:
        is_function_symbol = symbol.kind is ProgramSymbolKind.FUNCTION

        def rename_expression(
            value: ProgramExpression,
            current_function: ProgramFunction = function,
            function_symbol: bool = is_function_symbol,
        ) -> ProgramExpression:
            references_symbol = symbol.id in expression_symbol_ids(value)
            targeted_call = False
            if function_symbol:
                targeted_call = any(
                    isinstance(statement, ProgramCall)
                    and statement.target_function_id == symbol.owner_id
                    and statement.expression.id == value.id
                    for sequence in iter_sequences(current_function.body)
                    for statement in sequence.statements
                )
            if not references_symbol and not targeted_call:
                return value

            def rename_reference(node: ExpressionNode) -> ExpressionNode:
                if isinstance(node, SymbolReferenceExpression) and node.symbol_id == symbol.id:
                    return replace(node, name=new_name)
                return node

            tree = map_expression_tree(value.tree, rename_reference)
            if targeted_call:
                if isinstance(tree, SymbolReferenceExpression):
                    tree = replace(tree, name=new_name, symbol_id=symbol.id)
                elif isinstance(tree, AttributeExpression):
                    tree = replace(tree, attribute=new_name)

            resolver = resolve_symbol(renamed_model, current_function.id)

            def rebind(node: ExpressionNode) -> ExpressionNode:
                if isinstance(node, SymbolReferenceExpression):
                    return replace(node, symbol_id=resolver(node.name, node.context))
                return node

            return replace(value, tree=map_expression_tree(tree, rebind))

        updated = map_function_expressions(function, rename_expression)
        if symbol.kind is ProgramSymbolKind.FUNCTION and function.id == symbol.owner_id:
            updated = replace(updated, identifier=new_name)
        updated = replace(
            updated,
            parameters=tuple(
                replace(item, name=new_name) if item.symbol_id == symbol.id else item
                for item in updated.parameters
            ),
        )
        functions.append(updated)
    return replace(renamed_model, functions=tuple(functions))
