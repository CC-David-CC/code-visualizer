"""Immutable content-addressed resources beside canonical project metadata."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import BinaryIO

from code_visualizer.domain.resources import (
    DataResource,
    ResourceLogicalTypeReference,
    TensorDescriptor,
)
from code_visualizer.domain.values import ResourceReference
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.resources import resource_from_data, resource_to_data

MAX_DESCRIPTOR_BYTES = 128 * 1024
MAX_RESOURCE_READ_BYTES = 64 * 1024 * 1024


def read_bounded(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        payload = stream.read(limit + 1)
    if len(payload) > limit:
        raise ValueError("Stored record exceeds its bounded size")
    return payload


def resource_identity(value: DataResource) -> str:
    data = resource_to_data(value)
    data.pop("id")
    return "resource:" + hashlib.sha256(canonical_data_bytes(data)).hexdigest()


class ResourceStore:
    def __init__(self, root: Path, *, inputs: ResourceStore | None = None) -> None:
        project_root = root.resolve()
        self.root = (project_root / "resources").resolve()
        if not self.root.is_relative_to(project_root):
            raise ValueError("Resource store must remain inside its project directory")
        if inputs is not None:
            if not isinstance(inputs, ResourceStore):
                raise ValueError("Resource inputs require an explicit managed store")
            input_store: ResourceStore | None = inputs
            while input_store is not None:
                if self.root.is_relative_to(input_store.root) or input_store.root.is_relative_to(
                    self.root
                ):
                    raise ValueError("Writable resources must not overlap their read-only inputs")
                input_store = input_store.inputs
        self._inputs = inputs

    @property
    def inputs(self) -> ResourceStore | None:
        """Trusted read-only input source; its path is never persisted in a descriptor."""
        return self._inputs

    def _path(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Resource location escapes the managed store")
        return path

    def put(
        self,
        data: bytes,
        media_type: str,
        *,
        tensor: TensorDescriptor | None = None,
        logical_type: ResourceLogicalTypeReference | None = None,
    ) -> DataResource:
        import io

        if type(data) is not bytes:
            raise ValueError("Resource payload must be immutable bytes")
        return self._put_stream(
            io.BytesIO(data), media_type, tensor=tensor, logical_type=logical_type
        )

    def import_file(
        self,
        path: Path,
        media_type: str,
        *,
        tensor: TensorDescriptor | None = None,
        logical_type: ResourceLogicalTypeReference | None = None,
        expected_byte_size: int | None = None,
        expected_content_hash: str | None = None,
    ) -> DataResource:
        """Stream bulk data without placing it in a canonical value or command."""
        with path.open("rb") as stream:
            return self._put_stream(
                stream,
                media_type,
                tensor=tensor,
                logical_type=logical_type,
                expected_byte_size=expected_byte_size,
                expected_content_hash=expected_content_hash,
            )

    def import_reference(self, source: ResourceStore, reference: ResourceReference) -> DataResource:
        """Copy one verified immutable resource into this store's local ownership."""
        descriptor = source.describe(reference)
        imported = self.import_file(
            source.verified_path(reference),
            descriptor.media_type,
            tensor=descriptor.tensor,
            logical_type=descriptor.logical_type,
            expected_byte_size=descriptor.byte_size,
            expected_content_hash=descriptor.content_hash,
        )
        if imported != descriptor:
            raise ValueError("Imported resource differs from its exact immutable descriptor")
        return imported

    def _put_stream(
        self,
        stream: BinaryIO,
        media_type: str,
        *,
        tensor: TensorDescriptor | None,
        logical_type: ResourceLogicalTypeReference | None,
        expected_byte_size: int | None = None,
        expected_content_hash: str | None = None,
    ) -> DataResource:
        # Reject malformed metadata before reading or staging caller-owned bulk data.
        DataResource("pending", "0" * 64, 0, media_type, tensor, logical_type)
        if expected_byte_size is not None and (
            type(expected_byte_size) is not int or not 0 <= expected_byte_size < 1 << 63
        ):
            raise ValueError("Expected resource size must be a nonnegative signed 64-bit integer")
        if expected_content_hash is not None:
            ResourceReference("expected-file", expected_content_hash)
        staging = self._path("staging")
        staging.mkdir(parents=True, exist_ok=True)
        digest, size = hashlib.sha256(), 0
        with NamedTemporaryFile(dir=staging, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            try:
                while chunk := stream.read(
                    1024 * 1024
                    if expected_byte_size is None
                    else min(1024 * 1024, expected_byte_size - size + 1)
                ):
                    digest.update(chunk)
                    size += len(chunk)
                    if expected_byte_size is not None and size > expected_byte_size:
                        raise ValueError("Resource content differs from declared byte size")
                    temporary.write(chunk)
                if expected_byte_size is not None and size != expected_byte_size:
                    raise ValueError("Resource content differs from declared byte size")
                if (
                    expected_content_hash is not None
                    and digest.hexdigest() != expected_content_hash
                ):
                    raise ValueError("Resource content differs from declared content hash")
                temporary.flush()
                os.fsync(temporary.fileno())
            except BaseException:
                temporary.close()
                temporary_path.unlink(missing_ok=True)
                raise
        try:
            descriptor = DataResource(
                "pending", digest.hexdigest(), size, media_type, tensor, logical_type
            )
            descriptor = replace(descriptor, id=resource_identity(descriptor))
            target = self._path(f"sha256/{descriptor.content_hash[:2]}/{descriptor.content_hash}")
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(temporary_path, target)
            except FileExistsError:
                self._verify_content(target, descriptor)
            metadata = self._path(f"descriptors/{descriptor.id.removeprefix('resource:')}.json")
            self._write_immutable(metadata, canonical_data_bytes(resource_to_data(descriptor)))
            return descriptor
        finally:
            temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _write_immutable(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        try:
            try:
                os.link(temporary_path, path)
            except FileExistsError:
                if (
                    path.stat().st_size != len(payload)
                    or read_bounded(path, len(payload)) != payload
                ):
                    raise ValueError("Immutable resource metadata identity was rebound") from None
        finally:
            temporary_path.unlink(missing_ok=True)

    def describe(self, reference: ResourceReference) -> DataResource:
        return self._resolve(reference)[1]

    def _resolve(self, reference: ResourceReference) -> tuple[ResourceStore, DataResource]:
        """Choose an owner by descriptor presence, never by whether its bytes verify."""
        digest = reference.id.removeprefix("resource:")
        if (
            not reference.id.startswith("resource:")
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ValueError("Resource identity is not a managed descriptor identity")
        relative = f"descriptors/{digest}.json"
        path = self._path(relative)
        try:
            # Check the actual directory entry, including a dangling local link.
            # Later failures (even a removal race) must not select another owner.
            (self.root / relative).lstat()
        except FileNotFoundError:
            if self.inputs is None:
                raise
            return self.inputs._resolve(reference)
        if path.stat().st_size > MAX_DESCRIPTOR_BYTES:
            raise ValueError("Resource descriptor is oversized")
        descriptor = resource_from_data(json.loads(read_bounded(path, MAX_DESCRIPTOR_BYTES)))
        if descriptor.reference != reference or resource_identity(descriptor) != descriptor.id:
            raise ValueError("Resource descriptor hash or identity mismatch")
        return self, descriptor

    def descriptors(self) -> tuple[DataResource, ...]:
        directory = self._path("descriptors")
        if not directory.exists():
            return ()
        records = []
        for path in sorted(directory.glob("*.json")):
            path = self._path(f"descriptors/{path.name}")
            if path.stat().st_size > MAX_DESCRIPTOR_BYTES:
                raise ValueError("Resource descriptor is oversized")
            descriptor = resource_from_data(json.loads(read_bounded(path, MAX_DESCRIPTOR_BYTES)))
            identity = resource_identity(descriptor)
            if (
                descriptor.id != identity
                or path.name != f"{identity.removeprefix('resource:')}.json"
            ):
                raise ValueError("Local resource descriptor filename or identity mismatch")
            records.append(descriptor)
        return tuple(records)

    @staticmethod
    def _verify_content(path: Path, descriptor: DataResource) -> None:
        if path.stat().st_size != descriptor.byte_size:
            raise ValueError("Resource content hash or byte size mismatch")
        digest = hashlib.sha256()
        remaining = descriptor.byte_size + 1
        with path.open("rb") as stream:
            while remaining and (chunk := stream.read(min(1024 * 1024, remaining))):
                remaining -= len(chunk)
                digest.update(chunk)
        if digest.hexdigest() != descriptor.content_hash or remaining != 1:
            raise ValueError("Resource content hash or byte size mismatch")

    def verified_path(self, reference: ResourceReference) -> Path:
        """For file-oriented backends; reverify if another process can edit storage."""
        owner, descriptor = self._resolve(reference)
        path = owner._path(f"sha256/{descriptor.content_hash[:2]}/{descriptor.content_hash}")
        self._verify_content(path, descriptor)
        return path

    def read(self, reference: ResourceReference) -> bytes:
        descriptor = self.describe(reference)
        if descriptor.byte_size > MAX_RESOURCE_READ_BYTES:
            raise ValueError(
                "Resource exceeds in-memory read bound; use verified_path with a streaming backend"
            )
        data = read_bounded(self.verified_path(reference), descriptor.byte_size)
        if (
            len(data) != descriptor.byte_size
            or hashlib.sha256(data).hexdigest() != descriptor.content_hash
        ):
            raise ValueError("Resource changed during reading")
        return data
