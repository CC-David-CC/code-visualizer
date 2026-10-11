"""Side-effect-free project-kernel queries and derived graph projections."""

from __future__ import annotations

from collections import deque
from dataclasses import replace

from code_visualizer.application.live_views import resolve_live_document
from code_visualizer.application.projection_language import (
    builtin_projection_definition,
    compile_projection,
)
from code_visualizer.application.semantic_index import build_semantic_program
from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.project import Project, ProjectDocument
from code_visualizer.domain.projection import ProjectionDefinition
from code_visualizer.domain.semantic import (
    ProjectionEdge,
    ProjectionKind,
    ProjectionNode,
    SemanticObject,
    SemanticObjectKind,
    SemanticProgram,
    SemanticProjection,
    SemanticRelation,
    SemanticRelationKind,
)
from code_visualizer.extensions.registry import DomainExtensionRegistry


class ProjectQueries:
    """Stable read API; callers never need to inspect document dataclasses."""

    def __init__(
        self,
        program: SemanticProgram,
        projection_definitions: tuple[ProjectionDefinition, ...] = (),
        documents: tuple[ProjectDocument, ...] = (),
    ) -> None:
        self.program = program
        self._projection_definitions = {
            definition.id: definition for definition in projection_definitions
        }
        self._documents = {document.id: document for document in documents}
        self._objects = {item.id: item for item in program.objects}
        self._outgoing: dict[str, list[SemanticRelation]] = {}
        self._incoming: dict[str, list[SemanticRelation]] = {}
        for relation in program.relations:
            self._outgoing.setdefault(relation.source_id, []).append(relation)
            self._incoming.setdefault(relation.target_id, []).append(relation)

    @classmethod
    def from_project(
        cls,
        project: Project,
        extensions: DomainExtensionRegistry | None = None,
    ) -> ProjectQueries:
        return cls(
            build_semantic_program(project, extensions),
            project.projection_definitions,
            project.documents,
        )

    def resolved_document(self, document_id: str) -> ProjectDocument | None:
        """Resolve a live lens against this exact semantic-program revision."""

        document = self._documents.get(document_id)
        return None if document is None else resolve_live_document(document, self.program)

    def projection_definitions(self) -> tuple[ProjectionDefinition, ...]:
        return tuple(
            sorted(self._projection_definitions.values(), key=lambda item: (item.title, item.id))
        )

    def projection_definition(self, definition_id: str) -> ProjectionDefinition | None:
        return self._projection_definitions.get(definition_id)

    def compose_projection(
        self,
        definition: ProjectionDefinition,
        *,
        kind: ProjectionKind = ProjectionKind.COMPOSED,
    ) -> SemanticProjection:
        return compile_projection(self.program, definition, kind=kind)

    def saved_projection(self, definition_id: str) -> SemanticProjection | None:
        definition = self.projection_definition(definition_id)
        return None if definition is None else self.compose_projection(definition)

    def semantic_object(self, object_id: str) -> SemanticObject | None:
        return self._objects.get(object_id)

    def semantic_relation(self, relation_id: str) -> SemanticRelation | None:
        return next((item for item in self.program.relations if item.id == relation_id), None)

    def children(self, namespace_id: str) -> tuple[SemanticObject, ...]:
        ids = {
            relation.target_id
            for relation in self._outgoing.get(namespace_id, ())
            if relation.kind is SemanticRelationKind.CONTAINS
        }
        return tuple(
            sorted(
                (self._objects[item_id] for item_id in ids if item_id in self._objects),
                key=lambda item: (item.kind.value, item.label.casefold(), item.id),
            )
        )

    def callers(self, function_id: str) -> tuple[SemanticRelation, ...]:
        return tuple(
            relation
            for relation in self._incoming.get(function_id, ())
            if relation.kind is SemanticRelationKind.CALLS
        )

    def references(self, symbol_id: str) -> tuple[SemanticRelation, ...]:
        accepted = {
            SemanticRelationKind.READS,
            SemanticRelationKind.WRITES,
            SemanticRelationKind.REFERENCES,
        }
        return tuple(
            relation for relation in self._incoming.get(symbol_id, ()) if relation.kind in accepted
        )

    def control_flow(self, function_id: str) -> tuple[SemanticRelation, ...]:
        accepted = {SemanticRelationKind.CONTROL_FLOW, SemanticRelationKind.BRANCH}
        return tuple(
            relation
            for relation in self.program.relations
            if relation.owner_id == function_id and relation.kind in accepted
        )

    def data_dependencies(self, operation_id: str) -> tuple[SemanticRelation, ...]:
        accepted = {
            SemanticRelationKind.READS,
            SemanticRelationKind.WRITES,
            SemanticRelationKind.EVALUATES,
            SemanticRelationKind.REFERENCES,
            SemanticRelationKind.CONTAINS,
        }
        reachable = {operation_id}
        pending = deque((operation_id,))
        result: dict[str, SemanticRelation] = {}
        while pending:
            current = pending.popleft()
            for relation in self._outgoing.get(current, ()):
                if relation.kind not in accepted:
                    continue
                result[relation.id] = relation
                if relation.target_id not in reachable:
                    reachable.add(relation.target_id)
                    pending.append(relation.target_id)
        return tuple(sorted(result.values(), key=lambda item: item.id))

    def views_for(self, semantic_id: str) -> tuple[SemanticObject, ...]:
        return tuple(item for item in self.program.objects if item.anchor_id == semantic_id)

    def semantic_id_for_view_object(self, document_id: str, object_id: str) -> str | None:
        direct = self._objects.get(object_id)
        if direct is not None and direct.document_id == document_id:
            return direct.anchor_id or direct.id
        prefixes = (
            f"glyph:mindmap:{document_id}:{object_id}",
            f"glyph:freeform:{document_id}:{object_id}",
            f"glyph:drakon:{object_id}",
        )
        glyph = next((self._objects.get(item) for item in prefixes if item in self._objects), None)
        if glyph is None:
            return None
        return glyph.anchor_id or glyph.id

    def projection(
        self,
        kind: ProjectionKind | str,
        root: str | None = None,
        *,
        focus_ids: tuple[str, ...] = (),
    ) -> SemanticProjection:
        resolved = kind if isinstance(kind, ProjectionKind) else ProjectionKind(kind)
        if resolved in {
            ProjectionKind.ARCHITECTURE,
            ProjectionKind.CALLS,
            ProjectionKind.CONTROL,
            ProjectionKind.DATA,
            ProjectionKind.CONCEPTS,
        }:
            definition = replace(
                builtin_projection_definition(resolved, self.program, root),
                focus_ids=focus_ids,
            )
            return compile_projection(self.program, definition, kind=resolved)
        node_ids, relations = self._projection_members(resolved, root)
        nodes = tuple(
            ProjectionNode(
                item.id,
                item.anchor_id or item.id,
                item.kind,
                item.label,
                item.detail,
                item.document_id,
                item.field,
            )
            for item in self.program.objects
            if item.id in node_ids
        )
        edges = tuple(
            ProjectionEdge(
                relation.id,
                relation.source_id,
                relation.target_id,
                relation.kind,
                relation.label,
            )
            for relation in relations
            if relation.source_id in node_ids and relation.target_id in node_ids
        )
        if resolved is ProjectionKind.DRAKON:
            anchor_to_glyph = {
                item.anchor_id: item.id
                for item in self.program.objects
                if item.id in node_ids and item.anchor_id is not None
            }
            routed = tuple(
                ProjectionEdge(
                    f"view-edge:drakon:{relation.id}",
                    anchor_to_glyph[relation.source_id],
                    anchor_to_glyph[relation.target_id],
                    relation.kind,
                    relation.label,
                )
                for relation in self.program.relations
                if relation.kind
                in {
                    SemanticRelationKind.CONTROL_FLOW,
                    SemanticRelationKind.BRANCH,
                    SemanticRelationKind.TRANSITION,
                }
                and relation.source_id in anchor_to_glyph
                and relation.target_id in anchor_to_glyph
            )
            edges = (*edges, *routed)
        return SemanticProjection(
            resolved,
            self.program.project_id,
            self.program.revision,
            root,
            nodes,
            edges,
            f"builtin:{resolved.value}",
            resolved.value.replace("_", " ").title(),
        )

    def _projection_members(
        self,
        kind: ProjectionKind,
        root: str | None,
    ) -> tuple[set[str], tuple[SemanticRelation, ...]]:
        if kind is ProjectionKind.RUNTIME:
            # Runtime is revision-pinned ephemeral state supplied by the kernel's
            # runtime-session registry, never by the persisted semantic program.
            return set(), ()
        if kind in {ProjectionKind.CONCEPTS, ProjectionKind.COMPOSED}:
            return set(), ()
        view_detail = {
            ProjectionKind.DRAKON: "drakon",
            ProjectionKind.MIND_MAP: "mindmap",
            ProjectionKind.FREEFORM: "freeform",
        }[kind]
        view_ids = {
            item.id
            for item in self.program.objects
            if item.kind is SemanticObjectKind.VIEW
            and item.detail == view_detail
            and (root is None or item.document_id == root or item.id == root)
        }
        nodes = set(view_ids)
        for relation in self.program.relations:
            if relation.source_id in view_ids and relation.kind is SemanticRelationKind.CONTAINS:
                nodes.add(relation.target_id)
        relations = tuple(
            item
            for item in self.program.relations
            if item.source_id in nodes and item.target_id in nodes
        )
        return nodes, relations

    def _first_function(self) -> str | None:
        return next(
            (item.id for item in self.program.objects if item.kind is SemanticObjectKind.FUNCTION),
            None,
        )

    def _owned_operations(self, root: str) -> set[str]:
        result: set[str] = set()
        pending = deque((root,))
        visited = {root}
        while pending:
            current = pending.popleft()
            for relation in self._outgoing.get(current, ()):
                if relation.kind is not SemanticRelationKind.CONTAINS:
                    continue
                child = self._objects.get(relation.target_id)
                if child is None or child.id in visited:
                    continue
                visited.add(child.id)
                pending.append(child.id)
                if child.kind is SemanticObjectKind.OPERATION:
                    result.add(child.id)
        return result


def semantic_object_to_data(value: SemanticObject) -> dict[str, JsonValue]:
    return {
        "anchor_id": value.anchor_id,
        "detail": value.detail,
        "document_id": value.document_id,
        "field": value.field,
        "id": value.id,
        "kind": value.kind.value,
        "label": value.label,
        "parent_id": value.parent_id,
        "properties": [{"name": item.name, "value": item.value} for item in value.properties],
    }


def relation_to_data(value: SemanticRelation) -> dict[str, JsonValue]:
    return {
        "id": value.id,
        "kind": value.kind.value,
        "label": value.label,
        "owner_id": value.owner_id,
        "source_id": value.source_id,
        "target_id": value.target_id,
    }


def projection_to_data(value: SemanticProjection) -> dict[str, JsonValue]:
    return {
        "edges": [
            {
                "id": item.id,
                "kind": item.kind.value,
                "label": item.label,
                "source_id": item.source_id,
                "target_id": item.target_id,
                "active": item.active,
            }
            for item in value.edges
        ],
        "kind": value.kind.value,
        "nodes": [
            {
                "detail": item.detail,
                "document_id": item.document_id,
                "field": item.field,
                "id": item.id,
                "kind": item.kind.value,
                "label": item.label,
                "semantic_id": item.semantic_id,
                "badges": list(item.badges),
                "expandable": item.expandable,
                "hidden_count": item.hidden_count,
            }
            for item in value.nodes
        ],
        "project_id": value.project_id,
        "revision": value.revision,
        "root_id": value.root_id,
        "definition_id": value.definition_id,
        "title": value.title,
        "layout": value.layout,
    }
