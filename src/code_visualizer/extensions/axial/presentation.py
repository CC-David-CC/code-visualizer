"""Independent bounded consumption of derived axial coordinates and equilibrium."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.values import ResourceReference
from code_visualizer.execution.backends import ResolvedResource
from code_visualizer.extensions.axial.domain import quantity
from code_visualizer.extensions.axial.records import (
    CODEC,
    MAPPING_TYPE,
    RESULT_TYPE,
    AxialMapping,
    AxialResult,
    amount,
)
from code_visualizer.extensions.fields.arrays import read_array
from code_visualizer.extensions.fields.records import METADATA_LIMIT

if TYPE_CHECKING:
    from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class AxialPresentation:
    resource: ResourceReference
    result: AxialResult
    mapping: AxialMapping
    coordinates: tuple[float, ...]
    displacement: tuple[float, ...]
    stress: tuple[float, ...]


def prepare_result(
    reference: ResourceReference, resolve: Callable[[ResourceReference], ResolvedResource]
) -> AxialPresentation:
    import numpy as np

    def record[T](
        ref: ResourceReference, kind: type[T], logical: ResourceLogicalTypeReference
    ) -> T:
        resource = resolve(ref)
        if (
            resource.descriptor.logical_type != logical
            or resource.descriptor.media_type != "application/json"
            or resource.descriptor.byte_size > METADATA_LIMIT
        ):
            raise ValueError("AXIAL_RESULT_TYPE: invalid exact metadata contract")
        with resource.open() as stream:
            return CODEC.decode(stream.read(METADATA_LIMIT + 1), kind)

    result = record(reference, AxialResult, RESULT_TYPE)
    mapping = record(result.mapping, AxialMapping, MAPPING_TYPE)
    if result.source_digest != mapping.source_digest or result.semantic_ids != mapping.semantic_ids:
        raise ValueError("AXIAL_RESULT_SOURCE: mapping and equilibrium differ")
    arrays: dict[str, NDArray[np.float64]] = {}
    for name, shape, unit in (
        ("coordinates", (result.nodes,), "meter"),
        ("displacement", (result.nodes,), "meter"),
        ("stress", (result.nodes - 1,), "pascal"),
        ("element_force", (result.nodes - 1,), "newton"),
        ("stiffness", (result.nodes, result.nodes), "newton_per_meter"),
        ("right", (result.nodes,), "newton"),
    ):
        resource = resolve(getattr(result, name))
        if (
            resource.descriptor.tensor is None
            or resource.descriptor.tensor.unit != quantity(1, unit).unit
        ):
            raise ValueError("AXIAL_RESULT_UNIT: invalid derived array unit")
        arrays[name] = read_array(resource, shape)
    x, u = arrays["coordinates"], arrays["displacement"]
    if (
        not np.all(np.diff(x) > 0)
        or u[0] != 0
        or not np.allclose(
            x,
            np.linspace(
                amount(mapping.origin, "meter"),
                amount(mapping.origin, "meter") + amount(mapping.length, "meter"),
                result.nodes,
            ),
            rtol=1e-7,
            atol=1e-9,
        )
    ):
        raise ValueError("AXIAL_RESULT_SUPPORT: coordinates disagree with the geometry mapping")
    residual = arrays["stiffness"] @ u - arrays["right"]
    if np.max(np.abs(residual[1:])) > max(1, abs(amount(result.applied_force, "newton"))) * 1e-10:
        raise ValueError("AXIAL_RESULT_BALANCE: published equilibrium does not balance")
    return AxialPresentation(
        reference,
        result,
        mapping,
        tuple(float(v) for v in x),
        tuple(float(v) for v in u),
        tuple(float(v) for v in arrays["stress"]),
    )
