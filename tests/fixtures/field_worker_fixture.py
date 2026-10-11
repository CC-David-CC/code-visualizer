"""Trusted process fixture for grouped publication and lazy portable consumers."""

from __future__ import annotations

import sys
from pathlib import Path

_SOURCE = Path(__file__).resolve().parents[2] / "src"
if str(_SOURCE) not in sys.path:
    sys.path.insert(0, str(_SOURCE))

BACKEND_ID = "org.codevisualizer.test.fields"


def field_output(nodes=33, chunks=3, rows=4):
    from dataclasses import replace

    import numpy as np

    from code_visualizer.domain.values import QuantityValue
    from code_visualizer.execution.backends import ProducedResource
    from code_visualizer.extensions.fields.arrays import array_resource
    from code_visualizer.extensions.fields.codec import encode_record
    from code_visualizer.extensions.fields.records import (
        INTERPRETATION_TYPE,
        SERIES_TYPE,
        SUPPORT_TYPE,
        FieldInterpretation,
        FieldSeries,
        SampleChunk,
        TemporalPosition,
        UniformSupport,
    )
    from code_visualizer.extensions.foundations.unit_algebra import QuantityKind
    from code_visualizer.extensions.foundations.units_si import si_catalog
    from code_visualizer.persistence.computation_resources import produced_descriptor

    def q(value, unit="second"):
        return QuantityValue(value, si_catalog().unit("foundation.units.si:" + unit))

    staged = []

    def stage(resource):
        staged.append(resource)
        return produced_descriptor(resource).reference

    coordinates = stage(
        array_resource("coordinates", np.arange(nodes, dtype=np.float64) / (nodes - 1))
    )
    support = UniformSupport(
        "space",
        "frame",
        "axis",
        "x",
        q(0, "meter"),
        q(1 / (nodes - 1), "meter"),
        nodes,
        coordinates,
    )
    support_ref = stage(
        ProducedResource(
            "support", encode_record(support), "application/json", logical_type=SUPPORT_TYPE
        )
    )
    interpretation = FieldInterpretation(
        "field", support_ref, q(1, "kelvin").unit, QuantityKind.INTERVAL
    )
    interpretation_ref = stage(
        ProducedResource(
            "interpretation",
            encode_record(interpretation),
            "application/json",
            logical_type=INTERPRETATION_TYPE,
        )
    )
    entries = []
    for i in range(chunks):
        values = np.zeros((rows, nodes + 2), dtype=np.float64)
        samples = np.arange(i * rows, (i + 1) * rows)
        values[:, 0] = samples
        values[:, 1] = samples * 0.01
        values[:, 2:] = np.sin(np.arange(nodes) * np.pi / (nodes - 1)) * np.exp(
            -samples[:, None] * 0.01
        )
        reference = stage(array_resource(f"chunk-{i}", values))
        first = TemporalPosition(q(float(values[0, 1])), int(samples[0]), int(samples[0]))
        last = TemporalPosition(q(float(values[-1, 1])), int(samples[-1]), int(samples[-1]))
        entries.append(SampleChunk(reference, first, last, rows, nodes))
    root = ProducedResource(
        "history",
        encode_record(FieldSeries(interpretation_ref, "a" * 64, tuple(entries))),
        "application/json",
        label="Sealed field history",
        logical_type=SERIES_TYPE,
    )
    return replace(root, dependencies=tuple(staged))


def _stream(snapshot, context):
    from code_visualizer.domain.evidence import EvidenceObservation, ObservationEvent
    from code_visualizer.execution.backends import BackendResult, ProducedResourceEvent
    from code_visualizer.extensions.fields.history import FieldHistory

    config = {item.name: item.value for item in snapshot.request.configuration}
    if "input" in config:
        assert all(item.file is not None and item.data is None for item in snapshot.resources)
        resources = {item.descriptor.reference: item for item in snapshot.resources}
        history = FieldHistory(config["input"], resources.__getitem__)
        result = history.slice(history.sample_count - 1)
        yield ObservationEvent(
            context.session_id,
            EvidenceObservation(
                "midpoint", (), float(result.values[len(result.values) // 2]), sequence=0
            ),
        )
        history.close()
    else:
        yield ProducedResourceEvent(context.session_id, 0, field_output())
    yield BackendResult()


def fixture_registry():
    from code_visualizer.domain.computation import (
        BackendCapabilities,
        BackendDefinition,
        BackendExecutionMode,
    )
    from code_visualizer.domain.intentional import BundleReference
    from code_visualizer.domain.transformation import PROGRAM_REPRESENTATION
    from code_visualizer.execution.backends import RegisteredBackend
    from code_visualizer.extensions.builtin import builtin_registry
    from code_visualizer.extensions.publication import FIRST_PARTY_PUBLICATION
    from code_visualizer.extensions.registry import DomainExtensionBundle

    registry = builtin_registry()
    backend = RegisteredBackend(
        BackendDefinition(
            BACKEND_ID,
            "1",
            "Field resource process fixture",
            PROGRAM_REPRESENTATION,
            capabilities=BackendCapabilities(
                BackendExecutionMode.STREAMING, observations=True, publications=True
            ),
        ),
        stream=_stream,
        file_backed_inputs=True,
    )
    registry.register(
        DomainExtensionBundle(
            BACKEND_ID,
            "1",
            backends=(backend,),
            publication=FIRST_PARTY_PUBLICATION,
            required_bundles=(
                BundleReference("code_visualizer.program", "1"),
                BundleReference("foundation.fields", "1"),
            ),
        )
    )
    return registry


def worker_profile():
    from code_visualizer.execution.worker_process import WorkerProfile

    return WorkerProfile(
        "field-resource-proof",
        "1",
        (sys.executable, "-I", str(Path(__file__).resolve())),
        ((BACKEND_ID, "1"),),
    )


if __name__ == "__main__":
    from code_visualizer.application.computation_worker import serve

    raise SystemExit(serve(fixture_registry))
