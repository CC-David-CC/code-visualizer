"""Application boundary between canonical program truth and DRAKON editor views."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from code_visualizer.application.drakon_program_adapter import (
    drakon_from_program,
    promote_program_from_drakon,
)
from code_visualizer.domain.drakon import DrakonDiagram
from code_visualizer.domain.program import ProgramFunction, ProgramModel
from code_visualizer.domain.program_index import program_function_locations
from code_visualizer.domain.project import Project, ProjectDocument
from code_visualizer.domain.projection import DrakonViewDefinition


def _replace_by_identity[T](
    existing: tuple[T, ...],
    replacements: tuple[T, ...],
    identity: Callable[[T], str],
) -> tuple[T, ...]:
    """Replace known identities in place and append genuinely new identities."""

    replacement_by_id = {identity(item): item for item in replacements}
    existing_ids = {identity(item) for item in existing}
    return (
        *(replacement_by_id.get(identity(item), item) for item in existing),
        *(item for item in replacements if identity(item) not in existing_ids),
    )


def _replace_function_segments(
    model: ProgramModel,
    replacements: ProgramModel,
) -> ProgramModel:
    """Merge promoted function segments without turning replacement into a move."""

    replaced_owner_ids = {item.id for item in replacements.functions}
    replacement_symbol_ids = {item.id for item in replacements.symbols}
    retained_symbols = tuple(
        item
        for item in model.symbols
        if item.owner_id not in replaced_owner_ids or item.id in replacement_symbol_ids
    )
    return replace(
        model,
        functions=_replace_by_identity(
            model.functions, replacements.functions, lambda item: item.id
        ),
        symbols=_replace_by_identity(retained_symbols, replacements.symbols, lambda item: item.id),
        modules=replacements.modules,
    )


def effective_program_model(project: Project) -> ProgramModel:
    """Return canonical truth, bootstrapping an uninitialized in-memory project."""

    if (
        project.program_model.functions
        or project.program_model.modules
        or project.program_model.entrypoint is not None
    ) or not any(isinstance(item, DrakonDiagram) for item in project.documents):
        return project.program_model
    diagrams = tuple(item for item in project.documents if isinstance(item, DrakonDiagram))
    return promote_program_from_drakon(diagrams).model


def effective_drakon_views(project: Project) -> tuple[DrakonViewDefinition, ...]:
    """Return project-owned presentation bindings, bootstrapping them when absent."""

    if project.drakon_views:
        return project.drakon_views
    diagrams = tuple(item for item in project.documents if isinstance(item, DrakonDiagram))
    if not diagrams:
        return ()
    model = effective_program_model(project)
    return promote_program_from_drakon(diagrams, model).drakon_views


def function_for_document(project: Project, document_id: str) -> ProgramFunction | None:
    view = next(
        (item for item in effective_drakon_views(project) if item.document_id == document_id),
        None,
    )
    return None if view is None else effective_program_model(project).function(view.function_id)


def _project_documents(
    project: Project,
    model: ProgramModel,
    views: tuple[DrakonViewDefinition, ...],
    *,
    only_document_ids: frozenset[str] | None = None,
) -> tuple[ProjectDocument, ...]:
    functions = {item.id: item for item in model.functions}
    locations = program_function_locations(model)
    views_by_document = {item.document_id: item for item in views}
    result: list[ProjectDocument] = []
    for document in project.documents:
        if not isinstance(document, DrakonDiagram):
            result.append(document)
            continue
        if only_document_ids is not None and document.id not in only_document_ids:
            result.append(document)
            continue
        view = views_by_document.get(document.id)
        function = functions.get(view.function_id) if view is not None else None
        if view is None or function is None:
            result.append(document)
            continue
        result.append(
            drakon_from_program(function, view, document, model=model, locations=locations)
        )
    return tuple(result)


def canonicalize_project(project: Project) -> Project:
    """Make ProgramModel authoritative and refresh every mapped DRAKON projection.

    An uninitialized in-memory project gains a model once. If a project already has
    canonical functions, its DRAKON documents are projections and are refreshed.
    Previously unseen DRAKON documents are promoted additively.
    """

    diagrams = tuple(item for item in project.documents if isinstance(item, DrakonDiagram))
    model = effective_program_model(project)
    views = effective_drakon_views(project)
    mapped = {item.document_id for item in views}
    missing = tuple(item for item in diagrams if item.id not in mapped)
    if missing:
        promoted = promote_program_from_drakon(missing, model, views)
        model = _replace_function_segments(model, promoted.model)
        views = _replace_by_identity(
            views,
            promoted.drakon_views,
            lambda item: item.document_id,
        )
    document_ids = {item.id for item in diagrams}
    retained_views = tuple(item for item in views if item.document_id in document_ids)
    candidate = replace(project, program_model=model, drakon_views=retained_views)
    return replace(
        candidate,
        documents=_project_documents(candidate, model, retained_views),
    )


def project_program_changes(
    project: Project,
    model: ProgramModel,
    *,
    function_ids: frozenset[str],
) -> Project:
    """Commit canonical program changes and refresh only affected DRAKON views."""

    candidate = replace(project, program_model=model)
    document_ids = frozenset(
        item.document_id for item in project.drakon_views if item.function_id in function_ids
    )
    return replace(
        candidate,
        documents=_project_documents(
            candidate,
            model,
            project.drakon_views,
            only_document_ids=document_ids,
        ),
    )


def resolved_drakon_document(project: Project, document_id: str) -> DrakonDiagram | None:
    canonical = canonicalize_project(project)
    return next(
        (
            item
            for item in canonical.documents
            if isinstance(item, DrakonDiagram) and item.id == document_id
        ),
        None,
    )
