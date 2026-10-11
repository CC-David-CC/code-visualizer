"""Adaptive diffusion is an ordinary host-owned streaming computation backend."""

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
from code_visualizer.domain.values import QuantityValue, ResourceReference
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
from code_visualizer.execution.publication_budget import require_publication_capacity
from code_visualizer.extensions.adaptive_diffusion.checkpoint import (
    CHECKPOINT_TYPE,
)
from code_visualizer.extensions.adaptive_diffusion.domain import (
    BACKEND_ID,
    CHECKPOINT_PARAMETER,
    REPRESENTATION,
)
from code_visualizer.extensions.adaptive_diffusion.problem import (
    AdaptiveError,
    definition_digest,
    derive_problem,
)
from code_visualizer.extensions.adaptive_fields.preview import (
    CellPreview,
    ReducedCells,
    validate_preview,
)
from code_visualizer.extensions.adaptive_fields.records import PREVIEW_TYPE
from code_visualizer.extensions.adaptive_fields.units import quantity


def adaptive_backend() -> RegisteredBackend:
    return RegisteredBackend(
        BackendDefinition(
            BACKEND_ID,
            "1",
            "Conservative adaptive periodic diffusion",
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
        stream=stream,
        checkpoint=CheckpointContract(CHECKPOINT_TYPE, CHECKPOINT_PARAMETER),
        file_backed_inputs=True,
        cancellation_grace_seconds=5.0,
        preview=PreviewContract(PREVIEW_TYPE, validate_preview),
    )


def stream(snapshot: PreparedComputation, context: BackendContext) -> Iterator[BackendUpdate]:
    try:
        yield from integrate(snapshot, context)
    except AdaptiveError as exc:
        yield BackendResult(
            ComputationOutcome.FAILED,
            diagnostics=(EvidenceDiagnostic(exc.code, str(exc), (exc.object_id,)),),
        )
    except ImportError as exc:
        yield BackendResult(
            ComputationOutcome.FAILED,
            diagnostics=(
                EvidenceDiagnostic(
                    "SCIENCE_DEPENDENCY_MISSING",
                    f"Install the fields extra: {exc}",
                    (snapshot.request.model_id,) if snapshot.request.model_id else (),
                ),
            ),
        )
    except (ValueError, KeyError, FloatingPointError, OverflowError) as exc:
        yield BackendResult(
            ComputationOutcome.FAILED,
            diagnostics=(
                EvidenceDiagnostic(
                    "ADAPTIVE_INPUT_OR_NUMERIC",
                    str(exc),
                    (snapshot.request.model_id,) if snapshot.request.model_id else (),
                ),
            ),
        )


def integrate(snapshot: PreparedComputation, context: BackendContext) -> Iterator[BackendUpdate]:
    from code_visualizer.extensions.adaptive_diffusion.checkpoint import (
        checkpoint_resource,
        numerical_identity,
        restore,
    )
    from code_visualizer.extensions.adaptive_diffusion.controller import advance, initialize
    from code_visualizer.extensions.adaptive_diffusion.history import AdaptiveWriter
    from code_visualizer.extensions.adaptive_diffusion.initialization import initialization_resource

    if not isinstance(snapshot.value, DomainModel):
        raise ValueError("Adaptive diffusion requires intentional domain input")
    configuration = {
        parameter.name: parameter.value for parameter in snapshot.request.configuration
    }
    if set(configuration) - {CHECKPOINT_PARAMETER}:
        raise AdaptiveError(
            "ADAPTIVE_CONFIGURATION",
            "Physical policy belongs to the authored model",
            snapshot.value.id,
        )
    p = derive_problem(snapshot.project, snapshot.value)
    source, implementation = definition_digest(snapshot), numerical_identity()
    reference = configuration.get(CHECKPOINT_PARAMETER)
    previous = None
    initialization = None
    if reference is not None:
        if not isinstance(reference, ResourceReference):
            raise AdaptiveError(
                "ADAPTIVE_CHECKPOINT_TYPE", "Resume requires an explicit resource", p.policy_id
            )
        previous, state = restore(snapshot, reference, p, source, implementation)
    else:
        initialization = initialize(p)
        state = initialization.state
    writer = AdaptiveWriter(p, source, state, previous)
    if previous is not None:
        previous.close()
    remaining_samples = (p.policy.final_tick - state.tick) // p.policy.sample_ticks + 1
    checkpoint_count = ceil((p.policy.final_tick - state.tick) / p.policy.checkpoint_ticks) + 2
    roots = (
        ceil(remaining_samples / p.policy.chunk_rows)
        + p.policy.maximum_epochs
        + 2 * checkpoint_count
        + 3
    )
    require_publication_capacity(
        snapshot,
        context.session_id,
        roots,
        (p.problem_id, p.initial_id, p.field_id, p.policy_id),
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
        assert initialization is not None
        yield ProducedResourceEvent(
            context.session_id, next_sequence(), initialization_resource(p, source, initialization)
        )
        writer.sample(state)
        yield from flush()
        yield ProducedResourceEvent(
            context.session_id,
            next_sequence(),
            checkpoint_resource(p, source, implementation, writer, state),
        )
    last_checkpoint = state.tick
    while state.tick < p.policy.final_tick and not context.cancellation_requested:
        next_sample = (state.tick // p.policy.sample_ticks + 1) * p.policy.sample_ticks
        transition = advance(p, state, next_sample)
        if (state.step + 1) % p.policy.preview_every == 0:
            candidate = transition.state
            preview = CellPreview(
                p.region_id,
                p.frame_id,
                p.axis_id,
                p.policy.base_cells,
                quantity(p.length, "meter"),
                quantity(p.policy.quantum),
                "concentration",
                QuantityValue(1.0, p.unit),
                ReducedCells.reduce(state.mesh, state.epoch, state.tick, state.step, state.values),
                ReducedCells.reduce(
                    candidate.mesh,
                    candidate.epoch,
                    candidate.tick,
                    candidate.step,
                    candidate.values,
                ),
            )
            yield preview.event(
                context.session_id,
                next_sequence(),
                snapshot.input_digest,
                (p.field_id, p.region_id, p.policy_id),
            )
        writer.accept(transition)
        state = transition.state
        sampled = state.tick % p.policy.sample_ticks == 0
        checkpoint_due = state.tick % p.policy.checkpoint_ticks == 0
        if sampled:
            writer.sample(state)
            if writer.full or checkpoint_due or state.tick == p.policy.final_tick:
                yield from flush()
            if checkpoint_due:
                yield ProducedResourceEvent(
                    context.session_id,
                    next_sequence(),
                    checkpoint_resource(p, source, implementation, writer, state),
                )
                last_checkpoint = state.tick
        if state.step % p.policy.preview_every == 0 or state.tick == p.policy.final_tick:
            yield ProgressEvent(
                context.session_id,
                next_sequence(),
                p.policy.time(state.tick),
                p.policy.time(p.policy.final_tick),
                f"Accepted step {state.step}; {len(state.mesh.cells)} cells; "
                f"epoch {state.epoch}; t={p.policy.time(state.tick):.9g} s",
            )
    state = writer.discard_unsampled()
    yield from flush()
    if last_checkpoint != state.tick:
        yield ProducedResourceEvent(
            context.session_id,
            next_sequence(),
            checkpoint_resource(p, source, implementation, writer, state),
        )
    mass = p.area * float(state.mesh.widths @ state.values)
    for name, value, label in (
        ("time", quantity(p.policy.time(state.tick)), "Last retained accepted physical time"),
        ("mass", quantity(mass, "kilogram"), "Retained concentration integral"),
        (
            "mass_residual",
            (mass - state.initial_mass) / max(state.initial_mass, 1e-300),
            "Normalized whole-run mass residual",
        ),
        ("cells", len(state.mesh.cells), "Cells in the retained support"),
        ("work", state.work, "Solve, indicator and transfer work through the retained sample"),
    ):
        yield ObservationEvent(
            context.session_id,
            EvidenceObservation(
                name,
                (p.problem_id, p.field_id, p.region_id, p.policy_id),
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
