from dataclasses import replace

import pytest

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.domain_execution import debug_project, trace_project
from code_visualizer.application.domain_workbench import project_notation
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.language_commands import (
    DeleteDomainLanguage,
    PutDomainTransformation,
)
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.notations import notation_edit_command
from code_visualizer.application.search import search_project
from code_visualizer.domain.intentional import (
    ConceptDefinition,
    DomainModel,
    DomainSchema,
    DomainWorkspace,
    IntentionalNode,
    PropertyDefinition,
    PropertyValue,
)
from code_visualizer.domain.language import (
    AuthoredDomainLanguage,
    AuthoredTransformation,
    FunctionTemplate,
    QueryBinary,
    QueryBinaryOperator,
    QueryLiteral,
    QueryNodes,
    QueryProperty,
    QueryVariable,
    RuntimeLiteral,
    TemplateHole,
    TemplateOutput,
    ValidatorDefinition,
)
from code_visualizer.domain.notation import (
    NotationColumn,
    NotationDefinition,
    NotationField,
    NotationKind,
    NotationNodeRule,
)
from code_visualizer.domain.program import program_statements
from code_visualizer.domain.project import Project
from code_visualizer.domain.semantic import SemanticObjectKind
from code_visualizer.domain.transformation import (
    PROGRAM_REPRESENTATION,
    OriginLink,
    OriginMap,
    Representation,
    TransformationDefinition,
)
from code_visualizer.execution.runner import run_project
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.languages import resolve_domain_languages
from code_visualizer.extensions.registry import (
    DomainExtensionBundle,
    DomainExtensionRegistry,
    validate_extension_requirements,
)
from code_visualizer.generation.build import prepare_build
from code_visualizer.generation.python import generate_python, generate_python_project
from code_visualizer.generation.transformation import (
    RegisteredTransformation,
    TransformationError,
    TransformationInput,
    execute_transformations,
    plan_transformations,
)
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.serialization import normalized_project_json
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.validation import assess_project


def _project(prefix="announcement", namespace="example.announcements"):
    def identity(role):
        return f"{prefix}:{role}"

    schema = DomainSchema(
        identity("schema"),
        namespace,
        "1",
        (
            ConceptDefinition(
                identity("concept"),
                "Announcement",
                (PropertyDefinition(identity("text"), "Text", required=True),),
                display_property_id=identity("text"),
            ),
        ),
    )
    node = IntentionalNode(
        identity("item"), identity("concept"), (PropertyValue(identity("text"), "Doors opening"),)
    )
    model = DomainModel(identity("model"), schema.id, schema.version, (node.id,), (node,))
    notation_args = {"schema_id": schema.id, "concept_ids": (identity("concept"),)}
    notations = (
        NotationDefinition(
            identity("table"),
            "Announcements",
            NotationKind.TABLE,
            columns=(NotationColumn("text", "Text", NotationField(identity("text"))),),
            **notation_args,
        ),
        NotationDefinition(
            identity("graph"),
            "Announcement graph",
            NotationKind.GRAPH,
            node_rules=(NotationNodeRule(identity("concept"), identity("text")),),
            **notation_args,
        ),
        NotationDefinition(
            identity("form"), "Announcement form", NotationKind.TREE_FORM, **notation_args
        ),
    )
    rule = ValidatorDefinition(
        identity("rule"),
        identity("concept"),
        "announcement",
        QueryBinary(
            identity("predicate"),
            QueryBinaryOperator.NOT_EQUAL,
            QueryProperty(
                identity("rule-property"),
                QueryVariable(identity("rule-variable"), "announcement"),
                identity("text"),
            ),
            QueryLiteral(identity("rule-empty"), ""),
        ),
        "Announcement text must not be empty",
        "ANNOUNCEMENT_EMPTY",
    )
    recipe = AuthoredTransformation(
        TransformationDefinition(
            identity("transform"),
            "1",
            Representation(namespace, "1"),
            PROGRAM_REPRESENTATION,
        ),
        (
            FunctionTemplate(
                identity("function-template"),
                QueryNodes(identity("source-query"), identity("concept")),
                "announcement",
                body=(
                    TemplateOutput(
                        identity("output-template"),
                        RuntimeLiteral(
                            identity("runtime-expression"),
                            QueryProperty(
                                identity("output-property"),
                                QueryVariable(identity("output-variable"), "announcement"),
                                identity("text"),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    language = AuthoredDomainLanguage(
        identity("language"),
        schema.id,
        "1",
        version="3",
        title="Announcements language",
        notations=notations,
        validators=(rule,),
        transformations=(recipe,),
    )
    return Project(
        identity("project"),
        "Announcements",
        (),
        domain_workspace=DomainWorkspace(
            (schema,),
            (model,),
            language_definitions=(language,),
        ),
    )


def test_one_resolver_composes_authored_data_without_schema_or_host_ownership_changes():
    project = _project()
    host = builtin_registry()
    host_bundles = host.bundles()
    encoded = normalized_project_json(project)
    resolved = resolve_domain_languages(project, host)
    schema = project.domain_workspace.schemas[0]
    assert schema.bundle is None
    assert resolved.bundles() == host_bundles
    assert resolved.get("announcement:language", "3") is None
    assert host.notations_for(schema.id, "1") == ()
    assert len(resolved.notations_for(schema.id, "1")) == 3
    assert resolved.notations_for(schema.id, "2") == ()
    transforms = resolved.transformations_for(schema.id, "1")
    assert len(transforms) == 1
    assert (transforms[0].schema_id, transforms[0].schema_version) == (schema.id, "1")
    assert normalized_project_json(project) == encoded
    assert not validate_extension_requirements(project, resolved)


def test_authored_rules_build_generate_and_execute_through_existing_pipeline():
    project = _project()
    before = normalized_project_json(project)
    first, second = prepare_build(project), prepare_build(project)
    assert first == second
    assert not project.program_model.functions
    assert first.project.program_model.functions
    assert all(link.source_ids == ("announcement:item",) for link in first.origins.links)
    generated = generate_python_project(project)
    assert generated.invocation is not None
    result = run_project(generated)
    assert result.return_code == 0, result.stderr
    assert result.stdout == "Doors opening\n"
    assert normalized_project_json(project) == before


def test_authored_notations_edit_one_object_and_shared_semantic_index():
    project = _project()
    kernel = ProjectKernel(ProjectAuthority(project))
    client = CodeVisualizerClient(kernel.authority, actor_id="notation")
    try:
        table = kernel.notation("announcement:model", "announcement:table")
        binding = table.rows[0].cells[0].edit
        assert binding is not None
        result = client.submit(notation_edit_command(binding, "Please board", revision=0))
        assert isinstance(result, CommandAccepted)
        assert len(kernel.authority.snapshot().domain_workspace.models[0].nodes) == 1
        graph = kernel.notation("announcement:model", "announcement:graph")
        assert graph.graph.nodes[0].label == "Please board"
        form = kernel.notation("announcement:model", "announcement:form")
        assert form.roots[0].label == "Please board"
        objects = {item.id: item for item in kernel.queries.program.objects}
        assert objects["announcement:item"].label == "Please board"
        assert objects["announcement:language"].kind is SemanticObjectKind.LANGUAGE_DEFINITION
        assert objects["announcement:rule"].kind is SemanticObjectKind.VALIDATION_RULE
        assert objects["announcement:transform"].kind is SemanticObjectKind.TRANSFORMATION
        assert objects["announcement:output-template"].kind is SemanticObjectKind.TEMPLATE
        assert objects["announcement:function-template"].parent_id == "announcement:transform"
        matches = search_project(kernel.authority.snapshot(), "Announcements language")
        assert any(item.object_id == "announcement:language" for item in matches)
        assert all(not item.replace_supported for item in matches)
        kernel.selection.select(("announcement:output-template",), source="template-editor")
        assert kernel.selection.state.primary == "announcement:output-template"
        assert "Please board" in generate_python(kernel.authority.snapshot()).source
    finally:
        kernel.close()


def test_authored_validator_blocks_build_but_roundtrip_preserves_invalid_model():
    project = _project()
    workspace = project.domain_workspace
    model = workspace.models[0]
    invalid = replace(model.nodes[0], properties=(PropertyValue("announcement:text", ""),))
    project = replace(
        project, domain_workspace=replace(workspace, models=(replace(model, nodes=(invalid,)),))
    )
    restored = project_from_json(normalized_project_json(project))
    assert restored == project
    assert "ANNOUNCEMENT_EMPTY" in {item.code for item in assess_project(restored).diagnostics}
    with pytest.raises(TransformationError, match="must not be empty"):
        prepare_build(restored)


def test_unsupported_engine_preserves_data_and_has_discoverable_diagnostic():
    project = _project()
    workspace = project.domain_workspace
    future = replace(workspace.language_definitions[0], syntax_version=99)
    project = replace(project, domain_workspace=replace(workspace, language_definitions=(future,)))
    restored = project_from_json(normalized_project_json(project))
    assert restored.domain_workspace.language_definitions == (future,)
    kernel = ProjectKernel(ProjectAuthority(restored))
    try:
        assert "DOMAIN_LANGUAGE_ENGINE_UNAVAILABLE" in {
            item.code for item in kernel.workbench().diagnostics
        }
        assert "announcement:language" in {item.id for item in kernel.queries.program.objects}
        assert not assess_project(restored).buildable
    finally:
        kernel.close()


def test_resolving_an_old_resolved_registry_drops_deleted_authored_contributions():
    project = _project()
    resolved = resolve_domain_languages(project)
    without_language = replace(
        project,
        domain_workspace=replace(
            project.domain_workspace,
            language_definitions=(),
        ),
    )
    fresh = resolve_domain_languages(without_language, resolved)
    assert not fresh.notations_for("announcement:schema", "1")
    assert not fresh.transformations_for("announcement:schema", "1")
    assert fresh is resolved.host_registry


def test_authority_language_edits_undo_redo_and_delete_rebuild_one_resolved_registry():
    project = _project()
    kernel = ProjectKernel(ProjectAuthority(project))
    client = CodeVisualizerClient(kernel.authority, actor_id="language-editor")
    language = project.domain_workspace.language_definitions[0]
    recipe = language.transformations[0]
    function = recipe.functions[0]
    changed = replace(
        recipe,
        functions=(
            replace(
                function,
                body=(
                    TemplateOutput(
                        "announcement:output-template",
                        RuntimeLiteral(
                            "announcement:runtime-expression",
                            QueryLiteral("announcement:output-property", "Boarding complete"),
                        ),
                    ),
                ),
            ),
        ),
    )
    try:
        original_program = prepare_build(project).project.program_model
        assert isinstance(
            client.submit(PutDomainTransformation(language.id, changed)), CommandAccepted
        )
        assert "Boarding complete" in generate_python(kernel.authority.snapshot()).source
        assert kernel.queries.semantic_object("announcement:output-variable") is None
        assert isinstance(client.undo(), CommandAccepted)
        assert prepare_build(kernel.authority.snapshot()).project.program_model == original_program
        assert kernel.queries.semantic_object("announcement:output-variable") is not None
        assert isinstance(client.redo(), CommandAccepted)
        assert "Boarding complete" in generate_python(kernel.authority.snapshot()).source
        assert isinstance(client.submit(DeleteDomainLanguage(language.id)), CommandAccepted)
        assert not kernel.extensions.transformations_for("announcement:schema", "1")
        assert kernel.queries.semantic_object(language.id) is None
        assert isinstance(client.undo(), CommandAccepted)
        assert len(kernel.extensions.transformations_for("announcement:schema", "1")) == 1
        restored = project_from_json(normalized_project_json(kernel.authority.snapshot()))
        assert not restored.program_model.functions
        assert "Boarding complete" in generate_python(restored).source
    finally:
        kernel.close()


def test_incomplete_transform_keeps_valid_notations_and_rules_available_for_authoring():
    project = _project()
    workspace = project.domain_workspace
    language = workspace.language_definitions[0]
    recipe = language.transformations[0]
    incomplete = replace(
        recipe,
        functions=(
            replace(
                recipe.functions[0],
                body=(TemplateHole("announcement:hole"),),
            ),
        ),
    )
    project = replace(
        project,
        domain_workspace=replace(
            workspace, language_definitions=(replace(language, transformations=(incomplete,)),)
        ),
    )
    resolved = resolve_domain_languages(project)
    assert "LANGUAGE_HOLE" in {item.code for item in resolved.resolution_issues}
    assert len(resolved.notations_for("announcement:schema", "1")) == 3
    assert len(resolved.authored_validators_for("announcement:schema", "1")) == 1
    assert not resolved.transformations_for("announcement:schema", "1")
    assert not assess_project(project).buildable


def test_two_schema_ids_with_one_namespace_cannot_borrow_an_authored_transform():
    first, second = _project(), _project("other")
    project = replace(
        first,
        domain_workspace=replace(
            first.domain_workspace,
            schemas=(*first.domain_workspace.schemas, *second.domain_workspace.schemas),
            models=(*first.domain_workspace.models, *second.domain_workspace.models),
        ),
    )
    resolved = resolve_domain_languages(project)
    assert not resolved.transformations_for("other:schema", "1")
    with pytest.raises(TransformationError) as failure:
        prepare_build(project, entrypoint_model_id="announcement:model")
    assert failure.value.code == "TRANSFORM_NO_PATH"


def test_two_schema_scoped_transforms_compose_even_when_representations_match():
    first, second = _project(), _project("other")
    project = replace(
        first,
        domain_workspace=replace(
            first.domain_workspace,
            schemas=(*first.domain_workspace.schemas, *second.domain_workspace.schemas),
            models=(*first.domain_workspace.models, *second.domain_workspace.models),
            language_definitions=(
                *first.domain_workspace.language_definitions,
                *second.domain_workspace.language_definitions,
            ),
        ),
    )
    build = prepare_build(project, entrypoint_model_id="announcement:model")
    assert len(build.project.program_model.functions) == 2
    assert len({item.id for item in build.project.program_model.functions}) == 2
    assert set(build.transformations) == {"announcement:transform@1", "other:transform@1"}


def test_host_notation_collision_is_explicit_and_never_overrides_registered_behavior():
    project = _project()
    notation = project.domain_workspace.language_definitions[0].notations[0]
    host = DomainExtensionRegistry(
        (
            *builtin_registry().bundles(),
            DomainExtensionBundle("host.notations", "1", notations=(notation,)),
        )
    )
    resolved = resolve_domain_languages(project, host)
    assert {item.code for item in resolved.resolution_issues} == {
        "DOMAIN_LANGUAGE_CONTRIBUTION_CONFLICT"
    }
    assert resolved.notations_for("announcement:schema", "1") == (notation,)
    assert not resolved.transformations_for("announcement:schema", "1")
    assert not assess_project(project, extensions=host).buildable


def test_host_and_authored_valid_paths_are_reported_as_ambiguous():
    project = _project()
    authored = resolve_domain_languages(project).transformations_for("announcement:schema", "1")[0]
    competing = replace(authored, definition=replace(authored.definition, id="host:competing"))
    host = DomainExtensionRegistry(
        (
            *builtin_registry().bundles(),
            DomainExtensionBundle("host.transforms", "1", transformations=(competing,)),
        )
    )
    with pytest.raises(TransformationError) as failure:
        prepare_build(project, host)
    assert failure.value.code == "TRANSFORM_AMBIGUOUS_PATH"


@pytest.mark.parametrize(
    "generated_id, collision", [("announcement:predicate", True), ("text", False)]
)
def test_generated_ids_respect_language_ownership_but_not_local_notation_keys(
    generated_id, collision
):
    project = _project()
    registered = resolve_domain_languages(project).transformations_for("announcement:schema", "1")[
        0
    ]
    language = replace(project.domain_workspace.language_definitions[0], transformations=())
    project = replace(
        project,
        domain_workspace=replace(
            project.domain_workspace,
            language_definitions=(language,),
        ),
    )

    def remap_output(snapshot):
        result = registered.transform(snapshot)
        function = result.value.functions[0]
        output = function.body.statements[0]
        function = replace(
            function, body=replace(function.body, statements=(replace(output, id=generated_id),))
        )
        return replace(
            result,
            value=replace(result.value, functions=(function,)),
            origins=replace(
                result.origins,
                links=tuple(
                    replace(link, generated_id=generated_id)
                    if link.generated_id == output.id
                    else link
                    for link in result.origins.links
                ),
            ),
        )

    host = DomainExtensionRegistry(
        (
            *builtin_registry().bundles(),
            DomainExtensionBundle(
                "host.remapped",
                "1",
                transformations=(replace(registered, transform=remap_output),),
            ),
        )
    )
    if collision:
        with pytest.raises(TransformationError) as failure:
            prepare_build(project, host)
        assert failure.value.code == "TRANSFORM_ID_COLLISION"
    else:
        assert prepare_build(project, host).project.program_model.functions


def test_explicit_transform_execution_checks_schema_scope_before_calling_implementation():
    first, second = _project(), _project("other")
    registered = resolve_domain_languages(first).transformations_for("announcement:schema", "1")[0]
    model = second.domain_workspace.models[0]
    snapshot = TransformationInput(
        second,
        model,
        registered.definition.source,
        model,
        OriginMap(
            second.id,
            second.revision,
            (
                OriginLink(model.id, model.roots),
                OriginLink(model.nodes[0].id, (model.nodes[0].id,)),
            ),
        ),
    )
    with pytest.raises(TransformationError) as failure:
        execute_transformations(snapshot, (registered,))
    assert failure.value.code == "TRANSFORM_SCHEMA_SCOPE"


def test_schema_scope_requires_identity_and_version_together():
    project = _project()
    registered = resolve_domain_languages(project).transformations_for("announcement:schema", "1")[
        0
    ]
    with pytest.raises(ValueError, match="paired"):
        RegisteredTransformation(registered.definition, registered.transform, schema_id="schema")
    assert plan_transformations(
        (registered,), registered.definition.source, PROGRAM_REPRESENTATION
    ) == (registered,)


@pytest.mark.parametrize("execution", ["trace", "debug"])
def test_authored_transformation_runtime_uses_shared_origin_and_notation_plane(execution):
    project = _project()
    kernel = ProjectKernel(ProjectAuthority(project))
    operations = {
        statement.id
        for function in prepare_build(project).project.program_model.functions
        for statement in program_statements(function.body)
    }
    debug = None
    try:
        if execution == "trace":
            result = trace_project(kernel)
            assert result.run.return_code == 0, result.run.stderr
            assert result.run.stdout == "Doors opening\n"
        else:
            debug = debug_project(kernel)
            for _ in range(40):
                event = debug.wait_event()
                if event.event == "paused":
                    active = kernel.runtime.active
                    if active is not None and active.semantic_id in operations:
                        debug.step_over()
                    else:
                        debug.step_into()
                if event.event in {"finished", "exception"}:
                    assert event.event == "finished", event.detail
                    break
            else:
                pytest.fail("Authored template debugger did not complete")
        active = next(
            item
            for item in kernel.runtime.history()
            if "announcement:item" in item.origin_ids and item.semantic_id in operations
        )
        assert active.semantic_id.startswith("derived:")
        assert set(active.origin_ids) <= set(active.active_ids)
        for notation in project.domain_workspace.language_definitions[0].notations:
            projected = project_notation(
                project,
                "announcement:model",
                notation.id,
                kernel.extensions,
                active_node_ids=active.active_ids,
                runtime_revision=active.project_revision,
            )
            assert "active" in projected.graph.nodes[0].badges
            assert projected.roots[0].active
            if projected.rows:
                assert projected.rows[0].active
        assert kernel.authority.snapshot() == project
    finally:
        if debug is not None:
            debug.stop()
        kernel.close()
