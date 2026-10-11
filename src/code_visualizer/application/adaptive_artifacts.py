"""Prepare a support-aware retained consumer off-thread, then submit ordinary commands."""

from code_visualizer.application.cell_artifacts import PreparedCellProbe
from code_visualizer.application.domain_commands import PutDomainModel
from code_visualizer.application.domain_installation import bundle_installation
from code_visualizer.domain.common import new_id
from code_visualizer.domain.intentional import DomainModel, IntentionalNode, PropertyValue
from code_visualizer.domain.project import Project
from code_visualizer.domain.values import CanonicalValue, ResourceReference
from code_visualizer.extensions.adaptive_fields.domain import BUNDLE, SCHEMA_ID, identity
from code_visualizer.extensions.adaptive_fields.history import AdaptiveHistory
from code_visualizer.extensions.registry import DomainExtensionRegistry
from code_visualizer.persistence.computation_resources import resolve_computation_resource
from code_visualizer.persistence.resource_store import ResourceStore


def prepare_probe(
    project: Project,
    registry: DomainExtensionRegistry,
    source_store: ResourceStore,
    target_store: ResourceStore,
    history: ResourceReference,
    sample: int,
    epoch: int,
    cell_id: str,
    component_id: str,
) -> PreparedCellProbe:
    for reference in registry.resource_closure((history,), source_store):
        target_store.import_reference(source_store, reference)
    reader = AdaptiveHistory(
        history, lambda ref: resolve_computation_resource(target_store, ref, file_backed=True)
    )
    try:
        reader.probe(sample, epoch, cell_id, component_id)
        selected = reader.slice(sample)
        model_id, node_id = new_id("cell-probe-model"), new_id("cell-probe")
        values: tuple[tuple[str, CanonicalValue], ...] = (
            ("name", f"{component_id}, {cell_id}, sample {sample}"),
            ("history", history),
            ("sample", sample),
            ("epoch", epoch),
            ("cell_id", cell_id),
            ("component_id", component_id),
            ("time", selected.position.time),
        )
        model = DomainModel(
            model_id,
            SCHEMA_ID,
            "1",
            (node_id,),
            (
                IntentionalNode(
                    node_id,
                    identity("Probe"),
                    tuple(PropertyValue(identity("Probe", key), value) for key, value in values),
                ),
            ),
            "Exact retained cell probe",
        )
        return PreparedCellProbe(
            project.id,
            project.revision,
            model_id,
            (
                *bundle_installation(project.domain_workspace, registry, BUNDLE),
                PutDomainModel(model),
            ),
        )
    finally:
        reader.close()
