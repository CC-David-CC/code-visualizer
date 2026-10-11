"""Deterministic static contribution registry used by application seams."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StaticContribution[T]:
    id: str
    value: T
    order: int = 0


class StaticContributionRegistry[T]:
    """Explicit composition root; this is intentionally not a plugin loader."""

    def __init__(self) -> None:
        self._entries: dict[str, StaticContribution[T]] = {}

    def register(self, contribution_id: str, value: T, *, order: int = 0) -> None:
        if contribution_id in self._entries:
            raise ValueError(f"Contribution {contribution_id!r} is already registered")
        self._entries[contribution_id] = StaticContribution(contribution_id, value, order)

    def get(self, contribution_id: str) -> T:
        try:
            return self._entries[contribution_id].value
        except KeyError as exc:
            raise KeyError(f"Unknown contribution {contribution_id!r}") from exc

    def contributions(self) -> tuple[StaticContribution[T], ...]:
        return tuple(sorted(self._entries.values(), key=lambda item: (item.order, item.id)))

    def mapping(self) -> dict[str, T]:
        return {item.id: item.value for item in self.contributions()}
