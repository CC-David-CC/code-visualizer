"""Explicit changing-support history fixture, without an adaptive solver or editor."""

from dataclasses import replace

import numpy as np

from code_visualizer.execution.backends import ProducedResource, ResolvedResource
from code_visualizer.extensions.adaptive_fields.codec import encode_record
from code_visualizer.extensions.adaptive_fields.mesh import Mesh, transfer
from code_visualizer.extensions.adaptive_fields.records import (
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
)
from code_visualizer.extensions.adaptive_fields.units import quantity
from code_visualizer.extensions.fields.arrays import array_resource
from code_visualizer.extensions.foundations.unit_algebra import QuantityKind
from code_visualizer.persistence.computation_resources import produced_descriptor


class HistoryFixture:
    def __init__(self, *, cells=16):
        self.resources = {}
        self.records = {}
        base = Mesh.uniform("region", cells, 1.0)
        center = cells // 2
        refined = replace(
            base,
            cells=(*base.cells[:center], *base.cells[center].children(), *base.cells[center + 1 :]),
        )
        self.meshes = (base, refined, base)
        values = (1 + base.centers)[:, None]
        previous_values = values
        self.interpretations, self.supports, self.transfers, epochs, chunks = [], [], [], [], []
        for ordinal, mesh in enumerate(self.meshes):
            lineage = self.array(
                np.array([(c.base, c.level, c.offset) for c in mesh.cells], dtype=np.float64)
            )
            support = CellSupport(
                "region",
                "space",
                "frame",
                "axis",
                "x",
                quantity(1, "meter"),
                quantity(1, "square_meter"),
                cells,
                len(mesh.cells),
                lineage,
            )
            self.supports.append(support)
            support_ref = self.record(support, SUPPORT_TYPE)
            interpretation = CellInterpretation(
                "field",
                support_ref,
                (
                    CellComponent(
                        "concentration",
                        "field",
                        quantity(1, "kilogram_per_cubic_meter").unit,
                        QuantityKind.LINEAR,
                    ),
                ),
            )
            interpreted = self.record(interpretation, INTERPRETATION_TYPE)
            self.interpretations.append(interpreted)
            transfer_ref = None
            if ordinal:
                previous = self.meshes[ordinal - 1]
                values = transfer(previous, mesh, previous_values)
                residual = (mesh.widths @ values - previous.widths @ previous_values) / (
                    previous.widths @ abs(previous_values)
                )
                transfer_ref = self.record(
                    CellTransfer(
                        "region",
                        "policy",
                        2 * ordinal,
                        2 * ordinal,
                        quantity(0.1),
                        self.interpretations[ordinal - 1],
                        interpreted,
                        self.array(previous_values),
                        self.array(values),
                        self.array(np.zeros(len(previous.cells))),
                        tuple(float(v) for v in residual),
                    ),
                    TRANSFER_TYPE,
                )
                self.transfers.append(transfer_ref)
            epochs.append(CellEpoch(ordinal, 2 * ordinal, 2 * ordinal, interpreted, transfer_ref))
            block = np.tile(np.r_[0.0, 0.0, values.ravel()], (2, 1))
            block[:, 0] = block[:, 1] = np.arange(2 * ordinal, 2 * ordinal + 2)
            chunks.append(
                CellChunk(
                    self.array(block),
                    ordinal,
                    2 * ordinal,
                    2,
                    2 * ordinal,
                    2 * ordinal + 1,
                    2 * ordinal,
                    2 * ordinal + 1,
                )
            )
            previous_values = values
        self.series = CellHistory("field", "a" * 64, quantity(0.1), tuple(epochs), tuple(chunks))
        self.root = self.record(self.series, HISTORY_TYPE)

    def stage(self, produced):
        descriptor = produced_descriptor(produced)
        self.resources[descriptor.reference] = ResolvedResource(descriptor, produced.data)
        return descriptor.reference

    def array(self, values):
        return self.stage(array_resource("array", np.array(values, dtype=np.float64)))

    def record(self, record, logical_type):
        reference = self.stage(
            ProducedResource(
                "record", encode_record(record), "application/json", logical_type=logical_type
            )
        )
        self.records[reference] = record
        return reference

    def resolve(self, reference):
        return self.resources[reference]
