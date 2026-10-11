"""Authored FSM representations lower through disposable schema-defined IRs."""

from dataclasses import fields, is_dataclass, replace

import pytest

from code_visualizer.application.authored_examples import authored_traffic_light_project
from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.domain_commands import SetDomainProperty
from code_visualizer.application.domain_execution import trace_project
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.language_commands import PutDomainTransformation
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.domain import language as l
from code_visualizer.domain.intentional import DomainIssue, DomainModel, DomainWorkspace
from code_visualizer.domain.language_structure import language_owned_ids
from code_visualizer.domain.language_validation import validate_authored_language
from code_visualizer.domain.program import ProgramModel
from code_visualizer.domain.transformation import (
    PROGRAM_REPRESENTATION,
    OriginLink,
    OriginMap,
    Representation,
    TransformationDefinition,
)
from code_visualizer.execution.runner import run_generated
from code_visualizer.extensions.builtin import intentional_bundle, program_bundle
from code_visualizer.extensions.languages import resolve_domain_languages
from code_visualizer.extensions.registry import DomainExtensionRegistry
from code_visualizer.generation.build import prepare_build, program_identities
from code_visualizer.generation.python import generate_python, generate_python_project
from code_visualizer.generation.transformation import (
    TransformationError,
    TransformationInput,
    execute_transformations,
    plan_transformations,
    value_identities,
)
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.serialization import normalized_project_json
from code_visualizer.sdk import CodeVisualizerClient


def _rewrite(value, mapping):
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, tuple):
        return tuple(_rewrite(item, mapping) for item in value)
    if is_dataclass(value):
        return replace(
            value,
            **{
                field.name: _rewrite(getattr(value, field.name), mapping) for field in fields(value)
            },
        )
    return value


def _schema_copy(source, prefix):
    mapping = {identity: f"{prefix}:{identity}" for identity in value_identities(source)}
    mapping[source.namespace] = f"{source.namespace}.{prefix}"
    return _rewrite(source, mapping), mapping


def _copy_recipe(source, target, mapping, prefix, dependencies=()):
    templates = {concept.id: f"{prefix}:node:{concept.id}" for concept in source.concepts}
    nodes = []
    for concept in source.concepts:
        template_id = templates[concept.id]
        binding = f"{prefix}:source"

        def query_property(prop, template_id=template_id, binding=binding):
            return l.QueryProperty(
                f"{template_id}:{prop.id}:query",
                l.QueryVariable(f"{template_id}:{prop.id}:source", binding),
                prop.id,
            )

        def roles(items, template_id=template_id, binding=binding):
            return tuple(
                l.DomainRoleTemplate(
                    f"{template_id}:{role.id}:role",
                    mapping[role.id],
                    templates[role.allowed_concept_ids[0]],
                    l.QueryRole(
                        f"{template_id}:{role.id}:query",
                        l.QueryVariable(f"{template_id}:{role.id}:source", binding),
                        role.id,
                    ),
                )
                for role in items
            )

        nodes.append(
            l.DomainNodeTemplate(
                template_id,
                l.QueryNodes(f"{template_id}:select", concept.id),
                binding,
                mapping[concept.id],
                properties=tuple(
                    l.DomainPropertyTemplate(
                        f"{template_id}:{prop.id}:property", mapping[prop.id], query_property(prop)
                    )
                    for prop in concept.properties
                ),
                children=roles(concept.containment_roles),
                references=roles(concept.reference_roles),
                root=concept.id.endswith(":machine"),
            )
        )
    return l.AuthoredTransformation(
        TransformationDefinition(
            f"{prefix}:lower",
            "1",
            Representation(source.namespace, source.version),
            Representation(target.namespace, target.version),
            dependencies,
        ),
        domain=l.DomainTemplate(f"{prefix}:domain", target.id, target.version, tuple(nodes)),
    )


def staged_traffic_light():
    project = authored_traffic_light_project()
    original = project.domain_workspace
    source = original.schemas[0]
    b, a_to_b = _schema_copy(source, "normalized")
    c, b_to_c = _schema_copy(b, "executable")
    first = _copy_recipe(source, b, a_to_b, "stage:a")
    second = _copy_recipe(b, c, b_to_c, "stage:b", (first.definition.key,))
    language_a = replace(
        original.language_definitions[0], transformations=(first,), syntax_version=2
    )
    language_b = l.AuthoredDomainLanguage("language:b", b.id, b.version, transformations=(second,))
    mapping = {
        **{
            identity: f"stage:c:{identity}"
            for identity in language_owned_ids(original.language_definitions[0])
        },
        **{identity: b_to_c.get(mapped, mapped) for identity, mapped in a_to_b.items()},
    }
    language_c = _rewrite(original.language_definitions[0], mapping)
    last = language_c.transformations[0]
    last = replace(last, definition=replace(last.definition, depends_on=(second.definition.key,)))
    language_c = replace(language_c, transformations=(last,), notations=(), syntax_version=2)
    return replace(
        project,
        domain_workspace=DomainWorkspace(
            (source, b, c),
            original.models,
            language_definitions=(language_c, language_a, language_b),
        ),
    )


def _host():
    return DomainExtensionRegistry((intentional_bundle(), program_bundle()))


def _plan(project, target=PROGRAM_REPRESENTATION, target_schema=None):
    model = project.domain_workspace.models[0]
    schema = project.domain_workspace.schema(model.schema_id)
    registry = resolve_domain_languages(project, _host())
    assert not registry.resolution_issues, registry.resolution_issues
    plan = plan_transformations(
        registry.transformations(),
        Representation(schema.namespace, schema.version),
        target,
        source_schema=(schema.id, schema.version),
        target_schema=target_schema,
    )
    snapshot = TransformationInput(
        project,
        model,
        Representation(schema.namespace, schema.version),
        model,
        OriginMap(
            project.id,
            project.revision,
            (
                OriginLink(model.id, model.roots),
                *(OriginLink(node.id, (node.id,)) for node in model.nodes),
            ),
        ),
    )
    return registry, snapshot, plan


def test_three_authored_languages_generate_run_and_return_origins_without_derived_stores(tmp_path):
    project = staged_traffic_light()
    canonical = normalized_project_json(project)
    build = prepare_build(project, _host())
    assert build == prepare_build(project, _host())
    assert build.transformations == ("stage:a:lower@1", "stage:b:lower@1", "stage:c:recipe:lower@1")
    assert project.program_model == ProgramModel()
    assert len(project.domain_workspace.models) == 1
    assert build.project.domain_workspace == project.domain_workspace
    assert program_identities(build.project.program_model) == {
        link.generated_id for link in build.origins.links
    }
    source_ids = {node.id for node in project.domain_workspace.models[0].nodes}
    assert all(set(link.source_ids) <= source_ids for link in build.origins.links)
    generated = generate_python_project(project, extensions=_host())
    for item in generated.files:
        path = tmp_path / item.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(item.source, encoding="utf-8")
    run = run_generated(tmp_path / "run_project.py")
    assert run.return_code == 0, run.stderr
    assert run.stdout.splitlines() == [
        "Green",
        "The signal changes.",
        "Yellow",
        "The signal changes.",
        "Red",
        "The signal changes.",
    ]
    kernel = ProjectKernel(ProjectAuthority(project), extensions=_host())
    try:
        traced = trace_project(kernel)
        assert traced.run.return_code == 0, traced.run.stderr
        assert any(
            {"traffic:green-yellow", "traffic:yellow", "traffic:signal"} <= set(state.origin_ids)
            for state in kernel.runtime.history()
        )
        assert normalized_project_json(kernel.authority.snapshot()) == canonical
    finally:
        kernel.close()


def test_intermediate_models_have_exact_schema_ownership_references_and_composed_origins():
    project = staged_traffic_light()
    b = project.domain_workspace.schemas[1]
    registry, snapshot, plan = _plan(
        project, Representation(b.namespace, b.version), (b.id, b.version)
    )
    result = execute_transformations(
        snapshot, plan, validate_domain=lambda model: registry.validate_model(project, model)
    )
    assert isinstance(result.value, DomainModel)
    assert result.value.schema_id == b.id
    assert result.value.id not in {item.id for item in project.domain_workspace.models}
    nodes = {node.id: node for node in result.value.nodes}
    assert len(nodes) == len(snapshot.model.nodes)
    assert all(
        target in nodes
        for node in nodes.values()
        for role in (*node.children, *node.references)
        for target in role.node_ids
    )
    assert all(result.origins.sources(node.id) for node in nodes.values())
    assert {source for node in nodes.values() for source in result.origins.sources(node.id)} == {
        node.id for node in snapshot.model.nodes
    }


def test_save_rename_undo_and_redo_keep_pipeline_derived_and_ids_stable():
    project = staged_traffic_light()
    restored = project_from_json(normalized_project_json(project))
    assert restored == project
    kernel = ProjectKernel(ProjectAuthority(restored), extensions=_host())
    client = CodeVisualizerClient(kernel.authority, actor_id="author")
    try:
        before = prepare_build(project, kernel.extensions)
        assert isinstance(
            client.submit(
                SetDomainProperty("traffic:model", "traffic:yellow", "fsm:state:name", "Amber")
            ),
            CommandAccepted,
        )
        renamed = prepare_build(kernel.authority.snapshot(), kernel.extensions)
        assert renamed.origins.links == before.origins.links
        assert program_identities(renamed.project.program_model) == program_identities(
            before.project.program_model
        )
        assert (
            "Amber"
            in generate_python(kernel.authority.snapshot(), extensions=kernel.extensions).source
        )
        assert isinstance(client.undo(), CommandAccepted)
        assert (
            prepare_build(kernel.authority.snapshot(), kernel.extensions).project.program_model
            == before.project.program_model
        )
        assert isinstance(client.redo(), CommandAccepted)
        reloaded = project_from_json(normalized_project_json(kernel.authority.snapshot()))
        assert len(reloaded.domain_workspace.models) == 1
        assert not reloaded.program_model.functions
        assert "Amber" in generate_python(reloaded, extensions=_host()).source
    finally:
        kernel.close()


def test_intermediate_schema_can_share_a_namespace_without_becoming_another_schema():
    project = staged_traffic_light()
    a, b, c = project.domain_workspace.schemas
    # Exact schema scopes, not namespace strings alone, distinguish the stages.
    project = _rewrite(project, {b.namespace: a.namespace, c.namespace: a.namespace})
    assert prepare_build(project, _host()).project.program_model.functions


@pytest.mark.parametrize("cycle", [False, True])
def test_competing_authored_paths_and_cycles_are_explicit(cycle):
    project = staged_traffic_light()
    workspace = project.domain_workspace
    a_language = next(
        item for item in workspace.language_definitions if item.schema_id == workspace.schemas[0].id
    )
    first = a_language.transformations[0]
    if cycle:
        last = workspace.language_definitions[0].transformations[0]
        first = replace(
            first, definition=replace(first.definition, depends_on=(last.definition.key,))
        )
        changed = replace(a_language, transformations=(first,))
    else:
        mapping = {
            identity: f"alternative:{identity}"
            for identity in language_owned_ids(replace(a_language, notations=(), validators=()))
        }
        duplicate = _rewrite(first, mapping)
        changed = replace(a_language, transformations=(first, duplicate))
        # Either A->B implementation satisfies B's prerequisite only when its
        # transform key is listed; remove that constraint to expose both paths.
        languages = tuple(
            replace(
                item,
                transformations=tuple(
                    replace(recipe, definition=replace(recipe.definition, depends_on=()))
                    for recipe in item.transformations
                ),
            )
            if item.schema_id == workspace.schemas[1].id
            else item
            for item in workspace.language_definitions
        )
        workspace = replace(workspace, language_definitions=languages)
    project = replace(
        project,
        domain_workspace=replace(
            workspace,
            language_definitions=tuple(
                changed if item.id == changed.id else item
                for item in workspace.language_definitions
            ),
        ),
    )
    with pytest.raises(TransformationError) as caught:
        prepare_build(project, _host())
    assert caught.value.code == (
        "TRANSFORM_DEPENDENCY_CYCLE" if cycle else "TRANSFORM_AMBIGUOUS_PATH"
    )


def test_domain_template_edit_is_one_authority_command_and_undo_restores_the_recipe():
    project = staged_traffic_light()
    kernel = ProjectKernel(ProjectAuthority(project), extensions=_host())
    client = CodeVisualizerClient(kernel.authority, actor_id="template-editor")
    language = next(
        item
        for item in project.domain_workspace.language_definitions
        if item.schema_id == "fsm:schema"
    )
    recipe = language.transformations[0]
    assert recipe.domain is not None
    modified = replace(
        recipe, domain=replace(recipe.domain, nodes=tuple(reversed(recipe.domain.nodes)))
    )
    try:
        assert isinstance(
            client.submit(PutDomainTransformation(language.id, modified)), CommandAccepted
        )
        assert prepare_build(
            kernel.authority.snapshot(), kernel.extensions
        ).project.program_model.functions
        assert isinstance(client.undo(), CommandAccepted)
        assert kernel.authority.snapshot().domain_workspace.language(language.id) == language
    finally:
        kernel.close()


def test_domain_templates_require_grammar_two_and_a_real_target_schema():
    project = staged_traffic_light()
    schema = project.domain_workspace.schemas[0]
    language = next(
        item
        for item in project.domain_workspace.language_definitions
        if item.schema_id == schema.id
    )
    assert "LANGUAGE_SYNTAX_UPGRADE" in {
        item.code
        for item in validate_authored_language(
            replace(language, syntax_version=1), schema, schemas=project.domain_workspace.schemas
        )
    }
    assert "LANGUAGE_TARGET_SCHEMA" in {
        item.code for item in validate_authored_language(language, schema)
    }


def test_invalid_intermediate_required_values_fail_before_the_next_stage():
    project = staged_traffic_light()
    workspace = project.domain_workspace
    language = next(
        item for item in workspace.language_definitions if item.schema_id == "fsm:schema"
    )
    recipe = language.transformations[0]
    assert recipe.domain is not None
    changed = replace(
        recipe,
        domain=replace(
            recipe.domain,
            nodes=tuple(
                replace(node, properties=()) if node.concept_id.endswith(":state") else node
                for node in recipe.domain.nodes
            ),
        ),
    )
    project = replace(
        project,
        domain_workspace=replace(
            workspace,
            language_definitions=tuple(
                replace(item, transformations=(changed,)) if item.id == language.id else item
                for item in workspace.language_definitions
            ),
        ),
    )
    with pytest.raises(TransformationError) as caught:
        prepare_build(project, _host())
    assert caught.value.code == "DOMAIN_PROPERTY_REQUIRED"


def test_each_intermediate_runs_its_registered_validation_before_later_stages():
    project = staged_traffic_light()
    _, snapshot, plan = _plan(project)
    visited = []

    def reject_intermediate(model):
        visited.append(model.schema_id)
        return (DomainIssue("INTERMEDIATE_RULE", "Target invariant failed", model.id),)

    with pytest.raises(TransformationError) as caught:
        execute_transformations(snapshot, plan, validate_domain=reject_intermediate)
    assert caught.value.code == "INTERMEDIATE_RULE"
    assert visited == [project.domain_workspace.schemas[1].id]


def test_intermediate_output_cannot_reuse_canonical_identity():
    project = staged_traffic_light()
    _, snapshot, plan = _plan(project)
    first = plan[0]

    def collide(value):
        output = first.transform(value)
        old_id = output.value.id
        return replace(
            output,
            value=replace(output.value, id=snapshot.model.id),
            origins=replace(
                output.origins,
                links=tuple(
                    replace(link, generated_id=snapshot.model.id)
                    if link.generated_id == old_id
                    else link
                    for link in output.origins.links
                ),
            ),
        )

    with pytest.raises(TransformationError) as caught:
        execute_transformations(snapshot, (replace(first, transform=collide), *plan[1:]))
    assert caught.value.code == "TRANSFORM_ID_COLLISION"
