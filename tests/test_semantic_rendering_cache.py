"""Semantic indexing preserves Python labels when expression rendering is reused."""

from dataclasses import replace

import pytest

from code_visualizer.application.project_factory import (
    create_default_project,
    initialize_project_documents,
)
from code_visualizer.application.semantic_index import _Builder, build_semantic_program
from code_visualizer.domain.drakon import Action, DrakonDiagram
from code_visualizer.domain.expression import expression_node_label, render_expression_tree


@pytest.mark.parametrize(
    "source",
    [
        "value = 42",
        "'A module docstring'",
        "first = 1\nsecond = 2",
        "def nested():\n    'A function docstring'\n    return 42",
        "class Nested:\n    'A class docstring'\n    answer = 42",
        "if True:\n    value = 42",
        "try:\n    value = 1\nexcept Exception:\n    value = 2",
        "async def nested():\n    return 42",
        'f"Answer: {42}"',
        "values = (-0.0, 0.0, 1, 1.0, True, None, '1', 1j, b'1')",
        "",
    ],
)
def test_cached_index_matches_independent_expression_rendering(source, monkeypatch) -> None:
    project = create_default_project()
    document = project.documents[0]
    assert isinstance(document, DrakonDiagram)
    document = replace(
        document,
        body=replace(document.body, atoms=(Action("action", source), Action("copy", source))),
    )
    project = initialize_project_documents(project, (document,))
    cached = build_semantic_program(project)
    monkeypatch.setattr(
        _Builder, "_render_expression", lambda self, tree: render_expression_tree(tree)
    )
    monkeypatch.setattr(
        _Builder, "_expression_label", lambda self, tree: expression_node_label(tree)
    )
    assert cached == build_semantic_program(project)
