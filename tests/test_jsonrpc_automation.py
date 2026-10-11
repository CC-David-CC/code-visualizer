import asyncio

import pytest

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.commands import InsertDrakonAtom, RenameProject, SetDrakonText
from code_visualizer.application.headless import HeadlessService
from code_visualizer.application.messages import CommandAccepted, CommandRejected
from code_visualizer.application.project_factory import create_default_project
from code_visualizer.automation.host import LocalAutomationHost
from code_visualizer.automation.mcp import MCP_TOOLS, McpServerAdapter
from code_visualizer.automation.service import AccessMode, AutomationCapability, AutomationService
from code_visualizer.automation.websocket import AccessGrant, AutomationWebSocketServer
from code_visualizer.domain.program import ProgramModule
from code_visualizer.persistence.serialization import program_module_to_data
from code_visualizer.sdk import AsyncRemoteClient, RemoteRpcError
from code_visualizer.sdk.client import CodeVisualizerClient


async def _wait_for(predicate, *, attempts: int = 100) -> None:
    for _ in range(attempts):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("Timed out waiting for automation event")


def test_live_human_agent_revision_stream_conflict_identity_and_idempotency(tmp_path) -> None:
    service = HeadlessService.create(tmp_path / "shared")
    gui = service.client("desktop-human")
    diagram = service.authority.snapshot().documents[0]
    inserted = gui.insert_drakon_atom(diagram.id, "if", 0, operation_id="initial-if")
    assert isinstance(inserted, CommandAccepted)
    decision_id = service.authority.snapshot().documents[0].body.atoms[0].id
    host = LocalAutomationHost(
        service.authority,
        project_root=lambda: service.store.root,
    ).start()

    async def scenario() -> None:
        async with (
            AsyncRemoteClient(
                host.endpoint,
                host.token,
                actor_id="human",
            ) as human,
            AsyncRemoteClient(
                host.endpoint,
                host.token,
                actor_id="agent",
            ) as agent,
        ):
            await human.subscribe()
            await agent.subscribe()
            semantic = await agent.semantic_object(diagram.id)
            assert semantic is not None
            assert semantic["kind"] == "function"
            architecture = await agent.projection("architecture")
            assert diagram.id in {item["semantic_id"] for item in architecture["nodes"]}
            operations = await agent.list_operations()
            assert "view.architecture" in {item["id"] for item in operations}
            base_revision = human.observed_revision
            changed = await human.submit(
                SetDrakonText(diagram.id, decision_id, "condition", "2 + 2 == 4"),
                operation_id="human-condition",
            )
            assert isinstance(changed, CommandAccepted)
            await _wait_for(lambda: agent.observed_revision == changed.revision)

            added = await agent.submit(
                InsertDrakonAtom(
                    diagram.id,
                    "action",
                    1,
                    source='print("agent action")',
                ),
                operation_id="agent-action",
            )
            assert isinstance(added, CommandAccepted)
            undo_preview = await agent.preview_undo()
            assert undo_preview["can_apply"] is True
            assert undo_preview["target_operation_id"] == "agent-action"
            assert undo_preview["target_revision"] == added.revision
            duplicate = await agent.submit(
                InsertDrakonAtom(
                    diagram.id,
                    "action",
                    1,
                    source='print("must be ignored")',
                ),
                expected_revision=changed.revision,
                operation_id="agent-action",
            )
            assert duplicate == added

            stale = await human.submit(
                RenameProject("Stale rename"),
                expected_revision=base_revision,
                operation_id="human-stale",
            )
            assert isinstance(stale, CommandRejected)
            assert stale.code == "REVISION_CONFLICT"
            await _wait_for(
                lambda: any(event.event_type == "conflict.detected" for event in human.events)
            )

            snapshot = await agent.snapshot()
            decision = snapshot.documents[0].body.atoms[0]
            assert decision.condition == "2 + 2 == 4"
            assert snapshot.documents[0].body.atoms[1].source == "print('agent action')"
            assert any(event.actor_id == "human" for event in agent.events)
            assert any(event.actor_id == "agent" for event in human.events)

    try:
        asyncio.run(scenario())
        assert any(event.actor_id == "human" for event in gui.events)
        assert any(event.actor_id == "agent" for event in gui.events)
    finally:
        host.stop()
        gui.close()


def test_proposal_mode_previews_without_mutation_and_human_accepts(tmp_path) -> None:
    service = HeadlessService.create(tmp_path / "proposals")
    host = LocalAutomationHost(service.authority).start()

    async def scenario() -> None:
        async with (
            AsyncRemoteClient(
                host.endpoint,
                host.token,
                actor_id="planner-agent",
                mode=AccessMode.PROPOSAL,
            ) as planner,
            AsyncRemoteClient(
                host.endpoint,
                host.token,
                actor_id="reviewer",
            ) as reviewer,
        ):
            with pytest.raises(RemoteRpcError) as denied:
                await planner.submit(RenameProject("Not committed"))
            assert denied.value.data["code"] == "PERMISSION_PROPOSAL_ONLY"
            assert service.authority.snapshot().title == "Untitled Project"

            proposal = await planner.propose(
                RenameProject("Accepted proposal"),
                operation_id="proposal-rename",
                intent="Give the project a useful name",
            )
            assert proposal["base_revision"] == 0
            assert "Accepted proposal" in str(proposal["diff"])
            assert service.authority.revision == 0

            accepted = await reviewer.accept_proposal(str(proposal["proposal_id"]))
            assert isinstance(accepted, CommandAccepted)
            assert service.authority.snapshot().title == "Accepted proposal"

    try:
        asyncio.run(scenario())
    finally:
        host.stop()


def test_read_only_grant_rejects_edits_and_bounded_history_requires_snapshot_resync() -> None:
    authority = ProjectAuthority(create_default_project(), event_history_limit=2)
    local_service = AutomationService(authority)
    grant = AccessGrant(
        "read-only-token",
        frozenset({AutomationCapability.READ}),
    )
    server = AutomationWebSocketServer(local_service, grants=(grant,))

    async def scenario() -> None:
        await server.start()
        try:
            async with AsyncRemoteClient(
                server.endpoint,
                grant.token,
                actor_id="observer",
            ) as observer:
                snapshot = await observer.snapshot()
                assert snapshot.revision == 0
                with pytest.raises(RemoteRpcError) as denied:
                    await observer.submit(RenameProject("Denied"))
                assert denied.value.data["code"] == "PERMISSION_DENIED"

            local = CodeVisualizerClient(authority, actor_id="local")
            try:
                local.rename_project("One")
                local.rename_project("Two")
                local.rename_project("Three")
            finally:
                local.close()
            async with AsyncRemoteClient(
                server.endpoint,
                grant.token,
                actor_id="late-observer",
            ) as late:
                resynced = await late.subscribe(since_revision=0)
                assert resynced is not None
                assert resynced.title == "Three"
                assert resynced.revision == 3
        finally:
            await server.stop()

    asyncio.run(scenario())


def test_nonloopback_binding_requires_explicit_security_opt_in() -> None:
    service = AutomationService(ProjectAuthority(create_default_project()))
    with pytest.raises(ValueError, match="allow_remote"):
        AutomationWebSocketServer(service, host="192.0.2.10")


def test_mcp_exposes_only_semantic_tools_and_commits_through_same_authority(tmp_path) -> None:
    service = HeadlessService.create(tmp_path / "mcp")
    diagram = service.authority.snapshot().documents[0]
    host = LocalAutomationHost(service.authority).start()

    async def scenario() -> None:
        async with AsyncRemoteClient(
            host.endpoint,
            host.token,
            actor_id="mcp-agent",
        ) as remote:
            await remote.subscribe()
            adapter = McpServerAdapter(remote)
            listed = await adapter.handle_jsonrpc(
                {"id": 1, "jsonrpc": "2.0", "method": "tools/list"}
            )
            assert listed is not None
            names = {item.name for item in MCP_TOOLS}
            assert "semantic_command" in names
            assert {
                "list_projection_definitions",
                "compose_semantic_projection",
                "runtime_history",
            } <= names
            assert all("pixel" not in name and "line" not in name for name in names)

            diagrams = await adapter.call_tool("list_diagrams", {})
            assert diagrams["isError"] is False
            assert diagram.id in str(diagrams["content"])

            projection = await adapter.call_tool(
                "semantic_projection",
                {"kind": "architecture"},
            )
            assert projection["isError"] is False
            assert diagram.id in str(projection["content"])

            inserted = await adapter.call_tool(
                "semantic_command",
                {
                    "command_type": "drakon.insert",
                    "expected_revision": remote.observed_revision,
                    "intent": "Add a visible agent action",
                    "operation_id": "mcp-insert-action",
                    "payload": {
                        "atom_id": "mcp_action",
                        "atom_kind": "action",
                        "diagram_id": diagram.id,
                        "index": 0,
                        "sequence_id": diagram.body.id,
                        "source": 'print("MCP")',
                    },
                },
            )
            assert inserted["isError"] is False
            assert service.authority.snapshot().documents[0].body.atoms[0].source == "print('MCP')"

    try:
        asyncio.run(scenario())
    finally:
        host.stop()


def test_direct_rpc_mutation_requires_revision_and_bad_token_is_rejected(tmp_path) -> None:
    service = HeadlessService.create(tmp_path / "rpc-security")
    host = LocalAutomationHost(service.authority).start()

    async def scenario() -> None:
        async with AsyncRemoteClient(
            host.endpoint,
            host.token,
            actor_id="revision-client",
        ) as remote:
            with pytest.raises(RemoteRpcError) as missing:
                await remote.call(
                    "diagram.rename",
                    {"diagram_id": service.authority.snapshot().documents[0].id, "title": "No"},
                )
            assert missing.value.data["code"] == "EXPECTED_REVISION_REQUIRED"

        with pytest.raises(Exception, match=r"4401|authentication|required"):
            async with AsyncRemoteClient(
                host.endpoint,
                "not-the-token",
                actor_id="intruder",
            ):
                pass

    try:
        asyncio.run(scenario())
    finally:
        host.stop()


def test_direct_rpc_can_author_canonical_program_without_a_diagram(tmp_path) -> None:
    service = HeadlessService.create(tmp_path / "canonical-rpc")
    kernel_events = []
    host = LocalAutomationHost(service.authority)
    unsubscribe = host.service.kernel.subscribe(kernel_events.append)
    host.start()

    async def scenario() -> None:
        async with AsyncRemoteClient(
            host.endpoint,
            host.token,
            actor_id="program-author",
        ) as remote:
            await remote.subscribe()
            capabilities = await remote.call("service.capabilities", {})
            assert isinstance(capabilities, dict)
            assert "program.function.create" in capabilities["methods"]

            assert "program.module.put" in capabilities["methods"]
            module_created = await remote.call(
                "program.module.put",
                {
                    "expected_revision": remote.observed_revision,
                    "operation_id": "rpc-create-module",
                    "module": program_module_to_data(
                        ProgramModule("module_rpc_greeter", "app.greeter")
                    ),
                },
            )
            assert module_created["status"] == "accepted"

            created = await remote.call(
                "program.function.create",
                {
                    "body_sequence_id": "sequence_rpc_greet",
                    "display_name": "Greet",
                    "expected_revision": module_created["revision"],
                    "function_id": "function_rpc_greet",
                    "identifier": "greet",
                    "owner_id": "module_rpc_greeter",
                    "operation_id": "rpc-create-greet",
                    "symbol_id": "symbol_rpc_greet",
                },
            )
            assert isinstance(created, dict)
            assert created["status"] == "accepted"

            inserted = await remote.call(
                "program.statement.insert",
                {
                    "arguments": '"Hello from the canonical model"',
                    "expression": "print",
                    "expected_revision": created["revision"],
                    "function_id": "function_rpc_greet",
                    "index": 0,
                    "operation_id": "rpc-insert-print",
                    "sequence_id": "sequence_rpc_greet",
                    "statement_id": "statement_rpc_print",
                    "statement_kind": "call",
                },
            )
            assert isinstance(inserted, dict)
            assert inserted["status"] == "accepted", inserted

            snapshot = service.authority.snapshot()
            function = snapshot.program_model.function("function_rpc_greet")
            assert function is not None
            assert function.identifier == "greet"
            assert snapshot.program_model.owner_of(function.id).id == "module_rpc_greeter"
            assert len(function.body.statements) == 1
            assert all(document.id != function.id for document in snapshot.documents)
            assert any(
                event.semantic_delta is not None
                and "function_rpc_greet" in event.semantic_delta.affected_ids
                for event in kernel_events
            )

    try:
        asyncio.run(scenario())
    finally:
        host.stop()
        unsubscribe()
        service.close()


def test_remote_stop_terminates_nonterminating_execution_job(tmp_path) -> None:
    service = HeadlessService.create(tmp_path / "remote-stop")
    local = service.client("setup")
    diagram = service.authority.snapshot().documents[0]
    inserted = local.insert_drakon_atom(diagram.id, "while_loop", 0)
    assert isinstance(inserted, CommandAccepted)
    assert isinstance(
        local.set_drakon_text(
            diagram.id,
            inserted.affected_ids[0],
            "condition",
            "True",
        ),
        CommandAccepted,
    )
    local.close()
    host = LocalAutomationHost(service.authority).start()

    async def scenario() -> None:
        async with AsyncRemoteClient(
            host.endpoint,
            host.token,
            actor_id="test-runner",
        ) as remote:
            await remote.subscribe()
            started = await remote.call(
                "test.run_diagram",
                {"arguments": "", "diagram_id": diagram.id},
            )
            assert isinstance(started, dict)
            job_id = started["job_id"]
            assert isinstance(job_id, str)
            stopped = await remote.call("test.stop", {"job_id": job_id})
            assert isinstance(stopped, dict)
            assert stopped["stopped"] == 1

            async def job_stopped() -> bool:
                status = await remote.call("test.status", {"job_id": job_id})
                return isinstance(status, dict) and status.get("status") == "stopped"

            for _ in range(100):
                if await job_stopped():
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("Execution job did not stop")
            assert any(
                event.event_type == "execution.completed"
                and event.payload.get("termination_reason") == "stopped"
                for event in remote.events
            )

    try:
        asyncio.run(scenario())
    finally:
        host.stop()
