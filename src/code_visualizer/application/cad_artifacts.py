"""Prepare resource-consuming authoring commands outside GUI/authority handlers."""

from dataclasses import dataclass

from code_visualizer.application.commands import TypedCommand
from code_visualizer.application.domain_commands import PromoteEvidenceArtifact, PutDomainModel
from code_visualizer.application.domain_installation import bundle_installation
from code_visualizer.domain.common import new_id
from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.evidence import (
    ComputationEvidence,
    ComputationOutcome,
    EvidenceArtifact,
)
from code_visualizer.domain.project import Project
from code_visualizer.domain.values import CanonicalValue
from code_visualizer.extensions.cad.domain import BUNDLE, consumer_model, identity
from code_visualizer.extensions.cad.native import implementation_version
from code_visualizer.extensions.cad.resources import (
    BREP,
    MAX_HEADER_BYTES,
    MAX_PAYLOAD_BYTES,
    CadError,
    read_envelope_header,
)
from code_visualizer.extensions.registry import DomainExtensionRegistry
from code_visualizer.persistence.evidence import evidence_content_hash
from code_visualizer.persistence.resource_store import ResourceStore


@dataclass(frozen=True, slots=True)
class PreparedArtifactEdit:
    project_id: str
    revision: int
    commands: tuple[TypedCommand, ...]
    model_id: str
    node_id: str
    backend_id: str

    def request(self, project: Project) -> ComputationRequest:
        if project.id != self.project_id or project.domain_workspace.model(self.model_id) is None:
            raise ValueError("Accept the prepared authoring command before computing")
        return ComputationRequest(project.id, project.revision, self.backend_id, "1", self.model_id)


def selected_artifact(evidence: ComputationEvidence, artifact_id: str) -> EvidenceArtifact:
    if evidence.id != "evidence:" + evidence_content_hash(evidence):
        raise CadError("CAD_EVIDENCE_HASH", "Selected evidence failed its content hash")
    if evidence.outcome is not ComputationOutcome.SUCCEEDED:
        raise CadError("CAD_PRODUCER_OUTCOME", "Select a successful producer's explicit artifact")
    artifact = next((a for a in evidence.artifacts if a.id == artifact_id), None)
    if artifact is None:
        raise CadError("CAD_ARTIFACT", "Selected artifact is absent")
    return artifact


def prepare_consumer(
    project: Project,
    registry: DomainExtensionRegistry,
    evidence: ComputationEvidence,
    artifact_id: str,
    source_store: ResourceStore,
    target_store: ResourceStore,
    concept: str,
    *,
    model_id: str | None = None,
    node_id: str | None = None,
    properties: tuple[tuple[str, CanonicalValue], ...] = (),
) -> PreparedArtifactEdit:
    """Verify/retain exact bytes, then offer a single revision-checked transaction.

    There is no producer replay. A failed command may leave immutable retained
    bytes, but cannot publish a half-created authored input.
    """
    artifact = selected_artifact(evidence, artifact_id)
    if (
        evidence.provenance.project_id != project.id
        or evidence.provenance.revision > project.revision
    ):
        raise CadError("CAD_EVIDENCE_REVISION", "Select evidence of an existing project revision")
    descriptor = source_store.describe(artifact.resource)
    if descriptor.logical_type != BREP:
        raise CadError("CAD_TYPE_MISMATCH", "This operation requires an exact BREP resource")
    if descriptor.byte_size > MAX_HEADER_BYTES + MAX_PAYLOAD_BYTES + 20:
        raise CadError("CAD_SIZE", "Geometry exceeds the supported bound")
    path = source_store.verified_path(artifact.resource)
    with path.open("rb") as stream:
        header, size = read_envelope_header(stream, BREP)
        if stream.tell() + size != descriptor.byte_size:
            raise CadError("CAD_SIZE", "Geometry payload length differs from its descriptor")
        if not stream.read(20).startswith(b"DBRep_DrawableShape"):
            raise CadError("CAD_BREP_INVALID", "Missing Open Cascade BREP signature")
    if (
        header.serializer != "org.opencascade.brep"
        or header.serializer_version != implementation_version()
    ):
        raise CadError("CAD_DECODER_UNSUPPORTED", "This native serializer version is not qualified")
    # Native topology is interpreted only by the isolated computation backend.
    # Preparing an authored resource binding never loads OCP into the GUI process.
    target_store.import_reference(source_store, artifact.resource)
    options = dict(properties)
    if concept == "RegionSelection":
        options.setdefault("frame_id", header.frame.frame_id)
    if concept == "GeometryInput":
        options.update(source_evidence=evidence.id, source_artifact=artifact.id)
    model_id, node_id = model_id or new_id("cad-model"), node_id or new_id("cad-operation")
    model = consumer_model(model_id, node_id, concept, artifact.resource, **options)
    command: TypedCommand = (
        PromoteEvidenceArtifact(
            evidence, artifact.id, model, node_id, identity(concept, "geometry")
        )
        if concept == "GeometryInput"
        else PutDomainModel(model)
    )
    return PreparedArtifactEdit(
        project.id,
        project.revision,
        (*bundle_installation(project.domain_workspace, registry, BUNDLE), command),
        model_id,
        node_id,
        "code_visualizer.cad." + concept.lower(),
    )
