"""Shared immutable value types for the three domain models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


class DocumentKind(StrEnum):
    DRAKON = "drakon"
    MIND_MAP = "mind_map"
    FREEFORM = "freeform"


@dataclass(frozen=True, slots=True)
class ExtensionField:
    """Namespaced inert data reserved for a declared future extension."""

    namespace: str
    values: tuple[tuple[str, JsonValue], ...] = ()


def new_id(prefix: str) -> str:
    """Create an opaque stable identifier with a human-debuggable type prefix."""

    normalized = prefix.strip().lower().replace(" ", "-")
    if not normalized or not normalized.replace("-", "").isalnum():
        raise ValueError("ID prefix must contain letters, numbers, or hyphens")
    return f"{normalized}_{uuid4().hex}"
