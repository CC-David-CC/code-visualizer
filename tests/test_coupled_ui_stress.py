"""P6 response bounds under an actual coupled worker, retained data and Git edits."""

import gc
import json
import os
from dataclasses import replace
from itertools import pairwise
from pathlib import Path
from threading import get_ident
from time import perf_counter, thread_time

import numpy as np
from fixtures.large_channel_history import COLUMNS, ROWS, build_channel_histories
from PySide6.QtCore import QTimer
from test_coupled_active_git import result, voltage_edit
from test_diffusion_checkpoints import host as local_host
from test_electrothermal_contracts import changed
from test_electrothermal_git import repository, request
from test_field_history_stress import working_set

from code_visualizer.application.computation import execute_computation
from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.coupled_examples import electrothermal_project
from code_visualizer.application.git_service import GitProjectController
from code_visualizer.application.messages import CommandAccepted, CommandDeferred
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.computation import CancelRequest, ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.extensions.electrothermal.domain import BACKEND_ID
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.ui_qt.channel_history import ChannelHistoryPanel, ChannelViewSource
from code_visualizer.ui_qt.runtime_observer import QtRuntimeObserver


def test_coupled_cpu_retained_channels_git_fork_and_cancel_meet_p6_bounds(qtbot, tmp_path):
    resources = ResourceStore(tmp_path / "reader-resources")
    roots, chunks = build_channel_histories(resources)
    assert len(chunks) == 128
    assert all(3.9 * 1024**2 < resources.describe(r).byte_size <= 4 * 1024**2 for r in chunks)
    project = electrothermal_project(
        duration=2000, windows=20000, sample_every=50, checkpoint_every=1000
    )
    project = changed(project, "et:policy", "preview_every", 1)
    root = tmp_path / "repository"
    repository(root, project)
    service = ComputationService(max_workers=1)
    original = ProjectSession.open(root / "project", computations=service)
    controller = GitProjectController(original)
    panels = retained, live = ChannelHistoryPanel(), ChannelHistoryPanel()
    for panel in panels:
        qtbot.addWidget(panel)
        panel.resize(900, 780)
        panel.attach(original.kernel, original.client)
        panel.show()
    observer = QtRuntimeObserver(live)
    observer.attemptsChanged.connect(
        lambda attempts: live.observe_attempt(attempts[-1]) if attempts else None
    )
    pulses, pulse_cpu, acknowledgments, samples, collections = [], [], [], [], []
    heartbeat = QTimer(live)
    heartbeat.setInterval(10)

    def pulse():
        pulses.append(perf_counter())
        pulse_cpu.append(thread_time())

    heartbeat.timeout.connect(pulse)

    def collection(phase, info):
        if info["generation"] >= 1:
            collections.append(
                {
                    "phase": phase,
                    "info": dict(info),
                    "time": perf_counter(),
                    "thread_time": thread_time(),
                    "thread": get_ident(),
                }
            )

    report = {
        "phase": "P6",
        "heartbeat_limit_seconds": 0.25,
        "ack_limits_seconds": {"p95": 0.1, "p99": 0.2},
        "cache_limit_bytes": 64 * 1024**2,
        "reader_workload": "Synthetic typed resources, not simulated physical evidence",
        "coupled_workload": "Unpaused production electrothermal worker, no fixture backend",
        "columns": COLUMNS,
        "rows_per_chunk": ROWS,
        "chunk_count": len(chunks),
    }
    receipt = Path(os.environ.get("CODE_VISUALIZER_P6_STRESS_RECEIPT", tmp_path / "stress.json"))
    run = child = None
    gc.callbacks.append(collection)
    try:
        # Warm normal imports/extension contracts with a real small computation.
        warm = electrothermal_project(duration=2, windows=2, checkpoint_every=1)
        with local_host(warm, tmp_path / "warm") as kernel:
            evidence = execute_computation(
                kernel,
                ComputationRequest(
                    warm.id, warm.revision, BACKEND_ID, "1", "electrothermal:experiment"
                ),
            )
            assert evidence.outcome is ComputationOutcome.SUCCEEDED, evidence.diagnostics
        source = ChannelViewSource(
            roots[16],
            resources,
            "reader-history",
            "b" * 64,
            original.authority.revision,
            False,
            "RETAINED READER STIMULUS",
        )
        retained.inspect(source)
        qtbot.waitUntil(lambda: retained.presentation is not None, timeout=15000)
        retained.follow.setChecked(False)
        for index in range(16):
            retained.time_cursor.setValue(index * ROWS)
            qtbot.waitUntil(lambda: retained.pending_tasks == 0, timeout=10000)
        gc.collect()
        report["warmed_rss"] = working_set()
        # Git writes, closure capture and worker preparation stay off the GUI.
        heartbeat.start()
        run = result(qtbot, controller.submit_freeze_and_run(request(original)))
        live.attach(run.editor.kernel, run.editor.client)
        observer.attach(run.editor.kernel)
        qtbot.waitUntil(
            lambda: (
                (live.presentation is not None and live._preview is not None)
                or service.job(run.computation.id).done.is_set()
            ),
            timeout=30000,
        )
        if service.job(run.computation.id).done.is_set():
            raise AssertionError(service.wait(run.computation.id))
        assert not service.job(run.computation.id).done.is_set()
        before = run.editor.authority.snapshot()
        edit_future = None
        for count in (16, 128):
            retained.inspect(replace(source, resource=roots[count]))
            qtbot.waitUntil(lambda: retained.pending_tasks == 0, timeout=20000)
            retained.follow.setChecked(False)
            for iteration in range(32):
                started = perf_counter()
                retained.time_cursor.setValue(((iteration * 47) % count) * ROWS)
                retained.view.horizontalScrollBar().setValue(iteration * 3)
                if iteration % 8 == 0 and live.presentation is not None:
                    live.select.click()
                if count == 16 and iteration == 4:
                    submitted = run.editor.client.submit(voltage_edit(run.editor, 6))
                    assert isinstance(submitted, CommandDeferred)
                    edit_future = controller.experiments.edits[submitted.details["operation_id"]]
                delivered = []
                QTimer.singleShot(
                    0, lambda t=started, done=delivered: done.append(perf_counter() - t)
                )
                qtbot.waitUntil(lambda done=delivered: bool(done), timeout=2000)
                acknowledgments.extend(delivered)
                qtbot.waitUntil(lambda: retained.pending_tasks == 0, timeout=10000)
                assert retained.presentation.selected.sample == ((iteration * 47) % count) * ROWS
                samples.append(
                    {
                        "chunks": count,
                        "rss": working_set(),
                        "cache_bytes": retained._reader.history.cache_bytes,
                        "pending_tasks": live.pending_tasks,
                        "preview_sequence": live._preview.sequence,
                    }
                )
                assert not service.job(run.computation.id).done.is_set()
            retained.speed.setValue(40)
            playback_start = retained.presentation.selected.sample
            retained.play.click()
            qtbot.waitUntil(
                lambda start=playback_start: (
                    retained.presentation.selected.sample > start and retained.pending_tasks == 0
                ),
                timeout=5000,
            )
            qtbot.wait(150)
            retained.play.click()
        assert edit_future is not None
        edited = result(qtbot, edit_future)
        assert isinstance(edited.result, CommandAccepted)
        child = edited.editor
        assert child.experiment_context.attempt_id is None
        assert child.experiment_context.variant_id != run.attempt.variant_id
        assert run.editor.authority.snapshot() == before
        assert max(s["preview_sequence"] for s in samples) > min(
            s["preview_sequence"] for s in samples
        )
        # Replacement changes interpretation of the old run to historical,
        # preserving retained bytes and the still-running attempt.
        live.attach(child.kernel, child.client)
        observer.attach(child.kernel)
        live.observe_attempt(service.job(run.computation.id).view)
        qtbot.waitUntil(lambda: live.presentation is not None, timeout=15000)
        assert not live._source.current_source
        cancelled = perf_counter()
        service.cancel(CancelRequest(run.computation.id))
        report["cancel_ack_seconds"] = perf_counter() - cancelled
        qtbot.waitUntil(lambda: service.job(run.computation.id).done.is_set(), timeout=15000)
        report["cancel_finish_seconds"] = perf_counter() - cancelled
        assert service.wait(run.computation.id).outcome is ComputationOutcome.CANCELLED
        heartbeat.stop()
        assert controller.experiments.verify_run(run.attempt.id)
        assert all(resources.verified_path(ref).exists() for ref in chunks)
        report.update(
            {
                "ack_p95": float(np.percentile(acknowledgments, 95)),
                "ack_p99": float(np.percentile(acknowledgments, 99)),
                "heartbeat_max_gap": max(b - a for a, b in pairwise(pulses)),
                "incremental_rss": max(s["rss"] for s in samples if s["chunks"] == 128)
                - max(s["rss"] for s in samples if s["chunks"] == 16),
                "attempt": run.attempt.id,
                "input_commit": run.attempt.commit,
                "child_variant": child.experiment_context.variant_id,
                "worker_pid": service.job(run.computation.id).view.worker_pid,
            }
        )
        assert report["incremental_rss"] <= 64 * 1024**2, report
        assert max(s["cache_bytes"] for s in samples) <= 64 * 1024**2
        assert max(s["pending_tasks"] for s in samples) <= 2
        assert report["ack_p95"] <= 0.1 and report["ack_p99"] <= 0.2, report
        assert report["heartbeat_max_gap"] <= 0.25, report
        report["passed"] = True
    finally:
        heartbeat.stop()
        gc.callbacks.remove(collection)
        observer.attach(None)
        report.update(
            {
                "samples": samples,
                "pulses": pulses,
                "pulse_thread_times": pulse_cpu,
                "acknowledgments": acknowledgments,
                "collections": collections,
            }
        )
        if run is not None:
            view = service.job(run.computation.id).view
            report["run_before_cleanup"] = {
                "phase": view.phase,
                "status": view.session.status.value,
                "diagnostic": view.diagnostic,
                "preview": view.preview.sequence if view.preview else None,
                "panel_status": live.status.text(),
            }
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        for panel in panels:
            panel.attach(None, None)
            panel.shutdown()
        if run is not None and not service.job(run.computation.id).done.is_set():
            service.cancel(CancelRequest(run.computation.id))
        controller.close_background(wait=True)
        controller.session.close()
        if run is not None:
            run.editor.close()
        original.close()
        service.close()
