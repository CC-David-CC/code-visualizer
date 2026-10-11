"""The selected gas participant uses the existing host-owned worker lifecycle."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import asdict
from hashlib import sha256
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
from code_visualizer.domain.values import ResourceReference
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
from code_visualizer.extensions.fields.arrays import array_resource
from code_visualizer.extensions.hybrid_gas.calibration import transport
from code_visualizer.extensions.hybrid_gas.domain import BACKEND_ID, REPRESENTATION
from code_visualizer.extensions.hybrid_gas.preview import PREVIEW_TYPE, event, validate_preview
from code_visualizer.extensions.hybrid_gas.problem import (
    GasError,
    definition_digest,
    derive_problem,
)
from code_visualizer.extensions.hybrid_gas.records import (
    CHECKPOINT_TYPE,
    STATISTICS_TYPE,
    GasStatistics,
)
from code_visualizer.extensions.hybrid_gas.units import quantity
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.computation_resources import produced_descriptor


def gas_backend() -> RegisteredBackend:
    return RegisteredBackend(
        BackendDefinition(
            BACKEND_ID,
            "1",
            "Bounded argon state/flux computation",
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
        checkpoint=CheckpointContract(CHECKPOINT_TYPE, "checkpoint"),
        file_backed_inputs=True,
        cancellation_grace_seconds=10.0,
        preview=PreviewContract(PREVIEW_TYPE, validate_preview),
    )


def stream(snapshot: PreparedComputation, context: BackendContext) -> Iterator[BackendUpdate]:
    try:
        yield from integrate(snapshot, context)
    except GasError as exc:
        yield BackendResult(
            ComputationOutcome.FAILED,
            diagnostics=(EvidenceDiagnostic(exc.code, str(exc), (exc.object_id,)),),
        )
    except (ImportError, OSError, ValueError, KeyError, FloatingPointError, OverflowError) as exc:
        code = str(exc).split(":", 1)[0]
        if not code.startswith("GAS_") or len(code) > 80:
            code = (
                "GAS_DEPENDENCY_MISSING" if isinstance(exc, ImportError) else "GAS_INPUT_OR_NUMERIC"
            )
        yield BackendResult(
            ComputationOutcome.FAILED,
            diagnostics=(
                EvidenceDiagnostic(
                    code,
                    str(exc),
                    (snapshot.request.model_id,) if snapshot.request.model_id else (),
                ),
            ),
        )


def integrate(snapshot: PreparedComputation, context: BackendContext) -> Iterator[BackendUpdate]:
    import numpy as np

    from code_visualizer.extensions.hybrid_gas.checkpoint import (
        checkpoint_resource,
        method_digest,
        restore,
    )
    from code_visualizer.extensions.hybrid_gas.runtime import GasRuntime
    from code_visualizer.extensions.hybrid_gas.writer import GasWriter, record_resource

    if not isinstance(snapshot.value, DomainModel):
        raise ValueError("GAS_INPUT: requires one intentional gas definition")
    configuration = {p.name: p.value for p in snapshot.request.configuration}
    if set(configuration) - {"checkpoint"}:
        raise ValueError(
            "GAS_CONFIGURATION: physical and numerical policy belong to authored input"
        )
    p = derive_problem(snapshot.project, snapshot.value)
    if snapshot.request.seed is not None and snapshot.request.seed != p.policy.seed:
        raise GasError(
            "GAS_SEED", "The request cannot replace the frozen authored seed", p.policy_id
        )
    calibrated = transport(snapshot, p.calibration)
    law = calibrated.law
    source, method = definition_digest(snapshot), method_digest()
    law_digest = sha256(canonical_data_bytes(asdict(law))).hexdigest()
    # A comparison fingerprint excludes numerical choices, seed and slab
    # placement, while retaining the entire physical initial/boundary meaning.
    physical = sha256(
        canonical_data_bytes(
            {
                "law": asdict(law),
                "calibration": p.calibration.content_hash,
                "space": p.space_id,
                "frame": p.frame_id,
                "axis": p.axis_id,
                "height": p.grid.length,
                "area": p.grid.area,
                "density": p.number_density,
                "temperature": p.temperature,
                "velocity": list(p.velocity),
                "sine_amplitude": p.sine_amplitude,
                "walls": [asdict(w) for w in p.walls],
            }
        )
    ).hexdigest()
    roots = ceil((p.policy.final_tick // p.policy.sample_ticks + 1) / p.policy.chunk_rows)
    roots += 2 * ceil(p.policy.final_tick / p.policy.checkpoint_ticks) + 8
    require_publication_capacity(
        snapshot, context.session_id, roots, p.origins, artifact_text_bytes=512
    )
    sequence = 0

    def next_sequence() -> int:
        nonlocal sequence
        current, sequence = sequence, sequence + 1
        return current

    reference = configuration.get("checkpoint")
    replayed = 0
    if reference is None:
        runtime = GasRuntime(p, law, source, law_digest)
        writer = GasWriter(p, source, runtime)
    else:
        if not isinstance(reference, ResourceReference):
            raise GasError(
                "GAS_CHECKPOINT_TYPE", "Select an explicit checkpoint resource", p.policy_id
            )
        runtime, writer, replayed = yield from restore(
            snapshot,
            reference,
            p,
            law,
            source,
            method,
            law_digest,
            context.session_id,
            lambda: context.cancellation_requested,
            next_sequence,
        )

    def flush() -> Iterator[BackendUpdate]:
        for resource in writer.flush():
            yield ProducedResourceEvent(context.session_id, next_sequence(), resource)

    def checkpoint() -> Iterator[BackendUpdate]:
        yield ProducedResourceEvent(
            context.session_id,
            next_sequence(),
            checkpoint_resource(runtime, writer, source, method),
        )
        writer.checkpoint_acknowledged()

    with runtime:
        if reference is None:
            writer.sample_state(runtime.state)
            yield from flush()
            yield from checkpoint()
        last_checkpoint = runtime.state.tick
        while runtime.state.tick < p.policy.final_tick:
            # Cancellation finishes at the next scheduled sample, so it does
            # not add/remove scientific output positions. The host owns a
            # finite deadline and preserves the earlier ACK if termination wins.
            if context.cancellation_requested and runtime.state.tick % p.policy.sample_ticks == 0:
                break
            transition = runtime.advance()
            writer.accept(transition)
            state = runtime.state
            if state.windows % p.policy.preview_windows == 0:
                yield event(
                    p,
                    transition,
                    context.session_id,
                    next_sequence(),
                    source,
                    snapshot.input_digest,
                )
                yield ProgressEvent(
                    context.session_id,
                    next_sequence(),
                    float(state.tick),
                    float(p.policy.final_tick),
                    f"Accepted gas window {state.windows}; t={state.tick * p.policy.quantum:.9g} s",
                )
            if state.tick % p.policy.sample_ticks == 0:
                writer.sample_state(state)
                if (
                    writer.full
                    or state.tick % p.policy.checkpoint_ticks == 0
                    or state.tick == p.policy.final_tick
                ):
                    yield from flush()
                if state.tick % p.policy.checkpoint_ticks == 0:
                    yield from checkpoint()
                    last_checkpoint = state.tick
        yield from flush()
        state = runtime.state
        if last_checkpoint != state.tick:
            yield from checkpoint()
        if state.observations:
            blocks = array_resource("independent-replica-blocks", np.stack(state.observations))
            statistics = GasStatistics(
                source,
                physical,
                writer.interpretation,
                produced_descriptor(blocks).reference,
                len(state.observations),
                p.policy.seed,
                p.policy.warmup_ticks,
                p.policy.block_ticks,
            )
            yield ProducedResourceEvent(
                context.session_id,
                next_sequence(),
                record_resource(
                    "replica-statistics",
                    statistics,
                    STATISTICS_TYPE,
                    p.origins,
                    (blocks,),
                ),
            )
        for name, value, title in (
            (
                "time",
                quantity(state.tick * p.policy.quantum, "second"),
                "Last retained physical time",
            ),
            (
                "conservation",
                float(np.max(state.maximum_residual)),
                "Maximum five-component normalized conservation residual",
            ),
            (
                "viscosity",
                quantity(law.reference_viscosity, "pascal_second"),
                "Independently calibrated viscosity",
            ),
            (
                "viscosity_half_width",
                quantity(calibrated.half_width_95, "pascal_second"),
                "Independent calibration 95% half-width",
            ),
            ("particle_steps", state.particle_steps, "Accepted microscopic work"),
            ("continuum_work", state.continuum_unknowns, "Actual continuum stage unknowns"),
            ("reconstruction_windows", replayed, "Additional charged reconstruction windows"),
        ):
            yield ObservationEvent(
                context.session_id,
                EvidenceObservation(name, p.origins, value, title, sequence=next_sequence()),
            )
        if (
            p.policy.mode == "adaptive"
            and state.model.particle
            and not context.cancellation_requested
        ):
            raise GasError(
                "GAS_RETURN_INSUFFICIENT_FIDELITY",
                "The bounded run did not establish a valid return to the coarse model",
                p.policy_id,
            )
        yield BackendResult(
            ComputationOutcome.CANCELLED
            if context.cancellation_requested
            else ComputationOutcome.SUCCEEDED
        )
