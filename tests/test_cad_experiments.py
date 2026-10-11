"""P4 uses P2's real dirty Git and retained history, including edits during publication."""

import json
from dataclasses import replace

import pytest
from test_git_experiments import finish_edit, git, untouched

from code_visualizer.application.cad_examples import recipe_request, spring_cad_project
from code_visualizer.application.computation import execute_computation
from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.domain_commands import SetDomainProperty
from code_visualizer.application.experiment_inputs import INPUT_MANIFEST
from code_visualizer.application.git_service import GitProjectController
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.domain.program import ExpressionRole, ProgramAction, make_program_expression
from code_visualizer.domain.values import QuantityValue
from code_visualizer.extensions.cad.native import decode_solid
from code_visualizer.extensions.foundations.equations import identity
from code_visualizer.extensions.foundations.units_si import si_catalog
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.store import ProjectStore


def equation_request(session):
    project = session.authority.snapshot()
    return ComputationRequest(
        project.id, project.revision, "foundation.math.linear_equations", "1", "spring:equations"
    )


def test_cad_published_while_editing_retained_after_cleanup_and_restart(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "P4 proof")
    git(root, "config", "user.email", "p4@example.invalid")
    project = spring_cad_project()
    function = project.program_model.functions[0]
    pause = ProgramAction(
        "cad:pause",
        make_program_expression(
            "cad:pause",
            "code",
            "import time\ntime.sleep(15)",
            ExpressionRole.STATEMENTS,
            identity_namespace="p4-proof",
        ),
    )
    function = replace(
        function, body=replace(function.body, statements=(*function.body.statements, pause))
    )
    project = replace(project, program_model=replace(project.program_model, functions=(function,)))
    ProjectStore(root / "project").initialize(project)
    for name in ("staged.txt", "unstaged.txt", "selected.py"):
        (root / name).write_bytes(b"initial\n")
    git(root, "add", "project/project.json", "staged.txt", "unstaged.txt", "selected.py")
    git(root, "commit", "-m", "Independent original history")
    (root / "staged.txt").write_bytes(b"staged\n")
    git(root, "add", "staged.txt")
    (root / "staged.txt").write_bytes(b"unstaged too\n")
    (root / "unstaged.txt").write_bytes(b"unstaged\n")
    (root / "untracked.txt").write_bytes(b"untracked\n")
    service = ComputationService()
    original = ProjectSession.open(root / "project", computations=service)
    controller = GitProjectController(original)
    editors = [original]
    try:
        before = untouched(root)
        solution = execute_computation(original.kernel, equation_request(original))
        assert solution.outcome is ComputationOutcome.SUCCEEDED, solution.diagnostics
        first = controller.freeze_and_run(recipe_request(project, solution.artifacts[0].resource))
        editors.append(first.editor)
        job = service.job(first.computation.id)
        with job.condition:
            assert job.condition.wait_for(lambda: bool(job.publications) or job.done.is_set(), 120)
            assert job.publications, job.error or job.view.diagnostic
            publication = next(iter(job.publications.values()))
        assert not job.done.is_set()
        retained_root = controller.experiments.store.root
        retained = ResourceStore(retained_root)
        old_bytes = retained.read(publication.artifact.resource)
        old_header, old_shape = decode_solid(old_bytes)
        assert pytest.approx(50) == old_shape.bounding_box().size.X
        old_editor = controller.session
        count_before = len(list((retained_root / "variants").glob("*.json")))
        command = SetDomainProperty(
            "spring:equations",
            "spring:F:binding",
            identity("Binding", "value"),
            QuantityValue(12, si_catalog().unit("foundation.units.si:newton")),
        )
        child = finish_edit(controller, old_editor.client.submit(command))
        editors.append(child.editor)
        assert child.editor.experiment_context.attempt_id is None
        assert len(list((retained_root / "variants").glob("*.json"))) == count_before + 1
        assert isinstance(child.editor.client.undo(), CommandAccepted)
        assert isinstance(child.editor.client.redo(), CommandAccepted)
        old_evidence = service.wait(first.computation.id)
        assert old_evidence.outcome is ComputationOutcome.SUCCEEDED, old_evidence.diagnostics
        assert not child.editor.kernel.current_runtime_ids()
        assert old_header.origins.revision == first.computation.revision
        solved = controller.freeze_and_run(equation_request(child.editor))
        new_solution = service.wait(solved.computation.id)
        assert new_solution.outcome is ComputationOutcome.SUCCEEDED, new_solution.diagnostics
        new_project = controller.session.authority.snapshot()
        second = controller.freeze_and_run(
            recipe_request(new_project, new_solution.artifacts[0].resource)
        )
        editors.append(second.editor)
        new_evidence = service.wait(second.computation.id)
        assert new_evidence.outcome is ComputationOutcome.SUCCEEDED, new_evidence.diagnostics
        new_reference = new_evidence.artifacts[0].resource
        _, new_shape = decode_solid(retained.read(new_reference))
        assert pytest.approx(60) == new_shape.bounding_box().size.X
        assert first.attempt.commit != second.attempt.commit
        assert new_reference != publication.artifact.resource
        assert retained.read(publication.artifact.resource) == old_bytes
        assert untouched(root) == before
        manifest = json.loads(git(root, "show", f"{first.attempt.commit}:{INPUT_MANIFEST}"))
        dependencies = manifest["environment"]["application"]["distributions"]
        assert any(d["name"] == "build123d" and d["version"] == "0.11.1" for d in dependencies)
        assert manifest["request"]["inputs"][0]["name"] == "solution"
        assert git(root, "ls-tree", "-r", "--name-only", first.attempt.commit).splitlines() == [
            INPUT_MANIFEST,
            "project/project.json",
        ]
        old_editor.close()
        controller.experiments.remove_worktree(first.attempt.variant_id)
        assert not old_editor.root.exists()
        active_root = controller.session.root
        controller.close_background(wait=True)
        controller.session.close()
        service.close()
        service = ComputationService()
        reopened = ProjectSession.open(active_root, computations=service)
        controller = GitProjectController(reopened)
        editors.append(reopened)
        assert reopened.experiment_context.attempt_id == second.attempt.id
        inspector = controller.experiments.reopen_run(first.attempt.id)
        assert inspector.read_only
        assert inspector.kernel.resource_store.read(publication.artifact.resource) == old_bytes
        inspector.close()
        assert EvidenceStore(retained_root).get(old_evidence.id) == old_evidence
        retry = controller.freeze_and_run(
            recipe_request(reopened.authority.snapshot(), new_solution.artifacts[0].resource)
        )
        assert retry.attempt.commit == second.attempt.commit
        assert retry.attempt.id != second.attempt.id
        assert service.wait(retry.computation.id).outcome is ComputationOutcome.SUCCEEDED
    finally:
        controller.close_background(wait=True)
        controller.session.close()
        for editor in editors:
            editor.close()
        service.close()
