"""Resolve inert project-authored languages through the one registered language engine.

This is a disposable application composition step, shared by reads and builds. It
does not register project-selected Python code or change ownership of any schema.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from code_visualizer.domain.intentional import DomainIssue, DomainModel, DomainSchema
from code_visualizer.domain.language import AuthoredDomainLanguage
from code_visualizer.domain.project import Project
from code_visualizer.extensions.registry import (
    DomainExtensionRegistry,
    SchemaLanguageContribution,
)


def _validator(
    language: AuthoredDomainLanguage, schema: DomainSchema, schemas: tuple[DomainSchema, ...]
) -> Callable[[Project, DomainModel], tuple[DomainIssue, ...]]:
    from code_visualizer.generation.language import validate_authored_model

    def validate(_project: Project, model: DomainModel) -> tuple[DomainIssue, ...]:
        return validate_authored_model(
            language, schema, model, schemas=schemas, workspace=_project.domain_workspace
        )

    return validate


def resolve_domain_languages(
    project: Project, host_registry: DomainExtensionRegistry | None = None
) -> DomainExtensionRegistry:
    """Compose exact schema/version contributions from one immutable snapshot.

    Re-resolving an already resolved registry starts from its host registrations,
    so editing or deleting a language cannot retain stale compiled definitions.
    Unsupported or invalid definitions remain canonical data with diagnostics.
    """

    if host_registry is None:
        from code_visualizer.extensions.builtin import builtin_registry

        host_registry = builtin_registry()
    host = host_registry.host_registry
    languages = project.domain_workspace.language_definitions
    if not languages:
        return host

    from code_visualizer.domain.language_validation import (
        language_structure_issues,
        validate_authored_language,
    )
    from code_visualizer.generation.language import compile_authored_transformation

    issues: list[DomainIssue] = []
    contributions: list[SchemaLanguageContribution] = []
    structured: list[AuthoredDomainLanguage] = []
    for language in languages:
        structure_findings = language_structure_issues(language)
        if structure_findings:
            issues.extend(structure_findings)
        else:
            structured.append(language)
    for language in sorted(structured, key=lambda item: item.id):
        if language.syntax_version not in {1, 2}:
            issues.append(
                DomainIssue(
                    "DOMAIN_LANGUAGE_ENGINE_UNAVAILABLE",
                    f"Language syntax version {language.syntax_version!r} is unavailable; "
                    "data is preserved",
                    language.id,
                    incomplete=True,
                )
            )
            continue
        schema = project.domain_workspace.schema(language.schema_id)
        if schema is None or schema.version != language.schema_version:
            issues.append(
                DomainIssue(
                    "DOMAIN_LANGUAGE_SCHEMA",
                    "Authored language requires its exact schema identity and version",
                    language.id,
                    incomplete=True,
                )
            )
            continue
        schemas = project.domain_workspace.schemas
        findings = validate_authored_language(language, schema, schemas=schemas)
        issues.extend(findings)
        if findings:
            # Definitions are independently editable. An unfinished transform
            # cannot remove a valid notation needed to keep authoring its data.
            empty = replace(language, notations=(), validators=(), transformations=())
            language = replace(
                language,
                notations=tuple(
                    item
                    for item in language.notations
                    if not validate_authored_language(
                        replace(empty, notations=(item,)), schema, schemas=schemas
                    )
                ),
                validators=tuple(
                    item
                    for item in language.validators
                    if not validate_authored_language(
                        replace(empty, validators=(item,)), schema, schemas=schemas
                    )
                ),
                transformations=tuple(
                    item
                    for item in language.transformations
                    if not validate_authored_language(
                        replace(empty, transformations=(item,)), schema, schemas=schemas
                    )
                ),
            )
        contributions.append(
            SchemaLanguageContribution(
                language.id,
                schema.id,
                schema.version,
                validators=(_validator(language, schema, schemas),) if language.validators else (),
                notations=tuple(replace(item, schema_id=schema.id) for item in language.notations),
                transformations=tuple(
                    compile_authored_transformation(language, schema, item, schemas=schemas)
                    for item in language.transformations
                ),
            )
        )
    try:
        return DomainExtensionRegistry(
            host.bundles(),
            languages=tuple(contributions),
            resolution_issues=tuple(issues),
            host_registry=host,
        )
    except ValueError as exc:
        # A conflict rejects the composed set, rather than picking the first
        # authored definition by tuple or import order. Host behavior remains.
        return DomainExtensionRegistry(
            host.bundles(),
            host_registry=host,
            resolution_issues=(
                *issues,
                DomainIssue(
                    "DOMAIN_LANGUAGE_CONTRIBUTION_CONFLICT",
                    str(exc),
                    project.id,
                    incomplete=True,
                ),
            ),
        )
