"""Composable, persisted visual-lens vocabulary.

A projection definition says what to show and how to compose it.  It contains no Qt,
coordinates, or executable program meaning.  The compiler turns it into a disposable
``SemanticProjection`` for any matching project revision.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from code_visualizer.domain.semantic import SemanticObjectKind, SemanticRelationKind


class TraversalDirection(StrEnum):
    OUTGOING = "outgoing"
    INCOMING = "incoming"
    BOTH = "both"


class ProjectionGrouping(StrEnum):
    NONE = "none"
    OWNER = "owner"
    CONCEPT = "concept"
    KIND = "kind"


class ProjectionLabelStyle(StrEnum):
    SHORT = "short"
    DETAIL = "detail"
    QUALIFIED = "qualified"


class ProjectionLayout(StrEnum):
    HIERARCHICAL = "hierarchical"
    HORIZONTAL = "horizontal"
    RADIAL = "radial"
    GRID = "grid"


class ProjectionDecoration(StrEnum):
    KIND = "kind"
    DETAIL = "detail"
    ANCHOR_STATE = "anchor_state"


class ProjectionViewTarget(StrEnum):
    MIND_MAP = "mindmap"
    FREEFORM = "freeform"


@dataclass(frozen=True, slots=True)
class ProjectionDefinition:
    id: str
    title: str
    scope_id: str | None = None
    object_kinds: tuple[SemanticObjectKind, ...] = ()
    relation_kinds: tuple[SemanticRelationKind, ...] = ()
    direction: TraversalDirection = TraversalDirection.BOTH
    max_depth: int = 4
    grouping: ProjectionGrouping = ProjectionGrouping.NONE
    decorations: tuple[ProjectionDecoration, ...] = (ProjectionDecoration.KIND,)
    label_style: ProjectionLabelStyle = ProjectionLabelStyle.SHORT
    layout: ProjectionLayout = ProjectionLayout.HIERARCHICAL
    include_scope: bool = True
    include_isolated: bool = True
    node_limit: int = 100
    expanded_ids: tuple[str, ...] = ()
    focus_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DrakonViewDefinition:
    """Stable presentation binding from a DRAKON document to a program function."""

    document_id: str
    function_id: str
    title: str
    header_id: str
    end_id: str
