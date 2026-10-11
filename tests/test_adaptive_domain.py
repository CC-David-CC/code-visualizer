"""The P7 physical fragment uses the existing canonical authoring and unit boundary."""

from dataclasses import replace
from itertools import pairwise

import numpy as np
import pytest
from fixtures.adaptive_reference import pulse_average

from code_visualizer.application.adaptive_examples import adaptive_diffusion_project
from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.domain_commands import SetDomainProperty
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.domain.identifiers import ContractKind
from code_visualizer.domain.intentional import PropertyValue
from code_visualizer.domain.intentional_validation import validate_domain_workspace
from code_visualizer.extensions.adaptive_diffusion.domain import BUNDLE, identity
from code_visualizer.extensions.adaptive_diffusion.problem import AdaptiveError, derive_problem
from code_visualizer.extensions.adaptive_fields.mesh import Mesh
from code_visualizer.extensions.adaptive_fields.units import BUNDLE as UNITS
from code_visualizer.extensions.adaptive_fields.units import quantity
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.publication import publication_manifest
from code_visualizer.extensions.registry import (
    DomainExtensionRegistry,
    validate_extension_requirements,
)
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.serialization import normalized_project_json
from code_visualizer.sdk.client import CodeVisualizerClient


def change(project, node_id, name, value):
    models = []
    for model in project.domain_workspace.models:
        nodes = []
        for node in model.nodes:
            if node.id == node_id:
                key = node.concept_id + ":" + name
                node = replace(
                    node,
                    properties=(
                        *(item for item in node.properties if item.property_id != key),
                        PropertyValue(key, value),
                    ),
                )
            nodes.append(node)
        models.append(replace(model, nodes=tuple(nodes)))
    return replace(
        project, domain_workspace=replace(project.domain_workspace, models=tuple(models))
    )


def problem(project=None):
    project = project or adaptive_diffusion_project()
    return derive_problem(project, project.domain_workspace.models[0])


def test_canonical_physical_fragment_and_public_unit_closure():
    project = adaptive_diffusion_project()
    assert validate_domain_workspace(project.domain_workspace) == ()
    assert validate_extension_requirements(project, builtin_registry()) == ()
    assert not project.program_model.functions
    registry = builtin_registry()
    manifest = publication_manifest(registry, BUNDLE.id, BUNDLE.version)
    refs = {(item.kind, item.id, item.version) for item in manifest.references}
    assert (ContractKind.UNIT, UNITS.id + ":kilogram_per_cubic_meter", "1") in refs
    for bundle in registry.bundle_closure(BUNDLE):
        publication_manifest(registry, bundle.id, bundle.version)
    source = problem(project)
    mesh = Mesh.uniform(source.region_id, 32, source.length)
    reference = [pulse_average(a, b, 0) for a, b in pairwise(mesh.faces)]
    np.testing.assert_allclose(source.initial_values(mesh), reference, rtol=0, atol=3e-15)
    assert source.policy.time(source.policy.final_tick) == 20


def test_conversion_uses_shared_pint_boundary_and_same_scientific_meaning():
    original = adaptive_diffusion_project()
    alternate = change(original, "adaptive:region", "length", quantity(100, "centimeter"))
    alternate = change(alternate, "adaptive:region", "area", quantity(10000, "square_centimeter"))
    alternate = change(
        alternate, "adaptive:field", "scale", quantity(0.001, "gram_per_cubic_centimeter")
    )
    alternate = change(alternate, "adaptive:policy", "final_time", quantity(20000, "millisecond"))
    alternate = change(
        alternate,
        "adaptive:problem",
        "diffusivity",
        quantity(1, "square_millimeter_per_millisecond"),
    )
    p, q = problem(original), problem(alternate)
    assert (q.length, q.area, q.scale, q.diffusivity) == pytest.approx(
        (p.length, p.area, p.scale, p.diffusivity), rel=1e-14
    )
    assert q.policy == p.policy


@pytest.mark.parametrize(
    ("node", "name", "value", "code"),
    (
        ("adaptive:region", "length", quantity(1, "second"), "UNIT_DIMENSION_MISMATCH"),
        ("adaptive:region", "area", quantity(1, "meter"), "UNIT_DIMENSION_MISMATCH"),
        ("adaptive:space", "dimension", 2, "ADAPTIVE_FRAME"),
        ("adaptive:x", "ordinal", 1, "ADAPTIVE_FRAME"),
        ("adaptive:problem", "boundary", "reflecting", "ADAPTIVE_VALIDITY"),
        ("adaptive:policy", "coarsen_threshold", 0.9, "ADAPTIVE_POLICY"),
        ("adaptive:policy", "maximum_cells", 15, "ADAPTIVE_POLICY"),
        ("adaptive:policy", "sample_interval", quantity(0.10001), "ADAPTIVE_SCHEDULE"),
        ("adaptive:policy", "sample_interval", quantity(0.0125), "ADAPTIVE_OUTPUT_LIMIT"),
        (
            "adaptive:problem",
            "diffusivity",
            quantity(0, "square_meter_per_second"),
            "ADAPTIVE_RANGE",
        ),
        ("adaptive:initial", "mean", quantity(0, "kilogram_per_cubic_meter"), "ADAPTIVE_INITIAL"),
    ),
)
def test_invalid_input_reports_actual_contract_and_origin(node, name, value, code):
    assert problem().diffusivity == 0.001  # A real positive dependency control.
    project = change(adaptive_diffusion_project(), node, name, value)
    with pytest.raises(AdaptiveError) as caught:
        problem(project)
    assert caught.value.code == code
    expected = "adaptive:region" if code == "ADAPTIVE_FRAME" else node
    assert caught.value.object_id == expected


def test_save_reload_edit_undo_redo_keep_the_same_intentions():
    original = adaptive_diffusion_project()
    serialized = normalized_project_json(original)
    loaded = project_from_json(serialized)
    assert normalized_project_json(loaded) == serialized
    authority = ProjectAuthority(loaded)
    client = CodeVisualizerClient(authority, actor_id="p7-author")
    ids = {node.id for model in loaded.domain_workspace.models for node in model.nodes}
    assert isinstance(
        client.submit(
            SetDomainProperty(
                "adaptive:experiment",
                "adaptive:policy",
                identity("Policy", "spatial_atol"),
                quantity(0.0005, "kilogram_per_cubic_meter"),
            )
        ),
        CommandAccepted,
    )
    assert problem(authority.snapshot()).policy.spatial_atol == 0.0005
    assert isinstance(client.undo(), CommandAccepted)
    assert problem(authority.snapshot()).policy.spatial_atol == 0.004
    assert isinstance(client.redo(), CommandAccepted)
    assert problem(authority.snapshot()).policy.spatial_atol == 0.0005
    assert {
        node.id for model in authority.snapshot().domain_workspace.models for node in model.nodes
    } == ids
    assert (
        problem(
            project_from_json(normalized_project_json(authority.snapshot()))
        ).policy.spatial_atol
        == 0.0005
    )


def test_missing_implementation_preserves_all_source_data_and_reports_unavailable():
    source = normalized_project_json(adaptive_diffusion_project())
    loaded = project_from_json(source)
    issues = validate_extension_requirements(loaded, DomainExtensionRegistry())
    assert any(
        issue.code == "DOMAIN_EXTENSION_MISSING" and issue.object_id == BUNDLE.id
        for issue in issues
    )
    assert normalized_project_json(loaded) == source
