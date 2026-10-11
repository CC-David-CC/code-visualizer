"""Presentation command registry backed by semantic application actions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CommandSpec:
    id: str
    label: str
    category: str
    description: str
    execute: Callable[[], None]
    shortcut: str = ""
    is_enabled: Callable[[], bool] = lambda: True
    disabled_reason: Callable[[], str] = lambda: ""


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, CommandSpec] = {}

    def register(self, command: CommandSpec) -> None:
        if command.id in self._commands:
            raise ValueError(f"Command {command.id!r} is already registered")
        self._commands[command.id] = command

    def get(self, command_id: str) -> CommandSpec:
        return self._commands[command_id]

    def all(self) -> tuple[CommandSpec, ...]:
        return tuple(self._commands.values())
