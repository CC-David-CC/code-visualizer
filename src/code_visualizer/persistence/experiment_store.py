"""Durable operational run envelopes, separate from content-derived evidence."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock

from code_visualizer.domain.common import JsonValue
from code_visualizer.persistence.store import ProjectStore
from code_visualizer.persistence.values import array_data, object_data, text_data


@dataclass(frozen=True, slots=True)
class RetainedAttempt:
    id: str
    commit: str
    reference: str
    variant_id: str
    project_path: str
    source_digest: str
    closure_digest: str
    definition_digest: str
    created_at: str
    phase: str = "ready"
    evidence_id: str = ""
    input_digest: str = ""
    diagnostic: str = ""
    parent_attempt: str = ""
    checkpoint_id: str = ""
    publications: tuple[str, ...] = ()
    compatibility_digest: str = ""


class ExperimentStore:
    """An owned retention root, never an editor worktree; writes are bounded/atomic."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._lock = RLock()

    def _path(self, family: str, identity: str) -> Path:
        if not identity or not identity.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Operational identities must be opaque path-safe IDs")
        return self.root / family / f"{identity}.json"

    def write(self, family: str, identity: str, data: dict[str, JsonValue]) -> None:
        path = self._path(family, identity)
        path.parent.mkdir(parents=True, exist_ok=True)
        ProjectStore(self.root)._atomic_write(
            path, json.dumps(data, sort_keys=True, indent=2) + "\n", max_bytes=2 * 1024 * 1024
        )

    def read(self, family: str, identity: str) -> dict[str, JsonValue]:
        path = self._path(family, identity)
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("Experiment metadata exceeds its bounded envelope")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("version") != 1:
            raise ValueError("Unsupported experiment metadata")
        return value

    def create_attempt(self, attempt: RetainedAttempt) -> None:
        with self._lock:
            if self._path("attempts", attempt.id).exists():
                raise ValueError("A retained attempt identity cannot be reused")
            self.write("attempts", attempt.id, {"version": 1, **asdict(attempt)})

    def attempt(self, identity: str) -> RetainedAttempt:
        data = self.read("attempts", identity)
        if data.get("id") != identity:
            raise ValueError(f"Retained attempt identity changed: {identity}")
        fields = set(RetainedAttempt.__dataclass_fields__)
        object_data(data, fields | {"version"})
        publications = tuple(text_data(item) for item in array_data(data.get("publications", [])))
        return RetainedAttempt(
            **{
                key: text_data(
                    data.get(key, "") if key == "compatibility_digest" else data.get(key)
                )
                for key in fields - {"publications"}
            },
            publications=publications,
        )

    def update_attempt(self, identity: str, **changes: str) -> RetainedAttempt:
        with self._lock:
            if set(changes) - {"phase", "evidence_id", "input_digest", "diagnostic"}:
                raise ValueError("Attempt input identity is immutable")
            previous = self.attempt(identity)
            updated = replace(
                previous,
                phase=changes.get("phase", previous.phase),
                evidence_id=changes.get("evidence_id", previous.evidence_id),
                input_digest=changes.get("input_digest", previous.input_digest),
                diagnostic=changes.get("diagnostic", previous.diagnostic),
            )
            self.write("attempts", identity, {"version": 1, **asdict(updated)})
            return updated

    def record_publications(self, identity: str, publications: tuple[str, ...]) -> None:
        with self._lock:
            previous = self.attempt(identity)
            if not set(previous.publications).issubset(publications):
                raise ValueError("A retained publication cannot be retracted")
            updated = replace(previous, publications=publications)
            self.write("attempts", identity, {"version": 1, **asdict(updated)})

    def attempts(self) -> tuple[RetainedAttempt, ...]:
        return tuple(self.attempt(identity) for identity in self.identities("attempts"))

    def identities(self, family: str) -> tuple[str, ...]:
        # glob can suppress directory access errors. An unreadable history must
        # never look like an empty one when deciding whether editing is allowed.
        try:
            return tuple(
                sorted(
                    path.stem for path in (self.root / family).iterdir() if path.suffix == ".json"
                )
            )
        except FileNotFoundError:
            return ()

    def interrupted(self, active_ids: frozenset[str] = frozenset()) -> tuple[str, ...]:
        """Explicit host recovery never guesses whether an orphan worker completed."""
        recovered = []
        for attempt in self.attempts():
            if attempt.id not in active_ids and attempt.phase not in {
                "finished",
                "failed",
                "interrupted",
            }:
                self.update_attempt(
                    attempt.id,
                    phase="interrupted",
                    diagnostic="Host recovery: execution was not automatically replayed",
                )
                recovered.append(attempt.id)
        return tuple(recovered)


def now() -> str:
    return datetime.now(UTC).isoformat()
