from dataclasses import replace

import pytest
from test_composed_notations import composed_project

from code_visualizer.application.authored_examples import authored_traffic_light_project
from code_visualizer.application.notation_canvas import compile_notation_canvas
from code_visualizer.application.notation_expression import (
    NotationExpressionError,
    format_notation_expression,
    parse_notation_expression,
)
from code_visualizer.domain import notation_syntax as v
from code_visualizer.domain.intentional import DomainWorkspace
from code_visualizer.domain.language import AuthoredDomainLanguage
from code_visualizer.domain.language_structure import language_owned_ids
from code_visualizer.domain.notation import NotationDefinition, NotationKind


def test_readable_cross_domain_notation_roundtrips_the_same_typed_identities():
    project, definition = composed_project()
    schema = project.domain_workspace.schemas[0]
    expression = format_notation_expression(definition.body, schema, project.domain_workspace)
    assert "Sensor" in expression and "Reading" in expression and "Summary" in expression
    assert "sensor.reading" not in expression
    parsed = parse_notation_expression(
        expression, schema, project.domain_workspace, definition.body
    )
    assert parsed == definition.body
    assert compile_notation_canvas(
        project, "observations", replace(definition, body=parsed)
    ) == compile_notation_canvas(project, "observations", definition)


def test_expression_changes_preserve_all_unaffected_syntax_and_binding_ids():
    project, _ = composed_project()
    schema = project.domain_workspace.schemas[0]
    before = parse_notation_expression(
        "each('Sensor', 'sensor', row(field('sensor', 'Name'), text('m/s')))", schema
    )
    after = parse_notation_expression(
        "each('Sensor', 'reading', row(field('reading', 'Name'), text('m/s²')))",
        schema,
        existing=before,
    )

    def identities(body):
        return language_owned_ids(
            AuthoredDomainLanguage(
                "l",
                schema.id,
                schema.version,
                notations=(NotationDefinition("n", "N", NotationKind.COMPOSED, body=body),),
            )
        )

    assert identities(before) == identities(after)
    assert before.binding_id == after.binding_id
    assert before.body.children[0].binding_id == after.body.children[0].binding_id
    assert after.body.children[1].text == "m/s²"


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os')",
        "text(open('x').read())",
        "text('x' * 1000)",
        "text(*['x'])",
        "text('x', **{})",
        "text('x', unexpected=True)",
        "field('missing', 'Name')",
        "each('Missing', 'm', text('x'))",
        "each('Sensor', 's', field('s', 'Missing'))",
        "text('x', font_size=True)",
        "each('Sensor', 's', each('Sensor', 's', text('x')))",
    ],
)
def test_unknown_code_members_and_scopes_are_rejected(expression):
    project, _ = composed_project()
    with pytest.raises((NotationExpressionError, ValueError)):
        parse_notation_expression(expression, project.domain_workspace.schemas[0])


def test_workspace_schema_names_resolve_exact_versions_and_reject_ambiguity():
    project, definition = composed_project()
    schema = project.domain_workspace.schemas[0]
    text = (
        "each('Requirement', 'r', field('r', 'Summary'), scope='workspace', "
        "schema='example.requirements', version='3')"
    )
    parsed = parse_notation_expression(text, schema, project.domain_workspace)
    assert parsed.query.schema_id == "requirements"
    assert parsed.query.schema_version == "3"
    canvas = compile_notation_canvas(project, "observations", replace(definition, body=parsed))
    assert canvas.items[0].edit.model_id == "safety"
    assert (
        parse_notation_expression(
            format_notation_expression(parsed, schema, project.domain_workspace),
            schema,
            project.domain_workspace,
            parsed,
        )
        == parsed
    )
    duplicate = replace(project.domain_workspace.schemas[1], id="ambiguous")
    workspace = DomainWorkspace((*project.domain_workspace.schemas, duplicate))
    with pytest.raises(NotationExpressionError, match="ambiguous"):
        parse_notation_expression(text, schema, workspace)


def test_math_coordinates_paths_and_conditions_roundtrip_without_losing_options():
    project, _ = composed_project()
    schema = project.domain_workspace.schemas[0]
    text = """each('Sensor', 's', positioned(
      at(number('s', 'Reading', scale=10, offset=3), -20,
        box(fraction(field('s', 'Reading'), superscript(text('s'), text('2'))),
          width=120, height=number('s', 'Reading', scale=2), shape='ellipse')),
      when('s', 'Reading', 'greater', 9, text('high'), otherwise=text('low')),
      path(point(1, 2), point(10, 12), closed=True, fill='red')
    ))"""
    parsed = parse_notation_expression(text, schema)
    formatted = format_notation_expression(parsed, schema)
    assert parse_notation_expression(formatted, schema, existing=parsed) == parsed
    assert parsed.body.children[0].x.property_id == "sensor.reading"


def test_holes_are_editable_and_excessive_input_fails_before_compilation():
    project, _ = composed_project()
    schema = project.domain_workspace.schemas[0]
    value = parse_notation_expression("repeat_hole('x', hole('Choose body'))", schema)
    assert isinstance(value.body, v.VisualHole)
    assert (
        parse_notation_expression(format_notation_expression(value, schema), schema, existing=value)
        == value
    )
    with pytest.raises(NotationExpressionError, match="budget"):
        parse_notation_expression(" " * 100_001, schema)


def test_incoming_roles_and_reference_field_paths_resolve_by_name():
    project = authored_traffic_light_project()
    schema = project.domain_workspace.schemas[0]
    expression = """each('State', 's', related('s', '', 't',
        row(field('t', 'Name', through='Source'), text('→'), field('s', 'Name')),
        role='Target', incoming=True))"""
    parsed = parse_notation_expression(expression, schema, project.domain_workspace)
    assert parsed.body.query.role_id == "fsm:transition:target"
    assert parsed.body.body.children[0].reference_role_ids == ("fsm:transition:source",)
    formatted = format_notation_expression(parsed, schema, project.domain_workspace)
    assert parse_notation_expression(formatted, schema, project.domain_workspace, parsed) == parsed


def test_numeric_property_type_and_reference_role_kind_are_checked():
    project = authored_traffic_light_project()
    schema = project.domain_workspace.schemas[0]
    with pytest.raises(NotationExpressionError):
        parse_notation_expression(
            "each('State', 's', at(number('s', 'Name'), 0, text('x')))", schema
        )
    with pytest.raises(NotationExpressionError):
        parse_notation_expression(
            "each('State machine', 'm', field('m', 'Name', through='States'))", schema
        )
