"""Host side of typed resource exchange with the established Python trace child."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock
from typing import Any

from code_visualizer.domain.evidence import EvidenceArtifact, PublicationEvent
from code_visualizer.domain.resource_transfer import ResourceTransferFinish, ResourceTransferStart
from code_visualizer.domain.resources import DataResource
from code_visualizer.execution.backends import PreparedComputation
from code_visualizer.generation.emitter import GeneratedProject
from code_visualizer.persistence.computation import computation_request_to_data
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.resource_transfer import ResourceTransferReceiver
from code_visualizer.persistence.resources import resource_to_data
from code_visualizer.protocol.resource_transfer import resource_frame_from_proto
from code_visualizer.protocol.v1.resource_pb2 import ResourceTransferFrame
from code_visualizer.protocol.validation import parse_message


class PythonArtifactContext:
    def __init__(
        self,
        snapshot: PreparedComputation,
        generated: GeneratedProject,
        store: ResourceStore,
        publish: Callable[[EvidenceArtifact], PublicationEvent],
    ) -> None:
        self.snapshot, self.generated, self.store, self.publish = (
            snapshot,
            generated,
            store,
            publish,
        )
        self.temporary = TemporaryDirectory(prefix="cv-python-inputs-")
        self.receiver: ResourceTransferReceiver | None = None
        self.received: tuple[str, DataResource] | None = None
        self.published: set[str] = set()
        self.byte_budget = 2 * 1024 * 1024 * 1024
        self._lock = RLock()
        self._closed = False
        self.error: Exception | None = None

    def configuration(self, files: dict[str, str]) -> dict[str, Any]:
        inputs = {}
        try:
            for binding in self.snapshot.request.inputs:
                resource = next(
                    item
                    for item in self.snapshot.resources
                    if item.descriptor.reference == binding.resource
                )
                if resource.descriptor.logical_type != binding.logical_type:
                    raise ValueError("COMPUTATION_INPUT_TYPE: named input contract differs")
                path = Path(self.temporary.name) / binding.name
                digest, size = hashlib.sha256(), 0
                with resource.open() as source, path.open("wb") as output:
                    while chunk := source.read(256 * 1024):
                        digest.update(chunk)
                        size += len(chunk)
                        if size > resource.descriptor.byte_size:
                            raise ValueError(
                                "COMPUTATION_INPUT_CHANGED: resource grew while staging"
                            )
                        output.write(chunk)
                if (
                    digest.hexdigest() != binding.resource.content_hash
                    or size != resource.descriptor.byte_size
                ):
                    raise ValueError("COMPUTATION_INPUT_CHANGED: resource changed while staging")
                inputs[binding.name] = {
                    "descriptor": resource_to_data(resource.descriptor),
                    "path": str(path),
                }
            return {
                "request": computation_request_to_data(self.snapshot.request),
                "input_digest": self.snapshot.input_digest,
                "inputs": inputs,
                "files": files,
                "sdk_root": str(Path(__file__).resolve().parents[2]),
            }
        except BaseException:
            self.close()
            raise

    def accept(self, message: object) -> dict[str, Any]:
        with self._lock:
            if self._closed:
                raise ValueError("COMPUTATION_PROTOCOL: publication context is closed")
            try:
                return self._accept(message)
            except Exception as exc:
                self.error = exc
                raise

    def _accept(self, message: object) -> dict[str, Any]:
        if not isinstance(message, dict):
            raise ValueError("COMPUTATION_PROTOCOL: expected typed message")
        if message.get("kind") == "frame" and set(message) == {"kind", "data"}:
            frame = resource_frame_from_proto(
                parse_message(
                    base64.b64decode(message["data"], validate=True), ResourceTransferFrame
                )
            )
            if isinstance(frame, ResourceTransferStart):
                if self.receiver is not None or self.received is not None:
                    raise ValueError("COMPUTATION_PROTOCOL: only one pending publication")
                declared = next(
                    (v for v in self.snapshot.request.outputs if v.name == frame.transfer_id), None
                )
                if (
                    declared is None
                    or declared.logical_type != frame.resource.logical_type
                    or frame.transfer_id in self.published
                ):
                    raise ValueError(
                        "COMPUTATION_OUTPUT_DECLARATION: output type/name does not match"
                    )
                self.receiver = ResourceTransferReceiver(
                    self.store, frame.resource.reference, max_resource_bytes=self.byte_budget
                )
            if self.receiver is None:
                raise ValueError("COMPUTATION_PROTOCOL: resource transfer has not started")
            self.receiver.accept(frame)
            if isinstance(frame, ResourceTransferFinish):
                descriptor = self.receiver.commit()
                self.byte_budget -= descriptor.byte_size
                self.received = frame.transfer_id, descriptor
                self.receiver = None
            return {"ok": True}
        if message.get("kind") == "publish" and set(message) == {
            "kind",
            "name",
            "location",
            "semantic_ids",
        }:
            if self.received is None or self.received[0] != message["name"]:
                raise ValueError(
                    "COMPUTATION_PROTOCOL: publication requires its completed resource"
                )
            name, descriptor = self.received
            declaration = next(v for v in self.snapshot.request.outputs if v.name == name)
            origins = message["semantic_ids"]
            if (
                not isinstance(origins, list)
                or any(not isinstance(v, str) for v in origins)
                or not set(origins) <= set(declaration.semantic_ids)
            ):
                raise ValueError("COMPUTATION_OUTPUT_ORIGINS: undeclared origin")
            location = message["location"]
            if (
                not isinstance(location, dict)
                or set(location) != {"file_path", "line"}
                or type(location["line"]) is not int
            ):
                raise ValueError("COMPUTATION_OUTPUT_ORIGINS: invalid call site")
            spans = [
                s
                for s in self.generated.spans
                if s.file_path == location["file_path"]
                and s.start_line <= location["line"] <= s.end_line
            ]
            if not spans:
                raise ValueError("COMPUTATION_OUTPUT_ORIGINS: no canonical source for call site")
            site = min(spans, key=lambda s: s.end_line - s.start_line).semantic_id
            semantic_ids = tuple(sorted({site, *declaration.semantic_ids}))
            artifact = EvidenceArtifact(
                f"python:output:{name}", descriptor.reference, semantic_ids, name
            )
            receipt = self.publish(artifact)
            self.published.add(name)
            self.received = None
            return {"publication_id": receipt.publication.id}
        raise ValueError("COMPUTATION_PROTOCOL: unknown message")

    def missing_outputs(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(
                v.name
                for v in self.snapshot.request.outputs
                if v.required and v.name not in self.published
            )

    def finish(self) -> tuple[str, ...]:
        """Quiesce admitted host I/O before terminal evidence or staging cleanup.

        Cancellation stops the child independently. The host still owns a receipt
        write already in progress, and must resolve it before reporting completion.
        """
        with self._lock:
            self._closed = True
            return self.missing_outputs()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            if self.receiver is not None:
                self.receiver.close()
                self.receiver = None
            self.temporary.cleanup()
