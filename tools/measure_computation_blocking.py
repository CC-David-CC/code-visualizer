"""Record the pre-P1 GUI blocking baseline using the real workbench Run handler.

From the repository root, set PYTHONPATH=src and run this script with the project
Python environment. It defaults to Qt's offscreen platform and performs real CPU
work, without sleeping. The receipt is a baseline observation, not a P1 gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import threading
import time
import traceback
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

import PySide6
from PySide6.QtCore import Qt, QThread, QTimer, qVersion
from PySide6.QtWidgets import QApplication

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.domain.computation import BackendDefinition
from code_visualizer.domain.evidence import EvidenceObservation
from code_visualizer.domain.intentional import (
    ConceptDefinition,
    DomainModel,
    DomainSchema,
    DomainWorkspace,
    IntentionalNode,
)
from code_visualizer.domain.project import Project
from code_visualizer.domain.transformation import Representation
from code_visualizer.execution.backends import BackendResult, PreparedComputation, RegisteredBackend
from code_visualizer.extensions.builtin import computation_bundle
from code_visualizer.extensions.registry import DomainExtensionBundle, DomainExtensionRegistry
from code_visualizer.ui_qt.features.domain_workbench.widget import DomainWorkbenchWidget


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path("docs/receipts/transition-p1-before.json")
    )
    parser.add_argument("--cpu-seconds", type=float, default=0.4)
    args = parser.parse_args()
    if not 0.35 <= args.cpu_seconds <= 3:
        parser.error("--cpu-seconds must be between 0.35 and 3")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    application = QApplication([])
    origin = time.perf_counter()
    heartbeat: list[float] = []
    measurements: dict[str, object] = {}
    errors: list[str] = []
    gui_thread = threading.get_ident()

    def elapsed_ms() -> float:
        return round((time.perf_counter() - origin) * 1000, 6)

    def execute(_snapshot: PreparedComputation) -> BackendResult:
        measurements["backend_thread_id"] = threading.get_ident()
        measurements["backend_is_gui_thread"] = QThread.currentThread() == application.thread()
        measurements["backend_stack"] = [
            {"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
            for frame in traceback.extract_stack()
        ]
        measurements["backend_start_ms"] = elapsed_ms()
        cpu_start = time.thread_time()
        iterations, accumulator = 0, 1
        while time.thread_time() - cpu_start < args.cpu_seconds:
            for _ in range(8192):
                accumulator = (accumulator * 1664525 + 1013904223) & 0xFFFFFFFF
            iterations += 8192
        measurements["backend_cpu_ms"] = (time.thread_time() - cpu_start) * 1000
        measurements["backend_end_ms"] = elapsed_ms()
        measurements["arithmetic_iterations"] = iterations
        return BackendResult(
            observations=(EvidenceObservation("baseline:result", ("baseline:node",), accumulator),)
        )

    schema = DomainSchema(
        "org.example.blocking:schema",
        "org.example.blocking",
        "1",
        (ConceptDefinition("org.example.blocking:item", "Item"),),
    )
    model = DomainModel(
        "baseline:model",
        schema.id,
        schema.version,
        ("baseline:node",),
        (IntentionalNode("baseline:node", schema.concepts[0].id),),
    )
    project = Project(
        "baseline:project",
        "Computation blocking baseline",
        (),
        domain_workspace=DomainWorkspace((schema,), (model,)),
    )
    backend = RegisteredBackend(
        BackendDefinition(
            "org.example.blocking.backend",
            "1",
            "CPU-bound baseline",
            Representation(schema.namespace, schema.version),
            schema.id,
            schema.version,
        ),
        execute,
    )
    registry = DomainExtensionRegistry(
        (
            computation_bundle(),
            DomainExtensionBundle("org.example.blocking", "1", backends=(backend,)),
        )
    )
    kernel = ProjectKernel(ProjectAuthority(project), extensions=registry)
    widget = DomainWorkbenchWidget()
    widget.attach(kernel)
    widget.resize(1000, 700)
    widget.show()
    assert widget.current_model() == model
    assert widget.backend_choice.currentData() == backend.definition.key
    timer = QTimer()
    timer.setTimerType(Qt.TimerType.PreciseTimer)
    timer.setInterval(10)
    timer.timeout.connect(lambda: heartbeat.append(elapsed_ms()))

    def invoke() -> None:
        handler_start = elapsed_ms()
        measurements["handler_start_ms"] = handler_start
        try:
            widget.run_computation()
            measurements["status_text"] = widget.status.text()
            measurements["evidence_outcomes"] = [
                item.outcome.value for item in kernel.runtime.evidence_records()
            ]
        except Exception:
            errors.append(traceback.format_exc())
        finally:
            handler_end = elapsed_ms()
            measurements["handler_end_ms"] = handler_end
            measurements["handler_duration_ms"] = handler_end - handler_start
            QTimer.singleShot(150, application.quit)

    timer.start()
    QTimer.singleShot(120, invoke)
    application.exec()
    timer.stop()
    widget.attach(None)
    widget.close()
    kernel.close()
    gaps = [round(b - a, 6) for a, b in pairwise(heartbeat)]
    receipt = {
        "version": 1,
        "classification": "pre-P1 observational baseline; not a P1 acceptance gate",
        "created_utc": datetime.now(UTC).isoformat(),
        "reproduce_powershell": (
            "$env:PYTHONPATH='src'; .venv/Scripts/python.exe tools/measure_computation_blocking.py"
        ),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "processor": os.environ.get("PROCESSOR_IDENTIFIER", platform.processor()),
            "logical_cpu_count": os.cpu_count(),
            "pyside6": PySide6.__version__,
            "qt": qVersion(),
            "qt_platform": application.platformName(),
        },
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, encoding="utf-8"
        ).strip(),
        "working_source_sha256": {
            str(path).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (
                Path("src/code_visualizer/ui_qt/features/domain_workbench/widget.py"),
                Path("src/code_visualizer/application/computation.py"),
                Path("src/code_visualizer/execution/lifecycle.py"),
                Path(__file__),
            )
        },
        "requested_cpu_ms": args.cpu_seconds * 1000,
        "gui_thread_id": gui_thread,
        "heartbeat_interval_ms": timer.interval(),
        "heartbeat_timestamps_ms": heartbeat,
        "heartbeat_gaps_ms": gaps,
        "max_heartbeat_gap_ms": max(gaps, default=0),
        "measurements": measurements,
        "errors": errors,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(args.output), "max_gap_ms": max(gaps, default=0)}))
    assert not errors, errors
    assert measurements["backend_is_gui_thread"] is True
    assert measurements["evidence_outcomes"] == ["succeeded"]
    assert float(str(measurements["backend_cpu_ms"])) >= 350
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
