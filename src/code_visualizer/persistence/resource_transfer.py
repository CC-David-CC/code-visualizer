"""Stream resources into staging; publish immutable CAS objects only after verification."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from contextlib import ExitStack
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import TracebackType
from typing import IO

from code_visualizer.domain.boundaries import MAX_RESOURCE_CHUNK_BYTES
from code_visualizer.domain.resource_transfer import (
    ResourceTransferAbort,
    ResourceTransferChunk,
    ResourceTransferFinish,
    ResourceTransferFrame,
    ResourceTransferStart,
)
from code_visualizer.domain.resources import DataResource
from code_visualizer.domain.values import ResourceReference
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.resource_store import (
    MAX_DESCRIPTOR_BYTES,
    ResourceStore,
    resource_identity,
)
from code_visualizer.persistence.resources import resource_to_data


def resource_transfer_frames(
    store: ResourceStore,
    reference: ResourceReference,
    transfer_id: str,
    *,
    chunk_bytes: int = MAX_RESOURCE_CHUNK_BYTES,
) -> Iterator[ResourceTransferFrame]:
    """Read one bounded chunk at a time, with a second digest against mid-read changes."""
    if type(chunk_bytes) is not int or not 1 <= chunk_bytes <= MAX_RESOURCE_CHUNK_BYTES:
        raise ValueError("Resource chunk size must be between 1 byte and 256 KiB")
    descriptor = store.describe(reference)
    start = ResourceTransferStart(transfer_id, descriptor)
    path = store.verified_path(reference)
    digest, offset = hashlib.sha256(), 0
    yield start
    with path.open("rb") as source:
        while chunk := source.read(min(chunk_bytes, descriptor.byte_size - offset + 1)):
            if offset + len(chunk) > descriptor.byte_size:
                raise ValueError("Resource changed during transfer")
            digest.update(chunk)
            yield ResourceTransferChunk(transfer_id, offset, chunk)
            offset += len(chunk)
    if offset != descriptor.byte_size or digest.hexdigest() != descriptor.content_hash:
        raise ValueError("Resource changed during transfer")
    yield ResourceTransferFinish(transfer_id)


class ResourceTransferReceiver:
    """One explicit expected resource and caller-selected storage budget per transfer.

    Finish seals the staging file; commit is explicit so a caller can reject a
    truncated or trailing-frame stream before publishing metadata. Context exit,
    abort and every validation failure remove the unpublished staging file.
    """

    def __init__(
        self, store: ResourceStore, expected: ResourceReference, *, max_resource_bytes: int
    ) -> None:
        if not isinstance(expected, ResourceReference):
            raise ValueError("An incoming resource requires an expected typed reference")
        if type(max_resource_bytes) is not int or not 0 <= max_resource_bytes < 1 << 63:
            raise ValueError("The transfer storage budget must be a nonnegative 64-bit integer")
        self.store = store
        self.expected = expected
        self.max_resource_bytes = max_resource_bytes
        self._descriptor: DataResource | None = None
        self._transfer_id: str | None = None
        self._temporary: IO[bytes] | None = None
        self._files = ExitStack()
        self._path: Path | None = None
        self._digest = hashlib.sha256()
        self._offset = 0
        self._sealed = False
        self._closed = False

    def __enter__(self) -> ResourceTransferReceiver:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._closed = True
        if self._temporary is not None:
            self._temporary.close()
            self._temporary = None
        self._files.close()
        if self._path is not None:
            self._path.unlink(missing_ok=True)
            self._path = None

    def accept(self, frame: ResourceTransferFrame) -> None:
        try:
            self._accept(frame)
        except BaseException:
            self.close()
            raise

    def _accept(self, frame: ResourceTransferFrame) -> None:
        if self._closed or self._sealed:
            raise ValueError("Resource transfer is already finished or closed")
        if self._descriptor is None:
            if not isinstance(frame, ResourceTransferStart):
                raise ValueError("Resource transfer must begin with a descriptor")
            resource = frame.resource
            if resource.reference != self.expected or resource_identity(resource) != resource.id:
                raise ValueError("Resource descriptor identity or hash differs from expectation")
            if resource.byte_size > self.max_resource_bytes:
                raise ValueError("Resource exceeds the transfer storage budget")
            if len(canonical_data_bytes(resource_to_data(resource))) > MAX_DESCRIPTOR_BYTES:
                raise ValueError("Resource descriptor exceeds the storage metadata bound")
            staging = self.store._path("staging/transport")
            staging.mkdir(parents=True, exist_ok=True)
            # The receiver context spans multiple frames and owns this ExitStack.
            temporary = self._files.enter_context(
                NamedTemporaryFile(dir=staging, delete=False)  # noqa: SIM115
            )
            self._temporary = temporary.file
            self._path = Path(temporary.name)
            self._descriptor = resource
            self._transfer_id = frame.transfer_id
            return
        if frame.transfer_id != self._transfer_id:
            raise ValueError("Resource transfer identity changed")
        if isinstance(frame, ResourceTransferAbort):
            raise ValueError("Resource transfer aborted: " + frame.reason)
        if isinstance(frame, ResourceTransferStart):
            raise ValueError("Resource transfer descriptor cannot be replaced")
        if self._temporary is None:
            raise ValueError("Resource transfer has no staging file")
        if isinstance(frame, ResourceTransferChunk):
            if frame.offset != self._offset:
                raise ValueError("Resource chunks must have contiguous, increasing offsets")
            if self._offset + len(frame.data) > self._descriptor.byte_size:
                raise ValueError("Resource chunks exceed the declared byte size")
            self._temporary.write(frame.data)
            self._digest.update(frame.data)
            self._offset += len(frame.data)
            return
        if not isinstance(frame, ResourceTransferFinish):
            raise ValueError("Unknown resource transfer frame")
        if (
            self._offset != self._descriptor.byte_size
            or self._digest.hexdigest() != self._descriptor.content_hash
        ):
            raise ValueError("Resource transfer content hash or byte size mismatch")
        self._temporary.flush()
        os.fsync(self._temporary.fileno())
        self._temporary.close()
        self._temporary = None
        self._sealed = True

    def commit(self) -> DataResource:
        """Reverify the sealed file before atomically publishing content and descriptor."""
        try:
            if self._closed or not self._sealed or self._path is None or self._descriptor is None:
                raise ValueError("Resource transfer is incomplete or closed")
            descriptor = self._descriptor
            result = self.store.import_file(
                self._path,
                descriptor.media_type,
                tensor=descriptor.tensor,
                logical_type=descriptor.logical_type,
                expected_byte_size=descriptor.byte_size,
                expected_content_hash=descriptor.content_hash,
            )
            if result != descriptor:
                raise ValueError("Published resource descriptor differs from transfer")
            return result
        finally:
            self.close()
