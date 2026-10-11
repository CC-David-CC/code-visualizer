"""Feature-owned authority handlers for canonical executable edits."""

from __future__ import annotations

from dataclasses import replace
from typing import cast

from code_visualizer.application.authority import CommandError, Handler, Mutation
from code_visualizer.application.commands import Operation
from code_visualizer.application.features.program.model_ops import (
    ProgramEditError,
    build_statement,
    find_sequence,
    iter_expressions,
    iter_sequences,
    iter_statements,
    map_function_expressions,
    rebind_function_expressions,
    reconcile_function_locals,
    refresh_written_symbols,
    rename_symbol,
    replace_expression_source,
    replace_function,
    replace_output_sources,
    replace_sequence,
    replace_statement,
    require_identifier,
    statement_local_symbols,
)
from code_visualizer.application.features.program.ownership import (
    attach_function,
    header_operation,
    ownership_handlers,
    remove_function_reference,
)
from code_visualizer.application.program_model import project_program_changes
from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.program import (
    ProgramCall,
    ProgramExpression,
    ProgramFunction,
    ProgramModel,
    ProgramOutput,
    ProgramSequence,
    ProgramStatement,
    ProgramSymbol,
    ProgramSymbolKind,
    iter_program_nodes,
    program_node_id,
)
from code_visualizer.domain.program_kinds import CallableKind
from code_visualizer.domain.project import Project
from code_visualizer.domain.projection import DrakonViewDefinition
from code_visualizer.persistence.decoding import (
    document_from_data,
    program_expression_from_data,
    program_function_from_data,
    program_statement_from_data,
)
from code_visualizer.persistence.serialization import (
    document_to_data,
    program_expression_to_data,
    program_function_to_data,
    program_statement_to_data,
)


def _text(payload: dict[str, JsonValue], key: str, *, empty: bool = False) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or (not empty and not value.strip()):
        suffix = "text" if empty else "non-empty text"
        raise CommandError("COMMAND_INVALID_PAYLOAD", f"{key} must be {suffix}")
    return value


def _optional_text(payload: dict[str, JsonValue], key: str) -> str | None:
    value = payload.get(key)
    if value is not None and not isinstance(value, str):
        raise CommandError("COMMAND_INVALID_PAYLOAD", f"{key} must be text or null")
    return value


def _integer(payload: dict[str, JsonValue], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise CommandError("COMMAND_INVALID_PAYLOAD", f"{key} must be an integer")
    return value


def _boolean(payload: dict[str, JsonValue], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise CommandError("COMMAND_INVALID_PAYLOAD", f"{key} must be a boolean")
    return value


def _text_list(payload: dict[str, JsonValue], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise CommandError(
            "COMMAND_INVALID_PAYLOAD",
            f"{key} must be a non-empty text array",
        )
    result = cast(list[str], value)
    if len(set(result)) != len(result):
        raise CommandError("PROGRAM_DUPLICATE_ID", f"{key} cannot contain duplicates")
    return tuple(result)


def _function(project: Project, function_id: str) -> ProgramFunction:
    function = project.program_model.function(function_id)
    if function is None:
        raise CommandError(
            "PROGRAM_FUNCTION_NOT_FOUND",
            f"Program function {function_id!r} does not exist",
        )
    return function


def _program_error(exc: (ValueError | ProgramEditError)) -> CommandError:
    return CommandError("PROGRAM_EDIT_INVALID", str(exc))


def _symbol_payload(value: ProgramSymbol, index: int) -> dict[str, JsonValue]:
    return {
        "declaration_id": value.declaration_id,
        "id": value.id,
        "index": index,
        "kind": value.kind.value,
        "name": value.name,
        "owner_id": value.owner_id,
    }


def _symbol_from_payload(value: object) -> tuple[int, ProgramSymbol]:
    if not isinstance(value, dict):
        raise CommandError("COMMAND_INVALID_PAYLOAD", "restored symbol must be an object")
    raw = {str(key): item for key, item in value.items()}
    index = _integer(raw, "index")
    try:
        kind = ProgramSymbolKind(_text(raw, "kind"))
    except ValueError as exc:
        raise _program_error(exc) from exc
    return (
        index,
        ProgramSymbol(
            _text(raw, "id"),
            _text(raw, "name"),
            kind,
            _text(raw, "owner_id"),
            _text(raw, "declaration_id"),
        ),
    )


def _view_payload(value: DrakonViewDefinition) -> dict[str, JsonValue]:
    return {
        "document_id": value.document_id,
        "end_id": value.end_id,
        "function_id": value.function_id,
        "header_id": value.header_id,
        "title": value.title,
    }


def _view_from_payload(value: object) -> DrakonViewDefinition:
    if not isinstance(value, dict):
        raise CommandError("COMMAND_INVALID_PAYLOAD", "restored view must be an object")
    raw = {str(key): item for key, item in value.items()}
    return DrakonViewDefinition(
        _text(raw, "document_id"),
        _text(raw, "function_id"),
        _text(raw, "title"),
        _text(raw, "header_id"),
        _text(raw, "end_id"),
    )


def _create_function(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    function_id = _text(payload, "function_id")
    symbol_id = _text(payload, "symbol_id")
    sequence_id = _text(payload, "body_sequence_id")
    try:
        identifier = require_identifier(_text(payload, "identifier"), label="function name")
        owner_id = _text(payload, "owner_id")
    except (ValueError, ProgramEditError) as exc:
        raise _program_error(exc) from exc
    if project.program_model.function(function_id) is not None:
        raise CommandError("PROGRAM_DUPLICATE_ID", f"Function {function_id!r} already exists")
    if any(item.id == symbol_id for item in project.program_model.symbols):
        raise CommandError("PROGRAM_DUPLICATE_ID", f"Symbol {symbol_id!r} already exists")
    if any(
        item.identifier == identifier
        and (existing_owner := project.program_model.owner_of(item.id)) is not None
        and existing_owner.id == owner_id
        for item in project.program_model.functions
    ):
        raise CommandError(
            "PROGRAM_DUPLICATE_FUNCTION",
            f"Function {identifier!r} already exists in owner {owner_id!r}",
        )
    display_name = _optional_text(payload, "display_name") or identifier.replace("_", " ").title()
    symbol = ProgramSymbol(
        symbol_id,
        identifier,
        ProgramSymbolKind.FUNCTION,
        function_id,
        function_id,
    )
    function = ProgramFunction(
        function_id,
        symbol_id,
        identifier,
        display_name,
        CallableKind.SYNC,
        (),
        None,
        (),
        None,
        None,
        ProgramSequence(sequence_id),
    )
    model = replace(
        project.program_model,
        functions=(*project.program_model.functions, function),
        symbols=(*project.program_model.symbols, symbol),
    )
    model = attach_function(model, function_id, owner_id)
    return Mutation(
        project_program_changes(project, model, function_ids=frozenset({function_id})),
        "program.function_created",
        {"function_id": function_id, "identifier": identifier, "owner_id": owner_id},
        (function_id, symbol_id, sequence_id),
        Operation("program.function.delete", {"function_id": function_id}),
    )


def _delete_function(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    function_id = _text(payload, "function_id")
    function = _function(project, function_id)
    callers = tuple(
        statement.id
        for statement in iter_program_nodes(
            (
                tuple(
                    owner for owner in project.program_model.functions if owner.id != function_id
                ),
                project.program_model.modules,
                project.program_model.entrypoint,
            )
        )
        if isinstance(statement, ProgramCall) and statement.target_function_id == function_id
    )
    if callers:
        raise CommandError(
            "PROGRAM_FUNCTION_IN_USE",
            f"Function {function.identifier!r} is called by {len(callers)} canonical statement(s)",
            details={"caller_ids": list(callers)},
        )
    function_index = project.program_model.functions.index(function)
    symbols = tuple(
        (index, item)
        for index, item in enumerate(project.program_model.symbols)
        if item.owner_id == function_id
    )
    views = tuple(item for item in project.drakon_views if item.function_id == function_id)
    document_ids = {item.document_id for item in views}
    documents = tuple(
        (index, item) for index, item in enumerate(project.documents) if item.id in document_ids
    )
    model = replace(
        project.program_model,
        functions=tuple(item for item in project.program_model.functions if item.id != function_id),
        symbols=tuple(
            item for item in project.program_model.symbols if item.owner_id != function_id
        ),
    )
    previous_header = header_operation(project.program_model)
    model = remove_function_reference(model, function_id)
    if model.entrypoint is not None and model.entrypoint.callable_id == function_id:
        model = replace(model, entrypoint=replace(model.entrypoint, callable_id=None))
    candidate = replace(
        project,
        program_model=model,
        drakon_views=tuple(
            item for item in project.drakon_views if item.function_id != function_id
        ),
        documents=tuple(item for item in project.documents if item.id not in document_ids),
    )
    inverse = Operation(
        "program.function.restore",
        {
            "documents": [
                {"document": document_to_data(item), "index": index} for index, item in documents
            ],
            "program_header": previous_header.payload,
            "function": program_function_to_data(function),
            "function_index": function_index,
            "symbols": [_symbol_payload(item, index) for index, item in symbols],
            "views": [_view_payload(item) for item in views],
        },
    )
    return Mutation(
        candidate,
        "program.function_deleted",
        {
            "function_id": function_id,
            "removed_view_ids": cast(list[JsonValue], sorted(document_ids)),
        },
        tuple(
            dict.fromkeys(
                [function_id, *(item.id for _index, item in symbols), *sorted(document_ids)]
            )
        ),
        inverse,
    )


def _restore_function(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    try:
        function = program_function_from_data(payload.get("function"), "$.command.function")
    except ValueError as exc:
        raise _program_error(exc) from exc
    if project.program_model.function(function.id) is not None:
        raise CommandError("PROGRAM_DUPLICATE_ID", f"Function {function.id!r} already exists")
    function_index = _integer(payload, "function_index")
    functions = list(project.program_model.functions)
    if function_index < 0 or function_index > len(functions):
        raise CommandError("COMMAND_INVALID_PAYLOAD", "function restore index is out of range")
    functions.insert(function_index, function)
    raw_symbols = payload.get("symbols")
    if not isinstance(raw_symbols, list):
        raise CommandError("COMMAND_INVALID_PAYLOAD", "symbols must be an array")
    symbols = list(project.program_model.symbols)
    restored_symbols = tuple(_symbol_from_payload(item) for item in raw_symbols)
    for index, symbol in sorted(restored_symbols, key=lambda item: item[0]):
        if any(item.id == symbol.id for item in symbols):
            raise CommandError("PROGRAM_DUPLICATE_ID", f"Symbol {symbol.id!r} already exists")
        if index < 0 or index > len(symbols):
            raise CommandError("COMMAND_INVALID_PAYLOAD", "symbol restore index is out of range")
        symbols.insert(index, symbol)
    raw_views = payload.get("views")
    if not isinstance(raw_views, list):
        raise CommandError("COMMAND_INVALID_PAYLOAD", "views must be an array")
    views = tuple(_view_from_payload(item) for item in raw_views)
    raw_documents = payload.get("documents")
    if not isinstance(raw_documents, list):
        raise CommandError("COMMAND_INVALID_PAYLOAD", "documents must be an array")
    restored_documents: list[tuple[int, dict[str, JsonValue]]] = []
    for raw in raw_documents:
        if not isinstance(raw, dict):
            raise CommandError("COMMAND_INVALID_PAYLOAD", "document restore must be an object")
        restored = {str(key): item for key, item in raw.items()}
        index = _integer(restored, "index")
        restored_documents.append((index, restored))
    documents = list(project.documents)
    for index, restored in sorted(restored_documents, key=lambda item: item[0]):
        try:
            document = document_from_data(restored.get("document"), "$.command.document")
        except ValueError as exc:
            raise _program_error(exc) from exc
        if any(item.id == document.id for item in documents):
            raise CommandError("PROGRAM_DUPLICATE_ID", f"Document {document.id!r} already exists")
        if index < 0 or index > len(documents):
            raise CommandError("COMMAND_INVALID_PAYLOAD", "document restore index is out of range")
        documents.insert(index, document)
    candidate = replace(
        project,
        program_model=replace(
            project.program_model, functions=tuple(functions), symbols=tuple(symbols)
        ),
        drakon_views=(*project.drakon_views, *views),
        documents=tuple(documents),
    )
    from code_visualizer.application.features.program.ownership import _configure

    raw_header = payload.get("program_header")
    if not isinstance(raw_header, dict):
        raise CommandError("COMMAND_INVALID_PAYLOAD", "program_header must be an object")
    candidate = _configure(candidate, raw_header).project
    return Mutation(
        candidate,
        "program.function_restored",
        {"function_id": function.id},
        tuple(
            dict.fromkeys(
                [
                    function.id,
                    *(item.id for _index, item in restored_symbols),
                    *(item.document_id for item in views),
                ]
            )
        ),
        Operation("program.function.delete", {"function_id": function.id}),
    )


def _insert_statement(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    function_id = _text(payload, "function_id")
    sequence_id = _text(payload, "sequence_id")
    statement_id = _text(payload, "statement_id")
    index = _integer(payload, "index")
    function = _function(project, function_id)
    sequence = find_sequence(function, sequence_id)
    if sequence is None:
        raise CommandError("PROGRAM_SEQUENCE_NOT_FOUND", f"Sequence {sequence_id!r} does not exist")
    if index < 0 or index > len(sequence.statements):
        raise CommandError("PROGRAM_INVALID_INSERTION", "Statement insertion is out of range")
    existing_ids = {item.id for item in iter_statements(function.body)} | {
        item.id for item in iter_sequences(function.body)
    }
    if statement_id in existing_ids:
        raise CommandError("PROGRAM_DUPLICATE_ID", f"Statement {statement_id!r} already exists")
    try:
        if payload.get("statement") is not None:
            statement = program_statement_from_data(payload["statement"], "$.command.statement")
            if statement.id != statement_id:
                raise ProgramEditError("The statement payload and statement_id must agree")
            added_symbols = statement_local_symbols(project.program_model, function_id, statement)
        else:
            statement, added_symbols = build_statement(
                project.program_model,
                function_id,
                statement_id,
                _text(payload, "statement_kind"),
                target=_optional_text(payload, "target"),
                value=_optional_text(payload, "value"),
                annotation=_optional_text(payload, "annotation"),
                operator=_text(payload, "operator"),
                expression=_optional_text(payload, "expression"),
                arguments=_text(payload, "arguments", empty=True),
                awaited=_boolean(payload, "awaited"),
                result_target=_optional_text(payload, "result_target"),
                target_function_id=_optional_text(payload, "target_function_id"),
                destination=_optional_text(payload, "destination"),
                end=_optional_text(payload, "end"),
                condition=_optional_text(payload, "condition"),
                preferred_truth=_boolean(payload, "preferred_truth"),
                true_sequence_id=_text(payload, "true_sequence_id"),
                false_sequence_id=_text(payload, "false_sequence_id"),
            )
    except (ValueError, ProgramEditError) as exc:
        raise _program_error(exc) from exc
    statements = list(sequence.statements)
    statements.insert(index, statement)
    updated = replace_sequence(function, replace(sequence, statements=tuple(statements)))
    model = replace(
        replace_function(project.program_model, updated),
        symbols=(*project.program_model.symbols, *added_symbols),
    )
    updated = refresh_written_symbols(rebind_function_expressions(model, updated))
    model = replace_function(model, updated)
    candidate = project_program_changes(project, model, function_ids=frozenset({function_id}))
    affected = tuple(
        dict.fromkeys(
            [function_id, sequence_id, statement_id, *(item.id for item in added_symbols)]
        )
    )
    return Mutation(
        candidate,
        "program.statement_inserted",
        {"function_id": function_id, "sequence_id": sequence_id, "statement_id": statement_id},
        affected,
        Operation(
            "program.statement.delete",
            {
                "function_id": function_id,
                "sequence_id": sequence_id,
                "statement_ids": [statement_id],
            },
        ),
        Operation(
            "program.statement.restore",
            {
                "function_id": function_id,
                "items": [{"index": index, "statement": program_statement_to_data(statement)}],
                "sequence_id": sequence_id,
                "symbols": [
                    _symbol_payload(item, len(project.program_model.symbols) + offset)
                    for offset, item in enumerate(added_symbols)
                ],
            },
        ),
    )


def _function_state_operation(project: Project, function: ProgramFunction) -> Operation:
    """Capture canonical semantic state for exact compensating history."""

    return Operation(
        "program.function.replace_exact",
        {
            "function": program_function_to_data(function),
            "symbols": [
                _symbol_payload(item, index)
                for index, item in enumerate(project.program_model.symbols)
                if item.owner_id == function.id
            ],
        },
    )


def _replace_exact_function(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    """Apply an already typed signature/body without consulting any projection."""

    try:
        desired = program_function_from_data(payload.get("function"), "$.command.function")
    except ValueError as exc:
        raise _program_error(exc) from exc
    current = _function(project, desired.id)
    raw_symbols = payload.get("symbols")
    if not isinstance(raw_symbols, list):
        raise CommandError("COMMAND_INVALID_PAYLOAD", "symbols must be an array")
    restored = tuple(_symbol_from_payload(item) for item in raw_symbols)
    if any(item.owner_id != desired.id for _index, item in restored):
        raise CommandError("COMMAND_INVALID_PAYLOAD", "symbols must belong to this function")
    symbols = [item for item in project.program_model.symbols if item.owner_id != desired.id]
    if len({item.id for _index, item in restored}) != len(restored) or any(
        item.id == other.id for _index, item in restored for other in symbols
    ):
        raise CommandError("PROGRAM_DUPLICATE_ID", "Function state contains duplicate symbols")
    for index, symbol in sorted(restored, key=lambda item: item[0]):
        if index < 0 or index > len(symbols):
            raise CommandError("COMMAND_INVALID_PAYLOAD", "symbol index is out of range")
        symbols.insert(index, symbol)
    model = replace(replace_function(project.program_model, desired), symbols=tuple(symbols))
    return Mutation(
        project_program_changes(project, model, function_ids=frozenset({desired.id})),
        "program.function_exactly_replaced",
        {"function_id": desired.id},
        (desired.id,),
        _function_state_operation(project, current),
    )


def _splice_statements(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    """Replace one sequence interval with a typed subtree in a single semantic edit."""

    function_id = _text(payload, "function_id")
    sequence_id = _text(payload, "sequence_id")
    index = _integer(payload, "index")
    count = _integer(payload, "delete_count")
    function = _function(project, function_id)
    sequence = find_sequence(function, sequence_id)
    if sequence is None:
        raise CommandError("PROGRAM_SEQUENCE_NOT_FOUND", f"Sequence {sequence_id!r} does not exist")
    if index < 0 or count < 0 or index + count > len(sequence.statements):
        raise CommandError("PROGRAM_INVALID_INSERTION", "Sequence splice is out of range")
    raw_statements = payload.get("statements")
    if not isinstance(raw_statements, list):
        raise CommandError("COMMAND_INVALID_PAYLOAD", "statements must be an array")
    try:
        statements = tuple(
            program_statement_from_data(item, "$.command.statements[]") for item in raw_statements
        )
    except ValueError as exc:
        raise _program_error(exc) from exc
    replacement = replace(
        sequence,
        statements=(
            *sequence.statements[:index],
            *statements,
            *sequence.statements[index + count :],
        ),
    )
    updated = replace_sequence(function, replacement)
    identities = [program_node_id(item) for item in iter_program_nodes(updated)]
    if len(set(identities)) != len(identities):
        raise CommandError("PROGRAM_DUPLICATE_ID", "Sequence splice contains duplicate identities")
    model = reconcile_function_locals(replace_function(project.program_model, updated), updated)
    updated = refresh_written_symbols(rebind_function_expressions(model, updated))
    model = replace_function(model, updated)
    candidate = project_program_changes(project, model, function_ids=frozenset({function_id}))
    return Mutation(
        candidate,
        "program.sequence_spliced",
        {"function_id": function_id, "sequence_id": sequence_id, "index": index},
        (function_id, sequence_id, *(item.id for item in statements)),
        _function_state_operation(project, function),
        _function_state_operation(candidate, updated),
    )


def _delete_statements(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    function_id = _text(payload, "function_id")
    sequence_id = _text(payload, "sequence_id")
    statement_ids = _text_list(payload, "statement_ids")
    function = _function(project, function_id)
    sequence = find_sequence(function, sequence_id)
    if sequence is None:
        raise CommandError("PROGRAM_SEQUENCE_NOT_FOUND", f"Sequence {sequence_id!r} does not exist")
    by_id = {item.id: (index, item) for index, item in enumerate(sequence.statements)}
    if any(item not in by_id for item in statement_ids):
        raise CommandError("PROGRAM_STATEMENT_NOT_FOUND", "A deleted statement does not exist")
    removed = tuple(by_id[item] for item in statement_ids)
    removed_tree_ids = {
        program_node_id(node)
        for _index, statement in removed
        for node in iter_program_nodes(statement)
        if not isinstance(node, ProgramExpression)
    }

    retained_statements = tuple(
        item for item in sequence.statements if item.id not in set(statement_ids)
    )
    updated = replace_sequence(function, replace(sequence, statements=retained_statements))
    model = reconcile_function_locals(replace_function(project.program_model, updated), updated)
    before_symbols = {item.id: item for item in project.program_model.symbols}
    after_symbols = {item.id: item for item in model.symbols}
    changed_symbol_ids = tuple(
        sorted(
            identifier
            for identifier in before_symbols.keys() | after_symbols.keys()
            if before_symbols.get(identifier) != after_symbols.get(identifier)
        )
    )
    removed_symbols = tuple(
        (index, item)
        for index, item in enumerate(project.program_model.symbols)
        if item.id in changed_symbol_ids
    )
    updated = refresh_written_symbols(rebind_function_expressions(model, updated))
    model = replace_function(model, updated)
    candidate = project_program_changes(project, model, function_ids=frozenset({function_id}))
    return Mutation(
        candidate,
        "program.statements_deleted",
        {
            "function_id": function_id,
            "sequence_id": sequence_id,
            "statement_ids": list(statement_ids),
        },
        tuple(
            dict.fromkeys(
                [
                    function_id,
                    sequence_id,
                    *removed_tree_ids,
                    *(item.id for _index, item in removed_symbols),
                ]
            )
        ),
        Operation(
            "program.statement.restore",
            {
                "function_id": function_id,
                "items": [
                    {"index": index, "statement": program_statement_to_data(item)}
                    for index, item in removed
                ],
                "sequence_id": sequence_id,
                "symbols": [_symbol_payload(item, index) for index, item in removed_symbols],
                "symbol_ids": list(changed_symbol_ids),
            },
        ),
    )


def _restore_statements(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    function_id = _text(payload, "function_id")
    sequence_id = _text(payload, "sequence_id")
    function = _function(project, function_id)
    sequence = find_sequence(function, sequence_id)
    if sequence is None:
        raise CommandError("PROGRAM_SEQUENCE_NOT_FOUND", f"Sequence {sequence_id!r} does not exist")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise CommandError("COMMAND_INVALID_PAYLOAD", "items must be a non-empty array")
    decoded: list[tuple[int, ProgramStatement]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise CommandError("COMMAND_INVALID_PAYLOAD", "restore item must be an object")
        item = {str(key): value for key, value in raw.items()}
        try:
            statement = program_statement_from_data(
                item.get("statement"), "$.command.items[].statement"
            )
        except ValueError as exc:
            raise _program_error(exc) from exc
        decoded.append((_integer(item, "index"), statement))
    existing_ids = {item.id for item in iter_statements(function.body)}
    if any(item.id in existing_ids for _index, item in decoded):
        raise CommandError("PROGRAM_DUPLICATE_ID", "A restored statement ID already exists")
    statements = list(sequence.statements)
    for index, statement in sorted(decoded, key=lambda item: item[0]):
        if index < 0 or index > len(statements):
            raise CommandError(
                "PROGRAM_INVALID_INSERTION", "Statement restore index is out of range"
            )
        statements.insert(index, statement)
    updated = replace_sequence(function, replace(sequence, statements=tuple(statements)))
    raw_symbols = payload.get("symbols")
    if not isinstance(raw_symbols, list):
        raise CommandError("COMMAND_INVALID_PAYLOAD", "symbols must be an array")
    raw_symbol_ids = payload.get("symbol_ids", [])
    if not isinstance(raw_symbol_ids, list) or not all(
        isinstance(item, str) for item in raw_symbol_ids
    ):
        raise CommandError("COMMAND_INVALID_PAYLOAD", "symbol_ids must be a text array")
    changed_symbol_ids = set(cast(list[str], raw_symbol_ids))
    if any(
        item.id in changed_symbol_ids and item.owner_id != function_id
        for item in project.program_model.symbols
    ):
        raise CommandError(
            "COMMAND_INVALID_PAYLOAD", "Restored symbols must belong to this function"
        )
    symbols = [item for item in project.program_model.symbols if item.id not in changed_symbol_ids]
    restored_symbols = tuple(_symbol_from_payload(item) for item in raw_symbols)
    for index, symbol in sorted(restored_symbols, key=lambda item: item[0]):
        if any(item.id == symbol.id for item in symbols):
            raise CommandError("PROGRAM_DUPLICATE_ID", f"Symbol {symbol.id!r} already exists")
        if index < 0 or index > len(symbols):
            raise CommandError("PROGRAM_INVALID_INSERTION", "Symbol restore index is out of range")
        symbols.insert(index, symbol)
    model = replace(
        replace_function(project.program_model, updated),
        symbols=tuple(symbols),
    )
    updated = refresh_written_symbols(rebind_function_expressions(model, updated))
    model = replace_function(model, updated)
    statement_ids = tuple(item.id for _index, item in decoded)
    return Mutation(
        project_program_changes(project, model, function_ids=frozenset({function_id})),
        "program.statements_restored",
        {"function_id": function_id, "statement_ids": list(statement_ids)},
        tuple(
            dict.fromkeys(
                [
                    function_id,
                    sequence_id,
                    *statement_ids,
                    *(item.id for _index, item in restored_symbols),
                ]
            )
        ),
        Operation(
            "program.statement.delete",
            {
                "function_id": function_id,
                "sequence_id": sequence_id,
                "statement_ids": list(statement_ids),
            },
        ),
    )


def _move_statements(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    function_id = _text(payload, "function_id")
    source_id = _text(payload, "source_sequence_id")
    destination_id = _text(payload, "destination_sequence_id")
    destination_index = _integer(payload, "destination_index")
    statement_ids = _text_list(payload, "statement_ids")
    function = _function(project, function_id)
    source = find_sequence(function, source_id)
    destination = find_sequence(function, destination_id)
    if source is None or destination is None:
        raise CommandError("PROGRAM_SEQUENCE_NOT_FOUND", "Move sequence does not exist")
    if destination_index < 0 or destination_index > len(destination.statements):
        raise CommandError("PROGRAM_INVALID_INSERTION", "Move destination is out of range")
    first_index = next(
        (index for index, item in enumerate(source.statements) if item.id == statement_ids[0]),
        -1,
    )
    moving = source.statements[first_index : first_index + len(statement_ids)]
    if first_index < 0 or tuple(item.id for item in moving) != statement_ids:
        raise CommandError(
            "PROGRAM_MOVE_NOT_CONTIGUOUS",
            "Moved statements must be contiguous and in sequence order",
        )
    owned_sequences = {
        nested.id
        for statement in moving
        for nested in iter_sequences(ProgramSequence("moving", (statement,)))
    }
    if destination_id in owned_sequences:
        raise CommandError("PROGRAM_MOVE_INTO_SELF", "A statement cannot move into its own branch")
    same = source_id == destination_id
    block_end = first_index + len(moving)
    if same and first_index <= destination_index <= block_end:
        raise CommandError("PROGRAM_MOVE_NOOP", "The block is already at that boundary")
    source_statements = list(source.statements)
    del source_statements[first_index:block_end]
    updated = replace_sequence(function, replace(source, statements=tuple(source_statements)))
    destination_after = find_sequence(updated, destination_id)
    if destination_after is None:
        raise CommandError("PROGRAM_SEQUENCE_NOT_FOUND", "Move destination disappeared")
    adjusted = (
        destination_index - len(moving)
        if same and destination_index > block_end
        else destination_index
    )
    destination_statements = list(destination_after.statements)
    destination_statements[adjusted:adjusted] = moving
    updated = replace_sequence(
        updated,
        replace(destination_after, statements=tuple(destination_statements)),
    )
    model = replace_function(project.program_model, updated)
    inverse_index = (
        first_index if not same or first_index <= adjusted else first_index + len(moving)
    )
    return Mutation(
        project_program_changes(project, model, function_ids=frozenset({function_id})),
        "program.statements_moved",
        {
            "destination_index": adjusted,
            "destination_sequence_id": destination_id,
            "function_id": function_id,
            "source_sequence_id": source_id,
            "statement_ids": list(statement_ids),
        },
        tuple(dict.fromkeys([function_id, source_id, destination_id, *statement_ids])),
        Operation(
            "program.statement.move",
            {
                "destination_index": inverse_index,
                "destination_sequence_id": source_id,
                "function_id": function_id,
                "source_sequence_id": destination_id,
                "statement_ids": list(statement_ids),
            },
        ),
    )


def _expression_map(function: ProgramFunction) -> dict[str, ProgramExpression]:
    return {item.id: item for item in iter_expressions(function)}


def _expression_state_operation(
    function_id: str,
    function: ProgramFunction,
    model: ProgramModel,
    *,
    expression_ids: tuple[str, ...],
    symbol_ids: tuple[str, ...],
) -> Operation:
    expressions = _expression_map(function)
    missing = tuple(item for item in expression_ids if item not in expressions)
    if missing:
        raise CommandError(
            "PROGRAM_EXPRESSION_NOT_FOUND",
            f"Cannot snapshot missing expression {missing[0]!r}",
        )
    symbol_id_set = set(symbol_ids)
    return Operation(
        "program.expression.restore",
        {
            "expression_ids": list(expression_ids),
            "expressions": [
                program_expression_to_data(expressions[item]) for item in expression_ids
            ],
            "function_id": function_id,
            "symbol_ids": list(symbol_ids),
            "symbols": [
                _symbol_payload(item, index)
                for index, item in enumerate(model.symbols)
                if item.id in symbol_id_set
            ],
        },
    )


def _restore_expression_state(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    """Restore exact semantic objects captured by history; never reparse source."""

    function_id = _text(payload, "function_id")
    function = _function(project, function_id)
    raw_expression_ids = payload.get("expression_ids")
    if (
        not isinstance(raw_expression_ids, list)
        or not raw_expression_ids
        or not all(isinstance(item, str) and item for item in raw_expression_ids)
    ):
        raise CommandError(
            "COMMAND_INVALID_PAYLOAD",
            "expression_ids must be a non-empty text array",
        )
    expression_ids = tuple(cast(list[str], raw_expression_ids))
    if len(set(expression_ids)) != len(expression_ids):
        raise CommandError("PROGRAM_DUPLICATE_ID", "expression_ids cannot contain duplicates")
    raw_expressions = payload.get("expressions")
    if not isinstance(raw_expressions, list) or len(raw_expressions) != len(expression_ids):
        raise CommandError(
            "COMMAND_INVALID_PAYLOAD",
            "expressions must match expression_ids",
        )
    try:
        desired_expressions = tuple(
            program_expression_from_data(item, "$.command.expressions[]")
            for item in raw_expressions
        )
    except ValueError as exc:
        raise _program_error(exc) from exc
    if tuple(item.id for item in desired_expressions) != expression_ids:
        raise CommandError(
            "COMMAND_INVALID_PAYLOAD",
            "restored expression identities must match expression_ids",
        )
    current_expressions = _expression_map(function)
    if any(item not in current_expressions for item in expression_ids):
        raise CommandError(
            "PROGRAM_EXPRESSION_NOT_FOUND",
            "A restored expression no longer exists in the function",
        )
    if any(
        desired.role is not current_expressions[desired.id].role for desired in desired_expressions
    ):
        raise CommandError(
            "COMMAND_INVALID_PAYLOAD",
            "History cannot change an expression's semantic role",
        )

    raw_symbol_ids = payload.get("symbol_ids")
    if not isinstance(raw_symbol_ids, list) or not all(
        isinstance(item, str) and item for item in raw_symbol_ids
    ):
        raise CommandError("COMMAND_INVALID_PAYLOAD", "symbol_ids must be a text array")
    symbol_ids = tuple(cast(list[str], raw_symbol_ids))
    if len(set(symbol_ids)) != len(symbol_ids):
        raise CommandError("PROGRAM_DUPLICATE_ID", "symbol_ids cannot contain duplicates")
    symbol_id_set = set(symbol_ids)
    raw_symbols = payload.get("symbols")
    if not isinstance(raw_symbols, list):
        raise CommandError("COMMAND_INVALID_PAYLOAD", "symbols must be an array")
    desired_symbols = tuple(_symbol_from_payload(item) for item in raw_symbols)
    if any(
        item.id not in symbol_id_set or item.owner_id != function_id
        for _index, item in desired_symbols
    ):
        raise CommandError(
            "COMMAND_INVALID_PAYLOAD",
            "restored symbols must belong to the affected function and identity set",
        )
    if len({item.id for _index, item in desired_symbols}) != len(desired_symbols):
        raise CommandError("PROGRAM_DUPLICATE_ID", "restored symbols cannot contain duplicates")

    inverse = _expression_state_operation(
        function_id,
        function,
        project.program_model,
        expression_ids=expression_ids,
        symbol_ids=symbol_ids,
    )
    replacements = {item.id: item for item in desired_expressions}
    updated = map_function_expressions(
        function,
        lambda item: replacements.get(item.id, item),
    )
    symbols = [item for item in project.program_model.symbols if item.id not in symbol_id_set]
    if any(item.id in {symbol.id for symbol in symbols} for _index, item in desired_symbols):
        raise CommandError("PROGRAM_DUPLICATE_ID", "A restored symbol ID already exists")
    for index, symbol in sorted(desired_symbols, key=lambda item: item[0]):
        if index < 0:
            raise CommandError("COMMAND_INVALID_PAYLOAD", "symbol index must not be negative")
        symbols.insert(min(index, len(symbols)), symbol)
    updated = refresh_written_symbols(updated)
    model = replace(
        replace_function(project.program_model, updated),
        symbols=tuple(symbols),
    )
    return Mutation(
        project_program_changes(project, model, function_ids=frozenset({function_id})),
        "program.expression_state_restored",
        {
            "expression_ids": list(expression_ids),
            "function_id": function_id,
        },
        tuple(dict.fromkeys([function_id, *expression_ids, *symbol_ids])),
        inverse,
    )


def _exact_statement_operation(function_id: str, statement: ProgramStatement) -> Operation:
    return Operation(
        "program.statement.replace_exact",
        {
            "function_id": function_id,
            "statement": program_statement_to_data(statement),
        },
    )


def _replace_exact_statement(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    """Restore one complete canonical statement without reparsing any expression."""

    function_id = _text(payload, "function_id")
    function = _function(project, function_id)
    try:
        desired = program_statement_from_data(
            payload.get("statement"),
            "$.command.statement",
        )
    except ValueError as exc:
        raise _program_error(exc) from exc
    current = next(
        (item for item in iter_statements(function.body) if item.id == desired.id),
        None,
    )
    if current is None:
        raise CommandError(
            "PROGRAM_STATEMENT_NOT_FOUND",
            f"Program statement {desired.id!r} does not exist",
        )
    if type(current) is not type(desired):
        raise CommandError(
            "PROGRAM_STATEMENT_KIND_MISMATCH",
            "Exact statement history cannot change a construct family",
        )
    try:
        updated = replace_statement(function, desired)
    except ProgramEditError as exc:
        raise _program_error(exc) from exc
    model = replace_function(project.program_model, updated)
    return Mutation(
        project_program_changes(project, model, function_ids=frozenset({function_id})),
        "program.statement_exactly_replaced",
        {"function_id": function_id, "statement_id": desired.id},
        (function_id, desired.id),
        _exact_statement_operation(function_id, current),
    )


def _replace_output(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    function_id = _text(payload, "function_id")
    statement_id = _text(payload, "statement_id")
    function = _function(project, function_id)
    current = next(
        (
            item
            for item in iter_statements(function.body)
            if item.id == statement_id and isinstance(item, ProgramOutput)
        ),
        None,
    )
    if current is None:
        raise CommandError(
            "PROGRAM_OUTPUT_NOT_FOUND",
            f"Program output {statement_id!r} does not exist",
        )
    try:
        updated = replace_output_sources(
            project.program_model,
            function,
            statement_id,
            expression=_text(payload, "expression", empty=True),
            destination=_optional_text(payload, "destination"),
            end=_optional_text(payload, "end"),
        )
    except ProgramEditError as exc:
        raise _program_error(exc) from exc
    replacement = next(
        item
        for item in iter_statements(updated.body)
        if item.id == statement_id and isinstance(item, ProgramOutput)
    )
    if replacement == current:
        raise CommandError("PROGRAM_EDIT_NOOP", "Output already has those expressions")
    model = replace_function(project.program_model, updated)
    return Mutation(
        project_program_changes(project, model, function_ids=frozenset({function_id})),
        "program.output_replaced",
        {"function_id": function_id, "statement_id": statement_id},
        tuple(
            dict.fromkeys(
                [
                    function_id,
                    statement_id,
                    *(
                        item.id
                        for item in iter_expressions(updated)
                        if item.id.startswith(f"expression:{statement_id}:")
                    ),
                ]
            )
        ),
        _exact_statement_operation(function_id, current),
        _exact_statement_operation(function_id, replacement),
    )


def _replace_expression(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    function_id = _text(payload, "function_id")
    expression_id = _text(payload, "expression_id")
    source = _text(payload, "source", empty=True)
    function = _function(project, function_id)
    try:
        updated, _previous = replace_expression_source(
            project.program_model,
            function,
            expression_id,
            source,
        )
    except ProgramEditError as exc:
        raise _program_error(exc) from exc
    model = reconcile_function_locals(replace_function(project.program_model, updated), updated)
    updated = refresh_written_symbols(rebind_function_expressions(model, updated))
    model = replace_function(model, updated)
    before_expressions = _expression_map(function)
    after_expressions = _expression_map(updated)
    changed_expression_ids = tuple(
        sorted(
            expression_id
            for expression_id, before in before_expressions.items()
            if after_expressions.get(expression_id) != before
        )
    )
    before_symbols = {
        item.id: item for item in project.program_model.symbols if item.owner_id == function_id
    }
    after_symbols = {item.id: item for item in model.symbols if item.owner_id == function_id}
    changed_symbol_ids = tuple(
        sorted(
            symbol_id
            for symbol_id in before_symbols.keys() | after_symbols.keys()
            if before_symbols.get(symbol_id) != after_symbols.get(symbol_id)
        )
    )
    inverse = _expression_state_operation(
        function_id,
        function,
        project.program_model,
        expression_ids=changed_expression_ids,
        symbol_ids=changed_symbol_ids,
    )
    history_forward = _expression_state_operation(
        function_id,
        updated,
        model,
        expression_ids=changed_expression_ids,
        symbol_ids=changed_symbol_ids,
    )
    return Mutation(
        project_program_changes(project, model, function_ids=frozenset({function_id})),
        "program.expression_replaced",
        {"expression_id": expression_id, "function_id": function_id},
        (function_id, expression_id),
        inverse,
        history_forward,
    )


def _rename_symbol(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    symbol_id = _text(payload, "symbol_id")
    new_name = _text(payload, "name")
    symbol = project.program_model.symbol(symbol_id)
    if symbol is None:
        raise CommandError("PROGRAM_SYMBOL_NOT_FOUND", f"Symbol {symbol_id!r} does not exist")
    if symbol.kind is ProgramSymbolKind.FUNCTION and any(
        item.id != symbol.id and item.kind is ProgramSymbolKind.FUNCTION and item.name == new_name
        for item in project.program_model.symbols
    ):
        raise CommandError("PROGRAM_DUPLICATE_FUNCTION", f"Function {new_name!r} already exists")
    try:
        model = rename_symbol(project.program_model, symbol, new_name)
    except ProgramEditError as exc:
        raise _program_error(exc) from exc
    changed_ids = frozenset(
        before.id
        for before, after in zip(project.program_model.functions, model.functions, strict=True)
        if before != after
    )
    return Mutation(
        project_program_changes(project, model, function_ids=changed_ids),
        "program.symbol_renamed",
        {"name": new_name, "previous_name": symbol.name, "symbol_id": symbol_id},
        tuple(dict.fromkeys([symbol_id, *changed_ids])),
        Operation("program.symbol.rename", {"name": symbol.name, "symbol_id": symbol_id}),
    )


def program_handlers() -> tuple[tuple[str, Handler], ...]:
    """Static contribution point; deliberately not a dynamic plugin loader."""

    return (
        ("program.function.create", _create_function),
        ("program.function.delete", _delete_function),
        *ownership_handlers(),
        ("program.function.restore", _restore_function),
        ("program.function.replace_exact", _replace_exact_function),
        ("program.sequence.splice", _splice_statements),
        ("program.statement.insert", _insert_statement),
        ("program.statement.delete", _delete_statements),
        ("program.statement.restore", _restore_statements),
        ("program.statement.move", _move_statements),
        ("program.statement.replace_exact", _replace_exact_statement),
        ("program.output.replace", _replace_output),
        ("program.expression.replace", _replace_expression),
        ("program.expression.restore", _restore_expression_state),
        ("program.symbol.rename", _rename_symbol),
    )
