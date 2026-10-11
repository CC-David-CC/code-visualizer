"""Selected computation completeness is distinct from global structural integrity."""

from dataclasses import replace

import pytest
from test_computation_backends import _registry, _request, _schema, _source

from code_visualizer.domain.intentional import (
    BundleReference,
    DomainModel,
    IntentionalNode,
    RoleBinding,
    RoleDefinition,
)
from code_visualizer.domain.intentional_validation import validate_domain_workspace
from code_visualizer.generation.computation import prepare_computation
from code_visualizer.generation.transformation import TransformationError
from code_visualizer.persistence.serialization import project_to_data
from code_visualizer.validation import validate_integrity


def _incomplete():
    project = _source()
    schema = replace(_schema("unrelated"), bundle=BundleReference("org.missing.optional", "1"))
    model = DomainModel(
        "unrelated:model",
        schema.id,
        "1",
        ("unrelated:node",),
        (IntentionalNode("unrelated:node", "unrelated:value"),),
    )
    return replace(
        project,
        domain_workspace=replace(
            project.domain_workspace,
            schemas=(*project.domain_workspace.schemas, schema),
            models=(*project.domain_workspace.models, model),
            bundle_references=(schema.bundle,),
        ),
    )


def test_unrelated_incomplete_model_and_missing_bundle_do_not_block_requested_root():
    project = _incomplete()
    before = project_to_data(project)
    assert not validate_integrity(project)
    assert any(issue.incomplete for issue in validate_domain_workspace(project.domain_workspace))
    result = prepare_computation(project, _request(project), _registry())
    assert result.value.nodes[0].property("terminal:amount") == 3
    assert project_to_data(project) == before


def test_incomplete_referenced_model_is_an_actual_dependency():
    project = _incomplete()
    workspace = project.domain_workspace
    source = workspace.schemas[0]
    source = replace(
        source,
        concepts=(
            replace(
                source.concepts[0],
                reference_roles=(
                    RoleDefinition("source:dependency", "Dependency", ("unrelated:value",), 0, 1),
                ),
            ),
        ),
    )
    model = workspace.models[0]
    model = replace(
        model,
        nodes=(
            replace(
                model.nodes[0], references=(RoleBinding("source:dependency", ("unrelated:node",)),)
            ),
        ),
    )
    project = replace(
        project,
        domain_workspace=replace(
            workspace,
            schemas=(source, *workspace.schemas[1:]),
            models=(model, *workspace.models[1:]),
        ),
    )
    assert not validate_integrity(project)
    with pytest.raises(TransformationError) as caught:
        prepare_computation(project, _request(project), _registry())
    assert caught.value.code == "DOMAIN_PROPERTY_REQUIRED"


def test_unrelated_structural_corruption_still_blocks():
    project = _incomplete()
    workspace = project.domain_workspace
    invalid = replace(
        workspace.models[-1], nodes=(*workspace.models[-1].nodes, workspace.models[-1].nodes[0])
    )
    project = replace(
        project, domain_workspace=replace(workspace, models=(*workspace.models[:-1], invalid))
    )
    assert validate_integrity(project)
    with pytest.raises(TransformationError):
        prepare_computation(project, _request(project), _registry())
