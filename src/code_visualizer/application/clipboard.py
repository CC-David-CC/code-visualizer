"""Versioned, bounded semantic clipboard fragments shared by every UI adapter."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import cast

from code_visualizer.application.mindmap_structure import insert_child
from code_visualizer.domain.common import DocumentKind, JsonValue, new_id
from code_visualizer.domain.drakon import Call, DrakonAtom, nested_sequences
from code_visualizer.domain.freeform import (
    ConnectorObject,
    FreeformDiagram,
    FreeformObject,
    Rect,
    ShapeObject,
)
from code_visualizer.domain.mindmap import CrossLink, MindMapDiagram, Topic, walk_topics
from code_visualizer.domain.project import Project
from code_visualizer.persistence.decoding import (
    drakon_atom_from_data,
    freeform_object_from_data,
    topic_from_data,
)
from code_visualizer.persistence.serialization import (
    drakon_atom_to_data,
    freeform_object_to_data,
    topic_to_data,
)

SEMANTIC_FRAGMENT_MIME = "application/x-code-visualizer-semantic-fragment+json"
SEMANTIC_FRAGMENT_VERSION = 1
MAX_SEMANTIC_FRAGMENT_BYTES = 2 * 1024 * 1024
MAX_SEMANTIC_FRAGMENT_ITEMS = 20_000
MAX_SEMANTIC_FRAGMENT_DEPTH = 64


class ClipboardFormatError(ValueError):
    """Stable error raised before any untrusted clipboard content reaches commands."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class SemanticFragment:
    mode: DocumentKind
    source_project_id: str
    summary: str
    payload: dict[str, JsonValue]
    version: int = SEMANTIC_FRAGMENT_VERSION

    def to_json(self) -> str:
        return json.dumps(
            {
                "format": "code-visualizer-semantic-fragment",
                "mode": self.mode.value,
                "payload": self.payload,
                "source_project_id": self.source_project_id,
                "summary": self.summary,
                "version": self.version,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


def _validate_tree(value: object, *, depth: int = 0, count: list[int] | None = None) -> None:
    if depth > MAX_SEMANTIC_FRAGMENT_DEPTH:
        raise ClipboardFormatError("CLIPBOARD_TOO_DEEP", "Clipboard fragment nesting is too deep")
    counter = count if count is not None else [0]
    counter[0] += 1
    if counter[0] > MAX_SEMANTIC_FRAGMENT_ITEMS:
        raise ClipboardFormatError(
            "CLIPBOARD_TOO_COMPLEX", "Clipboard fragment has too many values"
        )
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ClipboardFormatError("CLIPBOARD_INVALID", "Clipboard object keys must be text")
        for item in value.values():
            _validate_tree(item, depth=depth + 1, count=counter)
    elif isinstance(value, list):
        for item in value:
            _validate_tree(item, depth=depth + 1, count=counter)
    elif not isinstance(value, (str, int, float, bool, type(None))):
        raise ClipboardFormatError("CLIPBOARD_INVALID", "Clipboard contains a non-JSON value")


def semantic_fragment_from_json(source: str | bytes) -> SemanticFragment:
    encoded = source.encode("utf-8") if isinstance(source, str) else source
    if len(encoded) > MAX_SEMANTIC_FRAGMENT_BYTES:
        raise ClipboardFormatError("CLIPBOARD_TOO_LARGE", "Clipboard fragment exceeds 2 MiB")
    try:
        raw: object = json.loads(
            encoded,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ClipboardFormatError("CLIPBOARD_NONFINITE", f"Invalid number {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClipboardFormatError("CLIPBOARD_INVALID_JSON", str(exc)) from exc
    _validate_tree(raw)
    if not isinstance(raw, dict):
        raise ClipboardFormatError("CLIPBOARD_INVALID", "Clipboard fragment must be an object")
    if raw.get("format") != "code-visualizer-semantic-fragment":
        raise ClipboardFormatError("CLIPBOARD_WRONG_FORMAT", "Clipboard format is not recognized")
    if raw.get("version") != SEMANTIC_FRAGMENT_VERSION:
        raise ClipboardFormatError(
            "CLIPBOARD_UNSUPPORTED_VERSION", "Clipboard fragment version is not supported"
        )
    mode_value = raw.get("mode")
    project_id = raw.get("source_project_id")
    summary = raw.get("summary")
    payload = raw.get("payload")
    try:
        mode = DocumentKind(mode_value) if isinstance(mode_value, str) else None
    except ValueError as exc:
        raise ClipboardFormatError("CLIPBOARD_WRONG_MODE", str(exc)) from exc
    if mode is None or not isinstance(project_id, str) or not project_id:
        raise ClipboardFormatError(
            "CLIPBOARD_INVALID", "Clipboard mode and project ID are required"
        )
    if not isinstance(summary, str) or not isinstance(payload, dict):
        raise ClipboardFormatError(
            "CLIPBOARD_INVALID", "Clipboard summary and payload are required"
        )
    return SemanticFragment(
        mode,
        project_id,
        summary,
        cast(dict[str, JsonValue], payload),
    )


def drakon_fragment(project_id: str, atoms: tuple[DrakonAtom, ...]) -> SemanticFragment:
    if not atoms:
        raise ClipboardFormatError("CLIPBOARD_EMPTY", "Select a contiguous DRAKON block first")
    return SemanticFragment(
        DocumentKind.DRAKON,
        project_id,
        f"DRAKON block: {len(atoms)} operation{'s' if len(atoms) != 1 else ''}",
        {"atoms": [drakon_atom_to_data(atom) for atom in atoms]},
    )


def drakon_atoms_from_fragment(fragment: SemanticFragment) -> tuple[DrakonAtom, ...]:
    if fragment.mode is not DocumentKind.DRAKON:
        raise ClipboardFormatError("CLIPBOARD_WRONG_MODE", "Fragment is not a DRAKON block")
    raw_atoms = fragment.payload.get("atoms")
    if not isinstance(raw_atoms, list) or not raw_atoms:
        raise ClipboardFormatError("CLIPBOARD_INVALID", "DRAKON fragment has no operations")
    return tuple(
        drakon_atom_from_data(item, f"$.payload.atoms[{index}]")
        for index, item in enumerate(raw_atoms)
    )


def _cross_link_data(link: CrossLink) -> dict[str, JsonValue]:
    return {
        "id": link.id,
        "label": link.label,
        "source_topic_id": link.source_topic_id,
        "target_topic_id": link.target_topic_id,
    }


def mindmap_fragment(project_id: str, diagram: MindMapDiagram, topic: Topic) -> SemanticFragment:
    topic_ids = {item.id for item in walk_topics(topic)}
    internal = tuple(
        link
        for link in diagram.cross_links
        if link.source_topic_id in topic_ids and link.target_topic_id in topic_ids
    )
    external = tuple(
        link
        for link in diagram.cross_links
        if (link.source_topic_id in topic_ids) != (link.target_topic_id in topic_ids)
    )
    attachments = sorted(
        {attachment for item in walk_topics(topic) for attachment in item.attachments}
    )
    return SemanticFragment(
        DocumentKind.MIND_MAP,
        project_id,
        f"Mind-map subtree: {len(topic_ids)} topic{'s' if len(topic_ids) != 1 else ''}",
        {
            "attachments": cast(list[JsonValue], attachments),
            "external_cross_links": [_cross_link_data(link) for link in external],
            "internal_cross_links": [_cross_link_data(link) for link in internal],
            "topic": topic_to_data(topic),
        },
    )


def topic_from_fragment(fragment: SemanticFragment) -> Topic:
    if fragment.mode is not DocumentKind.MIND_MAP:
        raise ClipboardFormatError("CLIPBOARD_WRONG_MODE", "Fragment is not a mind-map subtree")
    raw_topic = fragment.payload.get("topic")
    if raw_topic is None:
        raise ClipboardFormatError("CLIPBOARD_INVALID", "Mind-map fragment has no topic")
    return topic_from_data(raw_topic, "$.payload.topic")


def freeform_fragment(
    project_id: str,
    diagram: FreeformDiagram,
    selected_ids: tuple[str, ...],
) -> SemanticFragment:
    selected = set(selected_ids)
    shapes = tuple(
        item for item in diagram.objects if isinstance(item, ShapeObject) and item.id in selected
    )
    shape_ids = {item.id for item in shapes}
    internal_connectors = tuple(
        item
        for item in diagram.objects
        if isinstance(item, ConnectorObject)
        and item.source_id in shape_ids
        and item.target_id in shape_ids
    )
    external_connectors = tuple(
        item
        for item in diagram.objects
        if isinstance(item, ConnectorObject)
        and item.id in selected
        and item not in internal_connectors
    )
    objects: tuple[FreeformObject, ...] = (*shapes, *internal_connectors)
    if not objects and not external_connectors:
        raise ClipboardFormatError("CLIPBOARD_EMPTY", "Select free-form objects first")
    assets = sorted({item.asset_id for item in shapes if item.asset_id is not None})
    return SemanticFragment(
        DocumentKind.FREEFORM,
        project_id,
        f"Free-form selection: {len(objects)} object{'s' if len(objects) != 1 else ''}",
        {
            "asset_ids": cast(list[JsonValue], assets),
            "external_connectors": [freeform_object_to_data(item) for item in external_connectors],
            "objects": [freeform_object_to_data(item) for item in objects],
        },
    )


def freeform_objects_from_fragment(
    fragment: SemanticFragment,
) -> tuple[FreeformObject, ...]:
    if fragment.mode is not DocumentKind.FREEFORM:
        raise ClipboardFormatError("CLIPBOARD_WRONG_MODE", "Fragment is not free-form data")
    raw_objects = fragment.payload.get("objects")
    if not isinstance(raw_objects, list):
        raise ClipboardFormatError("CLIPBOARD_INVALID", "Free-form fragment has no objects")
    return tuple(
        freeform_object_from_data(item, f"$.payload.objects[{index}]")
        for index, item in enumerate(raw_objects)
    )


def unresolved_references(fragment: SemanticFragment, destination: Project) -> tuple[str, ...]:
    """Describe references that cannot be rebound automatically in the destination."""

    unresolved: set[str] = set()
    if fragment.mode is DocumentKind.DRAKON:
        diagram_ids = {document.id for document in destination.documents}

        def inspect(atoms: tuple[DrakonAtom, ...]) -> None:
            for atom in atoms:
                if isinstance(atom, Call) and (
                    atom.target_diagram_id is not None and atom.target_diagram_id not in diagram_ids
                ):
                    unresolved.add(f"linked Call target {atom.target_diagram_id}")
                for sequence in nested_sequences(atom):
                    inspect(sequence.atoms)

        inspect(drakon_atoms_from_fragment(fragment))
    else:
        raw_assets = fragment.payload.get("attachments")
        if raw_assets is None:
            raw_assets = fragment.payload.get("asset_ids", [])
        existing_assets = {asset.id for asset in destination.managed_assets}
        if isinstance(raw_assets, list):
            unresolved.update(
                f"managed asset {item}"
                for item in raw_assets
                if isinstance(item, str) and item not in existing_assets
            )
        external = fragment.payload.get("external_cross_links")
        if external is None:
            external = fragment.payload.get("external_connectors", [])
        if isinstance(external, list):
            unresolved.update(
                f"external relationship {index + 1}" for index, _item in enumerate(external)
            )
    return tuple(sorted(unresolved))


def paste_mindmap_fragment(
    fragment: SemanticFragment,
    destination: Project,
    diagram: MindMapDiagram,
    parent_id: str,
    index: int,
) -> tuple[MindMapDiagram, tuple[str, ...], tuple[str, ...]]:
    """Create a fresh-ID subtree snapshot suitable for one atomic command."""

    source = topic_from_fragment(fragment)
    allowed_assets = {asset.id for asset in destination.managed_assets}
    mapping = {topic.id: new_id("topic") for topic in walk_topics(source)}

    def clone(topic: Topic) -> Topic:
        return Topic(
            mapping[topic.id],
            topic.text,
            tuple(clone(child) for child in topic.children),
            topic.notes,
            topic.collapsed,
            topic.links,
            tuple(item for item in topic.attachments if item in allowed_assets),
            topic.semantic_id,
        )

    cloned = clone(source)
    try:
        root = insert_child(diagram.root, parent_id, cloned, index)
    except ValueError as exc:
        raise ClipboardFormatError("CLIPBOARD_INCOMPATIBLE_TARGET", str(exc)) from exc
    links = list(diagram.cross_links)
    raw_links = fragment.payload.get("internal_cross_links", [])
    if not isinstance(raw_links, list):
        raise ClipboardFormatError("CLIPBOARD_INVALID", "Mind-map cross-links must be a list")
    for raw in raw_links:
        if not isinstance(raw, dict):
            raise ClipboardFormatError("CLIPBOARD_INVALID", "Mind-map cross-link is invalid")
        source_id = raw.get("source_topic_id")
        target_id = raw.get("target_topic_id")
        label = raw.get("label", "")
        if not isinstance(source_id, str) or not isinstance(target_id, str):
            raise ClipboardFormatError("CLIPBOARD_INVALID", "Cross-link endpoints are required")
        if not isinstance(label, str) or source_id not in mapping or target_id not in mapping:
            raise ClipboardFormatError("CLIPBOARD_INVALID", "Cross-link does not belong to subtree")
        links.append(CrossLink(new_id("cross-link"), mapping[source_id], mapping[target_id], label))
    unresolved = unresolved_references(fragment, destination)
    return (
        replace(diagram, root=root, cross_links=tuple(links)),
        tuple(mapping.values()),
        unresolved,
    )


def paste_freeform_fragment(
    fragment: SemanticFragment,
    destination: Project,
    diagram: FreeformDiagram,
    *,
    offset: float = 24.0,
) -> tuple[FreeformDiagram, tuple[str, ...], tuple[str, ...]]:
    """Clone a complete free-form selection without accepting executable payloads."""

    source = freeform_objects_from_fragment(fragment)
    shapes = tuple(item for item in source if isinstance(item, ShapeObject))
    connectors = tuple(item for item in source if isinstance(item, ConnectorObject))
    mapping = {item.id: new_id("shape") for item in shapes}
    allowed_assets = {asset.id for asset in destination.managed_assets}
    allowed_layers = {layer.id for layer in diagram.layers if not layer.locked}
    fallback_layer = (
        "layer_default"
        if "layer_default" in allowed_layers
        else next(iter(sorted(allowed_layers)), "")
    )
    if not fallback_layer:
        raise ClipboardFormatError(
            "CLIPBOARD_INCOMPATIBLE_TARGET", "The destination has no writable layer"
        )
    group_mapping = {
        group_id: new_id("group")
        for group_id in {item.group_id for item in shapes if item.group_id is not None}
    }
    highest = max(
        (item.z_index for item in diagram.objects if isinstance(item, ShapeObject)), default=-1
    )
    ordered_z = {
        item.id: highest + index + 1
        for index, item in enumerate(sorted(shapes, key=lambda value: (value.z_index, value.id)))
    }
    cloned_shapes = tuple(
        replace(
            item,
            id=mapping[item.id],
            bounds=Rect(
                item.bounds.x + offset,
                item.bounds.y + offset,
                item.bounds.width,
                item.bounds.height,
            ),
            z_index=ordered_z[item.id],
            layer_id=item.layer_id if item.layer_id in allowed_layers else fallback_layer,
            group_id=group_mapping.get(item.group_id) if item.group_id is not None else None,
            asset_id=item.asset_id if item.asset_id in allowed_assets else None,
        )
        for item in shapes
    )
    cloned_connectors: list[ConnectorObject] = []
    for item in connectors:
        if item.source_id not in mapping or item.target_id not in mapping:
            continue
        cloned_connectors.append(
            replace(
                item,
                id=new_id("connector"),
                source_id=mapping[item.source_id],
                target_id=mapping[item.target_id],
                layer_id=item.layer_id if item.layer_id in allowed_layers else fallback_layer,
            )
        )
    selected = tuple(item.id for item in cloned_shapes)
    unresolved = unresolved_references(fragment, destination)
    return (
        replace(diagram, objects=(*diagram.objects, *cloned_shapes, *cloned_connectors)),
        selected,
        unresolved,
    )
