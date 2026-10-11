"""Prepare explicit retained checkpoint choices; all Git/resource work is host-owned."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from code_visualizer.application.experiment_checkpoints import ResumeCheckpoint
from code_visualizer.application.experiment_inputs import INPUT_MANIFEST, SourceInput
from code_visualizer.application.git import GitError
from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.values import ResourceReference
from code_visualizer.persistence.computation import computation_request_from_data
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore

if TYPE_CHECKING:
    from code_visualizer.application.git_experiments import GitExperiments


@dataclass(frozen=True, slots=True)
class CheckpointChoice:
    attempt_id: str
    publication_id: str
    label: str
    resource: ResourceReference


def checkpoint_choices(
    experiments: GitExperiments, attempt_id: str
) -> tuple[CheckpointChoice, ...]:
    attempt = experiments.verify_run(attempt_id)
    evidence = EvidenceStore(experiments.store.root)
    resources = ResourceStore(experiments.store.root)
    registry = experiments.controller.session.kernel.extensions
    choices = []
    for identity in attempt.publications:
        publication = evidence.get_publication(identity)
        provenance = publication.provenance
        if provenance.input_digest != attempt.input_digest:
            raise GitError("CHECKPOINT_PROVENANCE", "Publication belongs to another retained input")
        backend = registry.backend(provenance.backend_id, provenance.backend_version)
        if backend is None or backend.checkpoint is None:
            continue
        descriptor = resources.describe(publication.artifact.resource)
        if descriptor.logical_type != backend.checkpoint.logical_type:
            continue
        resources.verified_path(descriptor.reference)
        choices.append(
            CheckpointChoice(
                attempt.id,
                identity,
                publication.artifact.label or publication.artifact.id,
                descriptor.reference,
            )
        )
    return tuple(choices)


def checkpoint_request(
    experiments: GitExperiments, resume: ResumeCheckpoint
) -> tuple[ComputationRequest, tuple[SourceInput, ...]]:
    """Recover the original request, then let the existing freeze/bind transaction decide.

    Resumed attempts carry an additional input. Walk their explicit parent chain
    to the unresumed request instead of subtracting resources heuristically.
    """
    if not any(
        choice.publication_id == resume.publication_id
        for choice in checkpoint_choices(experiments, resume.attempt_id)
    ):
        raise GitError(
            "CHECKPOINT_SELECTION", "Select a sealed checkpoint belonging to this attempt"
        )
    base = experiments.verify_run(resume.attempt_id)
    seen = {base.id}
    while base.checkpoint_id:
        if not base.parent_attempt or base.parent_attempt in seen or len(seen) >= 256:
            raise GitError(
                "CHECKPOINT_CHAIN", "Retained checkpoint ancestry is invalid or excessive"
            )
        base = experiments.verify_run(base.parent_attempt)
        seen.add(base.id)
    manifest = json.loads(experiments.repository.read_input(base.commit, INPUT_MANIFEST))
    request = computation_request_from_data(manifest["request"])
    project = experiments.controller.session.authority.snapshot()
    if request.project_id != project.id:
        raise GitError("CHECKPOINT_PROJECT", "The selected checkpoint belongs to another project")
    sources = tuple(SourceInput(item["path"], item["destination"]) for item in manifest["sources"])
    return replace(request, revision=project.revision), sources
