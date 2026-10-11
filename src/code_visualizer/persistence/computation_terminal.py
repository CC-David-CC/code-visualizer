"""Portable terminal resources for workers that do not have the editor project."""

from __future__ import annotations

import json
from typing import cast

from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.computation import ComputationPlan
from code_visualizer.domain.identifiers import ContractKind, ContractReference
from code_visualizer.domain.intentional import DomainModel, DomainWorkspace
from code_visualizer.domain.intentional_validation import validate_domain_workspace
from code_visualizer.domain.program import ProgramModel
from code_visualizer.domain.project import Project
from code_visualizer.domain.resources import TERMINAL_LOGICAL_TYPE
from code_visualizer.domain.values import ResourceReference
from code_visualizer.execution.backends import (
    PreparedComputation,
    resource_references,
    terminal_schemas,
)
from code_visualizer.extensions.registry import DomainExtensionRegistry
from code_visualizer.generation.transformation import TransformationError, value_identities
from code_visualizer.persistence.canonical import (
    EncodedJsonValue,
    JsonArray,
    JsonObject,
    json_stream_chunks,
)
from code_visualizer.persistence.computation import (
    computation_plan_to_data,
    computation_request_to_data,
)
from code_visualizer.persistence.computation_resources import resolve_computation_resource
from code_visualizer.persistence.decoding import program_model_from_data
from code_visualizer.persistence.intentional import (
    domain_model_from_data,
    domain_model_stream,
    domain_schema_from_data,
    domain_schema_stream,
)
from code_visualizer.persistence.program_migration import default_program_module_kinds
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.serialization import program_model_stream
from code_visualizer.persistence.values import array_data, integer_data, object_data, text_data

TERMINAL_MEDIA_TYPE = "application/vnd.code-visualizer.computation-terminal+json;version=2"


def _canonical_bytes(value: EncodedJsonValue) -> bytes:
    return b"".join(json_stream_chunks(value))


def publish_terminal(snapshot: PreparedComputation, store: ResourceStore) -> ComputationPlan:
    value = snapshot.value
    payload = JsonObject(
        {
            "version": 2,
            "request": computation_request_to_data(snapshot.request),
            "representation": {
                "id": snapshot.representation.id,
                "version": snapshot.representation.version,
            },
            "kind": "domain" if isinstance(value, DomainModel) else "program",
            "value": domain_model_stream(value)
            if isinstance(value, DomainModel)
            else program_model_stream(value),
            "schemas": JsonArray(
                domain_schema_stream(schema) for schema in terminal_schemas(snapshot)
            ),
            "dependencies": JsonArray(
                domain_model_stream(model) for model in snapshot.dependency_models
            ),
            "entrypoint_ids": list(snapshot.entrypoint_ids),
            "transformations": list(snapshot.transformations),
            "origins": JsonArray(
                {"generated_id": link.generated_id, "source_ids": list(link.source_ids)}
                for link in snapshot.origins.links
            ),
            "input_digest": snapshot.input_digest,
        }
    )
    descriptor = store.put(
        _canonical_bytes(payload), TERMINAL_MEDIA_TYPE, logical_type=TERMINAL_LOGICAL_TYPE
    )
    return ComputationPlan(
        snapshot.request,
        snapshot.representation,
        ResourceReference(descriptor.id, descriptor.content_hash),
        snapshot.transformations,
        snapshot.origins,
        snapshot.input_digest,
    )


def decode_terminal(
    plan: ComputationPlan, store: ResourceStore, registry: DomainExtensionRegistry
) -> PreparedComputation:
    """Verify inert structure/contracts without invoking registered implementation code."""
    descriptor = store.describe(plan.model)
    if (
        descriptor.media_type != TERMINAL_MEDIA_TYPE
        or descriptor.logical_type != TERMINAL_LOGICAL_TYPE
    ):
        raise TransformationError(
            "COMPUTATION_TERMINAL_FORMAT", "Plan resource is not a supported terminal contract"
        )
    try:
        registry.resolve_registered_contract_references(
            (
                ContractReference(
                    ContractKind.RESOURCE_LOGICAL_TYPE,
                    descriptor.logical_type.id,
                    descriptor.logical_type.version,
                ),
            )
        )
    except ValueError as exc:
        raise TransformationError("RESOURCE_LOGICAL_TYPE_UNAVAILABLE", str(exc)) from exc
    raw_payload = store.read(plan.model)
    decoded_payload = json.loads(raw_payload)
    if _canonical_bytes(decoded_payload) != raw_payload:
        raise TransformationError(
            "COMPUTATION_TERMINAL_FORMAT", "Terminal resource must use canonical JSON encoding"
        )
    data = object_data(
        decoded_payload,
        {
            "version",
            "request",
            "representation",
            "kind",
            "value",
            "schemas",
            "dependencies",
            "entrypoint_ids",
            "transformations",
            "origins",
            "input_digest",
        },
    )
    if integer_data(data.get("version")) != 2:
        raise TransformationError(
            "COMPUTATION_TERMINAL_FORMAT", "Unsupported terminal resource version"
        )
    expected = computation_plan_to_data(plan)
    for field in ("request", "representation", "transformations", "origins", "input_digest"):
        if _canonical_bytes(cast(JsonValue, data.get(field))) != _canonical_bytes(expected[field]):
            raise TransformationError(
                "COMPUTATION_PLAN_MISMATCH", f"Terminal resource differs from plan {field}"
            )
    backend = registry.backend(plan.request.backend_id, plan.request.backend_version)
    if backend is None:
        raise TransformationError(
            "COMPUTATION_BACKEND_MISSING", "Portable plan requires an unavailable backend"
        )
    if backend.definition.input_representation != plan.representation:
        raise TransformationError(
            "COMPUTATION_REPRESENTATION", "Portable plan representation differs from backend input"
        )
    schemas = tuple(domain_schema_from_data(item) for item in array_data(data.get("schemas")))
    dependencies = tuple(
        domain_model_from_data(item) for item in array_data(data.get("dependencies"))
    )
    if _canonical_bytes(
        JsonArray(domain_schema_stream(item) for item in schemas)
    ) != _canonical_bytes(cast(JsonValue, data.get("schemas"))) or _canonical_bytes(
        JsonArray(domain_model_stream(item) for item in dependencies)
    ) != _canonical_bytes(cast(JsonValue, data.get("dependencies"))):
        raise TransformationError(
            "COMPUTATION_TERMINAL_FORMAT",
            "Portable records contain unknown or omitted typed fields",
        )
    kind = text_data(data.get("kind"))
    value: DomainModel | ProgramModel
    if kind == "domain":
        value = domain_model_from_data(data.get("value"))
        if _canonical_bytes(domain_model_stream(value)) != _canonical_bytes(
            cast(JsonValue, data.get("value"))
        ):
            raise TransformationError(
                "COMPUTATION_TERMINAL_FORMAT", "Domain terminal contains unknown or omitted fields"
            )
        if backend.definition.schema is not None and backend.definition.schema != (
            value.schema_id,
            value.schema_version,
        ):
            raise TransformationError(
                "COMPUTATION_SCHEMA", "Portable terminal schema differs from backend scope"
            )
        workspace = DomainWorkspace(schemas, (value, *dependencies))
    elif kind == "program":
        # Terminal-2 originally had only ordinary modules. Defaulting its missing
        # discriminator is additive; the original immutable bytes/hash above remain
        # the provenance, and strict round-trip comparison still rejects unknown fields.
        program_data = default_program_module_kinds(data.get("value"), "terminal.value")
        value = program_model_from_data(program_data)
        if _canonical_bytes(program_model_stream(value)) != _canonical_bytes(program_data):
            raise TransformationError(
                "COMPUTATION_TERMINAL_FORMAT", "Program terminal contains unknown or omitted fields"
            )
        if backend.definition.schema is not None:
            raise TransformationError(
                "COMPUTATION_SCHEMA", "Schema-specific backend cannot receive a program"
            )
        workspace = DomainWorkspace(schemas, dependencies)
    else:
        raise TransformationError(
            "COMPUTATION_TERMINAL_FORMAT", "Unknown terminal representation kind"
        )
    findings = validate_domain_workspace(workspace)
    if findings:
        raise TransformationError(findings[0].code, findings[0].message)
    project = Project(
        plan.request.project_id,
        "Computation input",
        (),
        revision=plan.request.revision,
        program_model=value if isinstance(value, ProgramModel) else ProgramModel(),
        domain_workspace=workspace,
    )
    from code_visualizer.validation import validate_integrity

    integrity = validate_integrity(project)
    if integrity:
        raise TransformationError(integrity[0].code, integrity[0].message)
    available = value_identities(value) | {
        node.id for model in dependencies for node in model.nodes
    }
    required_resources = resource_references(
        (value, dependencies, plan.request.configuration, plan.request.inputs)
    )
    if any(reference not in plan.request.resources for reference in required_resources):
        raise TransformationError(
            "COMPUTATION_RESOURCE_SCOPE", "Portable plan omits a required input resource"
        )
    if available != {link.generated_id for link in plan.origins.links}:
        raise TransformationError(
            "COMPUTATION_ORIGIN_SCOPE",
            "Portable origins must cover exactly the terminal and declared dependencies",
        )
    for model in workspace.models:
        schema = workspace.schema(model.schema_id)
        if schema is None:
            raise TransformationError("COMPUTATION_SCHEMA", "Portable terminal schema is absent")
        if schema.bundle is not None:
            owner = registry.get(schema.bundle.id, schema.bundle.version)
            if owner is None or schema not in owner.schemas:
                raise TransformationError(
                    "COMPUTATION_SCHEMA",
                    "Portable terminal schema differs from its installed contract",
                )
    entrypoints = tuple(text_data(item) for item in array_data(data.get("entrypoint_ids")))
    if isinstance(value, ProgramModel):
        if len(entrypoints) > 1:
            raise TransformationError(
                "EXECUTION_ENTRYPOINT", "Portable program can select at most one callable"
            )
        if value.entrypoint_callable_id != (entrypoints[0] if entrypoints else None):
            raise TransformationError(
                "EXECUTION_ENTRYPOINT", "Terminal invocation differs from its selected callable"
            )
    closure = registry.resource_closure(plan.request.resources, store)
    if set(closure) != set(plan.request.resources):
        raise TransformationError(
            "COMPUTATION_RESOURCE_SCOPE", "Portable plan omits a transitive input resource"
        )
    resolved = tuple(
        resolve_computation_resource(store, ref, file_backed=backend.file_backed_inputs)
        for ref in plan.request.resources
    )
    for binding in plan.request.inputs:
        resource = next(item for item in resolved if item.descriptor.reference == binding.resource)
        if resource.descriptor.logical_type != binding.logical_type:
            raise TransformationError(
                "COMPUTATION_INPUT_TYPE", f"Input {binding.name} has the wrong logical type/version"
            )
        registry.resolve_registered_contract_references(
            (
                ContractReference(
                    ContractKind.RESOURCE_LOGICAL_TYPE,
                    binding.logical_type.id,
                    binding.logical_type.version,
                ),
            )
        )
    for output in plan.request.outputs:
        if not set(output.semantic_ids) <= available:
            raise TransformationError(
                "COMPUTATION_OUTPUT_ORIGINS", "Output origins are outside the frozen definition"
            )
        registry.resolve_registered_contract_references(
            (
                ContractReference(
                    ContractKind.RESOURCE_LOGICAL_TYPE,
                    output.logical_type.id,
                    output.logical_type.version,
                ),
            )
        )
    return PreparedComputation(
        project,
        plan.request,
        plan.representation,
        value,
        plan.origins,
        plan.transformations,
        plan.input_digest,
        entrypoints,
        resolved,
        dependencies,
    )


def load_terminal(
    plan: ComputationPlan, store: ResourceStore, registry: DomainExtensionRegistry
) -> PreparedComputation:
    """Worker admission: decode inert data, then execute registered validation."""
    snapshot = decode_terminal(plan, store, registry)
    for model in snapshot.project.domain_workspace.models:
        issues = registry.validate_model(snapshot.project, model)
        if issues:
            raise TransformationError(issues[0].code, issues[0].message)
    if isinstance(snapshot.value, ProgramModel):
        from code_visualizer.validation import assess_project

        assessment = assess_project(snapshot.project, extensions=registry)
        if not assessment.buildable:
            first = assessment.blocking_diagnostics[0]
            raise TransformationError(first.code, first.message)
    return snapshot
