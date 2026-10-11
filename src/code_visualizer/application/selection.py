"""Application-wide semantic selection independent of any Qt widget."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from threading import RLock


@dataclass(frozen=True, slots=True)
class SelectionState:
    """One selection expressed only in stable semantic identities."""

    project_id: str
    revision: int
    semantic_ids: tuple[str, ...] = ()
    primary: str | None = None
    source: str = "system"
    execution_session_id: str | None = None

    def __post_init__(self) -> None:
        if len(set(self.semantic_ids)) != len(self.semantic_ids):
            raise ValueError("semantic_ids must not contain duplicates")
        if self.primary is not None and self.primary not in self.semantic_ids:
            raise ValueError("primary must be present in semantic_ids")


SelectionListener = Callable[[SelectionState], None]


class SelectionService:
    """Publish/subscribe selection highway shared by every visual projection."""

    def __init__(self, project_id: str, revision: int) -> None:
        self._state = SelectionState(project_id, revision)
        self._listeners: list[SelectionListener] = []
        self._lock = RLock()

    @property
    def state(self) -> SelectionState:
        with self._lock:
            return self._state

    def subscribe(
        self,
        listener: SelectionListener,
        *,
        replay: bool = True,
    ) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(listener)
            current = self._state
        if replay:
            listener(current)

        def unsubscribe() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe

    def select(
        self,
        semantic_ids: Iterable[str],
        *,
        primary: str | None = None,
        revision: int | None = None,
        source: str,
        execution_session_id: str | None = None,
    ) -> SelectionState:
        ordered = tuple(dict.fromkeys(item for item in semantic_ids if item))
        resolved_primary = primary if primary is not None else next(iter(ordered), None)
        if resolved_primary is not None and resolved_primary not in ordered:
            ordered = (resolved_primary, *ordered)
        with self._lock:
            candidate = SelectionState(
                self._state.project_id,
                self._state.revision if revision is None else revision,
                ordered,
                resolved_primary,
                source,
                execution_session_id,
            )
        return self.publish(candidate)

    def clear(self, *, revision: int | None = None, source: str) -> SelectionState:
        return self.select((), revision=revision, source=source)

    def publish(self, state: SelectionState) -> SelectionState:
        with self._lock:
            if state.project_id != self._state.project_id:
                raise ValueError("selection belongs to another project")
            if state == self._state:
                return state
            self._state = state
            listeners = tuple(self._listeners)
        for listener in listeners:
            listener(state)
        return state

    def rebase(self, revision: int, available_ids: Iterable[str]) -> SelectionState:
        """Advance selection to a revision, dropping semantic IDs that disappeared."""

        available = frozenset(available_ids)
        with self._lock:
            current = self._state
        retained = tuple(item for item in current.semantic_ids if item in available)
        primary = current.primary if current.primary in retained else next(iter(retained), None)
        return self.publish(
            SelectionState(
                current.project_id,
                revision,
                retained,
                primary,
                current.source,
                current.execution_session_id,
            )
        )
