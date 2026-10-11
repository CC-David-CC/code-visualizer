"""Execute an exact retained cell selection through the ordinary backend boundary."""

from code_visualizer.domain.computation import BackendDefinition
from code_visualizer.domain.evidence import (
    ComputationOutcome,
    EvidenceDiagnostic,
    EvidenceObservation,
)
from code_visualizer.domain.intentional import DomainModel
from code_visualizer.domain.transformation import Representation
from code_visualizer.domain.values import CanonicalValue, ResourceReference
from code_visualizer.execution.backends import BackendResult, PreparedComputation, RegisteredBackend
from code_visualizer.extensions.adaptive_fields.domain import BUNDLE, identity
from code_visualizer.extensions.adaptive_fields.history import AdaptiveHistory
from code_visualizer.extensions.fields.records import index

BACKEND_ID = BUNDLE.id + ".exact_probe"


def probe_backend() -> RegisteredBackend:
    return RegisteredBackend(
        BackendDefinition(
            BACKEND_ID, "1", "Inspect an exact retained cell sample", Representation(BUNDLE.id, "1")
        ),
        execute=execute_probe,
        file_backed_inputs=True,
    )


def execute_probe(snapshot: PreparedComputation) -> BackendResult:
    try:
        return probe(snapshot)
    except (ValueError, KeyError, ImportError) as exc:
        return BackendResult(
            ComputationOutcome.FAILED,
            diagnostics=(
                EvidenceDiagnostic(
                    "CELL_PROBE_INVALID",
                    str(exc),
                    snapshot.value.roots if isinstance(snapshot.value, DomainModel) else (),
                ),
            ),
        )


def probe(snapshot: PreparedComputation) -> BackendResult:
    model = snapshot.value
    if not isinstance(model, DomainModel) or len(model.roots) != 1:
        raise ValueError("Select one exact cell probe")
    node = model.node(model.roots[0])
    if node is None or node.concept_id != identity("Probe") or snapshot.request.configuration:
        raise ValueError("The authored probe owns its exact selection")
    root = node.property(identity("Probe", "history"))
    if not isinstance(root, ResourceReference):
        raise ValueError("A retained cell history resource is required")
    resources = {item.descriptor.reference: item for item in snapshot.resources}
    history = AdaptiveHistory(root, resources.__getitem__)
    try:
        sample = index(node.property(identity("Probe", "sample")), "Sample")
        epoch = index(node.property(identity("Probe", "epoch")), "Epoch")
        cell_id = node.property(identity("Probe", "cell_id"))
        component_id = node.property(identity("Probe", "component_id"))
        if not isinstance(cell_id, str) or not isinstance(component_id, str):
            raise ValueError("Select exact cell/component identities")
        value = history.probe(sample, epoch, cell_id, component_id)
        selected = history.slice(sample)
        if node.property(identity("Probe", "time")) != selected.position.time:
            raise ValueError("The probe's exact physical time differs from the retained sample")
        values: tuple[tuple[str, CanonicalValue], ...] = (
            ("value", value),
            ("time", selected.position.time),
            ("epoch", epoch),
            ("cell", cell_id),
            ("component", component_id),
            ("source_definition", selected.source_digest),
        )
        return BackendResult(
            observations=tuple(
                EvidenceObservation(name, (node.id,), value, name.replace("_", " "), sequence=i)
                for i, (name, value) in enumerate(values)
            )
        )
    finally:
        history.close()
