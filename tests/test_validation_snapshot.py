"""Assessment uses derived flow without accepting stale presentation semantics."""

from dataclasses import replace

from code_visualizer.application.project_factory import create_default_project
from code_visualizer.application.scale_fixture import build_scale_project
from code_visualizer.domain.program import ProgramTransfer
from code_visualizer.domain.program_kinds import TransferKind
from code_visualizer.validation import assess_project, validate_project


def test_flow_assessment_uses_canonical_body_and_keeps_global_identity_checks():
    project = create_default_project()
    function = project.program_model.functions[0]
    illegal = ProgramTransfer("outside-loop", TransferKind.BREAK, None, None)
    function = replace(function, body=replace(function.body, statements=(illegal,)))
    program = replace(project.program_model, functions=(function,))
    project = replace(project, program_model=program)
    # The existing empty DRAKON body is deliberately stale and contains no break.
    assert not project.documents[0].body.atoms
    assessment = assess_project(project, function_ids=frozenset((function.id,)))
    assert not assessment.buildable
    assert any(
        item.code == "PY_LOOP_TRANSFER_OUTSIDE_LOOP" and item.object_id == illegal.id
        for item in assessment.diagnostics
    )
    assert assessment.diagnostics == validate_project(project)
    # An illegal ownership identity remains blocking even in a focused assessment.
    duplicate = replace(program.modules[0], id=function.id)
    colliding = replace(project, program_model=replace(program, modules=(duplicate,)))
    assert any(
        item.code == "PROGRAM_DUPLICATE_OWNERSHIP"
        for item in assess_project(
            colliding, function_ids=frozenset((function.id,))
        ).blocking_diagnostics
    )


def test_ambiguous_view_binding_cannot_substitute_another_functions_flow():
    project = build_scale_project(2)
    first, second = project.program_model.functions
    illegal = ProgramTransfer("first:outside-loop", TransferKind.BREAK, None, None)
    first = replace(first, body=replace(first.body, statements=(illegal,)))
    first_view, second_view = project.drakon_views
    project = replace(
        project,
        program_model=replace(project.program_model, functions=(first, second)),
        drakon_views=(
            first_view,
            replace(second_view, document_id=first_view.document_id),
        ),
    )
    assessment = assess_project(project)
    assert not assessment.buildable
    assert any(item.code == "PROGRAM_DUPLICATE_DRAKON_VIEW" for item in assessment.diagnostics)
    assert any(
        item.code == "PY_LOOP_TRANSFER_OUTSIDE_LOOP" and item.object_id == illegal.id
        for item in assessment.diagnostics
    )
