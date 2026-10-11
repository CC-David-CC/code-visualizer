"""Fixed-step diffusion in the existing cancellable, acknowledged backend lifecycle."""

from __future__ import annotations

from collections.abc import Iterator
from math import ceil

from code_visualizer.domain.computation import (
    BackendCapabilities,
    BackendDefinition,
    BackendExecutionMode,
    ProgressEvent,
)
from code_visualizer.domain.evidence import (
    ComputationOutcome,
    EvidenceDiagnostic,
    EvidenceObservation,
    ObservationEvent,
)
from code_visualizer.domain.intentional import DomainModel
from code_visualizer.domain.values import QuantityValue, ResourceReference, TensorDType, TensorValue
from code_visualizer.execution.backends import (
    BackendContext,
    BackendResult,
    BackendUpdate,
    CheckpointContract,
    PreparedComputation,
    PreviewContract,
    ProducedResourceEvent,
    RegisteredBackend,
)
from code_visualizer.extensions.diffusion.checkpoint import checkpoint_resource, restore
from code_visualizer.extensions.diffusion.domain import (
    BACKEND_ID,
    CHECKPOINT_PARAMETER,
    REPRESENTATION,
    quantity,
)
from code_visualizer.extensions.diffusion.history import HistoryWriter
from code_visualizer.extensions.diffusion.problem import definition_digest, derive_problem
from code_visualizer.extensions.fields.preview import FieldPreview, validate_preview
from code_visualizer.extensions.fields.records import (
    CHECKPOINT_TYPE,
    PREVIEW_TYPE,
    TemporalPosition,
)


def diffusion_backend() -> RegisteredBackend:
    return RegisteredBackend(
        BackendDefinition(
            BACKEND_ID,
            "1",
            "One-dimensional diffusion (Crank-Nicolson)",
            REPRESENTATION,
            capabilities=BackendCapabilities(
                BackendExecutionMode.STREAMING,
                progress=True,
                observations=True,
                cancellation=True,
                deterministic=True,
                publications=True,
            ),
        ),
        stream=stream_diffusion,
        checkpoint=CheckpointContract(CHECKPOINT_TYPE, CHECKPOINT_PARAMETER),
        preview=PreviewContract(PREVIEW_TYPE, validate_preview),
        file_backed_inputs=True,
    )


def stream_diffusion(
    snapshot: PreparedComputation, context: BackendContext
) -> Iterator[BackendUpdate]:
    try:
        yield from _integrate(snapshot, context)
    except ImportError as exc:
        yield BackendResult(
            ComputationOutcome.FAILED,
            diagnostics=(
                EvidenceDiagnostic(
                    "SCIENCE_DEPENDENCY_MISSING", f"Install the fields extra: {exc}"
                ),
            ),
        )
    except (ValueError, KeyError, FloatingPointError, OverflowError) as exc:
        yield BackendResult(
            ComputationOutcome.FAILED,
            diagnostics=(EvidenceDiagnostic(getattr(exc, "code", "DIFFUSION_INVALID"), str(exc)),),
        )


def _integrate(snapshot: PreparedComputation, context: BackendContext) -> Iterator[BackendUpdate]:
    import numpy as np

    from code_visualizer.extensions.diffusion.numerics import CrankNicolson

    if not isinstance(snapshot.value, DomainModel):
        raise ValueError("Diffusion requires a typed intentional problem")
    configuration = {item.name: item.value for item in snapshot.request.configuration}
    if set(configuration) - {CHECKPOINT_PARAMETER}:
        raise ValueError(
            "Unknown diffusion configuration; physical policy belongs to the authored model"
        )
    problem = derive_problem(snapshot.project, snapshot.value)
    source = definition_digest(snapshot)
    solver = CrankNicolson(problem)
    coordinates = np.arange(problem.nodes, dtype=np.float64) * problem.dx
    previous = None
    reference = configuration.get(CHECKPOINT_PARAMETER)
    if reference is not None:
        if not isinstance(reference, ResourceReference):
            raise ValueError("DIFFUSION_CHECKPOINT_TYPE: resume requires an explicit resource")
        previous, state = restore(snapshot, reference, problem, source, solver.numerical_identity)
        start = previous.series.last.step
    else:
        state = problem.amplitude * np.sin(np.pi * coordinates / problem.length)
        state[0] = state[-1] = 0.0
        start = 0
    writer = HistoryWriter(problem, source, coordinates, previous)
    if previous is not None:
        previous.close()
    # Finite output is admitted against the same receipt encoding as publication.
    from code_visualizer.execution.publication_budget import require_publication_capacity

    samples = (
        ceil((problem.steps - start) / problem.sample_every)
        + ceil((problem.steps - start) / problem.checkpoint_every)
        + 2
    )
    checkpoint_count = ceil((problem.steps - start) / problem.checkpoint_every) + 2
    roots = ceil(samples / problem.chunk_rows) + checkpoint_count + 2
    require_publication_capacity(
        snapshot,
        context.session_id,
        roots + checkpoint_count,
        (problem.problem_id, problem.field_id),
        artifact_text_bytes=512,
    )
    sequence = 0

    def next_sequence() -> int:
        nonlocal sequence
        result, sequence = sequence, sequence + 1
        return result

    def flush() -> Iterator[BackendUpdate]:
        for produced in writer.flush():
            yield ProducedResourceEvent(context.session_id, next_sequence(), produced)

    if reference is None:
        writer.sample(0, state)
        yield from flush()
    last_checkpoint = start if reference is not None else -1
    sampled_step, sampled_state = start, state
    max_residual = max_normalized = 0.0
    step = start
    for step in range(start + 1, problem.steps + 1):
        if context.cancellation_requested:
            step -= 1
            break
        predictor = solver.predictor(state)
        # Only a genuine sampled accepted base is displayed. This is an actual
        # predictor, and its candidate never becomes a retained sample by rendering.
        position = writer.positions[-1] if writer.positions else writer.last
        if (
            (step - 1) % problem.preview_every == 0
            and position is not None
            and position.step == step - 1
        ):
            indices = np.unique(
                np.linspace(0, problem.nodes - 1, min(256, problem.nodes), dtype=np.int64)
            )
            preview = FieldPreview(
                writer.interpretation,
                position,
                TemporalPosition(quantity(problem.time(step)), step, position.sample + 1),
                TensorValue(TensorDType.INT64, (len(indices),), tuple(int(i) for i in indices)),
                TensorValue(
                    TensorDType.FLOAT64, (len(indices),), tuple(float(state[i]) for i in indices)
                ),
                TensorValue(
                    TensorDType.FLOAT64,
                    (len(indices),),
                    tuple(float(predictor[i]) for i in indices),
                ),
            )
            yield preview.event(
                context.session_id, next_sequence(), snapshot.input_digest, problem.field_id
            )
        corrected = solver.correct(state, predictor)
        state = corrected.accepted
        max_residual = max(max_residual, corrected.dimensional_residual)
        max_normalized = max(
            max_normalized, corrected.dimensional_residual / corrected.residual_scale
        )
        checkpoint_due = step % problem.checkpoint_every == 0
        if step % problem.sample_every == 0 or checkpoint_due or step == problem.steps:
            writer.sample(step, state)
            sampled_step, sampled_state = step, state
        if writer.full or checkpoint_due or step == problem.steps:
            yield from flush()
        if checkpoint_due:
            yield ProducedResourceEvent(
                context.session_id,
                next_sequence(),
                checkpoint_resource(problem, source, solver.numerical_identity, writer, state),
            )
            last_checkpoint = step
        if step % problem.preview_every == 0 or step == problem.steps:
            yield ProgressEvent(
                context.session_id,
                next_sequence(),
                problem.time(step),
                problem.final_time,
                f"Accepted step {step}/{problem.steps}; t={problem.time(step):.9g} s",
            )
    # Cancellation seals the scheduled accepted prefix. Unpublished numerical
    # steps after its last sample are disposable and are recomputed on resume;
    # cancellation must not insert an extra sample into the authored schedule.
    step, state = sampled_step, sampled_state
    yield from flush()
    if last_checkpoint != step:
        yield ProducedResourceEvent(
            context.session_id,
            next_sequence(),
            checkpoint_resource(problem, source, solver.numerical_identity, writer, state),
        )
    for identity, value, label in (
        (
            "midpoint",
            QuantityValue(float(state[problem.nodes // 2]), problem.unit),
            "Final center-node value",
        ),
        ("time", quantity(problem.time(step)), "Last retained accepted physical time"),
        (
            "residual",
            QuantityValue(max_residual, problem.unit),
            "Maximum dimensional step residual",
        ),
        (
            "residual_scale",
            QuantityValue(problem.scale, problem.unit),
            "Authored residual characteristic scale",
        ),
        ("normalized_residual", max_normalized, "Maximum normalized step residual"),
    ):
        yield ObservationEvent(
            context.session_id,
            EvidenceObservation(
                identity,
                (problem.field_id, problem.problem_id),
                value,
                label,
                sequence=next_sequence(),
            ),
        )
    yield BackendResult(
        ComputationOutcome.CANCELLED
        if context.cancellation_requested
        else ComputationOutcome.SUCCEEDED
    )
