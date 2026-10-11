"""Actual retained native output is viewable and reusable without its producer."""

from dataclasses import replace
from threading import get_ident

import numpy as np
import pytest
from fixtures.gas_project import short_project
from test_hybrid_gas_computation import host, reader, request, resources
from test_hybrid_gas_particle import WINDOWS

from code_visualizer.application.cell_presentations import CellPresentationReader, prepare_probe
from code_visualizer.application.computation import execute_computation
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.project_factory import create_default_project
from code_visualizer.domain.computation import ComputationParameter, ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.domain.preview import PreviewEvent
from code_visualizer.domain.values import TensorDType, TensorValue
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.gas_observation.domain import BACKEND_ID
from code_visualizer.extensions.gas_observation.presentation import GasPresentationReader
from code_visualizer.extensions.gas_observation.reader import cell_ids, probe
from code_visualizer.extensions.hybrid_gas.preview import PREVIEW_TYPE
from code_visualizer.extensions.hybrid_gas.records import CHECKPOINT_TYPE, CODEC, HISTORY_TYPE
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.serialization import normalized_project_json
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.ui_qt.adaptive_history import CellHistoryPanel, CellViewSource

pytestmark = WINDOWS


@pytest.fixture(scope="module")
def retained_gas(tmp_path_factory):
    root = tmp_path_factory.mktemp("retained-native-gas")
    project = short_project()
    with host(project, root) as kernel:
        result = execute_computation(kernel, request(project))
        assert result.outcome is ComputationOutcome.SUCCEEDED, result.diagnostics
        history = resources(result, kernel.resource_store, HISTORY_TYPE)[-1]
        checkpoint = resources(result, kernel.resource_store, CHECKPOINT_TYPE)[-1]
    return ResourceStore(root), history, checkpoint


def test_shared_reader_preserves_wall_geometry_units_and_actual_values(retained_gas):
    store, root, checkpoint = retained_gas
    history = reader(root, store)
    view = CellPresentationReader()
    try:
        for sample in (0, 2, 1):
            for column, field in enumerate(history.interpretation.field_ids):
                shown = view.prepare(
                    checkpoint, store, builtin_registry(), "retained", sample, field
                )
                assert shown.resource == root and shown.selected.sample == sample
                assert shown.support.interpretation == "wall_bounded_uniform_cell_average"
                assert shown.support.frame_id == history.interpretation.frame_id
                assert tuple(c.id for c in shown.cells) == cell_ids(history)
                assert shown.components[column].unit == history.interpretation.units[column]
                np.testing.assert_array_equal(
                    [c.value for c in shown.cells], history.gas_slice(sample).conserved[:, column]
                )
                assert sum(c.right - c.left for c in shown.cells) == pytest.approx(0.002)
        assert view.cache_bytes <= 64 * 1024 * 1024
    finally:
        history.close()
        view.close()


def candidate(history):
    support, saved = history.interpretation, history.gas_slice(1)
    indices = tuple(range(0, support.cells, 2))
    numbers = tuple(float(v) for v in saved.conserved[list(indices)].ravel())
    values = {
        "source": history.series.source_digest,
        "region": support.region_id,
        "slab": support.slab_id,
        "policy": support.policy_id,
        "frame": support.frame_id,
        "axis": support.axis_id,
        "cells": support.cells,
        "height": support.height,
        "quantum": support.quantum,
        "indices": TensorValue(TensorDType.INT64, (len(indices),), indices),
        "status": "numerical_candidate_pending_publication",
    }
    for name, tick in (("base", 500), ("candidate", 502)):
        values.update(
            {
                name + "_tick": tick,
                name + "_windows": tick // 2,
                name + "_particle": True,
                name + "_values": TensorValue(TensorDType.FLOAT64, (len(indices), 5), numbers),
            }
        )
    return PreviewEvent(
        "attempt",
        1,
        "b" * 64,
        PREVIEW_TYPE,
        (support.region_id,),
        tuple(ComputationParameter(k, v) for k, v in values.items()),
    )


@pytest.mark.parametrize("mutation", (None, "session", "source", "frame", "base"))
def test_provisional_cells_keep_source_and_retained_base_identity(retained_gas, mutation):
    store, root, _ = retained_gas
    history = reader(root, store)
    view = GasPresentationReader()
    try:
        prefix = replace(history.series, chunks=history.series.chunks[:2])
        # The short native run publishes one independently sealed sample per chunk.
        assert prefix.last.sample == 1
        partial = store.put(
            CODEC.encode(prefix), "application/json", logical_type=HISTORY_TYPE
        ).reference
        event = candidate(history)
        if mutation == "session":
            event = replace(event, session_id="another")
        elif mutation:
            name = "base_values" if mutation == "base" else mutation
            value = (
                TensorValue(TensorDType.FLOAT64, (32, 5), (7.0,) * 160)
                if mutation == "base"
                else "c" * 64
            )
            event = replace(
                event,
                values=tuple(
                    replace(p, value=value) if p.name == name else p for p in event.values
                ),
            )

        def prepare():
            return view.prepare(
                partial,
                history.resolve,
                "attempt",
                preview=event,
                session_id="attempt",
                input_digest="b" * 64,
            )

        if mutation:
            with pytest.raises(ValueError, match="GAS_PREVIEW"):
                prepare()
        else:
            shown = prepare()
            assert shown.selected.sample == 1 and shown.tick == 500 and shown.base_retained
            assert len(shown.preview.base.cells) == len(shown.preview.candidate.cells) == 32
            assert all(c.id in cell_ids(history) for c in shown.preview.candidate.cells)
            current = view.prepare(
                root,
                history.resolve,
                "attempt",
                preview=event,
                session_id="attempt",
                input_digest="b" * 64,
            )
            assert current.tick == 1000 and current.preview is None
    finally:
        history.close()
        view.close()


def test_fresh_consumer_authority_undo_reload_and_worker_need_only_retained_closure(
    retained_gas, tmp_path
):
    store, root, _ = retained_gas
    target, project = ResourceStore(tmp_path / "consumer"), create_default_project()
    source = reader(root, store)
    try:
        cell, component = cell_ids(source)[20], source.interpretation.field_ids[1]
        selected = source.gas_slice(2)
        expected = probe(
            source, 2, cell, component, source.interpretation.frame_id, selected.position.time
        )
        prepared = prepare_probe(
            project, builtin_registry(), store, target, root, 2, 0, cell, component
        )
        with pytest.raises(ValueError, match="GAS_PROBE_MEANING"):
            probe(
                source, 2, "20", component, source.interpretation.frame_id, selected.position.time
            )
    finally:
        source.close()
    with host(project, tmp_path / "consumer", inputs=False) as kernel:
        client = CodeVisualizerClient(kernel.authority, actor_id="gas-query")
        try:
            assert isinstance(
                client.transaction(prepared.commands, expected_revision=prepared.revision),
                CommandAccepted,
            )
            assert isinstance(client.undo(), CommandAccepted)
            assert client.snapshot().domain_workspace.model(prepared.model_id) is None
            assert isinstance(client.redo(), CommandAccepted)
            restored = project_from_json(normalized_project_json(client.snapshot()))
        finally:
            client.close()
    # No producing project, calibrated input fallback or retained native process is attached.
    with host(restored, tmp_path / "consumer", inputs=False) as fresh:
        evidence = execute_computation(
            fresh,
            ComputationRequest(restored.id, restored.revision, BACKEND_ID, "1", prepared.model_id),
        )
        assert evidence.outcome is ComputationOutcome.SUCCEEDED, evidence.diagnostics
        assert evidence.observations[0].value == expected
        assert (
            evidence.observations[0].semantic_ids
            == restored.domain_workspace.model(prepared.model_id).roots
        )


def test_shared_qt_view_scrubs_without_edits_and_authors_query_off_thread(
    qtbot, retained_gas, tmp_path, monkeypatch
):
    import code_visualizer.ui_qt.adaptive_history as views

    store, root, _ = retained_gas
    original, gui, commands = views.prepare_probe, get_ident(), []

    def off_thread(*args):
        assert get_ident() != gui
        prepared = original(*args)
        commands.append(prepared)
        return prepared

    monkeypatch.setattr(views, "prepare_probe", off_thread)
    with host(create_default_project(), tmp_path / "ui", inputs=False) as kernel:
        client = CodeVisualizerClient(kernel.authority, actor_id="gas-cell-ui")
        panel = CellHistoryPanel()
        qtbot.addWidget(panel)
        panel.attach(kernel, client)
        before = client.snapshot()
        try:
            panel.inspect(
                CellViewSource(root, store, "finished-native", "b" * 64, 0, False, "SUCCEEDED")
            )
            qtbot.waitUntil(
                lambda: panel.presentation is not None and not panel.pending_tasks, timeout=10000
            )
            for sample in (0, 2, 1):
                panel.time_cursor.setValue(sample)
                qtbot.waitUntil(
                    lambda sample=sample: (
                        panel.presentation.selected.sample == sample and not panel.pending_tasks
                    ),
                    timeout=10000,
                )
            assert client.snapshot() is before
            assert "wall_bounded" in panel.accepted_label.text()
            panel.table.selectRow(20)
            panel.probe.click()
            qtbot.waitUntil(lambda: bool(commands) and not panel.pending_tasks, timeout=10000)
            assert client.snapshot().domain_workspace.model(commands[0].model_id) is not None
            assert isinstance(client.undo(), CommandAccepted)
            assert client.snapshot().domain_workspace.model(commands[0].model_id) is None
            assert isinstance(client.redo(), CommandAccepted)
        finally:
            panel.attach(None, None)
            panel.shutdown()
            client.close()
