"""One canonical gas definition, ordinary authority and published dependency closure."""

import pytest
from fixtures.gas_project import change, saved_project

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.domain_commands import SetDomainProperty
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.domain.intentional_validation import validate_domain_workspace
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.hybrid_gas.domain import BUNDLE, identity
from code_visualizer.extensions.hybrid_gas.problem import GasError, derive_problem
from code_visualizer.extensions.hybrid_gas.units import quantity
from code_visualizer.extensions.publication import publication_manifest
from code_visualizer.extensions.registry import validate_extension_requirements
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.serialization import normalized_project_json
from code_visualizer.sdk.client import CodeVisualizerClient


def test_saved_gas_is_an_independent_domain_with_complete_public_contracts():
    project, registry = saved_project(), builtin_registry()
    assert not validate_domain_workspace(project.domain_workspace)
    assert not validate_extension_requirements(project, registry)
    assert not project.program_model.functions
    for bundle in registry.bundle_closure(BUNDLE):
        publication_manifest(registry, bundle.id, bundle.version)
    encoded = normalized_project_json(project)
    assert normalized_project_json(project_from_json(encoded)) == encoded
    p = derive_problem(project, project.domain_workspace.models[0])
    assert p.grid.cells == 64 and p.slab.cells == 16
    assert p.policy.final_tick == 340000 and p.policy.mode == "fixed"
    assert (
        p.calibration.content_hash
        == "3a55f616623de0cb48d3e4deff901f9560d54ee348db0a0b42b8b091243febce"
    )


def test_unit_normalization_and_ordinary_policy_edit_undo_redo():
    original = saved_project()
    project = change(original, "gas:channel", "height", quantity(0.2, "centimeter"))
    assert derive_problem(project, project.domain_workspace.models[0]).grid.length == 0.002
    authority = ProjectAuthority(project)
    client = CodeVisualizerClient(authority, actor_id="p7-gas-author")
    ids = {n.id for m in project.domain_workspace.models for n in m.nodes}

    def value():
        current = authority.snapshot()
        return derive_problem(current, current.domain_workspace.models[0]).policy.window_ticks

    assert isinstance(
        client.submit(
            SetDomainProperty("gas:experiment", "gas:policy", identity("Policy", "window_ticks"), 1)
        ),
        CommandAccepted,
    )
    assert value() == 1
    assert isinstance(client.undo(), CommandAccepted) and value() == 2
    assert isinstance(client.redo(), CommandAccepted) and value() == 1
    assert {n.id for m in authority.snapshot().domain_workspace.models for n in m.nodes} == ids


@pytest.mark.parametrize(
    "node,name,value,code",
    [
        ("gas:gas", "interpretation", "equilibrium_fluctuations", "GAS_MODEL_UNSUPPORTED"),
        ("gas:slab", "lower", quantity(0.00071, "meter"), "GAS_COVERAGE"),
        ("gas:policy", "window_ticks", 3, "GAS_OUTPUT_POLICY"),
        ("gas:policy", "cells", 65, "GAS_PROFILE_SUPPORT"),
        ("gas:y", "ordinal", 2, "GAS_FRAME"),
        ("gas:policy", "maximum_particles", 1000, "GAS_PARTICLE_BUDGET"),
    ],
)
def test_malformed_or_unsupported_meaning_is_explicit(node, name, value, code):
    project = change(saved_project(), node, name, value)
    with pytest.raises(GasError) as caught:
        derive_problem(project, project.domain_workspace.models[0])
    assert caught.value.code == code
