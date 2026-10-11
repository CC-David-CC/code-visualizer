"""Prepare one revision-checked axial consumer of a retained CAD artifact."""

from dataclasses import replace

from code_visualizer.application.cad_artifacts import PreparedArtifactEdit, selected_artifact
from code_visualizer.application.domain_commands import PutDomainModel
from code_visualizer.application.domain_installation import bundle_installation
from code_visualizer.domain.common import new_id
from code_visualizer.domain.evidence import ComputationEvidence
from code_visualizer.domain.project import Project
from code_visualizer.extensions.axial.authoring import create_models
from code_visualizer.extensions.axial.domain import BACKEND_ID, BUNDLE
from code_visualizer.extensions.cad.resources import BREP, read_envelope_header
from code_visualizer.extensions.registry import DomainExtensionRegistry
from code_visualizer.persistence.resource_store import ResourceStore


def prepare_axial(
    project: Project,
    registry: DomainExtensionRegistry,
    evidence: ComputationEvidence,
    artifact_id: str,
    source_store: ResourceStore,
    target_store: ResourceStore,
    *,
    young_modulus: float,
    force: float,
    nodes: int,
    axis: str,
) -> PreparedArtifactEdit:
    artifact = selected_artifact(evidence, artifact_id)
    descriptor = source_store.describe(artifact.resource)
    if descriptor.logical_type != BREP or descriptor.byte_size > 64 * 1024 * 1024:
        raise ValueError("Axial analysis requires an exact bounded BREP resource")
    for reference in registry.resource_closure((artifact.resource,), source_store):
        target_store.import_reference(source_store, reference)
    with target_store.verified_path(artifact.resource).open("rb") as stream:
        header, size = read_envelope_header(stream, BREP)
        if stream.tell() + size != descriptor.byte_size:
            raise ValueError("The BREP payload size differs from its descriptor")
    installation = bundle_installation(project.domain_workspace, registry, BUNDLE)
    # The draft sees the same reference models the transaction will install.
    # Only the returned commands can change authoring through its authority.
    pending_models = tuple(
        command.model for command in installation if isinstance(command, PutDomainModel)
    )
    context = replace(
        project,
        domain_workspace=replace(
            project.domain_workspace, models=(*project.domain_workspace.models, *pending_models)
        ),
    )
    namespace = new_id("axial")
    models = create_models(
        context,
        artifact.resource,
        namespace=namespace,
        frame_id=header.frame.frame_id,
        young_modulus=young_modulus,
        force=force,
        nodes=nodes,
        axis=axis,
    )
    return PreparedArtifactEdit(
        project.id,
        project.revision,
        (*installation, *(PutDomainModel(model) for model in models)),
        models[0].id,
        models[0].roots[0],
        BACKEND_ID,
    )
