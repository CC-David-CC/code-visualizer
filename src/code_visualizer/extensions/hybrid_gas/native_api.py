"""Private, pinned native implementation boundary used inside computation workers.

There is no project-selected DLL or native command file. A trusted gas adapter
forms commands from its validated derived definition. Canonical objects remain
ordinary Python/domain values; this C ABI is a real implementation boundary.
"""

from __future__ import annotations

import ctypes as c
import platform
import sys
from dataclasses import dataclass
from hashlib import sha256
from importlib.resources import files
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

BINARY_SHA = "6766e00788fe453010ba5fe830d4234ec4e38af377d6142abe100088161fc2c0"
SPECIES_SHA = "754b4d8d9ca22155310f0e253664abc99e8124e35f7b0fb52444eff1828d04a6"
COLLISION_SHA = "04d7ee96ba3bc764db4f1339c7fb8d8a55999e29511d490ac9a612bb62ffc599"
OBSERVATION_VERSION = 3


class NativeUnavailable(ValueError):
    """Missing or incompatible implementation, never a valid empty computation."""


@dataclass(frozen=True, slots=True)
class Installation:
    binary: Path
    species: Path
    collision: Path


def installation() -> Installation:
    if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise NativeUnavailable(
            "GAS_NATIVE_PLATFORM: this pinned native runtime is qualified on Windows x86-64 only"
        )
    root = Path(str(files("code_visualizer").joinpath("resources", "sparta")))
    selected = []
    for name, expected in (
        ("libsparta_p7serial.dll", BINARY_SHA),
        ("ar.species", SPECIES_SHA),
        ("ar.vss", COLLISION_SHA),
    ):
        path = root / name
        if not path.is_file() or sha256(path.read_bytes()).hexdigest() != expected:
            raise NativeUnavailable("GAS_NATIVE_IDENTITY: missing or changed installed " + name)
        selected.append(path)
    return Installation(*selected)


class NativeSparta:
    """Single-owner serial C instance; the host owns its enclosing worker process."""

    def __init__(self) -> None:
        self.installation = installation()
        try:
            self._dll = c.CDLL(str(self.installation.binary))
        except OSError as exc:
            raise NativeUnavailable("GAS_NATIVE_LOAD: " + str(exc)) from exc
        api = {
            "sparta_open_no_mpi": (c.c_void_p, (c.c_int, c.POINTER(c.c_char_p), c.c_void_p)),
            "sparta_close": (None, (c.c_void_p,)),
            "sparta_command": (c.c_void_p, (c.c_void_p, c.c_char_p)),
            "sparta_has_error": (c.c_int, (c.c_void_p,)),
            "sparta_get_last_error_message": (c.c_int, (c.c_void_p, c.c_char_p, c.c_int)),
            "sparta_extract_compute": (c.c_void_p, (c.c_void_p, c.c_char_p, c.c_int, c.c_int)),
            "sparta_extract_fix": (c.c_void_p, (c.c_void_p, c.c_char_p, c.c_int, c.c_int)),
            "sparta_extract_global": (c.c_void_p, (c.c_void_p, c.c_char_p)),
            "sparta_free": (None, (c.c_void_p,)),
            "cv_sparta_observe": (
                c.c_int,
                (c.c_void_p, c.POINTER(c.c_double), c.c_int, c.c_char_p, c.c_int),
            ),
            "cv_sparta_reservoir": (
                c.c_int,
                (
                    c.c_void_p,
                    c.c_char_p,
                    c.c_double,
                    c.c_double,
                    c.c_double,
                    c.c_double,
                    c.c_double,
                    c.c_char_p,
                    c.c_int,
                ),
            ),
            "cv_sparta_moments": (
                c.c_int,
                (
                    c.c_void_p,
                    c.c_double,
                    c.c_double,
                    c.c_int,
                    c.POINTER(c.c_double),
                    c.c_int,
                    c.c_char_p,
                    c.c_int,
                ),
            ),
        }
        for name, (result, arguments) in api.items():
            method = getattr(self._dll, name)
            method.restype, method.argtypes = result, arguments
        argv = (c.c_char_p * 5)(b"code-visualizer-gas", b"-screen", b"none", b"-log", b"none")
        self._handle = int(self._dll.sparta_open_no_mpi(len(argv), argv, None) or 0)
        if not self._handle:
            raise NativeUnavailable("GAS_NATIVE_LOAD: native instance creation failed")

    def _check(self) -> None:
        if not self._handle:
            raise ValueError("Native gas instance is closed")
        if self._dll.sparta_has_error(self._handle):
            error = c.create_string_buffer(4096)
            self._dll.sparta_get_last_error_message(self._handle, error, len(error))
            raise ValueError("GAS_NATIVE_FAILURE: " + error.value.decode("utf-8", errors="replace"))

    def _command(self, value: str) -> None:
        self._check()
        if "\n" in value or "\r" in value or "\0" in value:
            raise ValueError("The gas adapter submits one derived command at a time")
        self._dll.sparta_command(self._handle, value.encode("utf-8"))
        self._check()

    def _vector(self, name: str, count: int, *, fix: bool = False) -> NDArray[np.float64]:
        import numpy as np

        self._check()
        if type(count) is not int or not 1 <= count <= 64:
            raise ValueError("Native gas vector is outside its declared bound")
        method = self._dll.sparta_extract_fix if fix else self._dll.sparta_extract_compute
        pointer = method(self._handle, name.encode(), 0, 1)
        self._check()
        if not pointer:
            raise ValueError("Missing native gas vector: " + name)
        try:
            result = np.ctypeslib.as_array(c.cast(pointer, c.POINTER(c.c_double)), (count,)).copy()
            if not np.isfinite(result).all():
                raise ValueError("Nonfinite native gas vector")
            return result
        finally:
            if fix:
                self._dll.sparta_free(pointer)

    def _boundary(self) -> NDArray[np.float64]:
        import numpy as np

        self._check()
        pointer = self._dll.sparta_extract_compute(self._handle, b"cross", 0, 2)
        self._check()
        if not pointer:
            raise ValueError("Missing native measured boundary transfer")
        rows = c.cast(pointer, c.POINTER(c.POINTER(c.c_double)))
        result = np.array(
            [np.ctypeslib.as_array(rows[i], (6,)) for i in range(6)], dtype=np.float64
        )
        if not np.isfinite(result).all():
            raise ValueError("Nonfinite native measured boundary transfer")
        return result

    def particle_count(self) -> int:
        self._check()
        pointer = self._dll.sparta_extract_global(self._handle, b"nplocal")
        self._check()
        if not pointer:
            raise ValueError("Missing native serial particle count")
        return int(c.cast(pointer, c.POINTER(c.c_int))[0])

    def observation(self) -> NDArray[np.float64]:
        import numpy as np

        self._check()
        error = c.create_string_buffer(1024)
        method = self._dll.cv_sparta_observe
        size = int(method(self._handle, None, 0, error, len(error)))
        if not 0 < size <= 4_000_000:
            raise ValueError(
                error.value.decode() or "Native gas state exceeds its bounded interpretation"
            )
        result = np.empty(size, dtype=np.float64)
        copied = int(
            method(
                self._handle, result.ctypes.data_as(c.POINTER(c.c_double)), size, error, len(error)
            )
        )
        if copied != size or result[0] != OBSERVATION_VERSION or not np.isfinite(result).all():
            raise ValueError(
                error.value.decode() or "Native gas state changed or has incompatible meaning"
            )
        result.setflags(write=False)
        return result

    def _reservoir(
        self, name: str, density: float, temperature: float, velocity: tuple[float, float, float]
    ) -> None:
        self._check()
        if name not in ("low", "high"):
            raise ValueError("Unknown gas face reservoir")
        error = c.create_string_buffer(1024)
        status = self._dll.cv_sparta_reservoir(
            self._handle, name.encode(), density, temperature, *velocity, error, len(error)
        )
        self._check()
        if status:
            raise ValueError(error.value.decode() or "Native reservoir update failed")

    def moments(self, low: float, high: float, bins: int) -> NDArray[np.float64]:
        import numpy as np

        self._check()
        if type(bins) is not int or not 1 <= bins <= 512:
            raise ValueError("Native moments require 1..512 owned bins")
        error = c.create_string_buffer(1024)
        result = np.zeros((bins, 13), dtype=np.float64)
        status = self._dll.cv_sparta_moments(
            self._handle,
            low,
            high,
            bins,
            result.ctypes.data_as(c.POINTER(c.c_double)),
            result.size,
            error,
            len(error),
        )
        self._check()
        if status or not np.isfinite(result).all():
            raise ValueError(error.value.decode() or "Invalid native particle moments")
        result.setflags(write=False)
        return result

    def close(self) -> None:
        if self._handle:
            self._dll.sparta_close(self._handle)
            self._handle = 0

    def __enter__(self) -> NativeSparta:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
