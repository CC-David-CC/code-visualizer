from dataclasses import replace

import pytest

from code_visualizer.application.commands import SetProgramDeclarationText
from code_visualizer.application.messages import CommandAccepted, CommandRejected
from code_visualizer.application.search import replacement_commands, search_project
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.program import (
    ProgramClass,
    ProgramEntryPoint,
    ProgramModel,
    ProgramModule,
    program_expressions,
)
from code_visualizer.domain.python_declarations import parse_python_declarations
from code_visualizer.persistence import ProjectStore
from code_visualizer.persistence.serialization import project_to_data


def test_program_provider_advertises_module_roots_without_any_authored_function():
    from code_visualizer.domain.expression import expression_identity_ids
    from code_visualizer.extensions.builtin import builtin_registry

    session = ProjectSession.new()
    try:
        module_id = "module:generic"
        declarations = parse_python_declarations(module_id, "class Box[T: int]:\n    value: T = 7")
        declaration = declarations[0]
        assert isinstance(declaration, ProgramClass)
        entrypoint = ProgramEntryPoint("entrypoint:library")
        model = ProgramModel(
            modules=(ProgramModule(module_id, "generic", declarations),),
            entrypoint=entrypoint,
        )
        project = replace(session.authority.snapshot(), program_model=model)
        participant = next(
            item
            for item in builtin_registry().domains(project)
            if item.provider_id == "code_visualizer.program"
        )
        assert participant.root_ids == (module_id, entrypoint.id)
        assert {module_id, entrypoint.id, declaration.id, declaration.body[0].id}.issubset(
            participant.object_ids
        )
        assert set(expression_identity_ids(declaration.type_parameters[0])).issubset(
            participant.object_ids
        )
        expression = next(program_expressions(declaration.body))
        assert {expression.id, *expression_identity_ids(expression.tree)}.issubset(
            participant.object_ids
        )
    finally:
        session.close()


def test_module_and_class_renames_keep_selection_and_canonical_identities(tmp_path):
    session = ProjectSession.new()
    try:
        module = session.authority.snapshot().program_model.modules[0]
        declaration = ProgramClass("class:worker", "Worker")
        assert isinstance(session.client.put_program_class(module.id, declaration), CommandAccepted)
        session.kernel.selection.select(
            (module.id, declaration.id), primary=declaration.id, source="test"
        )
        assert isinstance(
            session.client.submit(
                SetProgramDeclarationText(declaration.id, "identifier", "Runner")
            ),
            CommandAccepted,
        )
        assert isinstance(
            session.client.submit(SetProgramDeclarationText(module.id, "path", "workers.runner")),
            CommandAccepted,
        )
        model = session.authority.snapshot().program_model
        assert model.class_(declaration.id).identifier == "Runner"
        assert model.module(module.id).path == "workers.runner"
        assert session.kernel.selection.state.primary == declaration.id
        assert session.kernel.queries.semantic_object(module.id).label == "runner"
        assert session.kernel.queries.semantic_object(declaration.id).label == "Runner"
        session.save_as(tmp_path / "project")
        recovered = ProjectStore(tmp_path / "project").recover(promote=False)
        assert recovered.program_model == model
        saved = project_to_data(recovered)
        assert set(saved["runtime_settings"]) == {"run_profiles", "active_run_profile"}
    finally:
        session.close()


def test_function_owner_move_undo_redo_and_delete_restore_preserve_header(tmp_path):
    session = ProjectSession.new()
    try:
        original = session.authority.snapshot().program_model
        function = original.functions[0]
        second = ProgramModule("module:second", "second")
        assert isinstance(session.client.put_program_module(second), CommandAccepted)
        before = session.authority.snapshot().program_model
        assert isinstance(
            session.client.set_function_owner(function.id, second.id), CommandAccepted
        )
        moved = session.authority.snapshot().program_model
        assert moved.owner_of(function.id).id == second.id
        assert moved.function(function.id) is before.function(function.id)
        assert isinstance(session.client.undo(), CommandAccepted)
        assert session.authority.snapshot().program_model == before
        assert isinstance(session.client.redo(), CommandAccepted)
        assert session.authority.snapshot().program_model == moved
        assert isinstance(session.client.delete_program_function(function.id), CommandAccepted)
        assert session.authority.snapshot().program_model.entrypoint_callable_id is None
        assert isinstance(session.client.undo(), CommandAccepted)
        assert session.authority.snapshot().program_model == moved
        session.save_as(tmp_path / "project")
        assert ProjectStore(tmp_path / "project").recover(promote=False).program_model == moved
    finally:
        session.close()


def test_owned_module_cannot_be_deleted_and_old_setup_command_is_not_live():
    session = ProjectSession.new()
    try:
        project = session.authority.snapshot()
        result = session.client.delete_program_module(project.program_model.modules[0].id)
        assert isinstance(result, CommandRejected)
        assert session.authority.snapshot() == project
        from code_visualizer.application.messages import CommandEnvelope

        rejected = session.authority.execute(
            CommandEnvelope(
                "python.replace_module_setup",
                "test",
                "old-command",
                project.id,
                project.revision,
                {},
            )
        )
        assert isinstance(rejected, CommandRejected)
        assert rejected.code == "COMMAND_UNKNOWN"
    finally:
        session.close()


def test_reselecting_function_owner_preserves_executable_declaration_order():
    session = ProjectSession.new()
    try:
        model = session.authority.snapshot().program_model
        module = model.modules[0]
        declarations = parse_python_declarations(module.id, "main()")
        assert isinstance(
            session.client.put_program_module(replace(module, body=(*module.body, *declarations))),
            CommandAccepted,
        )
        before = session.authority.snapshot().program_model
        assert isinstance(
            session.client.set_function_owner(model.functions[0].id, module.id), CommandAccepted
        )
        assert session.authority.snapshot().program_model == before
        rejected = session.client.delete_program_class(declarations[0].id)
        assert isinstance(rejected, CommandRejected)
        assert rejected.code == "PROGRAM_CLASS_NOT_FOUND"
        assert session.authority.snapshot().program_model == before
    finally:
        session.close()


def test_module_expression_search_replace_is_identity_targeted_and_one_undo():
    session = ProjectSession.new()
    try:
        module = session.authority.snapshot().program_model.modules[0]
        declarations = parse_python_declarations(module.id, 'FIRST = "needle"\nSECOND = "needle"')
        assert isinstance(
            session.client.put_program_module(replace(module, body=(*declarations, *module.body))),
            CommandAccepted,
        )
        before = session.authority.snapshot()
        expressions = tuple(item.id for item in program_expressions(before.program_model.modules))
        matches = tuple(
            item for item in search_project(before, "needle") if item.kind == "program_declaration"
        )
        assert len(matches) == 2
        commands = replacement_commands(
            before, tuple((item, item.text.replace("needle", "changed")) for item in matches)
        )
        assert isinstance(session.client.transaction(commands), CommandAccepted)
        changed = session.authority.snapshot()
        assert not search_project(changed, "needle")
        assert len(search_project(changed, "changed")) == 2
        assert (
            tuple(item.id for item in program_expressions(changed.program_model.modules))
            == expressions
        )
        assert isinstance(session.client.undo(), CommandAccepted)
        assert session.authority.snapshot().program_model == before.program_model
        assert isinstance(session.client.redo(), CommandAccepted)
        assert session.authority.snapshot().program_model == changed.program_model
    finally:
        session.close()


def test_signature_redo_restores_parameter_and_expression_identities_exactly():
    from code_visualizer.application.drakon_program_adapter import function_spec
    from code_visualizer.domain.program_signatures import ParameterSpec

    session = ProjectSession.new()
    try:
        model = session.authority.snapshot().program_model
        function = model.functions[0]
        signature = replace(
            function_spec(function, model),
            parameters=(ParameterSpec("value", annotation="int", default="7"),),
        )
        assert isinstance(
            session.client.replace_program_function_signature(function.id, signature),
            CommandAccepted,
        )
        changed = session.authority.snapshot().program_model
        assert isinstance(session.client.undo(), CommandAccepted)
        assert session.authority.snapshot().program_model == model
        assert isinstance(session.client.redo(), CommandAccepted)
        assert session.authority.snapshot().program_model == changed
    finally:
        session.close()


@pytest.mark.parametrize("scope", ("module", "class", "startup"))
def test_linked_calls_in_every_canonical_owner_prevent_target_deletion(scope):
    from code_visualizer.domain.program import ExpressionRole, ProgramCall, make_program_expression

    session = ProjectSession.new()
    try:
        model = session.authority.snapshot().program_model
        function = model.functions[0]
        call = ProgramCall(
            "call:main",
            make_program_expression("call:main", "expression", "main", ExpressionRole.CALL),
            make_program_expression("call:main", "arguments", "", ExpressionRole.ARGUMENTS),
            target_function_id=function.id,
        )
        module = model.modules[0]
        if scope == "startup":
            configured = session.client.configure_entrypoint(
                replace(model.entrypoint, startup=(call,))
            )
        else:
            declaration = (
                ProgramClass("class:caller", "Caller", (call,)) if scope == "class" else call
            )
            configured = session.client.put_program_module(
                replace(module, body=(*module.body, declaration))
            )
        assert isinstance(configured, CommandAccepted)
        before = session.authority.snapshot()
        result = session.client.delete_program_function(function.id)
        assert isinstance(result, CommandRejected)
        assert result.code == "PROGRAM_FUNCTION_IN_USE"
        assert session.authority.snapshot() == before
    finally:
        session.close()


def test_unchanged_declaration_text_preserves_complete_imported_syntax():
    from code_visualizer.application.python_authoring import edit_declaration_text
    from code_visualizer.domain.program import ProgramModel

    declarations = parse_python_declarations(
        "module:comments", "def typed(value): # type: (int) -> int\n    return value"
    )
    model = ProgramModel(modules=(ProgramModule("module:comments", "typed", declarations),))
    expression = next(program_expressions(model.modules))
    assert "# type: (int) -> int" in expression.source
    assert edit_declaration_text(model, expression.id, "source", expression.source) == model


def test_class_type_parameters_are_indexed_by_their_canonical_syntax_ids():
    from code_visualizer.domain.expression import expression_identity_ids

    session = ProjectSession.new()
    try:
        module = session.authority.snapshot().program_model.modules[0]
        declarations = parse_python_declarations(module.id, "class Box[T: int]:\n    value: T = 7")
        declaration = declarations[0]
        assert isinstance(declaration, ProgramClass)
        assert isinstance(
            session.client.put_program_module(replace(module, body=(*module.body, declaration))),
            CommandAccepted,
        )
        for parameter in declaration.type_parameters:
            for identity in expression_identity_ids(parameter):
                assert session.kernel.queries.semantic_object(identity) is not None
    finally:
        session.close()


def test_nested_module_statements_keep_their_own_semantic_nodes_and_call_origins():
    from code_visualizer.domain.program import (
        ExpressionRole,
        ProgramCall,
        ProgramIf,
        ProgramSequence,
        make_program_expression,
    )
    from code_visualizer.domain.semantic import SemanticObjectKind, SemanticRelationKind

    session = ProjectSession.new()
    try:
        model = session.authority.snapshot().program_model
        function = model.functions[0]
        call = ProgramCall(
            "call:nested",
            make_program_expression("call:nested", "expression", "main", ExpressionRole.CALL),
            make_program_expression("call:nested", "arguments", "", ExpressionRole.ARGUMENTS),
            target_function_id=function.id,
        )
        condition = ProgramIf(
            "if:module",
            make_program_expression("if:module", "condition", "True", ExpressionRole.CONDITION),
            ProgramSequence("sequence:yes", (call,)),
            ProgramSequence("sequence:no", ()),
        )
        module = model.modules[0]
        assert isinstance(
            session.client.put_program_module(replace(module, body=(*module.body, condition))),
            CommandAccepted,
        )
        queries = session.kernel.queries
        assert queries.semantic_object(call.id).kind is SemanticObjectKind.OPERATION
        assert queries.semantic_object(call.id).parent_id == condition.true_branch.id
        assert queries.semantic_object(call.arguments.id).parent_id == call.id
        assert any(
            relation.kind is SemanticRelationKind.CALLS
            and relation.source_id == module.id
            and relation.target_id == function.id
            for relation in queries.program.relations
        )
    finally:
        session.close()
