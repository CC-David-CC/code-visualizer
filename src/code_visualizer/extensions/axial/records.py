"""Closed derived mapping and equilibrium resources, never editable CAD authority."""

from dataclasses import dataclass
from math import isfinite

from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.values import QuantityValue, ResourceReference
from code_visualizer.execution.resource_interpretation import ResourceDependency
from code_visualizer.extensions.axial.domain import IDEALIZATION_ID, quantity
from code_visualizer.extensions.cad.resources import BREP
from code_visualizer.extensions.fields.records import ARRAY_TYPE, digest, identity, index, ref
from code_visualizer.extensions.foundations.record_codec import RecordCodec

MAPPING_TYPE = ResourceLogicalTypeReference("org.codevisualizer.axial.mapping", "1")
RESULT_TYPE = ResourceLogicalTypeReference("org.codevisualizer.axial.result", "1")


def amount(value: QuantityValue, unit: str, *, positive: bool = False) -> float:
    if (
        not isinstance(value, QuantityValue)
        or not isinstance(value.magnitude, int | float)
        or isinstance(value.magnitude, bool)
        or not isfinite(value.magnitude)
        or value.unit != quantity(1, unit).unit
        or (positive and value.magnitude <= 0)
    ):
        raise ValueError("Derived axial metadata requires a finite SI " + unit + " quantity")
    return float(value.magnitude)


def origins(values: tuple[str, ...]) -> None:
    if type(values) is not tuple or not 1 <= len(values) <= 32 or len(set(values)) != len(values):
        raise ValueError("Axial origins must be distinct bounded semantic identities")
    for value in values:
        identity(value)


@dataclass(frozen=True, slots=True)
class AxialMapping:
    source_digest: str
    geometry: ResourceReference
    geometry_project: str
    geometry_revision: int
    geometry_input_digest: str
    geometry_origins: tuple[str, ...]
    space_id: str
    frame_id: str
    axis: str
    origin: QuantityValue
    length: QuantityValue
    area: QuantityValue
    support_region: str
    load_region: str
    support_face: int
    load_face: int
    semantic_ids: tuple[str, ...]
    method_id: str = IDEALIZATION_ID
    method_version: str = "1"
    relative_tolerance: float = 1e-7
    absolute_tolerance_m: float = 1e-9

    def __post_init__(self) -> None:
        digest(self.source_digest)
        digest(self.geometry_input_digest)
        ref(self.geometry)
        for value in (
            self.geometry_project,
            self.space_id,
            self.frame_id,
            self.support_region,
            self.load_region,
        ):
            identity(value)
        for number in (self.geometry_revision, self.support_face, self.load_face):
            index(number, "Geometry index")
        origins(self.geometry_origins)
        origins(self.semantic_ids)
        amount(self.origin, "meter")
        amount(self.length, "meter", positive=True)
        amount(self.area, "square_meter", positive=True)
        if (
            self.axis not in ("x", "y", "z")
            or self.support_face == self.load_face
            or max(self.support_face, self.load_face) >= 6
            or self.support_region == self.load_region
            or (self.method_id, self.method_version) != (IDEALIZATION_ID, "1")
            or self.relative_tolerance != 1e-7
            or self.absolute_tolerance_m != 1e-9
        ):
            raise ValueError("Unsupported axial geometry interpretation")

    def dependencies(self) -> tuple[ResourceDependency, ...]:
        return (ResourceDependency(self.geometry, BREP),)


@dataclass(frozen=True, slots=True)
class AxialResult:
    source_digest: str
    mapping: ResourceReference
    nodes: int
    coordinates: ResourceReference
    displacement: ResourceReference
    stress: ResourceReference
    element_force: ResourceReference
    stiffness: ResourceReference
    right: ResourceReference
    young_modulus: QuantityValue
    applied_force: QuantityValue
    reaction: QuantityValue
    strain_energy: QuantityValue
    normalized_residual: float
    condition: float
    numerical_identity: str
    semantic_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        digest(self.source_digest)
        identity(self.numerical_identity)
        origins(self.semantic_ids)
        if type(self.nodes) is not int or not 3 <= self.nodes <= 65:
            raise ValueError("Axial output requires 3..65 nodes")
        for value in (
            self.mapping,
            self.coordinates,
            self.displacement,
            self.stress,
            self.element_force,
            self.stiffness,
            self.right,
        ):
            ref(value)
        amount(self.young_modulus, "pascal", positive=True)
        amount(self.applied_force, "newton")
        amount(self.reaction, "newton")
        amount(self.strain_energy, "joule")
        assert isinstance(self.strain_energy.magnitude, int | float)
        if (
            self.strain_energy.magnitude < 0
            or type(self.normalized_residual) is not float
            or not 0 <= self.normalized_residual <= 1e-10
            or type(self.condition) is not float
            or not 1 <= self.condition <= 1e12
        ):
            raise ValueError("Axial result is not a qualified finite equilibrium")

    def dependencies(self) -> tuple[ResourceDependency, ...]:
        return (
            ResourceDependency(self.mapping, MAPPING_TYPE),
            *(
                ResourceDependency(value, ARRAY_TYPE)
                for value in (
                    self.coordinates,
                    self.displacement,
                    self.stress,
                    self.element_force,
                    self.stiffness,
                    self.right,
                )
            ),
        )


CODEC = RecordCodec((AxialMapping, AxialResult))


def mapping_dependencies(data: bytes) -> tuple[ResourceDependency, ...]:
    return CODEC.decode(data, AxialMapping).dependencies()


def result_dependencies(data: bytes) -> tuple[ResourceDependency, ...]:
    return CODEC.decode(data, AxialResult).dependencies()
