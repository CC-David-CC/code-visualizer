from __future__ import annotations

import ast
import json
from dataclasses import fields, replace

import pytest

from code_visualizer.application.headless import HeadlessService
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.program_model import function_for_document
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.common import DocumentKind
from code_visualizer.domain.expression import (
    AssignmentTargetsExpression,
    BinaryExpression,
    CallExpression,
    ExpressionIdentityError,
    ExpressionScalar,
    LiteralExpression,
    SubscriptExpression,
    SymbolReferenceExpression,
    UnparsedPythonExpression,
    expression_children,
    expression_node_from_data,
    expression_node_to_data,
    map_expression_tree,
    parse_expression_tree,
    reconcile_expression_trees,
    render_expression_tree,
)
from code_visualizer.domain.program import ExpressionRole, ProgramAssignment, ProgramExpression
from code_visualizer.generation import BuildBlockedError, generate_python, generate_python_project
from code_visualizer.persistence.decoding import ProjectDecodeError, project_from_json
from code_visualizer.persistence.serialization import normalized_project_json, project_to_data
from code_visualizer.validation import BuildabilityStatus, assess_project, validate_integrity


def _dump_eval(source: str) -> str:
    return ast.dump(ast.parse(source, mode="eval").body, include_attributes=False)


def _node_ids(tree) -> set[str]:
    result = {tree.id}
    for _field, child in expression_children(tree):
        result.update(_node_ids(child))
    return result


def test_reparse_never_reuses_position_identity_without_reconciliation() -> None:
    before = parse_expression_tree("expression_identity", "a + b")
    after = parse_expression_tree("expression_identity", "a + b + c")
    repeated = parse_expression_tree("expression_identity", "a + b")

    assert _node_ids(before).isdisjoint(_node_ids(after))
    assert _node_ids(before).isdisjoint(_node_ids(repeated))


def test_reconciler_preserves_only_provable_expression_correspondence() -> None:
    symbols = {
        "distance": "symbol_distance",
        "current": "symbol_current",
        "weight": "symbol_weight",
        "edge_weight": "symbol_edge_weight",
    }

    def resolve(name, _context):
        return symbols.get(name)

    before = parse_expression_tree(
        "expression_relax",
        "distance[current] + weight",
        resolve_symbol=resolve,
    )
    provisional = parse_expression_tree(
        "expression_relax",
        "distance[current] + edge_weight",
        resolve_symbol=resolve,
    )
    reconciled = reconcile_expression_trees(before, provisional)

    assert isinstance(before, BinaryExpression)
    assert isinstance(reconciled, BinaryExpression)
    assert reconciled.id == before.id
    assert isinstance(before.left, SubscriptExpression)
    assert isinstance(reconciled.left, SubscriptExpression)
    assert reconciled.left == before.left
    assert isinstance(before.right, SymbolReferenceExpression)
    assert isinstance(reconciled.right, SymbolReferenceExpression)
    assert reconciled.right.id != before.right.id


def test_reconciler_tracks_unique_moved_subtree_but_not_a_new_parent() -> None:
    before = parse_expression_tree("expression_extend", "a + b")
    provisional = parse_expression_tree("expression_extend", "a + b + c")
    reconciled = reconcile_expression_trees(before, provisional)

    assert isinstance(before, BinaryExpression)
    assert isinstance(reconciled, BinaryExpression)
    assert reconciled.id != before.id
    assert isinstance(reconciled.left, BinaryExpression)
    assert reconciled.left.id == before.id
    assert reconciled.left.left.id == before.left.id
    assert reconciled.left.right.id == before.right.id
    assert reconciled.right.id not in _node_ids(before)


def test_reconciler_leaves_ambiguous_repeated_list_items_fresh() -> None:
    before = parse_expression_tree("expression_ambiguous", "call(a, a)")
    provisional = parse_expression_tree("expression_ambiguous", "call(a, a, a)")
    reconciled = reconcile_expression_trees(before, provisional)

    assert isinstance(reconciled, CallExpression)
    assert _node_ids(before).isdisjoint({item.id for item in reconciled.arguments})


def test_reconciler_does_not_reuse_operation_identity_when_operator_changes() -> None:
    before = parse_expression_tree("expression_operator", "left < right")
    provisional = parse_expression_tree("expression_operator", "left > right")
    reconciled = reconcile_expression_trees(before, provisional)

    assert reconciled.id != before.id


def test_structural_mapper_rejects_false_retained_symbol_identity() -> None:
    tree = parse_expression_tree("expression_identity_guard", "left + right")

    def falsely_replace(node):
        if isinstance(node, SymbolReferenceExpression) and node.name == "right":
            return replace(node, name="different_object")
        return node

    with pytest.raises(ExpressionIdentityError):
        map_expression_tree(tree, falsely_replace)


def test_complete_expression_tree_round_trips_python_forms_without_stored_outer_text() -> None:
    expressions = (
        "not ready or value < limit <= ceiling",
        "(left + right) * scale",
        "items[index:stop:step]",
        "{key: transform(value) for key, value in pairs if value is not None}",
        "lambda x=1: x + 1",
        "f'{name!r}:{value:.2f}'",
        "[item async for item in stream if item]",
        "(value := compute())",
        "{*left, *right}",
    )
    for index, source in enumerate(expressions):
        tree = parse_expression_tree(f"expression_{index}", source)
        assert not isinstance(tree, UnparsedPythonExpression)
        rendered = render_expression_tree(tree)
        assert _dump_eval(rendered) == _dump_eval(source)
        restored = expression_node_from_data(expression_node_to_data(tree))
        assert restored == tree
        assert render_expression_tree(restored) == rendered

    arguments = "first, *rest, flag=True, **options"
    argument_tree = parse_expression_tree("expression_arguments", arguments, mode="arguments")
    argument_text = render_expression_tree(argument_tree)
    original_call = ast.parse(f"call({arguments})", mode="eval").body
    rendered_call = ast.parse(f"call({argument_text})", mode="eval").body
    assert ast.dump(rendered_call, include_attributes=False) == ast.dump(
        original_call, include_attributes=False
    )

    target = "head, *tail"
    target_tree = parse_expression_tree("expression_target", target, mode="target")
    rendered_target = render_expression_tree(target_tree)
    original_assign = ast.parse(f"{target} = None", mode="exec").body[0]
    rendered_assign = ast.parse(f"{rendered_target} = None", mode="exec").body[0]
    assert ast.dump(rendered_assign, include_attributes=False) == ast.dump(
        original_assign, include_attributes=False
    )

    chained = parse_expression_tree("expression_chained_target", "primary = alias", mode="target")
    assert isinstance(chained, AssignmentTargetsExpression)
    assert render_expression_tree(chained) == "primary = alias"
    assert expression_node_from_data(expression_node_to_data(chained)) == chained


def test_program_expression_has_one_persisted_truth_and_tree_changes_drive_text() -> None:
    assert [item.name for item in fields(ProgramExpression)] == ["id", "role", "tree"]
    tree = parse_expression_tree("expression_value", "left + 2")
    assert isinstance(tree, BinaryExpression)
    expression = ProgramExpression("expression_value", ExpressionRole.VALUE, tree)
    assert expression.source == "left + 2"

    right = tree.right
    assert isinstance(right, LiteralExpression)
    changed = replace(
        expression,
        tree=replace(
            tree,
            right=replace(right, value=ExpressionScalar("int", "40")),
        ),
    )
    assert changed.source == "left + 40"


def test_program_model_persists_only_tree_and_unparsed_state_is_single_truth() -> None:
    session = ProjectSession.new()
    try:
        function = session.authority.snapshot().program_model.functions[0]
        assert isinstance(
            session.client.insert_program_statement(
                function.id,
                function.body.id,
                0,
                "assignment",
                statement_id="single_truth_assignment",
                target="answer",
                value="40 + 2",
                true_sequence_id="unused_true",
                false_sequence_id="unused_false",
            ),
            CommandAccepted,
        )
        project = session.authority.snapshot()
        data = project_to_data(project)
        assert set(data["program_model"]) == {
            "functions",
            "symbols",
            "modules",
            "package",
            "entrypoint",
        }
        statement = data["program_model"]["functions"][0]["body"]["statements"][0]
        assert "source" not in statement["target"]
        assert "source" not in statement["value"]

        value_id = project.program_model.functions[0].body.statements[0].value.id
        assert isinstance(
            session.client.replace_program_expression(
                function.id,
                value_id,
                "(",
            ),
            CommandAccepted,
        )
        incomplete_data = project_to_data(session.authority.snapshot())
        incomplete_value = incomplete_data["program_model"]["functions"][0]["body"]["statements"][
            0
        ]["value"]
        assert "source" not in incomplete_value
        assert incomplete_value["tree"]["kind"] == "unparsed"
        assert incomplete_value["tree"]["source"] == "("
    finally:
        session.close()


def test_expression_undo_and_redo_restore_exact_trees_symbols_and_ids() -> None:
    session = ProjectSession.new()
    try:
        function = session.authority.snapshot().program_model.functions[0]
        assert isinstance(
            session.client.insert_program_statement(
                function.id,
                function.body.id,
                0,
                "assignment",
                statement_id="history_assignment",
                target="result",
                value="result + 6 * 7",
                true_sequence_id="unused_true",
                false_sequence_id="unused_false",
            ),
            CommandAccepted,
        )
        before_project = session.authority.snapshot()
        before_function = before_project.program_model.function(function.id)
        assert before_function is not None
        before_symbols = tuple(
            item for item in before_project.program_model.symbols if item.owner_id == function.id
        )
        statement = before_function.body.statements[0]
        assert isinstance(statement, ProgramAssignment)

        assert isinstance(
            session.client.replace_program_expression(
                function.id,
                statement.target.id,
                "total",
            ),
            CommandAccepted,
        )
        edited_project = session.authority.snapshot()
        edited_function = edited_project.program_model.function(function.id)
        assert edited_function is not None
        edited_symbols = tuple(
            item for item in edited_project.program_model.symbols if item.owner_id == function.id
        )
        assert edited_function != before_function

        assert isinstance(session.client.undo(), CommandAccepted)
        restored_project = session.authority.snapshot()
        assert restored_project.program_model.function(function.id) == before_function
        assert (
            tuple(
                item
                for item in restored_project.program_model.symbols
                if item.owner_id == function.id
            )
            == before_symbols
        )

        assert isinstance(session.client.redo(), CommandAccepted)
        redone_project = session.authority.snapshot()
        assert redone_project.program_model.function(function.id) == edited_function
        assert (
            tuple(
                item
                for item in redone_project.program_model.symbols
                if item.owner_id == function.id
            )
            == edited_symbols
        )
    finally:
        session.close()


def test_exact_expression_history_survives_journal_restart(tmp_path) -> None:
    root = tmp_path / "exact-expression-history"
    service = HeadlessService.create(root)
    client = service.client("semantic-author")
    function = service.authority.snapshot().program_model.functions[0]
    assert isinstance(
        client.insert_program_statement(
            function.id,
            function.body.id,
            0,
            "assignment",
            statement_id="journal_assignment",
            target="answer",
            value="6 * 7",
            true_sequence_id="unused_true",
            false_sequence_id="unused_false",
        ),
        CommandAccepted,
    )
    before = service.authority.snapshot().program_model.function(function.id)
    assert before is not None
    statement = before.body.statements[0]
    assert isinstance(statement, ProgramAssignment)
    assert isinstance(
        client.replace_program_expression(function.id, statement.value.id, "40 + 2"),
        CommandAccepted,
    )
    client.close()
    service.close()

    reopened = HeadlessService.open(root)
    reopened_client = reopened.client("semantic-author")
    try:
        assert isinstance(reopened_client.undo(), CommandAccepted)
        assert reopened.authority.snapshot().program_model.function(function.id) == before
    finally:
        reopened_client.close()
        reopened.close()


def test_incomplete_expression_is_saveable_but_blocks_every_python_projection() -> None:
    session = ProjectSession.new()
    try:
        function = session.authority.snapshot().program_model.functions[0]
        assert isinstance(
            session.client.insert_program_statement(
                function.id,
                function.body.id,
                0,
                "assignment",
                statement_id="incomplete_assignment",
                target="distance",
                value="0",
                true_sequence_id="unused_true",
                false_sequence_id="unused_false",
            ),
            CommandAccepted,
        )
        expression_id = (
            session.authority.snapshot().program_model.functions[0].body.statements[0].value.id
        )
        assert isinstance(
            session.client.replace_program_expression(
                function.id,
                expression_id,
                "distance +",
            ),
            CommandAccepted,
        )
        incomplete = session.authority.snapshot()
        statement = incomplete.program_model.functions[0].body.statements[0]
        assert isinstance(statement, ProgramAssignment)
        assert isinstance(statement.value.tree, UnparsedPythonExpression)
        assert not [
            item
            for item in validate_integrity(incomplete)
            if item.code == "PROGRAM_INCOMPLETE_EXPRESSION"
        ]

        assessment = assess_project(incomplete)
        assert assessment.status is BuildabilityStatus.BLOCKED
        assert "PROGRAM_INCOMPLETE_EXPRESSION" in {
            item.code for item in assessment.blocking_diagnostics
        }
        with pytest.raises(BuildBlockedError, match="PROGRAM_INCOMPLETE_EXPRESSION"):
            generate_python(incomplete)
        with pytest.raises(BuildBlockedError, match="PROGRAM_INCOMPLETE_EXPRESSION"):
            generate_python_project(incomplete)

        restored = project_from_json(normalized_project_json(incomplete))
        restored_statement = restored.program_model.functions[0].body.statements[0]
        assert isinstance(restored_statement, ProgramAssignment)
        assert isinstance(restored_statement.value.tree, UnparsedPythonExpression)

        assert isinstance(
            session.client.replace_program_expression(
                function.id,
                expression_id,
                "distance + 1",
            ),
            CommandAccepted,
        )
        repaired = session.authority.snapshot()
        assert assess_project(repaired).status is BuildabilityStatus.BUILDABLE
        for emitted in generate_python_project(repaired).files:
            compile(emitted.source, emitted.path, "exec")
    finally:
        session.close()


def test_focused_live_projection_ignores_unrelated_incomplete_function() -> None:
    session = ProjectSession.new()
    try:
        first_diagram = session.authority.snapshot().documents[0]
        assert isinstance(
            session.client.create_diagram(
                DocumentKind.DRAKON,
                "Incomplete helper",
                identifier="incomplete_helper",
            ),
            CommandAccepted,
        )
        project = session.authority.snapshot()
        second_diagram = project.documents[-1]
        second_function = function_for_document(project, second_diagram.id)
        assert second_function is not None
        assert isinstance(
            session.client.insert_program_statement(
                second_function.id,
                second_function.body.id,
                0,
                "assignment",
                statement_id="unrelated_incomplete_assignment",
                target="answer",
                value="missing +",
                true_sequence_id="unused_true",
                false_sequence_id="unused_false",
            ),
            CommandAccepted,
        )
        project = session.authority.snapshot()
        assert assess_project(project).status is BuildabilityStatus.BLOCKED
        compile(
            generate_python(
                project,
                include_main=False,
                focus_diagram_id=first_diagram.id,
            ).source,
            "<focused-complete>",
            "exec",
        )
        with pytest.raises(BuildBlockedError, match="PROGRAM_INCOMPLETE_EXPRESSION"):
            generate_python(
                project,
                include_main=False,
                focus_diagram_id=second_diagram.id,
            )
    finally:
        session.close()


def test_current_decoder_rejects_a_second_outer_source_truth() -> None:
    session = ProjectSession.new()
    try:
        function = session.authority.snapshot().program_model.functions[0]
        assert isinstance(
            session.client.insert_program_statement(
                function.id,
                function.body.id,
                0,
                "assignment",
                statement_id="duplicate_truth_assignment",
                target="answer",
                value="40 + 2",
                true_sequence_id="unused_true",
                false_sequence_id="unused_false",
            ),
            CommandAccepted,
        )
        ambiguous = project_to_data(session.authority.snapshot())
    finally:
        session.close()

    ambiguous_value = ambiguous["program_model"]["functions"][0]["body"]["statements"][0]["value"]
    ambiguous_value["source"] = "6 * 7"
    with pytest.raises(ProjectDecodeError, match="FORMAT_DUPLICATE_EXPRESSION_TRUTH"):
        project_from_json(json.dumps(ambiguous))


def test_v3_decode_and_stable_symbol_rename_do_not_reparse_canonical_trees(monkeypatch) -> None:
    session = ProjectSession.new()
    try:
        function = session.authority.snapshot().program_model.functions[0]
        assert isinstance(
            session.client.insert_program_statement(
                function.id,
                function.body.id,
                0,
                "assignment",
                statement_id="declaration_total",
                target="total",
                value="1",
                true_sequence_id="unused_true",
                false_sequence_id="unused_false",
            ),
            CommandAccepted,
        )
        assert isinstance(
            session.client.insert_program_statement(
                function.id,
                function.body.id,
                1,
                "assignment",
                statement_id="use_total",
                target="result",
                value="total + 2",
                true_sequence_id="unused_true_2",
                false_sequence_id="unused_false_2",
            ),
            CommandAccepted,
        )
        serialized = normalized_project_json(session.authority.snapshot())
        before_rename_tree = (
            session.authority.snapshot().program_model.functions[0].body.statements[1].value.tree
        )
        before_rename_ids = _node_ids(before_rename_tree)
        total_symbol = next(
            item
            for item in session.authority.snapshot().program_model.symbols
            if item.name == "total"
        )

        def fail_parse(*_args, **_kwargs):
            raise AssertionError("canonical expression tree was reparsed")

        monkeypatch.setattr("code_visualizer.domain.expression.ast.parse", fail_parse)
        decoded = project_from_json(serialized)
        assert decoded.program_model.functions[0].body.statements[1].value.source == "total + 2"
        assert isinstance(
            session.client.rename_program_symbol(total_symbol.id, "subtotal"),
            CommandAccepted,
        )
        statements = session.authority.snapshot().program_model.functions[0].body.statements
        assert statements[0].target.source == "subtotal"
        assert statements[1].value.source == "subtotal + 2"
        assert _node_ids(statements[1].value.tree) == before_rename_ids
    finally:
        session.close()


def test_integrity_rejects_dangling_identity_inside_the_canonical_tree() -> None:
    session = ProjectSession.new()
    try:
        function = session.authority.snapshot().program_model.functions[0]
        assert isinstance(
            session.client.insert_program_statement(
                function.id,
                function.body.id,
                0,
                "assignment",
                statement_id="dangling_reference_assignment",
                target="answer",
                value="input_value",
                true_sequence_id="unused_true",
                false_sequence_id="unused_false",
            ),
            CommandAccepted,
        )
        project = session.authority.snapshot()
        function = project.program_model.functions[0]
        statement = function.body.statements[0]
        assert isinstance(statement, ProgramAssignment)
        broken_statement = replace(
            statement,
            value=replace(
                statement.value,
                tree=SymbolReferenceExpression(
                    "dangling_expression_node",
                    "input_value",
                    "missing_symbol_identity",
                ),
            ),
        )
        broken_function = replace(
            function,
            body=replace(function.body, statements=(broken_statement,)),
        )
        broken_project = replace(
            project,
            program_model=replace(
                project.program_model,
                functions=tuple(
                    broken_function if item.id == function.id else item
                    for item in project.program_model.functions
                ),
            ),
        )

        assert "PROGRAM_UNRESOLVED_EXPRESSION_SYMBOL" in {
            item.code for item in validate_integrity(broken_project)
        }
    finally:
        session.close()
