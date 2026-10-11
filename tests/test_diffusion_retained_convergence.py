"""Convergence measured from sealed worker output, independently of solver internals."""

import json
import os
from pathlib import Path

import numpy as np
from test_diffusion_checkpoints import history, host, latest, request

from code_visualizer.application.computation import execute_computation
from code_visualizer.application.field_examples import diffusion_project
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.extensions.fields.records import SERIES_TYPE


def test_published_field_convergence_matches_independent_continuum_and_semidiscrete_references(
    tmp_path,
):
    reports = {}
    for nodes, steps in ((33, 512), (65, 2048), (129, 8192), (33, 1024), (33, 2048)):
        project = diffusion_project(
            nodes=nodes,
            steps=steps,
            sample_every=steps // 8,
            checkpoint_every=steps,
            preview_every=steps,
        )
        with host(project, tmp_path / f"{nodes}-{steps}") as kernel:
            evidence = execute_computation(kernel, request(project))
            assert evidence.outcome is ComputationOutcome.SUCCEEDED, evidence.diagnostics
            reference = latest(evidence, kernel.resource_store, SERIES_TYPE)
            retained = history(reference, kernel.resource_store)
            try:
                assert retained.sample_count == 9
                x = retained.coordinates()
                final = retained.slice(8)
                assert final.position.step == steps and final.position.time.magnitude == 1.0
                assert retained.interpretation.unit.id == "foundation.units.si:kelvin"
                assert retained.interpretation.quantity_kind.value == "interval"
                exact = 10 * np.exp(-0.1 * np.pi**2) * np.sin(np.pi * x)
                dx = 1 / (nodes - 1)
                eigenvalue = -4 * 0.1 / dx**2 * np.sin(np.pi / (2 * (nodes - 1))) ** 2
                semidiscrete = 10 * np.exp(eigenvalue) * np.sin(np.pi * x)
                previous_norm = float("inf")
                for i in range(9):
                    values = retained.slice(i).values
                    assert values[0] == values[-1] == 0 and np.min(values) >= 0
                    norm = float(np.linalg.norm(values))
                    assert norm <= previous_norm
                    previous_norm = norm
                reports[(nodes, steps)] = {
                    "nodes": nodes,
                    "steps": steps,
                    "evidence": evidence.id,
                    "input_digest": evidence.provenance.input_digest,
                    "resource_hash": reference.content_hash,
                    "spatial_error": float(np.max(np.abs(final.values - exact))),
                    "temporal_error": float(np.max(np.abs(final.values - semidiscrete))),
                    "endpoint_error": max(
                        abs(float(final.values[0])), abs(float(final.values[-1]))
                    ),
                    "final_l2": previous_norm,
                }
            finally:
                retained.close()
    spatial = [reports[key]["spatial_error"] for key in ((33, 512), (65, 2048), (129, 8192))]
    temporal = [reports[(33, steps)]["temporal_error"] for steps in (512, 1024, 2048)]
    spatial_orders = np.log2(np.array(spatial[:-1]) / spatial[1:])
    temporal_orders = np.log2(np.array(temporal[:-1]) / temporal[1:])
    report = {
        "runs": list(reports.values()),
        "spatial_orders": spatial_orders.tolist(),
        "temporal_orders": temporal_orders.tolist(),
    }
    path = Path(
        os.environ.get("CODE_VISUALIZER_P5_NUMERICAL_RECEIPT", tmp_path / "convergence.json")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    assert spatial[-1] <= 2e-4, report
    assert np.all((spatial_orders >= 1.9) & (spatial_orders <= 2.1)), report
    assert np.all((temporal_orders >= 1.8) & (temporal_orders <= 2.2)), report
