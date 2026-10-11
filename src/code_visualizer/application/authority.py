"""Single-writer revision authority for one project."""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from threading import RLock
from typing import Any, cast

from code_visualizer.application.commands import Operation
from code_visualizer.application.document_clone import clone_document
from code_visualizer.application.drakon_structure import (
    primary_sequence,
)
from code_visualizer.application.messages import (
    CommandAccepted,
    CommandDeferred,
    CommandEnvelope,
    CommandRejected,
    CommandResult,
    EventEnvelope,
)
from code_visualizer.application.mindmap_structure import (
    insert_child,
    move_topic,
    remove_topic,
)
from code_visualizer.application.program_model import (
    canonicalize_project,
)
from code_visualizer.application.projection_language import compile_projection
from code_visualizer.application.projection_materializer import materialize_projection
from code_visualizer.application.semantic_index import build_semantic_program
from code_visualizer.domain.assets import ManagedAsset, ShapePackReference
from code_visualizer.domain.authoring import (
    AuthoredRelationKind,
    AuthoredSemanticRelation,
    SemanticConcept,
)
from code_visualizer.domain.common import DocumentKind, JsonValue
from code_visualizer.domain.drakon import (
    Action,
    Assignment,
    Call,
    Delay,
    DrakonAtom,
    DrakonDiagram,
    If,
    Input,
    Loop,
    Note,
    Output,
    Period,
    RealtimeProcess,
    Select,
    Silhouette,
    SimpleStatement,
    StartTimer,
    Synchronizer,
    Transfer,
    create_empty_drakon,
    drakon_atom_ids,
    find_atom_location,
    find_sequence,
    nested_sequences,
    owned_sequence_ids,
)
from code_visualizer.domain.drakon_defaults import create_default_atom
from code_visualizer.domain.freeform import (
    ConnectorObject,
    FreeformDiagram,
    Guide,
    GuideOrientation,
    Layer,
    ShapeKind,
    ShapeObject,
    create_empty_freeform,
)
from code_visualizer.domain.freeform import (
    Rect as FreeformRect,
)
from code_visualizer.domain.mindmap import (
    CrossLink,
    MindMapDiagram,
    Topic,
    create_empty_mind_map,
    find_topic,
    replace_topic,
    walk_topics,
)
from code_visualizer.domain.module_paths import canonical_module_path
from code_visualizer.domain.program import ProgramStatement
from code_visualizer.domain.project import Project, ProjectDocument
from code_visualizer.domain.projection import ProjectionViewTarget
from code_visualizer.persistence import JournalRecord, ProjectStore
from code_visualizer.persistence.decoding import (
    document_from_data,
    drakon_atom_from_data,
    function_spec_from_data,
    projection_definition_from_data,
    runtime_settings_from_data,
)
from code_visualizer.persistence.serialization import (
    document_to_data,
    function_spec_to_data,
    projection_definition_to_data,
    runtime_settings_to_data,
)
from code_visualizer.persistence.store import ProjectStoreError
from code_visualizer.validation import Severity, validate_integrity

type Subscriber = Callable[[EventEnvelope], None]
type Clock = Callable[[], str]


class CommandError(ValueError):
    def __init__(self, code: str, message: str, *, details: dict[str, JsonValue] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True, slots=True)
class Mutation:
    project: Project
    event_type: str
    event_payload: dict[str, JsonValue]
    affected_ids: tuple[str, ...]
    inverse: Operation
    history_forward: Operation | None = None


@dataclass(slots=True)
class HistoryEntry:
    operation_id: str
    actor_id: str
    revision: int
    forward: Operation
    inverse: Operation
    affected_ids: frozenset[str]
    undone: bool = False


type Handler = Callable[[Project, dict[str, JsonValue]], Mutation]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _payload_string(
    payload: dict[str, JsonValue],
    key: str,
    *,
    allow_empty: bool = False,
) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise CommandError("COMMAND_INVALID_PAYLOAD", f"{key} must be a string")
    if not allow_empty and not value.strip():
        raise CommandError("COMMAND_INVALID_PAYLOAD", f"{key} must not be empty")
    return value


def _payload_optional_string(payload: dict[str, JsonValue], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise CommandError("COMMAND_INVALID_PAYLOAD", f"{key} must be a string or null")
    return value


def _payload_integer(payload: dict[str, JsonValue], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise CommandError("COMMAND_INVALID_PAYLOAD", f"{key} must be an integer")
    return value


def _payload_optional_integer(payload: dict[str, JsonValue], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise CommandError("COMMAND_INVALID_PAYLOAD", f"{key} must be an integer or null")
    return value


def _payload_boolean(payload: dict[str, JsonValue], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise CommandError("COMMAND_INVALID_PAYLOAD", f"{key} must be a boolean")
    return value


def _payload_number(payload: dict[str, JsonValue], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CommandError("COMMAND_INVALID_PAYLOAD", f"{key} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise CommandError("COMMAND_INVALID_PAYLOAD", f"{key} must be finite")
    return result


def _payload_strings(
    payload: dict[str, JsonValue],
    key: str,
) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CommandError("COMMAND_INVALID_PAYLOAD", f"{key} must be an array of strings")
    return tuple(item for item in value if isinstance(item, str))


def _payload_string_list(payload: dict[str, JsonValue], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        raise CommandError(
            "COMMAND_INVALID_PAYLOAD",
            f"{key} must be a non-empty array of strings",
        )
    return tuple(item for item in value if isinstance(item, str))


def _document_index(project: Project, document_id: str) -> int:
    for index, document in enumerate(project.documents):
        if document.id == document_id:
            return index
    raise CommandError("DOCUMENT_NOT_FOUND", f"Document {document_id!r} does not exist")


def _replace_document(project: Project, index: int, document: ProjectDocument) -> Project:
    documents = list(project.documents)
    documents[index] = document
    return replace(project, documents=tuple(documents))


def _rename_project(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    title = _payload_string(payload, "title")
    candidate = replace(project, title=title)
    return Mutation(
        candidate,
        "project.renamed",
        {"title": title},
        (project.id,),
        Operation("project.rename", {"title": project.title}),
    )


def _create_diagram(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    title = _payload_string(payload, "title")
    document_id = _payload_string(payload, "document_id")
    if any(document.id == document_id for document in project.documents):
        raise CommandError("DOCUMENT_DUPLICATE_ID", f"Document {document_id!r} already exists")
    try:
        kind = DocumentKind(_payload_string(payload, "kind"))
    except ValueError as exc:
        raise CommandError("DOCUMENT_UNKNOWN_KIND", str(exc)) from exc
    if kind is DocumentKind.DRAKON:
        if project.program_model.function(document_id) is not None:
            raise CommandError("PROGRAM_DUPLICATE_ID", f"Function {document_id!r} already exists")
        identifier = _payload_optional_string(payload, "identifier") or "algorithm"
        drakon_document = create_empty_drakon(
            identifier=identifier,
            title=title,
            diagram_id=document_id,
        )
        module = _payload_optional_string(payload, "module")
        if module is not None:
            module = canonical_module_path(module)
            drakon_document = replace(
                drakon_document,
                header=replace(
                    drakon_document.header,
                    function=replace(drakon_document.header.function, module=module),
                ),
            )
        document: ProjectDocument = drakon_document
    elif kind is DocumentKind.MIND_MAP:
        document = create_empty_mind_map(title=title, diagram_id=document_id)
    else:
        document = create_empty_freeform(title=title, diagram_id=document_id)
    candidate = _import_drakon_document(
        replace(project, documents=(*project.documents, document)), document
    )
    return _created_document_history(
        Mutation(
            candidate,
            "diagram.created",
            {"diagram_id": document.id, "kind": kind.value, "title": title},
            (document.id,),
            Operation("diagram.delete", {"diagram_id": document.id}),
        ),
        document,
    )


def _delete_diagram(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    index = _document_index(project, diagram_id)
    document = project.documents[index]
    documents = (*project.documents[:index], *project.documents[index + 1 :])
    view = next((item for item in project.drakon_views if item.document_id == diagram_id), None)
    candidate = replace(
        project,
        documents=documents,
        drakon_views=tuple(item for item in project.drakon_views if item.document_id != diagram_id),
    )
    from code_visualizer.application.features.program.handlers import _view_payload

    return Mutation(
        candidate,
        "diagram.deleted",
        {"diagram_id": diagram_id},
        (diagram_id,),
        Operation(
            "diagram.restore",
            {
                "document": document_to_data(document),
                "index": index,
                "drakon_view": _view_payload(view) if view is not None else None,
            },
        ),
    )


def _restore_diagram(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    raw = payload.get("document")
    document = document_from_data(raw)
    index = _payload_integer(payload, "index")
    if index < 0 or index > len(project.documents):
        raise CommandError("COMMAND_INVALID_PAYLOAD", "diagram restore index is out of range")
    if any(item.id == document.id for item in project.documents):
        raise CommandError("DOCUMENT_DUPLICATE_ID", f"Document {document.id!r} already exists")
    documents = list(project.documents)
    documents.insert(index, document)
    candidate = replace(project, documents=tuple(documents))
    if payload.get("drakon_view") is not None:
        from code_visualizer.application.features.program.handlers import _view_from_payload

        view = _view_from_payload(payload["drakon_view"])
        if (
            view.document_id != document.id
            or candidate.program_model.function(view.function_id) is None
        ):
            raise CommandError("PROGRAM_VIEW_UNBOUND", "Restored view needs its canonical function")
        candidate = canonicalize_project(
            replace(candidate, drakon_views=(*candidate.drakon_views, view))
        )
    else:
        candidate = _import_drakon_document(candidate, document)
    return Mutation(
        candidate,
        "diagram.restored",
        {"diagram_id": document.id},
        (document.id,),
        Operation("diagram.delete", {"diagram_id": document.id}),
    )


def _rename_diagram(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    title = _payload_string(payload, "title")
    index = _document_index(project, diagram_id)
    document = project.documents[index]
    candidate_document = replace(document, title=title)
    candidate = _replace_document(project, index, candidate_document)
    candidate = replace(
        candidate,
        drakon_views=tuple(
            replace(item, title=title) if item.document_id == diagram_id else item
            for item in candidate.drakon_views
        ),
    )
    return Mutation(
        candidate,
        "diagram.renamed",
        {"diagram_id": diagram_id, "title": title},
        (diagram_id,),
        Operation("diagram.rename", {"diagram_id": diagram_id, "title": document.title}),
    )


def _move_diagram(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    target_index = _payload_integer(payload, "index")
    source_index = _document_index(project, diagram_id)
    if target_index < 0 or target_index >= len(project.documents):
        raise CommandError("DIAGRAM_INVALID_INDEX", "Diagram index is out of range")
    if source_index == target_index:
        raise CommandError("DIAGRAM_MOVE_NOOP", "Diagram is already at that index")
    documents = list(project.documents)
    document = documents.pop(source_index)
    documents.insert(target_index, document)
    return Mutation(
        replace(project, documents=tuple(documents)),
        "diagram.moved",
        {"diagram_id": diagram_id, "index": target_index},
        (diagram_id,),
        Operation("diagram.move", {"diagram_id": diagram_id, "index": source_index}),
    )


def _duplicate_diagram(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    document_id = _payload_string(payload, "document_id")
    title = _payload_optional_string(payload, "title")
    source_index = _document_index(project, diagram_id)
    if any(item.id == document_id for item in project.documents):
        raise CommandError("DOCUMENT_DUPLICATE_ID", f"Document {document_id!r} already exists")
    if (
        isinstance(project.documents[source_index], DrakonDiagram)
        and project.program_model.function(document_id) is not None
    ):
        raise CommandError("PROGRAM_DUPLICATE_ID", f"Function {document_id!r} already exists")
    duplicated = clone_document(
        project.documents[source_index],
        title=title,
        document_id=document_id,
    )
    documents = list(project.documents)
    documents.insert(source_index + 1, duplicated)
    return _created_document_history(
        Mutation(
            _import_drakon_document(replace(project, documents=tuple(documents)), duplicated),
            "diagram.duplicated",
            {"diagram_id": duplicated.id, "source_diagram_id": diagram_id},
            (diagram_id, duplicated.id),
            Operation("diagram.delete", {"diagram_id": duplicated.id}),
        ),
        duplicated,
    )


def _created_document_history(mutation: Mutation, document: ProjectDocument) -> Mutation:
    """Undo a new DRAKON function together with its view, retaining exact redo state."""

    if not isinstance(document, DrakonDiagram):
        return mutation
    from code_visualizer.application.features.program.handlers import _delete_function

    function_id = _program_function_id_for_document(mutation.project, document.id)
    inverse = Operation("program.function.delete", {"function_id": function_id})
    removed = _delete_function(mutation.project, inverse.payload)
    return replace(mutation, inverse=inverse, history_forward=removed.inverse)


def _import_drakon_document(project: Project, document: ProjectDocument) -> Project:
    """Import an explicit document snapshot; live gestures use semantic commands."""

    if not isinstance(document, DrakonDiagram):
        return project
    from code_visualizer.application.drakon_program_adapter import promote_program_from_drakon
    from code_visualizer.application.program_model import (
        _replace_function_segments,
        project_program_changes,
    )

    promoted = promote_program_from_drakon((document,), project.program_model, project.drakon_views)
    model = _replace_function_segments(project.program_model, promoted.model)
    replacements = {item.document_id: item for item in promoted.drakon_views}
    existing = {item.document_id for item in project.drakon_views}
    views = (
        *(replacements.get(item.document_id, item) for item in project.drakon_views),
        *(item for item in promoted.drakon_views if item.document_id not in existing),
    )
    return project_program_changes(
        replace(project, drakon_views=views),
        model,
        function_ids=frozenset(item.id for item in promoted.model.functions),
    )


def _replace_function_signature(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    function_id = _payload_string(payload, "function_id")
    try:
        spec = function_spec_from_data(payload.get("signature"), "$.payload.signature")
    except ValueError as exc:
        raise CommandError("COMMAND_INVALID_PAYLOAD", str(exc)) from exc
    from code_visualizer.application.drakon_program_adapter import program_signature_from_spec
    from code_visualizer.application.features.program.handlers import (
        _function_state_operation,
        _replace_exact_function,
    )
    from code_visualizer.application.features.program.model_ops import (
        rebind_function_expressions,
        reconcile_function_locals,
        refresh_written_symbols,
        replace_function,
    )

    function = project.program_model.function(function_id)
    if function is None:
        raise CommandError("PROGRAM_FUNCTION_NOT_FOUND", f"Function {function_id!r} does not exist")
    desired, owned_symbols = program_signature_from_spec(spec, function, project.program_model)
    by_id = {item.id: item for item in owned_symbols}
    old_ids = {item.id for item in project.program_model.symbols}
    symbols = (
        *(
            by_id.get(item.id, item)
            for item in project.program_model.symbols
            if item.owner_id != function_id or item.id in by_id
        ),
        *(item for item in owned_symbols if item.id not in old_ids),
    )
    model = replace(replace_function(project.program_model, desired), symbols=symbols)
    model = reconcile_function_locals(model, desired)
    desired = refresh_written_symbols(rebind_function_expressions(model, desired))
    candidate = replace(project, program_model=replace_function(model, desired))
    forward = _function_state_operation(candidate, desired)
    mutation = _replace_exact_function(project, forward.payload)
    return replace(mutation, history_forward=forward)


def _replace_function_spec(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    _document_index, document = _drakon_document(project, diagram_id)
    try:
        spec = function_spec_from_data(payload.get("function"), "$.payload.function")
    except ValueError as exc:
        raise CommandError("COMMAND_INVALID_PAYLOAD", str(exc)) from exc
    spec = replace(spec, module=canonical_module_path(spec.module))
    function_id = _program_function_id_for_document(project, diagram_id)
    mutation = _replace_function_signature(
        project, {"function_id": function_id, "signature": function_spec_to_data(spec)}
    )
    forward = mutation.history_forward or Operation(
        "program.function.replace_signature",
        {"function_id": function_id, "signature": function_spec_to_data(spec)},
    )
    from code_visualizer.application.features.program.ownership import _configure, header_operation
    from code_visualizer.domain.program_ownership import place_program_function

    placed = place_program_function(
        mutation.project.program_model, function_id, spec.module, spec.owning_class
    )
    if placed.modules != mutation.project.program_model.modules:
        ownership_forward = header_operation(placed)
        ownership_mutation = _configure(mutation.project, ownership_forward.payload)
        mutation = replace(
            mutation,
            project=ownership_mutation.project,
            inverse=_transaction_operation((ownership_mutation.inverse, mutation.inverse)),
        )
        forward = _transaction_operation((forward, ownership_forward))

    update_title = _payload_boolean(payload, "update_title") if "update_title" in payload else True
    if update_title and document.title != spec.display_name:
        title_operation = Operation(
            "diagram.rename", {"diagram_id": diagram_id, "title": spec.display_name}
        )
        renamed = _rename_diagram(mutation.project, title_operation.payload)
        mutation = replace(
            mutation,
            project=renamed.project,
            inverse=_transaction_operation((renamed.inverse, mutation.inverse)),
        )
        forward = _transaction_operation((forward, title_operation))
    return _drakon_event_from_program(
        mutation,
        event_type="function.spec_changed",
        event_payload={
            "diagram_id": diagram_id,
            "identifier": spec.identifier,
            "kind": spec.kind.value,
        },
        affected_ids=(diagram_id, document.header.id),
        history_forward=forward,
    )


def _configure_python_runtime(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    try:
        setup = runtime_settings_from_data(payload, "$.payload")
    except ValueError as exc:
        raise CommandError("COMMAND_INVALID_PAYLOAD", str(exc)) from exc
    return Mutation(
        replace(project, runtime_settings=setup),
        "python.runtime_configured",
        {},
        (project.id,),
        Operation("python.configure_runtime", runtime_settings_to_data(project.runtime_settings)),
    )


def _drakon_document(project: Project, diagram_id: str) -> tuple[int, DrakonDiagram]:
    index = _document_index(project, diagram_id)
    document = project.documents[index]
    if not isinstance(document, DrakonDiagram):
        raise CommandError("DOCUMENT_WRONG_KIND", "Target document is not DRAKON")
    return index, document


def _program_function_id_for_document(project: Project, diagram_id: str) -> str:
    view = next(
        (item for item in project.drakon_views if item.document_id == diagram_id),
        None,
    )
    if view is None:
        raise CommandError("PROGRAM_VIEW_UNBOUND", "The DRAKON view has no canonical function")
    return view.function_id


def _canonical_drakon_atom(project: Project, diagram_id: str, atom: DrakonAtom) -> ProgramStatement:
    from code_visualizer.application.drakon_program_adapter import program_statement_from_drakon

    function_id = _program_function_id_for_document(project, diagram_id)
    function = project.program_model.function(function_id)
    if function is None:
        raise CommandError("PROGRAM_FUNCTION_NOT_FOUND", "The view has no canonical function")
    return program_statement_from_drakon(atom, function, project.program_model)


def _program_splice(
    project: Project,
    diagram_id: str,
    sequence_id: str,
    index: int,
    count: int,
    statements: tuple[ProgramStatement, ...],
) -> Mutation:
    from code_visualizer.application.features.program.handlers import _splice_statements
    from code_visualizer.persistence.serialization import program_statement_to_data

    return _splice_statements(
        project,
        {
            "function_id": _program_function_id_for_document(project, diagram_id),
            "sequence_id": sequence_id,
            "index": index,
            "delete_count": count,
            "statements": [program_statement_to_data(item) for item in statements],
        },
    )


def _program_insert_payload(
    project: Project,
    function_id: str,
    sequence_id: str,
    index: int,
    atom: DrakonAtom,
) -> dict[str, JsonValue]:
    from code_visualizer.application.drakon_program_adapter import program_statement_from_drakon
    from code_visualizer.persistence.serialization import program_statement_to_data

    function = project.program_model.function(function_id)
    if function is None:
        raise CommandError("PROGRAM_FUNCTION_NOT_FOUND", "The view has no canonical function")
    statement = program_statement_from_drakon(atom, function, project.program_model)
    return {
        "function_id": function_id,
        "sequence_id": sequence_id,
        "index": index,
        "statement_id": atom.id,
        "statement": program_statement_to_data(statement),
    }


def _drakon_event_from_program(
    mutation: Mutation,
    *,
    event_type: str,
    event_payload: dict[str, JsonValue],
    affected_ids: tuple[str, ...],
    history_forward: Operation | None = None,
) -> Mutation:
    return replace(
        mutation,
        event_type=event_type,
        event_payload=event_payload,
        affected_ids=tuple(dict.fromkeys((*affected_ids, *mutation.affected_ids))),
        history_forward=history_forward or mutation.history_forward,
    )


def _insert_drakon(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    atom_id = _payload_string(payload, "atom_id")
    atom_kind = _payload_string(payload, "atom_kind")
    insertion_index = _payload_integer(payload, "index")
    _document_index, document = _drakon_document(project, diagram_id)
    sequence_id = _payload_optional_string(payload, "sequence_id") or document.body.id
    target_sequence = find_sequence(document.body, sequence_id)
    if target_sequence is None:
        raise CommandError("DRAKON_SEQUENCE_NOT_FOUND", f"Sequence {sequence_id!r} does not exist")
    if find_atom_location(document.body, atom_id) is not None:
        raise CommandError("DRAKON_DUPLICATE_ATOM", f"Atom {atom_id!r} already exists")
    if insertion_index < 0 or insertion_index > len(target_sequence.atoms):
        raise CommandError("DRAKON_INVALID_INSERTION", "Insertion index is out of range")
    try:
        atom = create_default_atom(atom_kind, atom_id)
    except KeyError as exc:
        raise CommandError("DRAKON_UNKNOWN_ATOM", f"Unknown atom kind {atom_kind!r}") from exc
    source = _payload_optional_string(payload, "source")
    if source is not None:
        if isinstance(atom, Action):
            atom = replace(atom, source=source)
        elif isinstance(atom, Output):
            atom = replace(atom, expression=source)
        elif isinstance(atom, If):
            atom = replace(atom, condition=source)
        elif isinstance(atom, (Call, Transfer)):
            atom = replace(atom, expression=source)
        elif isinstance(atom, SimpleStatement):
            atom = replace(atom, source=source)
    if isinstance(atom, Assignment):
        atom = replace(
            atom,
            target=_payload_optional_string(payload, "target") or atom.target,
            value=_payload_optional_string(payload, "value") or atom.value,
            annotation=_payload_optional_string(payload, "annotation"),
            operator=_payload_optional_string(payload, "operator") or atom.operator,
        )
    function_id = _program_function_id_for_document(project, diagram_id)
    from code_visualizer.application.features.program.handlers import _insert_statement

    mutation = _insert_statement(
        project,
        _program_insert_payload(
            project,
            function_id,
            sequence_id,
            insertion_index,
            atom,
        ),
    )
    return _drakon_event_from_program(
        mutation,
        event_type="drakon.atom_inserted",
        event_payload={
            "atom_id": atom.id,
            "diagram_id": diagram_id,
            "index": insertion_index,
            "sequence_id": sequence_id,
        },
        affected_ids=drakon_atom_ids(atom),
    )


def _remove_drakon(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    atom_id = _payload_string(payload, "atom_id")
    _document_index, document = _drakon_document(project, diagram_id)
    location = find_atom_location(document.body, atom_id)
    if location is None:
        raise CommandError("DRAKON_ATOM_NOT_FOUND", f"Atom {atom_id!r} does not exist")
    target_sequence, atom_index = location
    requested_sequence_id = _payload_optional_string(payload, "sequence_id")
    if requested_sequence_id is not None and requested_sequence_id != target_sequence.id:
        raise CommandError("DRAKON_SEQUENCE_MISMATCH", "Atom is not in the requested Sequence")
    atom = target_sequence.atoms[atom_index]
    function_id = _program_function_id_for_document(project, diagram_id)
    from code_visualizer.application.features.program.handlers import _delete_statements

    mutation = _delete_statements(
        project,
        {
            "function_id": function_id,
            "sequence_id": target_sequence.id,
            "statement_ids": [atom.id],
        },
    )
    return _drakon_event_from_program(
        mutation,
        event_type="drakon.atom_removed",
        event_payload={"atom_id": atom.id, "diagram_id": diagram_id},
        affected_ids=drakon_atom_ids(atom),
    )


def _restore_drakon(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    atom = drakon_atom_from_data(payload.get("atom"))
    insertion_index = _payload_integer(payload, "index")
    _document_index, document = _drakon_document(project, diagram_id)
    sequence_id = _payload_optional_string(payload, "sequence_id") or document.body.id
    target_sequence = find_sequence(document.body, sequence_id)
    if target_sequence is None:
        raise CommandError("DRAKON_SEQUENCE_NOT_FOUND", f"Sequence {sequence_id!r} does not exist")
    if insertion_index < 0 or insertion_index > len(target_sequence.atoms):
        raise CommandError("DRAKON_INVALID_INSERTION", "Restore index is out of range")
    function_id = _program_function_id_for_document(project, diagram_id)
    from code_visualizer.application.features.program.handlers import _insert_statement

    mutation = _insert_statement(
        project,
        _program_insert_payload(project, function_id, sequence_id, insertion_index, atom),
    )
    return _drakon_event_from_program(
        mutation,
        event_type="drakon.atom_restored",
        event_payload={"atom_id": atom.id, "diagram_id": diagram_id},
        affected_ids=drakon_atom_ids(atom),
    )


def _decoded_atom_block(
    payload: dict[str, JsonValue], key: str = "atoms"
) -> tuple[DrakonAtom, ...]:
    raw = payload.get(key)
    if not isinstance(raw, list) or not raw:
        raise CommandError("COMMAND_INVALID_PAYLOAD", f"{key} must be a non-empty atom array")
    try:
        return tuple(drakon_atom_from_data(item) for item in raw)
    except ValueError as exc:
        raise CommandError("COMMAND_INVALID_PAYLOAD", str(exc)) from exc


def _semantic_ids(sequence: Any) -> set[str]:
    result = {sequence.id}
    for atom in sequence.atoms:
        result.update(drakon_atom_ids(atom))
    return result


def _check_new_atom_ids(document: DrakonDiagram, atoms: tuple[DrakonAtom, ...]) -> None:
    identifiers = [identifier for atom in atoms for identifier in drakon_atom_ids(atom)]
    if len(identifiers) != len(set(identifiers)):
        raise CommandError("DRAKON_DUPLICATE_ATOM", "Inserted structure contains duplicate IDs")
    collisions = sorted(_semantic_ids(document.body) & set(identifiers))
    if collisions:
        raise CommandError(
            "DRAKON_DUPLICATE_ATOM",
            "Inserted structure reuses an existing semantic ID",
            details={"conflicting_ids": list(collisions)},
        )


def _insert_drakon_block(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    sequence_id = _payload_string(payload, "sequence_id")
    insertion_index = _payload_integer(payload, "index")
    atoms = _decoded_atom_block(payload)
    _document_index, document = _drakon_document(project, diagram_id)
    target = find_sequence(document.body, sequence_id)
    if target is None:
        raise CommandError("DRAKON_SEQUENCE_NOT_FOUND", f"Sequence {sequence_id!r} does not exist")
    if insertion_index < 0 or insertion_index > len(target.atoms):
        raise CommandError("DRAKON_INVALID_INSERTION", "Insertion index is out of range")
    _check_new_atom_ids(document, atoms)
    function_id = _program_function_id_for_document(project, diagram_id)
    from code_visualizer.application.features.program.handlers import _insert_statement

    candidate = project
    inverses: list[Operation] = []
    forwards: list[Operation] = []
    program_affected: list[str] = [sequence_id]
    for offset, atom in enumerate(atoms):
        program_payload = _program_insert_payload(
            candidate,
            function_id,
            sequence_id,
            insertion_index + offset,
            atom,
        )
        mutation = _insert_statement(candidate, program_payload)
        candidate = mutation.project
        inverses.insert(0, mutation.inverse)
        forwards.append(
            mutation.history_forward or Operation("program.statement.insert", program_payload)
        )
        program_affected.extend(mutation.affected_ids)
        program_affected.extend(drakon_atom_ids(atom))
    atom_ids = tuple(atom.id for atom in atoms)
    return Mutation(
        candidate,
        "drakon.block_inserted",
        {
            "atom_ids": list(atom_ids),
            "diagram_id": diagram_id,
            "index": insertion_index,
            "sequence_id": sequence_id,
        },
        tuple(dict.fromkeys(program_affected)),
        _transaction_operation(inverses),
        _transaction_operation(forwards),
    )


def _remove_drakon_block(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    sequence_id = _payload_string(payload, "sequence_id")
    atom_ids = _payload_string_list(payload, "atom_ids")
    if len(atom_ids) != len(set(atom_ids)):
        raise CommandError("DRAKON_REMOVE_DUPLICATE", "A block cannot list an atom twice")
    _document_index, document = _drakon_document(project, diagram_id)
    sequence = find_sequence(document.body, sequence_id)
    if sequence is None:
        raise CommandError("DRAKON_SEQUENCE_NOT_FOUND", f"Sequence {sequence_id!r} does not exist")
    first_index = next(
        (index for index, atom in enumerate(sequence.atoms) if atom.id == atom_ids[0]),
        -1,
    )
    if first_index < 0:
        raise CommandError("DRAKON_ATOM_NOT_FOUND", "The first block atom does not exist")
    removing = sequence.atoms[first_index : first_index + len(atom_ids)]
    if tuple(atom.id for atom in removing) != atom_ids:
        raise CommandError(
            "DRAKON_REMOVE_NOT_CONTIGUOUS",
            "A removed block must be contiguous and in Sequence order",
        )
    function_id = _program_function_id_for_document(project, diagram_id)
    from code_visualizer.application.features.program.handlers import _delete_statements

    mutation = _delete_statements(
        project,
        {
            "function_id": function_id,
            "sequence_id": sequence_id,
            "statement_ids": list(atom_ids),
        },
    )
    affected = tuple(
        dict.fromkeys(
            (sequence_id, *(value for atom in removing for value in drakon_atom_ids(atom)))
        )
    )
    return _drakon_event_from_program(
        mutation,
        event_type="drakon.block_removed",
        event_payload={
            "atom_ids": list(atom_ids),
            "diagram_id": diagram_id,
            "sequence_id": sequence_id,
        },
        affected_ids=affected,
    )


def _replace_drakon_atom(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    atom_id = _payload_string(payload, "atom_id")
    try:
        replacement_atom = drakon_atom_from_data(payload.get("atom"))
    except ValueError as exc:
        raise CommandError("COMMAND_INVALID_PAYLOAD", str(exc)) from exc
    if replacement_atom.id != atom_id:
        raise CommandError("DRAKON_ID_IMMUTABLE", "Replacing an atom cannot change its stable ID")
    _document_index, document = _drakon_document(project, diagram_id)
    location = find_atom_location(document.body, atom_id)
    if location is None:
        raise CommandError("DRAKON_ATOM_NOT_FOUND", f"Atom {atom_id!r} does not exist")
    sequence, atom_index = location
    previous = sequence.atoms[atom_index]
    previous_ids = set(drakon_atom_ids(previous))
    replacement_ids = drakon_atom_ids(replacement_atom)
    if len(replacement_ids) != len(set(replacement_ids)):
        raise CommandError("DRAKON_DUPLICATE_ATOM", "Replacement contains duplicate IDs")
    collisions = sorted((_semantic_ids(document.body) - previous_ids) & set(replacement_ids))
    if collisions:
        raise CommandError(
            "DRAKON_DUPLICATE_ATOM",
            "Replacement reuses an existing semantic ID",
            details={"conflicting_ids": list(collisions)},
        )
    function_id = _program_function_id_for_document(project, diagram_id)
    if (
        function_id is not None
        and isinstance(previous, Output)
        and isinstance(replacement_atom, Output)
    ):
        from code_visualizer.application.features.program.handlers import _replace_output

        mutation = _replace_output(
            project,
            {
                "destination": replacement_atom.destination,
                "end": replacement_atom.end,
                "expression": replacement_atom.expression,
                "function_id": function_id,
                "statement_id": replacement_atom.id,
            },
        )
        return _drakon_event_from_program(
            mutation,
            event_type="drakon.atom_replaced",
            event_payload={"atom_id": atom_id, "diagram_id": diagram_id},
            affected_ids=tuple(dict.fromkeys((*drakon_atom_ids(previous), *replacement_ids))),
        )
    mutation = _program_splice(
        project,
        diagram_id,
        sequence.id,
        atom_index,
        1,
        (_canonical_drakon_atom(project, diagram_id, replacement_atom),),
    )
    return _drakon_event_from_program(
        mutation,
        event_type="drakon.atom_replaced",
        event_payload={"atom_id": atom_id, "diagram_id": diagram_id},
        affected_ids=tuple(dict.fromkeys((*drakon_atom_ids(previous), *replacement_ids))),
    )


def _wrap_drakon_block(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    sequence_id = _payload_string(payload, "sequence_id")
    atom_ids = _payload_string_list(payload, "atom_ids")
    try:
        wrapper = drakon_atom_from_data(payload.get("wrapper"))
    except ValueError as exc:
        raise CommandError("COMMAND_INVALID_PAYLOAD", str(exc)) from exc
    _document_index, document = _drakon_document(project, diagram_id)
    sequence = find_sequence(document.body, sequence_id)
    if sequence is None:
        raise CommandError("DRAKON_SEQUENCE_NOT_FOUND", f"Sequence {sequence_id!r} does not exist")
    primary = primary_sequence(wrapper)
    if primary is None:
        raise CommandError("DRAKON_NOT_WRAPPER", "The selected construct cannot own a block")
    if primary.atoms:
        raise CommandError("DRAKON_WRAPPER_NOT_EMPTY", "The wrapper primary body must be empty")
    _check_new_atom_ids(document, (wrapper,))
    first_index = next(
        (index for index, atom in enumerate(sequence.atoms) if atom.id == atom_ids[0]),
        -1,
    )
    if first_index < 0:
        raise CommandError("DRAKON_ATOM_NOT_FOUND", "The first wrapped atom does not exist")
    moving = sequence.atoms[first_index : first_index + len(atom_ids)]
    if tuple(atom.id for atom in moving) != atom_ids:
        raise CommandError(
            "DRAKON_WRAP_NOT_CONTIGUOUS",
            "A wrapped block must be contiguous and in Sequence order",
        )
    from code_visualizer.application.features.program.model_ops import (
        find_sequence as program_sequence,
    )
    from code_visualizer.domain.program import map_program

    function_id = _program_function_id_for_document(project, diagram_id)
    function = project.program_model.function(function_id)
    assert function is not None
    canonical_parent = program_sequence(function, sequence_id)
    assert canonical_parent is not None
    canonical_wrapper = _canonical_drakon_atom(project, diagram_id, wrapper)
    populated = map_program(
        canonical_wrapper,
        sequence_mapper=lambda body: (
            replace(
                body,
                statements=canonical_parent.statements[first_index : first_index + len(atom_ids)],
            )
            if body.id == primary.id
            else body
        ),
    )
    mutation = _program_splice(
        project, diagram_id, sequence_id, first_index, len(atom_ids), (populated,)
    )
    return _drakon_event_from_program(
        mutation,
        event_type="drakon.block_wrapped",
        event_payload={
            "atom_ids": list(atom_ids),
            "diagram_id": diagram_id,
            "sequence_id": sequence_id,
            "wrapper_id": wrapper.id,
        },
        affected_ids=tuple(dict.fromkeys((sequence_id, *drakon_atom_ids(wrapper), *atom_ids))),
    )


def _unwrap_drakon_atom(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    atom_id = _payload_string(payload, "atom_id")
    requested_body_id = _payload_optional_string(payload, "body_sequence_id")
    discard_other_bodies = _payload_boolean(payload, "discard_other_bodies")
    _document_index, document = _drakon_document(project, diagram_id)
    location = find_atom_location(document.body, atom_id)
    if location is None:
        raise CommandError("DRAKON_ATOM_NOT_FOUND", f"Atom {atom_id!r} does not exist")
    parent, atom_index = location
    wrapper = parent.atoms[atom_index]
    bodies = nested_sequences(wrapper)
    selected = (
        next((body for body in bodies if body.id == requested_body_id), None)
        if requested_body_id is not None
        else primary_sequence(wrapper)
    )
    if selected is None or selected not in bodies:
        raise CommandError("DRAKON_UNWRAP_BODY_NOT_FOUND", "Choose a body owned by the construct")
    retained_elsewhere = [body.id for body in bodies if body.id != selected.id and body.atoms]
    if retained_elsewhere and not discard_other_bodies:
        raise CommandError(
            "DRAKON_UNWRAP_CONTENT_LOSS",
            "Other construct bodies contain operations",
            details={"nonempty_sequence_ids": list(retained_elsewhere)},
        )
    from code_visualizer.application.features.program.model_ops import (
        find_sequence as program_sequence,
    )

    function_id = _program_function_id_for_document(project, diagram_id)
    function = project.program_model.function(function_id)
    assert function is not None
    canonical_body = program_sequence(function, selected.id)
    assert canonical_body is not None
    mutation = _program_splice(
        project, diagram_id, parent.id, atom_index, 1, canonical_body.statements
    )
    return _drakon_event_from_program(
        mutation,
        event_type="drakon.construct_unwrapped",
        event_payload={
            "atom_id": atom_id,
            "body_sequence_id": selected.id,
            "diagram_id": diagram_id,
        },
        affected_ids=tuple(dict.fromkeys((parent.id, *drakon_atom_ids(wrapper)))),
    )


_EDITABLE_TEXT_FIELDS: dict[type[object], frozenset[str]] = {
    Action: frozenset({"source"}),
    Assignment: frozenset({"target", "value", "annotation", "operator"}),
    Call: frozenset({"arguments", "expression", "result_target"}),
    Delay: frozenset({"seconds"}),
    If: frozenset({"condition"}),
    Input: frozenset({"target", "prompt", "converter", "annotation"}),
    Loop: frozenset({"condition", "target", "iterable", "children", "delay_seconds"}),
    Note: frozenset({"text"}),
    Output: frozenset({"expression", "destination", "end"}),
    Period: frozenset({"timer", "seconds"}),
    RealtimeProcess: frozenset({"call"}),
    Select: frozenset({"expression"}),
    Silhouette: frozenset({"display_name", "identifier"}),
    SimpleStatement: frozenset({"source", "secondary"}),
    StartTimer: frozenset({"timer"}),
    Synchronizer: frozenset({"timer", "deadline"}),
    Transfer: frozenset({"expression", "cause"}),
}

_OPTIONAL_TEXT_FIELDS = frozenset(
    {"annotation", "cause", "converter", "destination", "end", "result_target", "secondary"}
)


def _replace_drakon_text(atom: DrakonAtom, field: str, value: str) -> tuple[DrakonAtom, str, str]:
    if isinstance(atom, Output) and field == "source":
        field = "expression"
    allowed = _EDITABLE_TEXT_FIELDS.get(type(atom), frozenset())
    if field not in allowed:
        raise CommandError(
            "DRAKON_UNKNOWN_FIELD",
            f"{type(atom).__name__} has no editable field {field!r}",
        )
    previous_value = getattr(atom, field)
    previous = "" if previous_value is None else str(previous_value)
    replacement_value: object = value or None if field in _OPTIONAL_TEXT_FIELDS else value
    replacement = cast(DrakonAtom, replace(cast(Any, atom), **{field: replacement_value}))
    return replacement, field, previous


def _set_drakon_text(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    atom_id = _payload_string(payload, "atom_id")
    field = _payload_string(payload, "field")
    value = _payload_string(payload, "value", allow_empty=True)
    _document_index, document = _drakon_document(project, diagram_id)
    if atom_id == document.header.id:
        function = document.header.function
        if field == "identifier":
            function = replace(function, identifier=value)
        elif field == "display_name":
            function = replace(function, display_name=value)
        else:
            raise CommandError("DRAKON_UNKNOWN_FIELD", f"Header has no field {field!r}")
        mutation = _replace_function_spec(
            project,
            {
                "diagram_id": diagram_id,
                "function": function_spec_to_data(function),
                "update_title": False,
            },
        )
        return _drakon_event_from_program(
            mutation,
            event_type="drakon.text_changed",
            event_payload={
                "atom_id": atom_id,
                "diagram_id": diagram_id,
                "field": field,
                "value": value,
            },
            affected_ids=(atom_id,),
        )
    else:
        location = find_atom_location(document.body, atom_id)
        if location is None:
            raise CommandError("DRAKON_ATOM_NOT_FOUND", f"Atom {atom_id!r} does not exist")
        target_sequence, atom_index = location
        atom = target_sequence.atoms[atom_index]
        function_id = _program_function_id_for_document(project, diagram_id)
        if function_id is not None and isinstance(atom, Output):
            from code_visualizer.application.features.program.handlers import _replace_output

            replacement, output_field, _previous = _replace_drakon_text(atom, field, value)
            assert isinstance(replacement, Output)
            mutation = _replace_output(
                project,
                {
                    "destination": replacement.destination,
                    "end": replacement.end,
                    "expression": replacement.expression,
                    "function_id": function_id,
                    "statement_id": atom.id,
                },
            )
            return _drakon_event_from_program(
                mutation,
                event_type="drakon.text_changed",
                event_payload={
                    "atom_id": atom_id,
                    "diagram_id": diagram_id,
                    "field": output_field,
                    "value": value,
                },
                affected_ids=(atom_id,),
            )
        replacement, field, _previous = _replace_drakon_text(atom, field, value)
        from code_visualizer.application.features.program.model_ops import iter_statements
        from code_visualizer.domain.program import ProgramExpression

        canonical_function = project.program_model.function(function_id)
        assert canonical_function is not None
        statement = next(
            item for item in iter_statements(canonical_function.body) if item.id == atom.id
        )
        expression = getattr(statement, field, None)
        if isinstance(expression, ProgramExpression) and not (
            field in _OPTIONAL_TEXT_FIELDS and not value
        ):
            from code_visualizer.application.features.program.handlers import _replace_expression

            mutation = _replace_expression(
                project,
                {
                    "expression_id": expression.id,
                    "function_id": function_id,
                    "source": value,
                },
            )
            return _drakon_event_from_program(
                mutation,
                event_type="drakon.text_changed",
                event_payload={
                    "atom_id": atom_id,
                    "diagram_id": diagram_id,
                    "field": field,
                    "value": value,
                },
                affected_ids=(atom_id,),
            )
        mutation = _program_splice(
            project,
            diagram_id,
            target_sequence.id,
            atom_index,
            1,
            (_canonical_drakon_atom(project, diagram_id, replacement),),
        )
        return _drakon_event_from_program(
            mutation,
            event_type="drakon.text_changed",
            event_payload={
                "atom_id": atom_id,
                "diagram_id": diagram_id,
                "field": field,
                "value": value,
            },
            affected_ids=(atom_id,),
        )


def _move_drakon_block(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    source_sequence_id = _payload_string(payload, "source_sequence_id")
    destination_sequence_id = _payload_string(payload, "destination_sequence_id")
    destination_index = _payload_integer(payload, "destination_index")
    atom_ids = _payload_string_list(payload, "atom_ids")
    if len(set(atom_ids)) != len(atom_ids):
        raise CommandError("DRAKON_MOVE_DUPLICATE", "A block cannot list an atom twice")
    _document_index, document = _drakon_document(project, diagram_id)
    source = find_sequence(document.body, source_sequence_id)
    destination = find_sequence(document.body, destination_sequence_id)
    if source is None or destination is None:
        raise CommandError("DRAKON_SEQUENCE_NOT_FOUND", "Move Sequence does not exist")
    if destination_index < 0 or destination_index > len(destination.atoms):
        raise CommandError("DRAKON_INVALID_INSERTION", "Move destination is out of range")

    first_index = next(
        (index for index, atom in enumerate(source.atoms) if atom.id == atom_ids[0]),
        -1,
    )
    if first_index < 0:
        raise CommandError("DRAKON_ATOM_NOT_FOUND", "The first block atom does not exist")
    moving = source.atoms[first_index : first_index + len(atom_ids)]
    if tuple(atom.id for atom in moving) != atom_ids:
        raise CommandError(
            "DRAKON_MOVE_NOT_CONTIGUOUS",
            "A transplanted block must be contiguous and in Sequence order",
        )
    for atom in moving:
        if destination_sequence_id in owned_sequence_ids(atom):
            raise CommandError(
                "DRAKON_MOVE_INTO_SELF",
                "A structure cannot be transplanted into one of its own branches",
            )

    same_sequence = source_sequence_id == destination_sequence_id
    block_end = first_index + len(moving)
    if same_sequence and first_index <= destination_index <= block_end:
        raise CommandError("DRAKON_MOVE_NOOP", "The block is already at that boundary")

    function_id = _program_function_id_for_document(project, diagram_id)
    from code_visualizer.application.features.program.handlers import _move_statements

    program_payload: dict[str, JsonValue] = {
        "destination_index": destination_index,
        "destination_sequence_id": destination_sequence_id,
        "function_id": function_id,
        "source_sequence_id": source_sequence_id,
        "statement_ids": list(atom_ids),
    }
    mutation = _move_statements(project, program_payload)
    adjusted = mutation.event_payload.get("destination_index", destination_index)
    assert isinstance(adjusted, int) and not isinstance(adjusted, bool)
    affected = [source_sequence_id, destination_sequence_id]
    for atom in moving:
        affected.extend(drakon_atom_ids(atom))
    return _drakon_event_from_program(
        mutation,
        event_type="drakon.block_moved",
        event_payload={
            "atom_ids": list(atom_ids),
            "destination_index": adjusted,
            "destination_sequence_id": destination_sequence_id,
            "diagram_id": diagram_id,
            "source_sequence_id": source_sequence_id,
        },
        affected_ids=tuple(dict.fromkeys(affected)),
        history_forward=Operation("program.statement.move", program_payload),
    )


def _document_snapshot_mutation(
    project: Project,
    document_index: int,
    updated: ProjectDocument,
    event_type: str,
    event_payload: dict[str, JsonValue],
    affected_ids: tuple[str, ...],
) -> Mutation:
    previous = project.documents[document_index]
    return Mutation(
        _replace_document(project, document_index, updated),
        event_type,
        event_payload,
        affected_ids,
        Operation(
            "diagram.replace_snapshot",
            {
                "diagram_id": previous.id,
                "document": document_to_data(previous),
            },
        ),
    )


def _replace_diagram_snapshot(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    index = _document_index(project, diagram_id)
    try:
        document = document_from_data(payload.get("document"), "$.payload.document")
    except ValueError as exc:
        raise CommandError("COMMAND_INVALID_PAYLOAD", str(exc)) from exc
    if document.id != diagram_id:
        raise CommandError("DOCUMENT_ID_MISMATCH", "Replacement snapshot changed the document ID")
    mutation = _document_snapshot_mutation(
        project,
        index,
        document,
        "diagram.snapshot_replaced",
        {"diagram_id": diagram_id},
        (diagram_id,),
    )

    return replace(mutation, project=_import_drakon_document(mutation.project, document))


def _mind_map_document(project: Project, diagram_id: str) -> tuple[int, MindMapDiagram]:
    index = _document_index(project, diagram_id)
    document = project.documents[index]
    if not isinstance(document, MindMapDiagram):
        raise CommandError("DOCUMENT_WRONG_KIND", "Target document is not a mind map")
    return index, document


def _add_mind_map_topic(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    parent_id = _payload_string(payload, "parent_id")
    topic_id = _payload_string(payload, "topic_id")
    text = _payload_string(payload, "text")
    child_index = _payload_integer(payload, "index")
    document_index, document = _mind_map_document(project, diagram_id)
    if find_topic(document.root, topic_id) is not None:
        raise CommandError("MIND_DUPLICATE_TOPIC", f"Topic {topic_id!r} already exists")
    try:
        root = insert_child(document.root, parent_id, Topic(topic_id, text), child_index)
    except ValueError as exc:
        raise CommandError("MIND_INVALID_INSERTION", str(exc)) from exc
    return _document_snapshot_mutation(
        project,
        document_index,
        replace(document, root=root),
        "mindmap.topic_added",
        {"diagram_id": diagram_id, "parent_id": parent_id, "topic_id": topic_id},
        (diagram_id, parent_id, topic_id),
    )


def _update_mind_map_topic(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    topic_id = _payload_string(payload, "topic_id")
    document_index, document = _mind_map_document(project, diagram_id)
    topic = find_topic(document.root, topic_id)
    if topic is None:
        raise CommandError("MIND_TOPIC_NOT_FOUND", f"Topic {topic_id!r} does not exist")
    derive_label = _payload_boolean(payload, "derive_label") if "derive_label" in payload else False
    update_label = _payload_boolean(payload, "update_label") if "update_label" in payload else True
    replacement = replace(
        topic,
        text=_payload_string(payload, "text"),
        notes=_payload_string(payload, "notes", allow_empty=True),
        collapsed=_payload_boolean(payload, "collapsed"),
        links=_payload_strings(payload, "links"),
        attachments=_payload_strings(payload, "attachments"),
        label_override=(None if derive_label else _payload_string(payload, "text"))
        if (update_label and document.live_projection is not None and topic.semantic_id is not None)
        else topic.label_override,
    )
    updated = replace(document, root=replace_topic(document.root, replacement))
    return _document_snapshot_mutation(
        project,
        document_index,
        updated,
        "mindmap.topic_changed",
        {"diagram_id": diagram_id, "topic_id": topic_id},
        (diagram_id, topic_id),
    )


def _move_mind_map_topic(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    topic_id = _payload_string(payload, "topic_id")
    parent_id = _payload_string(payload, "parent_id")
    child_index = _payload_integer(payload, "index")
    document_index, document = _mind_map_document(project, diagram_id)
    try:
        root = move_topic(document.root, topic_id, parent_id, child_index)
    except ValueError as exc:
        raise CommandError("MIND_INVALID_MOVE", str(exc)) from exc
    return _document_snapshot_mutation(
        project,
        document_index,
        replace(document, root=root),
        "mindmap.topic_moved",
        {"diagram_id": diagram_id, "parent_id": parent_id, "topic_id": topic_id},
        (diagram_id, topic_id, parent_id),
    )


def _remove_mind_map_topic(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    topic_id = _payload_string(payload, "topic_id")
    promote_children = _payload_boolean(payload, "promote_children")
    document_index, document = _mind_map_document(project, diagram_id)
    removing = find_topic(document.root, topic_id)
    if removing is None:
        raise CommandError("MIND_TOPIC_NOT_FOUND", f"Topic {topic_id!r} does not exist")
    removed_ids = {topic_id} if promote_children else {topic.id for topic in walk_topics(removing)}
    try:
        root = remove_topic(document.root, topic_id, promote_children=promote_children)
    except ValueError as exc:
        raise CommandError("MIND_INVALID_REMOVE", str(exc)) from exc
    links = tuple(
        link
        for link in document.cross_links
        if link.source_topic_id not in removed_ids and link.target_topic_id not in removed_ids
    )
    updated = replace(document, root=root, cross_links=links)
    return _document_snapshot_mutation(
        project,
        document_index,
        updated,
        "mindmap.topic_removed",
        {"diagram_id": diagram_id, "topic_id": topic_id},
        (diagram_id, *sorted(removed_ids)),
    )


def _add_mind_map_cross_link(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    link_id = _payload_string(payload, "link_id")
    source_id = _payload_string(payload, "source_topic_id")
    target_id = _payload_string(payload, "target_topic_id")
    label = _payload_string(payload, "label", allow_empty=True)
    document_index, document = _mind_map_document(project, diagram_id)
    if any(link.id == link_id for link in document.cross_links):
        raise CommandError("MIND_DUPLICATE_LINK", f"Cross-link {link_id!r} already exists")
    if find_topic(document.root, source_id) is None or find_topic(document.root, target_id) is None:
        raise CommandError("MIND_UNRESOLVED_LINK", "Both cross-link topics must exist")
    link = CrossLink(link_id, source_id, target_id, label)
    updated = replace(document, cross_links=(*document.cross_links, link))
    return _document_snapshot_mutation(
        project,
        document_index,
        updated,
        "mindmap.cross_link_added",
        {"diagram_id": diagram_id, "link_id": link_id},
        (diagram_id, link_id, source_id, target_id),
    )


def _set_mind_map_layout(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    layout = _payload_string(payload, "layout")
    if layout not in {"balanced", "left_to_right", "right_to_left", "radial"}:
        raise CommandError("MIND_UNKNOWN_LAYOUT", f"Unknown mind-map layout {layout!r}")
    document_index, document = _mind_map_document(project, diagram_id)
    return _document_snapshot_mutation(
        project,
        document_index,
        replace(document, layout=layout),
        "mindmap.layout_changed",
        {"diagram_id": diagram_id, "layout": layout},
        (diagram_id,),
    )


def _set_view_anchor(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    """Bind presentation-only objects to canonical semantic identities."""

    diagram_id = _payload_string(payload, "diagram_id")
    object_id = _payload_string(payload, "object_id")
    semantic_id = _payload_optional_string(payload, "semantic_id")
    relation_id = _payload_optional_string(payload, "semantic_relation_id")
    if semantic_id is not None and relation_id is not None:
        raise CommandError(
            "VIEW_ANCHOR_AMBIGUOUS",
            "A view object cannot anchor to an object and relation together",
        )

    semantic = build_semantic_program(project)
    object_ids = {item.id for item in semantic.objects}
    relation_ids = {item.id for item in semantic.relations}
    if semantic_id is not None and semantic_id not in object_ids:
        raise CommandError(
            "SEMANTIC_OBJECT_NOT_FOUND",
            f"Semantic object {semantic_id!r} does not exist",
        )
    if relation_id is not None and relation_id not in relation_ids:
        raise CommandError(
            "SEMANTIC_RELATION_NOT_FOUND",
            f"Semantic relation {relation_id!r} does not exist",
        )

    document_index = _document_index(project, diagram_id)
    document = project.documents[document_index]
    previous_semantic_id: str | None = None
    previous_relation_id: str | None = None
    if isinstance(document, MindMapDiagram):
        topic = find_topic(document.root, object_id)
        if topic is not None:
            if relation_id is not None:
                raise CommandError(
                    "VIEW_ANCHOR_KIND_MISMATCH",
                    "A mind-map topic anchors to a semantic object",
                )
            previous_semantic_id = topic.semantic_id
            updated: ProjectDocument = replace(
                document,
                root=replace_topic(document.root, replace(topic, semantic_id=semantic_id)),
            )
        else:
            link = next((item for item in document.cross_links if item.id == object_id), None)
            if link is None:
                raise CommandError("VIEW_OBJECT_NOT_FOUND", f"View object {object_id!r} not found")
            if semantic_id is not None:
                raise CommandError(
                    "VIEW_ANCHOR_KIND_MISMATCH",
                    "A mind-map cross-link anchors to a semantic relation",
                )
            previous_relation_id = link.semantic_relation_id
            updated = replace(
                document,
                cross_links=tuple(
                    replace(item, semantic_relation_id=relation_id)
                    if item.id == object_id
                    else item
                    for item in document.cross_links
                ),
            )
    elif isinstance(document, FreeformDiagram):
        target = next((item for item in document.objects if item.id == object_id), None)
        if target is None:
            raise CommandError("VIEW_OBJECT_NOT_FOUND", f"View object {object_id!r} not found")
        if isinstance(target, ShapeObject):
            if relation_id is not None:
                raise CommandError(
                    "VIEW_ANCHOR_KIND_MISMATCH",
                    "A free-form shape anchors to a semantic object",
                )
            previous_semantic_id = target.semantic_id
            replacement: ShapeObject | ConnectorObject = replace(target, semantic_id=semantic_id)
        else:
            if semantic_id is not None:
                raise CommandError(
                    "VIEW_ANCHOR_KIND_MISMATCH",
                    "A free-form connector anchors to a semantic relation",
                )
            previous_relation_id = target.semantic_relation_id
            replacement = replace(target, semantic_relation_id=relation_id)
        updated = replace(
            document,
            objects=tuple(
                replacement if item.id == object_id else item for item in document.objects
            ),
        )
    else:
        raise CommandError(
            "VIEW_ANCHOR_UNSUPPORTED",
            "DRAKON glyph anchors are intrinsic to their semantic operations",
        )

    affected = tuple(
        item for item in (diagram_id, object_id, semantic_id, relation_id) if item is not None
    )
    return Mutation(
        _replace_document(project, document_index, updated),
        "view.anchor_changed",
        {
            "diagram_id": diagram_id,
            "object_id": object_id,
            "semantic_id": semantic_id,
            "semantic_relation_id": relation_id,
        },
        affected,
        Operation(
            "view.set_anchor",
            {
                "diagram_id": diagram_id,
                "object_id": object_id,
                "semantic_id": previous_semantic_id,
                "semantic_relation_id": previous_relation_id,
            },
        ),
    )


def _concept_payload(concept: SemanticConcept) -> dict[str, JsonValue]:
    return {
        "description": concept.description,
        "id": concept.id,
        "member_ids": list(concept.member_ids),
        "tags": list(concept.tags),
        "title": concept.title,
    }


def _authored_relation_payload(
    relation: AuthoredSemanticRelation,
) -> dict[str, JsonValue]:
    return {
        "description": relation.description,
        "id": relation.id,
        "kind": relation.kind.value,
        "label": relation.label,
        "source_id": relation.source_id,
        "target_id": relation.target_id,
    }


def _view_anchor_uses(project: Project, semantic_id: str, *, relation: bool = False) -> bool:
    for document in project.documents:
        if isinstance(document, MindMapDiagram):
            if relation:
                if any(item.semantic_relation_id == semantic_id for item in document.cross_links):
                    return True
            elif any(topic.semantic_id == semantic_id for topic in walk_topics(document.root)):
                return True
        elif isinstance(document, FreeformDiagram):
            for item in document.objects:
                if relation and isinstance(item, ConnectorObject):
                    if item.semantic_relation_id == semantic_id:
                        return True
                elif (
                    not relation
                    and isinstance(item, ShapeObject)
                    and item.semantic_id == semantic_id
                ):
                    return True
    return False


def _put_semantic_concept(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    concept_id = _payload_string(payload, "id")
    title = _payload_string(payload, "title")
    description = _payload_string(payload, "description", allow_empty=True)
    member_ids = _payload_strings(payload, "member_ids")
    tags = _payload_strings(payload, "tags")
    if len(set(member_ids)) != len(member_ids):
        raise CommandError("SEMANTIC_CONCEPT_DUPLICATE_MEMBER", "Concept members must be unique")
    if any(not tag.strip() for tag in tags):
        raise CommandError("SEMANTIC_CONCEPT_EMPTY_TAG", "Concept tags must not be empty")
    existing = next((item for item in project.concepts if item.id == concept_id), None)
    program = build_semantic_program(project)
    object_ids = {item.id for item in program.objects}
    if existing is None and concept_id in object_ids:
        raise CommandError(
            "SEMANTIC_ID_COLLISION",
            f"Semantic identity {concept_id!r} already belongs to another object",
        )
    available_ids = object_ids | {concept_id}
    missing = sorted(set(member_ids) - available_ids)
    if missing:
        raise CommandError(
            "SEMANTIC_OBJECT_NOT_FOUND",
            "Every concept member must resolve in the current semantic revision",
            details={"missing_ids": cast(JsonValue, missing)},
        )
    concept = SemanticConcept(concept_id, title, description, member_ids, tags)
    concepts = (
        (*project.concepts, concept)
        if existing is None
        else tuple(concept if item.id == concept_id else item for item in project.concepts)
    )
    inverse = (
        Operation("semantic.concept.delete", {"concept_id": concept_id})
        if existing is None
        else Operation("semantic.concept.put", _concept_payload(existing))
    )
    return Mutation(
        replace(project, concepts=concepts),
        "semantic.concept_changed",
        {"concept_id": concept_id, "member_ids": list(member_ids)},
        tuple(dict.fromkeys((concept_id, *member_ids))),
        inverse,
    )


def _delete_semantic_concept(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    concept_id = _payload_string(payload, "concept_id")
    concept = next((item for item in project.concepts if item.id == concept_id), None)
    if concept is None:
        raise CommandError("SEMANTIC_CONCEPT_NOT_FOUND", f"Concept {concept_id!r} does not exist")
    references: list[str] = []
    references.extend(
        item.id
        for item in project.concepts
        if item.id != concept_id and concept_id in item.member_ids
    )
    references.extend(
        item.id
        for item in project.semantic_relations
        if concept_id in {item.source_id, item.target_id}
    )
    references.extend(
        item.id for item in project.projection_definitions if item.scope_id == concept_id
    )
    if _view_anchor_uses(project, concept_id):
        references.append("view anchor")
    if references:
        raise CommandError(
            "SEMANTIC_CONCEPT_IN_USE",
            "Remove concept memberships, relationships, projections, and view anchors first",
            details={"references": cast(JsonValue, sorted(references))},
        )
    return Mutation(
        replace(
            project,
            concepts=tuple(item for item in project.concepts if item.id != concept_id),
        ),
        "semantic.concept_deleted",
        {"concept_id": concept_id},
        (concept_id,),
        Operation("semantic.concept.put", _concept_payload(concept)),
    )


def _put_authored_relation(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    relation_id = _payload_string(payload, "id")
    source_id = _payload_string(payload, "source_id")
    target_id = _payload_string(payload, "target_id")
    label = _payload_string(payload, "label", allow_empty=True)
    description = _payload_string(payload, "description", allow_empty=True)
    try:
        kind = AuthoredRelationKind(_payload_string(payload, "kind"))
    except ValueError as exc:
        raise CommandError("SEMANTIC_RELATION_UNKNOWN_KIND", str(exc)) from exc
    existing = next(
        (item for item in project.semantic_relations if item.id == relation_id),
        None,
    )
    program = build_semantic_program(project)
    object_ids = {item.id for item in program.objects}
    missing = sorted({source_id, target_id} - object_ids)
    if missing:
        raise CommandError(
            "SEMANTIC_OBJECT_NOT_FOUND",
            "Authored relationship endpoints must resolve in the current revision",
            details={"missing_ids": cast(JsonValue, missing)},
        )
    derived_ids = {item.id for item in program.relations}
    if existing is None and relation_id in derived_ids:
        raise CommandError(
            "SEMANTIC_ID_COLLISION",
            f"Semantic relationship identity {relation_id!r} already exists",
        )
    relation = AuthoredSemanticRelation(
        relation_id,
        source_id,
        target_id,
        kind,
        label,
        description,
    )
    relations = (
        (*project.semantic_relations, relation)
        if existing is None
        else tuple(
            relation if item.id == relation_id else item for item in project.semantic_relations
        )
    )
    inverse = (
        Operation("semantic.relation.delete", {"relation_id": relation_id})
        if existing is None
        else Operation("semantic.relation.put", _authored_relation_payload(existing))
    )
    return Mutation(
        replace(project, semantic_relations=relations),
        "semantic.relationship_changed",
        {
            "kind": kind.value,
            "relation_id": relation_id,
            "source_id": source_id,
            "target_id": target_id,
        },
        (relation_id, source_id, target_id),
        inverse,
    )


def _delete_authored_relation(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    relation_id = _payload_string(payload, "relation_id")
    relation = next(
        (item for item in project.semantic_relations if item.id == relation_id),
        None,
    )
    if relation is None:
        raise CommandError(
            "SEMANTIC_RELATION_NOT_FOUND",
            f"Authored relationship {relation_id!r} does not exist",
        )
    if _view_anchor_uses(project, relation_id, relation=True):
        raise CommandError(
            "SEMANTIC_RELATION_IN_USE",
            "Remove presentation anchors to this relationship first",
        )
    return Mutation(
        replace(
            project,
            semantic_relations=tuple(
                item for item in project.semantic_relations if item.id != relation_id
            ),
        ),
        "semantic.relationship_deleted",
        {"relation_id": relation_id},
        (relation_id, relation.source_id, relation.target_id),
        Operation("semantic.relation.put", _authored_relation_payload(relation)),
    )


def _put_projection_definition(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    try:
        definition = projection_definition_from_data(payload, "$.command.projection")
    except ValueError as exc:
        raise CommandError("PROJECTION_INVALID", str(exc)) from exc
    if not 1 <= definition.max_depth <= 64:
        raise CommandError("PROJECTION_INVALID_DEPTH", "Traversal depth must be between 1 and 64")
    if not 2 <= definition.node_limit <= 1000:
        raise CommandError("PROJECTION_INVALID_LIMIT", "Object limit must be between 2 and 1000")
    if definition.scope_id is not None:
        object_ids = {item.id for item in build_semantic_program(project).objects}
        if definition.scope_id not in object_ids:
            raise CommandError(
                "SEMANTIC_OBJECT_NOT_FOUND",
                f"Projection scope {definition.scope_id!r} does not exist",
            )
    existing = next(
        (item for item in project.projection_definitions if item.id == definition.id),
        None,
    )
    definitions = (
        (*project.projection_definitions, definition)
        if existing is None
        else tuple(
            definition if item.id == definition.id else item
            for item in project.projection_definitions
        )
    )
    inverse = (
        Operation("projection.delete", {"definition_id": definition.id})
        if existing is None
        else Operation("projection.put", projection_definition_to_data(existing))
    )
    return Mutation(
        replace(project, projection_definitions=definitions),
        "projection.definition_changed",
        {"definition_id": definition.id, "title": definition.title},
        (definition.id,),
        inverse,
    )


def _delete_projection_definition(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    definition_id = _payload_string(payload, "definition_id")
    definition = next(
        (item for item in project.projection_definitions if item.id == definition_id),
        None,
    )
    if definition is None:
        raise CommandError(
            "PROJECTION_NOT_FOUND",
            f"Projection definition {definition_id!r} does not exist",
        )
    return Mutation(
        replace(
            project,
            projection_definitions=tuple(
                item for item in project.projection_definitions if item.id != definition_id
            ),
        ),
        "projection.definition_deleted",
        {"definition_id": definition_id},
        (definition_id,),
        Operation("projection.put", projection_definition_to_data(definition)),
    )


def _materialize_projection(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    title = _payload_string(payload, "title")
    document_id = _payload_string(payload, "document_id")
    if any(document.id == document_id for document in project.documents):
        raise CommandError("DOCUMENT_DUPLICATE_ID", f"Document {document_id!r} already exists")
    try:
        target = ProjectionViewTarget(_payload_string(payload, "target"))
        definition = projection_definition_from_data(
            payload.get("definition"),
            "$.command.projection.definition",
        )
    except ValueError as exc:
        raise CommandError("PROJECTION_INVALID", str(exc)) from exc
    if not 1 <= definition.max_depth <= 64:
        raise CommandError("PROJECTION_INVALID_DEPTH", "Traversal depth must be between 1 and 64")
    if not 2 <= definition.node_limit <= 1000:
        raise CommandError("PROJECTION_INVALID_LIMIT", "Object limit must be between 2 and 1000")
    program = build_semantic_program(project)
    if definition.scope_id is not None and not any(
        item.id == definition.scope_id for item in program.objects
    ):
        raise CommandError(
            "SEMANTIC_OBJECT_NOT_FOUND",
            f"Projection scope {definition.scope_id!r} does not exist",
        )
    projection = compile_projection(program, definition)
    document = materialize_projection(
        projection,
        target,
        document_id=document_id,
        title=title,
        definition=definition,
    )
    return Mutation(
        replace(project, documents=(*project.documents, document)),
        "projection.materialized",
        {
            "definition_id": definition.id,
            "diagram_id": document_id,
            "target": target.value,
            "title": title,
        },
        tuple(dict.fromkeys((document_id, *(item.semantic_id for item in projection.nodes)))),
        Operation("diagram.delete", {"diagram_id": document_id}),
    )


def _freeform_document(project: Project, diagram_id: str) -> tuple[int, FreeformDiagram]:
    index = _document_index(project, diagram_id)
    document = project.documents[index]
    if not isinstance(document, FreeformDiagram):
        raise CommandError("DOCUMENT_WRONG_KIND", "Target document is not free-form")
    return index, document


def _freeform_bounds(payload: dict[str, JsonValue]) -> FreeformRect:
    raw = payload.get("bounds")
    if not isinstance(raw, dict):
        raise CommandError("COMMAND_INVALID_PAYLOAD", "bounds must be an object")
    typed = {str(key): value for key, value in raw.items()}
    return FreeformRect(
        _payload_number(typed, "x"),
        _payload_number(typed, "y"),
        _payload_number(typed, "width"),
        _payload_number(typed, "height"),
    )


def _create_freeform_shape(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    object_id = _payload_string(payload, "object_id")
    layer_id = _payload_string(payload, "layer_id")
    document_index, document = _freeform_document(project, diagram_id)
    if any(item.id == object_id for item in document.objects):
        raise CommandError("FREEFORM_DUPLICATE_OBJECT", f"Object {object_id!r} already exists")
    target_layer = next((layer for layer in document.layers if layer.id == layer_id), None)
    if target_layer is None:
        raise CommandError("FREEFORM_LAYER_NOT_FOUND", f"Layer {layer_id!r} does not exist")
    if target_layer.locked:
        raise CommandError("FREEFORM_LAYER_LOCKED", "Locked layers cannot receive new objects")
    try:
        shape_kind = ShapeKind(_payload_string(payload, "shape"))
    except ValueError as exc:
        raise CommandError("FREEFORM_UNKNOWN_SHAPE", str(exc)) from exc
    bounds = _freeform_bounds(payload)
    if bounds.width < 0 or bounds.height < 0:
        raise CommandError("FREEFORM_NEGATIVE_SIZE", "Shape size cannot be negative")
    highest = max(
        (item.z_index for item in document.objects if isinstance(item, ShapeObject)),
        default=-1,
    )
    shape = ShapeObject(
        object_id,
        shape_kind,
        bounds,
        _payload_string(payload, "text", allow_empty=True),
        z_index=highest + 1,
        layer_id=layer_id,
    )
    updated = replace(document, objects=(*document.objects, shape))
    return _document_snapshot_mutation(
        project,
        document_index,
        updated,
        "freeform.object_created",
        {"diagram_id": diagram_id, "object_id": object_id, "shape": shape_kind.value},
        (diagram_id, object_id),
    )


def _transform_freeform_object(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    object_id = _payload_string(payload, "object_id")
    document_index, document = _freeform_document(project, diagram_id)
    target = next((item for item in document.objects if item.id == object_id), None)
    if not isinstance(target, ShapeObject):
        raise CommandError("FREEFORM_OBJECT_NOT_FOUND", "Transform target is not a shape")
    if target.locked:
        raise CommandError("FREEFORM_OBJECT_LOCKED", "Locked objects cannot be transformed")
    target_layer = next((layer for layer in document.layers if layer.id == target.layer_id), None)
    if target_layer is not None and target_layer.locked:
        raise CommandError(
            "FREEFORM_LAYER_LOCKED", "Objects on a locked layer cannot be transformed"
        )
    derive_label = _payload_boolean(payload, "derive_label") if "derive_label" in payload else False
    bounds = _freeform_bounds(payload)
    if bounds.width < 0 or bounds.height < 0:
        raise CommandError("FREEFORM_NEGATIVE_SIZE", "Shape size cannot be negative")
    replacement = replace(
        target,
        bounds=bounds,
        rotation=_payload_number(payload, "rotation"),
        text=(
            _payload_string(payload, "text", allow_empty=True) if "text" in payload else target.text
        ),
        fill=(_payload_string(payload, "fill") if "fill" in payload else target.fill),
        stroke=(_payload_string(payload, "stroke") if "stroke" in payload else target.stroke),
        asset_id=(
            _payload_string(payload, "asset_id", allow_empty=True) or None
            if "asset_id" in payload
            else target.asset_id
        ),
        label_override=(
            None if derive_label else _payload_string(payload, "text", allow_empty=True)
        )
        if (
            document.live_projection is not None
            and target.semantic_id is not None
            and ("text" in payload or derive_label)
        )
        else target.label_override,
    )
    objects = tuple(replacement if item.id == object_id else item for item in document.objects)
    return _document_snapshot_mutation(
        project,
        document_index,
        replace(document, objects=objects),
        "freeform.object_transformed",
        {"diagram_id": diagram_id, "object_id": object_id},
        (diagram_id, object_id),
    )


def _remove_freeform_objects(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    object_ids = set(_payload_string_list(payload, "object_ids"))
    document_index, document = _freeform_document(project, diagram_id)
    existing = {item.id for item in document.objects}
    if not object_ids <= existing:
        raise CommandError("FREEFORM_OBJECT_NOT_FOUND", "One or more objects do not exist")
    locked_layers = {layer.id for layer in document.layers if layer.locked}
    if any(
        item.id in object_ids and (item.locked or item.layer_id in locked_layers)
        for item in document.objects
    ):
        raise CommandError("FREEFORM_OBJECT_LOCKED", "Locked objects or layers cannot be removed")
    removed = set(object_ids)
    for item in document.objects:
        if isinstance(item, ConnectorObject) and (
            item.source_id in object_ids or item.target_id in object_ids
        ):
            removed.add(item.id)
    objects = tuple(item for item in document.objects if item.id not in removed)
    event_payload: dict[str, JsonValue] = {
        "diagram_id": diagram_id,
        "object_ids": cast(JsonValue, sorted(removed)),
    }
    return _document_snapshot_mutation(
        project,
        document_index,
        replace(document, objects=objects),
        "freeform.objects_removed",
        event_payload,
        (diagram_id, *sorted(removed)),
    )


def _create_freeform_connector(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    connector_id = _payload_string(payload, "connector_id")
    source_id = _payload_string(payload, "source_id")
    target_id = _payload_string(payload, "target_id")
    document_index, document = _freeform_document(project, diagram_id)
    if any(item.id == connector_id for item in document.objects):
        raise CommandError("FREEFORM_DUPLICATE_OBJECT", "Connector ID already exists")
    endpoints = {item.id for item in document.objects if isinstance(item, ShapeObject)}
    if source_id not in endpoints or target_id not in endpoints:
        raise CommandError("FREEFORM_UNRESOLVED_CONNECTOR", "Connector endpoints must be shapes")
    connector = ConnectorObject(
        connector_id,
        source_id,
        target_id,
        orthogonal=_payload_boolean(payload, "orthogonal"),
        label=_payload_string(payload, "label", allow_empty=True),
    )
    updated = replace(document, objects=(*document.objects, connector))
    return _document_snapshot_mutation(
        project,
        document_index,
        updated,
        "freeform.connector_created",
        {"connector_id": connector_id, "diagram_id": diagram_id},
        (diagram_id, connector_id, source_id, target_id),
    )


def _set_freeform_properties(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    object_ids = set(_payload_string_list(payload, "object_ids"))
    document_index, document = _freeform_document(project, diagram_id)
    if not object_ids <= {item.id for item in document.objects}:
        raise CommandError("FREEFORM_OBJECT_NOT_FOUND", "One or more objects do not exist")
    locked_layers = {layer.id for layer in document.layers if layer.locked}
    if any(item.id in object_ids and item.layer_id in locked_layers for item in document.objects):
        raise CommandError("FREEFORM_LAYER_LOCKED", "Objects on a locked layer cannot be edited")
    layer_id = _payload_optional_string(payload, "layer_id")
    if layer_id is not None and not any(layer.id == layer_id for layer in document.layers):
        raise CommandError("FREEFORM_LAYER_NOT_FOUND", f"Layer {layer_id!r} does not exist")
    replacements: list[ShapeObject | ConnectorObject] = []
    for item in document.objects:
        if item.id not in object_ids:
            replacements.append(item)
            continue
        if isinstance(item, ShapeObject):
            group = (
                _payload_string(payload, "group_id", allow_empty=True) or None
                if "group_id" in payload
                else item.group_id
            )
            replacements.append(
                replace(
                    item,
                    locked=(
                        _payload_boolean(payload, "locked") if "locked" in payload else item.locked
                    ),
                    hidden=(
                        _payload_boolean(payload, "hidden") if "hidden" in payload else item.hidden
                    ),
                    layer_id=layer_id or item.layer_id,
                    group_id=group,
                    z_index=(
                        _payload_integer(payload, "z_index")
                        if "z_index" in payload
                        else item.z_index
                    ),
                )
            )
        else:
            replacements.append(
                replace(
                    item,
                    locked=(
                        _payload_boolean(payload, "locked") if "locked" in payload else item.locked
                    ),
                    layer_id=layer_id or item.layer_id,
                )
            )
    event_payload: dict[str, JsonValue] = {
        "diagram_id": diagram_id,
        "object_ids": cast(JsonValue, sorted(object_ids)),
    }
    return _document_snapshot_mutation(
        project,
        document_index,
        replace(document, objects=tuple(replacements)),
        "freeform.properties_changed",
        event_payload,
        (diagram_id, *sorted(object_ids)),
    )


def _arrange_freeform_objects(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    object_ids = _payload_string_list(payload, "object_ids")
    arrangement = _payload_string(payload, "arrangement")
    allowed = {
        "align_left",
        "align_right",
        "align_top",
        "align_bottom",
        "align_horizontal_center",
        "align_vertical_center",
        "distribute_horizontal",
        "distribute_vertical",
    }
    if arrangement not in allowed:
        raise CommandError("FREEFORM_UNKNOWN_ARRANGEMENT", arrangement)
    document_index, document = _freeform_document(project, diagram_id)
    selected = [
        item for item in document.objects if item.id in object_ids and isinstance(item, ShapeObject)
    ]
    if len(selected) != len(object_ids) or len(selected) < 2:
        raise CommandError("FREEFORM_INVALID_SELECTION", "Arrange needs at least two shapes")
    locked_layers = {layer.id for layer in document.layers if layer.locked}
    if any(item.locked or item.layer_id in locked_layers for item in selected):
        raise CommandError("FREEFORM_OBJECT_LOCKED", "Locked selections cannot be arranged")
    target_bounds: dict[str, FreeformRect] = {item.id: item.bounds for item in selected}
    if arrangement.startswith("align_"):
        anchor = selected[0].bounds
        for item in selected[1:]:
            bounds = item.bounds
            if arrangement == "align_left":
                x, y = anchor.x, bounds.y
            elif arrangement == "align_right":
                x, y = anchor.x + anchor.width - bounds.width, bounds.y
            elif arrangement == "align_top":
                x, y = bounds.x, anchor.y
            elif arrangement == "align_bottom":
                x, y = bounds.x, anchor.y + anchor.height - bounds.height
            elif arrangement == "align_horizontal_center":
                x, y = anchor.x + (anchor.width - bounds.width) / 2, bounds.y
            else:
                x, y = bounds.x, anchor.y + (anchor.height - bounds.height) / 2
            target_bounds[item.id] = FreeformRect(x, y, bounds.width, bounds.height)
    else:
        horizontal = arrangement == "distribute_horizontal"
        ordered = sorted(selected, key=lambda item: item.bounds.x if horizontal else item.bounds.y)
        first = ordered[0].bounds
        last = ordered[-1].bounds
        span = (last.x - first.x) if horizontal else (last.y - first.y)
        step = span / (len(ordered) - 1)
        for index, item in enumerate(ordered):
            bounds = item.bounds
            x = first.x + step * index if horizontal else bounds.x
            y = bounds.y if horizontal else first.y + step * index
            target_bounds[item.id] = FreeformRect(x, y, bounds.width, bounds.height)
    objects = tuple(
        replace(item, bounds=target_bounds[item.id])
        if isinstance(item, ShapeObject) and item.id in target_bounds
        else item
        for item in document.objects
    )
    return _document_snapshot_mutation(
        project,
        document_index,
        replace(document, objects=objects),
        "freeform.objects_arranged",
        {"arrangement": arrangement, "diagram_id": diagram_id},
        (diagram_id, *object_ids),
    )


def _add_freeform_layer(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    layer_id = _payload_string(payload, "layer_id")
    name = _payload_string(payload, "name")
    document_index, document = _freeform_document(project, diagram_id)
    if any(layer.id == layer_id for layer in document.layers):
        raise CommandError("FREEFORM_DUPLICATE_LAYER", f"Layer {layer_id!r} already exists")
    updated = replace(document, layers=(*document.layers, Layer(layer_id, name)))
    return _document_snapshot_mutation(
        project,
        document_index,
        updated,
        "freeform.layer_added",
        {"diagram_id": diagram_id, "layer_id": layer_id, "name": name},
        (diagram_id, layer_id),
    )


def _update_freeform_layer(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    layer_id = _payload_string(payload, "layer_id")
    document_index, document = _freeform_document(project, diagram_id)
    target = next((layer for layer in document.layers if layer.id == layer_id), None)
    if target is None:
        raise CommandError("FREEFORM_LAYER_NOT_FOUND", f"Layer {layer_id!r} does not exist")
    replacement = replace(
        target,
        name=_payload_string(payload, "name"),
        hidden=_payload_boolean(payload, "hidden"),
        locked=_payload_boolean(payload, "locked"),
    )
    layers = tuple(replacement if layer.id == layer_id else layer for layer in document.layers)
    return _document_snapshot_mutation(
        project,
        document_index,
        replace(document, layers=layers),
        "freeform.layer_changed",
        {"diagram_id": diagram_id, "layer_id": layer_id},
        (diagram_id, layer_id),
    )


def _remove_freeform_layer(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    layer_id = _payload_string(payload, "layer_id")
    fallback_id = _payload_string(payload, "fallback_layer_id")
    document_index, document = _freeform_document(project, diagram_id)
    if layer_id == "layer_default":
        raise CommandError("FREEFORM_DEFAULT_LAYER_REQUIRED", "The default layer cannot be removed")
    if not any(layer.id == layer_id for layer in document.layers):
        raise CommandError("FREEFORM_LAYER_NOT_FOUND", f"Layer {layer_id!r} does not exist")
    if fallback_id == layer_id or not any(layer.id == fallback_id for layer in document.layers):
        raise CommandError("FREEFORM_LAYER_NOT_FOUND", "Choose another existing fallback layer")
    layers = tuple(layer for layer in document.layers if layer.id != layer_id)
    objects = tuple(
        replace(item, layer_id=fallback_id) if item.layer_id == layer_id else item
        for item in document.objects
    )
    return _document_snapshot_mutation(
        project,
        document_index,
        replace(document, layers=layers, objects=objects),
        "freeform.layer_removed",
        {
            "diagram_id": diagram_id,
            "fallback_layer_id": fallback_id,
            "layer_id": layer_id,
        },
        (diagram_id, layer_id, fallback_id),
    )


def _add_freeform_guide(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    guide_id = _payload_string(payload, "guide_id")
    document_index, document = _freeform_document(project, diagram_id)
    if any(guide.id == guide_id for guide in document.guides):
        raise CommandError("FREEFORM_DUPLICATE_GUIDE", f"Guide {guide_id!r} already exists")
    try:
        orientation = GuideOrientation(_payload_string(payload, "orientation"))
    except ValueError as exc:
        raise CommandError("FREEFORM_UNKNOWN_GUIDE", str(exc)) from exc
    guide = Guide(guide_id, orientation, _payload_number(payload, "position"))
    return _document_snapshot_mutation(
        project,
        document_index,
        replace(document, guides=(*document.guides, guide)),
        "freeform.guide_added",
        {"diagram_id": diagram_id, "guide_id": guide_id},
        (diagram_id, guide_id),
    )


def _remove_freeform_guide(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    guide_id = _payload_string(payload, "guide_id")
    document_index, document = _freeform_document(project, diagram_id)
    if not any(guide.id == guide_id for guide in document.guides):
        raise CommandError("FREEFORM_GUIDE_NOT_FOUND", f"Guide {guide_id!r} does not exist")
    return _document_snapshot_mutation(
        project,
        document_index,
        replace(document, guides=tuple(guide for guide in document.guides if guide.id != guide_id)),
        "freeform.guide_removed",
        {"diagram_id": diagram_id, "guide_id": guide_id},
        (diagram_id, guide_id),
    )


def _configure_freeform_canvas(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    diagram_id = _payload_string(payload, "diagram_id")
    grid_size = _payload_number(payload, "grid_size")
    if grid_size < 1.0 or grid_size > 10_000.0:
        raise CommandError("FREEFORM_INVALID_GRID", "Grid size must be between 1 and 10000")
    document_index, document = _freeform_document(project, diagram_id)
    updated = replace(
        document,
        grid_size=grid_size,
        snap_to_grid=_payload_boolean(payload, "snap_to_grid"),
    )
    return _document_snapshot_mutation(
        project,
        document_index,
        updated,
        "freeform.canvas_configured",
        {"diagram_id": diagram_id, "grid_size": grid_size},
        (diagram_id,),
    )


def _managed_asset_from_payload(payload: dict[str, JsonValue]) -> ManagedAsset:
    return ManagedAsset(
        id=_payload_string(payload, "id"),
        relative_path=_payload_string(payload, "relative_path"),
        sha256=_payload_string(payload, "sha256"),
        media_type=_payload_string(payload, "media_type"),
        byte_size=_payload_integer(payload, "byte_size"),
        original_name=_payload_string(payload, "original_name", allow_empty=True),
        width=_payload_optional_integer(payload, "width"),
        height=_payload_optional_integer(payload, "height"),
    )


def _managed_asset_payload(asset: ManagedAsset) -> dict[str, JsonValue]:
    return {
        "byte_size": asset.byte_size,
        "height": asset.height,
        "id": asset.id,
        "media_type": asset.media_type,
        "original_name": asset.original_name,
        "relative_path": asset.relative_path,
        "sha256": asset.sha256,
        "width": asset.width,
    }


def _register_managed_asset(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    asset = _managed_asset_from_payload(payload)
    if any(item.id == asset.id for item in project.managed_assets):
        raise CommandError("ASSET_DUPLICATE_ID", f"Asset {asset.id!r} already exists")
    return Mutation(
        replace(project, managed_assets=(*project.managed_assets, asset)),
        "asset.registered",
        {"asset_id": asset.id, "sha256": asset.sha256},
        (asset.id,),
        Operation("asset.remove", {"asset_id": asset.id}),
    )


def _remove_managed_asset(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    asset_id = _payload_string(payload, "asset_id")
    asset = next((item for item in project.managed_assets if item.id == asset_id), None)
    if asset is None:
        raise CommandError("ASSET_NOT_FOUND", f"Asset {asset_id!r} does not exist")
    for document in project.documents:
        if isinstance(document, FreeformDiagram) and any(
            isinstance(item, ShapeObject) and item.asset_id == asset_id for item in document.objects
        ):
            raise CommandError("ASSET_IN_USE", "Remove shapes using this image before the asset")
        if isinstance(document, MindMapDiagram) and any(
            asset_id in topic.attachments for topic in walk_topics(document.root)
        ):
            raise CommandError("ASSET_IN_USE", "Remove topic attachments before the asset")
    return Mutation(
        replace(
            project,
            managed_assets=tuple(item for item in project.managed_assets if item.id != asset_id),
        ),
        "asset.removed",
        {"asset_id": asset_id},
        (asset_id,),
        Operation("asset.register", _managed_asset_payload(asset)),
    )


def _shape_pack_from_payload(payload: dict[str, JsonValue]) -> ShapePackReference:
    return ShapePackReference(
        id=_payload_string(payload, "id"),
        name=_payload_string(payload, "name"),
        version=_payload_string(payload, "version"),
        manifest_path=_payload_string(payload, "manifest_path"),
        sha256=_payload_string(payload, "sha256"),
    )


def _shape_pack_payload(pack: ShapePackReference) -> dict[str, JsonValue]:
    return {
        "id": pack.id,
        "manifest_path": pack.manifest_path,
        "name": pack.name,
        "sha256": pack.sha256,
        "version": pack.version,
    }


def _register_shape_pack(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    pack = _shape_pack_from_payload(payload)
    if any(item.id == pack.id for item in project.shape_packs):
        raise CommandError("SHAPE_PACK_DUPLICATE_ID", f"Shape pack {pack.id!r} already exists")
    return Mutation(
        replace(project, shape_packs=(*project.shape_packs, pack)),
        "shape_pack.registered",
        {"shape_pack_id": pack.id, "version": pack.version},
        (pack.id,),
        Operation("shape_pack.remove", {"shape_pack_id": pack.id}),
    )


def _remove_shape_pack(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    pack_id = _payload_string(payload, "shape_pack_id")
    pack = next((item for item in project.shape_packs if item.id == pack_id), None)
    if pack is None:
        raise CommandError("SHAPE_PACK_NOT_FOUND", f"Shape pack {pack_id!r} does not exist")
    return Mutation(
        replace(
            project, shape_packs=tuple(item for item in project.shape_packs if item.id != pack_id)
        ),
        "shape_pack.removed",
        {"shape_pack_id": pack_id},
        (pack_id,),
        Operation("shape_pack.register", _shape_pack_payload(pack)),
    )


def _transaction_operation(operations: Iterable[Operation]) -> Operation:
    return Operation(
        "transaction",
        {"operations": [operation.to_data() for operation in operations]},
    )


def _operations_from_transaction(operation: Operation) -> tuple[Operation, ...]:
    raw = operation.payload.get("operations")
    if not isinstance(raw, list):
        raise CommandError("COMMAND_INVALID_PAYLOAD", "transaction operations must be a list")
    try:
        return tuple(Operation.from_data(item) for item in raw)
    except ValueError as exc:
        raise CommandError("COMMAND_INVALID_PAYLOAD", str(exc)) from exc


class ProjectAuthority:
    def __init__(
        self,
        project: Project,
        *,
        store: ProjectStore | None = None,
        handlers: dict[str, Handler] | None = None,
        clock: Clock = _utc_now,
        event_history_limit: int = 2_000,
        read_only: bool = False,
        write_guard: Callable[[], str | None] | None = None,
    ) -> None:
        if event_history_limit < 1:
            raise ValueError("event_history_limit must be positive")
        self._project = canonicalize_project(project)
        self._store = store
        if handlers is None:
            # Imported lazily after this module has defined every handler. The
            # separate composition root is static and intentionally not a plugin loader.
            from code_visualizer.application.authority_contributions import (
                authority_handlers,
            )

            self._handlers = authority_handlers()
        else:
            self._handlers = dict(handlers)
        self._clock = clock
        self._read_only = read_only
        self._write_guard = write_guard
        self._commit_admission: (
            Callable[[Project, JournalRecord], CommandRejected | CommandDeferred | None] | None
        ) = None
        self._lock = RLock()
        self._subscribers: list[Subscriber] = []
        self._history: list[HistoryEntry] = []
        self._completed: dict[str, CommandAccepted] = {}
        self._event_log: deque[EventEnvelope] = deque(maxlen=event_history_limit)
        if store is not None:
            self._restore_history(store.read_journal())

    @property
    def revision(self) -> int:
        with self._lock:
            return self._project.revision

    @property
    def has_store(self) -> bool:
        with self._lock:
            return self._store is not None

    @property
    def is_read_only(self) -> bool:
        return self._read_only

    def attach_store(self, store: ProjectStore) -> None:
        with self._lock:
            if self._read_only:
                raise RuntimeError("A read-only authority cannot attach writable storage")
            if self._store is not None and self._store.root != store.root:
                raise RuntimeError("A project authority cannot switch persistence roots")
            self._store = store

    def set_write_guard(self, guard: Callable[[], str | None]) -> None:
        """Install the host's external storage/lifecycle admission guard."""
        with self._lock:
            self._write_guard = guard

    def set_commit_admission(
        self,
        admission: Callable[[Project, JournalRecord], CommandRejected | CommandDeferred | None]
        | None,
    ) -> None:
        """A bounded host gate over a validated native command candidate.

        The gate may enqueue work. It must never perform IO or mutate canonical
        state. Deferred candidates have not been persisted, published or accepted.
        """
        with self._lock:
            self._commit_admission = admission

    def apply_transferred(
        self, record: JournalRecord, *, expected_project: Project
    ) -> CommandResult:
        """Resume one deferred native command in its explicitly seeded fork.

        This uses the same typed operations, validation, history and commit path.
        The captured candidate must be reproducible from that exact predecessor.
        """
        with self._lock:
            if self._read_only:
                return self._read_only_rejection()
            if self._project != expected_project:
                return CommandRejected(
                    "REVISION_CONFLICT", "Fork predecessor changed", self._project.revision, {}
                )
            if record.history_action in {"undo", "redo"}:
                method = self.undo if record.history_action == "undo" else self.redo
                return method(
                    actor_id=record.actor_id,
                    operation_id=record.operation_id,
                    expected_revision=self._project.revision,
                )
            if (
                record.forward_type is None
                or record.forward_payload is None
                or record.inverse_type is None
                or record.inverse_payload is None
            ):
                return CommandRejected(
                    "COMMAND_TRANSFER_INVALID",
                    "Missing native command history",
                    self._project.revision,
                    {},
                )
            forward = Operation(record.forward_type, record.forward_payload)
            try:
                candidate, events, affected = self._apply_history_operation(self._project, forward)
                if replace(candidate, revision=record.revision) != record.project:
                    return CommandRejected(
                        "COMMAND_TRANSFER_INVALID",
                        "Command candidate changed",
                        self._project.revision,
                        {},
                    )
                return self._commit(
                    actor_id=record.actor_id,
                    operation_id=record.operation_id,
                    command_type=record.command_type,
                    forward=forward,
                    inverse=Operation(record.inverse_type, record.inverse_payload),
                    project=candidate,
                    events=events,
                    affected_ids=affected,
                    intent="Accepted after experiment fork",
                )
            except CommandError as exc:
                return CommandRejected(exc.code, exc.message, self._project.revision, exc.details)

    def checkpoint(self, expected_revision: int) -> bool:
        """Compact durable state under the same lock used by semantic commits."""
        with self._lock:
            if (
                self._read_only
                or self._store is None
                or self._project.revision != expected_revision
            ):
                return False
            if self._write_guard is not None and self._write_guard() is not None:
                return False
            self._store.save(self._project)
            return True

    def snapshot(self) -> Project:
        with self._lock:
            return self._project

    def subscribe(self, subscriber: Subscriber) -> Callable[[], None]:
        with self._lock:
            self._subscribers.append(subscriber)

        def unsubscribe() -> None:
            with self._lock:
                if subscriber in self._subscribers:
                    self._subscribers.remove(subscriber)

        return unsubscribe

    def events_since(self, revision: int) -> tuple[EventEnvelope, ...] | None:
        """Return a bounded replay or ``None`` when a snapshot resync is required."""

        with self._lock:
            if revision < 0 or revision > self._project.revision:
                return None
            if revision == self._project.revision:
                return ()
            if not self._event_log:
                return None
            oldest_revision = self._event_log[0].revision
            if revision < oldest_revision - 1:
                return None
            return tuple(event for event in self._event_log if event.revision > revision)

    def preview_history(self, *, actor_id: str, redo: bool = False) -> dict[str, JsonValue]:
        """Describe the actor-scoped compensating command without mutating state."""

        with self._lock:
            target = next(
                (
                    entry
                    for entry in (self._history if redo else reversed(self._history))
                    if entry.actor_id == actor_id and entry.undone is redo
                ),
                None,
            )
            if target is None:
                return {
                    "affected_ids": [],
                    "can_apply": False,
                    "current_revision": self._project.revision,
                    "reason": "empty",
                    "target_revision": None,
                }
            conflicts: set[str] = set()
            if not redo:
                target_index = self._history.index(target)
                later_ids = set().union(
                    *(
                        entry.affected_ids
                        for entry in self._history[target_index + 1 :]
                        if not entry.undone
                    ),
                    set(),
                )
                conflicts = set(target.affected_ids) & later_ids
            return {
                "affected_ids": cast(JsonValue, sorted(target.affected_ids)),
                "can_apply": not conflicts,
                "command_type": target.forward.command_type,
                "conflicting_ids": cast(JsonValue, sorted(conflicts)),
                "current_revision": self._project.revision,
                "reason": "conflict" if conflicts else "ready",
                "target_operation_id": target.operation_id,
                "target_revision": target.revision,
            }

    def execute(self, command: CommandEnvelope) -> CommandResult:
        with self._lock:
            if self._read_only:
                return self._read_only_rejection()
            rejected = self._precondition(command)
            if rejected is not None:
                return rejected
            completed = self._completed.get(command.operation_id)
            if completed is not None:
                return completed
            try:
                forward = Operation(command.command_type, command.payload)
                mutation = self._apply(self._project, forward)
                return self._commit(
                    actor_id=command.actor_id,
                    operation_id=command.operation_id,
                    command_type=command.command_type,
                    forward=mutation.history_forward or forward,
                    inverse=mutation.inverse,
                    project=mutation.project,
                    events=((mutation.event_type, mutation.event_payload),),
                    affected_ids=mutation.affected_ids,
                    intent=command.intent,
                )
            except CommandError as exc:
                return CommandRejected(
                    exc.code,
                    exc.message,
                    self._project.revision,
                    exc.details,
                )

    def execute_transaction(
        self,
        commands: Sequence[CommandEnvelope],
        *,
        actor_id: str,
        operation_id: str,
        expected_revision: int,
        intent: str = "",
    ) -> CommandResult:
        with self._lock:
            if self._read_only:
                return self._read_only_rejection()
            if not commands:
                return CommandRejected(
                    "TRANSACTION_EMPTY",
                    "A transaction must contain at least one command",
                    self._project.revision,
                    {},
                )
            synthetic = CommandEnvelope(
                command_type=commands[0].command_type,
                actor_id=actor_id,
                operation_id=operation_id,
                project_id=self._project.id,
                expected_revision=expected_revision,
                payload={},
                intent=intent,
            )
            if any(
                type(item.schema_version) is not int or item.schema_version != 1
                for item in commands
            ):
                return CommandRejected(
                    "COMMAND_VERSION_UNSUPPORTED",
                    "Every transaction command envelope schema version must be 1",
                    self._project.revision,
                    {"supported_schema_version": 1},
                )
            rejected = self._precondition(synthetic)
            if rejected is not None:
                return rejected
            completed = self._completed.get(operation_id)
            if completed is not None:
                return completed
            candidate = self._project
            forwards: list[Operation] = []
            inverses: list[Operation] = []
            events: list[tuple[str, dict[str, JsonValue]]] = []
            affected: list[str] = []
            try:
                for command in commands:
                    if command.actor_id != actor_id or command.project_id != self._project.id:
                        raise CommandError(
                            "TRANSACTION_IDENTITY_MISMATCH",
                            "All commands must use the transaction actor and project",
                        )
                    forward = Operation(command.command_type, command.payload)
                    mutation = self._apply(candidate, forward)
                    candidate = mutation.project
                    forwards.append(mutation.history_forward or forward)
                    inverses.insert(0, mutation.inverse)
                    events.append((mutation.event_type, mutation.event_payload))
                    affected.extend(mutation.affected_ids)
                return self._commit(
                    actor_id=actor_id,
                    operation_id=operation_id,
                    command_type="transaction",
                    forward=_transaction_operation(forwards),
                    inverse=_transaction_operation(inverses),
                    project=candidate,
                    events=tuple(events),
                    affected_ids=tuple(dict.fromkeys(affected)),
                    intent=intent,
                )
            except CommandError as exc:
                return CommandRejected(
                    exc.code,
                    exc.message,
                    self._project.revision,
                    exc.details,
                )

    def undo(
        self,
        *,
        actor_id: str,
        operation_id: str,
        expected_revision: int,
    ) -> CommandResult:
        with self._lock:
            if self._read_only:
                return self._read_only_rejection()
            completed = self._completed.get(operation_id)
            if completed is not None:
                return completed
            rejected = self._history_precondition(
                actor_id=actor_id,
                operation_id=operation_id,
                expected_revision=expected_revision,
            )
            if rejected is not None:
                return rejected
            target = next(
                (
                    entry
                    for entry in reversed(self._history)
                    if entry.actor_id == actor_id and not entry.undone
                ),
                None,
            )
            if target is None:
                return CommandRejected(
                    "UNDO_EMPTY",
                    "There is no compatible command to undo",
                    self._project.revision,
                    {},
                )
            target_index = self._history.index(target)
            later_ids = set().union(
                *(
                    entry.affected_ids
                    for entry in self._history[target_index + 1 :]
                    if not entry.undone
                ),
                set(),
            )
            conflicts = sorted(target.affected_ids & later_ids)
            if conflicts:
                conflict_values: list[JsonValue] = list(conflicts)
                return CommandRejected(
                    "UNDO_CONFLICT",
                    "Later commands changed the same semantic objects",
                    self._project.revision,
                    {"conflicting_ids": conflict_values},
                )
            try:
                candidate, event_specs, affected = self._apply_history_operation(
                    self._project, target.inverse
                )
                result = self._commit_history_action(
                    actor_id=actor_id,
                    operation_id=operation_id,
                    command_type="history.undo",
                    project=candidate,
                    event_specs=event_specs,
                    affected_ids=affected,
                    target=target,
                    action="undo",
                )
                if isinstance(result, CommandAccepted):
                    target.undone = True
                return result
            except CommandError as exc:
                return CommandRejected(
                    exc.code,
                    exc.message,
                    self._project.revision,
                    exc.details,
                )

    def redo(
        self,
        *,
        actor_id: str,
        operation_id: str,
        expected_revision: int,
    ) -> CommandResult:
        with self._lock:
            if self._read_only:
                return self._read_only_rejection()
            completed = self._completed.get(operation_id)
            if completed is not None:
                return completed
            rejected = self._history_precondition(
                actor_id=actor_id,
                operation_id=operation_id,
                expected_revision=expected_revision,
            )
            if rejected is not None:
                return rejected
            target = next(
                (entry for entry in self._history if entry.actor_id == actor_id and entry.undone),
                None,
            )
            if target is None:
                return CommandRejected(
                    "REDO_EMPTY",
                    "There is no compatible command to redo",
                    self._project.revision,
                    {},
                )
            try:
                candidate, event_specs, affected = self._apply_history_operation(
                    self._project, target.forward
                )
                result = self._commit_history_action(
                    actor_id=actor_id,
                    operation_id=operation_id,
                    command_type="history.redo",
                    project=candidate,
                    event_specs=event_specs,
                    affected_ids=affected,
                    target=target,
                    action="redo",
                )
                if isinstance(result, CommandAccepted):
                    target.undone = False
                return result
            except CommandError as exc:
                return CommandRejected(
                    exc.code,
                    exc.message,
                    self._project.revision,
                    exc.details,
                )

    def _read_only_rejection(self) -> CommandRejected:
        return CommandRejected(
            "PROJECT_READ_ONLY",
            "This project is open read-only because another authority owns it",
            self._project.revision,
            {},
        )

    def _precondition(self, command: CommandEnvelope) -> CommandRejected | None:
        if type(command.schema_version) is not int or command.schema_version != 1:
            return CommandRejected(
                "COMMAND_VERSION_UNSUPPORTED",
                "Command envelope schema version must be 1",
                self._project.revision,
                {"supported_schema_version": 1},
            )
        if command.project_id != self._project.id:
            return CommandRejected(
                "PROJECT_ID_MISMATCH",
                "Command targets a different project",
                self._project.revision,
                {"project_id": self._project.id},
            )
        completed = self._completed.get(command.operation_id)
        if completed is not None:
            return None
        if (
            command.expected_revision is not None
            and command.expected_revision != self._project.revision
        ):
            return CommandRejected(
                "REVISION_CONFLICT",
                "Expected revision does not match the current project",
                self._project.revision,
                {"expected_revision": command.expected_revision},
            )
        if command.command_type not in self._handlers:
            return CommandRejected(
                "COMMAND_UNKNOWN",
                f"Unknown command {command.command_type!r}",
                self._project.revision,
                {},
            )
        return None

    def _history_precondition(
        self,
        *,
        actor_id: str,
        operation_id: str,
        expected_revision: int,
    ) -> CommandRejected | None:
        del actor_id
        completed = self._completed.get(operation_id)
        if completed is not None:
            return None
        if expected_revision != self._project.revision:
            return CommandRejected(
                "REVISION_CONFLICT",
                "Expected revision does not match the current project",
                self._project.revision,
                {"expected_revision": expected_revision},
            )
        return None

    def _apply(self, project: Project, operation: Operation) -> Mutation:
        handler = self._handlers.get(operation.command_type)
        if handler is None:
            raise CommandError("COMMAND_UNKNOWN", f"Unknown command {operation.command_type!r}")
        return handler(project, operation.payload)

    def _apply_history_operation(
        self,
        project: Project,
        operation: Operation,
    ) -> tuple[Project, tuple[tuple[str, dict[str, JsonValue]], ...], tuple[str, ...]]:
        operations = (
            _operations_from_transaction(operation)
            if operation.command_type == "transaction"
            else (operation,)
        )
        candidate = project
        events: list[tuple[str, dict[str, JsonValue]]] = []
        affected: list[str] = []
        for item in operations:
            mutation = self._apply(candidate, item)
            candidate = mutation.project
            events.append((mutation.event_type, mutation.event_payload))
            affected.extend(mutation.affected_ids)
        return candidate, tuple(events), tuple(dict.fromkeys(affected))

    def _commit(
        self,
        *,
        actor_id: str,
        operation_id: str,
        command_type: str,
        forward: Operation,
        inverse: Operation,
        project: Project,
        events: tuple[tuple[str, dict[str, JsonValue]], ...],
        affected_ids: tuple[str, ...],
        intent: str,
    ) -> CommandResult:
        del intent
        if self._write_guard is not None and (reason := self._write_guard()) is not None:
            return CommandRejected("PROJECT_STORAGE_CHANGED", reason, self._project.revision, {})
        candidate = replace(project, revision=self._project.revision + 1)
        validation = tuple(
            diagnostic
            for diagnostic in validate_integrity(candidate)
            if diagnostic.severity is Severity.ERROR
        )
        if validation:
            first = validation[0]
            return CommandRejected(
                "COMMAND_INVALID_RESULT",
                first.message,
                self._project.revision,
                {"diagnostic_code": first.code},
            )
        event_envelopes = tuple(
            EventEnvelope(
                event_type=event_type,
                actor_id=actor_id,
                operation_id=operation_id,
                project_id=candidate.id,
                revision=candidate.revision,
                payload=payload,
                occurred_at=self._clock(),
                affected_ids=affected_ids,
            )
            for event_type, payload in events
        )
        accepted = CommandAccepted(
            revision=candidate.revision,
            affected_ids=affected_ids,
            events=event_envelopes,
            undo_group_id=operation_id,
        )
        record = JournalRecord(
            revision=candidate.revision,
            actor_id=actor_id,
            operation_id=operation_id,
            command_type=command_type,
            project=candidate,
            affected_ids=affected_ids,
            forward_type=forward.command_type,
            forward_payload=forward.payload,
            inverse_type=inverse.command_type,
            inverse_payload=inverse.payload,
            occurred_at=self._clock(),
        )
        persistence_error = self._persist(record)
        if persistence_error is not None:
            return persistence_error
        self._history = [entry for entry in self._history if not entry.undone]
        self._history.append(
            HistoryEntry(
                operation_id=operation_id,
                actor_id=actor_id,
                revision=candidate.revision,
                forward=forward,
                inverse=inverse,
                affected_ids=frozenset(affected_ids),
            )
        )
        self._project = candidate
        self._completed[operation_id] = accepted
        self._publish(event_envelopes)
        return accepted

    def _commit_history_action(
        self,
        *,
        actor_id: str,
        operation_id: str,
        command_type: str,
        project: Project,
        event_specs: tuple[tuple[str, dict[str, JsonValue]], ...],
        affected_ids: tuple[str, ...],
        target: HistoryEntry,
        action: str,
    ) -> CommandResult:
        if self._write_guard is not None and (reason := self._write_guard()) is not None:
            return CommandRejected("PROJECT_STORAGE_CHANGED", reason, self._project.revision, {})
        candidate = replace(project, revision=self._project.revision + 1)
        event = EventEnvelope(
            event_type=f"history.{action}ne" if action == "undo" else "history.redone",
            actor_id=actor_id,
            operation_id=operation_id,
            project_id=candidate.id,
            revision=candidate.revision,
            payload={
                "affected_ids": list(affected_ids),
                "target_operation_id": target.operation_id,
            },
            occurred_at=self._clock(),
            affected_ids=affected_ids,
        )
        semantic_events = tuple(
            EventEnvelope(
                event_type=event_type,
                actor_id=actor_id,
                operation_id=operation_id,
                project_id=candidate.id,
                revision=candidate.revision,
                payload=payload,
                occurred_at=self._clock(),
                affected_ids=affected_ids,
            )
            for event_type, payload in event_specs
        )
        accepted = CommandAccepted(
            revision=candidate.revision,
            affected_ids=affected_ids,
            events=(*semantic_events, event),
            undo_group_id=operation_id,
        )
        record = JournalRecord(
            revision=candidate.revision,
            actor_id=actor_id,
            operation_id=operation_id,
            command_type=command_type,
            project=candidate,
            affected_ids=affected_ids,
            history_action=action,
            target_operation_id=target.operation_id,
            occurred_at=self._clock(),
        )
        persistence_error = self._persist(record)
        if persistence_error is not None:
            return persistence_error
        self._project = candidate
        self._completed[operation_id] = accepted
        self._publish(accepted.events)
        return accepted

    def _persist(self, record: JournalRecord) -> CommandRejected | CommandDeferred | None:
        if self._write_guard is not None and (reason := self._write_guard()) is not None:
            return CommandRejected("PROJECT_STORAGE_CHANGED", reason, self._project.revision, {})
        if self._commit_admission is not None:
            admission = self._commit_admission(self._project, record)
            if admission is not None:
                return admission
        if self._store is None:
            return None
        try:
            self._store.record_commit(record)
        except ProjectStoreError as exc:
            return CommandRejected(
                "PERSISTENCE_FAILED",
                str(exc),
                self._project.revision,
                {},
            )
        return None

    def _publish(self, events: tuple[EventEnvelope, ...]) -> None:
        self._event_log.extend(events)
        subscribers = tuple(self._subscribers)
        for event in events:
            for subscriber in subscribers:
                try:
                    subscriber(event)
                except Exception:
                    continue

    def _restore_history(self, records: tuple[JournalRecord, ...]) -> None:
        by_id: dict[str, HistoryEntry] = {}
        for record in records:
            self._completed[record.operation_id] = CommandAccepted(
                revision=record.revision,
                affected_ids=(),
                events=(),
                undo_group_id=record.operation_id,
            )
            if (
                record.history_action == "commit"
                and record.forward_type is not None
                and record.forward_payload is not None
                and record.inverse_type is not None
                and record.inverse_payload is not None
            ):
                entry = HistoryEntry(
                    operation_id=record.operation_id,
                    actor_id=record.actor_id,
                    revision=record.revision,
                    forward=Operation(record.forward_type, record.forward_payload),
                    inverse=Operation(record.inverse_type, record.inverse_payload),
                    affected_ids=frozenset(record.affected_ids),
                )
                self._history.append(entry)
                by_id[entry.operation_id] = entry
            elif record.target_operation_id in by_id:
                by_id[record.target_operation_id].undone = record.history_action == "undo"
