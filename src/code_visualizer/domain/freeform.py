"""Free-form vector-scene domain model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from code_visualizer.domain.common import DocumentKind, ExtensionField, new_id
from code_visualizer.domain.projection import ProjectionDefinition


@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class Rect:
    x: float
    y: float
    width: float
    height: float


class ShapeKind(StrEnum):
    RECTANGLE = "rectangle"
    ROUNDED_RECTANGLE = "rounded_rectangle"
    ELLIPSE = "ellipse"
    TEXT = "text"
    IMAGE = "image"
    LINE = "line"
    ARROW = "arrow"
    POLYLINE = "polyline"
    POLYGON = "polygon"
    REUSABLE = "reusable"


class GuideOrientation(StrEnum):
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"


@dataclass(frozen=True, slots=True)
class Layer:
    id: str
    name: str
    hidden: bool = False
    locked: bool = False


@dataclass(frozen=True, slots=True)
class Guide:
    id: str
    orientation: GuideOrientation
    position: float


@dataclass(frozen=True, slots=True)
class ShapeObject:
    id: str
    shape: ShapeKind
    bounds: Rect
    text: str = ""
    locked: bool = False
    hidden: bool = False
    z_index: int = 0
    rotation: float = 0.0
    layer_id: str = "layer_default"
    group_id: str | None = None
    asset_id: str | None = None
    points: tuple[Point, ...] = ()
    fill: str = "#ffffff"
    stroke: str = "#1f2937"
    semantic_id: str | None = None
    label_override: str | None = None


@dataclass(frozen=True, slots=True)
class ConnectorObject:
    id: str
    source_id: str
    target_id: str
    points: tuple[Point, ...] = ()
    orthogonal: bool = True
    label: str = ""
    arrow_start: bool = False
    arrow_end: bool = True
    layer_id: str = "layer_default"
    locked: bool = False
    semantic_relation_id: str | None = None
    label_override: str | None = None


type FreeformObject = ShapeObject | ConnectorObject


@dataclass(frozen=True, slots=True)
class FreeformDiagram:
    id: str
    title: str
    objects: tuple[FreeformObject, ...] = ()
    layers: tuple[Layer, ...] = (Layer("layer_default", "Layer 1"),)
    guides: tuple[Guide, ...] = ()
    grid_size: float = 16.0
    snap_to_grid: bool = True
    extensions: tuple[ExtensionField, ...] = ()
    kind: DocumentKind = DocumentKind.FREEFORM
    live_projection: ProjectionDefinition | None = None


def create_empty_freeform(
    *,
    title: str = "Free-form Canvas",
    diagram_id: str | None = None,
) -> FreeformDiagram:
    return FreeformDiagram(id=diagram_id or new_id("diagram"), title=title)
