"""Textual callable signatures shared by authoring and Python emission."""

from dataclasses import dataclass

from code_visualizer.domain.program_kinds import CallableKind, MethodKind, ParameterKind


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    name: str
    kind: ParameterKind = ParameterKind.POSITIONAL_OR_KEYWORD
    annotation: str | None = None
    default: str | None = None


@dataclass(frozen=True, slots=True)
class FunctionSpec:
    identifier: str
    display_name: str
    kind: CallableKind = CallableKind.SYNC
    parameters: tuple[ParameterSpec, ...] = ()
    return_annotation: str | None = None
    decorators: tuple[str, ...] = ()
    docstring: str | None = None
    module: str = "main"
    owning_class: str | None = None
    method_kind: MethodKind | None = None
