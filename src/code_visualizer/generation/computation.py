"""Prepare a declared terminal representation without assuming a Python destination."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from typing import TYPE_CHECKING

from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.intentional import DomainModel
from code_visualizer.domain.intentional_validation import validate_domain_workspace
from code_visualizer.domain.program import ProgramModel
from code_visualizer.domain.project import Project
from code_visualizer.domain.transformation import (
    PROGRAM_REPRESENTATION,
    OriginLink,
    OriginMap,
    Representation,
)
from code_visualizer.execution.backends import PreparedComputation, resource_references
from code_visualizer.extensions.languages import resolve_domain_languages
from code_visualizer.extensions.registry import validate_extension_requirements
from code_visualizer.generation.computation_scope import computation_scope
from code_visualizer.generation.program_composition import (
    compose_programs,
    composed_origins,
    select_entrypoint,
)
from code_visualizer.generation.transformation import (
    TransformationError,
    TransformationInput,
    execute_transformations,
    plan_transformations,
    value_identities,
)
from code_visualizer.persistence.canonical import JsonObject, json_stream_chunks
from code_visualizer.persistence.computation import computation_request_to_data
from code_visualizer.persistence.serialization import project_stream
from code_visualizer.validation import assess_project, validate_integrity

if TYPE_CHECKING:
    from code_visualizer.extensions.registry import DomainExtensionRegistry


def computation_input_digest(project: Project, request: ComputationRequest) -> str:
    """Conservative consumed-input identity; never substitute a movable branch label."""
    digest = sha256()
    for chunk in json_stream_chunks(
        JsonObject(
            {"project": project_stream(project), "request": computation_request_to_data(request)}
        )
    ):
        digest.update(chunk)
    return digest.hexdigest()


def prepare_computation(
    project: Project,
    request: ComputationRequest,
    registry: DomainExtensionRegistry | None = None,
) -> PreparedComputation:
    """Select one explicit computation root; other models remain immutable inputs."""
    if (request.project_id, request.revision) != (project.id, project.revision):
        raise TransformationError(
            "COMPUTATION_REVISION", "Request does not match the project snapshot"
        )
    request = replace(
        request,
        configuration=tuple(sorted(request.configuration, key=lambda item: item.name)),
        resources=resource_references((request.resources, request.inputs)),
        inputs=tuple(sorted(request.inputs, key=lambda item: item.name)),
        outputs=tuple(sorted(request.outputs, key=lambda item: item.name)),
    )
    installed = resolve_domain_languages(project, registry)
    backend = installed.backend(request.backend_id, request.backend_version)
    if backend is None:
        raise TransformationError(
            "COMPUTATION_BACKEND_MISSING", "Requested backend implementation is unavailable"
        )
    integrity = validate_integrity(project)
    if integrity:
        first = integrity[0]
        raise TransformationError(first.code, first.message)
    target = backend.definition
    input_digest = computation_input_digest(project, request)
    if request.model_id is None:
        if target.input_representation != PROGRAM_REPRESENTATION or target.schema is not None:
            raise TransformationError(
                "COMPUTATION_ROOT", "This backend requires an explicit domain model"
            )
        scope = computation_scope(project, None)
        program = project.program_model
        return _validate_terminal(
            PreparedComputation(
                project,
                request,
                PROGRAM_REPRESENTATION,
                program,
                OriginMap(
                    project.id,
                    project.revision,
                    tuple(
                        OriginLink(identity, (identity,))
                        for identity in sorted(value_identities(program))
                    ),
                ),
                (),
                input_digest,
                (project.program_model.entrypoint_callable_id,)
                if project.program_model.entrypoint_callable_id is not None
                else (),
            ),
            resolve_domain_languages(scope, registry),
        )
    model = project.domain_workspace.model(request.model_id)
    if model is None:
        raise TransformationError("COMPUTATION_ROOT", "Requested canonical domain model is absent")
    schema = project.domain_workspace.schema(model.schema_id)
    if schema is None:
        raise TransformationError("TRANSFORM_SCHEMA", "Computation source schema is absent")
    source = Representation(schema.namespace, schema.version)
    plan = plan_transformations(
        installed.transformations(),
        source,
        target.input_representation,
        source_schema=(schema.id, schema.version),
        target_schema=target.schema,
    )
    scope = computation_scope(
        project,
        model.id,
        schema_ids=tuple(
            identity
            for item in plan
            for identity in (item.schema_id, item.target_schema_id)
            if identity is not None
        ),
    )
    installed = resolve_domain_languages(scope, registry)
    issues = (
        *validate_domain_workspace(scope.domain_workspace),
        *validate_extension_requirements(scope, installed),
    )
    if issues:
        raise TransformationError(issues[0].code, issues[0].message)
    origins = OriginMap(
        project.id,
        project.revision,
        tuple(OriginLink(identity, (identity,)) for identity in sorted(value_identities(model))),
    )
    result = execute_transformations(
        TransformationInput(scope, model, source, model, origins),
        plan,
        validate_domain=lambda value: installed.validate_model(scope, value),
    )
    if (
        isinstance(result.value, DomainModel)
        and target.schema != (result.value.schema_id, result.value.schema_version)
        and target.schema is not None
    ):
        raise TransformationError(
            "COMPUTATION_SCHEMA", "Terminal model does not match backend schema"
        )
    value = result.value
    origins = result.origins
    if isinstance(value, ProgramModel):
        authored = project.program_model
        composition = compose_programs(authored, value)
        value = composition.program
        origins = OriginMap(
            project.id,
            project.revision,
            tuple(
                sorted(
                    (
                        *origins.links,
                        *(
                            OriginLink(identity, (identity,))
                            for identity in value_identities(authored)
                        ),
                    ),
                    key=lambda item: item.generated_id,
                )
            ),
        )
        origins = composed_origins(origins, value, composition.replacements)
    # Composition exists only in this disposable terminal snapshot.
    return _validate_terminal(
        PreparedComputation(
            project,
            replace(
                request,
                configuration=tuple(sorted(request.configuration, key=lambda item: item.name)),
            ),
            result.representation,
            value,
            origins,
            tuple(item.definition.key for item in plan),
            input_digest,
            result.entrypoint_ids,
        ),
        installed,
    )


def _validate_terminal(
    snapshot: PreparedComputation, installed: DomainExtensionRegistry
) -> PreparedComputation:
    if isinstance(snapshot.value, ProgramModel):
        if len(snapshot.entrypoint_ids) > 1:
            raise TransformationError(
                "EXECUTION_ENTRYPOINT", "A program computation can select at most one callable"
            )
        value = select_entrypoint(
            snapshot.value, snapshot.entrypoint_ids[0] if snapshot.entrypoint_ids else None
        )
        snapshot = replace(snapshot, value=value, origins=composed_origins(snapshot.origins, value))
        effective = replace(computation_scope(snapshot.project, None), program_model=value)
        assessment = assess_project(effective, extensions=installed)
        if not assessment.buildable:
            first = assessment.blocking_diagnostics[0]
            raise TransformationError(first.code, first.message)
    return snapshot
