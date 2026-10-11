"""Resolve persisted live view definitions with authored presentation overrides.

Mind maps and canvases store a query plus layout intent. Their semantic glyph labels
are re-derived for every project revision; only an explicit ``label_override`` wins.
This keeps view documents editable without turning copied semantic text into truth.
"""

from __future__ import annotations

from dataclasses import replace

from code_visualizer.application.projection_language import compile_projection
from code_visualizer.application.projection_materializer import materialize_projection
from code_visualizer.domain.freeform import (
    ConnectorObject,
    FreeformDiagram,
    FreeformObject,
    ShapeObject,
)
from code_visualizer.domain.mindmap import CrossLink, MindMapDiagram, Topic, walk_topics
from code_visualizer.domain.project import ProjectDocument
from code_visualizer.domain.projection import ProjectionViewTarget
from code_visualizer.domain.semantic import SemanticDelta, SemanticObjectKind, SemanticProgram


def resolve_live_document(
    document: ProjectDocument,
    program: SemanticProgram,
) -> ProjectDocument:
    """Return a disposable, revision-current view without mutating persistence."""

    if isinstance(document, MindMapDiagram) and document.live_projection is not None:
        return _resolve_mind_map(document, semantic_projection_source(program))
    if isinstance(document, FreeformDiagram) and document.live_projection is not None:
        return _resolve_freeform(document, semantic_projection_source(program))
    return document


def semantic_projection_source(program: SemanticProgram) -> SemanticProgram:
    """Return executable/architectural truth without presentation overlays.

    Live documents are downstream projections. In particular, an already
    materialized glyph must never become an input to the query that regenerates
    that glyph on the next revision.
    """

    presentation_kinds = {
        SemanticObjectKind.VIEW,
        SemanticObjectKind.GLYPH,
        SemanticObjectKind.ANNOTATION,
        SemanticObjectKind.GROUP,
    }
    objects = tuple(item for item in program.objects if item.kind not in presentation_kinds)
    object_ids = {item.id for item in objects}
    relations = tuple(
        item
        for item in program.relations
        if item.source_id in object_ids and item.target_id in object_ids
    )
    return SemanticProgram(
        program.project_id,
        program.revision,
        objects,
        relations,
    )


def changed_live_document_ids(
    documents: tuple[ProjectDocument, ...],
    before: SemanticProgram,
    after: SemanticProgram,
    delta: SemanticDelta,
) -> frozenset[str]:
    """Return live documents whose disposable resolution changed for ``delta``.

    The semantic index owns the upstream delta; live definitions consume it. A
    conservative re-resolution is cheap compared with rebuilding semantic truth,
    and comparing the resolved values keeps the reported visual invalidation local.
    """

    if not (
        delta.added_objects
        or delta.removed_objects
        or delta.changed_objects
        or delta.added_relations
        or delta.removed_relations
        or delta.changed_relations
    ):
        return frozenset()
    before_source = semantic_projection_source(before)
    after_source = semantic_projection_source(after)
    return frozenset(
        document.id
        for document in documents
        if (
            isinstance(document, (MindMapDiagram, FreeformDiagram))
            and document.live_projection is not None
            and resolve_live_document(document, before_source)
            != resolve_live_document(document, after_source)
        )
    )


def _resolve_mind_map(
    stored: MindMapDiagram,
    program: SemanticProgram,
) -> MindMapDiagram:
    definition = stored.live_projection
    assert definition is not None
    projection = compile_projection(program, definition)
    generated = materialize_projection(
        projection,
        ProjectionViewTarget.MIND_MAP,
        document_id=stored.id,
        title=stored.title,
        definition=definition,
    )
    assert isinstance(generated, MindMapDiagram)
    stored_topics = {item.id: item for item in walk_topics(stored.root)}
    generated_ids = {item.id for item in walk_topics(generated.root)}
    semantic_labels = {item.id: item.label for item in program.objects}

    def resolve_authored(topic: Topic) -> Topic:
        derived = semantic_labels.get(topic.semantic_id or "")
        text = (
            topic.label_override
            if topic.label_override is not None
            else (derived if derived is not None else topic.text)
        )
        return replace(
            topic,
            text=text,
            children=tuple(resolve_authored(child) for child in topic.children),
        )

    def merge(topic: Topic) -> Topic:
        authored = stored_topics.get(topic.id)
        if authored is None:
            return topic
        generated_children = tuple(merge(child) for child in topic.children)
        annotations = tuple(
            resolve_authored(child) for child in authored.children if child.id not in generated_ids
        )
        return replace(
            topic,
            text=(authored.label_override if authored.label_override is not None else topic.text),
            children=(*generated_children, *annotations),
            notes=authored.notes,
            collapsed=authored.collapsed,
            links=authored.links,
            attachments=authored.attachments,
            label_override=authored.label_override,
        )

    root = merge(generated.root)
    topic_ids = {item.id for item in walk_topics(root)}
    stored_links = {item.id: item for item in stored.cross_links}
    generated_link_ids = {item.id for item in generated.cross_links}
    relations = {item.id: item for item in program.relations}

    def merge_link(link: CrossLink) -> CrossLink:
        authored = stored_links.get(link.id)
        if authored is None:
            return link
        return replace(
            link,
            label=(authored.label_override if authored.label_override is not None else link.label),
            label_override=authored.label_override,
        )

    links = [merge_link(item) for item in generated.cross_links]
    for link in stored.cross_links:
        if (
            link.id in generated_link_ids
            or link.source_topic_id not in topic_ids
            or link.target_topic_id not in topic_ids
        ):
            continue
        relation = relations.get(link.semantic_relation_id or "")
        derived = None if relation is None else (relation.label or relation.kind.value)
        links.append(
            replace(
                link,
                label=(
                    link.label_override
                    if link.label_override is not None
                    else (derived if derived is not None else link.label)
                ),
            )
        )
    return replace(
        generated,
        root=root,
        cross_links=tuple(links),
        layout=stored.layout,
        extensions=stored.extensions,
    )


def _resolve_freeform(
    stored: FreeformDiagram,
    program: SemanticProgram,
) -> FreeformDiagram:
    definition = stored.live_projection
    assert definition is not None
    projection = compile_projection(program, definition)
    generated = materialize_projection(
        projection,
        ProjectionViewTarget.FREEFORM,
        document_id=stored.id,
        title=stored.title,
        definition=definition,
    )
    assert isinstance(generated, FreeformDiagram)
    stored_objects = {item.id: item for item in stored.objects}
    generated_ids = {item.id for item in generated.objects}
    semantic_labels = {item.id: item.label for item in program.objects}
    relations = {item.id: item for item in program.relations}

    def merge(item: FreeformObject) -> FreeformObject:
        authored = stored_objects.get(item.id)
        if isinstance(item, ShapeObject) and isinstance(authored, ShapeObject):
            return replace(
                item,
                bounds=authored.bounds,
                text=(
                    authored.label_override if authored.label_override is not None else item.text
                ),
                locked=authored.locked,
                hidden=authored.hidden,
                z_index=authored.z_index,
                rotation=authored.rotation,
                layer_id=authored.layer_id,
                group_id=authored.group_id,
                asset_id=authored.asset_id,
                points=authored.points,
                fill=authored.fill,
                stroke=authored.stroke,
                label_override=authored.label_override,
            )
        if isinstance(item, ConnectorObject) and isinstance(authored, ConnectorObject):
            return replace(
                item,
                points=authored.points,
                orthogonal=authored.orthogonal,
                label=(
                    authored.label_override if authored.label_override is not None else item.label
                ),
                arrow_start=authored.arrow_start,
                arrow_end=authored.arrow_end,
                layer_id=authored.layer_id,
                locked=authored.locked,
                label_override=authored.label_override,
            )
        return item

    objects: list[FreeformObject] = [merge(item) for item in generated.objects]
    for item in stored.objects:
        if item.id in generated_ids:
            continue
        if isinstance(item, ShapeObject):
            derived = semantic_labels.get(item.semantic_id or "")
            objects.append(
                replace(
                    item,
                    text=(
                        item.label_override
                        if item.label_override is not None
                        else (derived if derived is not None else item.text)
                    ),
                )
            )
        else:
            relation = relations.get(item.semantic_relation_id or "")
            derived = None if relation is None else (relation.label or relation.kind.value)
            objects.append(
                replace(
                    item,
                    label=(
                        item.label_override
                        if item.label_override is not None
                        else (derived if derived is not None else item.label)
                    ),
                )
            )
    return replace(
        generated,
        objects=tuple(objects),
        layers=stored.layers,
        guides=stored.guides,
        grid_size=stored.grid_size,
        snap_to_grid=stored.snap_to_grid,
        extensions=stored.extensions,
    )
