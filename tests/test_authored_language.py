"""A saved generic recipe supplies FSM behavior without its handwritten extension."""

from dataclasses import replace

import pytest

from code_visualizer.application.authored_examples import (
    authored_traffic_light_project as authored_traffic_light,
)
from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.domain_execution import trace_project
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.domain import language as l
from code_visualizer.domain.intentional import PropertyValue
from code_visualizer.domain.language_validation import validate_authored_language
from code_visualizer.domain.program import ProgramModel
from code_visualizer.domain.program_kinds import TransferKind
from code_visualizer.extensions.builtin import intentional_bundle, program_bundle
from code_visualizer.extensions.registry import DomainExtensionRegistry
from code_visualizer.generation.build import prepare_build, program_identities
from code_visualizer.generation.language import (
    EvaluationBudget,
    LanguageEvaluationError,
    compile_authored_transformation,
    evaluate_query,
    validate_authored_model,
)
from code_visualizer.generation.python import generate_python
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.serialization import normalized_project_json


def host_without_fsm():
    return DomainExtensionRegistry((program_bundle(), intentional_bundle()))


def test_authored_fsm_recipe_generates_and_traces_without_handwritten_domain_implementation():
    project = authored_traffic_light()
    schema, model = project.domain_workspace.schemas[0], project.domain_workspace.models[0]
    language = project.domain_workspace.language_definitions[0]
    assert not validate_authored_language(language, schema)
    assert not validate_authored_model(language, schema, model)
    before = normalized_project_json(project)
    reloaded = project_from_json(before)
    assert reloaded == project
    registry = host_without_fsm()
    build = prepare_build(reloaded, registry)
    assert build == prepare_build(reloaded, registry)
    assert build.transformations == ("recipe:lower@1",)
    assert program_identities(build.project.program_model) == {
        link.generated_id for link in build.origins.links
    }
    assert project.program_model == ProgramModel()
    kernel = ProjectKernel(ProjectAuthority(reloaded), extensions=registry)
    try:
        result = trace_project(kernel, model_id=model.id)
        assert result.run.return_code == 0, result.run.stderr
        assert result.run.stdout.splitlines() == [
            "Green",
            "The signal changes.",
            "Yellow",
            "The signal changes.",
            "Red",
            "The signal changes.",
        ]
        entrypoint = build.project.program_model.function(
            build.project.program_model.entrypoint_callable_id
        )
        assert entrypoint is not None
        assert any(
            event.event == "return"
            and event.function == entrypoint.identifier
            and event.detail == "'traffic:red'"
            for event in result.events
        )
        assert any(
            {"traffic:green-yellow", "traffic:yellow", "traffic:signal"} <= set(state.origin_ids)
            for state in kernel.runtime.history()
        )
        assert normalized_project_json(kernel.authority.snapshot()) == before
    finally:
        kernel.close()


def test_source_rename_preserves_generated_identity_and_saved_recipe_ownership():
    project = authored_traffic_light()
    model = project.domain_workspace.models[0]
    amber = replace(
        model.node("traffic:yellow"), properties=(PropertyValue("fsm:state:name", "Amber"),)
    )
    renamed = replace(
        project,
        domain_workspace=replace(
            project.domain_workspace,
            models=(
                replace(
                    model,
                    nodes=tuple(amber if node.id == amber.id else node for node in model.nodes),
                ),
            ),
        ),
    )
    registry = host_without_fsm()
    before, after = prepare_build(project, registry), prepare_build(renamed, registry)
    assert before.origins == after.origins
    assert program_identities(before.project.program_model) == program_identities(
        after.project.program_model
    )
    assert "Amber" in generate_python(renamed, extensions=registry).source
    assert "Yellow" not in generate_python(renamed, extensions=registry).source
    assert (
        project.domain_workspace.language_definitions
        == renamed.domain_workspace.language_definitions
    )


def test_authored_validator_rejects_ambiguous_transitions_without_discarding_source():
    project = authored_traffic_light()
    schema, model = project.domain_workspace.schemas[0], project.domain_workspace.models[0]
    duplicate = replace(model.node("traffic:red-green"), id="traffic:duplicate")
    machine = model.node("traffic:machine")
    updated_machine = replace(
        machine,
        children=tuple(
            replace(binding, node_ids=(*binding.node_ids, duplicate.id))
            if binding.role_id == "fsm:machine:transitions"
            else binding
            for binding in machine.children
        ),
    )
    model = replace(
        model,
        nodes=(
            *(updated_machine if node.id == machine.id else node for node in model.nodes),
            duplicate,
        ),
    )
    issues = validate_authored_model(
        project.domain_workspace.language_definitions[0], schema, model
    )
    assert any(
        issue.code == "AUTHORED_UNIQUE_TRANSITION" and issue.object_id == machine.id
        for issue in issues
    )


def test_queries_are_typed_short_circuited_and_bounded():
    project = authored_traffic_light()
    schema, model = project.domain_workspace.schemas[0], project.domain_workspace.models[0]
    expression = l.QueryBinary(
        "and",
        l.QueryBinaryOperator.AND,
        l.QueryLiteral("false", False),
        l.QueryUnary("empty-first", l.QueryUnaryOperator.FIRST, l.QueryTuple("empty")),
    )
    assert evaluate_query(expression, schema, model) is False
    assert (
        evaluate_query(
            l.QueryBinary(
                "equal",
                l.QueryBinaryOperator.EQUAL,
                l.QueryLiteral("bool", True),
                l.QueryLiteral("number", 1),
            ),
            schema,
            model,
        )
        is False
    )
    with pytest.raises(LanguageEvaluationError, match="operation budget"):
        evaluate_query(expression, schema, model, budget=EvaluationBudget(steps=1))
    with pytest.raises(LanguageEvaluationError, match="size budget"):
        evaluate_query(
            l.QueryNodes("states", "fsm:state"),
            schema,
            model,
            budget=EvaluationBudget(max_collection=1),
        )


@pytest.mark.parametrize(
    "predicate,code",
    [
        (l.QueryHole("hole"), "LANGUAGE_HOLE"),
        (
            l.QueryProperty("bad-property", l.QueryVariable("self", "machine"), "absent"),
            "LANGUAGE_PROPERTY",
        ),
        (l.QueryVariable("unbound", "absent"), "LANGUAGE_BINDING"),
        (l.QueryLiteral("not-boolean", "yes"), "LANGUAGE_TYPE"),
    ],
)
def test_invalid_validator_paths_types_and_explicit_holes_have_diagnostics(predicate, code):
    project = authored_traffic_light()
    schema = project.domain_workspace.schemas[0]
    language = l.AuthoredDomainLanguage(
        "invalid",
        schema.id,
        schema.version,
        validators=(
            l.ValidatorDefinition("validator", "fsm:machine", "machine", predicate, "Invalid"),
        ),
    )
    issues = validate_authored_language(language, schema)
    assert code in {issue.code for issue in issues}
    if code == "LANGUAGE_HOLE":
        assert all(issue.incomplete for issue in issues)


def test_runtime_template_cannot_use_undeclared_symbols_or_continue_outside_runtime_loop():
    project = authored_traffic_light()
    schema = project.domain_workspace.schemas[0]
    language = project.domain_workspace.language_definitions[0]
    recipe = language.transformations[0]
    broken = replace(
        recipe.functions[0],
        body=(
            l.TemplateOutput("unknown-output", l.RuntimeVariable("unknown", "absent")),
            l.TemplateTransfer("outside-loop", TransferKind.CONTINUE),
        ),
    )
    recipe = replace(recipe, functions=(broken,))
    language = replace(language, transformations=(recipe,))
    assert {"LANGUAGE_SYMBOL", "LANGUAGE_CONTROL"} <= {
        issue.code for issue in validate_authored_language(language, schema)
    }
    with pytest.raises(LanguageEvaluationError):
        compile_authored_transformation(language, schema, recipe)


def test_domain_text_is_emitted_as_literal_data_and_cannot_inject_transform_code():
    project = authored_traffic_light()
    model = project.domain_workspace.models[0]
    text = "'); __import__('os').system('echo UNSAFE'); #"
    action = replace(
        model.node("traffic:signal"),
        properties=(
            PropertyValue("fsm:action:name", "Quoted message"),
            PropertyValue("fsm:action:message", text),
        ),
    )
    project = replace(
        project,
        domain_workspace=replace(
            project.domain_workspace,
            models=(
                replace(
                    model,
                    nodes=tuple(action if node.id == action.id else node for node in model.nodes),
                ),
            ),
        ),
    )
    kernel = ProjectKernel(ProjectAuthority(project), extensions=host_without_fsm())
    try:
        result = trace_project(kernel, model_id=model.id)
        assert result.run.return_code == 0
        assert result.run.stdout.splitlines().count(text) == 3
        assert "UNSAFE" not in {line for line in result.run.stdout.splitlines() if line != text}
    finally:
        kernel.close()
