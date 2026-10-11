"""Read services for domain providers, notations, and available transformation plans."""

from __future__ import annotations

from dataclasses import dataclass, replace

from code_visualizer.application.notation_canvas import compile_notation_canvas
from code_visualizer.application.notations import (
    NotationProjection,
    NotationTreeNode,
    compile_notation,
    fallback_notations,
)
from code_visualizer.domain.computation import BackendDefinition
from code_visualizer.domain.intentional import DomainIssue, DomainSchema, DomainWorkspace
from code_visualizer.domain.intentional_validation import validate_domain_workspace
from code_visualizer.domain.notation import NotationDefinition
from code_visualizer.domain.project import Project
from code_visualizer.domain.semantic import SemanticProjection, SemanticRelation
from code_visualizer.domain.transformation import (
    Representation,
    TransformationDefinition,
)
from code_visualizer.domain.values import UnitReference
from code_visualizer.extensions.languages import resolve_domain_languages
from code_visualizer.extensions.registry import (
    DomainExtensionRegistry,
    DomainParticipant,
    RuntimeDecoration,
    validate_extension_requirements,
)
from code_visualizer.generation.transformation import TransformationError, plan_transformations


def catalog_unit_choices(project: Project) -> tuple[tuple[str, UnitReference], ...]:
    """Read declared unit labels; invalid vocabularies remain in workbench diagnostics."""
    from code_visualizer.extensions.foundations.units import UnitCatalog

    try:
        catalog = UnitCatalog.from_models(project.domain_workspace.models)
    except (ValueError, OverflowError):
        return ()
    return tuple(
        (f"{item.symbol} - {item.name}", item.reference)
        for item in sorted(catalog.units, key=lambda item: (item.name, item.reference.id))
    )


@dataclass(frozen=True, slots=True)
class BundleAvailability:
    id: str
    version: str
    available: bool


@dataclass(frozen=True, slots=True)
class GeneratorDescriptor:
    id: str
    title: str
    source: Representation
    target: Representation


@dataclass(frozen=True, slots=True)
class ComputationRoute:
    model_id: str
    backend_id: str
    backend_version: str
    transformations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WorkbenchSnapshot:
    project_id: str
    revision: int
    domains: tuple[DomainParticipant, ...]
    workspace: DomainWorkspace
    available_schemas: tuple[DomainSchema, ...]
    bundles: tuple[BundleAvailability, ...]
    transformations: tuple[TransformationDefinition, ...]
    generators: tuple[GeneratorDescriptor, ...]
    diagnostics: tuple[DomainIssue, ...]
    backends: tuple[BackendDefinition, ...] = ()
    computation_routes: tuple[ComputationRoute, ...] = ()


def workbench_snapshot(project: Project, registry: DomainExtensionRegistry) -> WorkbenchSnapshot:
    registry = resolve_domain_languages(project, registry)
    required = {(item.id, item.version) for item in project.domain_workspace.bundle_references}
    required.update(
        (schema.bundle.id, schema.bundle.version)
        for schema in project.domain_workspace.schemas
        if schema.bundle is not None
    )
    installed = {(item.id, item.version) for item in registry.bundles()}
    issues = [
        *validate_domain_workspace(project.domain_workspace),
        *validate_extension_requirements(project, registry),
    ]
    routes: list[ComputationRoute] = []
    for model in project.domain_workspace.models:
        schema = project.domain_workspace.schema(model.schema_id)
        if schema is None:
            continue
        for backend in registry.backends():
            try:
                plan = plan_transformations(
                    registry.transformations(),
                    Representation(schema.namespace, schema.version),
                    backend.definition.input_representation,
                    source_schema=(schema.id, schema.version),
                    target_schema=backend.definition.schema,
                )
                routes.append(
                    ComputationRoute(
                        model.id,
                        backend.definition.id,
                        backend.definition.version,
                        tuple(item.definition.key for item in plan),
                    )
                )
            except TransformationError as exc:
                if exc.code != "TRANSFORM_NO_PATH":
                    issue = DomainIssue(exc.code, str(exc), model.id, incomplete=True)
                    if issue not in issues:
                        issues.append(issue)
        if model.nodes and not any(route.model_id == model.id for route in routes):
            issues.append(
                DomainIssue(
                    "COMPUTATION_NO_BACKEND",
                    "No registered computation route is available for this domain; "
                    "its data remains editable and usable as input",
                    model.id,
                    incomplete=True,
                )
            )
    return WorkbenchSnapshot(
        project.id,
        project.revision,
        registry.domains(project),
        project.domain_workspace,
        tuple(schema for bundle in registry.bundles() for schema in bundle.schemas),
        tuple(
            BundleAvailability(key[0], key[1], key in installed)
            for key in sorted(required | installed)
        ),
        tuple(item.definition for item in registry.transformations()),
        tuple(
            GeneratorDescriptor(item.id, item.title, item.source, item.target)
            for item in registry.generators()
        ),
        tuple(issues),
        tuple(item.definition for item in registry.backends()),
        tuple(routes),
    )


def available_notations(
    project: Project,
    model_id: str,
    registry: DomainExtensionRegistry,
) -> tuple[NotationDefinition, ...]:
    registry = resolve_domain_languages(project, registry)
    model = project.domain_workspace.model(model_id)
    if model is None:
        raise ValueError(f"Unknown domain model {model_id!r}")
    schema = project.domain_workspace.schema(model.schema_id)
    if schema is None:
        raise ValueError(f"Missing schema {model.schema_id!r}")
    registered = registry.notations_for(schema.id, schema.version)
    fallback = fallback_notations(schema)
    by_id = {item.id: item for item in (*registered, *fallback)}
    if len(by_id) != len(registered) + len(fallback):
        raise ValueError("Registered and generic notations have ambiguous identities")
    return tuple(sorted(by_id.values(), key=lambda item: item.id))


def project_notation(
    project: Project,
    model_id: str,
    notation_id: str,
    registry: DomainExtensionRegistry,
    *,
    active_node_ids: tuple[str, ...] = (),
    runtime_revision: int | None = None,
    semantic_relations: tuple[SemanticRelation, ...] = (),
) -> NotationProjection:
    definition = next(
        (
            item
            for item in available_notations(project, model_id, registry)
            if item.id == notation_id
        ),
        None,
    )
    if definition is None:
        raise ValueError(f"Unknown notation {notation_id!r}")
    model = project.domain_workspace.model(model_id)
    assert model is not None
    schema = project.domain_workspace.schema(model.schema_id)
    assert schema is not None
    compiled = compile_notation(
        project.id,
        project.revision,
        schema,
        model,
        definition,
        active_node_ids=active_node_ids,
        runtime_revision=runtime_revision,
        workspace=project.domain_workspace,
    )
    if definition.body is not None:
        compiled = replace(
            compiled,
            canvas=compile_notation_canvas(
                project,
                model_id,
                definition,
                relations=semantic_relations,
                active_ids=active_node_ids,
                runtime_revision=runtime_revision,
            ),
        )
    decorations = registry.runtime_decorations(active_node_ids) if active_node_ids else ()

    def badges(identities: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(item.label for item in decorations if item.semantic_id in identities)

    def decorate_tree(node: NotationTreeNode) -> NotationTreeNode:
        return replace(
            node,
            badges=badges((node.node_id,)),
            children=tuple(decorate_tree(child) for child in node.children),
        )

    return replace(
        compiled,
        graph=decorate_semantic_projection(compiled.graph, decorations),
        rows=tuple(
            replace(row, badges=badges((row.node_id, *(cell.semantic_id for cell in row.cells))))
            for row in compiled.rows
        ),
        roots=tuple(decorate_tree(root) for root in compiled.roots),
    )


def decorate_semantic_projection(
    projection: SemanticProjection,
    decorations: tuple[RuntimeDecoration, ...],
) -> SemanticProjection:
    if not decorations:
        return projection
    return replace(
        projection,
        nodes=tuple(
            replace(
                node,
                badges=tuple(
                    dict.fromkeys(
                        (
                            *node.badges,
                            *(
                                item.label
                                for item in decorations
                                if item.semantic_id == node.semantic_id
                            ),
                        )
                    )
                ),
            )
            for node in projection.nodes
        ),
    )
