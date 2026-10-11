from dataclasses import fields, is_dataclass, replace

import pytest

from code_visualizer.application.authored_examples import authored_traffic_light_project
from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.language_commands import (
    PutDomainTransformation,
    PutDomainValidator,
)
from code_visualizer.application.language_expression import (
    QueryExpressionBinding,
    QueryExpressionError,
    format_query_expression,
    infer_query_concepts,
    infer_query_type,
    parse_query_expression,
)
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.domain import language as l
from code_visualizer.domain.language_structure import language_owned_ids
from code_visualizer.execution.runner import run_project
from code_visualizer.extensions.builtin import intentional_bundle, program_bundle
from code_visualizer.extensions.registry import DomainExtensionRegistry
from code_visualizer.generation.build import prepare_build
from code_visualizer.generation.python import generate_python_project
from code_visualizer.generation.transformation import TransformationError
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.serialization import normalized_project_json
from code_visualizer.sdk import CodeVisualizerClient


def _context():
    project = authored_traffic_light_project()
    return project.domain_workspace.schemas[0], (
        QueryExpressionBinding("rule:machine", "machine", ("fsm:machine",)),
    )


def test_existing_validator_formats_readably_and_roundtrips_all_ids():
    project = authored_traffic_light_project()
    schema, bindings = _context()
    query = project.domain_workspace.language_definitions[0].validators[0].predicate
    text = format_query_expression(query, schema, bindings)
    assert "machine.Transitions" in text
    assert "identity(first(transition.Source))" in text
    assert "QueryBinary" not in text and "fsm:transition:source" not in text
    assert parse_query_expression(text, schema, bindings, query) == query


@pytest.mark.parametrize(
    "text",
    [
        "count(machine.States) >= 3 and not (first(machine.Initial).Name == 'Amber')",
        "every(machine.Transitions, 't', first(t.Source) in machine.States)",
        "map(where(machine.States, 's', s.Name != 'Red'), 'other', other.Name)",
        "unique(machine.Transitions, 't', [identity(first(t.Source)), identity(first(t.Event))])",
        "prop(machine, 'Event cycles') + 1",
        "nodes('State', roots=False)",
        "[True, None, -2, 1.25, 'text']",
        "hole('Choose condition')",
    ],
)
def test_query_grammar_roundtrips_the_same_typed_ast(text):
    schema, bindings = _context()
    query = parse_query_expression(text, schema, bindings)
    assert (
        parse_query_expression(
            format_query_expression(query, schema, bindings), schema, bindings, query
        )
        == query
    )


def test_query_type_inference_supplies_nested_editor_binding_shapes():
    schema, bindings = _context()
    query = parse_query_expression("machine.Transitions", schema, bindings)
    assert infer_query_concepts(query, schema, bindings) == ("fsm:transition",)
    shape = infer_query_type(query, schema, bindings)
    inner = (QueryExpressionBinding("local", "transition", value_type=shape.element),)
    assert (
        infer_query_type(
            parse_query_expression("first(transition.Source).Name", schema, inner), schema, inner
        ).kind
        == "string"
    )


@pytest.mark.parametrize(
    "text",
    [
        "__import__('os')",
        "open('file')",
        "machine.__class__",
        "machine.States[0]",
        "[s.Name for s in machine.States]",
        "lambda: 1",
        "machine.Name * 10000",
        "machine.Name < 42",
        "count(machine)",
        "machine.Unknown",
        "unknown.Name",
        "every(machine.States, 'machine', True)",
        "first(*[machine.States])",
        "nodes('State', roots='yes')",
        "nodes('Missing')",
        "1 < 2 < 3",
        "1e999",
    ],
)
def test_executable_unsupported_or_ill_typed_expressions_are_rejected(text):
    schema, bindings = _context()
    with pytest.raises(QueryExpressionError):
        parse_query_expression(text, schema, bindings)


def test_validator_expression_edit_changes_behavior_under_one_authority_and_undo():
    project = authored_traffic_light_project()
    language = project.domain_workspace.language_definitions[0]
    schema, bindings = _context()
    previous = language.validators[0]
    changed = replace(
        previous,
        predicate=parse_query_expression(
            "count(machine.States) >= 4", schema, bindings, previous.predicate
        ),
    )
    host = DomainExtensionRegistry((program_bundle(), intentional_bundle()))
    client = CodeVisualizerClient(ProjectAuthority(project), actor_id="query-editor")
    try:
        assert isinstance(client.submit(PutDomainValidator(language.id, changed)), CommandAccepted)
        with pytest.raises(TransformationError) as caught:
            prepare_build(client.snapshot(), host)
        assert caught.value.code == previous.code
        assert project_from_json(normalized_project_json(client.snapshot())) == client.snapshot()
        assert isinstance(client.undo(), CommandAccepted)
        assert prepare_build(client.snapshot(), host).project.program_model.functions
        assert isinstance(client.redo(), CommandAccepted)
        assert client.snapshot().domain_workspace.language(language.id).validators[0] == changed
    finally:
        client.close()


def _map_records(value, change):
    if isinstance(value, tuple):
        return tuple(_map_records(item, change) for item in value)
    if is_dataclass(value):
        changed = change(value)
        if changed is not value:
            return changed
        return replace(
            value,
            **{
                field.name: _map_records(getattr(value, field.name), change)
                for field in fields(value)
            },
        )
    return value


def test_transform_query_expression_changes_actual_program_behavior_without_source_text_store():
    project = authored_traffic_light_project()
    schema = project.domain_workspace.schemas[0]
    language = project.domain_workspace.language_definitions[0]
    recipe = language.transformations[0]
    edited = []

    def change(value):
        if isinstance(value, l.QueryProperty) and value.property_id == "fsm:machine:steps":
            bindings = (
                QueryExpressionBinding(value.source.binding_id, "machine", ("fsm:machine",)),
            )
            result = parse_query_expression(
                "prop(machine, 'Event cycles') + 1", schema, bindings, value
            )
            edited.append(result)
            return result
        return value

    changed = _map_records(recipe, change)
    assert len(edited) == 1
    client = CodeVisualizerClient(ProjectAuthority(project), actor_id="query-editor")
    host = DomainExtensionRegistry((program_bundle(), intentional_bundle()))
    try:
        assert isinstance(
            client.submit(PutDomainTransformation(language.id, changed)), CommandAccepted
        )
        current = client.snapshot()
        generated = generate_python_project(current, extensions=host)
        result = run_project(generated)
        assert result.return_code == 0, result.stderr
        assert result.stdout.count("The signal changes.") == 4
        persisted = normalized_project_json(current)
        assert "prop(machine, 'Event cycles')" not in persisted
        assert project_from_json(persisted) == current
        assert isinstance(client.undo(), CommandAccepted)
        generated = generate_python_project(client.snapshot(), extensions=host)
        result = run_project(generated)
        assert result.stdout.count("The signal changes.") == 3
    finally:
        client.close()


def test_small_expression_edit_keeps_existing_identity_and_holes_remain_saveable():
    schema, bindings = _context()
    before = parse_query_expression("count(machine.States) >= 3", schema, bindings)
    after = parse_query_expression("count(machine.States) >= 4", schema, bindings, before)

    def identities(query):
        return language_owned_ids(
            l.AuthoredDomainLanguage(
                "language",
                schema.id,
                schema.version,
                validators=(
                    l.ValidatorDefinition("rule", "fsm:machine", "rule:machine", query, "Rule"),
                ),
            )
        )

    assert identities(after) == identities(before)
    assert parse_query_expression("hole('Finish later')", schema, bindings).label == "Finish later"
    project = authored_traffic_light_project()
    language = project.domain_workspace.language_definitions[0]
    rule = language.validators[0]
    hole = replace(rule, predicate=parse_query_expression("hole('Finish later')", schema, bindings))
    client = CodeVisualizerClient(ProjectAuthority(project), actor_id="query-editor")
    try:
        assert isinstance(client.submit(PutDomainValidator(language.id, hole)), CommandAccepted)
        assert project_from_json(normalized_project_json(client.snapshot())) == client.snapshot()
        with pytest.raises(TransformationError) as caught:
            prepare_build(client.snapshot())
        assert caught.value.code == "LANGUAGE_HOLE"
    finally:
        client.close()


def test_flat_boolean_input_cannot_expand_past_the_canonical_depth_budget():
    schema, bindings = _context()
    with pytest.raises(QueryExpressionError, match="budget"):
        parse_query_expression(" and ".join("True" for _ in range(2000)), schema, bindings)
