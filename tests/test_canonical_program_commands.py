from __future__ import annotations

from dataclasses import replace

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.messages import CommandAccepted, CommandEnvelope
from code_visualizer.application.project_factory import create_default_project
from code_visualizer.application.semantic_index import build_semantic_program
from code_visualizer.domain.drakon import Assignment, DrakonDiagram, If, Output, find_atom_location
from code_visualizer.domain.program import (
    ProgramAssignment,
    ProgramFunctionReference,
    ProgramModule,
    ProgramOutput,
)
from code_visualizer.domain.semantic import SemanticObjectKind
from code_visualizer.generation import generate_python_project
from code_visualizer.generation.lowering import lower_project
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.validation import BuildabilityStatus, assess_project


def _client() -> tuple[ProjectAuthority, CodeVisualizerClient]:
    authority = ProjectAuthority(create_default_project())
    return authority, CodeVisualizerClient(authority, actor_id="program-test")


def test_canonical_statement_edits_reproject_only_the_bound_drakon_view() -> None:
    authority, client = _client()
    project = authority.snapshot()
    view = project.drakon_views[0]
    function = project.program_model.function(view.function_id)
    assert function is not None

    result = client.insert_program_statement(
        function.id,
        function.body.id,
        0,
        "assignment",
        statement_id="statement_counter",
        target="counter",
        value="counter + 1",
        true_sequence_id="unused_true",
        false_sequence_id="unused_false",
    )
    assert isinstance(result, CommandAccepted)

    changed = authority.snapshot()
    diagram = next(
        item
        for item in changed.documents
        if isinstance(item, DrakonDiagram) and item.id == view.document_id
    )
    location = find_atom_location(diagram.body, "statement_counter")
    assert location is not None
    atom = location[0].atoms[location[1]]
    assert isinstance(atom, Assignment)
    assert atom.target == "counter"
    symbol = next(item for item in changed.program_model.symbols if item.name == "counter")

    assert isinstance(client.rename_program_symbol(symbol.id, "total"), CommandAccepted)
    renamed = authority.snapshot()
    function = renamed.program_model.function(function.id)
    assert function is not None
    assignment = function.body.statements[0]
    assert isinstance(assignment, ProgramAssignment)
    assert assignment.target.source == "total"
    assert assignment.value.source == "total + 1"

    renamed_diagram = next(
        item
        for item in renamed.documents
        if isinstance(item, DrakonDiagram) and item.id == view.document_id
    )
    renamed_location = find_atom_location(renamed_diagram.body, "statement_counter")
    assert renamed_location is not None
    renamed_atom = renamed_location[0].atoms[renamed_location[1]]
    assert isinstance(renamed_atom, Assignment)
    assert (renamed_atom.target, renamed_atom.value) == ("total", "total + 1")


def test_canonical_if_can_be_created_without_a_drakon_popup_and_undone() -> None:
    authority, client = _client()
    function = authority.snapshot().program_model.functions[0]
    assert isinstance(
        client.insert_program_statement(
            function.id,
            function.body.id,
            0,
            "if",
            statement_id="if_ready",
            condition="ready",
            true_sequence_id="if_ready_true",
            false_sequence_id="if_ready_false",
        ),
        CommandAccepted,
    )
    project = authority.snapshot()
    diagram = next(item for item in project.documents if isinstance(item, DrakonDiagram))
    location = find_atom_location(diagram.body, "if_ready")
    assert location is not None
    assert isinstance(location[0].atoms[location[1]], If)

    assert isinstance(client.undo(), CommandAccepted)
    restored = authority.snapshot().program_model.function(function.id)
    assert restored is not None and not restored.body.statements


def test_output_family_routes_directly_and_undo_restores_exact_expression_identity(
    monkeypatch,
) -> None:
    authority, client = _client()
    project = authority.snapshot()
    diagram = next(item for item in project.documents if isinstance(item, DrakonDiagram))
    function = project.program_model.function(project.drakon_views[0].function_id)
    assert function is not None

    def fail_transitional_promotion(*_args, **_kwargs):
        raise AssertionError("migrated Output edit used transitional DRAKON promotion")

    monkeypatch.setattr(
        "code_visualizer.application.program_model.promote_program_from_drakon",
        fail_transitional_promotion,
    )
    assert isinstance(
        client.insert_drakon_atom(
            diagram.id,
            "output",
            0,
            source='"Hello from ProgramModel"',
        ),
        CommandAccepted,
    )
    inserted_diagram = next(
        item for item in authority.snapshot().documents if isinstance(item, DrakonDiagram)
    )
    output_id = inserted_diagram.body.atoms[0].id
    assert isinstance(
        client.set_drakon_text(diagram.id, output_id, "destination", "stream"),
        CommandAccepted,
    )
    assert isinstance(
        client.set_drakon_text(diagram.id, output_id, "end", '"!"'),
        CommandAccepted,
    )
    configured = authority.snapshot().program_model.function(function.id)
    assert configured is not None
    configured_output = configured.body.statements[0]
    assert isinstance(configured_output, ProgramOutput)
    assert configured_output.destination is not None
    assert configured_output.end is not None
    assert "Unmigrated" not in type(configured_output).__name__
    assert (
        "print('Hello from ProgramModel', file=stream, end='!')"
        in generate_python_project(authority.snapshot()).file("app/main.py").source
    )

    exact_before_removal = configured_output
    assert isinstance(
        client.set_drakon_text(diagram.id, output_id, "end", ""),
        CommandAccepted,
    )
    edited = authority.snapshot().program_model.function(function.id)
    assert edited is not None
    edited_output = edited.body.statements[0]
    assert isinstance(edited_output, ProgramOutput)
    assert edited_output.end is None
    assert edited_output.expression is exact_before_removal.expression
    assert edited_output.destination is exact_before_removal.destination

    assert isinstance(client.undo(), CommandAccepted)
    restored = authority.snapshot().program_model.function(function.id)
    assert restored is not None
    assert restored.body.statements[0] == exact_before_removal
    assert isinstance(client.redo(), CommandAccepted)
    redone = authority.snapshot().program_model.function(function.id)
    assert redone is not None
    assert isinstance(redone.body.statements[0], ProgramOutput)
    assert redone.body.statements[0].end is None

    projected = next(
        item for item in authority.snapshot().documents if isinstance(item, DrakonDiagram)
    )
    projected_output = projected.body.atoms[0]
    assert isinstance(projected_output, Output)
    assert projected_output.destination == "stream"
    assert projected_output.end is None

    assert isinstance(
        client.remove_drakon_block(diagram.id, diagram.body.id, (output_id,)),
        CommandAccepted,
    )
    removed = authority.snapshot().program_model.function(function.id)
    assert removed is not None and not removed.body.statements


def test_program_function_lifetime_is_independent_of_presentation_documents() -> None:
    authority, client = _client()
    assert isinstance(
        client.put_program_module(ProgramModule("module_helpers", "helpers")),
        CommandAccepted,
    )
    document_count = len(authority.snapshot().documents)
    assert isinstance(
        client.create_program_function(
            "helper",
            owner_id="module_helpers",
            function_id="function_helper",
            symbol_id="symbol_helper",
            body_sequence_id="sequence_helper",
        ),
        CommandAccepted,
    )
    created = authority.snapshot()
    assert created.program_model.function("function_helper") is not None
    assert len(created.documents) == document_count
    assert all(item.function_id != "function_helper" for item in created.drakon_views)
    helper = created.program_model.function("function_helper")
    assert helper is not None
    assert isinstance(
        client.insert_program_statement(
            helper.id,
            helper.body.id,
            0,
            "assignment",
            statement_id="helper_assignment",
            target="answer",
            value="42",
            true_sequence_id="unused_true",
            false_sequence_id="unused_false",
        ),
        CommandAccepted,
    )
    generated = generate_python_project(authority.snapshot())
    helper_source = generated.file("app/helpers.py").source
    assert "def helper():" in helper_source
    assert "answer = 42" in helper_source
    semantic = authority.snapshot()
    helper_object = next(
        item for item in build_semantic_program(semantic).objects if item.id == "function_helper"
    )
    assert helper_object.kind is SemanticObjectKind.FUNCTION
    assert helper_object.document_id is None

    assert isinstance(client.delete_program_function("function_helper"), CommandAccepted)
    assert authority.snapshot().program_model.function("function_helper") is None
    assert isinstance(client.undo(), CommandAccepted)
    assert authority.snapshot().program_model.function("function_helper") is not None


def test_canonical_only_callable_can_be_the_project_entrypoint() -> None:
    authority, client = _client()
    assert isinstance(
        client.put_program_module(ProgramModule("module_helpers", "helpers")),
        CommandAccepted,
    )
    assert isinstance(
        client.create_program_function(
            "helper_main",
            owner_id="module_helpers",
            function_id="function_helper_main",
            symbol_id="symbol_helper_main",
            body_sequence_id="sequence_helper_main",
        ),
        CommandAccepted,
    )
    project = authority.snapshot()
    assert isinstance(
        client.configure_entrypoint(
            replace(project.program_model.entrypoint, callable_id="function_helper_main")
        ),
        CommandAccepted,
    )

    project = authority.snapshot()
    assert assess_project(project).buildable
    ir = lower_project(project)
    assert ir.entrypoint is not None
    assert ir.entrypoint.callable_id == "function_helper_main"
    generated = generate_python_project(project)
    assert generated.entrypoint == "helper_main"
    assert (
        "from app.helpers import helper_main as _entrypoint"
        in generated.file("run_project.py").source
    )


def test_deleting_entrypoint_projection_does_not_delete_or_clear_callable() -> None:
    authority, _client_adapter = _client()
    project = authority.snapshot()
    view = project.drakon_views[0]

    result = authority.execute(
        CommandEnvelope(
            command_type="diagram.delete",
            actor_id="program-test",
            operation_id="delete-entrypoint-projection",
            project_id=project.id,
            expected_revision=project.revision,
            payload={"diagram_id": view.document_id},
        )
    )

    assert isinstance(result, CommandAccepted)
    changed = authority.snapshot()
    assert changed.program_model.entrypoint_callable_id == view.function_id
    assert changed.program_model.function(view.function_id) is not None
    assert not changed.drakon_views
    assert generate_python_project(changed).entrypoint == "main"


def test_canonical_only_function_receives_executable_validation() -> None:
    authority, client = _client()
    assert isinstance(
        client.create_program_function(
            "helper",
            owner_id=authority.snapshot().program_model.modules[0].id,
            function_id="function_unprojected",
            symbol_id="symbol_unprojected",
            body_sequence_id="sequence_unprojected",
        ),
        CommandAccepted,
    )
    project = authority.snapshot()
    function = project.program_model.function("function_unprojected")
    assert function is not None
    invalid_function = replace(function, identifier="bad-name")
    invalid = replace(
        project,
        program_model=replace(
            project.program_model,
            functions=tuple(
                invalid_function if item.id == function.id else item
                for item in project.program_model.functions
            ),
        ),
    )

    assessment = assess_project(invalid)

    assert assessment.status is BuildabilityStatus.BLOCKED
    diagnostic = next(
        item for item in assessment.diagnostics if item.code == "PY_INVALID_IDENTIFIER"
    )
    assert diagnostic.object_id == function.id
    assert diagnostic.diagram_id is None


def test_canonical_module_membership_and_duplicate_names_are_independent_invariants() -> None:
    authority, client = _client()
    for identifier, function_id in (
        ("orphan", "function_orphan"),
        ("first", "function_first"),
        ("second", "function_second"),
    ):
        assert isinstance(
            client.create_program_function(
                identifier,
                owner_id=authority.snapshot().program_model.modules[0].id,
                function_id=function_id,
                symbol_id=f"symbol_{identifier}",
                body_sequence_id=f"sequence_{identifier}",
            ),
            CommandAccepted,
        )
    project = authority.snapshot()
    functions = tuple(
        replace(item, identifier="duplicate")
        if item.id in {"function_first", "function_second"}
        else item
        for item in project.program_model.functions
    )
    modules = tuple(
        replace(
            module,
            body=tuple(
                item
                for item in module.body
                if not (
                    isinstance(item, ProgramFunctionReference)
                    and item.function_id == "function_orphan"
                )
            ),
        )
        for module in project.program_model.modules
    )
    invalid = replace(
        project, program_model=replace(project.program_model, functions=functions, modules=modules)
    )

    assessment = assess_project(invalid)
    codes = {item.code for item in assessment.blocking_diagnostics}

    assert assessment.status is BuildabilityStatus.BLOCKED
    assert {"PROGRAM_UNOWNED_FUNCTION", "PY_DUPLICATE_FUNCTION"} <= codes
