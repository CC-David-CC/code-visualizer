"""Python adapter for the neutral computation contract, using the existing pipeline."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from code_visualizer.domain.computation import (
    BackendCapabilities,
    BackendDefinition,
    BackendExecutionMode,
)
from code_visualizer.domain.evidence import (
    ComputationOutcome,
    EvidenceDiagnostic,
    EvidenceObservation,
)
from code_visualizer.domain.program import ProgramModel
from code_visualizer.domain.transformation import PROGRAM_REPRESENTATION
from code_visualizer.domain.values import MAX_INLINE_BYTES, ResourceReference
from code_visualizer.execution.backends import (
    BackendContext,
    BackendResult,
    BackendUpdate,
    PreparedComputation,
    ProducedResource,
    RegisteredBackend,
)
from code_visualizer.generation.lowering import lower_project
from code_visualizer.generation.transformation import TransformationError

if TYPE_CHECKING:
    from code_visualizer.execution.runner import TraceResult
    from code_visualizer.generation.emitter import GeneratedProject

SOURCE_FILE_PREFIX = "source_file:"
MAX_SOURCE_FILE_BYTES = 8 * 1024 * 1024


def python_backend() -> RegisteredBackend:
    return RegisteredBackend(
        BackendDefinition(
            "code_visualizer.python",
            "1",
            "Python execution",
            PROGRAM_REPRESENTATION,
            description="Existing Python lowering, source maps, and trace worker.",
            capabilities=BackendCapabilities(external_worker=True),
        ),
        _execute,
        source_file_parameter_prefix=SOURCE_FILE_PREFIX,
    )


def publishing_python_backend() -> RegisteredBackend:
    return RegisteredBackend(
        BackendDefinition(
            "code_visualizer.python",
            "2",
            "Python with typed artifacts",
            PROGRAM_REPRESENTATION,
            description="The emitted package and managed child, with acknowledged publication.",
            capabilities=BackendCapabilities(
                BackendExecutionMode.STREAMING,
                observations=True,
                cancellation=True,
                external_worker=True,
                publications=True,
            ),
        ),
        stream=_host_stream,
        source_file_parameter_prefix=SOURCE_FILE_PREFIX,
    )


def _host_stream(snapshot: PreparedComputation, context: BackendContext) -> Iterator[BackendUpdate]:
    # A publication capability requires durable host admission. Embedding cannot
    # silently substitute an unacknowledged local file or another child process.
    yield BackendResult(
        ComputationOutcome.FAILED,
        diagnostics=(
            EvidenceDiagnostic(
                "COMPUTATION_HOST_REQUIRED",
                "Python resource publication requires the managed computation host",
            ),
        ),
    )


def python_timeout(snapshot: PreparedComputation) -> float:
    configuration = {item.name: item.value for item in snapshot.request.configuration}
    timeout = configuration.get("timeout_seconds", 30.0)
    if (
        any(
            name != "timeout_seconds" and not name.startswith(SOURCE_FILE_PREFIX)
            for name in configuration
        )
        or not isinstance(timeout, int | float)
        or isinstance(timeout, bool)
        or not 0 < timeout <= 300
    ):
        raise TransformationError(
            "COMPUTATION_CONFIGURATION",
            "Python accepts timeout_seconds in (0, 300]; "
            "callable arguments belong to module invocation",
        )
    return float(timeout)


def prepare_python(snapshot: PreparedComputation) -> GeneratedProject:
    """Prepare emitted files once, in the trusted preparation process."""
    from code_visualizer.generation.emitter import GeneratedFile, emit_project
    from code_visualizer.generation.program_composition import select_entrypoint

    program = snapshot.value
    if not isinstance(program, ProgramModel):
        raise TransformationError(
            "COMPUTATION_REPRESENTATION", "Python requires a typed ProgramModel terminal"
        )
    python_timeout(snapshot)
    if snapshot.request.backend_version == "1" and (
        snapshot.request.inputs or snapshot.request.outputs
    ):
        raise TransformationError(
            "COMPUTATION_BACKEND_CAPABILITY", "Named resources require Python backend version 2"
        )
    if len(snapshot.entrypoint_ids) > 1:
        raise TransformationError("EXECUTION_ENTRYPOINT", "Choose at most one Python entrypoint")
    project = replace(
        snapshot.project,
        program_model=select_entrypoint(
            program, snapshot.entrypoint_ids[0] if snapshot.entrypoint_ids else None
        ),
    )
    ir = lower_project(project)
    generated = emit_project(ir)
    files = list(generated.files)
    paths = {item.path.casefold() for item in files}
    resources = {item.descriptor.reference: item for item in snapshot.resources}
    for parameter in sorted(snapshot.request.configuration, key=lambda item: item.name):
        if not parameter.name.startswith(SOURCE_FILE_PREFIX):
            continue
        path = parameter.name.removeprefix(SOURCE_FILE_PREFIX)
        if (
            not path
            or PurePosixPath(path).is_absolute()
            or "\\" in path
            or ":" in path
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or path.casefold() in paths
        ):
            raise TransformationError(
                "COMPUTATION_SOURCE_PATH", "Source file path escapes or replaces emitted files"
            )
        reference = parameter.value
        if not isinstance(reference, ResourceReference) or reference not in resources:
            raise TransformationError(
                "COMPUTATION_SOURCE_RESOURCE", "Source files require resolved resource references"
            )
        resource = resources[reference]
        if resource.descriptor.byte_size > MAX_SOURCE_FILE_BYTES:
            raise TransformationError(
                "COMPUTATION_SOURCE_SIZE", "Source file exceeds its bounded payload"
            )
        with resource.open() as source:
            payload = source.read(MAX_SOURCE_FILE_BYTES + 1)
        if len(payload) != resource.descriptor.byte_size:
            raise TransformationError("COMPUTATION_SOURCE_SIZE", "Source file size changed")
        files.append(GeneratedFile(path, payload.decode("utf-8"), ()))
        paths.add(path.casefold())
    return replace(generated, files=tuple(files))


def _execute(snapshot: PreparedComputation) -> BackendResult:
    from code_visualizer.execution.computation_driver import ManagedPythonDriver

    driver = ManagedPythonDriver("embedded-python", snapshot, prepare_python(snapshot))
    try:
        return driver.advance()
    finally:
        driver.close()


def result_from_python_trace(
    snapshot: PreparedComputation, generated: GeneratedProject, trace: TraceResult
) -> BackendResult:
    """One result interpretation for managed production and explicit embedding."""
    program = snapshot.value
    assert isinstance(program, ProgramModel)
    scope_ids = snapshot.entrypoint_ids or tuple(module.id for module in program.modules)
    observations: list[EvidenceObservation] = []
    diagnostics: list[EvidenceDiagnostic] = []
    resources: list[ProducedResource] = []
    for event in trace.runtime_events:
        spans = [
            item
            for item in generated.spans
            if item.file_path == event.file_path and item.start_line <= event.line <= item.end_line
        ]
        if not spans:
            continue
        if len(observations) == 9998:
            diagnostics.append(
                EvidenceDiagnostic(
                    "PYTHON_TRACE_TRUNCATED",
                    "Evidence retained the first 9998 source observations",
                    scope_ids,
                )
            )
            break
        span = min(spans, key=lambda item: (item.end_line - item.start_line, item.start_line))
        observations.append(
            EvidenceObservation(
                f"python:trace:{len(observations)}",
                (span.semantic_id,),
                event.event,
                f"Python {event.file_path}:{event.line}",
                len(observations),
            )
        )
    for label, value in (("stdout", trace.run.stdout), ("stderr", trace.run.stderr)):
        encoded = value.encode("utf-8")
        if len(encoded) > MAX_INLINE_BYTES:
            resources.append(
                ProducedResource(
                    f"python:{label}",
                    encoded,
                    "text/plain;charset=utf-8",
                    scope_ids,
                    label,
                )
            )
            continue
        observations.append(
            EvidenceObservation(
                f"python:{label}",
                scope_ids,
                value,
                label,
                len(observations),
            )
        )
    if trace.events_truncated and not any(
        item.code == "PYTHON_TRACE_TRUNCATED" for item in diagnostics
    ):
        diagnostics.append(
            EvidenceDiagnostic(
                "PYTHON_TRACE_TRUNCATED",
                "The trace worker reached its event capture bound",
                scope_ids,
            )
        )
    if trace.run.output_truncated:
        diagnostics.append(
            EvidenceDiagnostic(
                "PYTHON_OUTPUT_TRUNCATED",
                "The execution worker reached its output capture bound",
                scope_ids,
            )
        )
    if trace.run.return_code != 0:
        diagnostics.append(
            EvidenceDiagnostic(
                "PYTHON_EXECUTION_TIMEOUT" if trace.run.timed_out else "PYTHON_EXECUTION_FAILED",
                trace.run.stderr[:2048]
                or f"Python execution ended: {trace.run.termination_reason}",
                scope_ids,
            )
        )
    return BackendResult(
        ComputationOutcome.CANCELLED
        if trace.run.termination_reason == "stopped"
        else ComputationOutcome.SUCCEEDED
        if trace.run.return_code == 0
        else ComputationOutcome.FAILED,
        tuple(observations),
        diagnostics=tuple(diagnostics),
        produced_resources=tuple(resources),
    )
