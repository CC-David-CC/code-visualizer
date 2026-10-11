"""Compose authored and transformed domains at a disposable build boundary."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from code_visualizer.domain.program import ProgramModel
from code_visualizer.domain.project import Project
from code_visualizer.domain.transformation import (
    PROGRAM_REPRESENTATION,
    OriginLink,
    OriginMap,
    Representation,
)
from code_visualizer.generation.program_composition import (
    compose_programs,
    composed_origins,
    select_entrypoint,
)
from code_visualizer.generation.transformation import (
    TransformationError,
    TransformationInput,
    canonical_project_identities,
    declared_transformation_sources,
    execute_transformations,
    plan_transformations,
    value_identities,
)

if TYPE_CHECKING:
    from code_visualizer.extensions.registry import DomainExtensionRegistry


@dataclass(frozen=True, slots=True)
class BuildSnapshot:
    project: Project
    origins: OriginMap
    transformations: tuple[str, ...] = ()


def program_identities(model: ProgramModel) -> frozenset[str]:
    return value_identities(model)


def prepare_build(
    project: Project,
    registry: DomainExtensionRegistry | None = None,
    *,
    entrypoint_model_id: str | None = None,
    model_ids: tuple[str, ...] | None = None,
) -> BuildSnapshot:
    """Build from an immutable revision; transformed output never becomes canonical."""

    workspace = project.domain_workspace
    if model_ids is not None and (
        type(model_ids) is not tuple
        or len(set(model_ids)) != len(model_ids)
        or any(workspace.model(identity) is None for identity in model_ids)
    ):
        raise TransformationError(
            "TRANSFORM_ROOT_SELECTION",
            "Python roots must identify distinct canonical domain models",
        )
    if (
        entrypoint_model_id is not None
        and model_ids is not None
        and entrypoint_model_id not in model_ids
    ):
        raise TransformationError(
            "TRANSFORM_ROOT_SELECTION",
            "The selected entrypoint model must be a Python contribution root",
        )
    empty_origins = OriginMap(project.id, project.revision)
    if not (
        workspace.models
        or workspace.schemas
        or workspace.bundle_references
        or workspace.language_definitions
    ):
        return BuildSnapshot(project, empty_origins)
    from code_visualizer.extensions.languages import resolve_domain_languages
    from code_visualizer.extensions.registry import validate_extension_requirements

    installed = resolve_domain_languages(project, registry)
    issues = validate_extension_requirements(project, installed)
    if issues:
        raise TransformationError(issues[0].code, issues[0].message)
    from code_visualizer.validation import assess_project

    assessment_project = (
        replace(project, program_model=select_entrypoint(project.program_model, None))
        if entrypoint_model_id is not None
        else project
    )
    assessment = assess_project(assessment_project, extensions=installed)
    if not assessment.buildable:
        first = assessment.blocking_diagnostics[0]
        raise TransformationError(first.code, first.message)

    program = project.program_model
    replacements: list[tuple[str, str]] = []
    owned = set(canonical_project_identities(project))
    node_ids = {node.id for model in workspace.models for node in model.nodes}
    origin_links: list[OriginLink] = []
    transformations: list[str] = []
    entrypoints: list[str] = []
    entrypoints_by_model: dict[str, tuple[str, ...]] = {}
    for model in sorted(workspace.models, key=lambda item: item.id):
        if model_ids is not None and model.id not in model_ids:
            continue
        if not model.nodes:
            continue
        schema = workspace.schema(model.schema_id)
        if schema is None:
            raise TransformationError("TRANSFORM_SCHEMA", f"Missing schema {model.schema_id!r}")
        source = Representation(schema.namespace, schema.version)
        try:
            plan = plan_transformations(
                installed.transformations(),
                source,
                PROGRAM_REPRESENTATION,
                source_schema=(schema.id, schema.version),
            )
        except TransformationError as exc:
            if (
                exc.code == "TRANSFORM_NO_PATH"
                and model_ids is None
                and model.id != entrypoint_model_id
                and source
                not in declared_transformation_sources(
                    installed.transformations(), PROGRAM_REPRESENTATION
                )
            ):
                # A representation with no declared Python route is reference-only.
                # Declared routes with unsupported scopes or prerequisites still fail.
                continue
            raise
        result = execute_transformations(
            TransformationInput(
                project,
                model,
                source,
                model,
                OriginMap(
                    project.id,
                    project.revision,
                    (
                        OriginLink(model.id, model.roots),
                        *(OriginLink(node.id, (node.id,)) for node in model.nodes),
                    ),
                ),
            ),
            plan,
            validate_domain=lambda value: installed.validate_model(project, value),
        )
        if not isinstance(result.value, ProgramModel):
            raise TransformationError("TRANSFORM_PROGRAM", "Python builds require ProgramModel")
        identities = program_identities(result.value)
        collisions = owned & identities
        if collisions:
            raise TransformationError(
                "TRANSFORM_ID_COLLISION", f"Domain contributions share IDs: {sorted(collisions)!r}"
            )
        mapped = {link.generated_id for link in result.origins.links}
        if mapped - identities:
            raise TransformationError(
                "TRANSFORM_ORIGIN_STALE", "Origins name objects absent from the generated model"
            )
        if identities - mapped:
            raise TransformationError(
                "TRANSFORM_ORIGIN_MISSING",
                f"Generated objects have no origins: {sorted(identities - mapped)!r}",
            )
        if any(set(link.source_ids) - node_ids for link in result.origins.links):
            raise TransformationError(
                "TRANSFORM_ORIGIN_UNKNOWN", "Generated origins must resolve to canonical intentions"
            )
        if any(result.value.function(identity) is None for identity in result.entrypoint_ids):
            raise TransformationError("TRANSFORM_ENTRYPOINT", "Unknown derived entrypoint")
        owned.update(identities)
        composition = compose_programs(program, result.value)
        program = composition.program
        replacements.extend(composition.replacements)
        origin_links.extend(result.origins.links)
        transformations.extend(item.definition.key for item in plan)
        entrypoints.extend(result.entrypoint_ids)
        entrypoints_by_model[model.id] = result.entrypoint_ids

    if (
        not program.functions
        and not any(module.body for module in program.modules)
        and not (program.entrypoint is not None and program.entrypoint.startup)
        and any(model.nodes for model in workspace.models)
    ):
        raise TransformationError(
            "TRANSFORM_NO_PATH",
            "The selected roots contribute no executable ProgramModel; "
            "select an applicable computation backend",
        )

    selected_id = project.program_model.entrypoint_callable_id
    if entrypoint_model_id is not None:
        selected = entrypoints_by_model.get(entrypoint_model_id, ())
        if len(selected) != 1:
            raise TransformationError(
                "TRANSFORM_ENTRYPOINT_SELECTION",
                "The selected domain model must contribute exactly one entrypoint",
            )
        selected_id = selected[0]
    elif selected_id is None and entrypoints:
        if len(entrypoints) != 1:
            raise TransformationError(
                "TRANSFORM_ENTRYPOINT_AMBIGUOUS",
                "Choose a domain entrypoint explicitly or author a programming entrypoint",
            )
        selected_id = entrypoints[0]
    program = select_entrypoint(program, selected_id)
    built = replace(project, program_model=program)
    built_assessment = assess_project(built, extensions=installed)
    if not built_assessment.buildable:
        first = built_assessment.blocking_diagnostics[0]
        raise TransformationError(first.code, first.message)
    return BuildSnapshot(
        built,
        composed_origins(
            OriginMap(project.id, project.revision, tuple(origin_links)),
            program,
            tuple(replacements),
        ),
        tuple(dict.fromkeys(transformations)),
    )
