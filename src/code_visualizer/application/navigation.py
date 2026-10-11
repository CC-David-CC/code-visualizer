"""Stable-reference navigation queries and non-mutating navigation history."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from code_visualizer.domain.drakon import (
    Call,
    DrakonAtom,
    DrakonDiagram,
    Sequence,
    Silhouette,
    nested_sequences,
)
from code_visualizer.domain.project import Project


class ReferenceKind(StrEnum):
    CALL = "call"
    ADDRESS = "address"


@dataclass(frozen=True, slots=True)
class NavigationLocation:
    diagram_id: str
    object_id: str | None = None
    field: str | None = None


@dataclass(frozen=True, slots=True)
class SemanticReference:
    kind: ReferenceKind
    label: str
    source: NavigationLocation
    target_diagram_id: str
    target_object_id: str | None = None
    stable_path: str = ""
    unresolved: bool = False


@dataclass(frozen=True, slots=True)
class CallHierarchyNode:
    diagram_id: str
    label: str
    reveal: NavigationLocation
    children: tuple[CallHierarchyNode, ...] = ()
    cycle: bool = False
    unresolved: bool = False


class NavigationHistory:
    """Bounded browser-like history that never touches semantic revisions."""

    def __init__(self, *, limit: int = 200) -> None:
        if limit < 1:
            raise ValueError("Navigation history limit must be positive")
        self._limit = limit
        self._entries: list[NavigationLocation] = []
        self._index = -1

    @property
    def can_go_back(self) -> bool:
        return self._index > 0

    @property
    def can_go_forward(self) -> bool:
        return 0 <= self._index < len(self._entries) - 1

    @property
    def current(self) -> NavigationLocation | None:
        return self._entries[self._index] if 0 <= self._index < len(self._entries) else None

    def clear(self) -> None:
        self._entries.clear()
        self._index = -1

    def visit(self, location: NavigationLocation) -> None:
        if self.current == location:
            return
        del self._entries[self._index + 1 :]
        self._entries.append(location)
        if len(self._entries) > self._limit:
            del self._entries[: len(self._entries) - self._limit]
        self._index = len(self._entries) - 1

    def back(self) -> NavigationLocation | None:
        if not self.can_go_back:
            return None
        self._index -= 1
        return self._entries[self._index]

    def forward(self) -> NavigationLocation | None:
        if not self.can_go_forward:
            return None
        self._index += 1
        return self._entries[self._index]


def find_callers(project: Project, target_diagram_id: str) -> tuple[SemanticReference, ...]:
    """Find linked Calls by stable diagram ID; never guess from expression text."""

    target = _drakon_documents(project).get(target_diagram_id)
    target_label = target.title if target is not None else target_diagram_id
    references: list[SemanticReference] = []
    for diagram in _drakon_documents(project).values():
        for atom in _walk_sequence(diagram.body):
            if isinstance(atom, Call) and atom.target_diagram_id == target_diagram_id:
                references.append(
                    SemanticReference(
                        ReferenceKind.CALL,
                        f"{diagram.title}: {atom.expression} -> {target_label}",
                        NavigationLocation(diagram.id, atom.id, "target_diagram_id"),
                        target_diagram_id,
                        stable_path=(f"documents.{diagram.id}.atoms.{atom.id}.target_diagram_id"),
                        unresolved=target is None,
                    )
                )
    return tuple(references)


def find_address_transitions(
    project: Project,
    *,
    diagram_id: str | None = None,
    branch_id: str | None = None,
) -> tuple[SemanticReference, ...]:
    """Find silhouette transitions by branch IDs, never by display-name text."""

    references: list[SemanticReference] = []
    for diagram in _drakon_documents(project).values():
        if diagram_id is not None and diagram.id != diagram_id:
            continue
        for atom in _walk_sequence(diagram.body):
            if not isinstance(atom, Silhouette):
                continue
            branch_names = {branch.id: branch.name for branch in atom.branches}
            for branch in atom.branches:
                target_id = branch.target_branch_id
                if target_id is None:
                    continue
                if branch_id is not None and branch_id not in {branch.id, target_id}:
                    continue
                target_name = branch_names.get(target_id, f"missing {target_id}")
                references.append(
                    SemanticReference(
                        ReferenceKind.ADDRESS,
                        (f"{diagram.title}: {atom.display_name} / {branch.name} -> {target_name}"),
                        NavigationLocation(
                            diagram.id,
                            atom.id,
                            f"branches.{branch.id}.target_branch_id",
                        ),
                        diagram.id,
                        target_id,
                        (
                            f"documents.{diagram.id}.atoms.{atom.id}.branches."
                            f"{branch.id}.target_branch_id"
                        ),
                        unresolved=target_id not in branch_names,
                    )
                )
    return tuple(references)


def build_call_hierarchy(project: Project, root_diagram_id: str) -> CallHierarchyNode:
    """Build a finite call tree and mark recursion instead of expanding forever."""

    diagrams = _drakon_documents(project)

    def build(
        diagram_id: str,
        reveal: NavigationLocation,
        ancestors: tuple[str, ...],
    ) -> CallHierarchyNode:
        diagram = diagrams.get(diagram_id)
        if diagram is None:
            return CallHierarchyNode(
                diagram_id,
                f"Missing linked diagram: {diagram_id}",
                reveal,
                unresolved=True,
            )
        if diagram_id in ancestors:
            return CallHierarchyNode(
                diagram_id,
                f"{diagram.title} [recursive cycle]",
                reveal,
                cycle=True,
            )
        path = (*ancestors, diagram_id)
        children: list[CallHierarchyNode] = []
        for atom in _walk_sequence(diagram.body):
            if not isinstance(atom, Call) or atom.target_diagram_id is None:
                continue
            children.append(
                build(
                    atom.target_diagram_id,
                    NavigationLocation(diagram.id, atom.id, "target_diagram_id"),
                    path,
                )
            )
        return CallHierarchyNode(
            diagram.id,
            diagram.title,
            reveal,
            tuple(children),
        )

    return build(root_diagram_id, NavigationLocation(root_diagram_id), ())


def _drakon_documents(project: Project) -> dict[str, DrakonDiagram]:
    return {
        document.id: document
        for document in project.documents
        if isinstance(document, DrakonDiagram)
    }


def _walk_sequence(sequence: Sequence) -> tuple[DrakonAtom, ...]:
    atoms: list[DrakonAtom] = []
    for atom in sequence.atoms:
        atoms.append(atom)
        for nested in nested_sequences(atom):
            atoms.extend(_walk_sequence(nested))
    return tuple(atoms)
