"""One ordinary streaming worker owns the bounded coupled computation."""

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
from code_visualizer.extensions.channels.preview import (
    PREVIEW_TYPE,
    ChannelPreview,
    validate_preview,
)
from code_visualizer.extensions.electrothermal.checkpoint import (
    CHECKPOINT_TYPE,
    checkpoint_resource,
    restore,
)
from code_visualizer.extensions.electrothermal.domain import (
    BACKEND_ID,
    CHECKPOINT_PARAMETER,
    REPRESENTATION,
    SCHEMA_ID,
)
from code_visualizer.extensions.electrothermal.history import HistoryWriter, values
from code_visualizer.extensions.electrothermal.numerics import (
    CoupledSolver,
    WindowCancelled,
    WindowIdentity,
)
from code_visualizer.extensions.electrothermal.problem import (
    CouplingError,
    definition_digest,
    derive_problem,
)
from code_visualizer.extensions.electrothermal.units import quantity
from code_visualizer.extensions.foundations.units import UnitError


def electrothermal_backend() -> RegisteredBackend:
    return RegisteredBackend(
        BackendDefinition(
            BACKEND_ID,
            "1",
            "Coupled electrothermal backward Euler",
            REPRESENTATION,
            SCHEMA_ID,
            "1",
            "Fixed windows, full accepted-base rollback, "
            "coherent circuit/temperature/energy outputs.",
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
        preview=PreviewContract(PREVIEW_TYPE, validate_preview),
        checkpoint=CheckpointContract(CHECKPOINT_TYPE, CHECKPOINT_PARAMETER),
        file_backed_inputs=True,
    )


def stream(snapshot: PreparedComputation, context: BackendContext) -> Iterator[BackendUpdate]:
    try:
        yield from integrate(snapshot, context)
    except CouplingError as exc:
        yield BackendResult(
            ComputationOutcome.FAILED,
            diagnostics=(EvidenceDiagnostic(exc.code, str(exc), (exc.object_id,)),),
        )
    except UnitError as exc:
        yield BackendResult(
            ComputationOutcome.FAILED,
            diagnostics=(
                EvidenceDiagnostic(
                    exc.issue.code,
                    exc.issue.message,
                    (exc.issue.object_id,)
                    if exc.issue.object_id
                    else ((snapshot.request.model_id,) if snapshot.request.model_id else ()),
                ),
            ),
        )
    except ImportError as exc:
        yield BackendResult(
            ComputationOutcome.FAILED,
            diagnostics=(EvidenceDiagnostic("SCIENCE_DEPENDENCY_MISSING", str(exc)),),
        )
    except (ValueError, KeyError, FloatingPointError, OverflowError) as exc:
        yield BackendResult(
            ComputationOutcome.FAILED,
            diagnostics=(EvidenceDiagnostic("COUPLING_INPUT_OR_NUMERIC", str(exc)),),
        )


def integrate(snapshot: PreparedComputation, context: BackendContext) -> Iterator[BackendUpdate]:
    if not isinstance(snapshot.value, DomainModel):
        raise ValueError("Coupling requires intentional domain input")
    configuration = {item.name: item.value for item in snapshot.request.configuration}
    if set(configuration) - {CHECKPOINT_PARAMETER}:
        raise CouplingError(
            "COUPLING_CONFIGURATION",
            "This adapter requires authored configuration",
            snapshot.value.id,
        )
    p = derive_problem(snapshot.project, snapshot.value)
    source = definition_digest(snapshot)
    solver = CoupledSolver(snapshot, p, source)
    reference = configuration.get(CHECKPOINT_PARAMETER)
    previous = None
    if reference is not None:
        if not isinstance(reference, ResourceReference):
            raise CouplingError(
                "COUPLING_CHECKPOINT_TYPE", "Resume requires an explicit resource", p.id
            )
        previous, state = restore(snapshot, reference, p, source, solver)
    else:
        state = solver.initial()
    circuit = solver.electrical(
        WindowIdentity(source, state.step, p.time(state.step)),
        p.ambient_temperature + state.resistor_rise,
    )
    writer = HistoryWriter(p, source, previous)
    sampled_values = (
        previous.slice(previous.sample_count - 1).values if previous else values(p, state, circuit)
    )
    if previous is not None:
        previous.close()
    from code_visualizer.execution.publication_budget import require_publication_capacity

    remaining = p.windows - state.step
    samples = ceil(remaining / p.sample_every) + ceil(remaining / p.checkpoint_every) + 2
    checkpoints = ceil(remaining / p.checkpoint_every) + 2
    roots = ceil(samples / p.chunk_rows) + checkpoints + 2
    try:
        require_publication_capacity(
            snapshot, context.session_id, roots + checkpoints, p.origins, artifact_text_bytes=512
        )
    except ValueError as exc:
        raise CouplingError("COUPLING_OUTPUT_BUDGET", str(exc), p.policy_id) from exc
    sequence = 0

    def next_sequence() -> int:
        nonlocal sequence
        sequence += 1
        return sequence

    def flush() -> Iterator[BackendUpdate]:
        for produced in writer.flush():
            yield ProducedResourceEvent(context.session_id, next_sequence(), produced)

    def checkpoint() -> Iterator[BackendUpdate]:
        yield ProducedResourceEvent(
            context.session_id,
            next_sequence(),
            checkpoint_resource(p, source, solver.numerical_identity, writer, sampled_state),
        )

    sampled_state = state
    if previous is None:
        writer.sample(0, sampled_values)
        yield from flush()
        yield from checkpoint()
    last_checkpoint = state.step
    iterations = rejected = 0
    last_trial = None
    try:
        for _step in range(state.step + 1, p.windows + 1):
            base_values = tuple(float(v) for v in values(p, state, circuit)[:9])
            for trial in solver.trials(state, context):
                iterations += 1
                if _step % p.preview_every == 0 or _step == p.windows:
                    # The trial exposes coherent endpoint channels, but neither
                    # accepted energy nor the retained sample cursor advances.
                    x, y = trial.thermal.resistor_rise, trial.thermal.sink_rise
                    point = trial.electrical
                    contact = p.contact_conductance * (x - y)
                    candidate = (
                        x + p.ambient_temperature,
                        y + p.ambient_temperature,
                        point.resistance,
                        point.voltage,
                        point.current,
                        point.power,
                        contact,
                        -contact,
                        p.ambient_conductance * y,
                    )
                    yield ChannelPreview(
                        writer.interpretation,
                        source,
                        state.step,
                        quantity(p.time(state.step)),
                        _step,
                        quantity(p.time(_step)),
                        trial.iteration,
                        TensorValue(TensorDType.INT64, (9,), tuple(range(9))),
                        TensorValue(TensorDType.FLOAT64, (9,), base_values),
                        TensorValue(TensorDType.FLOAT64, (9,), candidate),
                    ).event(context.session_id, next_sequence(), snapshot.input_digest, p.id)
                if not trial.converged:
                    rejected += 1
                    continue
                state, circuit, last_trial = solver.accept(trial), trial.electrical, trial
            due = state.step % p.checkpoint_every == 0
            if state.step % p.sample_every == 0 or due or state.step == p.windows:
                sampled_values = values(p, state, circuit, last_trial)
                writer.sample(state.step, sampled_values)
                sampled_state = state
            if writer.full or due or state.step == p.windows:
                yield from flush()
            if due:
                yield from checkpoint()
                last_checkpoint = state.step
            if state.step % p.preview_every == 0 or state.step == p.windows:
                yield ProgressEvent(
                    context.session_id,
                    next_sequence(),
                    p.time(state.step),
                    p.duration,
                    f"Accepted coupled window {state.step}/{p.windows}",
                )
    except WindowCancelled:
        pass
    # Cancellation never inserts an unscheduled accepted sample.
    yield from flush()
    if last_checkpoint != sampled_state.step:
        yield from checkpoint()
    retained = sampled_values
    for channel, number in zip(writer.meaning.channels, retained, strict=True):
        yield ObservationEvent(
            context.session_id,
            EvidenceObservation(
                channel.id,
                channel.semantic_ids,
                QuantityValue(float(number), channel.unit),
                channel.name,
                sequence=next_sequence(),
            ),
        )
    for name, number in (("iterations", iterations), ("rejected_trials", rejected)):
        yield ObservationEvent(
            context.session_id,
            EvidenceObservation(
                name, (p.policy_id,), number, name.replace("_", " "), sequence=next_sequence()
            ),
        )
    yield BackendResult(
        ComputationOutcome.CANCELLED
        if context.cancellation_requested
        else ComputationOutcome.SUCCEEDED
    )
