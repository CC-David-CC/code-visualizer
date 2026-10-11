"""Derive authoring protection from retained inputs, never from a status cache."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256

from code_visualizer.application.experiment_inputs import definition_state
from code_visualizer.application.git import GitError, GitRepository
from code_visualizer.application.messages import CommandRejected
from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.project import Project
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.experiment_store import ExperimentStore, RetainedAttempt
from code_visualizer.persistence.serialization import project_to_data
from code_visualizer.persistence.store import JournalRecord


def frozen_session_admission(before: Project, record: JournalRecord) -> CommandRejected | None:
    """Protect an ordinary loaded session until its controller supplies fork admission."""
    if definition_state(before) == definition_state(record.project):
        return None
    return CommandRejected(
        "EXPERIMENT_CONTROLLER_REQUIRED",
        "Attach the Git experiment controller to fork this frozen definition before editing",
        before.revision,
        {},
    )


def recover_frozen_attempt(
    repository: GitRepository,
    store: ExperimentStore,
    marker: dict[str, JsonValue],
    project: Project,
    *,
    read_only: bool,
) -> str | None:
    """Ready is already frozen. Later phases and marker writes cannot unfreeze it.

    Refuse uncertain metadata rather than silently granting in-place edits. This
    reads operational metadata and Git refs, not bulk retained resource bytes.
    """
    try:
        return _recover(repository, store, marker, project, read_only=read_only)
    except (OSError, ValueError, GitError) as exc:
        raise GitError(
            "GIT_EXPERIMENT_RECOVERY",
            f"Frozen variant {repository.root.name} requires recovery: {exc}. "
            f"Restore the conflicting attempt/operation or retained ref in {store.root}, "
            "then reopen; execution will not be replayed",
        ) from exc


def _recover(
    repository: GitRepository,
    store: ExperimentStore,
    marker: dict[str, JsonValue],
    project: Project,
    *,
    read_only: bool,
) -> str | None:
    variant_id = repository.root.name
    attempts = {item.id: item for item in store.attempts()}
    owned = [item for item in attempts.values() if item.variant_id == variant_id]
    cached_id = marker.get("attempt_id")
    cached = attempts.get(str(cached_id)) if cached_id else None
    if cached_id and cached is None:
        raise ValueError(f"Marker references missing attempt {cached_id}")
    if cached is not None and cached.variant_id != variant_id:
        # A historical inspector borrows a run's input; it is never its author.
        if not read_only or marker.get("branch") != "":
            raise ValueError(f"Attempt {cached.id} belongs to another editing variant")
        if marker.get("base_commit") != cached.commit:
            raise ValueError(f"Inspection input disagrees with attempt {cached.id}")
        owned = [cached]
    for identity in store.identities("operations"):
        operation = store.read("operations", identity)
        if operation.get("kind") != "freeze" or operation.get("variant_id") != variant_id:
            continue
        attempt = attempts.get(identity)
        if attempt is None:
            if operation.get("phase") in {"attempt_ready", "submitted"}:
                raise ValueError(f"Freeze operation {identity} references a missing attempt")
        elif attempt.variant_id != variant_id or operation.get("commit") != attempt.commit:
            raise ValueError(f"Freeze operation {identity} contradicts its retained input")
    if not owned:
        if marker.get("frozen_commit"):
            raise ValueError("Frozen marker has no retained attempt")
        return None
    for attempt in owned:
        if attempt.project_path != repository.project_path:
            raise ValueError(f"Attempt {attempt.id} belongs to another project path")
        if (
            attempt.reference != f"refs/code-visualizer/runs/{attempt.id}"
            or repository.resolve_ref(attempt.reference) != attempt.commit
        ):
            raise ValueError(f"Retained ref disagrees with attempt {attempt.id}")
    inputs = {
        (item.commit, item.source_digest, item.closure_digest, item.definition_digest)
        for item in owned
    }
    if len(inputs) != 1:
        raise ValueError(f"Variant has contradictory frozen inputs: {[item.id for item in owned]}")
    if cached is not None and marker.get("frozen_commit") not in {"", cached.commit}:
        raise ValueError(f"Marker contradicts frozen commit of attempt {cached.id}")

    def creation_order(attempt: RetainedAttempt) -> tuple[datetime, str]:
        timestamp = datetime.fromisoformat(attempt.created_at)
        if timestamp.tzinfo is None:
            raise ValueError(f"Attempt {attempt.id} has no creation timezone")
        return timestamp, attempt.id

    selected = max(owned, key=creation_order)
    if not read_only and (
        sha256(canonical_data_bytes(project_to_data(definition_state(project)))).hexdigest()
        != selected.definition_digest
    ):
        raise ValueError(f"Authored definition differs from frozen attempt {selected.id}")
    return selected.id
