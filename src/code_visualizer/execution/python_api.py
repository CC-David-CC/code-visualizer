"""Authored Python's explicit computation API; inert files replace live objects.

The managed child installs one attempt-local context. Ordinary Python execution
without that context diagnoses publication instead of pretending it succeeded.
"""

from __future__ import annotations

import base64
import hashlib
import inspect
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.resources import DataResource, ResourceLogicalTypeReference
from code_visualizer.persistence.computation import computation_request_from_data
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.resource_transfer import resource_transfer_frames
from code_visualizer.persistence.resources import resource_from_data
from code_visualizer.protocol.resource_transfer import resource_frame_to_proto


@dataclass(frozen=True, slots=True)
class InputResource:
    descriptor: DataResource
    _path: Path

    def read_bytes(self, *, limit: int = 512 * 1024 * 1024) -> bytes:
        if self.descriptor.byte_size > limit:
            raise ValueError("COMPUTATION_INPUT_SIZE: named input exceeds the reader bound")
        with self._path.open("rb") as stream:
            payload = stream.read(min(limit, self.descriptor.byte_size) + 1)
        if (
            len(payload) != self.descriptor.byte_size
            or hashlib.sha256(payload).hexdigest() != self.descriptor.content_hash
        ):
            raise ValueError("COMPUTATION_INPUT_CHANGED: staged bytes differ from frozen input")
        return payload


class _Context:
    def __init__(
        self, configuration: dict[str, Any], exchange: Callable[[dict[str, Any]], dict[str, Any]]
    ) -> None:
        self.request: ComputationRequest = computation_request_from_data(configuration["request"])
        self.input_digest = configuration["input_digest"]
        self.inputs = {
            name: InputResource(resource_from_data(item["descriptor"]), Path(item["path"]))
            for name, item in configuration["inputs"].items()
        }
        self.files = {
            os.path.normcase(str(Path(path).resolve())): relative
            for path, relative in configuration["files"].items()
        }
        self.exchange = exchange
        self.published: set[str] = set()

    def send(self, value: dict[str, Any]) -> dict[str, Any]:
        response = self.exchange(value)
        if response.get("error"):
            raise RuntimeError(response["error"])
        return response


_context: _Context | None = None


def _install(
    configuration: dict[str, Any], exchange: Callable[[dict[str, Any]], dict[str, Any]]
) -> None:
    global _context
    if _context is not None:
        raise RuntimeError("A Python computation context is installed exactly once")
    _context = _Context(configuration, exchange)


def context() -> _Context:
    if _context is None:
        raise RuntimeError(
            "COMPUTATION_CONTEXT_REQUIRED: run this package through the computation host"
        )
    return _context


def input_resource(name: str, logical_type: ResourceLogicalTypeReference) -> InputResource:
    item = context().inputs.get(name)
    if item is None or item.descriptor.logical_type != logical_type:
        raise ValueError(
            "COMPUTATION_INPUT_TYPE: named input is absent or has a different type/version"
        )
    return item


def publish_file(
    name: str,
    path: Path,
    *,
    logical_type: ResourceLogicalTypeReference,
    media_type: str,
    semantic_ids: tuple[str, ...] = (),
) -> str:
    active = context()
    declaration = next((v for v in active.request.outputs if v.name == name), None)
    if declaration is None or declaration.logical_type != logical_type or name in active.published:
        raise ValueError("COMPUTATION_OUTPUT_DECLARATION: unknown, mismatched or repeated output")
    if not set(semantic_ids) <= set(declaration.semantic_ids):
        raise ValueError("COMPUTATION_OUTPUT_ORIGINS: undeclared output origin")
    location = None
    frame = inspect.currentframe()
    while frame is not None:
        file = active.files.get(os.path.normcase(str(Path(frame.f_code.co_filename).resolve())))
        if file is not None:
            location = {"file_path": file, "line": frame.f_lineno}
            break
        frame = frame.f_back
    del frame
    if location is None:
        raise ValueError("COMPUTATION_OUTPUT_ORIGINS: publication has no authored call site")
    # This child-local store only stages an immutable transfer; it is never the
    # editor's durable store. All bytes and the receipt are acknowledged by host.
    with TemporaryDirectory(prefix="cv-python-publication-") as directory:
        store = ResourceStore(Path(directory))
        descriptor = store.import_file(Path(path), media_type, logical_type=logical_type)
        for value in resource_transfer_frames(store, descriptor.reference, name):
            encoded = resource_frame_to_proto(value).SerializeToString(deterministic=True)
            active.send({"kind": "frame", "data": base64.b64encode(encoded).decode("ascii")})
        receipt = active.send(
            {
                "kind": "publish",
                "name": name,
                "location": location,
                "semantic_ids": list(semantic_ids),
            }
        )
    active.published.add(name)
    return str(receipt["publication_id"])


def publish_bytes(
    name: str,
    data: bytes,
    *,
    logical_type: ResourceLogicalTypeReference,
    media_type: str,
    semantic_ids: tuple[str, ...] = (),
) -> str:
    with TemporaryDirectory(prefix="cv-python-output-") as directory:
        path = Path(directory) / "output"
        path.write_bytes(data)
        return publish_file(
            name, path, logical_type=logical_type, media_type=media_type, semantic_ids=semantic_ids
        )
