"""Load the actual saved gas source and its immutable calibrated-input closure."""

from dataclasses import replace
from importlib.resources import files
from pathlib import Path

from code_visualizer.domain.intentional import PropertyValue
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.project_resources import copy_project_resources
from code_visualizer.persistence.resource_store import ResourceStore

INPUT_ROOT = Path(str(files("code_visualizer").joinpath("resources", "hybrid_gas")))


def saved_project():
    return project_from_json((INPUT_ROOT / "project.json").read_text(encoding="utf-8"))


def change(project, node_id, property_name, value):
    models = []
    for model in project.domain_workspace.models:
        nodes = []
        for node in model.nodes:
            if node.id == node_id:
                key = node.concept_id + ":" + property_name
                node = replace(
                    node,
                    properties=(
                        *(p for p in node.properties if p.property_id != key),
                        PropertyValue(key, value),
                    ),
                )
            nodes.append(node)
        models.append(replace(model, nodes=tuple(nodes)))
    return replace(
        project, domain_workspace=replace(project.domain_workspace, models=tuple(models))
    )


def short_project(mode="fixed"):
    project = saved_project()
    for key, value in (
        ("mode", mode),
        ("final_tick", 1000),
        ("sample_ticks", 500),
        ("checkpoint_ticks", 500),
        ("statistics_ticks", 500),
        ("warmup_ticks", 0),
        ("block_ticks", 500),
        ("preview_windows", 100),
    ):
        project = change(project, "gas:policy", key, value)
    return project


def store(path):
    inputs = ResourceStore(INPUT_ROOT)
    registry = builtin_registry()
    copy_project_resources(
        saved_project(),
        inputs,
        None,
        path,
        resolve_closure=lambda refs: registry.resource_closure(refs, inputs),
    )
    return ResourceStore(path)
