"""Cross-process project authority leases with crash-safe OS ownership."""

from __future__ import annotations

import json
import os
import sys
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from code_visualizer.config import PRODUCT

MAX_LEASE_METADATA_BYTES = 16 * 1024


class ProjectLeaseConflict(RuntimeError):
    def __init__(self, root: Path, owner: dict[str, object]) -> None:
        self.root = root
        self.owner = owner
        endpoint = owner.get("endpoint")
        suffix = f" Connect to {endpoint}." if isinstance(endpoint, str) and endpoint else ""
        super().__init__(f"Another authority owns {root}.{suffix} Open read-only instead.")


def _try_lock(stream: BinaryIO) -> None:
    stream.seek(0)
    if sys.platform == "win32":
        import msvcrt

        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise BlockingIOError from exc
    else:
        import fcntl

        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise BlockingIOError from exc


def _unlock(stream: BinaryIO) -> None:
    stream.seek(0)
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _read_metadata(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as stream:
            stream.seek(1)
            source = stream.read(MAX_LEASE_METADATA_BYTES + 1)
        if len(source) > MAX_LEASE_METADATA_BYTES:
            return {"status": "metadata-too-large"}
        raw: object = json.loads(source.decode("utf-8"))
        return (
            {str(key): value for key, value in raw.items()}
            if isinstance(raw, dict)
            else {"status": "metadata-invalid"}
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"status": "owner-metadata-unavailable"}


@dataclass(slots=True)
class ProjectLease:
    root: Path
    path: Path
    owner_id: str
    _stream: BinaryIO | None
    _endpoint: str | None = None

    @classmethod
    def acquire(
        cls,
        root: Path,
        *,
        owner_id: str | None = None,
        endpoint: str | None = None,
    ) -> ProjectLease:
        resolved = root.resolve()
        state_root = resolved / PRODUCT.state_directory
        state_root.mkdir(parents=True, exist_ok=True)
        path = state_root / "authority.lock"
        stream = path.open("a+b")
        try:
            stream.seek(0, os.SEEK_END)
            if stream.tell() < 2:
                stream.seek(0)
                stream.write(b"\0{}")
                stream.flush()
            _try_lock(stream)
        except BlockingIOError as exc:
            stream.close()
            raise ProjectLeaseConflict(resolved, _read_metadata(path)) from exc
        except BaseException:
            stream.close()
            raise
        lease = cls(resolved, path, owner_id or f"authority_{uuid4().hex}", stream, endpoint)
        lease._write_metadata()
        return lease

    @property
    def endpoint(self) -> str | None:
        return self._endpoint

    @property
    def is_active(self) -> bool:
        return self._stream is not None

    def update_endpoint(self, endpoint: str | None) -> None:
        if self._stream is None:
            raise RuntimeError("Cannot update a released project lease")
        self._endpoint = endpoint
        self._write_metadata()

    def metadata(self) -> dict[str, object]:
        return _read_metadata(self.path)

    def release(self) -> None:
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            # A test runner or interpreter shutdown can close the underlying
            # descriptor before finalization reaches the lease. The OS has
            # already released the lock in that case, so finalization remains
            # idempotent and deliberately quiet.
            with suppress(OSError, ValueError):
                _unlock(stream)
        finally:
            with suppress(OSError, ValueError):
                stream.close()

    def _write_metadata(self) -> None:
        stream = self._stream
        if stream is None:
            return
        payload = json.dumps(
            {
                "endpoint": self._endpoint,
                "owner_id": self.owner_id,
                "pid": os.getpid(),
                "started_at": datetime.now(UTC).isoformat(),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        stream.seek(1)
        stream.truncate()
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())

    def __enter__(self) -> ProjectLease:
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()

    def __del__(self) -> None:
        with suppress(OSError, ValueError):
            self.release()
