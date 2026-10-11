"""Transient Python form values bound to canonical declaration identities.

These values are editor drafts. Only ProgramModule and its typed declarations are
submitted to the authority or persisted.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, fields, is_dataclass, replace
from typing import cast

from code_visualizer.domain.common import new_id
from code_visualizer.domain.expression import parse_expression_tree, reconcile_expression_trees
from code_visualizer.domain.program import (
    ExpressionRole,
    ProgramAssignment,
    ProgramClass,
    ProgramDeclaration,
    ProgramEntryPoint,
    ProgramExpression,
    ProgramImport,
    ProgramModel,
    ProgramModule,
    ProgramNote,
    ProgramTypeAlias,
    expression_parse_mode,
    make_program_expression,
)


@dataclass(frozen=True, slots=True)
class ImportSpec:
    module: str
    name: str | None = None
    alias: str | None = None
    id: str = ""


@dataclass(frozen=True, slots=True)
class ConstantSpec:
    name: str
    expression: str
    annotation: str | None = None
    id: str = ""


@dataclass(frozen=True, slots=True)
class TypeAliasSpec:
    name: str
    expression: str
    id: str = ""


@dataclass(frozen=True, slots=True)
class PythonModuleDraft:
    module: ProgramModule
    imports: tuple[ImportSpec, ...] = ()
    constants: tuple[ConstantSpec, ...] = ()
    type_aliases: tuple[TypeAliasSpec, ...] = ()

    @property
    def path(self) -> str:
        return self.module.path

    @property
    def docstring(self) -> str:
        return self.module.docstring


def module_draft(module: ProgramModule) -> PythonModuleDraft:
    imports: list[ImportSpec] = []
    constants: list[ConstantSpec] = []
    aliases: list[TypeAliasSpec] = []
    for item in module.body:
        if isinstance(item, ProgramImport):
            try:
                statement = ast.parse(item.source.source).body[0]
            except (SyntaxError, IndexError):
                continue
            if isinstance(statement, (ast.Import, ast.ImportFrom)) and len(statement.names) == 1:
                imported = statement.names[0]
                if isinstance(statement, ast.Import):
                    imports.append(ImportSpec(imported.name, alias=imported.asname, id=item.id))
                else:
                    imports.append(
                        ImportSpec(
                            "." * statement.level + (statement.module or ""),
                            imported.name,
                            imported.asname,
                            item.id,
                        )
                    )
        elif (
            isinstance(item, ProgramAssignment)
            and item.operator == "="
            and item.target.source.isidentifier()
        ):
            constants.append(
                ConstantSpec(
                    item.target.source,
                    item.value.source,
                    item.annotation.source if item.annotation is not None else None,
                    item.id,
                )
            )
        elif isinstance(item, ProgramTypeAlias):
            try:
                statement = ast.parse(item.source.source).body[0]
            except (SyntaxError, IndexError):
                continue
            if isinstance(statement, ast.TypeAlias) and not statement.type_params:
                aliases.append(
                    TypeAliasSpec(
                        ast.unparse(statement.name), ast.unparse(statement.value), item.id
                    )
                )
    return PythonModuleDraft(module, tuple(imports), tuple(constants), tuple(aliases))


def apply_module_draft(draft: PythonModuleDraft) -> ProgramModule:
    original = module_draft(draft.module)
    edited_ids = (
        {item.id for item in original.imports}
        | {item.id for item in original.constants}
        | {item.id for item in original.type_aliases}
    )
    replacements: dict[str, ProgramDeclaration] = {}
    additions: list[ProgramDeclaration] = []

    def store(identity: str, value: ProgramDeclaration) -> None:
        if identity:
            replacements[identity] = value
        else:
            additions.append(value)

    for item in draft.imports:
        identity = item.id or new_id("import")
        source = f"from {item.module} import {item.name}" if item.name else f"import {item.module}"
        if item.alias:
            source += f" as {item.alias}"
        old = next(
            (
                node
                for node in draft.module.body
                if isinstance(node, ProgramImport) and node.id == identity
            ),
            None,
        )
        if old is not None and old.source.source.strip() == source:
            value = old
        else:
            value = ProgramImport(
                identity,
                make_program_expression(identity, "source", source, ExpressionRole.STATEMENTS),
            )
        store(item.id, value)
    for constant in draft.constants:
        identity = constant.id or new_id("constant")
        old_constant = next(
            (
                node
                for node in draft.module.body
                if isinstance(node, ProgramAssignment) and node.id == identity
            ),
            None,
        )

        def expression(
            field: str,
            source: str,
            role: ExpressionRole,
            *,
            previous_assignment: ProgramAssignment | None = old_constant,
            owner_id: str = identity,
        ) -> ProgramExpression:
            previous = getattr(previous_assignment, field, None)
            return (
                previous
                if isinstance(previous, ProgramExpression) and previous.source == source
                else make_program_expression(owner_id, field, source, role)
            )

        value_constant = ProgramAssignment(
            identity,
            expression("target", constant.name, ExpressionRole.TARGET),
            expression("value", constant.expression, ExpressionRole.VALUE),
            expression("annotation", constant.annotation, ExpressionRole.ANNOTATION)
            if constant.annotation
            else None,
            written_symbol_ids=old_constant.written_symbol_ids if old_constant is not None else (),
        )
        store(constant.id, value_constant)
    for alias in draft.type_aliases:
        identity = alias.id or new_id("type_alias")
        source = f"type {alias.name} = {alias.expression}"
        old_alias = next(
            (
                node
                for node in draft.module.body
                if isinstance(node, ProgramTypeAlias) and node.id == identity
            ),
            None,
        )
        value_alias = (
            old_alias
            if old_alias is not None and old_alias.source.source.strip() == source
            else ProgramTypeAlias(
                identity,
                make_program_expression(identity, "source", source, ExpressionRole.STATEMENTS),
            )
        )
        store(alias.id, value_alias)
    body = tuple(
        replacements.get(getattr(item, "id", ""), item)
        for item in draft.module.body
        if getattr(item, "id", "") not in edited_ids or getattr(item, "id", "") in replacements
    )
    # New declarations precede existing authored statements and function definitions.
    return replace(draft.module, body=(*additions, *body))


def edit_declaration_text(
    model: ProgramModel, identity: str, field: str, value: str
) -> ProgramModel:
    """Resolve a semantic field directly; rendered views never participate."""
    found = False

    def visit(item: object) -> object:
        nonlocal found
        if isinstance(item, ProgramExpression):
            if item.id != identity:
                return item
            if field != "source":
                raise ValueError("Expressions expose the source editing field")
            found = True
            if value == item.source:
                return item
            tree = parse_expression_tree(item.id, value, mode=expression_parse_mode(item.role))
            return replace(item, tree=reconcile_expression_trees(item.tree, tree))
        if getattr(item, "id", None) == identity:
            permitted = (
                ("path", "docstring")
                if isinstance(item, ProgramModule)
                else ("identifier", "docstring")
                if isinstance(item, ProgramClass)
                else ("text",)
                if isinstance(item, ProgramNote)
                else ()
            )
            if field not in permitted:
                raise ValueError("This declaration does not expose that text field")
            found = True
            assert is_dataclass(item) and not isinstance(item, type)
            return replace(item, **{field: value})
        if isinstance(item, tuple):
            return tuple(visit(child) for child in item)
        if is_dataclass(item) and not isinstance(item, type):
            return replace(
                item,
                **{
                    definition.name: visit(getattr(item, definition.name))
                    for definition in fields(item)
                },
            )
        return item

    modules = cast(tuple[ProgramModule, ...], visit(model.modules))
    entrypoint = cast(ProgramEntryPoint | None, visit(model.entrypoint))
    if not found:
        raise ValueError(f"Canonical declaration {identity!r} does not exist")
    return replace(model, modules=modules, entrypoint=entrypoint)
