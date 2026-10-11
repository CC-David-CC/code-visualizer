"""Pure helpers for semantic DRAKON structure commands.

The helpers live in the application layer because cloning bridges canonical
domain values and their current native-format representation. No geometry or Qt state
participates in a structural edit.
"""

from __future__ import annotations

from dataclasses import replace

from code_visualizer.domain.common import JsonValue, new_id
from code_visualizer.domain.drakon import (
    DrakonAtom,
    If,
    Loop,
    Parallel,
    Select,
    Sequence,
    Silhouette,
    Synchronizer,
    Try,
    With,
    drakon_atom_ids,
    replace_sequence,
)
from code_visualizer.persistence.decoding import drakon_atom_from_data
from code_visualizer.persistence.serialization import drakon_atom_to_data


def primary_sequence(atom: DrakonAtom) -> Sequence | None:
    """Return the ordinary/preferred owned body used by wrap and unwrap."""

    if isinstance(atom, If):
        return atom.true_branch if atom.preferred_truth else atom.false_branch
    if isinstance(atom, Select):
        if not atom.cases:
            return None
        preferred = next(
            (case for case in atom.cases if case.id == atom.preferred_case_id),
            atom.cases[0],
        )
        return preferred.body
    if isinstance(atom, Loop):
        return atom.body
    if isinstance(atom, With):
        return atom.body
    if isinstance(atom, Try):
        return atom.body
    if isinstance(atom, Synchronizer):
        return atom.on_time if atom.preferred_on_time else atom.on_timeout
    if isinstance(atom, Parallel):
        return atom.branches[0].body if atom.branches else None
    if isinstance(atom, Silhouette):
        initial = next(
            (branch for branch in atom.branches if branch.id == atom.initial_branch_id),
            None,
        )
        return initial.body if initial is not None else None
    return None


def replace_owned_sequence(atom: DrakonAtom, sequence: Sequence) -> DrakonAtom:
    """Replace one recursively owned Sequence without knowing its owner type."""

    wrapper = Sequence("application_structure_root", (atom,))
    replaced = replace_sequence(wrapper, sequence)
    return replaced.atoms[0]


def with_empty_primary(atom: DrakonAtom) -> tuple[DrakonAtom, Sequence]:
    primary = primary_sequence(atom)
    if primary is None:
        raise ValueError(f"{type(atom).__name__} does not own a wrappable primary Sequence")
    empty = replace(primary, atoms=())
    return replace_owned_sequence(atom, empty), empty


def _fresh_prefix(value: str) -> str:
    prefix, separator, _remainder = value.partition("_")
    if separator and prefix.replace("-", "").isalnum():
        return prefix
    return "node"


def clone_atoms_with_fresh_ids(atoms: tuple[DrakonAtom, ...]) -> tuple[DrakonAtom, ...]:
    """Clone a semantic block while preserving references internal to the block.

    Building one mapping for the complete block is important: an Address in one
    top-level atom may refer to a branch owned by another atom in the same
    fragment.  External references, such as a linked Call's target diagram, are
    intentionally left untouched so the caller can surface them for rebinding.
    """

    mapping = {
        identifier: new_id(_fresh_prefix(identifier))
        for atom in atoms
        for identifier in drakon_atom_ids(atom)
    }
    reference_fields = frozenset({"id", "initial_branch_id", "target_branch_id"})

    def remap(value: JsonValue, field: str | None = None) -> JsonValue:
        if isinstance(value, dict):
            return {key: remap(item, key) for key, item in value.items()}
        if isinstance(value, list):
            return [remap(item, field) for item in value]
        if isinstance(value, str) and field in reference_fields:
            return mapping.get(value, value)
        return value

    return tuple(drakon_atom_from_data(remap(drakon_atom_to_data(atom))) for atom in atoms)


def clone_atom_with_fresh_ids(atom: DrakonAtom) -> DrakonAtom:
    """Clone one complete atom while preserving only its internal references."""

    return clone_atoms_with_fresh_ids((atom,))[0]
