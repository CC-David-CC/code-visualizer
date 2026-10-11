"""Declarative notation policy over stable domain identities.

Definitions contain data only. Field paths follow explicit reference roles; they
never evaluate code or own copies of the values they display.
"""

from dataclasses import dataclass
from enum import StrEnum

from code_visualizer.domain.notation_syntax import Visual
from code_visualizer.domain.projection import ProjectionLayout


class NotationKind(StrEnum):
    GRAPH = "graph"
    TABLE = "table"
    TREE_FORM = "tree_form"
    COMPOSED = "composed"


@dataclass(frozen=True, slots=True)
class NotationField:
    property_id: str | None = None
    reference_role_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.reference_role_ids) > 64:
            raise ValueError("Notation reference paths are limited to 64 roles")


@dataclass(frozen=True, slots=True)
class NotationColumn:
    id: str
    title: str
    field: NotationField
    editable: bool = True


@dataclass(frozen=True, slots=True)
class NotationNodeRule:
    concept_id: str
    label_property_id: str | None = None
    label_fields: tuple[NotationField, ...] = ()


@dataclass(frozen=True, slots=True)
class NotationEdgeRule:
    concept_id: str
    source_role_id: str
    target_role_id: str
    label_fields: tuple[NotationField, ...] = ()


@dataclass(frozen=True, slots=True)
class NotationDefinition:
    id: str
    title: str
    kind: NotationKind
    concept_ids: tuple[str, ...] = ()
    node_rules: tuple[NotationNodeRule, ...] = ()
    edge_rules: tuple[NotationEdgeRule, ...] = ()
    columns: tuple[NotationColumn, ...] = ()
    layout: str = "hierarchical"
    schema_id: str | None = None
    body: Visual | None = None

    def __post_init__(self) -> None:
        if not self.id or not self.title:
            raise ValueError("A notation needs an identity and title")
        ProjectionLayout(self.layout)
        column_ids = tuple(column.id for column in self.columns)
        if len(set(column_ids)) != len(column_ids):
            raise ValueError("Notation column identities must be unique")
