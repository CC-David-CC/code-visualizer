"""Disposable indexes for reading one immutable programming snapshot."""

from __future__ import annotations

from dataclasses import dataclass

from code_visualizer.domain.program import (
    ProgramClass,
    ProgramFunctionReference,
    ProgramModel,
    ProgramModule,
)


@dataclass(frozen=True, slots=True)
class ProgramFunctionLocation:
    module: ProgramModule
    owner: ProgramModule | ProgramClass
    class_name: str | None


def program_function_locations(model: ProgramModel) -> dict[str, ProgramFunctionLocation]:
    """Index declaration ownership once per operation, without caching canonical state.

    Invalid duplicate owners retain the same first-owner lookup behavior as the
    model's direct queries. Integrity validation separately reports duplicates.
    """
    result: dict[str, ProgramFunctionLocation] = {}

    def visit(
        module: ProgramModule, owner: ProgramModule | ProgramClass, classes: tuple[str, ...]
    ) -> None:
        location = ProgramFunctionLocation(module, owner, ".".join(classes) if classes else None)
        for item in owner.body:
            if isinstance(item, ProgramFunctionReference):
                result.setdefault(item.function_id, location)
            elif isinstance(item, ProgramClass):
                visit(module, item, (*classes, item.identifier))

    for module in model.modules:
        visit(module, module, ())
    return result
