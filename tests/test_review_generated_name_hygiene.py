"""External review regressions for programmodel(20260910-074437).zip.

Run from the extracted project root with PYTHONPATH=src:
    python -m pytest /path/to/test_review_generated_name_hygiene.py -q

These tests express required behavior and FAIL on the reviewed snapshot.
They do not patch the implementation or modify existing tests.
"""
from dataclasses import replace

import pytest

from code_visualizer.application.project_factory import create_default_project
from code_visualizer.domain.program import (
    ExpressionRole, ProgramDelay, ProgramOutput, make_program_expression,
)
from code_visualizer.domain.python_declarations import parse_python_declarations
from code_visualizer.execution import run_project, trace_project
from code_visualizer.generation import generate_python_project
from code_visualizer.validation import assess_project


def _project_with_output():
    project = create_default_project()
    function = project.program_model.functions[0]
    output = ProgramOutput(
        'review:output',
        make_program_expression(
            'review:output', 'value', repr('ENTRYPOINT RAN'), ExpressionRole.VALUE,
        ),
    )
    function = replace(function, body=replace(function.body, statements=(output,)))
    return replace(
        project, documents=(), drakon_views=(),
        program_model=replace(project.program_model, functions=(function,)),
    )


def _assert_output(project, mode):
    assert assess_project(project).diagnostics == ()
    emitted = generate_python_project(project)
    result = run_project(emitted) if mode == 'run' else trace_project(emitted).run
    assert result.return_code == 0, result.stderr
    assert result.stdout == 'ENTRYPOINT RAN\n'


@pytest.mark.parametrize('mode', ('run', 'trace'))
@pytest.mark.parametrize('startup_source', (
    '_entrypoint = 7',
    '_entrypoint = lambda: print("WRONG FUNCTION")',
))
def test_authored_startup_cannot_replace_selected_callable(startup_source, mode):
    project = _project_with_output()
    startup = parse_python_declarations(
        'review:startup', startup_source, identity_namespace='review:startup',
    )
    model = project.program_model
    project = replace(project, program_model=replace(
        model, entrypoint=replace(model.entrypoint, startup=startup),
    ))
    _assert_output(project, mode)


@pytest.mark.parametrize('mode', ('run', 'trace'))
def test_authored_module_binding_cannot_replace_generated_timer_dependency(mode):
    project = _project_with_output()
    model = project.program_model
    function = model.functions[0]
    delay = ProgramDelay(
        'review:delay',
        make_program_expression('review:delay', 'seconds', '0.0', ExpressionRole.VALUE),
        False,
    )
    function = replace(function, body=replace(
        function.body, statements=(delay, *function.body.statements),
    ))
    module = model.modules[0]
    declarations = parse_python_declarations(
        'review:module', '_cv_time = 7', identity_namespace='review:module',
    )
    module = replace(module, body=(*declarations, *module.body))
    project = replace(project, program_model=replace(
        model, functions=(function,), modules=(module,),
    ))
    _assert_output(project, mode)
