from dataclasses import replace

import pytest

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.domain_commands import SetDomainProperty
from code_visualizer.application.domain_workbench import project_notation
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.runtime_overlay import RuntimeOverlayContext
from code_visualizer.application.runtime_sessions import RuntimeSessionState, RuntimeSessionStatus
from code_visualizer.application.search import replacement_commands, search_project
from code_visualizer.application.semantic_index import (
    build_semantic_program,
    update_semantic_program,
)
from code_visualizer.automation.service import (
    AccessMode,
    AutomationCapability,
    AutomationContext,
    AutomationService,
)
from code_visualizer.domain.authoring import AuthoredSemanticRelation, SemanticConcept
from code_visualizer.domain.intentional import (
    BundleReference,
    ConceptDefinition,
    DomainIssue,
    DomainModel,
    DomainSchema,
    DomainWorkspace,
    IntentionalNode,
    PropertyDefinition,
    PropertyValue,
    RoleBinding,
    RoleDefinition,
)
from code_visualizer.domain.notation import NotationDefinition, NotationKind
from code_visualizer.domain.project import Project
from code_visualizer.domain.projection import ProjectionDefinition
from code_visualizer.domain.semantic import (
    SemanticObjectKind,
    SemanticRelation,
    SemanticRelationKind,
)
from code_visualizer.extensions.builtin import intentional_bundle, program_bundle
from code_visualizer.extensions.registry import (
    DomainExtensionBundle,
    DomainExtensionRegistry,
    RuntimeDecoration,
    RuntimePresentationContribution,
    SemanticContribution,
    validate_extension_requirements,
)
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.serialization import normalized_project_json
from code_visualizer.sdk.client import CodeVisualizerClient
from code_visualizer.validation import assess_project


def _project(*, required: BundleReference | None = None) -> Project:
    schema = DomainSchema(
        "schema:experiments",
        "example.experiments",
        "1",
        concepts=(
            ConceptDefinition(
                "experiment",
                "Experiment",
                properties=(PropertyDefinition("experiment:name", "Name", required=True),),
                reference_roles=(RoleDefinition("related", "Related", ("experiment",)),),
                display_property_id="experiment:name",
            ),
        ),
        bundle=required,
    )
    nodes = (
        IntentionalNode(
            "alpha",
            "experiment",
            (PropertyValue("experiment:name", "Alpha"),),
            references=(RoleBinding("related", ("beta",)),),
        ),
        IntentionalNode("beta", "experiment", (PropertyValue("experiment:name", "Beta"),)),
    )
    return Project(
        "project:domain",
        "Domain experiment",
        (),
        domain_workspace=DomainWorkspace(
            (schema,),
            (DomainModel("experiments", schema.id, "1", ("alpha", "beta"), nodes),),
        ),
    )


def test_registry_rejects_duplicate_bundles_and_ambiguous_contributions_atomically():
    notation = NotationDefinition("notation:shared", "Table", NotationKind.TABLE)
    first = DomainExtensionBundle("first", "1", notations=(notation,))
    registry = DomainExtensionRegistry((first,))
    with pytest.raises(ValueError, match="already registered"):
        registry.register(first)
    with pytest.raises(ValueError, match="Ambiguous"):
        registry.register(DomainExtensionBundle("second", "1", notations=(notation,)))
    assert registry.get("second", "1") is None
    assert registry.bundles() == (first,)


def test_registry_discovery_does_not_depend_on_registration_order():
    bundles = (program_bundle(), intentional_bundle())
    forward, reverse = DomainExtensionRegistry(bundles), DomainExtensionRegistry(reversed(bundles))
    assert forward.bundles() == reverse.bundles()
    assert forward.domains(_project()) == reverse.domains(_project())
    participants = forward.domains(_project())
    assert {item.command_prefix for item in participants} == {"program.", "domain."}
    assert next(item for item in participants if item.schema_id).object_ids == ("alpha", "beta")


def test_runtime_presentation_contribution_decorates_lenses_and_all_notation_kinds():
    project = _project()
    bundle = DomainExtensionBundle(
        "experiment.presentation",
        "1",
        runtime_presenters=(
            RuntimePresentationContribution(
                "experiment.active",
                lambda active_ids: tuple(
                    RuntimeDecoration(identity, "Observed experiment") for identity in active_ids
                ),
            ),
        ),
    )
    registry = DomainExtensionRegistry((program_bundle(), intentional_bundle(), bundle))
    kernel = ProjectKernel(ProjectAuthority(project), extensions=registry)
    before = normalized_project_json(project)
    try:
        state = RuntimeSessionState(
            "execution", 0, 0, RuntimeSessionStatus.PAUSED, semantic_id="alpha"
        )
        lens = kernel.compose_projection(
            ProjectionDefinition("domain", "Domain"),
            runtime_context=RuntimeOverlayContext(state),
        )
        assert (
            "Observed experiment" in next(item for item in lens.nodes if item.id == "alpha").badges
        )
        for definition in kernel.notations("experiments"):
            notation = project_notation(
                project,
                "experiments",
                definition.id,
                registry,
                active_node_ids=("alpha",),
                runtime_revision=0,
            )
            assert (
                "Observed experiment"
                in next(item for item in notation.graph.nodes if item.id == "alpha").badges
            )
            assert (
                "Observed experiment"
                in next(item for item in notation.roots if item.node_id == "alpha").badges
            )
            if notation.rows:
                assert (
                    "Observed experiment"
                    in next(item for item in notation.rows if item.node_id == "alpha").badges
                )
        assert normalized_project_json(project) == before
    finally:
        kernel.close()


def test_missing_extension_preserves_data_and_blocks_build_without_blocking_authority():
    project = _project(required=BundleReference("missing.bundle", "7"))
    encoded = normalized_project_json(project)
    restored = project_from_json(encoded)
    assert normalized_project_json(restored) == encoded
    assert restored.domain_workspace == project.domain_workspace
    assessment = assess_project(restored)
    assert not assessment.buildable
    assert "DOMAIN_EXTENSION_MISSING" in {item.code for item in assessment.blocking_diagnostics}
    authority = ProjectAuthority(restored)
    client = CodeVisualizerClient(authority, actor_id="editor")
    assert isinstance(
        client.submit(SetDomainProperty("experiments", "alpha", "experiment:name", "Renamed")),
        CommandAccepted,
    )
    assert (
        authority.snapshot().domain_workspace.models[0].node("alpha").property("experiment:name")
        == "Renamed"
    )


def test_bundle_validators_and_index_contributors_are_used_only_for_matching_schema():
    project = _project(required=BundleReference("experiments.bundle", "1"))
    schema = project.domain_workspace.schemas[0]

    def validate(snapshot, model):
        assert snapshot is project
        assert model.id == "experiments"
        return (DomainIssue("EXPERIMENT_REVIEW", "Review required", "alpha", incomplete=True),)

    def index(snapshot, model):
        return SemanticContribution(
            relations=(
                SemanticRelation(
                    "experiment:relation",
                    SemanticRelationKind.AUTHORED,
                    "alpha",
                    "beta",
                    "compares",
                ),
            )
        )

    bundle = DomainExtensionBundle(
        "experiments.bundle",
        "1",
        schemas=(schema,),
        validators=(validate,),
        semantic_indexers=(index,),
    )
    registry = DomainExtensionRegistry((bundle,))
    assert [item.code for item in validate_extension_requirements(project, registry)] == [
        "EXPERIMENT_REVIEW"
    ]
    assert "experiment:relation" in {
        item.id for item in build_semantic_program(project, registry).relations
    }
    changed = replace(
        project,
        domain_workspace=replace(
            project.domain_workspace,
            schemas=(replace(schema, description="Changed contract"),),
        ),
    )
    assert [item.code for item in validate_extension_requirements(changed, registry)] == [
        "DOMAIN_EXTENSION_SCHEMA_MISMATCH"
    ]
    assert "experiment:relation" not in {
        item.id for item in build_semantic_program(changed, registry).relations
    }


def test_domain_index_preserves_distinctions_identity_relations_and_selection_after_rename():
    project = _project()
    authority = ProjectAuthority(project)
    kernel = ProjectKernel(authority)
    client = CodeVisualizerClient(authority, actor_id="editor")
    try:
        before = kernel.queries.program
        by_id = {item.id: item for item in before.objects}
        assert by_id["experiments"].kind is SemanticObjectKind.DOMAIN
        assert by_id["schema:experiments"].kind is SemanticObjectKind.DOMAIN_SCHEMA
        assert by_id["experiment"].kind is SemanticObjectKind.CONCEPT_DEFINITION
        assert by_id["experiment:name"].kind is SemanticObjectKind.PROPERTY_DEFINITION
        assert by_id["related"].kind is SemanticObjectKind.ROLE_DEFINITION
        assert by_id["alpha"].kind is SemanticObjectKind.INTENTION
        kernel.selection.select(("alpha",), revision=0, source="test.table")
        result = client.submit(
            SetDomainProperty("experiments", "alpha", "experiment:name", "Renamed")
        )
        assert isinstance(result, CommandAccepted)
        assert kernel.selection.state.primary == "alpha"
        assert kernel.queries.semantic_object("alpha").label == "Renamed"
        assert before.relations == kernel.queries.program.relations
        update = update_semantic_program(
            project, before, authority.snapshot(), verify_with_full_rebuild=True
        )
        assert update.program == kernel.queries.program
        assert any(item.source_id == "alpha" for item in kernel.queries.references("beta"))
    finally:
        kernel.close()


def test_authored_concept_groupings_and_relationships_include_domain_objects():
    project = replace(
        _project(),
        concepts=(SemanticConcept("group:study", "Study", member_ids=("alpha",)),),
        semantic_relations=(AuthoredSemanticRelation("relation:study", "group:study", "beta"),),
    )
    indexed = build_semantic_program(project)
    assert (
        next(item for item in indexed.objects if item.id == "group:study").kind
        is SemanticObjectKind.CONCEPT
    )
    assert any(
        item.kind is SemanticRelationKind.CONCEPTUALLY_CONTAINS and item.target_id == "alpha"
        for item in indexed.relations
    )
    assert any(
        item.id == "relation:study" and item.target_id == "beta" for item in indexed.relations
    )


def test_domain_search_replace_uses_node_and_property_identity_in_one_transaction():
    authority = ProjectAuthority(_project())
    client = CodeVisualizerClient(authority, actor_id="search")
    matches = search_project(authority.snapshot(), "Alpha")
    assert len(matches) == 1
    assert matches[0].object_id == "alpha"
    commands = replacement_commands(authority.snapshot(), ((matches[0], "Renamed"),))
    assert isinstance(commands[0], SetDomainProperty)
    assert isinstance(client.transaction(commands), CommandAccepted)
    assert search_project(authority.snapshot(), "Renamed")[0].object_id == "alpha"
    assert isinstance(client.undo(), CommandAccepted)
    assert search_project(authority.snapshot(), "Alpha")[0].object_id == "alpha"


def test_workbench_automation_reads_notation_and_edits_same_identity_with_revision_conflict():
    authority = ProjectAuthority(_project())
    service = AutomationService(authority)
    context = AutomationContext(
        "automation",
        "connection",
        AccessMode.COMMIT,
        frozenset({AutomationCapability.READ, AutomationCapability.EDIT}),
    )
    try:
        info = service.dispatch("query.workbench", {}, context)
        assert info["workspace"]["models"][0]["id"] == "experiments"
        notations = service.dispatch("query.notations", {"model_id": "experiments"}, context)
        table = next(item for item in notations if item["kind"] == "table")
        projected = service.dispatch(
            "query.notation", {"model_id": "experiments", "notation_id": table["id"]}, context
        )
        cell = projected["rows"][0]["cells"][0]
        assert cell["edit"]["node_id"] == "alpha"
        result = service.dispatch(
            "domain.node.set_property",
            {
                "model_id": "experiments",
                "node_id": "alpha",
                "property_id": "experiment:name",
                "value": "Updated",
                "expected_revision": 0,
            },
            context,
        )
        assert (
            authority.snapshot()
            .domain_workspace.models[0]
            .node("alpha")
            .property("experiment:name")
            == "Updated"
        ), result
        assert service.kernel.queries.semantic_object("alpha").label == "Updated"
        snapshot = normalized_project_json(authority.snapshot())
        service.dispatch(
            "query.notation", {"model_id": "experiments", "notation_id": table["id"]}, context
        )
        assert normalized_project_json(authority.snapshot()) == snapshot
    finally:
        service.close()
