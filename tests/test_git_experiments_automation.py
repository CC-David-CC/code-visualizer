"""Retained experiments use the existing authenticated JSON/protobuf authority."""

import asyncio
import json
from argparse import Namespace
from dataclasses import replace

import pytest
from test_git_experiments import dirty_experiment as dirty_experiment
from test_git_experiments import request_for, untouched

from code_visualizer.application.commands import ReplaceProgramFunctionSignature
from code_visualizer.application.domain_commands import PutDomainSchema
from code_visualizer.automation.protobuf import dispatch_protobuf
from code_visualizer.automation.protocol import RpcError
from code_visualizer.automation.service import (
    AccessMode,
    AutomationCapability,
    AutomationContext,
    AutomationService,
)
from code_visualizer.cli import _serve_project
from code_visualizer.domain.intentional import DomainSchema
from code_visualizer.persistence.computation import computation_request_to_data
from code_visualizer.protocol.commands import command_to_proto
from code_visualizer.protocol.v1 import command_pb2
from code_visualizer.sdk import AsyncRemoteClient


def test_p2_automation_grants_deferred_proto_and_current_authority(dirty_experiment):
    controller, original, host, root = dirty_experiment
    before = untouched(root)
    context = AutomationContext(
        "p2", "connection", AccessMode.COMMIT, frozenset(AutomationCapability)
    )
    service = AutomationService(original.authority, kernel=original.kernel, git=controller)
    params = {"request": computation_request_to_data(request_for(original))}
    events = []
    service.subscribe_authority(events.append)
    service.set_event_sink(events.append)
    try:
        for missing in (
            AutomationCapability.EXECUTE,
            AutomationCapability.EDIT,
            AutomationCapability.SAVE,
            AutomationCapability.ADMIN,
        ):
            # The accepted automation contract makes ADMIN a superset grant.
            restricted = replace(
                context, capabilities=context.capabilities - {missing, AutomationCapability.ADMIN}
            )
            with pytest.raises(RpcError, match="lacks"):
                service.dispatch("git.freeze_run", params, restricted)
        with pytest.raises(RpcError, match="Proposal-mode"):
            service.dispatch("git.freeze_run", params, replace(context, mode=AccessMode.PROPOSAL))
        assert host.attempts() == ()
        pending = service.dispatch("git.freeze_run", params, context)
        run = controller._freezes[pending["operation_id"]].result(timeout=30)
        operation = service.dispatch("git.experiment_operation", pending, context)
        assert operation["status"] == "submitted" and operation["commit"] == run.attempt.commit
        assert service.authority is run.editor.authority
        assert service.kernel is run.editor.kernel
        assert host.wait(run.computation.id).id
        encoded = command_to_proto(
            PutDomainSchema(DomainSchema("schema_p2", "org.example.p2", "1")),
            actor_id=context.actor_id,
            operation_id="p2-protobuf-edit",
            project_id=service.authority.snapshot().id,
            expected_revision=service.authority.revision,
        )
        response = command_pb2.CommandResponse.FromString(
            dispatch_protobuf(service, encoded.SerializeToString(deterministic=True), context)
        )
        assert response.WhichOneof("result") == "deferred"
        operation_id = response.deferred.host_operation_id
        edited = controller.experiments.edits[operation_id].result(timeout=30)
        status = service.dispatch(
            "git.experiment_operation", {"operation_id": operation_id}, context
        )
        assert status["status"] == "completed"
        assert service.authority is edited.editor.authority
        assert any(e.event_type == "session.replaced" for e in events)
        events.clear()
        result = service.dispatch(
            "command.execute",
            {
                "command_type": "project.rename",
                "operation_id": "p2-current-title",
                "expected_revision": service.authority.revision,
                "payload": {"title": "Current variant"},
            },
            context,
        )
        assert result["status"] == "accepted"
        assert events and events[-1].revision == edited.editor.authority.revision
        assert run.editor.authority.snapshot().title != "Current variant"
        assert untouched(root) == before
        run.editor.close()
    finally:
        service.close()


def test_p2_headless_endpoint_reconnects_to_forked_worktree(dirty_experiment, monkeypatch):
    _controller, original, _host, root = dirty_experiment
    before = untouched(root)
    request = computation_request_to_data(request_for(original))
    original.close()
    publications = []
    monkeypatch.setattr(
        "code_visualizer.cli.print",
        lambda value, **kw: publications.append(json.loads(value)),
        raising=False,
    )

    async def published(count):
        for _ in range(1500):
            if len(publications) >= count:
                return publications[-1]
            await asyncio.sleep(0.02)
        raise AssertionError("Headless endpoint did not publish its replacement session")

    async def scenario():
        task = asyncio.create_task(
            _serve_project(
                Namespace(
                    path=str(original.root),
                    token="p2-token",
                    host="127.0.0.1",
                    port=0,
                    allow_remote=False,
                )
            )
        )
        try:
            first = await published(1)
            async with AsyncRemoteClient(first["endpoint"], "p2-token", actor_id="p2") as remote:
                pending = await remote.call("git.freeze_run", {"request": request})
                assert pending["status"] == "pending"
            second = await published(2)
            async with AsyncRemoteClient(second["endpoint"], "p2-token", actor_id="p2") as remote:
                status = await remote.call("git.status")
                assert status["branch"].startswith("experiment/")
                operation = ReplaceProgramFunctionSignature(
                    original.authority.snapshot().documents[0].id,
                    replace(
                        original.authority.snapshot().documents[0].header.function,
                        identifier="headless_fork",
                    ),
                ).to_operation()
                result = await remote.call(
                    "command.execute",
                    {
                        "command_type": operation.command_type,
                        "operation_id": "p2-headless-edit",
                        "payload": operation.payload,
                        "expected_revision": second["revision"],
                    },
                )
                assert result["status"] == "deferred"
            third = await published(3)
            async with AsyncRemoteClient(third["endpoint"], "p2-token", actor_id="p2") as remote:
                snapshot = await remote.call("project.snapshot")
                assert snapshot["program_model"]["functions"][0]["identifier"] == "headless_fork"
                runs = await remote.call("git.experiment_runs")
                assert len(runs) == 1
                assert runs[0]["commit"] and runs[0]["reference"]
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(scenario())
    assert untouched(root) == before
