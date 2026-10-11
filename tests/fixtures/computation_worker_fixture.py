"""Trusted test composition used by real process and Qt lifecycle proofs.

This is executable test implementation code, never an import selected by a
project. The host explicitly registers its command/profile and exact backend ID.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

_SOURCE = Path(__file__).resolve().parents[2] / "src"
if str(_SOURCE) not in sys.path:
    sys.path.insert(0, str(_SOURCE))

BACKEND_ID = "org.codevisualizer.test.stress"
BACKEND_VERSION = "1"


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
    from code_visualizer.execution.backends import RegisteredBackend
    from code_visualizer.extensions.builtin import builtin_registry
    from code_visualizer.extensions.publication import FIRST_PARTY_PUBLICATION
    from code_visualizer.extensions.registry import DomainExtensionBundle

    registry = builtin_registry()
    logical_type = ResourceLogicalTypeReference("org.codevisualizer.test:integer-series", "1")
    backend = RegisteredBackend(
        BackendDefinition(
            BACKEND_ID,
            BACKEND_VERSION,
            "Process stress fixture",
            PROGRAM_REPRESENTATION,
            capabilities=BackendCapabilities(
                BackendExecutionMode.STREAMING,
                progress=True,
                observations=True,
                cancellation=True,
                publications=True,
            ),
        ),
        stream=_stream,
    )
    registry.register(
        DomainExtensionBundle(
            "org.codevisualizer.test",
            "1",
            backends=(backend,),
            contracts=(
                ContractDefinition(
                    ContractKind.RESOURCE_LOGICAL_TYPE, logical_type.id, logical_type.version
                ),
            ),
            publication=FIRST_PARTY_PUBLICATION,
            required_bundles=(BundleReference("code_visualizer.program", "1"),),
        )
    )
    return registry


def _stream(snapshot, context):
    from hashlib import sha256

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
        ResourceFile,
    )

    config = {item.name: item.value for item in snapshot.request.configuration}
    mode = config.get("mode", "progress")
    identities = snapshot.entrypoint_ids or tuple(module.id for module in snapshot.value.modules)
    logical_type = ResourceLogicalTypeReference("org.codevisualizer.test:integer-series", "1")
    yield ProgressEvent(context.session_id, 0, 0.0, message="Worker started")
    if mode == "crash":
        os._exit(37)
    if mode == "descendant":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        yield ObservationEvent(
            context.session_id, EvidenceObservation("child", identities, child.pid, sequence=1)
        )
        while True:
            pass
    if mode == "cpu":
        while True:
            pass
    if mode in {"publish", "publish_hold", "publish_crash"}:
        payload = b"10,20,30"
        with TemporaryDirectory(prefix="computation-fixture-") as temporary:
            path = Path(temporary) / "integers.csv"
            path.write_bytes(payload)
            yield ProducedResourceEvent(
                context.session_id,
                1,
                ProducedResource(
                    "series",
                    media_type="text/csv",
                    semantic_ids=identities,
                    label="Integer series",
                    logical_type=logical_type,
                    file=ResourceFile(path, len(payload), sha256(payload).hexdigest()),
                ),
            )
            assert path.exists(), "Producer lifetime ended before publication was admitted"
            yield ProgressEvent(context.session_id, 2, 1.0, message="Publication acknowledged")
            if mode == "publish_crash":
                os._exit(37)
            while mode == "publish_hold" and not context.cancellation_requested:
                time.sleep(0.01)
            yield BackendResult(
                ComputationOutcome.CANCELLED
                if context.cancellation_requested
                else ComputationOutcome.SUCCEEDED
            )
        return
    if mode == "large_resource":
        reference = config.get("input")
        if not isinstance(reference, ResourceReference):
            raise ValueError("Large-resource proof requires an exact ResourceReference")
        resource = next(
            item for item in snapshot.resources if item.descriptor.reference == reference
        )
        if resource.descriptor.media_type != "application/octet-stream":
            raise ValueError("Large-resource proof accepts opaque byte data")
        digest, size = sha256(), 0
        with resource.open() as stream:
            while chunk := stream.read(1024 * 1024):
                if context.cancellation_requested:
                    yield BackendResult(ComputationOutcome.CANCELLED)
                    return
                digest.update(chunk)
                size += len(chunk)
        if (size, digest.hexdigest()) != (resource.descriptor.byte_size, reference.content_hash):
            raise ValueError("Large-resource proof did not receive the admitted bytes")
        yield ObservationEvent(
            context.session_id,
            EvidenceObservation("bytes", identities, size, "Streamed input bytes", 1),
        )
        yield ObservationEvent(
            context.session_id,
            EvidenceObservation("sha256", identities, digest.hexdigest(), "Streamed input hash", 2),
        )
        yield BackendResult()
        return
    if mode == "consume":
        reference = config.get("input")
        if not isinstance(reference, ResourceReference):
            raise ValueError("Consumer requires its exact input ResourceReference")
        resource = next(
            item for item in snapshot.resources if item.descriptor.reference == reference
        )
        if resource.descriptor.logical_type != logical_type:
            raise ValueError("Consumer requires integer-series@1")
        with resource.open() as stream:
            result = sum(int(item) for item in stream.read().decode().split(","))
        yield ObservationEvent(
            context.session_id,
            EvidenceObservation("sum", identities, result, "Sum of published input", 1),
        )
        yield BackendResult()
        return
    count = config.get("count", 10000)
    if type(count) is not int or not 1 <= count <= 1000000:
        raise ValueError("Progress count must be bounded")
    for index in range(count):
        if context.cancellation_requested:
            yield BackendResult(ComputationOutcome.CANCELLED)
            return
        yield ProgressEvent(
            context.session_id, index + 1, float(index), float(count), f"Progress {index}"
        )
    yield BackendResult()


def worker_profile():
    from code_visualizer.execution.worker_process import WorkerProfile

    return WorkerProfile(
        "test-stress-composition",
        "1",
        (sys.executable, "-I", str(Path(__file__).resolve())),
        ((BACKEND_ID, BACKEND_VERSION),),
    )


if __name__ == "__main__":
    from code_visualizer.application.computation_worker import serve

    raise SystemExit(serve(fixture_registry))
