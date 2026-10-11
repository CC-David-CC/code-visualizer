from code_visualizer.application.messages import CommandEnvelope, EventEnvelope


def test_command_envelope_carries_concurrency_identity() -> None:
    command = CommandEnvelope(
        command_type="project.rename",
        actor_id="human",
        operation_id="op-1",
        project_id="project-1",
        expected_revision=4,
        payload={"title": "New title"},
        intent="Rename the project",
    )

    assert command.expected_revision == 4
    assert command.actor_id == "human"
    assert command.payload == {"title": "New title"}


def test_event_envelope_carries_revision_and_actor() -> None:
    event = EventEnvelope.now(
        event_type="project.renamed",
        actor_id="agent",
        operation_id="op-2",
        project_id="project-1",
        revision=5,
        payload={"title": "New title"},
    )

    assert event.revision == 5
    assert event.actor_id == "agent"
    assert event.occurred_at
