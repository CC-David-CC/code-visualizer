"""Construct an explicit authored axial definition; no resources or execution are created."""

from dataclasses import replace

from code_visualizer.domain.intentional import (
    DomainModel,
    IntentionalNode,
    PropertyValue,
    RoleBinding,
)
from code_visualizer.domain.project import Project
from code_visualizer.domain.values import CanonicalValue, ResourceReference
from code_visualizer.extensions.axial.domain import BUNDLE, SCHEMA_ID, axial_schema, quantity
from code_visualizer.extensions.cad.domain import SCHEMA_ID as CAD_SCHEMA
from code_visualizer.extensions.cad.domain import consumer_model


def _node(
    prefix: str,
    node_id: str,
    concept: str,
    properties: tuple[tuple[str, CanonicalValue], ...] = (),
    children: tuple[tuple[str, tuple[str, ...]], ...] = (),
    references: tuple[tuple[str, tuple[str, ...]], ...] = (),
) -> IntentionalNode:
    concept_id = prefix + concept
    return IntentionalNode(
        node_id,
        concept_id,
        tuple(PropertyValue(concept_id + ":" + key, value) for key, value in properties),
        tuple(RoleBinding(concept_id + ":" + key, values) for key, values in children),
        tuple(RoleBinding(concept_id + ":" + key, values) for key, values in references),
    )


def create_models(
    project: Project,
    resource: ResourceReference,
    *,
    nodes: int = 9,
    young_modulus: float = 2e11,
    force: float = 1000,
    frame_id: str,
    namespace: str,
    axis: str = "x",
) -> tuple[DomainModel, DomainModel]:
    prefix = BUNDLE.id + ":"
    support_region = consumer_model(
        "unused",
        namespace + ":support-region",
        "RegionSelection",
        resource,
        frame_id=frame_id,
        axis=axis,
        side="min",
        assignment="support",
        tolerance=quantity(1e-9),
    )
    load_region = consumer_model(
        "unused",
        namespace + ":load-region",
        "RegionSelection",
        resource,
        frame_id=frame_id,
        axis=axis,
        side="max",
        assignment="load",
        tolerance=quantity(1e-9),
    )
    regions = DomainModel(
        namespace + ":regions",
        CAD_SCHEMA,
        "1",
        (*support_region.roots, *load_region.roots),
        (*support_region.nodes, *load_region.nodes),
        "Fixed and loaded end predicates",
    )
    unit_roots = tuple(
        root
        for model in project.domain_workspace.models
        if model.id.endswith(":catalog")
        for root in model.roots
    )
    contents: tuple[IntentionalNode, ...] = (
        _node(
            prefix,
            namespace + ":problem",
            "AxialProblem",
            (("nodes", nodes),),
            (
                ("material", (namespace + ":material",)),
                ("geometry", (namespace + ":geometry",)),
                ("support", (namespace + ":support",)),
                ("load", (namespace + ":load",)),
            ),
            (("unit_definitions", unit_roots),),
        ),
        _node(
            prefix,
            namespace + ":material",
            "Material",
            (("young_modulus", quantity(young_modulus, "pascal")),),
        ),
        _node(
            prefix,
            namespace + ":geometry",
            "GeometryIdealization",
            (("geometry", resource), ("frame_id", frame_id), ("axis", axis)),
        ),
        _node(
            prefix,
            namespace + ":support",
            "AxialSupport",
            references=(("region", (namespace + ":support-region",)),),
        ),
        _node(
            prefix,
            namespace + ":load",
            "AxialLoad",
            (("force", quantity(force, "newton")), ("frame_id", frame_id), ("axis", axis)),
            references=(("region", (namespace + ":load-region",)),),
        ),
    )
    schema = axial_schema()
    contents = tuple(
        replace(
            node,
            properties=(
                *node.properties,
                *(
                    PropertyValue(prop.id, prop.default)
                    for concept in schema.concepts
                    if concept.id == node.concept_id
                    for prop in concept.properties
                    if prop.default is not None and node.property(prop.id) is None
                ),
            ),
        )
        for node in contents
    )
    model = DomainModel(
        namespace + ":experiment",
        SCHEMA_ID,
        "1",
        (namespace + ":problem",),
        contents,
        "Solid-prism axial analysis",
    )
    return model, regions
