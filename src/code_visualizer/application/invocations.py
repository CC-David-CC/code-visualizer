"""Resolve a visual selection to its canonical callable's execution description."""

from code_visualizer.application.program_model import function_for_document
from code_visualizer.domain.invocation import (
    InvocationBindingError,
    InvocationSpec,
    bind_invocation,
)
from code_visualizer.domain.invocation_arguments import parse_invocation_arguments
from code_visualizer.domain.project import Project
from code_visualizer.generation import GenerationError


def invocation_for_document(
    project: Project, document_id: str, arguments: str = ""
) -> InvocationSpec:
    function = function_for_document(project, document_id)
    if function is None:
        raise GenerationError(f"Diagram {document_id!r} has no canonical callable")
    try:
        values = parse_invocation_arguments(arguments)
    except ValueError as exc:
        raise GenerationError(f"INVOCATION_LITERAL_ARGUMENTS: {exc}") from exc
    try:
        return bind_invocation(project.program_model, function, values)
    except InvocationBindingError as exc:
        raise GenerationError(f"{exc.code}: {exc}") from exc
