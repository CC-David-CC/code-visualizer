"""Admitted Python declarations preserve syntax semantics or explicit source holes."""

import ast

import pytest

from code_visualizer.domain.expression import UnparsedPythonExpression
from code_visualizer.domain.program import ProgramAction, ProgramModel, ProgramModule, ProgramNote
from code_visualizer.domain.project import Project
from code_visualizer.domain.python_declarations import parse_python_declarations
from code_visualizer.generation import BuildBlockedError, generate_python_project
from code_visualizer.persistence.decoding import program_model_from_data
from code_visualizer.persistence.serialization import program_model_to_data


def _project(source):
    declarations = parse_python_declarations("module:python", source, identity_namespace="fixed")
    return Project(
        "p",
        "Declaration fidelity",
        (),
        program_model=ProgramModel(
            modules=(ProgramModule("module:python", "main", declarations),),
        ),
    )


@pytest.mark.parametrize(
    "source",
    [
        "values = []  # type: list[int]\n",
        "def identity(value):  # type: (int) -> int\n    return value\n",
        "for value in []:  # type: int\n    print(value)\n",
        "with manager() as value:  # type: int\n    print(value)\n",
        '''"""Module documentation."""
from __future__ import annotations
type Values[T] = list[T]
@decorate
class Box[T: object](Base, metaclass=Meta):
    """Class documentation."""
    first = second = 1
    class Nested:
        value: int = 2
''',
    ],
)
def test_typing_comments_generic_definitions_and_declaration_order_survive_generation(source):
    project = _project(source)
    module = generate_python_project(project).file("app/main.py").source
    assert ast.dump(ast.parse(module, type_comments=True)) == ast.dump(
        ast.parse(source, type_comments=True)
    )
    assert (
        program_model_from_data(program_model_to_data(project.program_model))
        == project.program_model
    )
    assert not any(
        isinstance(item, ProgramNote) and item.text.startswith("type:")
        for item in project.program_model.modules[0].body
    )


@pytest.mark.parametrize(
    "source",
    [
        "value = missing  # type: ignore[name-defined]\n",
        "import missing  # type: ignore[import-not-found]\n",
        "class C:  # type: ignore[misc]\n    pass\n",
        "def function():  # type: ignore[no-untyped-def]\n    pass\n",
        "call(\n    missing,  # type: ignore[name-defined]\n)\n",
    ],
)
def test_unsupported_directive_anchors_remain_exact_explicit_values_and_block_generation(source):
    project = _project(source)
    body = project.program_model.modules[0].body
    assert len(body) == 1 and isinstance(body[0], ProgramAction)
    tree = body[0].source.tree
    assert isinstance(tree, UnparsedPythonExpression)
    assert tree.source == source
    assert "directive anchors" in tree.reason
    assert (
        program_model_from_data(program_model_to_data(project.program_model))
        == project.program_model
    )
    with pytest.raises(BuildBlockedError, match="PROGRAM_INCOMPLETE_EXPRESSION"):
        generate_python_project(project)


def test_invalid_typing_syntax_is_not_reparsed_with_a_more_permissive_parser():
    source = "# type: int\nvalue = 1\n"
    body = _project(source).program_model.modules[0].body
    assert len(body) == 1 and isinstance(body[0], ProgramAction)
    assert isinstance(body[0].source.tree, UnparsedPythonExpression)
    assert body[0].source.tree.source == source


def test_ordinary_comments_remain_notes_without_duplicating_ast_owned_type_comments():
    project = _project("# Explain the value.\nvalue = 1  # type: int\n# Next step.\n")
    notes = [
        item.text for item in project.program_model.modules[0].body if isinstance(item, ProgramNote)
    ]
    assert notes == ["Explain the value.", "Next step."]
