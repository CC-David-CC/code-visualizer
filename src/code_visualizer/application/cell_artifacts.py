"""Prepared commands for an exact retained cell consumer, awaiting one authority."""

from dataclasses import dataclass

from code_visualizer.application.commands import TypedCommand


@dataclass(frozen=True, slots=True)
class PreparedCellProbe:
    project_id: str
    revision: int
    model_id: str
    commands: tuple[TypedCommand, ...]
