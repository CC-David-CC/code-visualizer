"""Private sample buffers become retained only through the existing host's ACK."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.values import ResourceReference
from code_visualizer.execution.backends import ProducedResource
from code_visualizer.extensions.adaptive_diffusion.problem import AdaptiveProblem
from code_visualizer.extensions.adaptive_fields.codec import CellRecord, encode_record
from code_visualizer.extensions.adaptive_fields.history import AdaptiveHistory, mixed_array, record
from code_visualizer.extensions.adaptive_fields.mesh import Mesh
from code_visualizer.extensions.adaptive_fields.records import (
    DECISION_COLUMNS,
    DECISIONS_TYPE,
    HISTORY_TYPE,
    INTERPRETATION_TYPE,
    SUPPORT_TYPE,
    TRANSFER_TYPE,
    CellChunk,
    CellComponent,
    CellEpoch,
    CellHistory,
    CellInterpretation,
    CellSupport,
    CellTransfer,
    DecisionLog,
)
from code_visualizer.extensions.adaptive_fields.units import quantity
from code_visualizer.extensions.fields.arrays import array_resource
from code_visualizer.extensions.foundations.unit_algebra import QuantityKind
from code_visualizer.persistence.computation_resources import produced_descriptor

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

    from code_visualizer.extensions.adaptive_diffusion.controller import AcceptedState, Transition


def metadata(
    name: str, value: CellRecord, logical: ResourceLogicalTypeReference
) -> ProducedResource:
    return ProducedResource(name, encode_record(value), "application/json", logical_type=logical)


def interpretation_resources(p: AdaptiveProblem, mesh: Mesh) -> tuple[ProducedResource, ...]:
    import numpy as np

    lineage = array_resource(
        "lineage",
        np.array([(cell.base, cell.level, cell.offset) for cell in mesh.cells], dtype=np.float64),
    )
    support = metadata(
        "support",
        CellSupport(
            p.region_id,
            p.space_id,
            p.frame_id,
            p.axis_id,
            p.axis_name,
            quantity(p.length, "meter"),
            quantity(p.area, "square_meter"),
            mesh.base_cells,
            len(mesh.cells),
            produced_descriptor(lineage).reference,
        ),
        SUPPORT_TYPE,
    )
    meaning = CellInterpretation(
        p.field_id,
        produced_descriptor(support).reference,
        (CellComponent("concentration", p.field_id, p.unit, QuantityKind.LINEAR),),
    )
    return lineage, support, metadata("interpretation", meaning, INTERPRETATION_TYPE)


@dataclass(frozen=True, slots=True)
class _SampledBuffers:
    epochs: tuple[CellEpoch, ...]
    chunks: tuple[CellChunk, ...]
    pending: tuple[NDArray[np.float64], ...]
    staged: tuple[tuple[ResourceReference, ProducedResource], ...]
    decision_count: int
    samples: int


class AdaptiveWriter:
    def __init__(
        self,
        problem: AdaptiveProblem,
        source_digest: str,
        initial: AcceptedState,
        previous: AdaptiveHistory | None = None,
    ):
        self.problem, self.source_digest = problem, source_digest
        self.staged: dict[ResourceReference, ProducedResource] = {}
        self.known: set[ResourceReference] = set()
        self.pending: list[NDArray[np.float64]] = []
        self.decisions: list[tuple[float, ...]] = []
        self.epochs: list[CellEpoch] = []
        self.chunks: list[CellChunk] = []
        self.samples = 0
        self.root: ResourceReference | None = None
        self.acknowledged: CellHistory | None = None
        self.last_state = initial
        self.sampled_state = initial
        self._sampled_buffers: _SampledBuffers | None = None
        if previous is None:
            self.epochs.append(CellEpoch(0, 0, 0, self._interpretation(initial.mesh)))
        else:
            if previous.series.source_digest != source_digest:
                raise ValueError("A history continuation requires the same frozen definition")
            self.epochs = list(previous.series.epochs)
            self.chunks = list(previous.series.chunks)
            self.samples = previous.sample_count
            self.root, self.acknowledged = previous.root, previous.series
            self.known.update(dependency.reference for dependency in previous.series.dependencies())
            # Keep only inert, bounded decision rows; no live reader/solver is owned.
            if previous.series.decisions is not None:
                log = record(
                    previous.resolve, previous.series.decisions, DecisionLog, DECISIONS_TYPE
                )
                rows = mixed_array(previous.resolve, log.values, (log.rows, len(DECISION_COLUMNS)))
                self.decisions = [tuple(float(value) for value in row) for row in rows]
            self._remember_sample()

    def _remember_sample(self) -> None:
        self._sampled_buffers = _SampledBuffers(
            tuple(self.epochs),
            tuple(self.chunks),
            tuple(self.pending),
            tuple(self.staged.items()),
            len(self.decisions),
            self.samples,
        )

    def discard_unsampled(self) -> AcceptedState:
        """Cancellation rolls back private output buffers and controller state together."""
        boundary = self._sampled_buffers
        if boundary is None:
            raise ValueError("No complete scheduled sample exists")
        self.epochs, self.chunks = list(boundary.epochs), list(boundary.chunks)
        self.pending = list(boundary.pending)
        self.staged = {
            reference: value for reference, value in boundary.staged if reference not in self.known
        }
        self.decisions = self.decisions[: boundary.decision_count]
        self.samples = boundary.samples
        self.last_state = self.sampled_state
        return self.sampled_state

    def _stage(self, resource: ProducedResource) -> ResourceReference:
        reference = produced_descriptor(resource).reference
        if reference not in self.known:
            self.staged[reference] = resource
        return reference

    def _interpretation(self, mesh: Mesh) -> ResourceReference:
        resources = interpretation_resources(self.problem, mesh)
        for value in resources[:-1]:
            self._stage(value)
        return self._stage(resources[-1])

    def accept(self, transition: Transition) -> None:
        state = transition.state
        if state.step != self.last_state.step + 1 or state.tick <= self.last_state.tick:
            raise ValueError("Writer requires the next complete accepted state")
        self.decisions.extend(decision.row() for decision in transition.decisions)
        change = transition.change
        if change is not None:
            self._close_chunk()
            target = self._interpretation(change.after_mesh)
            before = self._stage(array_resource("transfer-before", change.before[:, None]))
            after = self._stage(array_resource("transfer-after", change.after[:, None]))
            indicators = self._stage(array_resource("indicators", change.indicators))
            scale = max(float(change.before_mesh.widths @ abs(change.before)), 1e-300)
            residual = (
                float(
                    change.after_mesh.widths @ change.after
                    - change.before_mesh.widths @ change.before
                )
                / scale
            )
            mapped = CellTransfer(
                self.problem.region_id,
                self.problem.policy_id,
                state.tick,
                state.step,
                quantity(self.problem.policy.quantum),
                self.epochs[-1].interpretation,
                target,
                before,
                after,
                indicators,
                (residual,),
            )
            mapping = self._stage(metadata("transfer", mapped, TRANSFER_TYPE))
            self.epochs.append(CellEpoch(state.epoch, state.tick, state.step, target, mapping))
        elif state.epoch != self.epochs[-1].index or state.mesh != self.last_state.mesh:
            raise ValueError("A changed support requires an explicit transfer")
        self.last_state = state

    def sample(self, state: AcceptedState) -> None:
        import numpy as np

        if (
            state.tick != self.samples * self.problem.policy.sample_ticks
            or state.tick != self.last_state.tick
            or state.step != self.last_state.step
            or state.epoch != self.epochs[-1].index
            or not np.array_equal(state.values, self.last_state.values)
        ):
            raise ValueError("Only the next scheduled complete state can become a sample")
        if self.full:
            raise ValueError("A full sample buffer must be published before continuing")
        row = np.r_[float(state.tick), float(state.step), state.values]
        row.setflags(write=False)
        self.pending.append(row)
        self.samples += 1
        self.sampled_state = state
        self._remember_sample()

    @property
    def full(self) -> bool:
        return len(self.pending) >= self.problem.policy.chunk_rows

    def _close_chunk(self) -> None:
        import numpy as np

        if not self.pending:
            return
        values = np.stack(self.pending)
        reference = self._stage(
            array_resource(f"samples:{self.samples - len(self.pending)}", values)
        )
        self.chunks.append(
            CellChunk(
                reference,
                self.epochs[-1].index,
                self.samples - len(self.pending),
                len(self.pending),
                int(values[0, 0]),
                int(values[-1, 0]),
                int(values[0, 1]),
                int(values[-1, 1]),
            )
        )
        self.pending.clear()

    def flush(self) -> Iterator[ProducedResource]:
        import numpy as np

        # Unsampled changes/controller advances must never decorate an older sample.
        if self.last_state.tick != self.sampled_state.tick:
            raise ValueError("Flush requires one coherent sampled support/controller boundary")
        self._close_chunk()
        decision_ref = None
        if self.decisions:
            array_ref = self._stage(
                array_resource("decision-values", np.array(self.decisions, dtype=np.float64))
            )
            log = DecisionLog(
                self.source_digest,
                self.problem.policy_id,
                quantity(self.problem.policy.quantum),
                len(self.decisions),
                array_ref,
            )
            decision_ref = self._stage(metadata("decisions", log, DECISIONS_TYPE))
        history = CellHistory(
            self.problem.field_id,
            self.source_digest,
            quantity(self.problem.policy.quantum),
            tuple(self.epochs),
            tuple(self.chunks),
            decision_ref,
        )
        if self.acknowledged is not None:
            history.extends(self.acknowledged)
            if history == self.acknowledged:
                self.staged.clear()
                return
        produced = replace(
            metadata(f"history:{self.samples - 1}", history, HISTORY_TYPE),
            semantic_ids=(self.problem.field_id, self.problem.problem_id, self.problem.policy_id),
            label="Accepted adaptive field through "
            f"t={self.problem.policy.time(self.sampled_state.tick):.9g} s",
            dependencies=tuple(self.staged.values()),
        )
        yield produced
        # Resumption means the existing host acknowledged the entire closure.
        self.known.update(self.staged)
        self.staged.clear()
        self.root, self.acknowledged = produced_descriptor(produced).reference, history
