"""Exact complete-input reconstruction, verified before continuation is admitted."""

from __future__ import annotations

from collections.abc import Callable, Generator
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

from code_visualizer.domain.computation import ProgressEvent
from code_visualizer.domain.values import ResourceReference
from code_visualizer.execution.backends import BackendUpdate, PreparedComputation, ProducedResource
from code_visualizer.extensions.fields.arrays import array_resource, read_array
from code_visualizer.extensions.hybrid_gas.history import GasHistory, record
from code_visualizer.extensions.hybrid_gas.native_api import BINARY_SHA, COLLISION_SHA, SPECIES_SHA
from code_visualizer.extensions.hybrid_gas.problem import GasError, GasProblem
from code_visualizer.extensions.hybrid_gas.records import (
    CHECKPOINT_TYPE,
    TAPE_TYPE,
    GasCheckpoint,
    GasTape,
)
from code_visualizer.extensions.hybrid_gas.runtime import GasRuntime
from code_visualizer.extensions.hybrid_gas.thermodynamics import GasLaw
from code_visualizer.extensions.hybrid_gas.writer import GasWriter, record_resource
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.computation_resources import produced_descriptor

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


def method_digest() -> str:
    import platform
    import sys

    import numpy as np
    import scipy  # type: ignore[import-untyped]

    package = Path(__file__).parent
    # Source is shipped as package data in the frozen worker as well. Hash the
    # installed implementation, never project-authored source or import paths.
    sources = {p.name: sha256(p.read_bytes()).hexdigest() for p in sorted(package.glob("*.py"))}
    if not {"runtime.py", "participant.py", "continuum.py", "native_api.py"} <= set(sources):
        raise ValueError(
            "GAS_IMPLEMENTATION_IDENTITY: installed implementation sources are missing"
        )
    return sha256(
        canonical_data_bytes(
            {
                "method": "sparta_v3_exact_complete_input_reconstruction_ssprk2_v1",
                "sources": dict(sources),
                "python": list(sys.version_info[:3]),
                "platform": platform.system() + ":" + platform.machine(),
                "numpy": np.__version__,
                "scipy": scipy.__version__,
                "byte_order": sys.byteorder,
                "native": [BINARY_SHA, SPECIES_SHA, COLLISION_SHA],
            }
        )
    ).hexdigest()


def accumulators(runtime: GasRuntime) -> NDArray[np.float64]:
    import numpy as np

    s = runtime.state
    return np.concatenate(
        (
            runtime.initial_total,
            s.wall_total,
            s.maximum_residual,
            s.statistics_sum.ravel(),
            s.moments_sum.ravel(),
            s.observation_sum.ravel(),
            s.observation_flux.ravel(),
            np.array([s.observation_shear]),
        )
    )


def checkpoint_resource(
    runtime: GasRuntime, writer: GasWriter, source: str, method: str
) -> ProducedResource:
    import numpy as np

    s, p = runtime.state, runtime.problem
    if (
        writer.root is None
        or writer.pending
        or writer.last is None
        or (writer.last.step != s.tick or writer.sampled_state is not s)
    ):
        raise ValueError("GAS_CHECKPOINT_BOUNDARY: acknowledge the exact sampled state first")
    tape = writer.tape_resource()
    dependencies: list[ProducedResource] = []
    for root in (tape, *writer.transfer_staged):
        dependencies.extend(root.dependencies)
        dependencies.append(replace(root, dependencies=()))

    def array(name: str, values: NDArray[np.float64]) -> ResourceReference:
        produced = array_resource(name, values)
        dependencies.append(produced)
        return produced_descriptor(produced).reference

    state = array("complete-gas-state", s.values)
    counters = array("complete-gas-accumulators", accumulators(runtime))
    means = array("regime-means", np.stack(s.means).reshape(len(s.means), -1)) if s.means else None
    moments = (
        array(
            "particle-statistical-blocks",
            np.stack(s.moment_blocks).reshape(len(s.moment_blocks), -1),
        )
        if s.moment_blocks
        else None
    )
    observations = (
        array("gas-observation-blocks", np.stack(s.observations)) if s.observations else None
    )
    native = runtime.native.native.observation() if runtime.native else None
    native_ref = array("complete-native-observation-v3", native) if native is not None else None
    decisions = array("model-decisions", np.stack(writer.decisions)) if writer.decisions else None
    saved = GasCheckpoint(
        source,
        method,
        writer.root,
        produced_descriptor(replace(tape, dependencies=())).reference,
        state,
        counters,
        means,
        moments,
        observations,
        native_ref,
        decisions,
        tuple(writer.transfers),
        s.tick,
        s.windows,
        s.model,
        len(s.means),
        len(s.moment_blocks),
        len(s.observations),
        len(native) if native is not None else 0,
        len(writer.decisions),
        s.particle_steps,
        s.continuum_unknowns,
    )
    return record_resource(
        f"checkpoint:{s.tick}", saved, CHECKPOINT_TYPE, p.origins, tuple(dependencies)
    )


def restore(
    snapshot: PreparedComputation,
    reference: ResourceReference,
    p: GasProblem,
    law: GasLaw,
    source: str,
    method: str,
    law_digest: str,
    session_id: str,
    cancelled: Callable[[], bool],
    next_sequence: Callable[[], int],
) -> Generator[BackendUpdate, None, tuple[GasRuntime, GasWriter, int]]:
    import numpy as np

    resources = {r.descriptor.reference: r for r in snapshot.resources}
    saved = record(resources.__getitem__, reference, GasCheckpoint, CHECKPOINT_TYPE)
    if saved.source_digest != source or saved.method_digest != method:
        raise GasError(
            "GAS_CHECKPOINT_COMPATIBILITY",
            "Frozen source or numerical implementation changed",
            p.policy_id,
        )
    if saved.tick > p.policy.final_tick or saved.tick % p.policy.window_ticks:
        raise GasError(
            "GAS_CHECKPOINT_TIME",
            "Checkpoint is outside the declared physical horizon",
            p.policy_id,
        )
    history = GasHistory(saved.history, resources.__getitem__, cache_bytes=0)
    try:
        if history.series.source_digest != source or history.series.last.step != saved.tick:
            raise GasError(
                "GAS_CHECKPOINT_HISTORY",
                "History does not end at the accepted boundary",
                p.policy_id,
            )
        last = history.gas_slice(history.sample_count - 1)
        state_values = read_array(resources[saved.state], (p.grid.cells, 5))
        if (
            not np.array_equal(last.conserved, state_values)
            or last.particle != saved.model.particle
        ):
            raise GasError(
                "GAS_CHECKPOINT_HISTORY",
                "Saved fields/ownership differ from their history",
                p.policy_id,
            )
        tape = record(resources.__getitem__, saved.tape, GasTape, TAPE_TYPE)
        if tape.source_digest != source:
            raise GasError(
                "GAS_CHECKPOINT_TAPE", "Native inputs belong to another frozen source", p.policy_id
            )
        expected_rows = (
            row
            for chunk in tape.chunks
            for row in read_array(resources[chunk.resource], (chunk.rows, 12))
        )
        runtime = GasRuntime(p, law, source, law_digest)
        writer = GasWriter(p, source, runtime)
        replayed = 0
        try:
            while runtime.state.tick < saved.tick:
                if cancelled():
                    raise GasError(
                        "GAS_RECONSTRUCTION_CANCELLED",
                        "Reconstruction cancelled before continuation",
                        p.policy_id,
                    )
                transition = runtime.advance()
                if transition.input_row is not None:
                    expected = next(expected_rows, None)
                    if expected is None or not np.array_equal(expected, transition.input_row):
                        raise GasError(
                            "GAS_CHECKPOINT_TAPE",
                            "Reconstructed reservoir inputs differ",
                            p.slab_id,
                        )
                writer.accept(transition)
                replayed += 1
                if replayed % p.policy.preview_windows == 0:
                    yield ProgressEvent(
                        session_id,
                        next_sequence(),
                        float(runtime.state.tick),
                        float(saved.tick),
                        f"Reconstructing accepted prefix: {runtime.state.tick}/{saved.tick} ticks",
                    )
            if next(expected_rows, None) is not None:
                raise GasError(
                    "GAS_CHECKPOINT_TAPE", "Native input tape has an unconsumed suffix", p.slab_id
                )
            s = runtime.state
            if (
                s.model != saved.model
                or s.windows != saved.windows
                or s.particle_steps != saved.particle_steps
                or s.continuum_unknowns != saved.continuum_unknowns
                or tuple(writer.transfers) != saved.transfers
            ):
                raise GasError(
                    "GAS_CHECKPOINT_CONTROLLER",
                    "Reconstructed controller/transfer history differs",
                    p.policy_id,
                )

            def identical(
                reference: ResourceReference | None, actual: NDArray[np.float64] | None
            ) -> None:
                if (reference is None) != (actual is None):
                    raise GasError(
                        "GAS_CHECKPOINT_STATE", "Complete accepted state is missing", p.policy_id
                    )
                if reference is not None and actual is not None:
                    expected = read_array(resources[reference], actual.shape)
                    if not np.array_equal(expected, actual):
                        raise GasError(
                            "GAS_CHECKPOINT_STATE",
                            "Complete reconstructed state differs",
                            p.policy_id,
                        )

            identical(saved.state, s.values)
            identical(saved.accumulators, accumulators(runtime))
            identical(saved.means, np.stack(s.means).reshape(len(s.means), -1) if s.means else None)
            identical(
                saved.moment_blocks,
                np.stack(s.moment_blocks).reshape(len(s.moment_blocks), -1)
                if s.moment_blocks
                else None,
            )
            identical(saved.observations, np.stack(s.observations) if s.observations else None)
            native = runtime.native.native.observation() if runtime.native else None
            if (len(native) if native is not None else 0) != saved.native_length:
                raise GasError(
                    "GAS_CHECKPOINT_COUNT", "Saved native state length differs", p.policy_id
                )
            identical(saved.native, native)
            identical(saved.decisions, np.stack(writer.decisions) if writer.decisions else None)
            if (len(s.means), len(s.moment_blocks), len(s.observations), len(writer.decisions)) != (
                saved.mean_count,
                saved.moment_count,
                saved.observation_count,
                saved.decision_count,
            ):
                raise GasError(
                    "GAS_CHECKPOINT_COUNT",
                    "Saved observation/controller counts differ",
                    p.policy_id,
                )
            # Keep the already acknowledged physical resource partition. Replay
            # recomputes meaning, never rewrites retained history or input bytes.
            writer.root = saved.history
            writer.last = history.series.last
            writer.prefix = history.series.prefix
            writer.prefix_last = history.series.prefix_last
            writer.entries = list(history.series.chunks)
            writer.samples = history.sample_count
            writer.sampled_state = s
            writer.staged.clear()
            writer.tape_chunks = list(tape.chunks)
            writer.tape_pending.clear()
            writer.tape_staged.clear()
            writer.transfer_staged.clear()
            return runtime, writer, replayed
        except BaseException:
            runtime.close()
            raise
    finally:
        history.close()
