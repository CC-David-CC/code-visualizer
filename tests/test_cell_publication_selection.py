"""A final metric/statistical resource must not hide the same attempt's cell history."""

import pytest
from fixtures.gas_project import short_project
from test_hybrid_gas_computation import host, request, resources
from test_hybrid_gas_particle import WINDOWS

from code_visualizer.application.cell_presentations import CellPresentationReader
from code_visualizer.application.computation import execute_computation
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.extensions.hybrid_gas.records import CHECKPOINT_TYPE, HISTORY_TYPE
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.ui_qt.adaptive_history import CellHistoryPanel


@WINDOWS
def test_completed_native_attempt_shows_latest_history_after_statistics_and_rejects_corruption(
    qtbot, tmp_path
):
    project = short_project()
    with host(project, tmp_path / "producer") as kernel:
        client = CodeVisualizerClient(kernel.authority, actor_id="cell-publication-proof")
        panel = CellHistoryPanel()
        qtbot.addWidget(panel)
        panel.attach(kernel, client)
        failures = []
        panel.failed.connect(failures.append)
        try:
            evidence = execute_computation(kernel, request(project))
            assert evidence.outcome is ComputationOutcome.SUCCEEDED, evidence.diagnostics
            attempt = kernel.computations.attempts()[-1]
            final = kernel.computations.publication(attempt.publications[-1])
            assert final.artifact.id == "replica-statistics"
            expected = resources(evidence, kernel.resource_store, HISTORY_TYPE)[-1]
            panel.observe_attempt(attempt)
            qtbot.waitUntil(lambda: panel.pending_tasks == 0, timeout=10000)
            assert not failures, failures
            assert panel.presentation is not None
            assert panel.presentation.resource == expected
            assert panel.presentation.selected.sample == 2
            assert panel.presentation.sample_count == 3
            view = CellPresentationReader()
            try:
                # Direct inspection stays strict; the explicit attempt receipt
                # list is what authorizes selecting another output for this view.
                with pytest.raises(ValueError, match="Select a retained cell history"):
                    view.prepare(
                        final.artifact.resource, kernel.resource_store, kernel.extensions, "direct"
                    )
                corrupt = kernel.resource_store.put(
                    b"{}", "application/json", logical_type=CHECKPOINT_TYPE
                ).reference
                with pytest.raises(ValueError):
                    view.prepare(
                        corrupt,
                        kernel.resource_store,
                        kernel.extensions,
                        "corrupt",
                        alternatives=(expected,),
                    )
            finally:
                view.close()
        finally:
            panel.attach(None, None)
            panel.shutdown()
            client.close()
