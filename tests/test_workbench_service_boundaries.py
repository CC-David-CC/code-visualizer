"""Domain automation retains the same commit and execution grants on every route."""

import pytest

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.automation.protocol import RpcError
from code_visualizer.automation.service import (
    AccessMode,
    AutomationCapability,
    AutomationContext,
    AutomationService,
)
from code_visualizer.extensions.fsm import traffic_light_project


def _context(*, proposal=False, destructive=False):
    capabilities = {
        AutomationCapability.READ,
        AutomationCapability.EDIT,
        AutomationCapability.PROPOSE,
    }
    if destructive:
        capabilities.add(AutomationCapability.DESTRUCTIVE)
    return AutomationContext(
        "actor",
        "connection",
        AccessMode.PROPOSAL if proposal else AccessMode.COMMIT,
        frozenset(capabilities),
    )


def _deletion():
    return {
        "command_type": "domain.model.delete",
        "payload": {"model_id": "traffic:model"},
        "expected_revision": 0,
        "operation_id": "delete-domain",
    }


def test_domain_deletion_requires_same_grant_when_wrapped_in_transaction():
    authority = ProjectAuthority(traffic_light_project())
    service = AutomationService(authority)
    try:
        with pytest.raises(RpcError, match="destructive"):
            service.dispatch(
                "command.transaction",
                {"commands": [_deletion()], "expected_revision": 0},
                _context(),
            )
        assert authority.revision == 0
        allowed = service.dispatch(
            "command.transaction",
            {"commands": [_deletion()], "expected_revision": 0},
            _context(destructive=True),
        )
        assert allowed["status"] == "accepted"
        assert authority.snapshot().domain_workspace.models == ()
    finally:
        service.close()


def test_accepting_domain_deletion_proposal_requires_destructive_grant():
    authority = ProjectAuthority(traffic_light_project())
    service = AutomationService(authority)
    try:
        proposal = service.dispatch(
            "proposal.create", {"command": _deletion()}, _context(proposal=True)
        )
        with pytest.raises(RpcError, match="destructive"):
            service.dispatch(
                "proposal.accept", {"proposal_id": proposal["proposal_id"]}, _context()
            )
        assert authority.revision == 0
    finally:
        service.close()


def test_proposal_only_actor_cannot_accept_and_commit_its_own_domain_proposal():
    authority = ProjectAuthority(traffic_light_project())
    service = AutomationService(authority)
    context = _context(proposal=True, destructive=True)
    try:
        proposal = service.dispatch("proposal.create", {"command": _deletion()}, context)
        with pytest.raises(RpcError, match="Proposal-mode"):
            service.dispatch("proposal.accept", {"proposal_id": proposal["proposal_id"]}, context)
        assert authority.revision == 0
    finally:
        service.close()


def test_workbench_trace_capability_requires_execution_grant_before_running():
    authority = ProjectAuthority(traffic_light_project())
    service = AutomationService(authority)
    try:
        with pytest.raises(RpcError, match="execute"):
            service.dispatch(
                "capability.invoke",
                {
                    "capability_id": "execution.workbench.trace",
                    "inputs": {"model_id": "traffic:model"},
                },
                _context(),
            )
        assert service.kernel.runtime.sessions() == ()
    finally:
        service.close()


def test_direct_domain_method_cannot_spoof_command_type_to_bypass_its_grant():
    authority = ProjectAuthority(traffic_light_project())
    service = AutomationService(authority)
    try:
        with pytest.raises(RpcError, match="destructive"):
            service.dispatch(
                "domain.model.delete",
                {
                    "model_id": "traffic:model",
                    "expected_revision": 0,
                    "command_type": "domain.node.set_property",
                },
                _context(),
            )
        assert authority.revision == 0
    finally:
        service.close()
