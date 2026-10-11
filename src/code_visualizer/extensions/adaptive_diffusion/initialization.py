"""Auditable initialization from authored integrals, before accepted sample zero."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.values import QuantityValue, ResourceReference
from code_visualizer.execution.backends import ProducedResource
from code_visualizer.execution.resource_interpretation import ResourceDependency
from code_visualizer.extensions.adaptive_diffusion.problem import AdaptiveProblem
from code_visualizer.extensions.adaptive_fields.records import INTERPRETATION_TYPE
from code_visualizer.extensions.adaptive_fields.units import quantity
from code_visualizer.extensions.fields.arrays import array_resource
from code_visualizer.extensions.fields.records import (
    ARRAY_TYPE,
    digest,
    identity,
    index,
    ref,
    scalar,
)
from code_visualizer.extensions.foundations.record_codec import RecordCodec
from code_visualizer.persistence.computation_resources import produced_descriptor

if TYPE_CHECKING:
    from code_visualizer.extensions.adaptive_diffusion.controller import Initialization

INITIALIZATION_TYPE = ResourceLogicalTypeReference(
    "code_visualizer.adaptive_diffusion.initialization", "1"
)


@dataclass(frozen=True, slots=True)
class InitialPartition:
    interpretation: ResourceReference
    values: ResourceReference
    indicators: ResourceReference | None

    def __post_init__(self) -> None:
        ref(self.interpretation)
        ref(self.values)
        if self.indicators is not None:
            ref(self.indicators)


@dataclass(frozen=True, slots=True)
class InitialResolution:
    source_digest: str
    initial_id: str
    policy_id: str
    partitions: tuple[InitialPartition, ...]
    mass: QuantityValue
    indicator_visits: int
    remeshed_cells: int
    method: str = "authored_fourier_cell_integrals"

    def __post_init__(self) -> None:
        digest(self.source_digest)
        identity(self.initial_id)
        identity(self.policy_id)
        if (
            type(self.partitions) is not tuple
            or not 1 <= len(self.partitions) <= 6
            or any(not isinstance(item, InitialPartition) for item in self.partitions)
            or self.method != "authored_fourier_cell_integrals"
            or scalar(self.mass, "Initial mass") < 0
        ):
            raise ValueError("Initialization requires a bounded authored integral refinement chain")
        index(self.indicator_visits, "Initial indicator work")
        index(self.remeshed_cells, "Initial remeshing work")

    def dependencies(self) -> tuple[ResourceDependency, ...]:
        return tuple(
            dependency
            for item in self.partitions
            for dependency in (
                ResourceDependency(item.interpretation, INTERPRETATION_TYPE),
                ResourceDependency(item.values, ARRAY_TYPE),
                *((ResourceDependency(item.indicators, ARRAY_TYPE),) if item.indicators else ()),
            )
        )


_CODEC = RecordCodec((InitialPartition, InitialResolution))


def decode_initialization(payload: bytes) -> InitialResolution:
    return _CODEC.decode(payload, InitialResolution)


def initialization_dependencies(payload: bytes) -> tuple[ResourceDependency, ...]:
    return decode_initialization(payload).dependencies()


def initialization_resource(
    p: AdaptiveProblem, source: str, result: Initialization
) -> ProducedResource:
    from code_visualizer.extensions.adaptive_diffusion.history import interpretation_resources

    staged: dict[ResourceReference, ProducedResource] = {}

    def stage(value: ProducedResource) -> ResourceReference:
        reference = produced_descriptor(value).reference
        staged[reference] = value
        return reference

    partitions = []
    for item in result.passes:
        resources = interpretation_resources(p, item.mesh)
        references = [stage(resource) for resource in resources]
        values = stage(array_resource("initial-values", item.values[:, None]))
        indicators = (
            stage(array_resource("initial-indicators", item.indicators))
            if item.indicators is not None
            else None
        )
        partitions.append(InitialPartition(references[-1], values, indicators))
    audit = InitialResolution(
        source,
        p.initial_id,
        p.policy_id,
        tuple(partitions),
        quantity(result.state.initial_mass, "kilogram"),
        result.state.indicator_visits,
        result.state.transferred_cells,
    )
    return ProducedResource(
        "initialization",
        _CODEC.encode(audit),
        "application/json",
        (p.initial_id, p.field_id, p.policy_id),
        "Initial resolution from authored cell integrals at t=0",
        logical_type=INITIALIZATION_TYPE,
        dependencies=tuple(staged.values()),
    )
