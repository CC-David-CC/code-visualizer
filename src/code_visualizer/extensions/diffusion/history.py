"""Spatial diffusion interpretation over the shared bounded history writer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from code_visualizer.execution.backends import ProducedResource
from code_visualizer.extensions.diffusion.domain import quantity
from code_visualizer.extensions.diffusion.problem import DiffusionProblem
from code_visualizer.extensions.fields.arrays import array_resource
from code_visualizer.extensions.fields.codec import encode_record
from code_visualizer.extensions.fields.records import (
    INTERPRETATION_TYPE,
    SERIES_TYPE,
    SUPPORT_TYPE,
    FieldInterpretation,
    FieldSeries,
    SampleChunk,
    UniformSupport,
)
from code_visualizer.extensions.foundations.series_writer import NumericSeriesWriter
from code_visualizer.persistence.computation_resources import produced_descriptor

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

    from code_visualizer.extensions.fields.history import FieldHistory


def metadata(
    identity: str, record: UniformSupport | FieldInterpretation | FieldSeries, logical_type: object
) -> ProducedResource:
    from code_visualizer.domain.resources import ResourceLogicalTypeReference

    assert isinstance(logical_type, ResourceLogicalTypeReference)
    return ProducedResource(
        identity, encode_record(record), "application/json", logical_type=logical_type
    )


class HistoryWriter(NumericSeriesWriter[SampleChunk, FieldSeries]):
    def __init__(
        self,
        problem: DiffusionProblem,
        source_digest: str,
        coordinates: NDArray[np.float64],
        previous: FieldHistory | None = None,
    ):
        self.problem = problem
        staged: tuple[ProducedResource, ...] = ()
        if previous is not None:
            interpretation = previous.series.interpretation
        else:
            coords = array_resource("coordinates", coordinates)
            support = metadata(
                "support",
                UniformSupport(
                    problem.space_id,
                    problem.frame_id,
                    problem.axis_id,
                    problem.axis_name,
                    quantity(0.0, "meter"),
                    quantity(problem.dx, "meter"),
                    problem.nodes,
                    produced_descriptor(coords).reference,
                ),
                SUPPORT_TYPE,
            )
            meaning = metadata(
                "interpretation",
                FieldInterpretation(
                    problem.field_id,
                    produced_descriptor(support).reference,
                    problem.unit,
                    problem.quantity_kind,
                ),
                INTERPRETATION_TYPE,
            )
            interpretation = produced_descriptor(meaning).reference
            staged = (coords, support, meaning)
        super().__init__(
            interpretation,
            source_digest,
            problem.nodes,
            problem.chunk_rows,
            lambda step: quantity(problem.time(step)),
            SampleChunk,
            FieldSeries,
            encode_record,
            SERIES_TYPE,
            (problem.field_id,),
            "Accepted field",
            staged=staged,
            prefix=previous.root if previous else None,
            prefix_last=previous.series.last if previous else None,
        )
