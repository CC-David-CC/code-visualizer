"""P7 response gates with actual native histories, an unpaused gas worker and Git."""

import gc
import json
from itertools import pairwise
from time import perf_counter

import numpy as np
from fixtures.gas_project import change, short_project, store
from PySide6.QtCore import QTimer
from test_coupled_active_git import result
from test_electrothermal_git import repository
from test_field_history_stress import working_set
from test_hybrid_gas_computation import host as local_host
from test_hybrid_gas_computation import request, resources
from test_hybrid_gas_particle import WINDOWS

from code_visualizer.application.computation import execute_computation
from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.domain_commands import SetDomainProperty
from code_visualizer.application.git_service import GitProjectController
from code_visualizer.application.messages import CommandAccepted, CommandDeferred
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.computation import CancelRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.extensions.hybrid_gas.domain import identity
from code_visualizer.extensions.hybrid_gas.records import HISTORY_TYPE
from code_visualizer.ui_qt.adaptive_history import CellHistoryPanel, CellViewSource
from code_visualizer.ui_qt.runtime_observer import QtRuntimeObserver


@WINDOWS
def test_native_worker_scrubbing_and_policy_fork_keep_p7_response_bounds(
    qtbot, tmp_path, monkeypatch
):
    # Predeclared reader load: complete real 16/128-cell native histories, three
    # exact samples and five components. These short runs qualify the application
    # path, not the separately frozen long-run statistical benchmark.
    histories = []
    for cells in (16, 128):
        source = change(short_project(), "gas:policy", "cells", cells)
        with local_host(source, tmp_path / f"reader-{cells}") as kernel:
            evidence = execute_computation(kernel, request(source))
            assert evidence.outcome is ComputationOutcome.SUCCEEDED, evidence.diagnostics
            histories.append(
                (
                    resources(evidence, kernel.resource_store, HISTORY_TYPE)[-1],
                    kernel.resource_store,
                )
            )
    project = short_project()
    for name, value in (("final_tick", 40000), ("checkpoint_ticks", 4000), ("preview_windows", 25)):
        project = change(project, "gas:policy", name, value)
    root = tmp_path / "repository"
    repository(root, project)
    store(root / "project")
    host = ComputationService(max_workers=1)
    publications = []
    publish = host.publish

    def timed_publication(job, event):
        started = perf_counter()
        publish(job, event)
        publications.append(
            {
                "started": started,
                "finished": perf_counter(),
                "type": type(event).__name__,
                "completed": getattr(event, "completed", None),
                "artifact": getattr(getattr(event, "artifact", None), "id", None),
            }
        )

    monkeypatch.setattr(host, "publish", timed_publication)
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
    pulses, acknowledgments, measurements, stages, collections = [], [], [], [], []
    timer = QTimer(live)
    timer.setInterval(10)
    timer.timeout.connect(lambda: pulses.append(perf_counter()))
    report = {
        "phase": "P7-gas-ui",
        "heartbeat_limit_seconds": 0.25,
        "ack_limits_seconds": {"p95": 0.1, "p99": 0.2},
        "cache_limit_bytes": 64 * 1024**2,
        "reader_stimulus": "Actual 16/128-cell, three-sample, five-component native histories",
        "rss_measurement": "Incremental presentation: large versus small history, as in P6",
        "worker": "Unpaused native gas, 40000 ticks, 500/sample, 4000/checkpoint, 25/preview",
    }

    def collection(phase, info):
        collections.append((perf_counter(), phase, info["generation"]))

    gc.callbacks.append(collection)
    run = None
    try:

        def show_retained(index):
            reference, resource_store = histories[index]
            retained.inspect(
                CellViewSource(
                    reference,
                    resource_store,
                    f"reader-{index}",
                    str(index + 1) * 64,
                    0,
                    False,
                    "RETAINED NATIVE READER STIMULUS",
                )
            )
            qtbot.waitUntil(lambda: retained.pending_tasks == 0, timeout=10000)
            assert retained.presentation is not None

        show_retained(0)
        for sample in range(3):
            retained.time_cursor.setValue(sample)
            qtbot.waitUntil(lambda: retained.pending_tasks == 0, timeout=10000)
        gc.collect()
        report["warmed_rss"] = working_set()
        timer.start()
        stages.append(("freeze", perf_counter()))
        run = result(qtbot, controller.submit_freeze_and_run(request(project)))
        live.attach(run.editor.kernel, run.editor.client)
        observer.attach(run.editor.kernel)
        qtbot.waitUntil(
            lambda: (
                (live.presentation is not None and live._preview is not None)
                or host.job(run.computation.id).done.is_set()
            ),
            timeout=90000,
        )
        assert not host.job(run.computation.id).done.is_set(), host.job(run.computation.id).view
        frozen = run.editor.authority.snapshot()
        stages.append(("scrub", perf_counter()))
        future = None
        for iteration in range(80):
            if iteration == 40:
                show_retained(1)
            started = perf_counter()
            retained.time_cursor.setValue(iteration % 3)
            retained.component.setCurrentIndex(iteration % 5)
            retained.view.horizontalScrollBar().setValue(iteration * 3)
            if iteration % 8 == 0:
                live.select.click()
            if iteration == 4:
                deferred = run.editor.client.submit(
                    SetDomainProperty(
                        "gas:experiment", "gas:policy", identity("Policy", "seed"), 10009
                    )
                )
                assert isinstance(deferred, CommandDeferred)
                future = controller.experiments.edits[deferred.details["operation_id"]]
            acknowledged = []
            QTimer.singleShot(
                0, lambda t=started, done=acknowledged: done.append(perf_counter() - t)
            )
            qtbot.waitUntil(lambda done=acknowledged: bool(done), timeout=2000)
            acknowledgments.extend(acknowledged)
            qtbot.waitUntil(lambda: retained.pending_tasks == 0, timeout=10000)
            assert retained.presentation.selected.sample == iteration % 3
            measurements.append(
                {
                    "rss": working_set(),
                    "cache_bytes": retained._reader.cache_bytes + live._reader.cache_bytes,
                    "pending": live.pending_tasks,
                    "preview": live._preview.sequence,
                    "reader_cells": 16 if iteration < 40 else 128,
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
        assert len(controller.experiments.store.identities("variants")) == 2
        assert max(s["preview"] for s in measurements) > min(s["preview"] for s in measurements)
        live.attach(child.kernel, child.client)
        observer.attach(child.kernel)
        live.observe_attempt(host.job(run.computation.id).view)
        qtbot.waitUntil(lambda: live.presentation is not None, timeout=10000)
        assert not live._source.current_source
        selected = child.kernel.selection.state
        live.select.click()
        assert child.kernel.selection.state == selected
        cancelled = perf_counter()
        stages.append(("cancel", cancelled))
        host.cancel(CancelRequest(run.computation.id))
        report["cancel_ack_seconds"] = perf_counter() - cancelled
        qtbot.waitUntil(lambda: host.job(run.computation.id).done.is_set(), timeout=15000)
        report["cancel_finish_seconds"] = perf_counter() - cancelled
        report["forced_termination"] = host.job(run.computation.id).view.forced_termination
        report["diagnostics"] = [
            {"code": diagnostic.code, "message": diagnostic.message}
            for diagnostic in host.wait(run.computation.id).diagnostics
        ]
        assert host.wait(run.computation.id).outcome is ComputationOutcome.CANCELLED
        assert not host.job(run.computation.id).view.forced_termination
        timer.stop()
        assert controller.experiments.verify_run(run.attempt.id)
        report.update(
            ack_p95=float(np.percentile(acknowledgments, 95)),
            ack_p99=float(np.percentile(acknowledgments, 99)),
            heartbeat_max_gap=max(b - a for a, b in pairwise(pulses)),
            incremental_rss=max(s["rss"] for s in measurements if s["reader_cells"] == 128)
            - max(s["rss"] for s in measurements if s["reader_cells"] == 16),
            total_host_incremental_rss=max(s["rss"] for s in measurements) - report["warmed_rss"],
            attempt=run.attempt.id,
            input_commit=run.attempt.commit,
            child_variant=child.experiment_context.variant_id,
        )
        assert report["heartbeat_max_gap"] <= 0.25, report
        assert report["ack_p95"] <= 0.1 and report["ack_p99"] <= 0.2, report
        assert report["incremental_rss"] <= 64 * 1024**2, report
        assert max(s["cache_bytes"] for s in measurements) <= 64 * 1024**2
        assert max(s["pending"] for s in measurements) <= 2
        report["passed"] = True
    finally:
        timer.stop()
        gc.callbacks.remove(collection)
        observer.attach(None)
        report.update(
            measurements=measurements,
            pulses=pulses,
            acknowledgments=acknowledgments,
            stages=stages,
            garbage_collections=collections,
            publications=publications,
        )
        (tmp_path / "gas-ui-stress.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
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
