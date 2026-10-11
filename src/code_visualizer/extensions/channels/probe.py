"""Consume a published exact sample through the normal computation host."""

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
from code_visualizer.extensions.channels.domain import BUNDLE, identity
from code_visualizer.extensions.channels.history import ChannelHistory

BACKEND_ID = BUNDLE.id + ".exact_probe"


def probe_backend() -> RegisteredBackend:
    return RegisteredBackend(
        BackendDefinition(
            BACKEND_ID,
            "1",
            "Inspect an exact retained channel sample",
            Representation(BUNDLE.id, "1"),
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
                    "CHANNEL_PROBE_INVALID",
                    str(exc),
                    snapshot.value.roots if isinstance(snapshot.value, DomainModel) else (),
                ),
            ),
        )


def probe(snapshot: PreparedComputation) -> BackendResult:
    model = snapshot.value
    if not isinstance(model, DomainModel) or len(model.roots) != 1:
        raise ValueError("Select one exact channel probe")
    node = model.node(model.roots[0])
    if node is None or node.concept_id != identity("Probe") or snapshot.request.configuration:
        raise ValueError("The probe's authored properties own the exact selection")
    ref = node.property(identity("Probe", "series"))
    if not isinstance(ref, ResourceReference):
        raise ValueError("An exact retained series resource is required")
    resources = {r.descriptor.reference: r for r in snapshot.resources}
    history = ChannelHistory(ref, resources.__getitem__)
    try:
        sample = node.property(identity("Probe", "sample"))
        if type(sample) is not int:
            raise ValueError("Select an exact retained sample")
        selected = history.slice(sample)
        channel_id = node.property(identity("Probe", "channel_id"))
        match = next(
            ((i, c) for i, c in enumerate(history.interpretation.channels) if c.id == channel_id),
            None,
        )
        if match is None:
            raise ValueError("The selected channel is absent from this interpretation")
        index, channel = match
        if (
            node.property(identity("Probe", "support_id")) != channel.support_id
            or node.property(identity("Probe", "quantity_kind")) != channel.quantity_kind.value
            or node.property(identity("Probe", "time")) != selected.position.time
        ):
            raise ValueError("Channel support, quantity kind or exact physical time differs")
        values: tuple[tuple[str, CanonicalValue], ...] = (
            ("value", QuantityValue(float(selected.values[index]), channel.unit)),
            ("time", selected.position.time),
            ("channel", channel.id),
            ("support", channel.support_id),
            ("quantity_kind", channel.quantity_kind.value),
            ("source_definition", selected.source_digest),
        )
        return BackendResult(
            observations=tuple(
                EvidenceObservation(key, (node.id,), value, key.replace("_", " "), sequence=i)
                for i, (key, value) in enumerate(values)
            )
        )
    finally:
        history.close()
