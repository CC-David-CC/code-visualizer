"""Bounded private worker pipes and ownership of the entire child process tree.

Commands are trusted composition values. This module knows no project authority,
backend semantics, or persisted callbacks. The worker must open its channel before
loading implementation code; the startup gate establishes process-tree ownership.
"""

from __future__ import annotations

import ctypes
import os
import signal
import struct
import subprocess
import sys
import threading
import time
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from code_visualizer.domain.boundaries import MAX_PORTABLE_ENVELOPE_BYTES

_GATE = b"G"
_HEADER = struct.Struct("!I")
_STDERR_LIMIT = 64 * 1024
_WINDOWS = sys.platform == "win32"


class WorkerProtocolError(ValueError):
    pass


class WorkerExited(RuntimeError):
    def __init__(self, return_code: int, stderr: str) -> None:
        self.return_code = return_code
        self.stderr = stderr
        super().__init__(f"Worker exited with code {return_code}: {stderr}")


@dataclass(frozen=True, slots=True)
class WorkerProfile:
    """An explicit static composition profile, supplied by the host application."""

    id: str
    version: str
    command: tuple[str, ...]
    backend_keys: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.id or not self.version:
            raise ValueError("A worker profile requires identity and version")
        if (
            type(self.command) is not tuple
            or not self.command
            or any(
                not isinstance(value, str) or not value or "\0" in value for value in self.command
            )
        ):
            raise ValueError("A worker command must be a nonempty immutable argument vector")
        if (
            type(self.backend_keys) is not tuple
            or any(
                type(key) is not tuple
                or len(key) != 2
                or any(not isinstance(value, str) or not value for value in key)
                for key in self.backend_keys
            )
            or len(set(self.backend_keys)) != len(self.backend_keys)
        ):
            raise ValueError("Worker backend contracts must be unique exact identity/version pairs")


def profile_for_backend(
    profiles: tuple[WorkerProfile, ...], backend_id: str, backend_version: str
) -> WorkerProfile:
    identities = [(profile.id, profile.version) for profile in profiles]
    contracts = [key for profile in profiles for key in profile.backend_keys]
    if len(identities) != len(set(identities)) or len(contracts) != len(set(contracts)):
        raise ValueError("Duplicate worker profile or ambiguous backend strategy registration")
    for profile in profiles:
        if (backend_id, backend_version) in profile.backend_keys:
            return profile
    raise ValueError(f"No process strategy registered for {backend_id}@{backend_version}")


def _read_exact(stream: IO[bytes], size: int, *, allow_eof: bool = False) -> bytes:
    parts: list[bytes] = []
    remaining = size
    while remaining:
        part = stream.read(remaining)
        if not part:
            if allow_eof and remaining == size:
                raise EOFError
            raise WorkerProtocolError("Truncated worker frame")
        parts.append(part)
        remaining -= len(part)
    return b"".join(parts)


def read_worker_frame(stream: IO[bytes]) -> bytes:
    size = _HEADER.unpack(_read_exact(stream, _HEADER.size, allow_eof=True))[0]
    if not 0 < size <= MAX_PORTABLE_ENVELOPE_BYTES:
        raise WorkerProtocolError("Worker frame exceeds its bounded portable envelope")
    return _read_exact(stream, size)


def write_worker_frame(stream: IO[bytes], payload: bytes) -> None:
    if type(payload) is not bytes or not 0 < len(payload) <= MAX_PORTABLE_ENVELOPE_BYTES:
        raise WorkerProtocolError("Worker frame must contain bounded immutable bytes")
    for part in (_HEADER.pack(len(payload)), payload):
        offset = 0
        while offset < len(part):
            written = stream.write(part[offset:])
            if written is None or written <= 0:
                raise WorkerProtocolError("Worker stream stopped accepting a frame")
            offset += written
    stream.flush()


class WorkerChannel:
    """Worker-side channel; stdout, including native writes, is a separate stream."""

    def __init__(self, incoming: IO[bytes], outgoing: IO[bytes]) -> None:
        self.incoming = incoming
        self.outgoing = outgoing
        self._write_lock = threading.Lock()

    def receive(self) -> bytes:
        return read_worker_frame(self.incoming)

    def send(self, payload: bytes) -> None:
        with self._write_lock:
            write_worker_frame(self.outgoing, payload)

    def close(self) -> None:
        self.incoming.close()
        self.outgoing.close()


def open_worker_channel() -> WorkerChannel:
    """Call before static backend composition or any submitted work is evaluated."""
    incoming = os.fdopen(os.dup(0), "rb", buffering=0)
    outgoing = os.fdopen(os.dup(1), "wb", buffering=0)
    os.dup2(2, 1)
    with open(os.devnull, "rb") as empty:
        os.dup2(empty.fileno(), 0)
    if _read_exact(incoming, 1) != _GATE:
        incoming.close()
        outgoing.close()
        raise WorkerProtocolError("Worker startup gate was not admitted")
    return WorkerChannel(incoming, outgoing)


class _WindowsJob:
    """One kill-on-close job; the child is gated until assignment succeeds."""

    def __init__(self, pid: int) -> None:
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("process_time", ctypes.c_longlong),
                ("job_time", ctypes.c_longlong),
                ("flags", wintypes.DWORD),
                ("minimum", ctypes.c_size_t),
                ("maximum", ctypes.c_size_t),
                ("process_limit", wintypes.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority", wintypes.DWORD),
                ("scheduling", wintypes.DWORD),
            ]

        class Counters(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_ulonglong)
                for name in (
                    "reads",
                    "writes",
                    "others",
                    "read_bytes",
                    "write_bytes",
                    "other_bytes",
                )
            ]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("basic", BasicLimits),
                ("io", Counters),
                ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t),
                ("peak_process_memory", ctypes.c_size_t),
                ("peak_job_memory", ctypes.c_size_t),
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.TerminateJobObject.restype = wintypes.BOOL
        kernel.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.c_void_p,
        ]
        kernel.QueryInformationJobObject.restype = wintypes.BOOL
        kernel.IsProcessInJob.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.BOOL),
        ]
        kernel.IsProcessInJob.restype = wintypes.BOOL
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        self._kernel = kernel
        self._handle = kernel.CreateJobObjectW(None, None)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            limits = ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not kernel.SetInformationJobObject(
                self._handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            handle = kernel.OpenProcess(0x0100 | 0x0001, False, pid)
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                if not kernel.AssignProcessToJobObject(self._handle, handle):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                kernel.CloseHandle(handle)
        except BaseException:
            self.close()
            raise

    def terminate(self) -> None:
        if self._handle and not self._kernel.TerminateJobObject(self._handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        handle, self._handle = self._handle, None
        if handle:
            self._kernel.CloseHandle(handle)

    def wait_for_exit(self, timeout: float = 5.0) -> None:
        """Wait for all associated processes, independently of open process handles."""
        from ctypes import wintypes

        deadline = time.monotonic() + timeout
        waited: set[int] = set()
        while True:
            capacity = 64
            while True:
                if capacity * ctypes.sizeof(ctypes.c_size_t) > MAX_PORTABLE_ENVELOPE_BYTES:
                    raise WorkerProtocolError("Owned process list exceeds its supervision envelope")
                buffer = ctypes.create_string_buffer(8 + capacity * ctypes.sizeof(ctypes.c_size_t))
                if self._kernel.QueryInformationJobObject(
                    self._handle, 3, buffer, ctypes.sizeof(buffer), None
                ):
                    break
                if ctypes.get_last_error() != 234:  # ERROR_MORE_DATA
                    raise ctypes.WinError(ctypes.get_last_error())
                capacity *= 2
            count = ctypes.cast(buffer, ctypes.POINTER(wintypes.DWORD))[1]
            ids = set((ctypes.c_size_t * count).from_buffer(buffer, 8))
            fresh = ids - waited
            if not fresh:
                return
            for pid in fresh:
                handle = self._kernel.OpenProcess(0x00100000 | 0x1000, False, pid)
                if not handle:
                    if ctypes.get_last_error() == 87:  # Exited process no longer has an ID.
                        continue
                    raise ctypes.WinError(ctypes.get_last_error())
                try:
                    belongs = wintypes.BOOL()
                    if not self._kernel.IsProcessInJob(handle, self._handle, ctypes.byref(belongs)):
                        raise ctypes.WinError(ctypes.get_last_error())
                    if not belongs.value:  # An exited PID may already have been reused.
                        continue
                    remaining = max(0, int((deadline - time.monotonic()) * 1000))
                    result = self._kernel.WaitForSingleObject(handle, remaining)
                    if result == 258:
                        raise TimeoutError("Owned worker descendants did not finish shutdown")
                    if result != 0:
                        raise ctypes.WinError(ctypes.get_last_error())
                finally:
                    self._kernel.CloseHandle(handle)
            waited.update(fresh)


def _resume_windows_initial_thread(pid: int) -> None:
    """Resume the owned suspended process after its Job is assigned.

    Popen closes CreateProcess's primary-thread handle. The oldest thread of the
    still-suspended process is that initial thread; ambiguity is a startup failure.
    Toolhelp and ResumeThread are documented Win32 APIs, with no global hooks.
    """
    from ctypes import wintypes

    class ThreadEntry(ctypes.Structure):
        _fields_ = [
            ("size", wintypes.DWORD),
            ("usage", wintypes.DWORD),
            ("thread_id", wintypes.DWORD),
            ("owner_id", wintypes.DWORD),
            ("base_priority", wintypes.LONG),
            ("delta_priority", wintypes.LONG),
            ("flags", wintypes.DWORD),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
    kernel.Thread32First.restype = wintypes.BOOL
    kernel.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
    kernel.Thread32Next.restype = wintypes.BOOL
    kernel.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenThread.restype = wintypes.HANDLE
    kernel.GetThreadTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetThreadTimes.restype = wintypes.BOOL
    kernel.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel.ResumeThread.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel.CreateToolhelp32Snapshot(0x00000004, 0)  # TH32CS_SNAPTHREAD
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    handles: list[tuple[int, int]] = []
    try:
        entry = ThreadEntry()
        entry.size = ctypes.sizeof(entry)
        found = kernel.Thread32First(snapshot, ctypes.byref(entry))
        while found:
            if entry.owner_id == pid:
                handle = kernel.OpenThread(0x0002 | 0x0800, False, entry.thread_id)
                if not handle:
                    raise ctypes.WinError(ctypes.get_last_error())
                created, ended, system, user = (wintypes.FILETIME() for _ in range(4))
                if not kernel.GetThreadTimes(
                    handle,
                    ctypes.byref(created),
                    ctypes.byref(ended),
                    ctypes.byref(system),
                    ctypes.byref(user),
                ):
                    kernel.CloseHandle(handle)
                    raise ctypes.WinError(ctypes.get_last_error())
                handles.append(((created.dwHighDateTime << 32) | created.dwLowDateTime, handle))
            entry.size = ctypes.sizeof(entry)
            found = kernel.Thread32Next(snapshot, ctypes.byref(entry))
        if not handles:
            raise WorkerProtocolError("Suspended worker has no identifiable initial thread")
        oldest = min(created for created, _handle in handles)
        initial = [handle for created, handle in handles if created == oldest]
        if len(initial) != 1:
            raise WorkerProtocolError("Suspended worker has ambiguous initial thread ownership")
        previous = kernel.ResumeThread(initial[0])
        if previous == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        if previous != 1:
            raise WorkerProtocolError("Worker initial thread was not suspended exactly once")
    finally:
        for _created, handle in handles:
            kernel.CloseHandle(handle)
        kernel.CloseHandle(snapshot)


class OwnedProcessTree:
    """Process-tree ownership reused by computation and the existing Python worker."""

    def __init__(self, process: subprocess.Popen[bytes] | subprocess.Popen[str]) -> None:
        self.process = process
        self._job = _WindowsJob(process.pid) if _WINDOWS else None
        self._lock = threading.RLock()
        self._closed = False
        if _WINDOWS:
            try:
                _resume_windows_initial_thread(process.pid)
            except BaseException:
                self.close()
                raise

    @staticmethod
    def popen_options() -> dict[str, int | bool]:
        if _WINDOWS:
            return {
                "creationflags": (
                    subprocess.CREATE_NEW_PROCESS_GROUP
                    | subprocess.CREATE_NO_WINDOW
                    | 0x00000004  # CREATE_SUSPENDED: Job ownership precedes redirector children.
                )
            }
        return {"start_new_session": True}

    def terminate(self) -> None:
        with self._lock:
            if self._closed:
                return
            if self._job is not None:
                self._job.terminate()
            else:
                if not hasattr(os, "killpg") or not hasattr(signal, "SIGKILL"):
                    raise RuntimeError("This platform has no owned process-group termination")
                with suppress(ProcessLookupError):
                    os.killpg(self.process.pid, signal.SIGKILL)
            if self.process.poll() is None:
                self.process.wait(timeout=5)
            if self._job is not None:
                self._job.wait_for_exit()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                self.terminate()
            finally:
                if self._job is not None:
                    self._job.close()
                    self._job = None
                self._closed = True


class WorkerProcess:
    def __init__(
        self,
        profile: WorkerProfile,
        *,
        working_directory: Path | None = None,
        environment: dict[str, str] | None = None,
        queue_bytes: int = MAX_PORTABLE_ENVELOPE_BYTES,
    ) -> None:
        if type(queue_bytes) is not int or queue_bytes < MAX_PORTABLE_ENVELOPE_BYTES:
            raise ValueError("Worker queue must admit one complete portable envelope")
        self.profile = profile
        self.working_directory = working_directory
        self.environment = environment
        self.queue_bytes = queue_bytes
        self._process: subprocess.Popen[bytes] | None = None
        self._tree: OwnedProcessTree | None = None
        self._condition = threading.Condition()
        self._write_lock = threading.Lock()
        self._frames: deque[bytes] = deque()
        self._queued_bytes = 0
        self._error: BaseException | None = None
        self._closed = False
        self._stderr = bytearray()
        self._stderr_truncated = False
        self._cancelled = threading.Event()
        self._cancellation_acknowledged = threading.Event()
        self._finalization_expected = False
        self._exited = threading.Event()
        self._stderr_drained = threading.Event()
        self._forced_termination = False

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else None

    @property
    def is_active(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def forced_termination(self) -> bool:
        return self._forced_termination

    @property
    def cancellation_acknowledged(self) -> bool:
        return self._cancellation_acknowledged.is_set()

    @property
    def buffered_bytes(self) -> int:
        with self._condition:
            return self._queued_bytes

    @property
    def stderr(self) -> str:
        with self._condition:
            prefix = "[worker stderr truncated]\n" if self._stderr_truncated else ""
            return prefix + self._stderr.decode("utf-8", errors="replace")

    def start(self) -> None:
        if self._process is not None or self._closed:
            raise ValueError("A worker process starts exactly once")
        options = OwnedProcessTree.popen_options()
        process = subprocess.Popen(
            self.profile.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.working_directory,
            env=None if self.environment is None else {**os.environ, **self.environment},
            creationflags=int(options.get("creationflags", 0)),
            start_new_session=bool(options.get("start_new_session", False)),
        )
        self._process = process
        try:
            self._tree = OwnedProcessTree(process)
            assert process.stdin is not None
            process.stdin.write(_GATE)
            process.stdin.flush()
        except BaseException:
            self._forced_termination = process.poll() is None
            process.kill()
            process.wait(timeout=5)
            self.close()
            raise
        threading.Thread(target=self._drain, daemon=True, name="computation-worker-events").start()
        threading.Thread(
            target=self._drain_stderr, daemon=True, name="computation-worker-stderr"
        ).start()
        threading.Thread(
            target=self._watch_exit, daemon=True, name="computation-worker-exit"
        ).start()

    def _watch_exit(self) -> None:
        assert self._process is not None
        self._process.wait()
        tree = self._tree
        try:
            if tree is not None:
                tree.close()
        except BaseException as exc:
            with self._condition:
                self._error = exc
                self._condition.notify_all()
        finally:
            self._exited.set()

    def send(self, payload: bytes) -> None:
        process = self._process
        if process is None or process.stdin is None or self._closed:
            raise ValueError("Worker channel is not active")
        with self._write_lock:
            write_worker_frame(process.stdin, payload)

    def receive(self, timeout: float | None = None) -> bytes:
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while not self._frames:
                if self._error is not None:
                    raise self._error
                if self._closed:
                    raise ValueError("Worker channel was closed")
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise TimeoutError("Timed out waiting for worker event")
                self._condition.wait(remaining)
            payload = self._frames.popleft()
            self._queued_bytes -= len(payload)
            self._condition.notify_all()
            return payload

    def _drain(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        process = self._process
        try:
            while True:
                assert process.stdout is not None
                payload = read_worker_frame(process.stdout)
                with self._condition:
                    while not self._closed and (
                        self._queued_bytes + len(payload) > self.queue_bytes
                        or len(self._frames) >= 256
                    ):
                        self._condition.wait()
                    if self._closed:
                        return
                    self._frames.append(payload)
                    self._queued_bytes += len(payload)
                    self._condition.notify_all()
        except EOFError:
            code = process.wait()
            self._exited.wait()
            self._stderr_drained.wait()
            error: BaseException = WorkerExited(code, self.stderr)
        except BaseException as exc:
            error = exc
            self._force_stop()
        with self._condition:
            if self._error is None:
                self._error = error
            self._condition.notify_all()

    def _drain_stderr(self) -> None:
        assert self._process is not None and self._process.stderr is not None
        try:
            while chunk := self._process.stderr.read(4096):
                with self._condition:
                    self._stderr.extend(chunk)
                    if len(self._stderr) > _STDERR_LIMIT:
                        del self._stderr[:-_STDERR_LIMIT]
                        self._stderr_truncated = True
        finally:
            self._stderr_drained.set()

    def cancel(self, payload: bytes, *, grace_seconds: float = 0.5) -> None:
        if not 0 <= grace_seconds <= 60:
            raise ValueError("Worker cancellation grace must be between zero and 60 seconds")
        if self._cancelled.is_set():
            return
        self._cancelled.set()

        def notify() -> None:
            with suppress(OSError, ValueError):
                self.send(payload)

        def escalate() -> None:
            if self._cancellation_acknowledged.wait(grace_seconds):
                return
            self._force_stop()

        threading.Thread(target=notify, daemon=True, name="computation-worker-cancel").start()
        threading.Thread(target=escalate, daemon=True, name="computation-worker-escalation").start()

    def _force_stop(self) -> None:
        tree = self._tree
        if tree is not None and self.is_active:
            self._forced_termination = True
            tree.terminate()

    def acknowledge_cancellation(self) -> None:
        """Disarm cooperative grace after an admitted cancelled proposal.

        The host calls expect_exit only after securing the result and sending its
        terminal ACK. Resource admission is not backend finalization time.
        """
        if not self._cancelled.is_set():
            raise ValueError("No cancellation was requested from this worker")
        if self._cancellation_acknowledged.is_set():
            return
        self._cancellation_acknowledged.set()

    def expect_exit(self, *, timeout: float = 5.0) -> None:
        """Bound final verification after any admitted terminal proposal.

        Repeated acknowledgements cannot extend the first deadline. A backend
        that hangs while verifying completion is terminated with its descendants.
        """
        if not 0 < timeout <= 60:
            raise ValueError("Terminal verification requires a bounded positive timeout")
        with self._condition:
            if self._finalization_expected:
                return
            self._finalization_expected = True

        def finalize() -> None:
            if not self._exited.wait(timeout):
                self._force_stop()

        threading.Thread(
            target=finalize, daemon=True, name="computation-worker-finalization"
        ).start()

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._condition.notify_all()
        tree, self._tree = self._tree, None
        if tree is not None:
            if self.is_active:
                self._forced_termination = True
            tree.close()
        process = self._process
        if process is not None:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()

    def __enter__(self) -> WorkerProcess:
        self.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
