"""Independent exact sampling of an immutable field; no producer or solver import."""

from code_visualizer.domain.computation import BackendDefinition
from code_visualizer.domain.evidence import (
    ComputationOutcome,
    EvidenceDiagnostic,
    EvidenceObservation,
)
from code_visualizer.domain.intentional import DomainModel
from code_visualizer.domain.transformation import Representation
from code_visualizer.domain.values import CanonicalValue, QuantityValue, ResourceReference
from code_visualizer.execution.backends import BackendResult, PreparedComputation, RegisteredBackend
from code_visualizer.extensions.fields.domain import BUNDLE, identity
from code_visualizer.extensions.fields.history import FieldHistory
from code_visualizer.extensions.fields.units import field_catalog
from code_visualizer.extensions.foundations.unit_algebra import UnitAlgebra

BACKEND_ID = BUNDLE.id + ".exact_probe"


def probe_backend() -> RegisteredBackend:
    return RegisteredBackend(
        BackendDefinition(
            BACKEND_ID,
            "1",
            "Inspect an exact retained field sample",
            Representation(BUNDLE.id, BUNDLE.version),
        ),
        execute=execute_probe,
        file_backed_inputs=True,
    )


def execute_probe(snapshot: PreparedComputation) -> BackendResult:
    try:
        return _probe(snapshot)
    except (ValueError, KeyError, ImportError) as exc:
        return BackendResult(
            ComputationOutcome.FAILED,
            diagnostics=(EvidenceDiagnostic("FIELD_PROBE_INVALID", str(exc)),),
        )


def _probe(snapshot: PreparedComputation) -> BackendResult:
    model = snapshot.value
    if not isinstance(model, DomainModel) or len(model.roots) != 1:
        raise ValueError("An exact field probe requires one authored request")
    node = model.node(model.roots[0])
    if node is None or node.concept_id != identity("Probe"):
        raise ValueError("Select a field Probe intention")
    if snapshot.request.configuration:
        raise ValueError("Probe selection belongs to its authored properties")
    reference = node.property(identity("Probe", "series"))
    if not isinstance(reference, ResourceReference):
        raise ValueError("Select an immutable series resource")
    resources = {item.descriptor.reference: item for item in snapshot.resources}
    history = FieldHistory(reference, resources.__getitem__)
    try:
        history.coordinates()
        sample, index = (node.property(identity("Probe", key)) for key in ("sample", "node"))
        time = node.property(identity("Probe", "time"))
        if (
            type(sample) is not int
            or type(index) is not int
            or not 0 <= index < history.support.nodes
            or not isinstance(time, QuantityValue)
        ):
            raise ValueError(
                "Probe requires an exact retained sample/node and explicit physical time"
            )
        selected = history.slice(sample)
        if (
            node.property(identity("Probe", "frame_id")) != history.support.frame_id
            or node.property(identity("Probe", "component_id"))
            != history.interpretation.component_id
        ):
            raise ValueError("FIELD_PROBE_INTERPRETATION: frame/component does not match")
        if (
            UnitAlgebra(field_catalog()).convert(time, selected.position.time.unit)
            != selected.position.time
        ):
            raise ValueError("FIELD_PROBE_TIME: requested time is not the selected accepted sample")
        values: tuple[tuple[str, CanonicalValue], ...] = (
            ("value", QuantityValue(float(selected.values[index]), history.interpretation.unit)),
            ("time", selected.position.time),
            ("source_field", history.interpretation.field_id),
            ("source_definition", selected.source_digest),
            ("quantity_kind", history.interpretation.quantity_kind.value),
        )
        return BackendResult(
            observations=tuple(
                EvidenceObservation(key, (node.id,), value, sequence=sequence)
                for sequence, (key, value) in enumerate(values)
            )
        )
    finally:
        history.close()
