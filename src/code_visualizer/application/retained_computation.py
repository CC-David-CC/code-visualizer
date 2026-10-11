"""Admission adapter linking a host computation to its already retained Git input."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from code_visualizer.application.git import GitRepository
from code_visualizer.persistence.experiment_store import ExperimentStore

if TYPE_CHECKING:
    from code_visualizer.application.computation_service import ComputationAttempt


@dataclass(frozen=True, slots=True)
class RetainedComputation:
    id: str
    repository: GitRepository
    store: ExperimentStore

    def admit(self, source_digest: str) -> None:
        attempt = self.store.attempt(self.id)
        if (
            attempt.phase != "ready"
            or attempt.source_digest != source_digest
            or self.repository.resolve_ref(attempt.reference) != attempt.commit
        ):
            raise ValueError("Computation requires its exact ready attempt and retained input ref")
        self.store.update_attempt(self.id, phase="admitted")

    def changed(self, previous: ComputationAttempt, current: ComputationAttempt) -> None:
        # Never fsync for progress ticks or a GUI cancellation acknowledgement.
        if current.phase == "cancelling":
            return
        if previous.publications != current.publications:
            self.store.record_publications(self.id, current.publications)
        if (previous.phase, previous.input_digest, previous.session.evidence_id) == (
            current.phase,
            current.input_digest,
            current.session.evidence_id,
        ):
            return
        self.store.update_attempt(
            self.id,
            phase=current.phase,
            input_digest=current.input_digest or "",
            evidence_id=current.session.evidence_id or "",
            diagnostic=current.diagnostic,
        )
