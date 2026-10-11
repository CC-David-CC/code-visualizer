"""Typed DRAKON program structure.

Geometry is deliberately absent. Header and End are intrinsic exactly-once
members of every finite callable diagram.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from code_visualizer.domain.common import DocumentKind, ExtensionField, new_id
from code_visualizer.domain.program_kinds import (
    CallableKind as CallableKind,
)
from code_visualizer.domain.program_kinds import (
    LoopKind as LoopKind,
)
from code_visualizer.domain.program_kinds import (
    MethodKind as MethodKind,
)
from code_visualizer.domain.program_kinds import (
    NotePlacement as NotePlacement,
)
from code_visualizer.domain.program_kinds import (
    ParallelMode as ParallelMode,
)
from code_visualizer.domain.program_kinds import (
    ParameterKind as ParameterKind,
)
from code_visualizer.domain.program_kinds import (
    SelectMode as SelectMode,
)
from code_visualizer.domain.program_kinds import (
    SimpleKind as SimpleKind,
)
from code_visualizer.domain.program_kinds import (
    TransferKind as TransferKind,
)
from code_visualizer.domain.program_signatures import (
    FunctionSpec as FunctionSpec,
)
from code_visualizer.domain.program_signatures import (
    ParameterSpec as ParameterSpec,
)


@dataclass(frozen=True, slots=True)
class Header:
    id: str
    function: FunctionSpec


@dataclass(frozen=True, slots=True)
class End:
    id: str


@dataclass(frozen=True, slots=True)
class Action:
    id: str
    source: str = 'print("action")'


@dataclass(frozen=True, slots=True)
class Output:
    id: str
    expression: str = '"output"'
    destination: str | None = None
    end: str | None = None


@dataclass(frozen=True, slots=True)
class Assignment:
    id: str
    target: str = "result"
    value: str = "None"
    annotation: str | None = None
    operator: str = "="


@dataclass(frozen=True, slots=True)
class Transfer:
    id: str
    transfer_kind: TransferKind = TransferKind.RETURN
    expression: str = "None"
    cause: str | None = None


@dataclass(frozen=True, slots=True)
class SimpleStatement:
    id: str
    statement_kind: SimpleKind = SimpleKind.PASS
    source: str = "pass"
    secondary: str | None = None


@dataclass(frozen=True, slots=True)
class Call:
    id: str
    expression: str = "print()"
    awaited: bool = False
    result_target: str | None = None
    target_diagram_id: str | None = None
    arguments: str = ""


@dataclass(frozen=True, slots=True)
class Input:
    id: str
    target: str = "value"
    prompt: str = '"Input: "'
    converter: str | None = None
    annotation: str | None = None


@dataclass(frozen=True, slots=True)
class Delay:
    id: str
    seconds: str = "0.1"
    asynchronous: bool = False


@dataclass(frozen=True, slots=True)
class StartTimer:
    id: str
    timer: str = "operation"


@dataclass(frozen=True, slots=True)
class Period:
    id: str
    timer: str = "operation"
    seconds: str = "1.0"
    asynchronous: bool = False


@dataclass(frozen=True, slots=True)
class RealtimeProcess:
    id: str
    call: str = "print()"
    awaited: bool = False


@dataclass(frozen=True, slots=True)
class Note:
    id: str
    text: str = "Note"
    placement: NotePlacement = NotePlacement.RICH


@dataclass(frozen=True, slots=True)
class Sequence:
    id: str
    atoms: tuple[DrakonAtom, ...] = ()


@dataclass(frozen=True, slots=True)
class If:
    """A complete binary decision with explicit preferred and secondary routes."""

    id: str
    condition: str = "True"
    true_branch: Sequence = field(default_factory=lambda: Sequence(new_id("sequence")))
    false_branch: Sequence = field(default_factory=lambda: Sequence(new_id("sequence")))
    preferred_truth: bool = True


@dataclass(frozen=True, slots=True)
class Case:
    id: str
    label: str
    body: Sequence
    condition: str = "False"
    pattern: str = "_"
    guard: str | None = None
    is_default: bool = False


@dataclass(frozen=True, slots=True)
class Select:
    id: str
    expression: str = "None"
    cases: tuple[Case, ...] = ()
    mode: SelectMode = SelectMode.CONDITIONS
    preferred_case_id: str | None = None


@dataclass(frozen=True, slots=True)
class Loop:
    id: str
    loop_kind: LoopKind
    body: Sequence
    else_body: Sequence
    condition: str = "False"
    target: str = "item"
    iterable: str = "[]"
    children: str = "lambda node: []"
    delay_seconds: str = "0.1"


@dataclass(frozen=True, slots=True)
class ContextItem:
    id: str
    expression: str = "nullcontext()"
    target: str | None = None


@dataclass(frozen=True, slots=True)
class With:
    id: str
    contexts: tuple[ContextItem, ...]
    body: Sequence
    asynchronous: bool = False


@dataclass(frozen=True, slots=True)
class ExceptionHandler:
    id: str
    exception: str = "Exception"
    name: str | None = "error"
    body: Sequence = field(default_factory=lambda: Sequence(new_id("sequence")))


@dataclass(frozen=True, slots=True)
class Try:
    id: str
    body: Sequence
    handlers: tuple[ExceptionHandler, ...]
    else_body: Sequence
    finally_body: Sequence
    except_star: bool = False


@dataclass(frozen=True, slots=True)
class Synchronizer:
    id: str
    timer: str
    deadline: str
    on_time: Sequence
    on_timeout: Sequence
    preferred_on_time: bool = True


@dataclass(frozen=True, slots=True)
class ParallelBranch:
    id: str
    name: str
    body: Sequence


@dataclass(frozen=True, slots=True)
class Parallel:
    id: str
    branches: tuple[ParallelBranch, ...]
    mode: ParallelMode = ParallelMode.SYNC


@dataclass(frozen=True, slots=True)
class SilhouetteBranch:
    id: str
    name: str
    body: Sequence
    target_branch_id: str | None = None


@dataclass(frozen=True, slots=True)
class Silhouette:
    id: str
    display_name: str
    identifier: str
    branches: tuple[SilhouetteBranch, ...]
    initial_branch_id: str


type DrakonAtom = (
    Action
    | Output
    | Assignment
    | Transfer
    | SimpleStatement
    | Call
    | Input
    | Delay
    | StartTimer
    | Period
    | RealtimeProcess
    | Note
    | If
    | Select
    | Loop
    | With
    | Try
    | Synchronizer
    | Parallel
    | Silhouette
)


@dataclass(frozen=True, slots=True)
class DrakonDiagram:
    id: str
    title: str
    header: Header
    body: Sequence
    end: End
    description: str = ""
    extensions: tuple[ExtensionField, ...] = ()
    kind: DocumentKind = DocumentKind.DRAKON


def create_empty_drakon(
    *,
    identifier: str = "main",
    title: str = "main",
    diagram_id: str | None = None,
) -> DrakonDiagram:
    resolved_id = diagram_id or new_id("diagram")
    function = FunctionSpec(identifier=identifier, display_name=title)
    return DrakonDiagram(
        id=resolved_id,
        title=title,
        header=Header(id=new_id("header"), function=function),
        body=Sequence(id=new_id("sequence")),
        end=End(id=new_id("end")),
    )


def nested_sequences(atom: DrakonAtom) -> tuple[Sequence, ...]:
    if isinstance(atom, If):
        return (atom.true_branch, atom.false_branch)
    if isinstance(atom, Select):
        return tuple(case.body for case in atom.cases)
    if isinstance(atom, Loop):
        return (atom.body, atom.else_body)
    if isinstance(atom, With):
        return (atom.body,)
    if isinstance(atom, Try):
        return (
            atom.body,
            *(handler.body for handler in atom.handlers),
            atom.else_body,
            atom.finally_body,
        )
    if isinstance(atom, Synchronizer):
        return (atom.on_time, atom.on_timeout)
    if isinstance(atom, Parallel):
        return tuple(branch.body for branch in atom.branches)
    if isinstance(atom, Silhouette):
        return tuple(branch.body for branch in atom.branches)
    return ()


def find_sequence(root: Sequence, sequence_id: str) -> Sequence | None:
    if root.id == sequence_id:
        return root
    for atom in root.atoms:
        for nested in nested_sequences(atom):
            found = find_sequence(nested, sequence_id)
            if found is not None:
                return found
    return None


def replace_sequence(root: Sequence, replacement: Sequence) -> Sequence:
    if root.id == replacement.id:
        return replacement
    changed = False
    atoms: list[DrakonAtom] = []
    for atom in root.atoms:
        updated = atom
        nested = nested_sequences(atom)
        replaced = tuple(replace_sequence(item, replacement) for item in nested)
        if any(before is not after for before, after in zip(nested, replaced, strict=True)):
            if isinstance(atom, If):
                updated = replace(atom, true_branch=replaced[0], false_branch=replaced[1])
            elif isinstance(atom, Select):
                updated = replace(
                    atom,
                    cases=tuple(
                        replace(case, body=body)
                        for case, body in zip(atom.cases, replaced, strict=True)
                    ),
                )
            elif isinstance(atom, Loop):
                updated = replace(atom, body=replaced[0], else_body=replaced[1])
            elif isinstance(atom, With):
                updated = replace(atom, body=replaced[0])
            elif isinstance(atom, Try):
                handler_count = len(atom.handlers)
                updated = replace(
                    atom,
                    body=replaced[0],
                    handlers=tuple(
                        replace(handler, body=replaced[index + 1])
                        for index, handler in enumerate(atom.handlers)
                    ),
                    else_body=replaced[handler_count + 1],
                    finally_body=replaced[handler_count + 2],
                )
            elif isinstance(atom, Synchronizer):
                updated = replace(atom, on_time=replaced[0], on_timeout=replaced[1])
            elif isinstance(atom, Parallel):  # noqa: SIM114 - distinct branch types
                updated = replace(
                    atom,
                    branches=tuple(
                        replace(branch, body=body)
                        for branch, body in zip(atom.branches, replaced, strict=True)
                    ),
                )
            elif isinstance(atom, Silhouette):
                updated = replace(
                    atom,
                    branches=tuple(
                        replace(branch, body=body)
                        for branch, body in zip(atom.branches, replaced, strict=True)
                    ),
                )
            changed = True
        atoms.append(updated)
    return Sequence(root.id, tuple(atoms)) if changed else root


def find_atom_location(root: Sequence, atom_id: str) -> tuple[Sequence, int] | None:
    for index, atom in enumerate(root.atoms):
        if atom.id == atom_id:
            return root, index
        for nested in nested_sequences(atom):
            found = find_atom_location(nested, atom_id)
            if found is not None:
                return found
    return None


def drakon_atom_ids(atom: DrakonAtom) -> tuple[str, ...]:
    result = [atom.id]
    if isinstance(atom, Select):
        result.extend(case.id for case in atom.cases)
    elif isinstance(atom, With):
        result.extend(item.id for item in atom.contexts)
    elif isinstance(atom, Try):
        result.extend(handler.id for handler in atom.handlers)
    elif isinstance(atom, (Parallel, Silhouette)):
        result.extend(branch.id for branch in atom.branches)
    for sequence in nested_sequences(atom):
        result.append(sequence.id)
        for child in sequence.atoms:
            result.extend(drakon_atom_ids(child))
    return tuple(result)


def owned_sequence_ids(atom: DrakonAtom) -> frozenset[str]:
    result: set[str] = set()
    for sequence in nested_sequences(atom):
        result.add(sequence.id)
        for child in sequence.atoms:
            result.update(owned_sequence_ids(child))
    return frozenset(result)
