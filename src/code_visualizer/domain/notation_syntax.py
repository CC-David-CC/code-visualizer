"""Composable, inert projectional notation syntax over stable domain identities."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class VisualLayout(StrEnum):
    ROW = "row"
    COLUMN = "column"
    WRAP = "wrap"
    POSITIONED = "positioned"


class VisualShape(StrEnum):
    RECTANGLE = "rectangle"
    ROUNDED = "rounded"
    ELLIPSE = "ellipse"


class VisualComparison(StrEnum):
    EQUAL = "equal"
    NOT_EQUAL = "not_equal"
    LESS = "less"
    GREATER = "greater"
    PRESENT = "present"


class ScriptPosition(StrEnum):
    SUPER = "super"
    SUB = "sub"


@dataclass(frozen=True, slots=True)
class NotationObjects:
    id: str
    concept_id: str = ""
    schema_id: str | None = None
    schema_version: str | None = None
    model_id: str | None = None
    workspace: bool = False
    roots_only: bool = False


@dataclass(frozen=True, slots=True)
class NotationRelated:
    id: str
    source_binding_id: str = "self"
    role_id: str | None = None
    relation_kind: str | None = None
    relation_label: str | None = None
    incoming: bool = False


@dataclass(frozen=True, slots=True)
class NotationQueryHole:
    id: str
    label: str = "Choose objects to display"


type NotationQuery = NotationObjects | NotationRelated | NotationQueryHole


@dataclass(frozen=True, slots=True)
class VisualNumber:
    id: str
    value: float = 0.0
    binding_id: str = "self"
    property_id: str | None = None
    scale: float = 1.0
    offset: float = 0.0


@dataclass(frozen=True, slots=True)
class VisualPredicate:
    id: str
    binding_id: str = "self"
    property_id: str | None = None
    operator: VisualComparison = VisualComparison.PRESENT
    expected: str | int | float | bool | None = None


@dataclass(frozen=True, slots=True)
class VisualText:
    id: str
    text: str = "Text"
    font_size: float = 14.0
    strong: bool = False
    color: str = "#172033"


@dataclass(frozen=True, slots=True)
class VisualField:
    id: str
    binding_id: str = "self"
    property_id: str | None = None
    reference_role_ids: tuple[str, ...] = ()
    editable: bool = True
    font_size: float = 14.0


@dataclass(frozen=True, slots=True)
class VisualGroup:
    id: str
    layout: VisualLayout = VisualLayout.ROW
    children: tuple[Visual, ...] = ()
    gap: float = 8.0
    padding: float = 0.0
    wrap_width: float = 600.0


@dataclass(frozen=True, slots=True)
class VisualBox:
    id: str
    body: Visual
    shape: VisualShape = VisualShape.ROUNDED
    padding: float = 12.0
    fill: str = "#edf3fc"
    stroke: str = "#536b91"
    width: VisualNumber | None = None
    height: VisualNumber | None = None


@dataclass(frozen=True, slots=True)
class VisualPosition:
    id: str
    body: Visual
    x: VisualNumber
    y: VisualNumber


@dataclass(frozen=True, slots=True)
class VisualRepeat:
    id: str
    query: NotationQuery
    binding_id: str
    body: Visual
    binding_name: str = "item"
    layout: VisualLayout = VisualLayout.COLUMN
    gap: float = 8.0


@dataclass(frozen=True, slots=True)
class VisualConditional:
    id: str
    predicate: VisualPredicate
    body: Visual
    otherwise: Visual | None = None


@dataclass(frozen=True, slots=True)
class VisualFraction:
    id: str
    numerator: Visual
    denominator: Visual


@dataclass(frozen=True, slots=True)
class VisualScript:
    id: str
    base: Visual
    script: Visual
    position: ScriptPosition = ScriptPosition.SUPER


@dataclass(frozen=True, slots=True)
class VisualPoint:
    id: str
    x: VisualNumber
    y: VisualNumber


@dataclass(frozen=True, slots=True)
class VisualPath:
    id: str
    points: tuple[VisualPoint, ...] = ()
    closed: bool = False
    stroke: str = "#536b91"
    fill: str = "transparent"


@dataclass(frozen=True, slots=True)
class VisualConnector:
    id: str
    source_binding_id: str
    target_binding_id: str
    label: str = ""
    arrow: bool = True
    stroke: str = "#536b91"


@dataclass(frozen=True, slots=True)
class VisualHole:
    id: str
    label: str = "Choose a visual or textual element"


type Visual = (
    VisualText
    | VisualField
    | VisualGroup
    | VisualBox
    | VisualPosition
    | VisualRepeat
    | VisualConditional
    | VisualFraction
    | VisualScript
    | VisualPath
    | VisualConnector
    | VisualHole
)


NOTATION_SYNTAX_RECORDS = (
    NotationObjects,
    NotationRelated,
    NotationQueryHole,
    VisualNumber,
    VisualPredicate,
    VisualText,
    VisualField,
    VisualGroup,
    VisualBox,
    VisualPosition,
    VisualRepeat,
    VisualConditional,
    VisualFraction,
    VisualScript,
    VisualPoint,
    VisualPath,
    VisualConnector,
    VisualHole,
)
