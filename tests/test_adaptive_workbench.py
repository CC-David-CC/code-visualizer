"""Retained cell views keep support, selection, authoring and worker work separate."""

from dataclasses import replace
from threading import Event, get_ident

import numpy as np
import pytest
from test_adaptive_artifacts import fixture

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.project_factory import create_default_project
from code_visualizer.extensions.adaptive_fields.history import AdaptiveHistory
from code_visualizer.extensions.adaptive_fields.presentation import CellPresentationReader
from code_visualizer.extensions.adaptive_fields.preview import CellPreview, ReducedCells
from code_visualizer.extensions.adaptive_fields.records import HISTORY_TYPE
from code_visualizer.extensions.adaptive_fields.units import quantity
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.ui_qt.adaptive_history import CellHistoryPanel, CellViewSource


@pytest.fixture
def retained(tmp_path):
    return fixture(tmp_path / "source")


def test_presentation_preserves_actual_partition_identity_and_exact_sample(retained):
    source, _ = retained
    reader = CellPresentationReader()
    try:
        refined = reader.prepare(source.root, source.resolve, "attempt", 3)
        coarse = reader.prepare(source.root, source.resolve, "attempt", 5)
        assert refined.epoch == 1 and coarse.epoch == 2
        assert len(refined.cells) == 17 and len(coarse.cells) == 16
        assert len({c.id for c in refined.cells} - {c.id for c in coarse.cells}) == 2
        assert sum(c.right - c.left for c in refined.cells) == 1
        for presentation in (refined, coarse):
            selected = reader.history.slice(presentation.selected.sample)
            assert tuple(c.id for c in presentation.cells) == selected.mesh.cell_ids
            np.testing.assert_array_equal(
                [c.value for c in presentation.cells], selected.values[:, 0]
            )
        assert reader.cache_bytes <= 64 * 1024 * 1024
    finally:
        reader.close()


def candidate(source):
    history = AdaptiveHistory(source.root, source.resolve)
    try:
        base, trial = history.slice(1), history.slice(2)
        return CellPreview(
            "region",
            "frame",
            "axis",
            16,
            quantity(1, "meter"),
            quantity(0.1),
            "concentration",
            quantity(1, "kilogram_per_cubic_meter"),
            ReducedCells.reduce(base.mesh, 0, 1, 1, base.values[:, 0]),
            ReducedCells.reduce(trial.mesh, 1, 2, 2, trial.values[:, 0]),
        ).event("attempt", 1, "b" * 64, ("field",))
    finally:
        history.close()


def test_preview_has_independent_support_and_never_advances_retained_time(retained):
    source, _ = retained
    prefix = source.record(
        replace(source.series, epochs=source.series.epochs[:1], chunks=source.series.chunks[:1]),
        HISTORY_TYPE,
    )
    reader = CellPresentationReader()
    try:
        value = reader.prepare(
            prefix,
            source.resolve,
            "attempt",
            preview=candidate(source),
            session_id="attempt",
            input_digest="b" * 64,
        )
        assert value.selected.sample == 1 and value.epoch == 0
        assert value.base_retained
        assert len(value.preview.base.cells) == 16 and len(value.preview.candidate.cells) == 17
        latest = reader.prepare(
            source.root,
            source.resolve,
            "attempt",
            preview=candidate(source),
            session_id="attempt",
            input_digest="b" * 64,
        )
        assert latest.selected.sample == 5 and latest.preview is None
    finally:
        reader.close()


@pytest.mark.parametrize("mutation", ("session", "input", "frame", "base", "support", "time"))
def test_preview_rejects_cross_source_or_incoherent_retained_bases(retained, mutation):
    from code_visualizer.extensions.adaptive_fields.preview import cell_preview

    source, _ = retained
    prefix = source.record(
        replace(source.series, epochs=source.series.epochs[:1], chunks=source.series.chunks[:1]),
        HISTORY_TYPE,
    )
    event = candidate(source)
    if mutation == "session":
        event = replace(event, session_id="other")
    elif mutation == "input":
        event = replace(event, input_digest="c" * 64)
    else:
        trial = cell_preview(event)
        if mutation == "frame":
            trial = replace(trial, frame_id="another-frame")
        elif mutation == "base":
            values = replace(trial.base.values, elements=(7.0,) * 16)
            trial = replace(trial, base=replace(trial.base, values=values))
        elif mutation == "support":
            trial = replace(trial, base=replace(trial.base, support_digest="c" * 64))
        else:
            trial = replace(
                trial, base=replace(trial.base, step=0), candidate=replace(trial.candidate, step=1)
            )
        event = trial.event(event.session_id, event.sequence, event.input_digest, ("field",))
    reader = CellPresentationReader()
    try:
        with pytest.raises(ValueError, match="CELL_PREVIEW"):
            reader.prepare(
                prefix,
                source.resolve,
                "attempt",
                preview=event,
                session_id="attempt",
                input_digest="b" * 64,
            )
    finally:
        reader.close()


def test_qt_coarsening_never_reassigns_a_cell_selection_by_array_position(qtbot, retained):
    source, store = retained
    project = create_default_project()
    kernel = ProjectKernel(ProjectAuthority(project))
    client = CodeVisualizerClient(kernel.authority, actor_id="cell-view")
    panel = CellHistoryPanel()
    qtbot.addWidget(panel)
    panel.attach(kernel, client)
    panel.show()
    canonical = kernel.authority.snapshot()
    try:
        panel.inspect(
            CellViewSource(source.root, store, "attempt", "b" * 64, 0, False, "SUCCEEDED")
        )
        qtbot.waitUntil(lambda: panel.presentation is not None, timeout=10000)
        panel.time_cursor.setValue(3)
        qtbot.waitUntil(lambda: panel.presentation.selected.sample == 3, timeout=10000)
        panel.table.selectRow(8)
        identity = panel.selected_cell
        assert panel.probe.isEnabled() and identity == panel.presentation.cells[8].id
        panel.time_cursor.setValue(5)
        qtbot.waitUntil(lambda: panel.presentation.selected.sample == 5, timeout=10000)
        assert panel.selected_cell == identity
        assert not panel.probe.isEnabled() and "absent" in panel.selection_label.text()
        assert not panel.table.selectionModel().selectedRows()
        panel.table.selectRow(8)
        assert panel.selected_cell != identity and panel.probe.isEnabled()
        for i in range(100):
            panel.time_cursor.setValue(i % 6)
            assert panel.pending_tasks <= 2
        qtbot.waitUntil(lambda: panel.pending_tasks == 0, timeout=10000)
        assert kernel.authority.snapshot() is canonical and kernel.revision == canonical.revision
        assert panel._reader.cache_bytes <= 64 * 1024 * 1024
    finally:
        panel.attach(None, None)
        panel.shutdown()
        client.close()
        kernel.close()


def test_same_revision_attachment_change_discards_old_work(qtbot, retained, monkeypatch):
    import code_visualizer.ui_qt.adaptive_history as views

    source, store = retained
    project = create_default_project()
    one, two = (ProjectKernel(ProjectAuthority(project)), ProjectKernel(ProjectAuthority(project)))
    entered, released = Event(), Event()
    prepare = views._prepare
    gui = get_ident()

    def held(*args):
        assert get_ident() != gui
        entered.set()
        assert released.wait(10)
        return prepare(*args)

    monkeypatch.setattr(views, "_prepare", held)
    panel = CellHistoryPanel()
    qtbot.addWidget(panel)
    panel.attach(one, None)
    try:
        panel.inspect(CellViewSource(source.root, store, "old", "b" * 64, 0, True, "SUCCEEDED"))
        qtbot.waitUntil(entered.is_set, timeout=10000)
        panel.attach(two, None)
        released.set()
        qtbot.waitUntil(lambda: panel.pending_tasks == 0, timeout=10000)
        assert panel.presentation is None
        assert one.revision == two.revision
        assert one.computation_attachment.id != two.computation_attachment.id
        assert not two.selection.state.semantic_ids
    finally:
        released.set()
        panel.shutdown()
        one.close()
        two.close()


def test_qt_probe_copies_resources_off_thread_then_uses_authority_undo(
    qtbot, retained, tmp_path, monkeypatch
):
    from test_adaptive_computation import host

    import code_visualizer.ui_qt.adaptive_history as views

    source, store = retained
    gui = get_ident()
    copied = []
    prepare = views.prepare_probe

    def off_thread(*args):
        assert get_ident() != gui
        result = prepare(*args)
        copied.append(result)
        return result

    monkeypatch.setattr(views, "prepare_probe", off_thread)
    project = create_default_project()
    with host(project, tmp_path / "target") as kernel:
        client = CodeVisualizerClient(kernel.authority, actor_id="cell-probe-ui")
        panel = CellHistoryPanel()
        qtbot.addWidget(panel)
        panel.attach(kernel, client)
        try:
            panel.inspect(
                CellViewSource(source.root, store, "attempt", "b" * 64, 0, False, "SUCCEEDED")
            )
            qtbot.waitUntil(
                lambda: panel.presentation is not None and panel.pending_tasks == 0, timeout=10000
            )
            panel.table.selectRow(8)
            panel.probe.click()
            qtbot.waitUntil(lambda: bool(copied) and panel.pending_tasks == 0, timeout=10000)
            assert client.snapshot().domain_workspace.model(copied[0].model_id) is not None
            assert isinstance(client.undo(), CommandAccepted)
            assert client.snapshot().domain_workspace.model(copied[0].model_id) is None
            assert isinstance(client.redo(), CommandAccepted)
            assert client.snapshot().domain_workspace.model(copied[0].model_id) is not None
        finally:
            panel.attach(None, None)
            panel.shutdown()
            client.close()
