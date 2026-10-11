"""Actual GUI submission and headless wait share exact input and durable semantics."""

import struct
from dataclasses import replace

from PySide6.QtCore import Qt

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.computation import execute_computation
from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.domain.intentional import IntentionalNode, PropertyValue
from code_visualizer.domain.resources import ResourceLogicalTypeReference, TensorDescriptor
from code_visualizer.domain.values import TensorDType, TensorValue
from code_visualizer.extensions.foundations.backend import BACKEND_ID, TENSOR_MEDIA_TYPE
from code_visualizer.extensions.foundations.examples import matrix_product_project
from code_visualizer.extensions.foundations.math import identity as math_id
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.ui_qt.features.domain_workbench.widget import DomainWorkbenchWidget


def test_gui_run_and_headless_wait_produce_identical_evidence_for_exact_resource_input(
    qtbot, tmp_path
):
    gui_resources = ResourceStore(tmp_path / "gui")
    gui_evidence = EvidenceStore(tmp_path / "gui")
    source_resource = gui_resources.put(
        struct.pack("<4d", 1.0, 2.0, 3.0, 4.0),
        TENSOR_MEDIA_TYPE,
        tensor=TensorDescriptor(TensorDType.FLOAT64, (2, 2)),
        logical_type=ResourceLogicalTypeReference("foundation.math.tensor", "1"),
    )
    project = matrix_product_project()
    model = project.domain_workspace.models[0]
    resource_node = IntentionalNode(
        "matrix:A:value",
        math_id("ResourceLiteral"),
        (PropertyValue(math_id("ResourceLiteral", "value"), source_resource.reference),),
    )
    model = replace(
        model,
        nodes=tuple(resource_node if node.id == resource_node.id else node for node in model.nodes),
    )
    project = replace(project, domain_workspace=replace(project.domain_workspace, models=(model,)))
    host = ComputationService()
    authority = ProjectAuthority(project)
    kernel = ProjectKernel(
        authority,
        computations=host,
        resource_store=gui_resources,
        evidence_store=gui_evidence,
    )
    client = CodeVisualizerClient(authority, actor_id="gui-headless-parity")
    widget = DomainWorkbenchWidget()
    qtbot.addWidget(widget)
    widget.attach(kernel, client)
    widget.show()
    project = authority.snapshot()
    request = ComputationRequest(project.id, project.revision, BACKEND_ID, "1", model.id)
    headless_kernel = None
    try:
        assert widget.current_model().id == model.id
        selected = widget.backend_choice.findData(f"{BACKEND_ID}@1")
        assert selected >= 0
        widget.backend_choice.setCurrentIndex(selected)
        qtbot.mouseClick(widget.run_computation_button, Qt.MouseButton.LeftButton)
        assert len(host.attempts()) == 1
        gui_session = host.attempts()[0].session.id
        gui_job = host.job(gui_session)
        assert gui_job.request == request
        qtbot.waitUntil(gui_job.done.is_set, timeout=40000)
        gui_result = host.wait(gui_session)
        qtbot.waitUntil(lambda: widget.evidence_view.topLevelItemCount() == 1, timeout=5000)
        assert widget.evidence_view.topLevelItem(0).toolTip(0) == gui_result.id
        assert gui_result.outcome is ComputationOutcome.SUCCEEDED, gui_result.diagnostics
        assert gui_result.provenance.resources == (source_resource.reference,)
        assert gui_job.plan is not None and gui_job.snapshot is not None
        assert gui_job.plan.request.resources == (source_resource.reference,)
        assert authority.snapshot() is project
        widget.attach(None)
        widget.hide()

        # A fresh host/store must compute again; a shared evidence cache cannot supply parity.
        headless_resources = ResourceStore(tmp_path / "headless")
        headless_evidence = EvidenceStore(tmp_path / "headless")
        copied = headless_resources.import_file(
            gui_resources.verified_path(source_resource.reference),
            source_resource.media_type,
            tensor=source_resource.tensor,
            logical_type=source_resource.logical_type,
        )
        assert copied == source_resource
        headless_kernel = ProjectKernel(
            ProjectAuthority(project),
            resource_store=headless_resources,
            evidence_store=headless_evidence,
        )
        assert headless_evidence.identities() == ()
        assert headless_kernel.computations.attempts() == ()
        headless_result = execute_computation(headless_kernel, request)
        headless_attempts = headless_kernel.computations.attempts()
        assert len(headless_attempts) == 1
        headless_job = headless_kernel.computations.job(headless_attempts[0].session.id)
        assert headless_attempts[0].session.id != gui_session
        assert headless_job.request == gui_job.request == request
        assert headless_job.plan == gui_job.plan
        assert headless_job.view.source_digest == gui_job.view.source_digest
        assert headless_job.view.input_digest == gui_job.view.input_digest
        assert headless_result == gui_result
        assert headless_evidence.get(gui_result.id) == gui_evidence.get(gui_result.id) == gui_result
        assert gui_result.observations[0].value == TensorValue(
            TensorDType.FLOAT64, (2, 2), (19.0, 22.0, 43.0, 50.0)
        )
        assert {"matrix:equation", "matrix:A", "matrix:B", "matrix:C"} <= set(
            gui_result.observations[0].semantic_ids
        )
        assert gui_result.provenance.transformations == ()
        assert gui_result.provenance.terminal_resource is not None
        for artifact in gui_result.artifacts:
            assert gui_resources.describe(artifact.resource) == headless_resources.describe(
                artifact.resource
            )
            assert gui_resources.read(artifact.resource) == headless_resources.read(
                artifact.resource
            )
        assert headless_kernel.authority.snapshot() == project
        assert not project.program_model.functions
    finally:
        widget.attach(None)
        kernel.close()
        client.close()
        host.close()
        if headless_kernel is not None:
            headless_kernel.close()
