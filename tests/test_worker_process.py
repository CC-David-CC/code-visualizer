"""Private worker transport bounds and real process-tree ownership."""

import ctypes
import io
import os
import struct
import sys
import time
from pathlib import Path

import pytest

from code_visualizer.domain.boundaries import MAX_PORTABLE_ENVELOPE_BYTES
from code_visualizer.execution.worker_process import (
    OwnedProcessTree,
    WorkerExited,
    WorkerProcess,
    WorkerProfile,
    WorkerProtocolError,
    profile_for_backend,
    read_worker_frame,
    write_worker_frame,
)


def _profile(tmp_path, body):
    script = tmp_path / "trusted_worker.py"
    source = str(Path(__file__).resolve().parents[1] / "src")
    script.write_text(
        f"import sys\nsys.path.insert(0, {source!r})\n"
        "from code_visualizer.execution.worker_process import open_worker_channel\n"
        "channel = open_worker_channel()\n" + body,
        encoding="utf-8",
    )
    return WorkerProfile(
        "test-composition",
        "1",
        (sys.executable, "-I", str(script)),
        (("org.example.backend", "1"),),
    )


def _terminated(pid):
    if sys.platform == "win32":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            return True
        try:
            return kernel.WaitForSingleObject(handle, 0) == 0
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def test_frames_reject_truncation_and_oversized_headers_before_reading_payload():
    stream = io.BytesIO()
    write_worker_frame(stream, b"hello")
    stream.seek(0)
    assert read_worker_frame(stream) == b"hello"
    with pytest.raises(EOFError):
        read_worker_frame(stream)
    for payload in (
        b"\0",
        struct.pack("!I", 4) + b"abc",
        struct.pack("!I", MAX_PORTABLE_ENVELOPE_BYTES + 1),
    ):
        with pytest.raises(WorkerProtocolError):
            read_worker_frame(io.BytesIO(payload))


def test_frame_writer_preserves_all_bytes_across_short_pipe_writes():
    class ShortWrites(io.BytesIO):
        def write(self, data):
            return super().write(data[:3])

    stream = ShortWrites()
    write_worker_frame(stream, b"a complete framed payload")
    stream.seek(0)
    assert read_worker_frame(stream) == b"a complete framed payload"


def test_profiles_resolve_only_exact_static_backend_contracts(tmp_path):
    profile = _profile(tmp_path, "")
    assert profile_for_backend((profile,), "org.example.backend", "1") == profile
    with pytest.raises(ValueError, match="No process strategy"):
        profile_for_backend((profile,), "org.example.backend", "2")
    with pytest.raises(ValueError, match="Duplicate worker"):
        profile_for_backend((profile, profile), "org.example.backend", "1")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows suspended startup boundary")
def test_windows_worker_stays_suspended_until_its_entire_launcher_tree_is_owned(tmp_path):
    import subprocess

    marker = tmp_path / "started"
    options = OwnedProcessTree.popen_options()
    process = subprocess.Popen(
        [sys.executable, "-I", "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"],
        creationflags=int(options["creationflags"]),
    )
    owned = None
    try:
        # The venv redirector itself cannot spawn its real interpreter yet.
        with pytest.raises(subprocess.TimeoutExpired):
            process.wait(timeout=0.1)
        assert not marker.exists()
        owned = OwnedProcessTree(process)
        assert process.wait(timeout=5) == 0
        assert marker.exists()
    finally:
        if owned is not None:
            owned.close()
        elif process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_worker_protocol_survives_python_and_native_stdout(tmp_path):
    profile = _profile(
        tmp_path,
        "import os\nprint('python text', flush=True)\nos.write(1, b'native text\\n')\n"
        "channel.send(channel.receive()[::-1])\n",
    )
    with WorkerProcess(profile) as worker:
        worker.send(b"hello")
        assert worker.receive(5) == b"olleh"
        with pytest.raises(WorkerExited) as ended:
            worker.receive(5)
        assert ended.value.return_code == 0
    assert "native text" in worker.stderr
    assert "python text" in worker.stderr


def test_worker_crash_is_explicit_and_retains_queued_events(tmp_path):
    profile = _profile(tmp_path, "import os\nchannel.send(b'before crash')\nos._exit(23)\n")
    with WorkerProcess(profile) as worker:
        assert worker.receive(5) == b"before crash"
        with pytest.raises(WorkerExited) as ended:
            worker.receive(5)
        assert ended.value.return_code == 23
        assert not worker.forced_termination


def test_invalid_frame_terminates_the_worker_and_reports_actual_force(tmp_path):
    profile = _profile(
        tmp_path,
        "import struct\n"
        f"channel.outgoing.write(struct.pack('!I', {MAX_PORTABLE_ENVELOPE_BYTES + 1}))\n"
        "channel.outgoing.flush()\nwhile True:\n    pass\n",
    )
    with WorkerProcess(profile) as worker:
        with pytest.raises(WorkerProtocolError, match="portable envelope"):
            worker.receive(5)
        assert worker.forced_termination
        assert not worker.is_active


def test_slow_consumer_has_bounded_queue_and_cancellation_still_completes(tmp_path):
    profile = _profile(tmp_path, "while True:\n    channel.send(b'x' * 65536)\n")
    with WorkerProcess(profile) as worker:
        deadline = time.monotonic() + 5
        while worker.buffered_bytes < MAX_PORTABLE_ENVELOPE_BYTES and time.monotonic() < deadline:
            time.sleep(0.01)
        assert worker.buffered_bytes == MAX_PORTABLE_ENVELOPE_BYTES
        started = time.monotonic()
        worker.cancel(b"cancel", grace_seconds=0.05)
        assert time.monotonic() - started < 0.2
        deadline = time.monotonic() + 5
        while worker.is_active and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not worker.is_active
        assert worker.buffered_bytes <= MAX_PORTABLE_ENVELOPE_BYTES


def test_uncooperative_worker_and_its_descendant_are_cancelled(tmp_path):
    profile = _profile(
        tmp_path,
        "import subprocess\nchild = subprocess.Popen([sys.executable, '-c', "
        "'import time; time.sleep(60)'])\nchannel.send(str(child.pid).encode())\n"
        "while True:\n    pass\n",
    )
    with WorkerProcess(profile) as worker:
        descendant = int(worker.receive(5))
        assert not _terminated(descendant)
        worker.cancel(b"cancel", grace_seconds=0.05)
        deadline = time.monotonic() + 5
        while (worker.is_active or not _terminated(descendant)) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not worker.is_active
        assert _terminated(descendant)


def test_worker_exit_also_terminates_its_remaining_descendants(tmp_path):
    profile = _profile(
        tmp_path,
        "import subprocess\nchild = subprocess.Popen([sys.executable, '-c', "
        "'import time; time.sleep(60)'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "channel.send(str(child.pid).encode())\n",
    )
    with WorkerProcess(profile) as worker:
        descendant = int(worker.receive(5))
        with pytest.raises(WorkerExited):
            worker.receive(5)
    deadline = time.monotonic() + 5
    while not _terminated(descendant) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert _terminated(descendant)


def test_terminal_verification_has_a_deadline_without_a_cancel_request(tmp_path):
    profile = _profile(tmp_path, "channel.send(b'proposal')\nwhile True:\n    pass\n")
    with WorkerProcess(profile) as worker:
        assert worker.receive(5) == b"proposal"
        worker.expect_exit(timeout=0.05)
        # Repeated acknowledgements must never extend the first deadline.
        worker.expect_exit(timeout=60)
        with pytest.raises(WorkerExited):
            worker.receive(5)
        assert worker.forced_termination
        assert not worker.cancellation_acknowledged


def test_acknowledged_cancel_finishes_without_false_forced_termination(tmp_path):
    profile = _profile(
        tmp_path,
        "channel.send(b'ready')\n"
        "assert channel.receive() == b'cancel'\n"
        "channel.send(b'cancelled proposal')\n"
        "assert channel.receive() == b'secured'\n"
        "channel.send(b'verified')\n",
    )
    with WorkerProcess(profile) as worker:
        assert worker.receive(5) == b"ready"
        worker.cancel(b"cancel", grace_seconds=1)
        assert worker.receive(5) == b"cancelled proposal"
        worker.acknowledge_cancellation()
        assert not worker._finalization_expected
        worker.send(b"secured")
        worker.expect_exit(timeout=5)
        assert worker.receive(5) == b"verified"
        with pytest.raises(WorkerExited) as ended:
            worker.receive(5)
        assert ended.value.return_code == 0
        assert worker.cancellation_acknowledged
        assert not worker.forced_termination
