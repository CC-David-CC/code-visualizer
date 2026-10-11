"""Authored source fixtures; saved field computations never invoke these builders."""

from __future__ import annotations

from code_visualizer.domain.intentional import (
    BundleReference,
    DomainModel,
    DomainWorkspace,
    IntentionalNode,
    PropertyValue,
    RoleBinding,
)
from code_visualizer.domain.project import Project
from code_visualizer.domain.values import CanonicalValue
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.diffusion.domain import BUNDLE, SCHEMA_ID, identity, quantity
from code_visualizer.extensions.fields.domain import SCHEMA_ID as FIELD_SCHEMA
from code_visualizer.extensions.fields.domain import identity as field_id
from code_visualizer.extensions.foundations.space import ALGEBRA_SCHEMA_ID
from code_visualizer.extensions.foundations.space import identity as space_id


def _node(
    node_id: str,
    concept: str,
    properties: tuple[tuple[str, CanonicalValue], ...],
    children: tuple[tuple[str, tuple[str, ...]], ...] = (),
    references: tuple[tuple[str, tuple[str, ...]], ...] = (),
) -> IntentionalNode:
    return IntentionalNode(
        node_id,
        concept,
        tuple(PropertyValue(concept + ":" + key, value) for key, value in properties),
        tuple(RoleBinding(concept + ":" + key, values) for key, values in children),
        tuple(RoleBinding(concept + ":" + key, values) for key, values in references),
    )


def diffusion_project(
    *,
    nodes: int = 65,
    steps: int = 2048,
    sample_every: int = 16,
    checkpoint_every: int = 512,
    chunk_rows: int = 256,
    preview_every: int = 16,
) -> Project:
    space = DomainModel(
        "diffusion:space-model",
        ALGEBRA_SCHEMA_ID,
        "2",
        ("diffusion:space", "diffusion:frame"),
        (
            _node(
                "diffusion:space",
                space_id("Space"),
                (("name", "Rod space"), ("dimension", 1)),
                (("axes", ("diffusion:x",)),),
            ),
            _node("diffusion:x", space_id("Axis"), (("name", "x"), ("ordinal", 0))),
            _node(
                "diffusion:frame",
                space_id("Frame"),
                (("name", "Laboratory frame"),),
                references=(("space", ("diffusion:space",)),),
            ),
        ),
        "One-dimensional laboratory support",
    )
    field = DomainModel(
        "diffusion:field-model",
        FIELD_SCHEMA,
        "1",
        ("diffusion:field", "diffusion:grid"),
        (
            _node(
                "diffusion:grid",
                field_id("UniformGrid"),
                (
                    ("name", "Uniform rod grid"),
                    ("length", quantity(1.0, "meter")),
                    ("nodes", nodes),
                ),
                references=(("frame", ("diffusion:frame",)), ("axis", ("diffusion:x",))),
            ),
            _node(
                "diffusion:field",
                field_id("Field"),
                (
                    ("name", "Temperature excess"),
                    ("scale", quantity(1.0, "kelvin")),
                    ("quantity_kind", "interval"),
                ),
                references=(("grid", ("diffusion:grid",)),),
            ),
        ),
        "Temperature interval field",
    )
    model = DomainModel(
        "diffusion:experiment",
        SCHEMA_ID,
        "1",
        ("diffusion:problem",),
        (
            _node(
                "diffusion:problem",
                identity("Problem"),
                (
                    ("name", "Diffusion in a uniform rod"),
                    ("diffusivity", quantity(0.1, "square_meter_per_second")),
                ),
                (
                    ("initial", ("diffusion:initial",)),
                    ("boundary", ("diffusion:boundary",)),
                    ("policy", ("diffusion:policy",)),
                ),
                (("field", ("diffusion:field",)),),
            ),
            _node(
                "diffusion:initial",
                identity("SineInitial"),
                (
                    ("name", "Sine initial temperature excess"),
                    ("amplitude", quantity(10.0, "kelvin")),
                ),
            ),
            _node(
                "diffusion:boundary", identity("ZeroBoundary"), (("name", "Zero endpoint excess"),)
            ),
            _node(
                "diffusion:policy",
                identity("TimePolicy"),
                (
                    ("name", "Fixed accepted steps and output schedule"),
                    ("final_time", quantity(1.0)),
                    ("steps", steps),
                    ("sample_every", sample_every),
                    ("checkpoint_every", checkpoint_every),
                    ("preview_every", preview_every),
                    ("chunk_rows", chunk_rows),
                ),
            ),
        ),
        "Diffusion experiment",
    )
    closure = builtin_registry().bundle_closure(BUNDLE)
    return Project(
        "physical:diffusion-field",
        "Diffusion: time, fields and checkpoints",
        (),
        description="One metre, D=0.1 m²/s, sine amplitude 10 K interval, horizon 1 s. "
        "Freeze and run; inspect accepted history, cancel, "
        "and explicitly resume a retained checkpoint. "
        "Analytic final midpoint: 3.7270783885343794 K interval.",
        domain_workspace=DomainWorkspace(
            tuple(schema for bundle in closure for schema in bundle.schemas),
            (
                model,
                field,
                space,
                *(reference for bundle in closure for reference in bundle.reference_models),
            ),
            tuple(BundleReference(bundle.id, bundle.version) for bundle in closure),
        ),
    )
