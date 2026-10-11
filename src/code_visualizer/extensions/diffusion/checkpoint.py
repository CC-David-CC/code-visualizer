"""Portable numerical state, validated independently of a live solver process."""

from __future__ import annotations

from dataclasses import fields
from hashlib import sha256
from math import lcm
from typing import TYPE_CHECKING

from code_visualizer.domain.values import ResourceReference
from code_visualizer.execution.backends import PreparedComputation, ProducedResource
from code_visualizer.extensions.diffusion.domain import quantity
from code_visualizer.extensions.diffusion.problem import DiffusionProblem
from code_visualizer.extensions.fields.arrays import array_resource, read_array
from code_visualizer.extensions.fields.codec import decode_record, encode_record
from code_visualizer.extensions.fields.history import FieldHistory
from code_visualizer.extensions.fields.records import (
    CHECKPOINT_TYPE,
    METADATA_LIMIT,
    DiffusionCheckpoint,
)
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.computation_resources import produced_descriptor
from code_visualizer.persistence.values import canonical_value_to_data

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

    from code_visualizer.extensions.diffusion.history import HistoryWriter


def policy_digest(problem: DiffusionProblem) -> str:
    data = {
        item.name: getattr(problem, item.name)
        for item in fields(problem)
        if item.name not in ("unit", "quantity_kind")
    }
    from code_visualizer.domain.values import QuantityValue

    data["unit"] = canonical_value_to_data(QuantityValue(1.0, problem.unit))
    data["quantity_kind"] = problem.quantity_kind.value
    return sha256(canonical_data_bytes(data)).hexdigest()


def next_cursor(step: int, every: int) -> int:
    return (step // every + 1) * every


def checkpoint_resource(
    problem: DiffusionProblem,
    source_digest: str,
    numerical_identity: str,
    history: HistoryWriter,
    values: NDArray[np.float64],
) -> ProducedResource:
    if history.root is None or history.last is None or history.pending:
        raise ValueError("A checkpoint requires its acknowledged exact accepted history prefix")
    state = array_resource(f"state:{history.last.step}", values, unit=problem.unit)
    record = DiffusionCheckpoint(
        source_digest,
        history.interpretation,
        produced_descriptor(state).reference,
        history.root,
        history.last,
        numerical_identity,
        policy_digest(problem),
        next_cursor(history.last.step, problem.sample_every),
        next_cursor(history.last.step, problem.checkpoint_every),
    )
    return ProducedResource(
        f"checkpoint:{history.last.step}",
        encode_record(record),
        "application/json",
        (problem.problem_id, problem.field_id),
        f"Restart at accepted step {history.last.step}, t={problem.time(history.last.step):.9g} s",
        logical_type=CHECKPOINT_TYPE,
        dependencies=(state,),
    )


def restore(
    snapshot: PreparedComputation,
    reference: ResourceReference,
    problem: DiffusionProblem,
    source_digest: str,
    numerical_identity: str,
) -> tuple[FieldHistory, NDArray[np.float64]]:
    import numpy as np

    resources = {item.descriptor.reference: item for item in snapshot.resources}
    try:
        resolved = resources[reference]
    except KeyError as exc:
        raise ValueError(
            "DIFFUSION_CHECKPOINT_RESOURCE: checkpoint is absent from admitted input"
        ) from exc
    if (
        resolved.descriptor.logical_type != CHECKPOINT_TYPE
        or resolved.descriptor.media_type != "application/json"
        or resolved.descriptor.byte_size > METADATA_LIMIT
    ):
        raise ValueError("DIFFUSION_CHECKPOINT_TYPE: unsupported checkpoint resource")
    with resolved.open() as stream:
        record = decode_record(stream.read(METADATA_LIMIT + 1), DiffusionCheckpoint)
    if (
        record.compatibility_digest != source_digest
        or record.policy_digest != policy_digest(problem)
        or record.numerical_identity != numerical_identity
    ):
        raise ValueError(
            "DIFFUSION_CHECKPOINT_COMPATIBILITY: input, policy or numerical implementation changed"
        )
    position = record.position
    if (
        position.step > problem.steps
        or position.time != quantity(problem.time(position.step))
        or record.next_sample_step != next_cursor(position.step, problem.sample_every)
        or record.next_checkpoint_step != next_cursor(position.step, problem.checkpoint_every)
    ):
        raise ValueError(
            "DIFFUSION_CHECKPOINT_CURSOR: incompatible physical time or output schedule"
        )
    history = FieldHistory(record.prefix, resources.__getitem__, cache_bytes=0)
    try:
        support, interpretation = history.support, history.interpretation
        if (
            history.series.source_digest != source_digest
            or history.series.interpretation != record.interpretation
            or history.series.last != position
            or interpretation.field_id != problem.field_id
            or interpretation.unit != problem.unit
            or interpretation.quantity_kind != problem.quantity_kind
            or support.space_id != problem.space_id
            or support.frame_id != problem.frame_id
            or support.axis_id != problem.axis_id
            or support.axis_name != problem.axis_name
            or support.nodes != problem.nodes
            or support.origin != quantity(0.0, "meter")
            or support.spacing != quantity(problem.dx, "meter")
        ):
            raise ValueError("DIFFUSION_CHECKPOINT_INTERPRETATION: field, grid or frame changed")
        # Samples are the union of both authored schedules, plus the initial
        # and final states. Ordered rows alone do not prove complete coverage.
        expected_count = (
            1
            + position.step // problem.sample_every
            + position.step // problem.checkpoint_every
            - position.step // lcm(problem.sample_every, problem.checkpoint_every)
        )
        if (
            position.step == problem.steps
            and position.step % problem.sample_every
            and position.step % problem.checkpoint_every
        ):
            expected_count += 1
        if history.sample_count != expected_count:
            raise ValueError("DIFFUSION_CHECKPOINT_HISTORY: authored samples are missing")
        history.coordinates()
        state_resource = resources[record.state]
        if (
            state_resource.descriptor.tensor is None
            or state_resource.descriptor.tensor.unit != problem.unit
        ):
            raise ValueError("DIFFUSION_CHECKPOINT_UNIT: state vector has a different unit")
        state = read_array(state_resource, (problem.nodes,)).copy()
        if (
            state[0] != 0
            or state[-1] != 0
            or np.min(state) < -problem.scale * 1e-12
            or not np.array_equal(state, history.slice(position.sample).values)
        ):
            raise ValueError(
                "DIFFUSION_CHECKPOINT_STATE: vector disagrees with its accepted prefix/boundary"
            )
        # Validate each retained physical time against the exact fixed step policy.
        # Arrays stay bounded and are released between chunks.
        previous_step = -1
        for _chunk, values in history.iter_chunks():
            steps = values[:, 0]
            if (
                np.any(steps != np.floor(steps))
                or np.any(np.diff(steps) <= 0)
                or steps[0] <= previous_step
                or steps[-1] > position.step
                or np.any(
                    (steps % problem.sample_every != 0)
                    & (steps % problem.checkpoint_every != 0)
                    & (steps != problem.steps)
                )
                or not np.array_equal(values[:, 1], steps * problem.dt)
            ):
                raise ValueError(
                    "DIFFUSION_CHECKPOINT_HISTORY: retained physical coverage is invalid"
                )
            previous_step = int(steps[-1])
        return history, state
    except BaseException:
        history.close()
        raise
