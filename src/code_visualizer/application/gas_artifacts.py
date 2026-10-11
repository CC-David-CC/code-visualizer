"""Prepare exact retained gas queries off-thread for the existing project authority."""

from code_visualizer.application.cell_artifacts import PreparedCellProbe
from code_visualizer.application.domain_commands import PutDomainModel
from code_visualizer.application.domain_installation import bundle_installation
from code_visualizer.domain.common import new_id
from code_visualizer.domain.intentional import DomainModel, IntentionalNode, PropertyValue
from code_visualizer.domain.project import Project
from code_visualizer.domain.values import CanonicalValue, ResourceReference
from code_visualizer.extensions.gas_observation.domain import BUNDLE, SCHEMA_ID, identity
from code_visualizer.extensions.gas_observation.reader import probe
from code_visualizer.extensions.hybrid_gas.history import GasHistory
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
    if epoch != 0:
        raise ValueError("This retained gas support has exactly one partition")
    for reference in registry.resource_closure((history,), source_store):
        target_store.import_reference(source_store, reference)
    reader = GasHistory(
        history, lambda r: resolve_computation_resource(target_store, r, file_backed=True)
    )
    try:
        selected = reader.gas_slice(sample)
        frame = reader.interpretation.frame_id
        probe(reader, sample, cell_id, component_id, frame, selected.position.time)
        model_id, node_id = new_id("gas-probe-model"), new_id("gas-probe")
        values: tuple[tuple[str, CanonicalValue], ...] = (
            ("name", f"{component_id}, {cell_id}, sample {sample}"),
            ("history", history),
            ("sample", sample),
            ("cell_id", cell_id),
            ("component_id", component_id),
            ("frame_id", frame),
            ("time", selected.position.time),
        )
        model = DomainModel(
            model_id,
            SCHEMA_ID,
            "1",
            (node_id,),
            (
                IntentionalNode(
                    node_id, identity(), tuple(PropertyValue(identity(k), v) for k, v in values)
                ),
            ),
            "Exact retained gas cell",
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
