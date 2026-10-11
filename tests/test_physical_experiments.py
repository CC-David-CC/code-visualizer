"""P3 physical evidence uses the real P2 freeze/fork/retention transaction."""

import pytest
from test_git_experiments import finish_edit, git, untouched

from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.domain_commands import CreateDomainNode, SetDomainProperty
from code_visualizer.application.experiment_comparison import _difference, compare_retained_runs
from code_visualizer.application.git import GitError
from code_visualizer.application.git_service import GitProjectController
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.physical_examples import dc_divider_project
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.domain.intentional import IntentionalNode, PropertyValue, RoleBinding
from code_visualizer.domain.transformation import derived_id
from code_visualizer.domain.values import QuantityValue
from code_visualizer.extensions.dc import TRANSFORMATION, identity
from code_visualizer.extensions.foundations.equations import BACKEND_ID
from code_visualizer.extensions.foundations.unit_algebra_si import algebra_si_catalog
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.store import ProjectStore


@pytest.fixture
def physical_experiment(tmp_path):
    pytest.importorskip("numpy")
    pytest.importorskip("sympy")
    pytest.importorskip("pint")
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "P3 physical proof")
    git(root, "config", "user.email", "p3@example.invalid")
    ProjectStore(root / "project").initialize(dc_divider_project())
    for name in ("staged.txt", "unstaged.txt", "selected.py"):
        (root / name).write_text("initial\n", encoding="utf-8")
    git(root, "add", "project/project.json", "staged.txt", "unstaged.txt", "selected.py")
    git(root, "commit", "-m", "Original authored circuit and unrelated work")
    (root / "staged.txt").write_text("staged\n", encoding="utf-8")
    git(root, "add", "staged.txt")
    (root / "staged.txt").write_text("also unstaged\n", encoding="utf-8")
    (root / "unstaged.txt").write_text("unstaged\n", encoding="utf-8")
    (root / "untracked.txt").write_text("untracked\n", encoding="utf-8")
    host = ComputationService()
    session = ProjectSession.open(root / "project", computations=host)
    controller = GitProjectController(session)
    try:
        yield controller, session, host, root
    finally:
        controller.close_background(wait=True)
        controller.session.close()
        session.close()
        host.close()


def physical_request(session):
    project = session.authority.snapshot()
    return ComputationRequest(project.id, project.revision, BACKEND_ID, "1", "dc:network")


def load_commands():
    resistor = IntentionalNode(
        "dc:load",
        identity("Resistor"),
        (
            PropertyValue(identity("Resistor", "name"), "Load"),
            PropertyValue(
                identity("Resistor", "resistance"),
                QuantityValue(1000, algebra_si_catalog().unit("foundation.units.si:ohm")),
            ),
        ),
    )
    commands = [
        CreateDomainNode("dc:network", resistor, "dc:circuit", identity("Circuit", "components"))
    ]
    for role, net in (("positive", "dc:middle"), ("negative", "dc:ground")):
        commands.append(
            CreateDomainNode(
                "dc:network",
                IntentionalNode(
                    "dc:load:" + role,
                    identity("Terminal"),
                    (PropertyValue(identity("Terminal", "name"), "Load " + role),),
                    references=(RoleBinding(identity("Terminal", "net"), (net,)),),
                ),
                "dc:load",
                identity("Resistor", role),
            )
        )
    return tuple(commands)


def midpoint_row(comparison):
    wanted = derived_id(TRANSFORMATION.key, "dc:middle", "potential") + ":solution"
    return next(row for row in comparison["rows"] if row["observation_id"] == wanted)


def test_p3_dirty_git_fork_solve_compare_remove_reopen(physical_experiment):
    controller, original, host, root = physical_experiment
    before = untouched(root)
    first = controller.freeze_and_run(physical_request(original))
    first_evidence = host.wait(first.computation.id)
    assert first_evidence.outcome is ComputationOutcome.SUCCEEDED
    predecessor = controller.session
    child = finish_edit(controller, predecessor.client.transaction(load_commands()))
    assert child.editor.authority.snapshot().domain_workspace.node("dc:load") is not None
    assert predecessor.authority.snapshot().domain_workspace.node("dc:load") is None
    assert isinstance(child.editor.client.undo(), CommandAccepted)
    assert child.editor.authority.snapshot().domain_workspace.node("dc:load") is None
    assert isinstance(child.editor.client.redo(), CommandAccepted)
    assert isinstance(
        child.editor.client.submit(
            SetDomainProperty("dc:network", "dc:load", identity("Resistor", "name"), "RL")
        ),
        CommandAccepted,
    )
    assert len(list((controller.experiments.store.root / "variants").glob("*.json"))) == 2
    second = controller.freeze_and_run(physical_request(child.editor))
    second_evidence = host.wait(second.computation.id)
    assert second_evidence.outcome is ComputationOutcome.SUCCEEDED
    assert first.attempt.commit != second.attempt.commit
    comparison = controller.execute(
        "compare_runs", {"left_id": first.attempt.id, "right_id": second.attempt.id}
    )
    row = midpoint_row(comparison)
    assert row["left"]["magnitude"] == pytest.approx(2.5)
    assert row["right"]["magnitude"] == pytest.approx(5 / 3)
    assert row["difference"]["magnitude"] == pytest.approx(-5 / 6)
    assert "dc:middle" in row["semantic_ids"]
    assert untouched(root) == before
    assert controller.session.experiment_context.attempt_id == second.attempt.id

    # Old evidence and terminal resources belong to retained history, not this editor.
    retained_root = controller.experiments.store.root
    predecessor.close()
    controller.experiments.remove_worktree(first.attempt.variant_id)
    assert not predecessor.root.exists()
    active_root = controller.session.root
    controller.close_background(wait=True)
    controller.session.close()
    host.close()
    restarted_host = ComputationService()
    reopened = ProjectSession.open(active_root, computations=restarted_host)
    restarted = GitProjectController(reopened)
    try:
        assert reopened.experiment_context.attempt_id == second.attempt.id
        assert (
            compare_retained_runs(restarted.experiments, first.attempt.id, second.attempt.id)
            == comparison
        )
        inspector = restarted.experiments.reopen_run(first.attempt.id)
        assert inspector.read_only
        assert inspector.authority.snapshot().domain_workspace.node("dc:load") is None
        inspector.close()
        assert (
            ResourceStore(retained_root)
            .verified_path(first_evidence.artifacts[0].resource)
            .is_file()
        )
        retry = restarted.freeze_and_run(physical_request(reopened))
        restarted_host.wait(retry.computation.id)
        assert retry.attempt.id != second.attempt.id
        assert retry.attempt.commit == second.attempt.commit
        # A corrupt observation resource cannot be presented as trusted retained evidence.
        resource = ResourceStore(retained_root).verified_path(first_evidence.artifacts[0].resource)
        resource.write_bytes(b"corrupt")
        with pytest.raises(GitError):
            compare_retained_runs(restarted.experiments, first.attempt.id, second.attempt.id)
    finally:
        restarted.close_background(wait=True)
        restarted.session.close()
        restarted_host.close()


def test_retained_difference_uses_both_declared_unit_contexts_and_bounded_values():
    catalog = algebra_si_catalog()
    left = QuantityValue(1, catalog.unit("foundation.units.si:meter"))
    right = QuantityValue(1500, catalog.unit("foundation.units.si:millimeter"))
    delta, note = _difference(left, right, catalog, catalog)
    assert delta == QuantityValue(0.5, left.unit) and not note
    assert _difference(left, right, None, catalog)[0] is None
    assert _difference(-1e308, 1e308, None, None)[0] is None
    assert (
        _difference(
            QuantityValue(-1e308, left.unit), QuantityValue(1e308, left.unit), catalog, catalog
        )[0]
        is None
    )
