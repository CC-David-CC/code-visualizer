"""Trusted P2 counter/checkpoint composition using the normal portable worker."""

import sys
import time
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

BACKEND_ID = "org.codevisualizer.test.experiments.counter"
LOGICAL_TYPE = "org.codevisualizer.test.experiments:checkpoint"


def fixture_registry():
    from code_visualizer.domain.computation import (
        BackendCapabilities,
        BackendDefinition,
        BackendExecutionMode,
    )
    from code_visualizer.domain.identifiers import ContractDefinition, ContractKind
    from code_visualizer.domain.intentional import BundleReference
    from code_visualizer.domain.resources import ResourceLogicalTypeReference
    from code_visualizer.domain.transformation import PROGRAM_REPRESENTATION
    from code_visualizer.execution.backends import CheckpointContract, RegisteredBackend
    from code_visualizer.extensions.builtin import builtin_registry
    from code_visualizer.extensions.publication import FIRST_PARTY_PUBLICATION
    from code_visualizer.extensions.registry import DomainExtensionBundle

    registry = builtin_registry()
    logical = ResourceLogicalTypeReference(LOGICAL_TYPE, "1")
    backend = RegisteredBackend(
        BackendDefinition(
            BACKEND_ID,
            "1",
            "P2 counter proof",
            PROGRAM_REPRESENTATION,
            capabilities=BackendCapabilities(
                BackendExecutionMode.STREAMING,
                progress=True,
                observations=True,
                cancellation=True,
                publications=True,
            ),
        ),
        stream=stream,
        checkpoint=CheckpointContract(logical, "checkpoint"),
    )
    registry.register(
        DomainExtensionBundle(
            "org.codevisualizer.test.experiments",
            "1",
            backends=(backend,),
            contracts=(ContractDefinition(ContractKind.RESOURCE_LOGICAL_TYPE, LOGICAL_TYPE, "1"),),
            publication=FIRST_PARTY_PUBLICATION,
            required_bundles=(BundleReference("code_visualizer.program", "1"),),
        )
    )
    return registry


def stream(snapshot, context):
    from code_visualizer.domain.computation import ProgressEvent
    from code_visualizer.domain.evidence import (
        ComputationOutcome,
        EvidenceObservation,
        ObservationEvent,
    )
    from code_visualizer.domain.resources import ResourceLogicalTypeReference
    from code_visualizer.domain.values import ResourceReference
    from code_visualizer.execution.backends import (
        BackendResult,
        ProducedResource,
        ProducedResourceEvent,
    )

    config = {item.name: item.value for item in snapshot.request.configuration}
    reference = config.get("checkpoint")
    state = 0
    if reference is not None:
        assert isinstance(reference, ResourceReference)
        resource = next(
            item for item in snapshot.resources if item.descriptor.reference == reference
        )
        with resource.open() as source:
            state = int(source.read().decode("ascii"))
    state += config.get("step", 1)
    origins = snapshot.entrypoint_ids
    yield ObservationEvent(
        context.session_id, EvidenceObservation("state", origins, state, sequence=1)
    )
    yield ProducedResourceEvent(
        context.session_id,
        2,
        ProducedResource(
            f"checkpoint-{state}",
            str(state).encode("ascii"),
            "text/plain",
            origins,
            logical_type=ResourceLogicalTypeReference(LOGICAL_TYPE, "1"),
        ),
    )
    yield ProgressEvent(context.session_id, 3, 1.0, message="Checkpoint sealed")
    while config.get("hold", False) and not context.cancellation_requested:
        time.sleep(0.01)
    yield BackendResult(
        ComputationOutcome.CANCELLED
        if context.cancellation_requested
        else ComputationOutcome.SUCCEEDED
    )


def worker_profile():
    from code_visualizer.execution.worker_process import WorkerProfile

    return WorkerProfile(
        "p2-counter",
        "1",
        (sys.executable, "-I", str(Path(__file__).resolve())),
        ((BACKEND_ID, "1"),),
    )


if __name__ == "__main__":
    from code_visualizer.application.computation_worker import serve

    raise SystemExit(serve(fixture_registry))
