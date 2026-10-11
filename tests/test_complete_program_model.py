import subprocess
import sys
from dataclasses import replace
from typing import get_args

import pytest
from python_persistence_fixtures import legacy_project_data

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.drakon_program_adapter import drakon_from_program
from code_visualizer.application.examples import EXAMPLE_CATALOG, example_session
from code_visualizer.application.messages import CommandAccepted, CommandEnvelope
from code_visualizer.application.program_model import (
    canonicalize_project,
)
from code_visualizer.application.project_factory import (
    create_default_project,
    initialize_project_documents,
)
from code_visualizer.application.semantic_index import build_semantic_program
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain import program
from code_visualizer.domain.drakon import (
    Assignment,
    Case,
    Loop,
    Output,
    Select,
    Sequence,
    SimpleStatement,
    Transfer,
)
from code_visualizer.domain.drakon_defaults import ATOM_KIND_INVENTORY, create_default_atom
from code_visualizer.domain.program import (
    ExpressionRole,
    ProgramLoop,
    ProgramSequence,
    ProgramStatement,
    make_program_expression,
    program_expressions,
    program_statements,
)
from code_visualizer.domain.program_kinds import LoopKind, SelectMode, SimpleKind, TransferKind
from code_visualizer.domain.projection import DrakonViewDefinition
from code_visualizer.domain.semantic import SemanticObjectKind
from code_visualizer.generation import generate_python, generate_python_project
from code_visualizer.generation.lowering import dependency_closure
from code_visualizer.persistence.decoding import (
    ProjectDecodeError,
    project_from_data,
    project_from_json,
)
from code_visualizer.persistence.serialization import (
    document_to_data,
    normalized_project_json,
    project_to_data,
)
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.validation import assess_project


def _project(*atoms):
    project = create_default_project()
    diagram = project.documents[0]
    return initialize_project_documents(
        project, (replace(diagram, body=Sequence(diagram.body.id, atoms)),)
    )


@pytest.mark.parametrize("definition", EXAMPLE_CATALOG, ids=lambda item: item.id)
def test_catalog_executes_and_indexes_after_every_view_is_removed(definition, tmp_path):
    session = example_session(definition.id)
    try:
        original = session.authority.snapshot()
    finally:
        session.close()
    project = replace(original, documents=(), drakon_views=())
    project = project_from_json(normalized_project_json(project))
    assert assess_project(project).diagnostics == ()
    generated = generate_python_project(project)
    assert {item.path: item.source for item in generated.files} == {
        item.path: item.source for item in generate_python_project(original).files
    }
    for item in generated.files:
        target = tmp_path / item.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item.source, encoding="utf-8")
        assert all(span.presentation_id is None for span in item.spans)
    result = subprocess.run(
        [sys.executable, str(tmp_path / "run_project.py")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    if definition.id == "dijkstra":
        assert result.stdout.count("['A', 'C', 'B', 'D']") == 2
        assert result.stdout.count("total cost: 4.0") == 2
    if definition.id == "computational_instrument":
        assert "Replay deterministic: True" in result.stdout
    index = build_semantic_program(project)
    by_id = {item.id: item for item in index.objects}
    for function in project.program_model.functions:
        for statement in program_statements(function.body):
            assert by_id[statement.id].kind is SemanticObjectKind.OPERATION
        for expression in program_expressions(function):
            assert expression.id in by_id
    assert not any(item.kind is SemanticObjectKind.GLYPH for item in index.objects)


def test_every_palette_construct_is_canonical_and_round_trips_without_payload():
    atoms = tuple(
        create_default_atom(item.kind, f"atom_{item.kind}") for item in ATOM_KIND_INVENTORY
    )
    project = _project(*atoms)
    function = project.program_model.functions[0]
    assert {type(item) for item in program_statements(function.body)} == set(
        get_args(ProgramStatement.__value__)
    )
    assert not hasattr(program, "UnmigratedDrakonStatement")
    raw = project_to_data(project)
    assert not {"body", "header", "end"} & raw["documents"][0].keys()
    round_trip = project_from_data(raw)
    assert round_trip.program_model == project.program_model
    assert round_trip.documents == canonicalize_project(project).documents
    isolated = replace(project, documents=(), drakon_views=())
    assert project_from_json(normalized_project_json(isolated)) == isolated


def _legacy_project():
    project = _project(
        Assignment("answer", "answer", "42"),
        Loop(
            "loop",
            LoopKind.FOR,
            Sequence("loop_body", (Output("out", "answer + item"),)),
            Sequence("loop_else"),
            target="item",
            iterable="[1, 2]",
        ),
    )
    raw = legacy_project_data(project, 4)
    raw["documents"] = [document_to_data(item) for item in project.documents]
    statements = raw["program_model"]["functions"][0]["body"]["statements"]
    statements[1] = {"kind": "unmigrated_drakon_statement", "id": "loop", "drakon_kind": "Loop"}
    # A stale migrated field must never win over its canonical value during load.
    raw["documents"][0]["body"]["atoms"][0]["value"] = "999"
    return raw


def test_revision_four_upgrade_is_deterministic_and_preserves_canonical_truth():
    raw = _legacy_project()
    first = project_from_data(raw)
    second = project_from_data(raw)
    assert first == second
    assert first.format_revision == 11
    assert first.program_model.functions[0].body.statements[0].value.source == "42"
    assert isinstance(first.program_model.functions[0].body.statements[1], ProgramLoop)
    assert "unmigrated_drakon_statement" not in normalized_project_json(first)
    assert assess_project(replace(first, documents=(), drakon_views=())).buildable
    assert project_from_json(normalized_project_json(first)) == first


def test_legacy_loader_requires_matching_payload_and_current_format_rejects_duplicates():
    raw = _legacy_project()
    raw["documents"][0]["body"]["atoms"].pop()
    with pytest.raises(ProjectDecodeError, match="FORMAT_LEGACY_PAYLOAD_REQUIRED"):
        project_from_data(raw)
    current = project_to_data(_project(Output("out", "42")))
    current["documents"][0]["body"] = {"id": "shadow", "atoms": []}
    with pytest.raises(ProjectDecodeError, match="FORMAT_DUPLICATE_EXECUTABLE_STATE"):
        project_from_data(current)


def test_nested_edit_delete_and_undo_remain_exact_after_view_deletion(tmp_path):
    session = example_session("loops")
    try:
        session.save_as(tmp_path / "loops")
        before = session.authority.snapshot()
        function = before.program_model.functions[0]
        loop = next(
            item for item in program_statements(function.body) if isinstance(item, ProgramLoop)
        )
        original = loop.condition
        result = session.client.replace_program_expression(
            function.id, original.id, "False or False"
        )
        assert isinstance(result, CommandAccepted)
        assert session.authority.snapshot().program_model != before.program_model
        assert isinstance(session.client.undo(), CommandAccepted)
        assert session.authority.snapshot().program_model == before.program_model
        # View removal must leave the executable function and its nested bodies intact.
        snapshot = session.authority.snapshot()
        result = session.authority.execute(
            CommandEnvelope(
                command_type="diagram.delete",
                actor_id=session.client.actor_id,
                operation_id="delete-view",
                project_id=snapshot.id,
                expected_revision=snapshot.revision,
                payload={"diagram_id": before.documents[0].id},
            )
        )
        assert isinstance(result, CommandAccepted)
        assert session.authority.snapshot().program_model == before.program_model
        result = session.client.insert_program_statement(
            function.id, loop.body.id, 0, "assignment", target="nested", value="42"
        )
        assert isinstance(result, CommandAccepted)
        modified = session.authority.snapshot().program_model
        assert isinstance(session.client.undo(), CommandAccepted)
        assert session.authority.snapshot().program_model == before.program_model
        assert isinstance(session.client.redo(), CommandAccepted)
        assert session.authority.snapshot().program_model == modified
    finally:
        session.close()


def test_sdk_accepts_a_complete_canonical_structured_subtree():
    session = ProjectSession.new()
    try:
        before = session.authority.snapshot()
        function = before.program_model.functions[0]
        node = ProgramLoop(
            "loop",
            LoopKind.FOR,
            ProgramSequence("body"),
            ProgramSequence("else"),
            make_program_expression("loop", "condition", "False", ExpressionRole.CONDITION),
            make_program_expression("loop", "target", "item", ExpressionRole.TARGET),
            make_program_expression("loop", "iterable", "[1, 2]", ExpressionRole.EXPRESSION),
            make_program_expression(
                "loop", "children", "lambda node: []", ExpressionRole.EXPRESSION
            ),
            make_program_expression("loop", "delay_seconds", "0", ExpressionRole.EXPRESSION),
        )
        assert isinstance(
            session.client.insert_program_statement(
                function.id, function.body.id, 0, statement=node
            ),
            CommandAccepted,
        )
        saved = session.authority.snapshot()
        assert assess_project(saved).buildable
        assert any(symbol.name == "item" for symbol in saved.program_model.symbols)
        assert isinstance(
            session.client.delete_program_statements(function.id, function.body.id, (node.id,)),
            CommandAccepted,
        )
        assert session.authority.snapshot().program_model == before.program_model
        assert isinstance(session.client.undo(), CommandAccepted)
        assert session.authority.snapshot().program_model == saved.program_model
    finally:
        session.close()


def test_invalid_nested_control_flow_and_expressions_block_without_a_view():
    project = _project(Transfer("bad_break", TransferKind.BREAK))
    project = replace(project, documents=(), drakon_views=())
    assessment = assess_project(project)
    assert not assessment.buildable
    assert any(
        item.object_id == "bad_break" and item.diagram_id is None for item in assessment.diagnostics
    )
    project = _project(
        Loop("bad", LoopKind.WHILE, Sequence("body"), Sequence("else"), condition="(")
    )
    project = replace(project, documents=(), drakon_views=())
    assert any(
        item.code == "PROGRAM_INCOMPLETE_EXPRESSION" for item in assess_project(project).diagnostics
    )


def test_drakon_binding_can_have_a_different_identity_from_its_function():
    project = _project(Loop("loop", LoopKind.WHILE, Sequence("body"), Sequence("else")))
    function = project.program_model.functions[0]
    view = DrakonViewDefinition("view_only", function.id, "Loop view", "header", "end")
    diagram = drakon_from_program(function, view, model=project.program_model)
    project = replace(project, documents=(diagram,), drakon_views=(view,))
    authority = ProjectAuthority(project)
    client = CodeVisualizerClient(authority, actor_id="test")
    assert isinstance(
        client.set_drakon_text(diagram.id, "loop", "condition", "True"), CommandAccepted
    )
    result = authority.snapshot()
    assert len(result.program_model.functions) == 1
    assert result.program_model.functions[0].id == function.id
    assert result.program_model.functions[0].body.statements[0].condition.source == "True"
    assert canonicalize_project(result) == result


def test_match_capture_rename_updates_pattern_and_body_without_reparsing():
    project = _project(
        Select(
            "select",
            "[42]",
            (
                Case(
                    "case",
                    "Captured",
                    Sequence("body", (Output("output", "captured"),)),
                    pattern="[captured]",
                ),
            ),
            mode=SelectMode.MATCH,
        )
    )
    function = project.program_model.functions[0]
    symbol = next(item for item in project.program_model.symbols if item.name == "captured")
    from code_visualizer.application.features.program.model_ops import rename_symbol

    updated = rename_symbol(project.program_model, symbol, "value")
    branch = updated.functions[0].body.statements[0].cases[0]
    assert branch.pattern.source == "[value]"
    assert branch.body.statements[0].expression.source == "value"
    assert updated.symbol(symbol.id).id == symbol.id
    assert function.id == updated.functions[0].id


def test_dependency_closure_sees_calls_in_structured_bodies_without_views():
    session = example_session("python_modules")
    try:
        project = session.authority.snapshot()
    finally:
        session.close()
    project = replace(project, documents=(), drakon_views=())
    main = next(item for item in project.program_model.functions if item.identifier == "main")
    assert dependency_closure(project, main.id) == {
        item.id for item in project.program_model.functions
    }
    assert "def " in generate_python(project, focus_diagram_id=main.id).source


def test_name_lists_and_deletion_targets_render_as_valid_python():
    project = _project(
        SimpleStatement("names", SimpleKind.GLOBAL, "first, second"),
        Assignment("assign", "first, second", "(1, 2)"),
        SimpleStatement("delete", SimpleKind.DELETE, "first, second"),
    )
    project = replace(project, documents=(), drakon_views=())
    source = generate_python(project).source
    assert "global first, second" in source
    for item in generate_python_project(project).files:
        compile(item.source, item.path, "exec")


def test_nested_multiple_target_symbols_keep_their_ids_through_editor_changes():
    project = canonicalize_project(
        _project(
            Loop(
                "loop",
                LoopKind.FOR,
                Sequence("body", (Assignment("pair", "left, right", "(1, 2)"),)),
                Sequence("else"),
                target="item",
                iterable="[1]",
            ),
        )
    )
    diagram = project.documents[0]
    authority = ProjectAuthority(project)
    client = CodeVisualizerClient(authority, actor_id="test")
    assert isinstance(
        client.set_drakon_text(diagram.id, "loop", "iterable", "[1, 2]"), CommandAccepted
    )
    result = authority.snapshot()
    assert result.program_model.symbols == project.program_model.symbols
