"""Actual published coupling, independent retained consumers and source-pinned Qt views."""

from dataclasses import replace
from itertools import pairwise
from threading import Event
from unittest.mock import patch

import pytest
from test_diffusion_checkpoints import host
from test_electrothermal_checkpoints import last_root, request, rows
from test_electrothermal_contracts import changed

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.channel_artifacts import prepare_probe
from code_visualizer.application.computation import (
    execute_computation,
    export_computation_plan,
    run_computation_plan,
)
from code_visualizer.application.coupled_examples import electrothermal_project
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.domain.preview import PreviewEvent
from code_visualizer.domain.values import TensorDType, TensorValue
from code_visualizer.extensions.channels.presentation import ChannelPresentationReader
from code_visualizer.extensions.channels.preview import channel_preview
from code_visualizer.extensions.channels.probe import BACKEND_ID as PROBE_BACKEND
from code_visualizer.persistence.computation_resources import resolve_computation_resource
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.serialization import normalized_project_json
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.ui_qt.channel_history import ChannelHistoryPanel, ChannelViewSource


@pytest.fixture(scope="module")
def coupled_history(tmp_path_factory):
    project = electrothermal_project(duration=6, windows=6, sample_every=2, checkpoint_every=3)
    project = changed(project, "et:policy", "preview_every", 1)
    path = tmp_path_factory.mktemp("channel-workbench")
    source = path / "authored.json"
    source.write_text(normalized_project_json(project), encoding="utf-8")
    project = project_from_json(source.read_text(encoding="utf-8"))
    with host(project, path) as kernel:
        updates = []
        original = kernel.computations.publish

        def capture(job, update):
            if isinstance(update, PreviewEvent):
                updates.append(update)
            return original(job, update)

        with patch.object(kernel.computations, "publish", capture):
            result = execute_computation(kernel, request(project))
        assert result.outcome is ComputationOutcome.SUCCEEDED, result.diagnostics
        assert updates
        root = last_root(result, kernel.resource_store)
        session_id = kernel.computations.attempts()[-1].session.id
        view_source = ChannelViewSource(
            root,
            kernel.resource_store,
            session_id,
            result.provenance.input_digest,
            project.revision,
            True,
            result.outcome.value,
        )
        yield project, kernel, result, view_source, tuple(updates)


def read(source, event=None, channel=None):
    reader = ChannelPresentationReader()
    try:
        return reader.prepare(
            source.resource,
            lambda ref: resolve_computation_resource(source.store, ref),
            source.store,
            0,
            channel,
            preview=event,
            session_id=source.session_id,
            input_digest=source.input_digest,
        )
    finally:
        reader.close()


def test_actual_trials_are_distinct_from_retained_sample_positions(coupled_history):
    project, kernel, result, source, updates = coupled_history
    first, last = channel_preview(updates[0]), channel_preview(updates[-1])
    assert first.base_step == 0 and first.candidate_step == 1
    assert first.base_values != first.trial_values
    assert last.base_step == 5 and last.candidate_step == 6
    early, late = read(source, updates[0]), read(source, updates[-1])
    assert early.base_retained and not late.base_retained
    assert early.selected.sample == late.selected.sample == 0
    assert late.preview.base_time.magnitude == 5
    assert all("trial" not in artifact.id for artifact in result.artifacts)
    assert kernel.authority.snapshot() == project
    data = rows(source.store, source.resource)
    assert tuple(data[:, 0]) == (0, 2, 3, 4, 6)
    for channel in early.interpretation.channels[:2]:
        assert channel.quantity_kind.value == "point" and channel.unit.id.endswith(":kelvin")
    assert all(value.sequence < other.sequence for value, other in pairwise(updates))


@pytest.mark.parametrize(
    "mutation", ("session", "input", "definition", "meaning", "time", "base", "indices")
)
def test_preview_source_and_physical_meaning_are_checked(coupled_history, mutation):
    _, _, _, source, events = coupled_history
    event = events[0]
    if mutation == "session":
        event = replace(event, session_id="other")
    elif mutation == "input":
        event = replace(event, input_digest="f" * 64)
    else:
        trial = channel_preview(event)
        if mutation == "definition":
            trial = replace(trial, definition_digest="f" * 64)
        elif mutation == "meaning":
            trial = replace(trial, interpretation=replace(trial.interpretation, id="other"))
        elif mutation == "time":
            trial = replace(trial, base_time=replace(trial.base_time, magnitude=0.1))
        elif mutation == "base":
            trial = replace(trial, base_values=TensorValue(TensorDType.FLOAT64, (9,), (7.0,) * 9))
        else:
            trial = replace(trial, indices=TensorValue(TensorDType.INT64, (9,), (*range(8), 30)))
        event = trial.event(
            event.session_id, event.sequence, event.input_digest, event.semantic_ids[0]
        )
    with pytest.raises(ValueError, match="CHANNEL_PREVIEW"):
        read(source, event)


def test_authored_probe_consumes_only_retained_resources_and_preserves_kind(
    coupled_history, tmp_path
):
    project, producer, _, source, _ = coupled_history
    from code_visualizer.persistence.evidence_store import EvidenceStore
    from code_visualizer.persistence.resource_store import ResourceStore

    destination = ResourceStore(tmp_path / "consumer")
    meaning = read(source)
    prepared = prepare_probe(
        project,
        producer.extensions,
        source.store,
        destination,
        source.resource,
        2,
        meaning.interpretation.channels[0].id,
    )
    with host(project, tmp_path / "consumer") as kernel:
        client = CodeVisualizerClient(kernel.authority, actor_id="channel-consumer")
        try:
            assert isinstance(client.transaction(prepared.commands), CommandAccepted)
            current = client.snapshot()
            intent = ComputationRequest(
                current.id, current.revision, PROBE_BACKEND, "1", prepared.model_id
            )
            result = execute_computation(kernel, intent)
            assert result.outcome is ComputationOutcome.SUCCEEDED, result.diagnostics
            values = {o.id: o.value for o in result.observations}
            assert values["quantity_kind"] == "point"
            assert values["time"].magnitude == 3
            assert values["value"].magnitude == rows(source.store, source.resource)[2, 2]
            assert client.snapshot() == current
            plan = export_computation_plan(kernel, intent)
            empty = ResourceStore(tmp_path / "portable")
            for reference in kernel.extensions.resource_closure(
                (plan.model, *plan.request.resources), destination
            ):
                empty.import_reference(destination, reference)
        finally:
            client.close()
    replay = run_computation_plan(
        plan, producer.extensions, empty, EvidenceStore(tmp_path / "portable")
    )
    assert (
        replay.outcome is ComputationOutcome.SUCCEEDED
        and replay.observations == result.observations
    )


def test_qt_scrub_play_trials_and_source_selection_share_one_authority(qtbot, coupled_history):
    project, kernel, _, source, updates = coupled_history
    panel = ChannelHistoryPanel()
    client = CodeVisualizerClient(kernel.authority, actor_id="channel-view")
    qtbot.addWidget(panel)
    panel.attach(kernel, client)
    panel.show()
    try:
        panel.inspect(source)
        qtbot.waitUntil(lambda: panel.presentation is not None, timeout=10000)
        assert panel.presentation.selected.sample == 4
        panel.time_cursor.setValue(1)
        qtbot.waitUntil(lambda: panel.presentation.selected.sample == 1, timeout=5000)
        for sequence in range(1000, 1300):
            panel.preview(replace(updates[0], sequence=sequence))
            assert panel.pending_tasks <= 2
        qtbot.waitUntil(lambda: panel.pending_tasks == 0, timeout=10000)
        assert panel.presentation.selected.time.magnitude == 2
        assert panel.presentation.preview.base_step == 0
        assert "Provisional iteration" in panel.trial_label.text()
        assert "point" in panel.table.item(0, 2).text()
        panel.channel.setCurrentIndex(1)
        qtbot.waitUntil(
            lambda: panel.presentation.channel_id.endswith(":sink_temperature"), timeout=5000
        )
        panel.select.click()
        assert kernel.selection.state.semantic_ids == ("et:sink",)
        panel.speed.setValue(40)
        panel.play.click()
        qtbot.waitUntil(lambda: not panel._playback.isActive(), timeout=5000)
        qtbot.waitUntil(lambda: panel.pending_tasks == 0, timeout=5000)
        assert panel.presentation.selected.sample == 4
        assert kernel.authority.snapshot() == project
        assert panel._reader.history.cache_bytes <= 64 * 1024 * 1024
    finally:
        panel.attach(None, None)
        panel.shutdown()
        client.close()


def test_same_revision_editor_replacement_drops_channel_work(qtbot, coupled_history, monkeypatch):
    import code_visualizer.ui_qt.channel_history as views

    project, kernel, _, source, _ = coupled_history
    second = ProjectKernel(ProjectAuthority(project))
    entered, release = Event(), Event()
    original = views._prepare

    def held(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(views, "_prepare", held)
    panel = ChannelHistoryPanel()
    qtbot.addWidget(panel)
    panel.attach(kernel, None)
    try:
        panel.inspect(source)
        qtbot.waitUntil(entered.is_set)
        panel.attach(second, None)
        release.set()
        qtbot.waitUntil(lambda: panel.pending_tasks == 0)
        assert panel.presentation is None
        assert kernel.revision == second.revision
        assert kernel.computation_attachment.id != second.computation_attachment.id
    finally:
        release.set()
        panel.shutdown()
        second.close()
