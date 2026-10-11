"""The Qt attachment observes the host without owning scientific execution."""

import json
from dataclasses import replace
from itertools import pairwise
from math import ceil
from threading import Thread
from time import perf_counter

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QLineEdit

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.domain.computation import ComputationParameter, ComputationStatus
from code_visualizer.domain.notation import NotationKind
from code_visualizer.execution import DebugEvent, DebugState
from code_visualizer.extensions.fsm import traffic_light_project
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.ui_qt.features.domain_workbench.widget import DomainWorkbenchWidget


def test_runtime_bursts_preserve_open_form_table_tree_and_authoring_selection(qtbot):
    project = traffic_light_project()
    authority = ProjectAuthority(project)
    project = authority.snapshot()
    host = ComputationService()
    kernel = ProjectKernel(authority, computations=host)
    client = CodeVisualizerClient(authority, actor_id="responsive-ui")
    widget = DomainWorkbenchWidget()
    qtbot.addWidget(widget)
    widget.attach(kernel, client)
    widget.show()
    widget.reveal("traffic:red")
    field = widget._properties["fsm:state:name"].control
    assert isinstance(field, QLineEdit)
    field.setText("Uncommitted edit")
    table_item = widget.table.item(0, 0)
    tree_item = widget.tree.topLevelItem(0)
    selection = kernel.selection.state
    deliveries = []
    widget._runtime_observer.runtimeChanged.connect(deliveries.append)

    def produce():
        for sequence in range(1, 1001):
            kernel.runtime.record(
                DebugEvent(
                    sequence,
                    "trace",
                    DebugState.RUNNING,
                    execution_session_id="ui-burst",
                    project_revision=project.revision,
                    artifact_revision=project.revision,
                ),
                "traffic:green",
            )

    producer = Thread(target=produce)
    try:
        producer.start()
        qtbot.waitUntil(lambda: not producer.is_alive(), timeout=5000)
        qtbot.waitUntil(
            lambda: bool(deliveries) and deliveries[-1].event_sequence == 1000, timeout=5000
        )
        assert len(deliveries) < 100
        assert len(kernel.runtime.history("ui-burst")) <= kernel.runtime.history_limit
        assert widget._properties["fsm:state:name"].control is field
        assert field.text() == "Uncommitted edit"
        assert widget.table.item(0, 0) is table_item
        assert widget.tree.topLevelItem(0) is tree_item
        assert authority.snapshot() is project
        assert kernel.selection.state == selection
        graph = widget.projections[NotationKind.GRAPH].graph
        assert "active" in next(item for item in graph.nodes if item.id == "traffic:green").badges
        kernel.selection.select(
            ("traffic:green",), revision=project.revision, source="runtime.computation"
        )
        assert kernel.selection.state.primary == "traffic:green"
        assert widget._properties["fsm:state:name"].control is field
        assert field.text() == "Uncommitted edit"
        assert widget._selected_id == "traffic:red"
        client.rename_project("Changed while the observation is retained")
        qtbot.waitUntil(lambda: not kernel.current_runtime_ids())
        assert kernel.runtime.active.project_revision == project.revision
        assert all(
            "active" not in item.badges
            for projection in widget.projections.values()
            for item in projection.graph.nodes
        )
    finally:
        producer.join(timeout=5)
        widget.attach(None)
        kernel.close()
        client.close()
        host.close()


def _stress_widget(qtbot, tmp_path, monkeypatch, *, mode=None, configuration=()):
    from fixtures.computation_worker_fixture import BACKEND_ID, fixture_registry, worker_profile

    from code_visualizer.application import computation

    host = ComputationService(profiles=(worker_profile(),))
    authority = ProjectAuthority(traffic_light_project())
    resources = ResourceStore(tmp_path)
    kernel = ProjectKernel(
        authority,
        computations=host,
        extensions=fixture_registry(),
        resource_store=resources,
        evidence_store=EvidenceStore(tmp_path),
    )
    client = CodeVisualizerClient(authority, actor_id="host-qt-proof")
    widget = DomainWorkbenchWidget()
    qtbot.addWidget(widget)
    widget.attach(kernel, client)
    widget.show()
    widget.backend_choice.setCurrentIndex(widget.backend_choice.findData(f"{BACKEND_ID}@1"))
    assert widget.backend_choice.currentData() == f"{BACKEND_ID}@1"
    if mode is not None:
        start = computation.start_computation

        def configured_start(kernel, request):
            return start(
                kernel,
                replace(
                    request, configuration=(ComputationParameter("mode", mode), *configuration)
                ),
            )

        # Supply a typed backend configuration; submission, preparation, process,
        # event transport and resource/evidence admission remain production code.
        monkeypatch.setattr(computation, "start_computation", configured_start)
    return host, kernel, client, widget, resources


def _terminal(host):
    return bool(host.attempts()) and host.attempts()[0].session.status in {
        ComputationStatus.SUCCEEDED,
        ComputationStatus.FAILED,
        ComputationStatus.CANCELLED,
    }


def test_real_run_button_keeps_large_resource_admission_off_gui(qtbot, tmp_path, monkeypatch):
    payload_path = tmp_path / "large-input.bin"
    with payload_path.open("wb") as stream:
        for _ in range(128):
            stream.write(b"r" * (1024 * 1024))
    resources = ResourceStore(tmp_path)
    descriptor = resources.import_file(payload_path, "application/octet-stream")
    host, kernel, client, widget, _ = _stress_widget(
        qtbot,
        tmp_path,
        monkeypatch,
        mode="large_resource",
        configuration=(ComputationParameter("input", descriptor.reference),),
    )
    source = client.snapshot()
    pulses = []
    timer = QTimer(widget)
    timer.setInterval(10)
    timer.timeout.connect(lambda: pulses.append(perf_counter()))
    try:
        timer.start()
        qtbot.wait(50)
        started = perf_counter()
        qtbot.mouseClick(widget.run_computation_button, Qt.MouseButton.LeftButton)
        acknowledgement = perf_counter() - started
        qtbot.waitUntil(lambda: _terminal(host), timeout=30000)
        qtbot.waitUntil(lambda: widget.evidence_view.topLevelItemCount() == 1, timeout=5000)
        timer.stop()
        attempt = host.attempts()[0]
        assert attempt.session.status is ComputationStatus.SUCCEEDED, attempt.diagnostic
        evidence = host.evidence(attempt.session.id)
        assert evidence is not None
        observations = {value.id: value.value for value in evidence.observations}
        assert observations == {"bytes": descriptor.byte_size, "sha256": descriptor.content_hash}
        assert descriptor.reference in evidence.provenance.resources
        assert client.snapshot() is source
        assert len(pulses) > 2
        gap = max(right - left for left, right in pairwise(pulses))
        receipt = {
            "resource_bytes": descriptor.byte_size,
            "resource_hash": descriptor.content_hash,
            "source_digest": attempt.source_digest,
            "input_digest": attempt.input_digest,
            "acknowledgement_seconds": acknowledgement,
            "heartbeat_max_gap_seconds": gap,
        }
        (tmp_path / "gui-large-resource-receipt.json").write_text(json.dumps(receipt, indent=2))
        assert acknowledgement <= 0.2, receipt
        assert gap <= 0.25, receipt
    finally:
        timer.stop()
        (tmp_path / "gui-large-resource-samples.json").write_text(json.dumps({"pulses": pulses}))
        widget.attach(None)
        kernel.close()
        client.close()
        host.close()


def test_real_run_button_keeps_progress_bounded_and_preserves_open_editor(
    qtbot, tmp_path, monkeypatch
):
    host, kernel, client, widget, _resources = _stress_widget(qtbot, tmp_path, monkeypatch)
    widget.reveal("traffic:red")
    field = widget._properties["fsm:state:name"].control
    assert isinstance(field, QLineEdit)
    field.setText("Draft while computing")
    source = client.snapshot()
    deliveries = []
    widget._runtime_observer.attemptsChanged.connect(deliveries.append)
    pulses = []
    heartbeat = QTimer(widget)
    heartbeat.setInterval(10)
    heartbeat.timeout.connect(lambda: pulses.append(perf_counter()))
    try:
        qtbot.wait(80)
        heartbeat.start()
        started = perf_counter()
        qtbot.mouseClick(widget.run_computation_button, Qt.MouseButton.LeftButton)
        acknowledgement = perf_counter() - started
        assert host.attempts()
        assert not _terminal(host)
        qtbot.waitUntil(lambda: _terminal(host), timeout=30000)
        qtbot.waitUntil(lambda: widget.evidence_view.topLevelItemCount() == 1, timeout=5000)
        heartbeat.stop()
        attempt = host.attempts()[0]
        assert attempt.session.status is ComputationStatus.SUCCEEDED, attempt.diagnostic
        assert attempt.source_digest and attempt.input_digest
        assert len(deliveries) < 1000  # The fixture produces 10,001 progress events.
        assert len(kernel.runtime.history()) <= kernel.runtime.history_limit
        assert client.snapshot() is source
        assert widget._properties["fsm:state:name"].control is field
        assert field.text() == "Draft while computing"
        assert len(pulses) >= 2
        gaps = [right - left for left, right in pairwise(pulses)]
        measurement = {
            "fixture": "default-progress-10000",
            "acknowledgement_seconds": acknowledgement,
            "heartbeat_max_gap_seconds": max(gaps, default=0.0),
            "gui_deliveries": len(deliveries),
            "source_digest": attempt.source_digest,
            "input_digest": attempt.input_digest,
        }
        (tmp_path / "gui-progress-receipt.json").write_text(json.dumps(measurement, indent=2))
        assert acknowledgement <= 0.2, measurement
        assert max(gaps, default=0.0) <= 0.25, measurement
    finally:
        heartbeat.stop()
        (tmp_path / "gui-progress-samples.json").write_text(json.dumps({"pulses": pulses}))
        widget.attach(None)
        kernel.close()
        client.close()
        host.close()


def test_cancel_button_acknowledges_uncooperative_cpu_worker_without_freezing(
    qtbot, tmp_path, monkeypatch
):
    host, kernel, client, widget, _resources = _stress_widget(
        qtbot, tmp_path, monkeypatch, mode="cpu"
    )
    widget.reveal("traffic:red")
    field = widget._properties["fsm:state:name"].control
    assert isinstance(field, QLineEdit)
    acknowledgements = []

    def edit_gesture():
        started = perf_counter()
        qtbot.keyClicks(field, ".")
        acknowledgements.append(perf_counter() - started)

    interactions = QTimer(widget)
    interactions.setInterval(20)
    interactions.timeout.connect(edit_gesture)
    pulses = []
    timer = QTimer(widget)
    timer.setInterval(10)
    timer.timeout.connect(lambda: pulses.append(perf_counter()))
    try:
        qtbot.mouseClick(widget.run_computation_button, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(
            lambda: (
                host.attempts()[0].progress is not None
                and host.attempts()[0].progress.message == "Worker started"
            ),
            timeout=20000,
        )
        qtbot.waitUntil(widget.cancel_computation_button.isEnabled)
        timer.start()
        interactions.start()
        qtbot.waitUntil(lambda: len(acknowledgements) >= 100, timeout=5000)
        interactions.stop()
        samples = sorted(acknowledgements)
        p95 = samples[ceil(0.95 * len(samples)) - 1]
        p99 = samples[ceil(0.99 * len(samples)) - 1]
        assert p95 <= 0.1
        assert p99 <= 0.2
        started = perf_counter()
        qtbot.mouseClick(widget.cancel_computation_button, Qt.MouseButton.LeftButton)
        acknowledgement = perf_counter() - started
        qtbot.waitUntil(lambda: _terminal(host), timeout=10000)
        timer.stop()
        attempt = host.attempts()[0]
        assert attempt.session.status is ComputationStatus.CANCELLED, attempt.diagnostic
        assert attempt.forced_termination
        assert acknowledgement <= 0.2
        assert len(pulses) >= 3
        gap = max(right - left for left, right in pairwise(pulses))
        assert gap <= 0.25
        (tmp_path / "gui-cancel-receipt.json").write_text(
            json.dumps(
                {
                    "configuration": {"mode": "cpu"},
                    "acknowledgement_seconds": acknowledgement,
                    "heartbeat_max_gap_seconds": gap,
                    "interaction_sample_count": len(samples),
                    "interaction_p95_seconds": p95,
                    "interaction_p99_seconds": p99,
                    "quantile_method": "nearest_rank",
                    "forced_termination": attempt.forced_termination,
                    "source_digest": attempt.source_digest,
                    "input_digest": attempt.input_digest,
                },
                indent=2,
            )
        )
    finally:
        interactions.stop()
        timer.stop()
        (tmp_path / "gui-cancel-samples.json").write_text(
            json.dumps({"interaction_seconds": acknowledgements, "pulses": pulses})
        )
        widget.attach(None)
        kernel.close()
        client.close()
        host.close()


def test_graph_pan_and_uncommitted_form_survive_running_worker_and_terminal_update(
    qtbot, tmp_path, monkeypatch
):
    host, kernel, client, widget, _resources = _stress_widget(
        qtbot, tmp_path, monkeypatch, mode="cpu"
    )
    widget.resize(1100, 760)
    widget.reveal("traffic:red")
    field = widget._properties["fsm:state:name"].control
    field.setText("Uncommitted while panning")
    source = client.snapshot()
    view = widget.graph_view
    # Make room for a viewport gesture without changing authored geometry.
    view.setSceneRect(view.sceneRect().adjusted(-1000, -1000, 1000, 1000))
    view.centerOn(0, 0)
    node = widget.reconciler.node_items["traffic:red"]
    node_position = node.pos()
    try:
        qtbot.mouseClick(widget.run_computation_button, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(
            lambda: (
                host.attempts()[0].progress is not None
                and host.attempts()[0].progress.message == "Worker started"
            ),
            timeout=20000,
        )
        assert not _terminal(host)
        viewport = view.viewport()
        point = next(
            point
            for point in (
                QPoint(20, 20),
                QPoint(20, viewport.height() - 20),
                QPoint(viewport.width() - 20, 20),
            )
            if view.itemAt(point) is None
        )
        before = (view.horizontalScrollBar().value(), view.verticalScrollBar().value())
        qtbot.mousePress(viewport, Qt.MouseButton.LeftButton, pos=point)
        qtbot.mouseMove(viewport, point + QPoint(55, 35), delay=20)
        qtbot.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=point + QPoint(55, 35))
        after = (view.horizontalScrollBar().value(), view.verticalScrollBar().value())
        assert after != before
        assert not _terminal(host)
        qtbot.mouseClick(widget.cancel_computation_button, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: _terminal(host), timeout=10000)
        qtbot.wait(80)  # Include the terminal runtime observer delivery.
        assert (view.horizontalScrollBar().value(), view.verticalScrollBar().value()) == after
        assert widget.reconciler.node_items["traffic:red"] is node
        assert node.pos() == node_position
        assert widget._properties["fsm:state:name"].control is field
        assert field.text() == "Uncommitted while panning"
        assert client.snapshot() is source
    finally:
        widget.attach(None)
        kernel.close()
        client.close()
        host.close()


def test_editor_replacement_retains_running_attempt_and_sealed_publication(
    qtbot, tmp_path, monkeypatch
):
    from fixtures.computation_worker_fixture import fixture_registry

    host, kernel, client, widget, resources = _stress_widget(
        qtbot, tmp_path, monkeypatch, mode="publish_hold"
    )
    try:
        qtbot.mouseClick(widget.run_computation_button, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: bool(host.attempts()[0].publications), timeout=20000)
        previous = host.attempts()[0]
        publication = EvidenceStore(tmp_path).get_publication(previous.publications[0])
        sealed_reference = publication.artifact.resource
        assert resources.verified_path(sealed_reference).read_bytes() == b"10,20,30"
        qtbot.waitUntil(lambda: widget.publication_view.topLevelItemCount() == 1)
        widget._publication_selected(widget.publication_view.topLevelItem(0), 0)
        assert sealed_reference.content_hash in widget.evidence_details.toPlainText()
        original_registry = kernel.runtime
        source = client.snapshot()
        widget.attach(None)
        kernel.close()
        client.close()
        assert not _terminal(host)
        authority = ProjectAuthority(source)
        kernel = ProjectKernel(
            authority,
            computations=host,
            extensions=fixture_registry(),
            resource_store=resources,
            evidence_store=EvidenceStore(tmp_path),
        )
        client = CodeVisualizerClient(authority, actor_id="replacement-editor")
        widget.attach(kernel, client)
        assert kernel.runtime is not original_registry
        assert kernel.runtime.active is None
        assert kernel.revision == previous.session.revision
        assert kernel.computation_attachment.id != previous.attachment_id
        assert widget.attempt_view.topLevelItemCount() == 1
        row = widget.attempt_view.topLevelItem(0)
        assert "historical source" in row.text(1)
        widget.attempt_view.setCurrentItem(row)
        assert widget.publication_view.topLevelItemCount() == 1
        assert "historical source" in widget.publication_view.topLevelItem(0).text(1)
        qtbot.waitUntil(widget.cancel_computation_button.isEnabled)
        qtbot.mouseClick(widget.cancel_computation_button, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: _terminal(host), timeout=10000)
        qtbot.waitUntil(lambda: widget.evidence_view.topLevelItemCount() == 1, timeout=5000)
        attempt = host.attempts()[0]
        assert attempt.session.status is ComputationStatus.CANCELLED, attempt.diagnostic
        assert attempt.publications == previous.publications
        assert EvidenceStore(tmp_path).get_publication(previous.publications[0]) == publication
        assert resources.verified_path(sealed_reference).read_bytes() == b"10,20,30"
        assert not attempt.forced_termination
        assert kernel.runtime.active is None
        assert not kernel.current_runtime_ids()
        assert original_registry.sessions()
        receipt = host.evidence(attempt.session.id)
        assert receipt is not None
        assert receipt.provenance.revision == source.revision
        assert all(
            "active" not in node.badges
            for projection in widget.projections.values()
            for node in projection.graph.nodes
        )
        selected = kernel.selection.state
        evidence_item = widget.evidence_view.topLevelItem(0)
        widget._evidence_selected(evidence_item, 0)
        assert kernel.selection.state == selected
        assert "historical source" in evidence_item.text(1)
    finally:
        widget.attach(None)
        kernel.close()
        client.close()
        host.close()
