"""Explicit edits of canonical Python declaration ownership.

Paths and spellings are authoring input only. Once allocated, scope identities are
stored and are never recomputed when a module or class is renamed.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from uuid import uuid4

from code_visualizer.domain.program import (
    ProgramClass,
    ProgramDeclaration,
    ProgramFunctionReference,
    ProgramModel,
    ProgramModule,
)


def remove_function_ownership(model: ProgramModel, function_id: str) -> ProgramModel:
    def visit(body: tuple[ProgramDeclaration, ...]) -> tuple[ProgramDeclaration, ...]:
        return tuple(
            replace(item, body=visit(item.body)) if isinstance(item, ProgramClass) else item
            for item in body
            if not (isinstance(item, ProgramFunctionReference) and item.function_id == function_id)
        )

    return replace(
        model, modules=tuple(replace(module, body=visit(module.body)) for module in model.modules)
    )


def place_program_function(
    model: ProgramModel,
    function_id: str,
    module_path: str,
    owning_class: str | None,
    *,
    identity_namespace: str | None = None,
) -> ProgramModel:
    """Place an explicitly authored function in one module or class body.

    Existing ownership is left in position when unchanged. New scopes are created
    only for this explicit authoring/import operation, never during generation.
    """
    old_owner = model.owner_of(function_id)
    if (
        old_owner is not None
        and model.module_path_for(function_id) == module_path
        and model.class_name_for(function_id) == owning_class
    ):
        return model
    updated = remove_function_ownership(model, function_id)
    namespace = identity_namespace or uuid4().hex

    def identity(kind: str, owner: str, name: str) -> str:
        digest = hashlib.sha256(f"{namespace}\0{kind}\0{owner}\0{name}".encode()).hexdigest()[:24]
        return f"{kind}_{digest}"

    module = next((item for item in updated.modules if item.path == module_path), None)
    if module is None:
        module = ProgramModule(identity("module", "", module_path), module_path)
        updated = replace(updated, modules=(*updated.modules, module))

    def insert(
        owner_id: str, body: tuple[ProgramDeclaration, ...], names: tuple[str, ...]
    ) -> tuple[ProgramDeclaration, ...]:
        if not names:
            return (*body, ProgramFunctionReference(function_id))
        cls = next(
            (
                item
                for item in body
                if isinstance(item, ProgramClass) and item.identifier == names[0]
            ),
            None,
        )
        if cls is None:
            cls = ProgramClass(identity("class", owner_id, names[0]), names[0])
            body = (*body, cls)
        replacement = replace(cls, body=insert(cls.id, cls.body, names[1:]))
        return tuple(replacement if item is cls else item for item in body)

    placed = replace(
        module,
        body=insert(
            module.id,
            module.body,
            tuple(owning_class.split(".")) if owning_class is not None else (),
        ),
    )
    return replace(
        updated, modules=tuple(placed if item.id == module.id else item for item in updated.modules)
    )
