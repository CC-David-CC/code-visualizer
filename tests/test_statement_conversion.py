from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.session import ProjectSession
from code_visualizer.application.statement_conversion import (
    StatementConversionError,
    convert_simple_statement,
)
from code_visualizer.domain.drakon import (
    Action,
    Assignment,
    Call,
    Input,
    Output,
)


def test_conversion_recognizes_typed_assignment_input_output_and_call() -> None:
    assignment = convert_simple_statement(Action("a", "total += 1"))
    assert isinstance(assignment, Assignment)
    assert (assignment.target, assignment.operator, assignment.value) == ("total", "+=", "1")

    user_input = convert_simple_statement(Action("b", 'answer: int = int(input("Value: "))'))
    assert isinstance(user_input, Input)
    assert (user_input.target, user_input.annotation, user_input.converter) == (
        "answer",
        "int",
        "int",
    )
    assert user_input.prompt == "'Value: '"

    output = convert_simple_statement(Action("c", 'print("Hello", end="!")'))
    assert isinstance(output, Output)
    assert (output.expression, output.end) == ("'Hello'", "'!'")

    call = convert_simple_statement(Action("d", "result = helper(2)"))
    assert isinstance(call, Call)
    assert (call.result_target, call.expression) == ("result", "helper(2)")


def test_compound_statement_conversion_is_explicitly_rejected() -> None:
    try:
        convert_simple_statement(Action("compound", "if ready:\n    run()"))
    except StatementConversionError as exc:
        assert "compound" in str(exc).casefold()
    else:
        raise AssertionError("A compound statement must use a structural insertion command")


def test_sdk_conversion_preserves_id_is_one_revision_and_undoes() -> None:
    session = ProjectSession.new()
    try:
        diagram = session.authority.snapshot().documents[0]
        inserted = session.client.insert_drakon_atom(
            diagram.id,
            "action",
            0,
            source='print("converted")',
        )
        assert isinstance(inserted, CommandAccepted)
        atom = session.authority.snapshot().documents[0].body.atoms[0]
        revision = session.authority.revision

        converted = session.client.convert_drakon_statement(diagram.id, atom.id)

        assert isinstance(converted, CommandAccepted)
        assert session.authority.revision == revision + 1
        replacement = session.authority.snapshot().documents[0].body.atoms[0]
        assert isinstance(replacement, Output)
        assert replacement.id == atom.id
        assert isinstance(session.client.undo(), CommandAccepted)
        restored = session.authority.snapshot().documents[0].body.atoms[0]
        assert isinstance(restored, Action)
        assert restored.source == "print('converted')"
    finally:
        session.close()
