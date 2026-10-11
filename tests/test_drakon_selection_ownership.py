from dataclasses import replace

from code_visualizer.domain.drakon import (
    Action,
    Case,
    If,
    Select,
    Sequence,
    create_empty_drakon,
)
from code_visualizer.domain.drakon_selection import selection_objects, selection_ownership


def test_nested_case_owns_descendants_and_sequences_but_never_siblings_or_ancestors():
    leaf = Action("nested_action", "print(1)")
    nested = If("nested_if", "True", Sequence("true_body", (leaf,)), Sequence("false_body"))
    first = Case("first_case", "First", Sequence("first_body", (nested,)))
    second = Case("default_case", "Otherwise", Sequence("default_body"), is_default=True)
    select = Select("select", cases=(first, second))
    final = Action("final", "print(2)")
    diagram = replace(create_empty_drakon(), body=Sequence("body", (select, final)))

    assert set(selection_ownership(diagram, select.id)) == {
        "select",
        "first_case",
        "first_body",
        "nested_if",
        "true_body",
        "false_body",
        "nested_action",
        "default_case",
        "default_body",
    }
    assert set(selection_ownership(diagram, first.id)) == {
        "first_case",
        "first_body",
        "nested_if",
        "true_body",
        "false_body",
        "nested_action",
    }
    assert selection_ownership(diagram, leaf.id) == (leaf.id,)
    assert set(selection_ownership(diagram, diagram.header.id)) == {
        diagram.header.id,
        "body",
        *selection_ownership(diagram, select.id),
        final.id,
    }
    selectable = {item.id for item in selection_objects(diagram)}
    assert selectable == {
        diagram.header.id,
        "select",
        "first_case",
        "default_case",
        "nested_if",
        "nested_action",
        "final",
    }
    for identity in (
        diagram.end.id,
        "body",
        "first_body",
        "first_body:insertion",
        "select:end",
        "default_case:address",
        "unknown",
    ):
        assert selection_ownership(diagram, identity) == ()
