"""Generated bindings preserve lexical references and the existing helper environment."""

from dataclasses import replace

import pytest

from code_visualizer.application.project_factory import create_default_project
from code_visualizer.domain.invocation import InvocationSpec
from code_visualizer.domain.program import (
    ExpressionRole,
    ProgramAction,
    ProgramCall,
    ProgramDelay,
    ProgramOutput,
    make_program_expression,
)
from code_visualizer.domain.program_kinds import CallableKind
from code_visualizer.domain.python_declarations import parse_python_declarations
from code_visualizer.domain.python_symbols import PythonSymbolAllocator, python_identifiers
from code_visualizer.execution import run_project, run_source, trace_project, trace_source
from code_visualizer.generation import generate_python_project
from code_visualizer.persistence.serialization import normalized_project_json
from code_visualizer.validation import assess_project


def _expression(owner, source, role=ExpressionRole.VALUE):
    return make_program_expression(owner, role.value, source, role)


def _project(module_source, statements):
    project = create_default_project()
    model = project.program_model
    function = replace(
        model.functions[0], body=replace(model.functions[0].body, statements=statements)
    )
    module = model.modules[0]
    module = replace(
        module,
        body=(
            *parse_python_declarations(module.id, module_source, identity_namespace="scope:module"),
            *module.body,
        ),
    )
    return replace(
        project,
        documents=(),
        drakon_views=(),
        program_model=replace(model, functions=(function,), modules=(module,)),
    )


def _execute(project, mode):
    assert assess_project(project).diagnostics == ()
    before = normalized_project_json(project)
    generated = generate_python_project(project)
    assert generated == generate_python_project(project)
    result = run_project(generated) if mode == "run" else trace_project(generated).run
    assert result.return_code == 0, result.stderr
    assert not result.stderr
    assert normalized_project_json(project) == before
    return result.stdout


@pytest.mark.parametrize("mode", ("run", "trace"))
def test_helper_initial_binding_preserves_defaults_class_order_and_private_names(mode):
    project = _project(
        "def captured(clock=_cv_time):\n"
        "    return clock.__name__\n"
        "class Authored:\n"
        "    __clock = _cv_time\n"
        "    before = _cv_time.__name__\n"
        "    _cv_time = 'class shadow'\n"
        "    after = _cv_time\n"
        "    @staticmethod\n"
        "    def snapshot():\n"
        "        return Authored.__clock.__name__\n"
        "_cv_time = 'module shadow'",
        (
            ProgramDelay("scope:delay", _expression("scope:delay", "0.0"), False),
            ProgramOutput(
                "scope:output",
                _expression(
                    "scope:output",
                    "(captured(), Authored.before, Authored.after, Authored.snapshot(), _cv_time)",
                ),
            ),
        ),
    )
    assert _execute(project, mode) == "('time', 'time', 'class shadow', 'time', 'module shadow')\n"


@pytest.mark.parametrize("mode", ("run", "trace"))
def test_authored_helper_override_remains_explicit_while_generated_delay_uses_its_dependency(mode):
    project = _project(
        "calls = []\n"
        "class Recorder:\n"
        "    @staticmethod\n"
        "    def sleep(value):\n"
        "        calls.append(value)",
        (
            ProgramAction(
                "scope:local",
                _expression("scope:local", "_cv_time = Recorder()", ExpressionRole.STATEMENTS),
            ),
            ProgramDelay("scope:delay", _expression("scope:delay", "0.0"), False),
            ProgramCall(
                "scope:call",
                _expression("scope:call", "_cv_time.sleep(7)"),
                _expression("scope:call", "", ExpressionRole.ARGUMENTS),
            ),
            ProgramOutput("scope:output", _expression("scope:output", "calls")),
        ),
    )
    assert _execute(project, mode) == "[7]\n"


@pytest.mark.parametrize("kind", (CallableKind.GENERATOR, CallableKind.ASYNC_GENERATOR))
def test_raw_invocation_generator_temporaries_do_not_capture_nested_authored_loads(kind):
    prefix = "async " if kind is CallableKind.ASYNC_GENERATOR else ""
    source = (
        "_cv_item = 'item'\n_cv_asyncio = 'asyncio'\n"
        "_cv_consume_entrypoint = 'consumer'\n_cv_invocation_result = 'result'\n"
        "nested = lambda: (_cv_item, _cv_asyncio, _cv_consume_entrypoint, _cv_invocation_result)\n"
        f"{prefix}def main():\n"
        "    yield 42\n"
        "    print(nested())\n"
    )
    invocation = InvocationSpec("main", kind)
    for result in (
        run_source(source, invocation=invocation),
        trace_source(source, invocation=invocation).run,
    ):
        assert result.return_code == 0, result.stderr
        assert result.stdout == "('item', 'asyncio', 'consumer', 'result')\n"


def test_identifier_allocation_normalizes_lexical_names_without_reserving_literal_text():
    names = python_identifiers(
        "_cv_t\uff49me = 7\n"
        "nested = lambda: _cv_time_2\n"
        "text = '_cv_time_3'  # _cv_time_4 is a comment\n"
    )
    allocator = PythonSymbolAllocator(names)
    assert allocator.allocate("_cv_time") == "_cv_time_3"
    assert allocator.allocate("_cv_time") == "_cv_time_4"
    with pytest.raises(ValueError, match="identifier"):
        allocator.allocate("\uff43\uff4c\uff41\uff53\uff53")
