"""One field view, bounded work and source-pinned accepted/trial frames."""

from dataclasses import replace
from threading import Event

import pytest
from fixtures.field_worker_fixture import field_output
from test_computation_publications import publication_context as publication_context

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.computation_publications import seal_resource
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.project_factory import create_default_project
from code_visualizer.domain.values import QuantityValue, TensorDType, TensorValue
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.fields.history import FieldHistory
from code_visualizer.extensions.fields.presentation import FieldPresentationReader
from code_visualizer.extensions.fields.preview import FieldPreview
from code_visualizer.extensions.fields.records import TemporalPosition
from code_visualizer.persistence.computation_resources import resolve_computation_resource
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.ui_qt.field_history import FieldHistoryPanel, FieldViewSource


def fixture_source(publication_context):
    snapshot, _, store, _, _, _ = publication_context
    registry = builtin_registry()
    resource = seal_resource(snapshot, field_output(), store, registry).resource
    return FieldViewSource(resource, store, "run", "a" * 64, 0, False, "SUCCEEDED")


def preview(source, sequence):
    history = FieldHistory(
        source.resource,
        lambda ref: resolve_computation_resource(source.store, ref, file_backed=True),
    )
    accepted = history.slice(0)
    values = tuple(float(v) for v in accepted.values)
    frame = FieldPreview(
        history.series.interpretation,
        accepted.position,
        TemporalPosition(QuantityValue(0.01, accepted.position.time.unit), 1, 1),
        TensorValue(TensorDType.INT64, (33,), tuple(range(33))),
        TensorValue(TensorDType.FLOAT64, (33,), values),
        TensorValue(TensorDType.FLOAT64, (33,), tuple(v * 0.99 for v in values)),
    )
    history.close()
    return frame.event(source.session_id, sequence, source.input_digest, "field")


def test_history_scrub_and_preview_burst_keep_one_canonical_state(qtbot, publication_context):
    source = fixture_source(publication_context)
    authority = ProjectAuthority(create_default_project())
    kernel = ProjectKernel(authority)
    client = CodeVisualizerClient(authority, actor_id="field-view-proof")
    panel = FieldHistoryPanel()
    qtbot.addWidget(panel)
    panel.attach(kernel, client)
    panel.show()
    before = authority.snapshot()
    selected = kernel.selection.state
    try:
        panel.inspect(source)
        qtbot.waitUntil(lambda: panel.presentation is not None, timeout=5000)
        assert panel.presentation.selected.sample == 11
        panel.time_cursor.setValue(5)
        qtbot.waitUntil(lambda: panel.presentation.selected.sample == 5, timeout=5000)
        event = preview(source, 1)
        for sequence in range(1, 501):
            panel.preview(replace(event, sequence=sequence))
            assert panel.pending_tasks <= 2
        qtbot.waitUntil(lambda: panel.pending_tasks == 0, timeout=5000)
        assert panel.presentation.selected.sample == 5
        assert panel.presentation.preview.accepted.sample == 0
        assert panel._preview.sequence == 500
        assert "Provisional trial" in panel.trial_label.text()
        panel.overview.setChecked(True)
        qtbot.waitUntil(lambda: bool(panel.presentation.rgba), timeout=5000)
        assert len(panel.presentation.image_times) == 12
        assert authority.snapshot() is before and kernel.selection.state == selected
        assert panel._reader.history.cache_bytes <= 64 * 1024 * 1024
    finally:
        panel.attach(None, None)
        panel.shutdown()
        client.close()
        kernel.close()


def test_replaced_same_revision_attachment_never_installs_old_work(
    qtbot, publication_context, monkeypatch
):
    import code_visualizer.ui_qt.field_history as views

    source = fixture_source(publication_context)
    first, second = (
        ProjectKernel(ProjectAuthority(create_default_project())),
        ProjectKernel(ProjectAuthority(create_default_project())),
    )
    entered, released = Event(), Event()
    prepare = views._prepare

    def held(*args):
        entered.set()
        assert released.wait(5)
        return prepare(*args)

    monkeypatch.setattr(views, "_prepare", held)
    panel = FieldHistoryPanel()
    qtbot.addWidget(panel)
    panel.attach(first, None)
    try:
        panel.inspect(source)
        qtbot.waitUntil(entered.is_set)
        panel.attach(second, None)
        released.set()
        qtbot.waitUntil(lambda: panel.pending_tasks == 0)
        assert panel.presentation is None
        assert first.revision == second.revision
        assert first.computation_attachment.id != second.computation_attachment.id
    finally:
        released.set()
        panel.shutdown()
        first.close()
        second.close()


@pytest.mark.parametrize("mutation", ("attempt", "input", "time", "base"))
def test_reader_rejects_incoherent_preview_without_changing_selected_sample(
    publication_context, mutation
):
    source = fixture_source(publication_context)
    event = preview(source, 1)
    if mutation == "attempt":
        event = replace(event, session_id="another")
    elif mutation == "input":
        event = replace(event, input_digest="b" * 64)
    else:
        values = list(event.values)
        name = "accepted_time" if mutation == "time" else "accepted_values"
        for i, item in enumerate(values):
            if item.name == name:
                changed = (
                    QuantityValue(0.001, item.value.unit)
                    if mutation == "time"
                    else TensorValue(TensorDType.FLOAT64, (33,), (7.0,) * 33)
                )
                values[i] = replace(item, value=changed)
        event = replace(event, values=tuple(values))
    reader = FieldPresentationReader()
    try:
        with pytest.raises(ValueError):
            reader.prepare(
                source.resource,
                lambda ref: resolve_computation_resource(source.store, ref, file_backed=True),
                source.store,
                5,
                preview=event,
                session_id="run",
                input_digest="a" * 64,
            )
    finally:
        reader.close()
