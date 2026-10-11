"""Selection ownership of semantic DRAKON presentations, without layout machinery."""

from collections.abc import Iterator

from code_visualizer.domain.drakon import (
    Case,
    DrakonAtom,
    DrakonDiagram,
    ExceptionHandler,
    Header,
    Parallel,
    ParallelBranch,
    Select,
    Sequence,
    Silhouette,
    SilhouetteBranch,
    Try,
    drakon_atom_ids,
    nested_sequences,
)

type SelectionObject = (
    Header | DrakonAtom | Case | ExceptionHandler | ParallelBranch | SilhouetteBranch
)


def selection_objects(diagram: DrakonDiagram) -> Iterator[SelectionObject]:
    """Walk real selectable objects; sequences, End and synthetic nodes are absent."""
    yield diagram.header

    def visit(sequence: Sequence) -> Iterator[SelectionObject]:
        for atom in sequence.atoms:
            yield atom
            if isinstance(atom, Select):
                yield from atom.cases
            elif isinstance(atom, Try):
                yield from atom.handlers
            elif isinstance(atom, Parallel | Silhouette):
                yield from atom.branches
            for nested in nested_sequences(atom):
                yield from visit(nested)

    yield from visit(diagram.body)


def selection_ownership(diagram: DrakonDiagram, presentation_id: str) -> tuple[str, ...]:
    """Resolve the identities encompassed by selecting one presentation object.

    Sequence identities participate in ownership (including generated empty-body
    pass statements), but are not independently selectable. The intrinsic header's
    identity is resolved to the canonical callable through its view binding by the
    application; it is never treated as a body atom here.
    """
    selected = next(
        (item for item in selection_objects(diagram) if item.id == presentation_id), None
    )
    if selected is None:
        return ()
    if isinstance(selected, Header):
        body = diagram.body
    elif isinstance(selected, Case | ExceptionHandler | ParallelBranch | SilhouetteBranch):
        body = selected.body
    else:
        return drakon_atom_ids(selected)
    return (
        selected.id,
        body.id,
        *(identity for atom in body.atoms for identity in drakon_atom_ids(atom)),
    )
