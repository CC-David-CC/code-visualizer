"""Neutral semantic-program and projection contracts shared by every adapter.

These immutable DTOs are intentionally independent of DRAKON, Qt, generated Python,
and debugger transports.  A project kernel builds them from one canonical revision;
views and tools consume them without walking editor-specific dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SemanticObjectKind(StrEnum):
    PROJECT = "project"
    NAMESPACE = "namespace"
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    STRUCTURE = "structure"
    OPERATION = "operation"
    EXPRESSION = "expression"
    SYMBOL = "symbol"
    CONCEPT = "concept"
    DOMAIN = "domain"
    DOMAIN_SCHEMA = "domain_schema"
    CONCEPT_DEFINITION = "concept_definition"
    PROPERTY_DEFINITION = "property_definition"
    ROLE_DEFINITION = "role_definition"
    INTENTION = "intention"
    LANGUAGE_DEFINITION = "language_definition"
    NOTATION_DEFINITION = "notation_definition"
    VALIDATION_RULE = "validation_rule"
    TRANSFORMATION = "transformation"
    TEMPLATE = "template"
    GROUP = "group"
    VIEW = "view"
    GLYPH = "glyph"
    ANNOTATION = "annotation"


class SemanticRelationKind(StrEnum):
    CONTAINS = "contains"
    CALLS = "calls"
    CONTROL_FLOW = "control_flow"
    BRANCH = "branch"
    READS = "reads"
    WRITES = "writes"
    DEFINES = "defines"
    REFERENCES = "references"
    EVALUATES = "evaluates"
    ANCHORS = "anchors"
    TRANSITION = "transition"
    CONCEPTUALLY_CONTAINS = "conceptually_contains"
    AUTHORED = "authored"


class ProjectionKind(StrEnum):
    ARCHITECTURE = "architecture"
    CALLS = "calls"
    CONTROL = "control"
    DATA = "data"
    RUNTIME = "runtime"
    CONCEPTS = "concepts"
    COMPOSED = "composed"
    DRAKON = "drakon"
    MIND_MAP = "mindmap"
    FREEFORM = "freeform"


@dataclass(frozen=True, slots=True)
class SemanticProperty:
    name: str
    value: str


@dataclass(frozen=True, slots=True)
class SemanticObject:
    id: str
    kind: SemanticObjectKind
    label: str
    parent_id: str | None = None
    document_id: str | None = None
    field: str | None = None
    detail: str = ""
    properties: tuple[SemanticProperty, ...] = ()
    anchor_id: str | None = None


@dataclass(frozen=True, slots=True)
class SemanticRelation:
    id: str
    kind: SemanticRelationKind
    source_id: str
    target_id: str
    label: str = ""
    owner_id: str | None = None


@dataclass(frozen=True, slots=True)
class SemanticProgram:
    project_id: str
    revision: int
    objects: tuple[SemanticObject, ...]
    relations: tuple[SemanticRelation, ...]


@dataclass(frozen=True, slots=True)
class SemanticObjectChange:
    before: SemanticObject
    after: SemanticObject


@dataclass(frozen=True, slots=True)
class SemanticRelationChange:
    before: SemanticRelation
    after: SemanticRelation


@dataclass(frozen=True, slots=True)
class SemanticDelta:
    """Exact identity-keyed difference between two semantic read-model revisions."""

    project_id: str
    from_revision: int
    to_revision: int
    added_objects: tuple[SemanticObject, ...] = ()
    removed_objects: tuple[SemanticObject, ...] = ()
    changed_objects: tuple[SemanticObjectChange, ...] = ()
    added_relations: tuple[SemanticRelation, ...] = ()
    removed_relations: tuple[SemanticRelation, ...] = ()
    changed_relations: tuple[SemanticRelationChange, ...] = ()

    @property
    def affected_ids(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                [
                    *(item.id for item in self.added_objects),
                    *(item.id for item in self.removed_objects),
                    *(item.after.id for item in self.changed_objects),
                    *(item.id for item in self.added_relations),
                    *(item.id for item in self.removed_relations),
                    *(item.after.id for item in self.changed_relations),
                ]
            )
        )


def diff_semantic_program(before: SemanticProgram, after: SemanticProgram) -> SemanticDelta:
    if before.project_id != after.project_id:
        raise ValueError("Semantic programs from different projects cannot be diffed")
    before_objects = {item.id: item for item in before.objects}
    after_objects = {item.id: item for item in after.objects}
    before_relations = {item.id: item for item in before.relations}
    after_relations = {item.id: item for item in after.relations}
    object_ids = before_objects.keys() & after_objects.keys()
    relation_ids = before_relations.keys() & after_relations.keys()
    return SemanticDelta(
        before.project_id,
        before.revision,
        after.revision,
        tuple(after_objects[item] for item in sorted(after_objects.keys() - before_objects.keys())),
        tuple(
            before_objects[item] for item in sorted(before_objects.keys() - after_objects.keys())
        ),
        tuple(
            SemanticObjectChange(before_objects[item], after_objects[item])
            for item in sorted(object_ids)
            if before_objects[item] != after_objects[item]
        ),
        tuple(
            after_relations[item]
            for item in sorted(after_relations.keys() - before_relations.keys())
        ),
        tuple(
            before_relations[item]
            for item in sorted(before_relations.keys() - after_relations.keys())
        ),
        tuple(
            SemanticRelationChange(before_relations[item], after_relations[item])
            for item in sorted(relation_ids)
            if before_relations[item] != after_relations[item]
        ),
    )


@dataclass(frozen=True, slots=True)
class ProjectionNode:
    id: str
    semantic_id: str
    kind: SemanticObjectKind
    label: str
    detail: str = ""
    document_id: str | None = None
    field: str | None = None
    badges: tuple[str, ...] = ()
    expandable: bool = False
    hidden_count: int = 0


@dataclass(frozen=True, slots=True)
class ProjectionEdge:
    id: str
    source_id: str
    target_id: str
    kind: SemanticRelationKind
    label: str = ""
    active: bool = False


@dataclass(frozen=True, slots=True)
class SemanticProjection:
    kind: ProjectionKind
    project_id: str
    revision: int
    root_id: str | None
    nodes: tuple[ProjectionNode, ...]
    edges: tuple[ProjectionEdge, ...]
    definition_id: str | None = None
    title: str = ""
    layout: str = "hierarchical"
