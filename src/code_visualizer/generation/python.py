"""Public Python projection adapters backed exclusively by typed IR."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from code_visualizer.domain.invocation import (
    InvocationBindingError,
    InvocationSpec,
    bind_invocation,
)
from code_visualizer.domain.project import Project
from code_visualizer.domain.transformation import OriginMap
from code_visualizer.generation.build import BuildSnapshot, prepare_build
from code_visualizer.generation.emitter import (
    GeneratedFile,
    GeneratedProject,
    GenerationError,
    SourceSpan,
    emit_combined,
    emit_modules,
    emit_project,
    module_file_path,
)
from code_visualizer.generation.lowering import dependency_closure, lower_project
from code_visualizer.generation.program_composition import select_entrypoint
from code_visualizer.generation.transformation import TransformationError
from code_visualizer.validation import ProjectAssessment, assess_project

if TYPE_CHECKING:
    from code_visualizer.extensions.registry import DomainExtensionRegistry


@dataclass(frozen=True, slots=True)
class GeneratedPython:
    """Readable multi-file preview; execute GeneratedProject instead of this text."""

    source: str
    spans: tuple[SourceSpan, ...]
    invocation: InvocationSpec | None
    file_path: str = "<code-visualizer-memory>"
    origins: OriginMap | None = None
    module_sources: tuple[GeneratedFile, ...] = ()

    @property
    def entrypoint(self) -> str | None:
        """Callable display name; execute the complete invocation value instead."""

        return self.invocation.identifier if self.invocation is not None else None


class BuildBlockedError(GenerationError):
    """Python projection was requested for a non-buildable authoring state."""

    def __init__(self, assessment: ProjectAssessment) -> None:
        self.assessment = assessment
        first = assessment.blocking_diagnostics[0]
        super().__init__(f"Build blocked by {first.code}: {first.message}")


def _require_buildable(
    project: Project,
    *,
    function_ids: frozenset[str] | None = None,
    extensions: DomainExtensionRegistry | None = None,
) -> None:
    assessment = assess_project(project, function_ids=function_ids, extensions=extensions)
    if not assessment.buildable:
        raise BuildBlockedError(assessment)


def generate_python(
    project: Project,
    *,
    include_main: bool = True,
    focus_diagram_id: str | None = None,
    extensions: DomainExtensionRegistry | None = None,
    entrypoint_model_id: str | None = None,
    invocation: InvocationSpec | None = None,
    model_ids: tuple[str, ...] | None = None,
) -> GeneratedPython:
    if invocation is not None:
        if entrypoint_model_id is not None:
            raise GenerationError(
                "INVOCATION_SCOPE: Choose a callable invocation or a domain model"
            )
        project = _with_invocation(project, invocation, focus_diagram_id=focus_diagram_id)
    build = _prepare(project, extensions, entrypoint_model_id, model_ids)
    project = build.project
    selected = (
        dependency_closure(project, focus_diagram_id) if focus_diagram_id is not None else None
    )
    _require_buildable(project, function_ids=selected, extensions=extensions)
    ir = lower_project(project, diagram_ids=selected)
    modules = emit_modules(ir)
    generated = emit_combined(ir, include_main=include_main, _rendered_modules=modules)
    return GeneratedPython(
        generated.source,
        generated.spans,
        ir.entrypoint.invocation if ir.entrypoint else None,
        generated.path,
        build.origins if build.origins.links else None,
        modules,
    )


def _with_invocation(
    project: Project, invocation: InvocationSpec, *, focus_diagram_id: str | None
) -> Project:
    """Validate an execution request before selecting its disposable build settings."""
    function = project.program_model.function(invocation.callable_id or "")
    if function is None:
        raise GenerationError("INVOCATION_CALLABLE: Invocation must identify a canonical callable")
    if focus_diagram_id is not None:
        selected_id = next(
            (
                view.function_id
                for view in project.drakon_views
                if view.document_id == focus_diagram_id
            ),
            focus_diagram_id,
        )
        if selected_id != function.id:
            raise GenerationError("INVOCATION_SCOPE: Invocation must target the selected callable")
    try:
        bound = bind_invocation(project.program_model, function, invocation.arguments)
    except InvocationBindingError as exc:
        raise GenerationError(f"{exc.code}: {exc}") from exc
    if bound != invocation:
        raise GenerationError(
            "INVOCATION_METADATA: Invocation metadata differs from the canonical callable"
        )
    return replace(
        project,
        program_model=select_entrypoint(project.program_model, function.id, bound.arguments),
    )


def generate_python_project(
    project: Project,
    *,
    extensions: DomainExtensionRegistry | None = None,
    entrypoint_model_id: str | None = None,
    model_ids: tuple[str, ...] | None = None,
    focus_diagram_id: str | None = None,
    invocation: InvocationSpec | None = None,
) -> GeneratedProject:
    return prepare_python_project(
        project,
        extensions=extensions,
        entrypoint_model_id=entrypoint_model_id,
        model_ids=model_ids,
        focus_diagram_id=focus_diagram_id,
        invocation=invocation,
    )[1]


def prepare_python_project(
    project: Project,
    *,
    extensions: DomainExtensionRegistry | None = None,
    entrypoint_model_id: str | None = None,
    model_ids: tuple[str, ...] | None = None,
    focus_diagram_id: str | None = None,
    invocation: InvocationSpec | None = None,
) -> tuple[BuildSnapshot, GeneratedProject]:
    """Return emitted files and their once-prepared semantic build together."""
    if invocation is not None:
        if entrypoint_model_id is not None:
            raise GenerationError(
                "INVOCATION_SCOPE: Choose a callable invocation or a domain model"
            )
        project = _with_invocation(project, invocation, focus_diagram_id=focus_diagram_id)
    build = _prepare(project, extensions, entrypoint_model_id, model_ids)
    selected = (
        dependency_closure(build.project, focus_diagram_id)
        if focus_diagram_id is not None
        else None
    )
    _require_buildable(build.project, function_ids=selected, extensions=extensions)
    generated = emit_project(lower_project(build.project, diagram_ids=selected))
    return build, replace(generated, origins=build.origins if build.origins.links else None)


def _prepare(
    project: Project,
    extensions: DomainExtensionRegistry | None = None,
    entrypoint_model_id: str | None = None,
    model_ids: tuple[str, ...] | None = None,
) -> BuildSnapshot:
    if entrypoint_model_id is not None:
        project = replace(
            project,
            program_model=select_entrypoint(project.program_model, None),
        )
    if project.domain_workspace.models:
        _require_buildable(project, extensions=extensions)
    try:
        return prepare_build(
            project, extensions, entrypoint_model_id=entrypoint_model_id, model_ids=model_ids
        )
    except TransformationError as exc:
        raise GenerationError(f"{exc.code}: {exc}") from exc


def generated_module_for_diagram(project: Project, diagram_id: str) -> str:
    authored = project
    project = _prepare(project).project
    view = next((item for item in project.drakon_views if item.document_id == diagram_id), None)
    function_id = view.function_id if view is not None else diagram_id
    function = project.program_model.function(function_id)
    if function is None:
        raise GenerationError(f"Program function or DRAKON view {diagram_id!r} does not exist")
    generated = generate_python_project(authored)
    path = module_file_path(
        lower_project(project), project.program_model.module_path_for(function.id)
    )
    return generated.file(path).source


__all__ = [
    "BuildBlockedError",
    "GeneratedProject",
    "GeneratedPython",
    "GenerationError",
    "SourceSpan",
    "generate_python",
    "generate_python_project",
    "generated_module_for_diagram",
]
