"""Measure and record the release-gate 500-diagram reference workload."""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import tempfile
from pathlib import Path
from time import perf_counter

from code_visualizer.application.queries import ProjectQueries
from code_visualizer.application.scale_fixture import build_scale_project
from code_visualizer.application.search import search_project
from code_visualizer.generation import generate_python
from code_visualizer.persistence import ProjectStore
from code_visualizer.rendering import layout_drakon
from code_visualizer.validation import validate_project


def _measure(operation):
    started = perf_counter()
    value = operation()
    return value, perf_counter() - started


def benchmark(*, include_gui: bool) -> dict[str, object]:
    project = build_scale_project()
    semantic_project = build_scale_project(atoms_per_diagram=20)
    large_diagram = build_scale_project(1, atoms_per_diagram=300).documents[0]
    with tempfile.TemporaryDirectory(prefix="code-visualizer-scale-") as temporary:
        root = Path(temporary) / "project"
        store = ProjectStore(root)
        _saved, save_seconds = _measure(lambda: store.initialize(project))
        opened, open_seconds = _measure(store.recover)
        matches, search_seconds = _measure(lambda: search_project(opened, "Function 049"))
        diagnostics, validation_seconds = _measure(lambda: validate_project(opened))
        queries, semantic_index_seconds = _measure(
            lambda: ProjectQueries.from_project(semantic_project)
        )
        generated, generation_seconds = _measure(lambda: generate_python(opened))
        scene, layout_seconds = _measure(lambda: layout_drakon(large_diagram))
        gui_seconds: float | None = None
        eager_tabs: int | None = None
        if include_gui:
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            from PySide6.QtCore import QSettings
            from PySide6.QtWidgets import QApplication

            from code_visualizer.ui_qt.main_window import CloseDecision, MainWindow

            app = QApplication.instance() or QApplication([])
            window = MainWindow(
                close_decision=lambda _session: CloseDecision.DISCARD,
                settings=QSettings(
                    str(Path(temporary) / "benchmark.ini"), QSettings.Format.IniFormat
                ),
            )
            started = perf_counter()
            window.open_project(root)
            app.processEvents()
            gui_seconds = perf_counter() - started
            eager_tabs = window.documents.count()
            window.close()
            app.processEvents()
        return {
            "fixture": {
                "diagram_count": len(opened.documents),
                "large_diagram_atoms": len(large_diagram.body.atoms),
                "native_bytes": store.project_file.stat().st_size,
                "semantic_atoms_per_diagram": 20,
            },
            "measurements_seconds": {
                "generate_python": generation_seconds,
                "gui_open": gui_seconds,
                "layout_300_atoms": layout_seconds,
                "native_open": open_seconds,
                "native_save": save_seconds,
                "search": search_seconds,
                "semantic_index": semantic_index_seconds,
                "validate": validation_seconds,
            },
            "observations": {
                "diagnostic_count": len(diagnostics),
                "generated_characters": len(generated.source),
                "gui_eager_tabs": eager_tabs,
                "large_scene_nodes": len(scene.nodes),
                "search_matches": len(matches),
                "semantic_objects": len(queries.program.objects),
                "semantic_relations": len(queries.program.relations),
            },
            "platform": {
                "machine": platform.machine(),
                "operating_system": platform.platform(),
                "processor": platform.processor(),
                "python": sys.version.split()[0],
            },
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/performance/m9-scale-results.json"),
    )
    parser.add_argument("--no-gui", action="store_true")
    args = parser.parse_args()
    result = benchmark(include_gui=not args.no_gui)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
