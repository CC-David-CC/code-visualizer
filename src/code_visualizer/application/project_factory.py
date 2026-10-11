"""Initial project construction and explicit diagram import boundary."""

from __future__ import annotations

from dataclasses import replace

from code_visualizer.application.drakon_program_adapter import promote_program_from_drakon
from code_visualizer.domain.common import new_id
from code_visualizer.domain.drakon import DrakonDiagram, create_empty_drakon
from code_visualizer.domain.program import ProgramEntryPoint, ProgramModel
from code_visualizer.domain.program_ownership import remove_function_ownership
from code_visualizer.domain.project import Project, ProjectDocument


def initialize_project_documents(
    project: Project,
    documents: tuple[ProjectDocument, ...],
) -> Project:
    """Install an initial document set and derive its canonical executable plane.

    This constructor helper is for fixtures/import-free project creation, not ordinary
    editing. Once initialized, document replacement cannot overwrite ProgramModel.
    """

    diagrams = tuple(item for item in documents if isinstance(item, DrakonDiagram))
    views = {view.document_id: view for view in project.drakon_views}
    retained = {
        views[diagram.id].function_id if diagram.id in views else diagram.id for diagram in diagrams
    }
    previous = project.program_model
    for function in previous.functions:
        if function.id not in retained:
            previous = remove_function_ownership(previous, function.id)
    promoted = promote_program_from_drakon(diagrams, previous, project.drakon_views)
    return replace(
        project,
        documents=documents,
        program_model=promoted.model,
        drakon_views=promoted.drakon_views,
    )


def create_default_project(*, title: str = "Untitled Project") -> Project:
    main = create_empty_drakon()
    return initialize_project_documents(
        Project(
            id=new_id("project"),
            title=title,
            documents=(),
            program_model=ProgramModel(entrypoint=ProgramEntryPoint(new_id("entrypoint"), main.id)),
        ),
        (main,),
    )
