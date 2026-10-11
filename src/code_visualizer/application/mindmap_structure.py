"""Pure immutable operations for ordered rooted mind-map trees."""

from __future__ import annotations

from dataclasses import replace

from code_visualizer.domain.mindmap import Topic, contains_topic, find_topic, find_topic_parent


def insert_child(root: Topic, parent_id: str, child: Topic, index: int) -> Topic:
    parent = find_topic(root, parent_id)
    if parent is None:
        raise ValueError("parent topic does not exist")
    if index < 0 or index > len(parent.children):
        raise ValueError("child index is out of range")
    children = list(parent.children)
    children.insert(index, child)
    return _replace_by_id(root, parent_id, replace(parent, children=tuple(children)))


def detach_topic(root: Topic, topic_id: str) -> tuple[Topic, Topic, str, int]:
    if root.id == topic_id:
        raise ValueError("the root topic cannot be detached")
    parent = find_topic_parent(root, topic_id)
    topic = find_topic(root, topic_id)
    if parent is None or topic is None:
        raise ValueError("topic does not exist")
    index = next(i for i, child in enumerate(parent.children) if child.id == topic_id)
    children = (*parent.children[:index], *parent.children[index + 1 :])
    return (
        _replace_by_id(root, parent.id, replace(parent, children=children)),
        topic,
        parent.id,
        index,
    )


def remove_topic(root: Topic, topic_id: str, *, promote_children: bool) -> Topic:
    without, topic, parent_id, index = detach_topic(root, topic_id)
    if not promote_children:
        return without
    parent = find_topic(without, parent_id)
    if parent is None:
        raise ValueError("topic parent disappeared")
    children = list(parent.children)
    children[index:index] = topic.children
    return _replace_by_id(without, parent_id, replace(parent, children=tuple(children)))


def move_topic(root: Topic, topic_id: str, parent_id: str, index: int) -> Topic:
    moving = find_topic(root, topic_id)
    if moving is None:
        raise ValueError("topic does not exist")
    if moving.id == root.id:
        raise ValueError("the root topic cannot be moved")
    if contains_topic(moving, parent_id):
        raise ValueError("a topic cannot be moved into its own subtree")
    without, detached, old_parent_id, old_index = detach_topic(root, topic_id)
    parent = find_topic(without, parent_id)
    if parent is None:
        raise ValueError("new parent topic does not exist")
    adjusted = index
    if parent_id == old_parent_id and index > old_index:
        adjusted -= 1
    return insert_child(without, parent_id, detached, adjusted)


def _replace_by_id(root: Topic, topic_id: str, replacement: Topic) -> Topic:
    if root.id == topic_id:
        return replacement
    children = tuple(_replace_by_id(child, topic_id, replacement) for child in root.children)
    return replace(root, children=children)
