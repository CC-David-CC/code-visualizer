"""History, decisions and native input tape use existing resource publication ACKs."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.values import ResourceReference
from code_visualizer.execution.backends import ProducedResource
from code_visualizer.extensions.fields.arrays import array_resource
from code_visualizer.extensions.foundations.series_writer import NumericSeriesWriter
from code_visualizer.extensions.hybrid_gas.model_transfer import Activation, CoarseReturn
from code_visualizer.extensions.hybrid_gas.policy import ModelDecision
from code_visualizer.extensions.hybrid_gas.problem import GasProblem
from code_visualizer.extensions.hybrid_gas.records import (
    CODEC,
    HISTORY_TYPE,
    INTERPRETATION_TYPE,
    TAPE_TYPE,
    TRANSFER_TYPE,
    GasChunk,
    GasInterpretation,
    GasSeries,
    GasTape,
    GasTransfer,
    TapeChunk,
)
from code_visualizer.extensions.hybrid_gas.runtime import GasAdvance, GasRuntime, GasState
from code_visualizer.extensions.hybrid_gas.units import quantity
from code_visualizer.persistence.computation_resources import produced_descriptor

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


def record_resource(
    label: str,
    record: object,
    logical_type: ResourceLogicalTypeReference,
    origins: tuple[str, ...],
    dependencies: tuple[ProducedResource, ...] = (),
) -> ProducedResource:
    return ProducedResource(
        label,
        CODEC.encode(record),
        "application/json",
        origins,
        label,
        logical_type=logical_type,
        dependencies=dependencies,
    )


def interpretation(p: GasProblem) -> GasInterpretation:
    return GasInterpretation(
        p.problem_id,
        p.region_id,
        p.slab_id,
        p.policy_id,
        p.space_id,
        p.frame_id,
        p.axis_id,
        p.field_ids,
        (
            quantity(1, "kilogram_per_cubic_meter").unit,
            *(quantity(1, "momentum_per_volume").unit for _ in range(3)),
            quantity(1, "joule_per_cubic_meter").unit,
        ),
        quantity(p.grid.length, "meter"),
        quantity(p.grid.area, "square_meter"),
        quantity(p.policy.quantum, "second"),
        p.grid.cells,
        p.slab.first_cell,
        p.slab.stop_cell,
    )


def transfer_resource(
    p: GasProblem,
    source: str,
    support: ResourceReference,
    tick: int,
    before: NDArray[np.float64],
    transfer: Activation | CoarseReturn,
) -> ProducedResource:
    import numpy as np

    dependencies: list[ProducedResource] = []

    def array(name: str, values: NDArray[np.float64]) -> ResourceReference:
        resource = array_resource(name, values)
        dependencies.append(resource)
        return produced_descriptor(resource).reference

    initial = isinstance(transfer, Activation)
    initial_state = array("model-transfer-before", before)
    after = array("model-transfer-after", transfer.after)
    if isinstance(transfer, Activation):
        moments = array("realized-particle-moments", transfer.realized_particle_moments)
        accounting = array(
            "initialization-accounting",
            np.stack(
                (
                    transfer.realized_difference,
                    transfer.exterior_density_correction,
                    transfer.normalized_residual,
                )
            ),
        )
        block_ref, uncertainty, count = None, None, 0
    else:
        moments = array("restricted-particle-moments", transfer.particle_moments)
        accounting = array(
            "restriction-accounting",
            np.stack(
                (
                    np.zeros(5),
                    np.zeros(5),
                    transfer.normalized_residual,
                )
            ),
        )
        count = len(transfer.block_moments)
        block_ref = array("retained-unresolved-moments", transfer.block_moments.reshape(count, -1))
        uncertainty = array(
            "return-uncertainty",
            np.stack(
                (
                    transfer.uncertainty.mean,
                    transfer.uncertainty.half_width,
                    transfer.uncertainty.effective_blocks,
                )
            ),
        )
    record = GasTransfer(
        source,
        support,
        p.policy_id,
        tick,
        "activation" if initial else "return",
        initial_state,
        after,
        moments,
        accounting,
        block_ref,
        count,
        uncertainty,
    )
    return record_resource(
        f"model-transfer:{tick}",
        record,
        TRANSFER_TYPE,
        (p.problem_id, p.slab_id, p.policy_id, *p.field_ids),
        tuple(dependencies),
    )


class GasWriter(NumericSeriesWriter[GasChunk, GasSeries]):
    def __init__(self, p: GasProblem, source: str, runtime: GasRuntime):
        self.problem = p
        self.support = interpretation(p)
        resource = record_resource(
            "gas-interpretation", self.support, INTERPRETATION_TYPE, p.origins
        )
        support_ref = produced_descriptor(resource).reference
        super().__init__(
            support_ref,
            source,
            self.support.width,
            p.policy.chunk_rows,
            lambda tick: quantity(tick * p.policy.quantum, "second"),
            GasChunk,
            GasSeries,
            CODEC.encode,
            HISTORY_TYPE,
            p.origins,
            "Conserved gas history",
            staged=(resource,),
        )
        self.tape_chunks: list[TapeChunk] = []
        self.tape_pending: list[NDArray[np.float64]] = []
        self.tape_staged: list[ProducedResource] = []
        self.decisions: list[NDArray[np.float64]] = []
        self.transfers: list[ResourceReference] = []
        self.transfer_staged: list[ProducedResource] = []
        self.sampled_state: GasState | None = None
        if runtime.initial_transfer is not None:
            self._transfer(0, runtime.initial_values, runtime.initial_transfer)
        if runtime.initial_decision is not None:
            self._decision(runtime.initial_decision, 0)

    def _transfer(
        self, tick: int, before: NDArray[np.float64], result: Activation | CoarseReturn
    ) -> None:
        resource = transfer_resource(
            self.problem, self.source_digest, self.interpretation, tick, before, result
        )
        self.transfers.append(produced_descriptor(replace(resource, dependencies=())).reference)
        self.transfer_staged.append(resource)

    def _decision(self, decision: ModelDecision, windows: int) -> None:
        import numpy as np

        actions = ("retain", "activate", "return", "reject")
        reasons = (
            "hysteresis",
            "gradient_threshold",
            "minimum_dwell",
            "insufficient_return_statistics",
            "coarse_compatible",
            "switch_budget",
        )
        self.decisions.append(
            np.array(
                [
                    decision.tick,
                    windows,
                    decision.indicator,
                    actions.index(decision.action),
                    reasons.index(decision.reason),
                    int(decision.before.particle),
                    int(decision.after.particle),
                    decision.after.low_count,
                    decision.after.switches,
                ],
                dtype=np.float64,
            )
        )

    def accept(self, advance: GasAdvance) -> None:
        if advance.input_row is not None:
            self.tape_pending.append(advance.input_row)
            if len(self.tape_pending) == 4096:
                self.seal_tape_chunk()
        if advance.decision is not None:
            self._decision(advance.decision, advance.after.windows)
        if advance.transfer is not None:
            self._transfer(advance.after.tick, advance.transfer.before, advance.transfer)

    def sample_state(self, state: GasState) -> None:
        import numpy as np

        if self.sample(state.tick, np.r_[float(state.model.particle), state.values.ravel()]):
            self.sampled_state = state

    def seal_tape_chunk(self) -> None:
        import numpy as np

        if not self.tape_pending:
            return
        if len(self.tape_chunks) >= 128:
            raise ValueError("GAS_TAPE_BUDGET: native inputs exceed the bounded closure")
        resource = array_resource(
            "native-inputs:" + str(len(self.tape_chunks)), np.stack(self.tape_pending)
        )
        self.tape_chunks.append(
            TapeChunk(produced_descriptor(resource).reference, len(self.tape_pending))
        )
        self.tape_staged.append(resource)
        self.tape_pending.clear()

    def tape_resource(self) -> ProducedResource:
        self.seal_tape_chunk()
        return record_resource(
            "complete-native-input-tape",
            GasTape(self.source_digest, tuple(self.tape_chunks)),
            TAPE_TYPE,
            (self.problem.slab_id, self.problem.policy_id),
            tuple(self.tape_staged),
        )

    def checkpoint_acknowledged(self) -> None:
        self.tape_staged.clear()
        self.transfer_staged.clear()
