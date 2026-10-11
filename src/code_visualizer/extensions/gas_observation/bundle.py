"""An ordinary Python backend consumes published gas data after its producer exits."""

from code_visualizer.domain.computation import BackendDefinition
from code_visualizer.domain.evidence import (
    ComputationOutcome,
    EvidenceDiagnostic,
    EvidenceObservation,
)
from code_visualizer.domain.intentional import DomainModel
from code_visualizer.domain.values import QuantityValue, ResourceReference
from code_visualizer.execution.backends import BackendResult, PreparedComputation, RegisteredBackend
from code_visualizer.extensions.gas_observation.domain import (
    BACKEND_ID,
    BUNDLE,
    REPRESENTATION,
    identity,
    notations,
    observation_schema,
)
from code_visualizer.extensions.hybrid_gas.domain import BUNDLE as GAS
from code_visualizer.extensions.publication import FIRST_PARTY_PUBLICATION
from code_visualizer.extensions.registry import DomainExtensionBundle


def execute(snapshot: PreparedComputation) -> BackendResult:
    from code_visualizer.extensions.gas_observation.reader import probe
    from code_visualizer.extensions.hybrid_gas.history import GasHistory

    if not isinstance(snapshot.value, DomainModel):
        return BackendResult(
            ComputationOutcome.FAILED,
            diagnostics=(EvidenceDiagnostic("GAS_PROBE_INPUT", "Select a retained gas query"),),
        )
    if snapshot.request.configuration or snapshot.request.seed is not None:
        return BackendResult(
            ComputationOutcome.FAILED,
            diagnostics=(
                EvidenceDiagnostic(
                    "GAS_PROBE_CONFIGURATION", "The query belongs to authored input"
                ),
            ),
        )
    roots = tuple(snapshot.value.node(i) for i in snapshot.value.roots)
    if not roots or any(n is None or n.concept_id != identity() for n in roots):
        return BackendResult(
            ComputationOutcome.FAILED,
            diagnostics=(EvidenceDiagnostic("GAS_PROBE_INPUT", "Select typed root queries"),),
        )
    resources = {r.descriptor.reference: r for r in snapshot.resources}
    observations: list[EvidenceObservation] = []
    for node in roots:
        assert node is not None
        try:
            history_ref, sample, cell, component, frame, time = (
                node.property(identity(key))
                for key in ("history", "sample", "cell_id", "component_id", "frame_id", "time")
            )
            if (
                not isinstance(history_ref, ResourceReference)
                or type(sample) is not int
                or not isinstance(cell, str)
                or not isinstance(component, str)
                or not isinstance(frame, str)
                or not isinstance(time, QuantityValue)
            ):
                raise ValueError("GAS_PROBE_INPUT: incomplete typed selection")
            history = GasHistory(history_ref, resources.__getitem__, cache_bytes=0)
            try:
                value = probe(history, sample, cell, component, frame, time)
                observations.append(
                    EvidenceObservation(
                        node.id + ":value",
                        (node.id,),
                        value,
                        f"{component}, {cell}, sample {sample}",
                    )
                )
            finally:
                history.close()
        except (ValueError, KeyError, OSError, IndexError) as exc:
            return BackendResult(
                ComputationOutcome.FAILED,
                diagnostics=(EvidenceDiagnostic("GAS_PROBE_INVALID", str(exc), (node.id,)),),
            )
    return BackendResult(observations=tuple(observations))


def observation_bundle() -> DomainExtensionBundle:
    return DomainExtensionBundle(
        BUNDLE.id,
        BUNDLE.version,
        schemas=(observation_schema(),),
        notations=notations(),
        backends=(
            RegisteredBackend(
                BackendDefinition(BACKEND_ID, "1", "Exact retained gas cell", REPRESENTATION),
                execute=execute,
                file_backed_inputs=True,
            ),
        ),
        required_bundles=(GAS,),
        publication=FIRST_PARTY_PUBLICATION,
    )
