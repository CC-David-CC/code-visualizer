"""Conservative checkpoint admission. Numerical state transfer is outside P2."""

from dataclasses import dataclass, replace

from code_visualizer.application.experiment_inputs import CapturedInputs
from code_visualizer.application.git import GitError
from code_visualizer.domain.computation import ComputationParameter, ComputationRequest
from code_visualizer.extensions.registry import DomainExtensionRegistry
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.experiment_store import ExperimentStore
from code_visualizer.persistence.resource_store import ResourceStore


@dataclass(frozen=True, slots=True)
class ResumeCheckpoint:
    attempt_id: str
    publication_id: str


def bind_checkpoint(
    inputs: CapturedInputs,
    resume: ResumeCheckpoint,
    registry: DomainExtensionRegistry,
    store: ExperimentStore,
) -> ComputationRequest:
    parent = store.attempt(resume.attempt_id)
    if (parent.compatibility_digest or parent.closure_digest) != inputs.closure_digest:
        raise GitError(
            "CHECKPOINT_INCOMPATIBLE", "Changed inputs require an explicit state-transfer operation"
        )
    backend = registry.backend(inputs.request.backend_id, inputs.request.backend_version)
    if backend is None or backend.checkpoint is None:
        raise GitError(
            "CHECKPOINT_UNSUPPORTED", "The registered backend does not declare restart semantics"
        )
    if resume.publication_id not in parent.publications:
        raise GitError(
            "CHECKPOINT_NOT_SEALED", "Checkpoint was not sealed by the selected parent attempt"
        )
    publication = EvidenceStore(store.root).get_publication(resume.publication_id)
    if publication.provenance.input_digest != parent.input_digest:
        raise GitError(
            "CHECKPOINT_INCOMPATIBLE", "Checkpoint provenance does not match its parent input"
        )
    reference = publication.artifact.resource
    resources = ResourceStore(store.root)
    descriptor = resources.describe(reference)
    resources.verified_path(reference)
    if descriptor.logical_type != backend.checkpoint.logical_type:
        raise GitError("CHECKPOINT_TYPE", "Resource does not match the backend checkpoint contract")
    if any(item.name == backend.checkpoint.parameter for item in inputs.request.configuration):
        raise GitError(
            "CHECKPOINT_BINDING", "Checkpoint binding must be owned by explicit resume admission"
        )
    return replace(
        inputs.request,
        configuration=(
            *inputs.request.configuration,
            ComputationParameter(backend.checkpoint.parameter, reference),
        ),
    )
