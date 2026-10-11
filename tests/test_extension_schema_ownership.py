"""A registered schema cannot silently lose its complete bundle behavior."""

from dataclasses import replace

import pytest

from code_visualizer.domain.intentional import (
    BundleReference,
    DomainIssue,
    DomainModel,
    DomainSchema,
    DomainWorkspace,
)
from code_visualizer.domain.project import Project
from code_visualizer.extensions.registry import (
    DomainExtensionBundle,
    DomainExtensionRegistry,
    validate_extension_requirements,
)


@pytest.mark.parametrize("owner", [None, BundleReference("other", "1")])
def test_bundle_rejects_schema_without_its_exact_explicit_owner(owner):
    schema = DomainSchema("schema", "example.schema", "1", bundle=owner)
    registry = DomainExtensionRegistry()
    bundle = DomainExtensionBundle("extension", "1", schemas=(schema,))
    with pytest.raises(ValueError, match="explicitly name its owning bundle"):
        registry.register(bundle)
    assert registry.bundles() == ()
    assert registry.get("extension", "1") is None


def test_owned_schema_runs_its_validator_while_unbundled_user_schema_remains_legal():
    reference = BundleReference("extension", "1")
    schema = DomainSchema("schema", "example.schema", "1", bundle=reference)
    model = DomainModel("model", schema.id, schema.version)
    issue = DomainIssue("REVIEW", "Review the instance", model.id, incomplete=True)
    registry = DomainExtensionRegistry(
        (
            DomainExtensionBundle(
                reference.id,
                reference.version,
                schemas=(schema,),
                validators=(lambda _project, _model: (issue,),),
            ),
        )
    )
    project = Project(
        "project", "Domain", (), domain_workspace=DomainWorkspace((schema,), (model,))
    )
    assert validate_extension_requirements(project, registry) == (issue,)
    independent = replace(
        project,
        domain_workspace=replace(
            project.domain_workspace,
            schemas=(replace(schema, bundle=None),),
        ),
    )
    assert validate_extension_requirements(independent, registry) == ()
