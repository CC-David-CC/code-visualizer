"""Signature edits retain existing identities and reconcile Python locals."""

from dataclasses import replace

import pytest

from code_visualizer.application.commands import CreateDiagram, DuplicateDiagram
from code_visualizer.application.messages import CommandAccepted, CommandEnvelope, CommandRejected
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.common import DocumentKind
from code_visualizer.domain.drakon import Assignment, DrakonDiagram
from code_visualizer.domain.expression import SymbolReferenceExpression
from code_visualizer.domain.program import ProgramAssignment, ProgramSymbolKind
from code_visualizer.domain.program_signatures import ParameterSpec


def test_prepending_parameter_preserves_existing_parameter_identities() -> None:
    session = ProjectSession.new()
    try:
        diagram = session.authority.snapshot().documents[0]
        assert isinstance(diagram, DrakonDiagram)
        spec = replace(
            diagram.header.function,
            parameters=(ParameterSpec("a"), ParameterSpec("b")),
        )
        assert isinstance(session.client.replace_function_spec(diagram.id, spec), CommandAccepted)
        before = session.authority.snapshot().program_model.functions[0]
        previous = {item.name: (item.id, item.symbol_id) for item in before.parameters}
        expanded = replace(spec, parameters=(ParameterSpec("x"), *spec.parameters))
        assert isinstance(
            session.client.replace_function_spec(diagram.id, expanded), CommandAccepted
        )
        after = session.authority.snapshot().program_model.functions[0]
        assert len({item.id for item in after.parameters}) == 3
        assert len({item.symbol_id for item in after.parameters}) == 3
        for item in after.parameters[1:]:
            assert (item.id, item.symbol_id) == previous[item.name]
    finally:
        session.close()


def test_removing_parameter_reconciles_surviving_local_assignment() -> None:
    session = ProjectSession.new()
    try:
        diagram = session.authority.snapshot().documents[0]
        assert isinstance(diagram, DrakonDiagram)
        spec = replace(diagram.header.function, parameters=(ParameterSpec("value"),))
        assert isinstance(session.client.replace_function_spec(diagram.id, spec), CommandAccepted)
        assert isinstance(
            session.client.insert_drakon_atom(
                diagram.id, "assignment", 0, target="value", value="1"
            ),
            CommandAccepted,
        )
        before = session.authority.snapshot().program_model
        assert isinstance(
            session.client.replace_function_spec(diagram.id, replace(spec, parameters=())),
            CommandAccepted,
        )
        after = session.authority.snapshot().program_model
        local = next(
            item
            for item in after.symbols
            if item.kind is ProgramSymbolKind.LOCAL and item.name == "value"
        )
        assignment = after.functions[0].body.statements[0]
        assert isinstance(assignment, ProgramAssignment)
        assert isinstance(assignment.target.tree, SymbolReferenceExpression)
        assert assignment.target.tree.symbol_id == local.id
        assert assignment.written_symbol_ids == (local.id,)
        assert isinstance(session.client.undo(), CommandAccepted)
        assert session.authority.snapshot().program_model == before
        assert isinstance(session.client.redo(), CommandAccepted)
        assert session.authority.snapshot().program_model == after
    finally:
        session.close()


def test_parameter_replaces_same_name_local_binding() -> None:
    session = ProjectSession.new()
    try:
        diagram = session.authority.snapshot().documents[0]
        assert isinstance(diagram, DrakonDiagram)
        assert isinstance(
            session.client.insert_drakon_atom(
                diagram.id, "assignment", 0, target="value", value="1"
            ),
            CommandAccepted,
        )
        spec = replace(diagram.header.function, parameters=(ParameterSpec("value"),))
        assert isinstance(session.client.replace_function_spec(diagram.id, spec), CommandAccepted)
        model = session.authority.snapshot().program_model
        declarations = tuple(
            item for item in model.symbols if item.owner_id == diagram.id and item.name == "value"
        )
        assert len(declarations) == 1
        assert declarations[0].kind is ProgramSymbolKind.PARAMETER
        assignment = model.functions[0].body.statements[0]
        assert isinstance(assignment, ProgramAssignment)
        assert assignment.written_symbol_ids == (declarations[0].id,)
    finally:
        session.close()


def test_prepend_tuple_target_preserves_surviving_local_identities() -> None:
    session = ProjectSession.new()
    try:
        diagram = session.authority.snapshot().documents[0]
        assert isinstance(diagram, DrakonDiagram)
        assert isinstance(
            session.client.insert_drakon_atom(
                diagram.id, "assignment", 0, target="a, b", value="(1, 2)"
            ),
            CommandAccepted,
        )
        before = session.authority.snapshot().program_model
        previous = {item.name: item.id for item in before.symbols}
        statement = before.functions[0].body.statements[0]
        assert isinstance(
            session.client.replace_drakon_atom(
                diagram.id, Assignment(statement.id, "c, a, b", "(3, 1, 2)")
            ),
            CommandAccepted,
        )
        after = session.authority.snapshot().program_model
        current = {item.name: item.id for item in after.symbols}
        assert current["a"] == previous["a"]
        assert current["b"] == previous["b"]
        assert current["c"] not in previous.values()
    finally:
        session.close()


def test_tuple_target_rename_does_not_reuse_surviving_symbol_identity() -> None:
    session = ProjectSession.new()
    try:
        diagram = session.authority.snapshot().documents[0]
        assert isinstance(diagram, DrakonDiagram)
        assert isinstance(
            session.client.insert_drakon_atom(
                diagram.id, "assignment", 0, target="a, b", value="(1, 2)"
            ),
            CommandAccepted,
        )
        before = session.authority.snapshot().program_model
        previous = {item.name: item.id for item in before.symbols}
        statement = before.functions[0].body.statements[0]
        assert isinstance(
            session.client.set_drakon_text(diagram.id, statement.id, "target", "c, a"),
            CommandAccepted,
        )
        after = session.authority.snapshot().program_model
        current = {item.name: item.id for item in after.symbols}
        assert current["a"] == previous["a"]
        assert current["c"] != current["a"]
    finally:
        session.close()


@pytest.mark.parametrize("duplicate", [False, True])
def test_new_drakon_function_undo_redo_restores_exact_semantics(duplicate: bool) -> None:
    session = ProjectSession.new()
    try:
        before = session.authority.snapshot()
        result = (
            session.client.duplicate_diagram(before.documents[0].id, title="Copy")
            if duplicate
            else session.client.create_diagram(DocumentKind.DRAKON, "Extra", identifier="extra")
        )
        assert isinstance(result, CommandAccepted)
        after = session.authority.snapshot()
        assert len(after.program_model.functions) == len(before.program_model.functions) + 1
        assert isinstance(session.client.undo(), CommandAccepted)
        undone = session.authority.snapshot()
        assert undone.program_model == before.program_model
        assert undone.drakon_views == before.drakon_views
        assert undone.documents == before.documents
        assert isinstance(session.client.redo(), CommandAccepted)
        redone = session.authority.snapshot()
        assert redone.program_model == after.program_model
        assert redone.drakon_views == after.drakon_views
        assert redone.documents == after.documents
    finally:
        session.close()


def test_deleting_first_write_keeps_later_local_binding_and_exact_history() -> None:
    session = ProjectSession.new()
    try:
        diagram = session.authority.snapshot().documents[0]
        assert isinstance(diagram, DrakonDiagram)
        for index in range(2):
            assert isinstance(
                session.client.insert_drakon_atom(
                    diagram.id, "assignment", index, target="value", value=str(index)
                ),
                CommandAccepted,
            )
        before = session.authority.snapshot().program_model
        function = before.functions[0]
        local = next(
            item
            for item in before.symbols
            if item.kind is ProgramSymbolKind.LOCAL and item.name == "value"
        )
        assert isinstance(
            session.client.delete_program_statements(
                function.id, function.body.id, (function.body.statements[0].id,)
            ),
            CommandAccepted,
        )
        after = session.authority.snapshot().program_model
        surviving = after.symbol(local.id)
        assert surviving is not None
        assert surviving.declaration_id == function.body.statements[1].id
        assignment = after.functions[0].body.statements[0]
        assert isinstance(assignment, ProgramAssignment)
        assert assignment.written_symbol_ids == (local.id,)
        assert isinstance(session.client.undo(), CommandAccepted)
        assert session.authority.snapshot().program_model == before
        assert isinstance(session.client.redo(), CommandAccepted)
        assert session.authority.snapshot().program_model == after
    finally:
        session.close()


@pytest.mark.parametrize("duplicate", [False, True])
def test_new_diagram_cannot_overwrite_function_after_its_view_is_deleted(duplicate: bool) -> None:
    session = ProjectSession.new()
    try:
        original_id = session.authority.snapshot().documents[0].id
        assert isinstance(
            session.client.create_diagram(DocumentKind.DRAKON, "Source", identifier="source"),
            CommandAccepted,
        )
        snapshot = session.authority.snapshot()
        assert isinstance(
            session.authority.execute(
                CommandEnvelope(
                    command_type="diagram.delete",
                    actor_id=session.client.actor_id,
                    operation_id="delete-original-view",
                    project_id=snapshot.id,
                    expected_revision=snapshot.revision,
                    payload={"diagram_id": original_id},
                )
            ),
            CommandAccepted,
        )
        before = session.authority.snapshot()
        command = (
            DuplicateDiagram(before.documents[0].id, document_id=original_id)
            if duplicate
            else CreateDiagram(DocumentKind.DRAKON, "Replacement", document_id=original_id)
        )
        result = session.client.submit(command, expected_revision=before.revision)
        assert isinstance(result, CommandRejected)
        assert result.code == "PROGRAM_DUPLICATE_ID"
        assert session.authority.snapshot() == before
    finally:
        session.close()
