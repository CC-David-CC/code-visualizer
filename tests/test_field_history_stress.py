"""Real chunked histories, CPU worker and native CAD share the existing host/UI."""

import gc
import json
import os
import sys
from dataclasses import replace
from itertools import pairwise
from pathlib import Path
from threading import Event, Thread, get_ident
from time import perf_counter, thread_time

import numpy as np
from fixtures.computation_worker_fixture import BACKEND_ID, fixture_registry, worker_profile
from fixtures.large_field_history import NODES, ROWS, build_histories
from PySide6.QtCore import QTimer

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.cad_artifacts import prepare_consumer
from code_visualizer.application.cad_examples import recipe_request, spring_cad_project
from code_visualizer.application.computation import execute_computation, start_computation
from code_visualizer.application.computation_process import default_profiles
from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.project_factory import create_default_project
from code_visualizer.domain.computation import (
    CancelRequest,
    ComputationParameter,
    ComputationRequest,
)
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.domain.transformation import OriginMap
from code_visualizer.domain.values import TensorDType, TensorValue
from code_visualizer.extensions.diffusion.domain import quantity
from code_visualizer.extensions.fields.preview import FieldPreview
from code_visualizer.extensions.fields.records import TemporalPosition
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.ui_qt.cad_artifacts import CadArtifactPanel
from code_visualizer.ui_qt.field_history import FieldHistoryPanel, FieldViewSource
from code_visualizer.ui_qt.runtime_observer import QtRuntimeObserver


def working_set():
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("faults", wintypes.DWORD),
                *(
                    (name, ctypes.c_size_t)
                    for name in (
                        "peak",
                        "working",
                        "peak_paged",
                        "paged",
                        "peak_nonpaged",
                        "nonpaged",
                        "pagefile",
                        "peak_pagefile",
                    )
                ),
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        process = ctypes.WinDLL("psapi", use_last_error=True)
        process.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if not process.GetProcessMemoryInfo(
            kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return counters.working
    pages = int(Path("/proc/self/statm").read_text().split()[1])
    return pages * os.sysconf("SC_PAGE_SIZE")


def test_large_field_history_with_cpu_and_native_cad_keeps_response_bounds(qtbot, tmp_path):
    host_profile = os.environ.get("CODE_VISUALIZER_P5_HOST_PROFILE", "normal")
    heartbeat_limits = {"normal": 0.25, "restricted": 0.35}
    if host_profile not in heartbeat_limits:
        raise ValueError("CODE_VISUALIZER_P5_HOST_PROFILE must be normal or restricted")
    heartbeat_limit = heartbeat_limits[host_profile]
    resources = ResourceStore(tmp_path / "store")
    roots, chunks = build_histories(resources)
    assert len(chunks) == 128
    assert all(3.99 * 1024**2 <= resources.describe(ref).byte_size <= 4 * 1024**2 for ref in chunks)
    registry = fixture_registry()
    closure = registry.resource_closure((roots[128],), resources)
    assert set(chunks) <= set(closure) and len(closure) < 1024
    host = ComputationService(profiles=(*default_profiles(), worker_profile()))
    kernel = ProjectKernel(
        ProjectAuthority(spring_cad_project()),
        computations=host,
        extensions=registry,
        resource_store=resources,
        evidence_store=EvidenceStore(tmp_path / "store"),
    )
    client = CodeVisualizerClient(kernel.authority, actor_id="field-stress")
    field_kernel = ProjectKernel(ProjectAuthority(create_default_project()), computations=host)
    field_client = CodeVisualizerClient(field_kernel.authority, actor_id="historical-field-view")
    field, cad = FieldHistoryPanel(), CadArtifactPanel()
    qtbot.addWidget(field)
    qtbot.addWidget(cad)
    field.attach(field_kernel, field_client)
    cad.attach(kernel, client)
    field.resize(1000, 780)
    cad.resize(800, 650)
    field.show()
    cad.show()
    pulses, acknowledgments, samples, runs = [], [], [], []
    pulse_thread_times = []
    heartbeat = QTimer(field)
    heartbeat.setInterval(10)

    def record_pulse():
        pulses.append(perf_counter())
        pulse_thread_times.append(thread_time())

    heartbeat.timeout.connect(record_pulse)
    observer = QtRuntimeObserver(field)
    observer.runtimeChanged.connect(lambda state: field.preview(state.preview) if state else None)
    stopped, burst, completed = Event(), Event(), Event()
    sequence = [0]
    producer = None
    cpu = None
    cpu_states = []
    report = {
        "platform": os.name,
        "host_profile": host_profile,
        "heartbeat_limit_seconds": heartbeat_limit,
        "nodes": NODES,
        "rows_per_chunk": ROWS,
        "closure_count": len(closure),
        "chunk_bytes": resources.describe(chunks[0]).byte_size,
    }
    receipt = Path(os.environ.get("CODE_VISUALIZER_P5_STRESS_RECEIPT", tmp_path / "stress.json"))
    garbage_collections = []

    def record_collection(phase, info):
        if info["generation"] < 1:
            return
        stack = []
        if phase == "start":
            frame = sys._getframe(1)
            while frame is not None and len(stack) < 8:
                stack.append((frame.f_code.co_filename, frame.f_code.co_name, frame.f_lineno))
                frame = frame.f_back
        garbage_collections.append(
            {
                "phase": phase,
                "time": perf_counter(),
                "thread_time": thread_time(),
                "thread": get_ident(),
                "info": dict(info),
                "stack": stack,
            }
        )

    # Observe collections without changing their policy or deferring them. Wall
    # and thread CPU time distinguish collector work from scheduling delays.
    gc.callbacks.append(record_collection)
    try:
        project = client.snapshot()
        solved = execute_computation(
            kernel,
            ComputationRequest(
                project.id,
                project.revision,
                "foundation.math.linear_equations",
                "1",
                "spring:equations",
            ),
        )
        assert solved.outcome is ComputationOutcome.SUCCEEDED, solved.diagnostics
        geometry = execute_computation(
            kernel, recipe_request(project, solved.artifacts[0].resource)
        )
        assert geometry.outcome is ComputationOutcome.SUCCEEDED, geometry.diagnostics
        solid = next(a for a in geometry.artifacts if a.id == "python:output:solid")
        prepared = []
        for concept in ("Tessellation", "Measurement"):
            edit = prepare_consumer(
                client.snapshot(), registry, geometry, solid.id, resources, resources, concept
            )
            assert isinstance(
                client.transaction(edit.commands, expected_revision=edit.revision), CommandAccepted
            )
            prepared.append(edit)
        meshed = execute_computation(kernel, prepared[0].request(client.snapshot()))
        assert meshed.outcome is ComputationOutcome.SUCCEEDED, meshed.diagnostics
        cad.inspect(meshed, meshed.artifacts[0].id, resources, current_source=False)
        qtbot.waitUntil(lambda: cad._future is None, timeout=15000)
        assert cad.scene.items(), cad.status.text()
        before = client.snapshot()
        field_before = field_client.snapshot()
        selected = field_kernel.selection.state
        source = FieldViewSource(
            roots[16], resources, "stress-run", "a" * 64, field_before.revision, False, "SUCCEEDED"
        )
        field.inspect(source)
        qtbot.waitUntil(lambda: field.presentation is not None, timeout=5000)
        field.follow.setChecked(False)
        for index in range(16):
            field.time_cursor.setValue(index * ROWS)
            qtbot.waitUntil(lambda: field.pending_tasks == 0, timeout=5000)
        gc.collect()
        warmed = working_set()
        report["warmed_rss"] = warmed
        history = field._reader.history
        accepted = history.slice(0)
        indices = np.arange(0, NODES, 8)
        frame = FieldPreview(
            history.series.interpretation,
            accepted.position,
            TemporalPosition(quantity(0.01), 1, 1),
            TensorValue(TensorDType.INT64, (len(indices),), tuple(int(i) for i in indices)),
            TensorValue(
                TensorDType.FLOAT64,
                (len(indices),),
                tuple(float(accepted.values[i]) for i in indices),
            ),
            TensorValue(
                TensorDType.FLOAT64,
                (len(indices),),
                tuple(float(accepted.values[i]) * 0.99 for i in indices),
            ),
        )
        field_kernel.runtime.register_origins(
            "stress-run", OriginMap(field_before.id, field_before.revision)
        )
        field_kernel.runtime.mark_starting(
            "stress-run", field_before.revision, field_before.revision
        )
        observer.attach(field_kernel)

        def produce():
            # Stimulus enters the existing already-admitted runtime plane off the
            # GUI thread. QtRuntimeObserver samples its single latest preview.
            while not stopped.is_set():
                if not burst.wait(0.05):
                    continue
                burst.clear()
                for _ in range(128):
                    if stopped.is_set():
                        return
                    sequence[0] += 1
                    field_kernel.runtime.record_computation_update(
                        frame.event("stress-run", sequence[0], "a" * 64, "stress:field")
                    )
                completed.set()

        producer = Thread(target=produce, name="field-preview-stimulus")
        producer.start()
        cpu = start_computation(
            kernel,
            ComputationRequest(
                before.id,
                before.revision,
                BACKEND_ID,
                "1",
                configuration=(ComputationParameter("mode", "cpu"),),
            ),
        )
        report["cpu_submitted_time"] = perf_counter()

        def cpu_started():
            view = host.job(cpu.id).view
            state = (view.phase, view.worker_pid, view.progress is not None)
            if not cpu_states or cpu_states[-1]["state"] != state:
                cpu_states.append({"time": perf_counter(), "state": state})
            return view.progress is not None

        qtbot.waitUntil(cpu_started, timeout=15000)
        heartbeat.start()
        for count in (16, 128):
            field.inspect(replace(source, resource=roots[count]))
            qtbot.waitUntil(lambda: field.pending_tasks == 0, timeout=5000)
            native_run = start_computation(kernel, prepared[1].request(before))
            runs.append(native_run.id)
            history = field._reader.history
            for iteration in range(48):
                started = perf_counter()
                field.time_cursor.setValue(((iteration * 47) % count) * ROWS)
                completed.clear()
                burst.set()
                delivered = []
                QTimer.singleShot(
                    0, lambda t=started, done=delivered: done.append(perf_counter() - t)
                )
                qtbot.waitUntil(lambda done=delivered: bool(done), timeout=2000)
                acknowledgments.extend(delivered)
                qtbot.waitUntil(completed.is_set, timeout=5000)
                qtbot.waitUntil(
                    lambda: field._preview is not None and field._preview.sequence == sequence[0],
                    timeout=5000,
                )
                qtbot.waitUntil(lambda: field.pending_tasks == 0, timeout=5000)
                assert field.presentation.selected.sample == ((iteration * 47) % count) * ROWS
                assert field.presentation.preview.accepted.sample == 0
                samples.append(
                    {
                        "chunks": count,
                        "rss": working_set(),
                        "cache_bytes": history.cache_bytes,
                        "decoded_chunks": history.decoded_chunks,
                        "pending_tasks": field.pending_tasks,
                        "preview_sequence": field._preview.sequence,
                    }
                )
                if iteration % 12 == 0:
                    cad.orientation.setCurrentIndex((cad.orientation.currentIndex() + 1) % 3)
            field.overview.setChecked(True)
            qtbot.waitUntil(lambda: field.pending_tasks == 0, timeout=15000)
            assert len(field.presentation.image_times) == 64
            field.overview.setChecked(False)
            qtbot.waitUntil(lambda: field.pending_tasks == 0, timeout=5000)
            qtbot.waitUntil(lambda run=native_run: host.job(run.id).done.is_set(), timeout=30000)
            assert host.wait(native_run.id).outcome is ComputationOutcome.SUCCEEDED
        cancelled = perf_counter()
        host.cancel(CancelRequest(cpu.id))
        report["cancel_ack_seconds"] = perf_counter() - cancelled
        qtbot.waitUntil(lambda: host.job(cpu.id).done.is_set(), timeout=15000)
        report["cancel_finish_seconds"] = perf_counter() - cancelled
        assert host.wait(cpu.id).outcome is ComputationOutcome.CANCELLED
        heartbeat.stop()
        assert client.snapshot() is before and field_client.snapshot() is field_before
        assert field_kernel.selection.state == selected
        assert len(field_kernel.runtime.history("stress-run")) == 1
        assert all(resources.verified_path(ref).exists() for ref in chunks)
        report.update(
            {
                "warmed_rss": warmed,
                "cad_evidence": meshed.id,
                "cad_attempts": runs,
                "cpu_pid": host.job(cpu.id).view.worker_pid,
                "forced_cpu_termination": host.job(cpu.id).view.forced_termination,
                "preview_stimulus": "background admitted-event bursts through QtRuntimeObserver",
                "previews_generated": sequence[0],
                "ack_p95": float(np.percentile(acknowledgments, 95)),
                "ack_p99": float(np.percentile(acknowledgments, 99)),
                "heartbeat_max_gap": max(b - a for a, b in pairwise(pulses)),
                "incremental_rss": max(s["rss"] for s in samples if s["chunks"] == 128)
                - max(s["rss"] for s in samples if s["chunks"] == 16),
            }
        )
        assert report["incremental_rss"] <= 64 * 1024**2, report
        assert max(s["cache_bytes"] for s in samples) <= 64 * 1024**2
        assert report["ack_p95"] <= 0.1 and report["ack_p99"] <= 0.2, report
        assert report["heartbeat_max_gap"] <= heartbeat_limit, report
        report["passed"] = True
    finally:
        gc.callbacks.remove(record_collection)
        heartbeat.stop()
        if cpu is not None:
            job = host.job(cpu.id)
            worker = job.worker
            report["cpu_before_cleanup"] = {
                "phase": job.view.phase,
                "status": job.view.session.status.value,
                "progress": job.view.progress is not None,
                "diagnostic": job.view.diagnostic,
                "error": repr(job.error) if job.error is not None else None,
                "worker_pid": job.view.worker_pid,
                "worker_active": worker.is_active if worker is not None else False,
                "worker_stderr": worker.stderr if worker is not None else None,
                "time": perf_counter(),
            }
            if not report.get("passed"):
                stacks = []
                for thread_id, frame in sys._current_frames().items():
                    entries = []
                    while frame is not None and len(entries) < 12:
                        entries.append(
                            (frame.f_code.co_filename, frame.f_code.co_name, frame.f_lineno)
                        )
                        frame = frame.f_back
                    stacks.append({"thread": thread_id, "frames": entries})
                report["failure_stacks"] = stacks
        observer.attach(None)
        stopped.set()
        burst.set()
        if producer is not None:
            producer.join(timeout=5)
        report.update(
            {
                "samples": samples,
                "acknowledgments": acknowledgments,
                "pulses": pulses,
                "pulse_thread_times": pulse_thread_times,
                "garbage_collections": garbage_collections,
                "cpu_startup_states": cpu_states,
            }
        )
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        field.attach(None, None)
        field.shutdown()
        cad.attach(None, None)
        field_client.close()
        field_kernel.close()
        kernel.close()
        client.close()
        host.close()
