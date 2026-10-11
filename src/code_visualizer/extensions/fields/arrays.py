"""Bounded NumPy files, read-only mappings and exact float64 header admission."""

from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING, cast

from code_visualizer.domain.resources import TensorDescriptor
from code_visualizer.domain.values import TensorDType, UnitReference
from code_visualizer.execution.backends import ProducedResource, ResolvedResource
from code_visualizer.extensions.fields.records import ARRAY_TYPE, CHUNK_BYTES

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


def array_resource(
    identity: str, values: NDArray[np.float64], *, unit: UnitReference | None = None
) -> ProducedResource:
    import numpy as np

    if (
        values.dtype != np.dtype("<f8")
        or not 1 <= values.ndim <= 2
        or not np.isfinite(values).all()
    ):
        raise ValueError("Field arrays require finite float64 vectors or matrices")
    if values.nbytes > CHUNK_BYTES - 128:
        raise ValueError("Field arrays exceed the 4 MiB chunk boundary")
    stream = BytesIO()
    np.save(stream, np.ascontiguousarray(values), allow_pickle=False)
    payload = stream.getvalue()
    if len(payload) > CHUNK_BYTES:
        raise ValueError("Field array header exceeds its chunk allowance")
    return ProducedResource(
        identity,
        payload,
        "application/x-npy",
        tensor=TensorDescriptor(TensorDType.FLOAT64, tuple(values.shape), unit=unit),
        logical_type=ARRAY_TYPE,
    )


def read_array(resource: ResolvedResource, shape: tuple[int, ...]) -> NDArray[np.float64]:
    """No pickle, object dtype, guessed shape, mutable file, or whole-history load."""
    import numpy as np

    descriptor = resource.descriptor
    if descriptor.logical_type != ARRAY_TYPE or descriptor.media_type != "application/x-npy":
        raise ValueError("Not a versioned field numeric array")
    if (
        descriptor.byte_size > CHUNK_BYTES
        or descriptor.tensor is None
        or (descriptor.tensor.dtype != TensorDType.FLOAT64 or descriptor.tensor.shape != shape)
    ):
        raise ValueError("Field numeric descriptor has an incompatible shape/dtype/size")
    # Admit the header before load/mmap can allocate or expose an attacker-selected
    # shape. Version 1.0 is the exact emitted format for this bounded fragment.
    with resource.open() as stream:
        if np.lib.format.read_magic(stream) != (1, 0):
            raise ValueError("Unsupported field array format")
        actual, fortran, dtype = np.lib.format.read_array_header_1_0(stream, max_header_size=1024)
        offset = stream.tell()
        if actual != shape or fortran or dtype != np.dtype("<f8"):
            raise ValueError("Numeric header differs from the declared field shape/dtype")
        if offset + int(np.prod(shape)) * 8 != descriptor.byte_size:
            raise ValueError("Numeric file has trailing or missing bytes")
    if resource.file is not None:
        values = np.load(
            resource.file.path, mmap_mode="r", allow_pickle=False, max_header_size=1024
        )
    else:
        with resource.open() as stream:
            values = np.load(stream, allow_pickle=False, max_header_size=1024)
        values.setflags(write=False)
    if not np.isfinite(values).all():
        raise ValueError("Field array contains nonfinite values")
    return cast("NDArray[np.float64]", values)
