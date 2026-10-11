"""Typed edits of canonical Python declarations and their ownership."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from code_visualizer.application.authority import CommandError, Handler, Mutation
from code_visualizer.application.commands import ConfigureProgram, Operation
from code_visualizer.application.program_model import project_program_changes
from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.module_paths import canonical_module_path, canonical_package_path
from code_visualizer.domain.program import (
    ProgramClass,
    ProgramDeclaration,
    ProgramFunctionReference,
    ProgramModel,
    ProgramModule,
)
from code_visualizer.domain.project import Project
from code_visualizer.persistence.decoding import (
    program_class_from_data,
    program_entrypoint_from_data,
    program_module_from_data,
)


def _text(payload: dict[str, JsonValue], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise CommandError("COMMAND_INVALID_PAYLOAD", f"{key} must be non-empty text")
    return value


def header_operation(model: ProgramModel) -> Operation:
    return ConfigureProgram(model.package, model.modules, model.entrypoint).to_operation()


def update_owner(
    model: ProgramModel,
    owner_id: str,
    edit: Callable[[tuple[ProgramDeclaration, ...]], tuple[ProgramDeclaration, ...]],
) -> ProgramModel:
    found = False

    def visit[T: ProgramModule | ProgramClass](owner: T) -> T:
        nonlocal found
        if owner.id == owner_id:
            found = True
            return replace(owner, body=edit(owner.body))
        return replace(
            owner,
            body=tuple(
                visit(item) if isinstance(item, ProgramClass) else item for item in owner.body
            ),
        )

    modules = tuple(visit(item) for item in model.modules)
    if not found:
        raise CommandError("PROGRAM_OWNER_NOT_FOUND", f"Owner {owner_id!r} does not exist")
    return replace(model, modules=modules)


def remove_function_reference(model: ProgramModel, function_id: str) -> ProgramModel:
    owner = model.owner_of(function_id)
    if owner is None:
        raise CommandError("PROGRAM_OWNER_NOT_FOUND", f"Function {function_id!r} has no owner")
    return update_owner(
        model,
        owner.id,
        lambda body: tuple(
            item
            for item in body
            if not (isinstance(item, ProgramFunctionReference) and item.function_id == function_id)
        ),
    )


def attach_function(
    model: ProgramModel,
    function_id: str,
    owner_id: str,
    index: int | None = None,
) -> ProgramModel:
    def insert(body: tuple[ProgramDeclaration, ...]) -> tuple[ProgramDeclaration, ...]:
        offset = len(body) if index is None else index
        if offset < 0 or offset > len(body):
            raise CommandError("PROGRAM_INVALID_INSERTION", "Owner insertion index is out of range")
        return (*body[:offset], ProgramFunctionReference(function_id), *body[offset:])

    return update_owner(model, owner_id, insert)


def _mutation(project: Project, model: ProgramModel, event: str) -> Mutation:
    function_ids = frozenset(item.id for item in model.functions)
    return Mutation(
        project_program_changes(project, model, function_ids=function_ids),
        event,
        {},
        (project.id, *(item.id for item in model.modules), *sorted(function_ids)),
        header_operation(project.program_model),
        header_operation(model),
    )


def _configure(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    try:
        raw = payload.get("modules")
        if not isinstance(raw, list):
            raise ValueError("modules must be an array")
        modules = tuple(program_module_from_data(item, "$.payload.modules") for item in raw)
        modules = tuple(
            replace(item, path=canonical_module_path(item.path, kind=item.kind)) for item in modules
        )
        package = payload.get("package")
        if not isinstance(package, str):
            raise ValueError("package must be text")
        model = replace(
            project.program_model,
            package=canonical_package_path(package),
            modules=modules,
            entrypoint=(
                program_entrypoint_from_data(payload.get("entrypoint"), "$.payload.entrypoint")
                if payload.get("entrypoint") is not None
                else None
            ),
        )
    except ValueError as exc:
        raise CommandError("COMMAND_INVALID_PAYLOAD", str(exc)) from exc
    return _mutation(project, model, "program.configured")


def _put_module(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    try:
        module = program_module_from_data(payload.get("module"), "$.payload.module")
        module = replace(module, path=canonical_module_path(module.path, kind=module.kind))
    except ValueError as exc:
        raise CommandError("COMMAND_INVALID_PAYLOAD", str(exc)) from exc
    model = project.program_model
    known = any(item.id == module.id for item in model.modules)
    modules = tuple(module if item.id == module.id else item for item in model.modules)
    if not known:
        modules = (*modules, module)
    return _mutation(project, replace(model, modules=modules), "program.module_changed")


def _delete_module(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    module_id = _text(payload, "module_id")
    model = project.program_model
    if not any(item.id == module_id for item in model.modules):
        raise CommandError("PROGRAM_MODULE_NOT_FOUND", f"Module {module_id!r} does not exist")
    modules = tuple(item for item in model.modules if item.id != module_id)
    return _mutation(project, replace(model, modules=modules), "program.module_deleted")


def _put_class(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    owner_id = _text(payload, "owner_id")
    try:
        declaration = program_class_from_data(payload.get("class"), "$.payload.class")
    except ValueError as exc:
        raise CommandError("COMMAND_INVALID_PAYLOAD", str(exc)) from exc

    def put(body: tuple[ProgramDeclaration, ...]) -> tuple[ProgramDeclaration, ...]:
        known = any(isinstance(item, ProgramClass) and item.id == declaration.id for item in body)
        updated = tuple(
            declaration if isinstance(item, ProgramClass) and item.id == declaration.id else item
            for item in body
        )
        return updated if known else (*updated, declaration)

    return _mutation(
        project, update_owner(project.program_model, owner_id, put), "program.class_changed"
    )


def _delete_class(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    class_id = _text(payload, "class_id")
    model = project.program_model
    owner = model.owner_of(class_id)
    if model.class_(class_id) is None or owner is None:
        raise CommandError("PROGRAM_CLASS_NOT_FOUND", f"Class {class_id!r} does not exist")
    updated = update_owner(
        model,
        owner.id,
        lambda body: tuple(
            item for item in body if not (isinstance(item, ProgramClass) and item.id == class_id)
        ),
    )
    return _mutation(project, updated, "program.class_deleted")


def _set_owner(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    function_id = _text(payload, "function_id")
    owner_id = _text(payload, "owner_id")
    index = payload.get("index")
    if index is not None and (isinstance(index, bool) or not isinstance(index, int)):
        raise CommandError("COMMAND_INVALID_PAYLOAD", "index must be an integer or null")
    model = project.program_model
    if model.function(function_id) is None:
        raise CommandError("PROGRAM_FUNCTION_NOT_FOUND", f"Function {function_id!r} does not exist")
    owner = model.owner_of(function_id)
    if owner is not None and owner.id == owner_id and index is None:
        return _mutation(project, model, "program.function_owner_changed")
    model = attach_function(
        remove_function_reference(model, function_id), function_id, owner_id, index
    )
    return _mutation(project, model, "program.function_owner_changed")


def _configure_entrypoint(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    try:
        value = (
            program_entrypoint_from_data(payload.get("entrypoint"), "$.payload.entrypoint")
            if payload.get("entrypoint") is not None
            else None
        )
    except ValueError as exc:
        raise CommandError("COMMAND_INVALID_PAYLOAD", str(exc)) from exc
    return _mutation(
        project, replace(project.program_model, entrypoint=value), "program.entrypoint_changed"
    )


def ownership_handlers() -> tuple[tuple[str, Handler], ...]:
    return (
        ("program.configure", _configure),
        ("program.module.put", _put_module),
        ("program.module.delete", _delete_module),
        ("program.class.put", _put_class),
        ("program.class.delete", _delete_class),
        ("program.function.set_owner", _set_owner),
        ("program.entrypoint.configure", _configure_entrypoint),
        ("program.declaration.set_text", _set_text),
    )


def _set_text(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    from code_visualizer.application.python_authoring import edit_declaration_text

    identity = _text(payload, "declaration_id")
    field = _text(payload, "field")
    value = payload.get("value")
    if not isinstance(value, str):
        raise CommandError("COMMAND_INVALID_PAYLOAD", "value must be text")
    try:
        model = edit_declaration_text(project.program_model, identity, field, value)
    except ValueError as exc:
        raise CommandError("PROGRAM_EDIT_INVALID", str(exc)) from exc
    return _mutation(project, model, "program.declaration_text_changed")
