"""Canonical integrity and compilation protect the same inert slots as decoding."""

from dataclasses import replace

import pytest

from code_visualizer.application.authored_examples import authored_traffic_light_project
from code_visualizer.domain.language import QueryLiteral, QueryProperty
from code_visualizer.domain.language_structure import validate_language_slots
from code_visualizer.domain.language_validation import validate_authored_language
from code_visualizer.extensions.builtin import intentional_bundle, program_bundle
from code_visualizer.extensions.languages import resolve_domain_languages
from code_visualizer.extensions.registry import DomainExtensionRegistry
from code_visualizer.validation import validate_integrity


@pytest.mark.parametrize(
    "change",
    [
        lambda language: replace(language, syntax_version=True),
        lambda language: replace(language, title={"code": "arbitrary callback"}),
        lambda language: replace(
            language,
            validators=(
                replace(
                    language.validators[0],
                    predicate=QueryProperty("bad:property", "not a query", "name"),
                ),
            ),
        ),
        lambda language: replace(
            language,
            validators=(
                replace(
                    language.validators[0],
                    predicate=QueryLiteral("bad:literal", {"callback": "os.system"}),
                ),
            ),
        ),
        lambda language: replace(language, transformations=[language.transformations[0]]),
    ],
)
def test_direct_project_values_have_explicit_integrity_and_compilation_diagnostics(change):
    project = authored_traffic_light_project()
    language = change(project.domain_workspace.language_definitions[0])
    malformed = replace(
        project,
        domain_workspace=replace(project.domain_workspace, language_definitions=(language,)),
    )
    issues = validate_integrity(malformed)
    assert "DOMAIN_LANGUAGE_STRUCTURE" in {issue.code for issue in issues}
    assert "DOMAIN_LANGUAGE_STRUCTURE" in {
        issue.code
        for issue in validate_authored_language(language, project.domain_workspace.schemas[0])
    }
    resolved = resolve_domain_languages(
        malformed, DomainExtensionRegistry((program_bundle(), intentional_bundle()))
    )
    assert "DOMAIN_LANGUAGE_STRUCTURE" in {issue.code for issue in resolved.resolution_issues}


def test_slot_validation_rejects_oversized_direct_values_before_authority_admission():
    language = authored_traffic_light_project().domain_workspace.language_definitions[0]
    with pytest.raises(ValueError, match="text limits"):
        validate_language_slots(replace(language, title="x" * 1_000_001))
    with pytest.raises(ValueError, match="structural limits"):
        validate_language_slots(replace(language, validators=(language.validators[0],) * 100_001))
