"""Rooted ordered mind-map domain model."""

from __future__ import annotations

from dataclasses import dataclass

from code_visualizer.domain.common import DocumentKind, ExtensionField, new_id
from code_visualizer.domain.projection import ProjectionDefinition


@dataclass(frozen=True, slots=True)
class Topic:
    id: str
    text: str
    children: tuple[Topic, ...] = ()
    notes: str = ""
    collapsed: bool = False
    links: tuple[str, ...] = ()
    attachments: tuple[str, ...] = ()
    semantic_id: str | None = None
    label_override: str | None = None


@dataclass(frozen=True, slots=True)
class CrossLink:
    id: str
    source_topic_id: str
    target_topic_id: str
    label: str = ""
    semantic_relation_id: str | None = None
    label_override: str | None = None


@dataclass(frozen=True, slots=True)
class MindMapDiagram:
    id: str
    title: str
    root: Topic
    cross_links: tuple[CrossLink, ...] = ()
    layout: str = "balanced"
    extensions: tuple[ExtensionField, ...] = ()
    kind: DocumentKind = DocumentKind.MIND_MAP
    live_projection: ProjectionDefinition | None = None


def create_empty_mind_map(
    *,
    title: str = "Mind Map",
    diagram_id: str | None = None,
) -> MindMapDiagram:
    return MindMapDiagram(
        id=diagram_id or new_id("diagram"),
        title=title,
        root=Topic(id=new_id("topic"), text="Central topic"),
    )


def walk_topics(root: Topic) -> tuple[Topic, ...]:
    result = [root]
    for child in root.children:
        result.extend(walk_topics(child))
    return tuple(result)


def find_topic(root: Topic, topic_id: str) -> Topic | None:
    return next((topic for topic in walk_topics(root) if topic.id == topic_id), None)


def find_topic_parent(root: Topic, topic_id: str) -> Topic | None:
    for child in root.children:
        if child.id == topic_id:
            return root
        parent = find_topic_parent(child, topic_id)
        if parent is not None:
            return parent
    return None


def replace_topic(root: Topic, replacement: Topic) -> Topic:
    if root.id == replacement.id:
        return replacement
    children = tuple(replace_topic(child, replacement) for child in root.children)
    return Topic(
        root.id,
        root.text,
        children,
        root.notes,
        root.collapsed,
        root.links,
        root.attachments,
        root.semantic_id,
        root.label_override,
    )


def contains_topic(root: Topic, topic_id: str) -> bool:
    return any(topic.id == topic_id for topic in walk_topics(root))
