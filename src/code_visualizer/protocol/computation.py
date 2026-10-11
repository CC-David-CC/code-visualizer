"""Computation requests describe a pinned backend; they never carry executable callbacks."""

from typing import cast

from code_visualizer.domain.computation import (
    BackendCapabilities,
    BackendDefinition,
    BackendExecutionMode,
    CancelRequest,
    ComputationParameter,
    ComputationPlan,
    ComputationRequest,
    ComputationSession,
    ComputationStatus,
    ProgressEvent,
    ResourceInput,
    ResourceOutput,
)
from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.transformation import Representation
from code_visualizer.protocol.identity import origins_from_proto, origins_to_proto
from code_visualizer.protocol.v1 import computation_pb2 as wire
from code_visualizer.protocol.v1.identity_pb2 import VersionedReference
from code_visualizer.protocol.validation import check_message, invalid, require_field
from code_visualizer.protocol.values import (
    canonical_value_from_proto,
    canonical_value_to_proto,
    integer_from_proto,
    integer_to_proto,
    resource_reference_from_proto,
    resource_reference_to_proto,
)


def parameter_to_proto(value: ComputationParameter) -> wire.ComputationParameter:
    return wire.ComputationParameter(name=value.name, value=canonical_value_to_proto(value.value))


def parameter_from_proto(value: wire.ComputationParameter) -> ComputationParameter:
    require_field(value, "value")
    return ComputationParameter(value.name, canonical_value_from_proto(value.value))


def backend_to_proto(value: BackendDefinition) -> wire.BackendDefinition:
    result = wire.BackendDefinition(
        schema_version=1,
        id=value.id,
        version=value.version,
        title=value.title,
        description=value.description,
        api_version=value.api_version,
        capabilities=capabilities_to_proto(value.capabilities),
        input_representation=VersionedReference(
            id=value.input_representation.id, version=value.input_representation.version
        ),
    )
    if value.schema_id is not None:
        result.input_schema_id = value.schema_id
    if value.schema_version is not None:
        result.input_schema_version = value.schema_version
    return result


def backend_from_proto(value: wire.BackendDefinition) -> BackendDefinition:
    check_message(value, version=value.schema_version)
    require_field(value, "input_representation")
    require_field(value, "capabilities")
    return BackendDefinition(
        value.id,
        value.version,
        value.title,
        Representation(value.input_representation.id, value.input_representation.version),
        value.input_schema_id if value.HasField("input_schema_id") else None,
        value.input_schema_version if value.HasField("input_schema_version") else None,
        value.description,
        value.api_version,
        capabilities_from_proto(value.capabilities),
    )


def capabilities_to_proto(value: BackendCapabilities) -> wire.BackendCapabilities:
    return wire.BackendCapabilities(
        execution_mode=cast(
            wire.BackendExecutionMode,
            wire.BackendExecutionMode.Value("MODE_" + value.execution_mode.value.upper()),
        ),
        progress=value.progress,
        observations=value.observations,
        cancellation=value.cancellation,
        deterministic=value.deterministic,
        seeded=value.seeded,
        external_worker=value.external_worker,
        publications=value.publications,
    )


def capabilities_from_proto(value: wire.BackendCapabilities) -> BackendCapabilities:
    try:
        mode = BackendExecutionMode(
            wire.BackendExecutionMode.Name(value.execution_mode).removeprefix("MODE_").lower()
        )
    except ValueError as exc:
        raise invalid("Unknown backend execution mode") from exc
    return BackendCapabilities(
        mode,
        value.progress,
        value.observations,
        value.cancellation,
        value.deterministic,
        value.seeded,
        value.external_worker,
        value.publications,
    )


def computation_request_to_proto(value: ComputationRequest) -> wire.ComputationRequest:
    result = wire.ComputationRequest(
        schema_version=2 if value.inputs or value.outputs else 1,
        project_id=value.project_id,
        revision=value.revision,
        backend_id=value.backend_id,
        backend_version=value.backend_version,
        configuration=[parameter_to_proto(p) for p in value.configuration],
        resources=[resource_reference_to_proto(r) for r in value.resources],
        inputs=[
            wire.ResourceInput(
                name=i.name,
                resource=resource_reference_to_proto(i.resource),
                logical_type=VersionedReference(
                    id=i.logical_type.id, version=i.logical_type.version
                ),
            )
            for i in value.inputs
        ],
        outputs=[
            wire.ResourceOutput(
                name=o.name,
                logical_type=VersionedReference(
                    id=o.logical_type.id, version=o.logical_type.version
                ),
                semantic_ids=o.semantic_ids,
                required=o.required,
            )
            for o in value.outputs
        ],
    )
    if value.model_id is not None:
        result.model_id = value.model_id
    if value.seed is not None:
        result.seed.CopyFrom(integer_to_proto(value.seed))
    check_message(result)
    return result


def computation_request_from_proto(value: wire.ComputationRequest) -> ComputationRequest:
    check_message(value)
    if value.schema_version != (2 if value.inputs or value.outputs else 1):
        raise invalid("Request schema version must match its resource binding contract")
    for item in value.inputs:
        require_field(item, "resource")
        require_field(item, "logical_type")
    for output in value.outputs:
        require_field(output, "logical_type")
    return ComputationRequest(
        value.project_id,
        value.revision,
        value.backend_id,
        value.backend_version,
        value.model_id if value.HasField("model_id") else None,
        tuple(parameter_from_proto(p) for p in value.configuration),
        integer_from_proto(value.seed) if value.HasField("seed") else None,
        tuple(resource_reference_from_proto(r) for r in value.resources),
        tuple(
            ResourceInput(
                i.name,
                resource_reference_from_proto(i.resource),
                ResourceLogicalTypeReference(i.logical_type.id, i.logical_type.version),
            )
            for i in value.inputs
        ),
        tuple(
            ResourceOutput(
                o.name,
                ResourceLogicalTypeReference(o.logical_type.id, o.logical_type.version),
                tuple(o.semantic_ids),
                o.required,
            )
            for o in value.outputs
        ),
    )


def computation_plan_to_proto(value: ComputationPlan) -> wire.ComputationPlan:
    result = wire.ComputationPlan(
        schema_version=1,
        request=computation_request_to_proto(value.request),
        representation=VersionedReference(
            id=value.representation.id, version=value.representation.version
        ),
        model=resource_reference_to_proto(value.model),
        transformations=value.transformations,
        origins=origins_to_proto(value.origins),
        input_digest=value.input_digest,
    )
    check_message(result, version=1)
    return result


def computation_plan_from_proto(value: wire.ComputationPlan) -> ComputationPlan:
    check_message(value, version=value.schema_version)
    for field in ("request", "representation", "model", "origins"):
        require_field(value, field)
    return ComputationPlan(
        computation_request_from_proto(value.request),
        Representation(value.representation.id, value.representation.version),
        resource_reference_from_proto(value.model),
        tuple(value.transformations),
        origins_from_proto(value.origins),
        value.input_digest,
    )


def session_to_proto(value: ComputationSession) -> wire.ComputationSession:
    result = wire.ComputationSession(
        schema_version=1,
        id=value.id,
        project_id=value.project_id,
        revision=value.revision,
        backend_id=value.backend_id,
        backend_version=value.backend_version,
        status=cast(
            wire.ComputationStatus,
            wire.ComputationStatus.Value("STATUS_" + value.status.value.upper()),
        ),
        cancellation_supported=value.cancellation_supported,
    )
    if value.evidence_id is not None:
        result.evidence_id = value.evidence_id
    return result


def session_from_proto(value: wire.ComputationSession) -> ComputationSession:
    check_message(value, version=value.schema_version)
    try:
        status = ComputationStatus(
            wire.ComputationStatus.Name(value.status).removeprefix("STATUS_").lower()
        )
    except ValueError as exc:
        raise invalid("Unknown computation status") from exc
    return ComputationSession(
        value.id,
        value.project_id,
        value.revision,
        value.backend_id,
        value.backend_version,
        status,
        value.cancellation_supported,
        value.evidence_id if value.HasField("evidence_id") else None,
    )


def progress_to_proto(value: ProgressEvent) -> wire.ProgressEvent:
    result = wire.ProgressEvent(
        schema_version=1,
        session_id=value.session_id,
        sequence=value.sequence,
        completed=value.completed,
        message=value.message,
    )
    if value.total is not None:
        result.total = value.total
    check_message(result, version=1)
    return result


def progress_from_proto(value: wire.ProgressEvent) -> ProgressEvent:
    check_message(value, version=value.schema_version)
    return ProgressEvent(
        value.session_id,
        value.sequence,
        value.completed,
        value.total if value.HasField("total") else None,
        value.message,
    )


def cancel_to_proto(value: CancelRequest) -> wire.CancelRequest:
    return wire.CancelRequest(schema_version=1, session_id=value.session_id, reason=value.reason)


def cancel_from_proto(value: wire.CancelRequest) -> CancelRequest:
    check_message(value, version=value.schema_version)
    return CancelRequest(value.session_id, value.reason)
