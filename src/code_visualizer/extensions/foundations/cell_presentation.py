"""Disposable cell-average presentation shared by resource-specific readers.

These are prepared display values, never a persisted support interpretation or
editable field. Readers retain responsibility for geometry, units and identity.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from code_visualizer.domain.preview import PreviewEvent
from code_visualizer.domain.values import QuantityValue, ResourceReference, UnitReference
from code_visualizer.execution.backends import ResolvedResource
from code_visualizer.extensions.fields.records import TemporalPosition
from code_visualizer.extensions.foundations.unit_algebra import QuantityKind

Resolver = Callable[[ResourceReference], ResolvedResource]


@dataclass(frozen=True, slots=True)
class PresentedSupport:
    region_id: str
    frame_id: str
    length: QuantityValue
    interpretation: str


@dataclass(frozen=True, slots=True)
class PresentedComponent:
    id: str
    field_id: str
    unit: UnitReference
    quantity_kind: QuantityKind


@dataclass(frozen=True, slots=True)
class PresentedCell:
    id: str
    left: float
    right: float
    level: int
    value: float


@dataclass(frozen=True, slots=True)
class MeshDecision:
    tick: int
    step: int
    epoch: int
    cells: int
    refined: int
    coarsened: int


@dataclass(frozen=True, slots=True)
class PresentedFrame:
    tick: int
    step: int
    epoch: int
    cells: tuple[PresentedCell, ...]


@dataclass(frozen=True, slots=True)
class PresentedTrial:
    base: PresentedFrame
    candidate: PresentedFrame


@dataclass(frozen=True, slots=True)
class CellPresentation:
    resource: ResourceReference
    definition_digest: str
    sample_count: int
    selected: TemporalPosition
    tick: int
    epoch: int
    support: PresentedSupport
    components: tuple[PresentedComponent, ...]
    component_id: str
    cells: tuple[PresentedCell, ...]
    decisions: tuple[MeshDecision, ...]
    preview: PresentedTrial | None = None
    base_retained: bool = False
    annotations: tuple[str, ...] = ()


class CellReader(Protocol):
    @property
    def cache_bytes(self) -> int: ...

    def close(self) -> None: ...

    def prepare(
        self,
        root: ResourceReference,
        resolve: Resolver,
        context: object,
        sample: int | None = None,
        component_id: str | None = None,
        *,
        preview: PreviewEvent | None = None,
        session_id: str = "",
        input_digest: str = "",
        cancelled: Callable[[], bool] = lambda: False,
    ) -> CellPresentation: ...
