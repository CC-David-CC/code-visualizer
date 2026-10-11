"""Qt-free typed Python intermediate representation.

The IR is the sole input to every Python emitter. It deliberately carries
semantic origins without embedding project IDs into ordinary Python names.
"""

from __future__ import annotations

from dataclasses import dataclass

from code_visualizer.domain.invocation import InvocationSpec
from code_visualizer.domain.program_kinds import (
    CallableKind,
    LoopKind,
    MethodKind,
    ParallelMode,
    ProgramModuleKind,
    SelectMode,
    SimpleKind,
    TransferKind,
)
from code_visualizer.domain.program_signatures import ParameterSpec


@dataclass(frozen=True, slots=True)
class Origin:
    project_id: str
    semantic_id: str
    field: str
    presentation_id: str | None = None


@dataclass(frozen=True, slots=True)
class PassIR:
    origin: Origin


@dataclass(frozen=True, slots=True)
class RawStatementIR:
    source: str
    origin: Origin


@dataclass(frozen=True, slots=True)
class OutputIR:
    expression: str
    destination: str | None
    end: str | None
    origin: Origin


@dataclass(frozen=True, slots=True)
class AssignmentIR:
    target: str
    value: str
    annotation: str | None
    operator: str
    origin: Origin


@dataclass(frozen=True, slots=True)
class IfIR:
    condition: str
    true_branch: tuple[StatementIR, ...]
    false_branch: tuple[StatementIR, ...]
    preferred_truth: bool
    origin: Origin


@dataclass(frozen=True, slots=True)
class TransferIR:
    kind: TransferKind
    expression: str
    cause: str | None
    origin: Origin


@dataclass(frozen=True, slots=True)
class SimpleStatementIR:
    kind: SimpleKind
    source: str
    secondary: str | None
    origin: Origin


@dataclass(frozen=True, slots=True)
class CallIR:
    expression: str
    awaited: bool
    result_target: str | None
    origin: Origin


@dataclass(frozen=True, slots=True)
class InputIR:
    target: str
    prompt: str
    converter: str | None
    annotation: str | None
    origin: Origin


@dataclass(frozen=True, slots=True)
class DelayIR:
    seconds: str
    asynchronous: bool
    origin: Origin


@dataclass(frozen=True, slots=True)
class StartTimerIR:
    timer: str
    origin: Origin


@dataclass(frozen=True, slots=True)
class PeriodIR:
    timer: str
    seconds: str
    asynchronous: bool
    origin: Origin


@dataclass(frozen=True, slots=True)
class RealtimeProcessIR:
    call: str
    awaited: bool
    origin: Origin


@dataclass(frozen=True, slots=True)
class NoteIR:
    text: str
    placement: str
    origin: Origin


@dataclass(frozen=True, slots=True)
class SelectCaseIR:
    id: str
    label: str
    condition: str
    pattern: str
    guard: str | None
    is_default: bool
    body: tuple[StatementIR, ...]
    origin: Origin


@dataclass(frozen=True, slots=True)
class SelectIR:
    expression: str
    cases: tuple[SelectCaseIR, ...]
    mode: SelectMode
    preferred_case_id: str | None
    origin: Origin


@dataclass(frozen=True, slots=True)
class LoopIR:
    kind: LoopKind
    body: tuple[StatementIR, ...]
    else_body: tuple[StatementIR, ...]
    condition: str
    target: str
    iterable: str
    children: str
    delay_seconds: str
    origin: Origin


@dataclass(frozen=True, slots=True)
class ContextItemIR:
    expression: str
    target: str | None
    origin: Origin


@dataclass(frozen=True, slots=True)
class WithIR:
    contexts: tuple[ContextItemIR, ...]
    body: tuple[StatementIR, ...]
    asynchronous: bool
    origin: Origin


@dataclass(frozen=True, slots=True)
class ExceptionHandlerIR:
    exception: str
    name: str | None
    body: tuple[StatementIR, ...]
    origin: Origin


@dataclass(frozen=True, slots=True)
class TryIR:
    body: tuple[StatementIR, ...]
    handlers: tuple[ExceptionHandlerIR, ...]
    else_body: tuple[StatementIR, ...]
    finally_body: tuple[StatementIR, ...]
    except_star: bool
    origin: Origin


@dataclass(frozen=True, slots=True)
class SynchronizerIR:
    timer: str
    deadline: str
    on_time: tuple[StatementIR, ...]
    on_timeout: tuple[StatementIR, ...]
    preferred_on_time: bool
    origin: Origin


@dataclass(frozen=True, slots=True)
class ParallelBranchIR:
    name: str
    body: tuple[StatementIR, ...]
    origin: Origin


@dataclass(frozen=True, slots=True)
class ParallelIR:
    branches: tuple[ParallelBranchIR, ...]
    mode: ParallelMode
    origin: Origin


@dataclass(frozen=True, slots=True)
class SilhouetteBranchIR:
    name: str
    body: tuple[StatementIR, ...]
    target_name: str | None
    origin: Origin


@dataclass(frozen=True, slots=True)
class SilhouetteIR:
    display_name: str
    identifier: str
    branches: tuple[SilhouetteBranchIR, ...]
    initial_name: str
    origin: Origin


type StatementIR = (
    PassIR
    | RawStatementIR
    | OutputIR
    | AssignmentIR
    | IfIR
    | TransferIR
    | SimpleStatementIR
    | CallIR
    | InputIR
    | DelayIR
    | StartTimerIR
    | PeriodIR
    | RealtimeProcessIR
    | NoteIR
    | SelectIR
    | LoopIR
    | WithIR
    | TryIR
    | SynchronizerIR
    | ParallelIR
    | SilhouetteIR
)


@dataclass(frozen=True, slots=True)
class FunctionIR:
    callable_id: str
    presentation_id: str | None
    identifier: str
    display_name: str
    kind: CallableKind
    parameters: tuple[ParameterSpec, ...]
    return_annotation: str | None
    decorators: tuple[str, ...]
    docstring: str | None
    module: str
    owning_class: str | None
    method_kind: MethodKind | None
    body: tuple[StatementIR, ...]
    signature_origin: Origin
    type_parameters: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ClassIR:
    identifier: str
    arguments: str | None
    decorators: tuple[str, ...]
    docstring: str | None
    type_parameters: tuple[str, ...]
    body: tuple[DeclarationIR, ...]
    origin: Origin


type DeclarationIR = StatementIR | FunctionIR | ClassIR


@dataclass(frozen=True, slots=True)
class ModuleIR:
    path: str
    docstring: str
    body: tuple[DeclarationIR, ...]
    origin: Origin
    kind: ProgramModuleKind = ProgramModuleKind.MODULE


@dataclass(frozen=True, slots=True)
class EntryPointIR:
    module: str
    invocation: InvocationSpec
    origin: Origin

    @property
    def callable_id(self) -> str | None:
        return self.invocation.callable_id


@dataclass(frozen=True, slots=True)
class PythonProjectIR:
    project_id: str
    revision: int
    package: str
    modules: tuple[ModuleIR, ...]
    startup: tuple[DeclarationIR, ...]
    entrypoint: EntryPointIR | None
