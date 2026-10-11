"""P7 response gates with an unpaused adaptive worker, retained cells and a real Git fork."""

import gc
import json
import os
import sys
from itertools import pairwise
from pathlib import Path
from threading import Event, Thread, get_ident
from time import perf_counter, thread_time

import numpy as np
from PySide6.QtCore import QTimer
from test_adaptive_artifacts import fixture
from test_adaptive_computation import host as local_host
from test_adaptive_computation import request as computation_request
from test_adaptive_domain import change
from test_adaptive_git import policy_edit, request
from test_coupled_active_git import result
from test_electrothermal_git import repository
from test_field_history_stress import working_set

from code_visualizer.application.adaptive_examples import adaptive_diffusion_project
from code_visualizer.application.computation import execute_computation
from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.git_service import GitProjectController
from code_visualizer.application.messages import CommandAccepted, CommandDeferred
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.computation import CancelRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.extensions.adaptive_fields.units import quantity
from code_visualizer.ui_qt.adaptive_history import CellHistoryPanel, CellViewSource
from code_visualizer.ui_qt.runtime_observer import QtRuntimeObserver


def test_adaptive_worker_scrubbing_and_policy_fork_keep_p7_response_bounds(
    qtbot, tmp_path, monkeypatch
):
    # The retained reader stimulus is explicitly synthetic, not claimed physics.
    small_source, small_resources = fixture(tmp_path / "reader-small")
    source, resources = fixture(tmp_path / "reader-large", cells=511)
    project = adaptive_diffusion_project()
    project = change(project, "adaptive:policy", "maximum_dt", quantity(0.0025))
    project = change(project, "adaptive:policy", "preview_every", 1)
    root = tmp_path / "repository"
    repository(root, project)
    host = ComputationService(max_workers=1)
    original = ProjectSession.open(root / "project", computations=host)
    controller = GitProjectController(original)
    retained, live = CellHistoryPanel(), CellHistoryPanel()
    for panel in (retained, live):
        qtbot.addWidget(panel)
        panel.resize(900, 780)
        panel.attach(original.kernel, original.client)
        panel.show()
    observer = QtRuntimeObserver(live)
    observer.attemptsChanged.connect(
        lambda attempts: live.observe_attempt(attempts[-1]) if attempts else None
    )
    pulses, cpu_pulses, acknowledgments, samples, draws, stages = [], [], [], [], [], []
    for name, panel in (("retained", retained), ("live", live)):
        draw = panel._draw

        def measured(value, draw=draw, name=name):
            start, cpu = perf_counter(), thread_time()
            try:
                return draw(value)
            finally:
                draws.append((name, start, perf_counter() - start, thread_time() - cpu))

        monkeypatch.setattr(panel, "_draw", measured)
    timer = QTimer(live)
    timer.setInterval(10)

    def pulse():
        pulses.append(perf_counter())
        cpu_pulses.append(thread_time())

    timer.timeout.connect(pulse)
    report = {
        "phase": "P7-continuum",
        "heartbeat_limit_seconds": 0.25,
        "ack_limits_seconds": {"p95": 0.1, "p99": 0.2},
        "cache_limit_bytes": 64 * 1024**2,
        "reader_stimulus": "Synthetic 16/17 then 511/512-cell epochs; not physical evidence",
        "rss_measurement": "Incremental presentation: large versus small history, as in P6",
        "worker": "Unpaused production adaptive diffusion, dt_max=.0025 s, preview_every=1",
    }
    receipt = Path(os.environ.get("CODE_VISUALIZER_P7_STRESS_RECEIPT", tmp_path / "stress.json"))
    collections, stacks = [], []
    gui_thread = get_ident()
    stop_profile = Event()

    def collection(phase, info):
        if info["generation"] >= 1:
            collections.append((phase, perf_counter(), thread_time(), get_ident(), dict(info)))

    def profile():
        while not stop_profile.wait(0.02):
            frame = sys._current_frames().get(gui_thread)
            stack = []
            while frame is not None and len(stack) < 10:
                stack.append((frame.f_code.co_filename, frame.f_code.co_name, frame.f_lineno))
                frame = frame.f_back
            stacks.append((perf_counter(), stack))

    profiling = os.environ.get("CODE_VISUALIZER_P7_PROFILE") == "1"
    profiler = Thread(target=profile, name="p7-gui-diagnostic", daemon=True)
    gc.callbacks.append(collection)
    run = edited = None
    try:
        warm = change(adaptive_diffusion_project(), "adaptive:policy", "final_time", quantity(0.2))
        warm = change(warm, "adaptive:policy", "checkpoint_interval", quantity(0.1))
        with local_host(warm, tmp_path / "warm") as kernel:
            evidence = execute_computation(kernel, computation_request(warm))
            assert evidence.outcome is ComputationOutcome.SUCCEEDED, evidence.diagnostics
        retained.inspect(
            CellViewSource(
                small_source.root,
                small_resources,
                "reader-small",
                "b" * 64,
                0,
                False,
                "READER STIMULUS",
            )
        )
        qtbot.waitUntil(lambda: retained.presentation is not None, timeout=10000)
        for sample in range(6):
            retained.time_cursor.setValue(sample)
            qtbot.waitUntil(lambda: retained.pending_tasks == 0, timeout=10000)
        gc.collect()
        report["warmed_rss"] = working_set()
        timer.start()
        if profiling:
            profiler.start()
        stages.append(("freeze", perf_counter()))
        run = result(qtbot, controller.submit_freeze_and_run(request(original)))
        stages.append(("attach", perf_counter()))
        live.attach(run.editor.kernel, run.editor.client)
        observer.attach(run.editor.kernel)
        qtbot.waitUntil(
            lambda: (
                (live.presentation is not None and live._preview is not None)
                or host.job(run.computation.id).done.is_set()
            ),
            timeout=30000,
        )
        assert not host.job(run.computation.id).done.is_set(), (
            host.wait(run.computation.id) if host.job(run.computation.id).done.is_set() else None
        )
        frozen = run.editor.authority.snapshot()
        stages.append(("scrub", perf_counter()))
        future = None
        for iteration in range(80):
            if iteration == 40:
                retained.inspect(
                    CellViewSource(
                        source.root,
                        resources,
                        "reader-large",
                        "c" * 64,
                        0,
                        False,
                        "READER STIMULUS",
                    )
                )
                qtbot.waitUntil(lambda: retained.pending_tasks == 0, timeout=10000)
            started = perf_counter()
            retained.time_cursor.setValue(iteration % 6)
            retained.view.horizontalScrollBar().setValue(iteration * 3)
            if iteration % 8 == 0:
                live.select.click()
            if iteration == 4:
                deferred = policy_edit(run.editor, 0.003)
                assert isinstance(deferred, CommandDeferred)
                future = controller.experiments.edits[deferred.details["operation_id"]]
            acknowledged = []
            QTimer.singleShot(
                0, lambda t=started, done=acknowledged: done.append(perf_counter() - t)
            )
            qtbot.waitUntil(lambda done=acknowledged: bool(done), timeout=2000)
            acknowledgments.extend(acknowledged)
            qtbot.waitUntil(lambda: retained.pending_tasks == 0, timeout=10000)
            assert retained.presentation.selected.sample == iteration % 6
            samples.append(
                {
                    "rss": working_set(),
                    "cache_bytes": retained._reader.cache_bytes + live._reader.cache_bytes,
                    "pending": live.pending_tasks,
                    "preview": live._preview.sequence,
                    "reader_base_cells": 16 if iteration < 40 else 511,
                }
            )
            assert not host.job(run.computation.id).done.is_set()
        assert future is not None
        stages.append(("fork result", perf_counter()))
        edited = result(qtbot, future)
        assert isinstance(edited.result, CommandAccepted)
        child = edited.editor
        assert child.experiment_context.attempt_id is None
        assert child.experiment_context.variant_id != run.attempt.variant_id
        assert run.editor.authority.snapshot() == frozen
        assert max(s["preview"] for s in samples) > min(s["preview"] for s in samples)
        live.attach(child.kernel, child.client)
        stages.append(("child attached", perf_counter()))
        observer.attach(child.kernel)
        live.observe_attempt(host.job(run.computation.id).view)
        qtbot.waitUntil(lambda: live.presentation is not None, timeout=10000)
        assert not live._source.current_source
        cancelled = perf_counter()
        stages.append(("cancel", cancelled))
        host.cancel(CancelRequest(run.computation.id))
        report["cancel_ack_seconds"] = perf_counter() - cancelled
        qtbot.waitUntil(lambda: host.job(run.computation.id).done.is_set(), timeout=15000)
        report["cancel_finish_seconds"] = perf_counter() - cancelled
        assert host.wait(run.computation.id).outcome is ComputationOutcome.CANCELLED
        timer.stop()
        assert controller.experiments.verify_run(run.attempt.id)
        report.update(
            ack_p95=float(np.percentile(acknowledgments, 95)),
            ack_p99=float(np.percentile(acknowledgments, 99)),
            heartbeat_max_gap=max(b - a for a, b in pairwise(pulses)),
            incremental_rss=max(s["rss"] for s in samples if s["reader_base_cells"] == 511)
            - max(s["rss"] for s in samples if s["reader_base_cells"] == 16),
            total_host_incremental_rss=max(s["rss"] for s in samples) - report["warmed_rss"],
            attempt=run.attempt.id,
            input_commit=run.attempt.commit,
            child_variant=child.experiment_context.variant_id,
        )
        assert report["heartbeat_max_gap"] <= 0.25, report
        assert report["ack_p95"] <= 0.1 and report["ack_p99"] <= 0.2, report
        assert report["incremental_rss"] <= 64 * 1024**2, report
        assert max(s["cache_bytes"] for s in samples) <= 64 * 1024**2
        assert max(s["pending"] for s in samples) <= 2
        report["passed"] = True
    finally:
        timer.stop()
        stop_profile.set()
        if profiling:
            profiler.join(timeout=2)
        gc.callbacks.remove(collection)
        observer.attach(None)
        report.update(
            samples=samples,
            pulses=pulses,
            pulse_thread_times=cpu_pulses,
            acknowledgments=acknowledgments,
            draws=draws,
            stages=stages,
            garbage_collections=collections,
            diagnostic_stacks=stacks,
        )
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        for panel in (retained, live):
            panel.attach(None, None)
            panel.shutdown()
        if run is not None and not host.job(run.computation.id).done.is_set():
            host.cancel(CancelRequest(run.computation.id))
        controller.close_background(wait=True)
        controller.session.close()
        if run is not None:
            run.editor.close()
        original.close()
        host.close()
