from dataclasses import replace

import pytest

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.notations import (
    NotationEditKind,
    compile_notation,
    fallback_notations,
    field_cell,
    notation_edit_command,
)
from code_visualizer.domain.intentional import (
    ConceptDefinition,
    DomainModel,
    DomainSchema,
    DomainWorkspace,
    IntentionalNode,
    PropertyDefinition,
    PropertyValue,
    RoleBinding,
    RoleDefinition,
)
from code_visualizer.domain.notation import (
    NotationColumn,
    NotationDefinition,
    NotationEdgeRule,
    NotationField,
    NotationKind,
    NotationNodeRule,
)
from code_visualizer.domain.project import Project
from code_visualizer.extensions.registry import DomainExtensionBundle, DomainExtensionRegistry
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.serialization import normalized_project_json
from code_visualizer.sdk import CodeVisualizerClient


def _library():
    schema = DomainSchema(
        "library",
        "example.library",
        "1",
        (
            ConceptDefinition(
                "book",
                "Book",
                (PropertyDefinition("book.title", "Title"),),
                display_property_id="book.title",
            ),
            ConceptDefinition(
                "citation",
                "Citation",
                reference_roles=(
                    RoleDefinition("citation.from", "From", ("book",), max_count=1),
                    RoleDefinition("citation.to", "To", ("book",), max_count=1),
                ),
            ),
        ),
    )
    first = IntentionalNode("book:a", "book", (PropertyValue("book.title", "First book"),))
    second = IntentionalNode("book:b", "book", (PropertyValue("book.title", "Second book"),))
    citation = IntentionalNode(
        "citation:1",
        "citation",
        references=(
            RoleBinding("citation.from", (first.id,)),
            RoleBinding("citation.to", (second.id,)),
        ),
    )
    model = DomainModel(
        "reading",
        schema.id,
        "1",
        (first.id, second.id, citation.id),
        (first, second, citation),
        "Reading list",
    )
    graph = NotationDefinition(
        "library.graph",
        "Citation graph",
        NotationKind.GRAPH,
        node_rules=(NotationNodeRule("book", "book.title"),),
        edge_rules=(NotationEdgeRule("citation", "citation.from", "citation.to"),),
        schema_id=schema.id,
    )
    table = NotationDefinition(
        "library.table",
        "Citations",
        NotationKind.TABLE,
        concept_ids=("citation",),
        columns=(
            NotationColumn("from", "From book", NotationField("book.title", ("citation.from",))),
            NotationColumn("to", "To book", NotationField("book.title", ("citation.to",))),
        ),
        schema_id=schema.id,
    )
    project = Project(
        "library-project", "Library", (), domain_workspace=DomainWorkspace((schema,), (model,))
    )
    return project, schema, model, graph, table


def test_reference_path_cell_renames_canonical_target_and_round_trips_without_views():
    project, schema, model, graph, table = _library()
    authority = ProjectAuthority(project)
    client = CodeVisualizerClient(authority, actor_id="notation-test")
    registry = DomainExtensionRegistry(
        (DomainExtensionBundle("library", "1", notations=(graph, table)),)
    )
    kernel = ProjectKernel(authority, extensions=registry)
    try:
        view = compile_notation(project.id, 0, schema, model, table)
        cell = view.rows[0].cells[0]
        assert cell.semantic_id == "book:a"
        assert cell.edit is not None
        assert cell.edit.node_id == "book:a"
        assert isinstance(
            client.submit(notation_edit_command(cell.edit, "Revised title", revision=0)),
            CommandAccepted,
        )
        updated = client.snapshot()
        changed = updated.domain_workspace.model(model.id)
        assert changed is not None
        assert changed.node("citation:1").references == model.node("citation:1").references
        assert kernel.notation(model.id, graph.id).graph.nodes[0].label == "Revised title"
        assert kernel.notation(model.id, table.id).rows[0].cells[0].text == "Revised title"
        assert (
            project_from_json(normalized_project_json(updated)).domain_workspace
            == updated.domain_workspace
        )
        assert isinstance(client.undo(), CommandAccepted)
        assert client.snapshot().domain_workspace == project.domain_workspace
        assert isinstance(client.redo(), CommandAccepted)
        assert client.snapshot().domain_workspace == updated.domain_workspace
    finally:
        kernel.close()
        client.close()


def test_reference_terminal_rebinds_identity_and_stale_or_ambiguous_edits_do_not_guess():
    _project, schema, model, _, table = _library()
    citation = model.node("citation:1")
    assert citation is not None
    terminal = field_cell(
        schema,
        model,
        citation,
        NotationField(reference_role_ids=("citation.to",)),
        cell_id="target-cell",
        revision=4,
    )
    assert terminal.edit is not None
    assert terminal.edit.kind is NotationEditKind.REFERENCE
    assert terminal.target_ids == ("book:b",)
    command = notation_edit_command(terminal.edit, ("book:a",), revision=4)
    assert command.to_operation().payload["target_ids"] == ["book:a"]
    with pytest.raises(ValueError, match="changed"):
        notation_edit_command(terminal.edit, ("book:a",), revision=5)
    ambiguous = replace(citation, references=(RoleBinding("citation.from", ("book:a", "book:b")),))
    cell = field_cell(
        schema, model, ambiguous, table.columns[0].field, cell_id="ambiguous", revision=0
    )
    assert cell.edit is None
    assert "First book" in cell.text and "Second book" in cell.text


def test_generic_graph_identity_runtime_and_fallbacks_have_no_domain_specific_rules():
    project, schema, model, graph, _ = _library()
    result = compile_notation(
        project.id,
        0,
        schema,
        model,
        graph,
        active_node_ids=("book:b", "citation:1"),
        runtime_revision=0,
    )
    assert {node.id for node in result.graph.nodes} == {"book:a", "book:b"}
    assert result.graph.edges[0].id == "citation:1"
    assert result.graph.edges[0].active
    assert "active" in next(node for node in result.graph.nodes if node.id == "book:b").badges
    assert {value.kind for value in fallback_notations(schema)} == {
        NotationKind.GRAPH,
        NotationKind.TABLE,
        NotationKind.TREE_FORM,
    }
    stale = compile_notation(
        project.id, 1, schema, model, graph, active_node_ids=("book:b",), runtime_revision=0
    )
    assert "runtime stale" in next(node for node in stale.graph.nodes if node.id == "book:b").badges


def test_unsafe_notation_model_scope_is_rejected():
    project, schema, model, graph, _ = _library()
    with pytest.raises(ValueError, match="same domain"):
        compile_notation(project.id, 0, schema, model, replace(graph, schema_id="somewhere-else"))
