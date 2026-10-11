import pytest
from PySide6.QtCore import Qt

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.domain_commands import SetDomainProperty
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.automation.protocol import RpcError
from code_visualizer.automation.service import (
    AccessMode,
    AutomationCapability,
    AutomationContext,
    AutomationService,
)
from code_visualizer.domain.projection import ProjectionDefinition
from code_visualizer.domain.semantic import SemanticObjectKind
from code_visualizer.extensions.fsm import traffic_light_project
from code_visualizer.persistence.serialization import normalized_project_json
from code_visualizer.sdk.client import CodeVisualizerClient
from code_visualizer.ui_qt.features.semantic_visualizer.semantic_text import SemanticTextWidget


def test_domain_semantic_text_is_an_edit_client_with_a_stale_affordance_guard(qtbot):
    authority = ProjectAuthority(traffic_light_project())
    kernel = ProjectKernel(authority)
    client = CodeVisualizerClient(authority, actor_id="text")
    widget = SemanticTextWidget()
    qtbot.addWidget(widget)
    widget.attach(kernel, client)
    widget.show()
    try:
        widget.set_projection(
            kernel.compose_projection(
                ProjectionDefinition(
                    "states",
                    "States",
                    object_kinds=(SemanticObjectKind.INTENTION,),
                )
            )
        )
        selected = kernel.selection.select(("traffic:yellow",), revision=0, source="test.table")
        widget.apply_selection(selected)
        assert widget.field_editor.toPlainText() == "Yellow"
        widget.field_editor.setPlainText("Amber")
        qtbot.mouseClick(widget.apply_button, Qt.MouseButton.LeftButton)
        assert kernel.queries.semantic_object("traffic:yellow").label == "Amber"
        assert "Amber" in {
            node.label for node in kernel.notation("traffic:model", "fsm:graph").graph.nodes
        }
        widget.apply_selection(kernel.selection.state)
        assert isinstance(
            client.submit(
                SetDomainProperty(
                    "traffic:model",
                    "traffic:yellow",
                    "fsm:state:name",
                    "Gold",
                )
            ),
            CommandAccepted,
        )
        widget.field_editor.setPlainText("Clobber")
        qtbot.mouseClick(widget.apply_button, Qt.MouseButton.LeftButton)
        assert kernel.queries.semantic_object("traffic:yellow").label == "Gold"
        assert "Refresh" in widget.status.text()
    finally:
        widget.attach(None, None)
        widget.close()
        kernel.close()


def test_registered_trace_capability_preserves_authority_and_exposes_runtime_origins():
    authority = ProjectAuthority(traffic_light_project())
    service = AutomationService(authority)
    reader = AutomationContext(
        "reader", "reader", AccessMode.COMMIT, frozenset({AutomationCapability.READ})
    )
    runner = AutomationContext(
        "runner",
        "runner",
        AccessMode.COMMIT,
        frozenset({AutomationCapability.READ, AutomationCapability.EXECUTE}),
    )
    params = {"capability_id": "execution.workbench.trace", "inputs": {"model_id": "traffic:model"}}
    before = normalized_project_json(authority.snapshot())
    try:
        with pytest.raises(RpcError, match="execute"):
            service.dispatch("capability.invoke", params, reader)
        result = service.dispatch("capability.invoke", params, runner)
        assert result["return_code"] == 0
        assert "Green" in result["stdout"]
        assert result["execution_session_id"]
        history = service.dispatch(
            "runtime.history", {"execution_session_id": result["execution_session_id"]}, reader
        )
        active_transition = next(
            item
            for item in history
            if "traffic:green-yellow" in item["origin_ids"]
            and "traffic:yellow" in item["origin_ids"]
        )
        assert active_transition["semantic_id"].startswith("derived:")
        assert active_transition["project_revision"] == 0
        assert normalized_project_json(authority.snapshot()) == before
        assert authority.snapshot().program_model.functions == ()
    finally:
        service.close()
