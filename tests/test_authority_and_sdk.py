from code_visualizer.application.commands import CreateDiagram, RenameProject
from code_visualizer.application.headless import HeadlessService
from code_visualizer.application.messages import CommandAccepted, CommandRejected
from code_visualizer.domain.common import DocumentKind
from code_visualizer.domain.drakon import If


def test_two_clients_observe_events_and_stale_revision_conflicts(tmp_path) -> None:
    service = HeadlessService.create(tmp_path / "project")
    human = service.client("human")
    agent = service.client("agent")
    try:
        renamed = human.rename_project(
            "Shared Project",
            expected_revision=0,
            operation_id="human-rename",
        )
        assert isinstance(renamed, CommandAccepted)
        assert renamed.revision == 1
        assert [event.event_type for event in human.events] == ["project.renamed"]
        assert [event.event_type for event in agent.events] == ["project.renamed"]

        stale = agent.create_diagram(
            DocumentKind.MIND_MAP,
            "Plan",
            expected_revision=0,
            operation_id="agent-stale",
        )
        assert isinstance(stale, CommandRejected)
        assert stale.code == "REVISION_CONFLICT"
        assert service.authority.revision == 1

        created = agent.create_diagram(
            DocumentKind.MIND_MAP,
            "Plan",
            operation_id="agent-create",
        )
        assert isinstance(created, CommandAccepted)
        assert created.revision == 2
        assert len(human.events) == 2
        assert len(agent.events) == 2
    finally:
        human.close()
        agent.close()
        service.close()

    reopened = HeadlessService.open(tmp_path / "project")
    try:
        assert reopened.authority.snapshot().title == "Shared Project"
        assert len(reopened.authority.snapshot().documents) == 2
        assert reopened.authority.revision == 2
    finally:
        reopened.close()


def test_operation_id_is_idempotent_without_duplicate_event(tmp_path) -> None:
    service = HeadlessService.create(tmp_path / "project")
    client = service.client("human")
    try:
        first = client.rename_project(
            "Once",
            expected_revision=0,
            operation_id="same-operation",
        )
        second = client.rename_project(
            "Ignored duplicate payload",
            expected_revision=0,
            operation_id="same-operation",
        )

        assert first == second
        assert service.authority.snapshot().title == "Once"
        assert service.authority.revision == 1
        assert len(client.events) == 1
    finally:
        client.close()


def test_transaction_commits_multiple_commands_as_one_revision(tmp_path) -> None:
    service = HeadlessService.create(tmp_path / "project")
    client = service.client("human")
    try:
        result = client.transaction(
            (
                RenameProject("Transactional"),
                CreateDiagram(DocumentKind.FREEFORM, "Canvas"),
            ),
            operation_id="transaction-1",
        )

        assert isinstance(result, CommandAccepted)
        assert result.revision == 1
        assert len(result.events) == 2
        assert service.authority.snapshot().title == "Transactional"
        assert len(service.authority.snapshot().documents) == 2

        undone = client.undo(operation_id="transaction-undo")
        assert isinstance(undone, CommandAccepted)
        assert service.authority.snapshot().title == "Untitled Project"
        assert len(service.authority.snapshot().documents) == 1

        redone = client.redo(operation_id="transaction-redo")
        assert isinstance(redone, CommandAccepted)
        assert service.authority.snapshot().title == "Transactional"
        assert len(service.authority.snapshot().documents) == 2
    finally:
        client.close()


def test_actor_undo_preserves_disjoint_later_edit_and_redo_restores(tmp_path) -> None:
    service = HeadlessService.create(tmp_path / "project")
    human = service.client("human")
    agent = service.client("agent")
    try:
        assert isinstance(
            human.rename_project("Human title", operation_id="human-title"),
            CommandAccepted,
        )
        assert isinstance(
            agent.create_diagram(
                DocumentKind.MIND_MAP,
                "Agent plan",
                operation_id="agent-plan",
            ),
            CommandAccepted,
        )

        undone = human.undo(operation_id="human-undo")
        assert isinstance(undone, CommandAccepted)
        assert service.authority.snapshot().title == "Untitled Project"
        assert len(service.authority.snapshot().documents) == 2

        redone = human.redo(operation_id="human-redo")
        assert isinstance(redone, CommandAccepted)
        assert service.authority.snapshot().title == "Human title"
        assert len(service.authority.snapshot().documents) == 2
    finally:
        human.close()
        agent.close()


def test_actor_undo_rejects_intersecting_later_edit(tmp_path) -> None:
    service = HeadlessService.create(tmp_path / "project")
    human = service.client("human")
    agent = service.client("agent")
    try:
        human.rename_project("Human title", operation_id="human-title")
        agent.rename_project("Agent title", operation_id="agent-title")

        result = human.undo(operation_id="human-undo")

        assert isinstance(result, CommandRejected)
        assert result.code == "UNDO_CONFLICT"
        assert service.authority.snapshot().title == "Agent title"
    finally:
        human.close()
        agent.close()


def test_history_and_idempotency_restore_from_journal(tmp_path) -> None:
    root = tmp_path / "project"
    first_service = HeadlessService.create(root)
    first_client = first_service.client("human")
    first_client.rename_project("Persisted", operation_id="rename-persisted")
    first_client.close()
    first_service.close()

    second_service = HeadlessService.open(root)
    second_client = second_service.client("human")
    try:
        duplicate = second_client.rename_project(
            "Must not replace",
            expected_revision=0,
            operation_id="rename-persisted",
        )
        assert isinstance(duplicate, CommandAccepted)
        assert second_service.authority.snapshot().title == "Persisted"

        undone = second_client.undo(operation_id="undo-after-restart")
        assert isinstance(undone, CommandAccepted)
        assert second_service.authority.snapshot().title == "Untitled Project"
    finally:
        second_client.close()
        second_service.close()


def test_actor_undo_conflict_information_survives_restart(tmp_path) -> None:
    root = tmp_path / "project"
    service = HeadlessService.create(root)
    human = service.client("human")
    agent = service.client("agent")
    human.rename_project("Human", operation_id="human-title")
    agent.rename_project("Agent", operation_id="agent-title")
    human.close()
    agent.close()
    service.close()

    reopened = HeadlessService.open(root)
    client = reopened.client("human")
    try:
        result = client.undo(operation_id="human-undo-after-restart")
        assert isinstance(result, CommandRejected)
        assert result.code == "UNDO_CONFLICT"
        assert reopened.authority.snapshot().title == "Agent"
    finally:
        client.close()
        reopened.close()


def test_structured_if_undo_redo_preserves_all_stable_ids(tmp_path) -> None:
    service = HeadlessService.create(tmp_path / "project")
    client = service.client("human")
    try:
        diagram = service.authority.snapshot().documents[0]
        inserted = client.insert_drakon_atom(
            diagram.id,
            "if",
            0,
            operation_id="insert-if",
        )
        assert isinstance(inserted, CommandAccepted)
        decision = service.authority.snapshot().documents[0].body.atoms[0]
        assert isinstance(decision, If)
        stable_ids = (
            decision.id,
            decision.true_branch.id,
            decision.true_branch.atoms[0].id,
            decision.false_branch.id,
            decision.false_branch.atoms[0].id,
        )

        assert isinstance(client.undo(operation_id="undo-if"), CommandAccepted)
        assert not service.authority.snapshot().documents[0].body.atoms
        assert isinstance(client.redo(operation_id="redo-if"), CommandAccepted)

        restored = service.authority.snapshot().documents[0].body.atoms[0]
        assert isinstance(restored, If)
        assert (
            restored.id,
            restored.true_branch.id,
            restored.true_branch.atoms[0].id,
            restored.false_branch.id,
            restored.false_branch.atoms[0].id,
        ) == stable_ids
    finally:
        client.close()
