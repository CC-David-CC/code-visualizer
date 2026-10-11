"""Prepare exact field consumers off the GUI thread; accept through the existing authority."""

from dataclasses import dataclass

from code_visualizer.application.commands import TypedCommand
from code_visualizer.application.domain_commands import PutDomainModel
from code_visualizer.application.domain_installation import bundle_installation
from code_visualizer.domain.common import new_id
from code_visualizer.domain.intentional import DomainModel, IntentionalNode, PropertyValue
from code_visualizer.domain.project import Project
from code_visualizer.domain.values import CanonicalValue, ResourceReference
from code_visualizer.extensions.fields.domain import BUNDLE, SCHEMA_ID, identity
from code_visualizer.extensions.fields.history import FieldHistory
from code_visualizer.extensions.registry import DomainExtensionRegistry
from code_visualizer.persistence.computation_resources import resolve_computation_resource
from code_visualizer.persistence.resource_store import ResourceStore


@dataclass(frozen=True, slots=True)
class PreparedFieldProbe:
    project_id: str
    revision: int
    model_id: str
    commands: tuple[TypedCommand, ...]


def prepare_probe(
    project: Project,
    registry: DomainExtensionRegistry,
    source_store: ResourceStore,
    target_store: ResourceStore,
    series: ResourceReference,
    sample: int,
    node: int,
) -> PreparedFieldProbe:
    for reference in registry.resource_closure((series,), source_store):
        target_store.import_reference(source_store, reference)
    history = FieldHistory(
        series, lambda ref: resolve_computation_resource(target_store, ref, file_backed=True)
    )
    try:
        selected = history.slice(sample)
        if type(node) is not int or not 0 <= node < history.support.nodes:
            raise ValueError("Select an exact spatial node within the field support")
        model_id, node_id = new_id("field-probe-model"), new_id("field-probe")
        values: tuple[tuple[str, CanonicalValue], ...] = (
            ("name", f"Field sample {sample}, node {node}"),
            ("series", series),
            ("sample", sample),
            ("node", node),
            ("time", selected.position.time),
            ("frame_id", history.support.frame_id),
            ("component_id", history.interpretation.component_id),
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
            "Exact retained field probe",
        )
        return PreparedFieldProbe(
            project.id,
            project.revision,
            model_id,
            (
                *bundle_installation(project.domain_workspace, registry, BUNDLE),
                PutDomainModel(model),
            ),
        )
    finally:
        history.close()
