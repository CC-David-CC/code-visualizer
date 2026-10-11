"""Prepare a retained-channel consumer off the GUI thread, then use one authority."""

from dataclasses import dataclass

from code_visualizer.application.commands import TypedCommand
from code_visualizer.application.domain_commands import PutDomainModel
from code_visualizer.application.domain_installation import bundle_installation
from code_visualizer.domain.common import new_id
from code_visualizer.domain.intentional import DomainModel, IntentionalNode, PropertyValue
from code_visualizer.domain.project import Project
from code_visualizer.domain.values import CanonicalValue, ResourceReference
from code_visualizer.extensions.channels.domain import BUNDLE, SCHEMA_ID, identity
from code_visualizer.extensions.channels.history import ChannelHistory
from code_visualizer.extensions.registry import DomainExtensionRegistry
from code_visualizer.persistence.computation_resources import resolve_computation_resource
from code_visualizer.persistence.resource_store import ResourceStore


@dataclass(frozen=True, slots=True)
class PreparedChannelProbe:
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
    channel_id: str,
) -> PreparedChannelProbe:
    for reference in registry.resource_closure((series,), source_store):
        target_store.import_reference(source_store, reference)
    history = ChannelHistory(
        series, lambda ref: resolve_computation_resource(target_store, ref, file_backed=True)
    )
    try:
        selected = history.slice(sample)
        channel = next((c for c in history.interpretation.channels if c.id == channel_id), None)
        if channel is None:
            raise ValueError("Select a channel from this retained interpretation")
        model_id, node_id = new_id("channel-probe-model"), new_id("channel-probe")
        values: tuple[tuple[str, CanonicalValue], ...] = (
            ("name", f"{channel.name} at sample {sample}"),
            ("series", series),
            ("sample", sample),
            ("channel_id", channel.id),
            ("support_id", channel.support_id),
            ("quantity_kind", channel.quantity_kind.value),
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
            "Exact retained channel probe",
        )
        return PreparedChannelProbe(
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
