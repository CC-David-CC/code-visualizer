"""Bounded worker protocol; no code loading, paths, untyped payloads, or callbacks."""

from code_visualizer.domain.computation import CancelRequest, ProgressEvent
from code_visualizer.domain.evidence import EvidenceDiagnostic, ObservationEvent, PublicationEvent
from code_visualizer.domain.preview import PreviewEvent
from code_visualizer.domain.worker import (
    WorkerCompletionVerified,
    WorkerControl,
    WorkerEditorPreparationRequest,
    WorkerEditorPrepared,
    WorkerEvent,
    WorkerEvidenceProposal,
    WorkerExecutionRequest,
    WorkerFailure,
    WorkerPreparationRequest,
    WorkerPrepared,
    WorkerPublicationOffer,
    WorkerRequest,
    WorkerResourceEvent,
    WorkerTerminalSecured,
)
from code_visualizer.protocol.computation import (
    backend_from_proto,
    backend_to_proto,
    cancel_from_proto,
    cancel_to_proto,
    computation_plan_from_proto,
    computation_plan_to_proto,
    computation_request_from_proto,
    computation_request_to_proto,
    progress_from_proto,
    progress_to_proto,
)
from code_visualizer.protocol.evidence import (
    artifact_from_proto,
    artifact_to_proto,
    evidence_from_proto,
    evidence_to_proto,
    observation_event_from_proto,
    observation_event_to_proto,
    publication_event_from_proto,
    publication_event_to_proto,
)
from code_visualizer.protocol.invocation import (
    invocation_arguments_from_proto,
    invocation_arguments_to_proto,
)
from code_visualizer.protocol.preview import preview_from_proto, preview_to_proto
from code_visualizer.protocol.resource_transfer import (
    resource_frame_from_proto,
    resource_frame_to_proto,
)
from code_visualizer.protocol.v1 import worker_pb2 as wire
from code_visualizer.protocol.v1.evidence_pb2 import EvidenceDiagnostic as WireDiagnostic
from code_visualizer.protocol.validation import check_message, invalid, parse_message, require_field
from code_visualizer.protocol.values import (
    resource_reference_from_proto,
    resource_reference_to_proto,
)


def worker_request_to_proto(value: WorkerRequest) -> wire.WorkerRequest:
    result = wire.WorkerRequest(schema_version=1)
    if isinstance(value, WorkerPreparationRequest):
        result.prepare.CopyFrom(
            wire.WorkerPreparationRequest(
                session_id=value.session_id,
                project=resource_reference_to_proto(value.project),
                request=computation_request_to_proto(value.request),
                backend=backend_to_proto(value.backend),
            )
        )
    elif isinstance(value, WorkerExecutionRequest):
        result.execute.CopyFrom(
            wire.WorkerExecutionRequest(
                session_id=value.session_id,
                plan=computation_plan_to_proto(value.plan),
                backend=backend_to_proto(value.backend),
            )
        )
        if value.execution_artifact is not None:
            result.execute.execution_artifact.CopyFrom(
                resource_reference_to_proto(value.execution_artifact)
            )
    elif isinstance(value, WorkerEditorPreparationRequest):
        editor = result.prepare_editor
        editor.session_id = value.session_id
        editor.project.CopyFrom(resource_reference_to_proto(value.project))
        editor.project_id = value.project_id
        editor.revision = value.revision
        if value.focus_diagram_id is not None:
            editor.focus_diagram_id = value.focus_diagram_id
        if value.model_id is not None:
            editor.model_id = value.model_id
        if value.arguments is not None:
            editor.arguments.CopyFrom(invocation_arguments_to_proto(value.arguments))
    else:
        raise invalid("A worker request must use the closed preparation/execution vocabulary")
    check_message(result, version=1)
    return result


def worker_request_from_proto(value: wire.WorkerRequest) -> WorkerRequest:
    check_message(value, version=value.schema_version)
    match value.WhichOneof("request"):
        case "prepare":
            prepare = value.prepare
            for name in ("project", "request", "backend"):
                require_field(prepare, name)
            return WorkerPreparationRequest(
                prepare.session_id,
                resource_reference_from_proto(prepare.project),
                computation_request_from_proto(prepare.request),
                backend_from_proto(prepare.backend),
            )
        case "execute":
            execute = value.execute
            for name in ("plan", "backend"):
                require_field(execute, name)
            return WorkerExecutionRequest(
                execute.session_id,
                computation_plan_from_proto(execute.plan),
                backend_from_proto(execute.backend),
                resource_reference_from_proto(execute.execution_artifact)
                if execute.HasField("execution_artifact")
                else None,
            )
        case "prepare_editor":
            editor = value.prepare_editor
            require_field(editor, "project")
            return WorkerEditorPreparationRequest(
                editor.session_id,
                resource_reference_from_proto(editor.project),
                editor.project_id,
                editor.revision,
                editor.focus_diagram_id if editor.HasField("focus_diagram_id") else None,
                editor.model_id if editor.HasField("model_id") else None,
                invocation_arguments_from_proto(editor.arguments)
                if editor.HasField("arguments")
                else None,
            )
        case _:
            raise invalid("A worker request variant must be present")


def worker_event_to_proto(value: WorkerEvent) -> wire.WorkerEvent:
    result = wire.WorkerEvent(schema_version=1)
    if isinstance(value, WorkerPrepared):
        result.prepared.CopyFrom(
            wire.WorkerPrepared(
                session_id=value.session_id, plan=computation_plan_to_proto(value.plan)
            )
        )
        if value.execution_artifact is not None:
            result.prepared.execution_artifact.CopyFrom(
                resource_reference_to_proto(value.execution_artifact)
            )
    elif isinstance(value, WorkerEditorPrepared):
        result.editor_prepared.CopyFrom(
            wire.WorkerEditorPrepared(
                session_id=value.session_id,
                source_digest=value.source_digest,
                execution_artifact=resource_reference_to_proto(value.execution_artifact),
            )
        )
    elif isinstance(value, WorkerResourceEvent):
        result.resource.CopyFrom(
            wire.WorkerResourceEvent(
                session_id=value.session_id, frame=resource_frame_to_proto(value.frame)
            )
        )
    elif isinstance(value, ProgressEvent):
        result.progress.CopyFrom(progress_to_proto(value))
    elif isinstance(value, PreviewEvent):
        result.preview.CopyFrom(preview_to_proto(value))
    elif isinstance(value, ObservationEvent):
        result.observation.CopyFrom(observation_event_to_proto(value))
    elif isinstance(value, WorkerPublicationOffer):
        result.publication.CopyFrom(
            wire.WorkerPublicationOffer(
                session_id=value.session_id,
                sequence=value.sequence,
                artifact=artifact_to_proto(value.artifact),
            )
        )
    elif isinstance(value, WorkerEvidenceProposal):
        result.evidence.CopyFrom(
            wire.WorkerEvidenceProposal(
                session_id=value.session_id, evidence=evidence_to_proto(value.evidence)
            )
        )
    elif isinstance(value, WorkerCompletionVerified):
        result.verified.CopyFrom(wire.WorkerCompletionVerified(session_id=value.session_id))
    elif isinstance(value, WorkerFailure):
        result.failure.CopyFrom(
            wire.WorkerFailure(
                session_id=value.session_id,
                diagnostic=WireDiagnostic(
                    code=value.diagnostic.code,
                    message=value.diagnostic.message,
                    semantic_ids=value.diagnostic.semantic_ids,
                ),
            )
        )
    else:
        raise invalid("A worker event must use the closed typed vocabulary")
    check_message(result, version=1)
    return result


def worker_event_from_proto(value: wire.WorkerEvent) -> WorkerEvent:
    check_message(value, version=value.schema_version)
    match value.WhichOneof("event"):
        case "prepared":
            prepared = value.prepared
            require_field(prepared, "plan")
            return WorkerPrepared(
                prepared.session_id,
                computation_plan_from_proto(prepared.plan),
                resource_reference_from_proto(prepared.execution_artifact)
                if prepared.HasField("execution_artifact")
                else None,
            )
        case "editor_prepared":
            editor = value.editor_prepared
            require_field(editor, "execution_artifact")
            return WorkerEditorPrepared(
                editor.session_id,
                editor.source_digest,
                resource_reference_from_proto(editor.execution_artifact),
            )
        case "resource":
            require_field(value.resource, "frame")
            return WorkerResourceEvent(
                value.resource.session_id, resource_frame_from_proto(value.resource.frame)
            )
        case "progress":
            return progress_from_proto(value.progress)
        case "preview":
            return preview_from_proto(value.preview)
        case "observation":
            return observation_event_from_proto(value.observation)
        case "publication":
            require_field(value.publication, "artifact")
            return WorkerPublicationOffer(
                value.publication.session_id,
                value.publication.sequence,
                artifact_from_proto(value.publication.artifact),
            )
        case "evidence":
            require_field(value.evidence, "evidence")
            return WorkerEvidenceProposal(
                value.evidence.session_id, evidence_from_proto(value.evidence.evidence)
            )
        case "verified":
            return WorkerCompletionVerified(value.verified.session_id)
        case "failure":
            require_field(value.failure, "diagnostic")
            diagnostic = value.failure.diagnostic
            return WorkerFailure(
                value.failure.session_id,
                EvidenceDiagnostic(
                    diagnostic.code, diagnostic.message, tuple(diagnostic.semantic_ids)
                ),
            )
        case _:
            raise invalid("A worker event variant must be present")


def worker_control_to_proto(value: WorkerControl) -> wire.WorkerControl:
    result = wire.WorkerControl(schema_version=1)
    if isinstance(
        value, WorkerPreparationRequest | WorkerExecutionRequest | WorkerEditorPreparationRequest
    ):
        result.request.CopyFrom(worker_request_to_proto(value))
    elif isinstance(value, CancelRequest):
        result.cancel.CopyFrom(cancel_to_proto(value))
    elif isinstance(value, PublicationEvent):
        result.publication_ack.CopyFrom(publication_event_to_proto(value))
    elif isinstance(value, WorkerTerminalSecured):
        result.terminal_ack.CopyFrom(
            wire.WorkerTerminalSecured(session_id=value.session_id, evidence_id=value.evidence_id)
        )
    else:
        raise invalid("A worker control must use the closed typed vocabulary")
    check_message(result, version=1)
    return result


def worker_control_from_proto(value: wire.WorkerControl) -> WorkerControl:
    check_message(value, version=value.schema_version)
    match value.WhichOneof("control"):
        case "request":
            return worker_request_from_proto(value.request)
        case "cancel":
            return cancel_from_proto(value.cancel)
        case "publication_ack":
            return publication_event_from_proto(value.publication_ack)
        case "terminal_ack":
            return WorkerTerminalSecured(
                value.terminal_ack.session_id, value.terminal_ack.evidence_id
            )
        case _:
            raise invalid("A worker control variant must be present")


def worker_control_to_bytes(value: WorkerControl) -> bytes:
    return worker_control_to_proto(value).SerializeToString(deterministic=True)


def worker_control_from_bytes(value: bytes) -> WorkerControl:
    return worker_control_from_proto(parse_message(value, wire.WorkerControl))


def worker_event_to_bytes(value: WorkerEvent) -> bytes:
    return worker_event_to_proto(value).SerializeToString(deterministic=True)


def worker_event_from_bytes(value: bytes) -> WorkerEvent:
    return worker_event_from_proto(parse_message(value, wire.WorkerEvent))
