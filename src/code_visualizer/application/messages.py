"""Versioned command and event envelopes shared by every adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from code_visualizer.domain.common import JsonValue


@dataclass(frozen=True, slots=True)
class CommandEnvelope:
    command_type: str
    actor_id: str
    operation_id: str
    project_id: str
    expected_revision: int | None
    payload: dict[str, JsonValue]
    schema_version: int = 1
    transaction_id: str | None = None
    intent: str = ""


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    event_type: str
    actor_id: str
    operation_id: str
    project_id: str
    revision: int
    payload: dict[str, JsonValue]
    schema_version: int = 1
    occurred_at: str = ""
    affected_ids: tuple[str, ...] = ()

    @classmethod
    def now(
        cls,
        *,
        event_type: str,
        actor_id: str,
        operation_id: str,
        project_id: str,
        revision: int,
        payload: dict[str, JsonValue],
        affected_ids: tuple[str, ...] = (),
    ) -> EventEnvelope:
        return cls(
            event_type=event_type,
            actor_id=actor_id,
            operation_id=operation_id,
            project_id=project_id,
            revision=revision,
            payload=payload,
            occurred_at=datetime.now(UTC).isoformat(),
            affected_ids=affected_ids,
        )


@dataclass(frozen=True, slots=True)
class CommandAccepted:
    revision: int
    affected_ids: tuple[str, ...]
    events: tuple[EventEnvelope, ...]
    undo_group_id: str


@dataclass(frozen=True, slots=True)
class CommandRejected:
    code: str
    message: str
    current_revision: int
    details: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class CommandDeferred:
    """Host admission is pending; the command has not changed canonical state."""

    code: str
    message: str
    current_revision: int
    details: dict[str, JsonValue]


CommandResult = CommandAccepted | CommandRejected | CommandDeferred
