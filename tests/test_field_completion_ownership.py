"""Completed field work releases its future and obsolete GUI context immediately."""

import gc
from concurrent.futures import Future
from weakref import ref

import pytest
from test_computation_publications import publication_context as publication_context
from test_field_history_qt import fixture_source

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.project_factory import create_default_project
from code_visualizer.ui_qt.field_history import FieldHistoryPanel


@pytest.mark.parametrize("error_type", (None, InterruptedError, ValueError))
@pytest.mark.parametrize("obsolete", (False, True))
def test_field_completion_releases_future_without_collecting_gui_frames(
    qtbot, publication_context, monkeypatch, error_type, obsolete
):
    import code_visualizer.ui_qt.field_history as views

    source = fixture_source(publication_context)
    kernel = ProjectKernel(ProjectAuthority(create_default_project()))
    panel = FieldHistoryPanel()
    qtbot.addWidget(panel)
    panel.attach(kernel, None)
    prepare = views._prepare
    failures, loaded = [], []
    panel.failed.connect(failures.append)
    panel.loaded.connect(lambda: loaded.append(True))

    def complete(*args):
        if error_type is not None:
            raise error_type("Completed field request")
        return prepare(*args)

    monkeypatch.setattr(views, "_prepare", complete)
    try:
        # Establish a clean ownership baseline; do not collect after the handoff.
        gc.collect()
        panel.inspect(source)
        future = panel._future
        assert future is not None
        reference = ref(future)
        panel._timer.stop()
        qtbot.waitUntil(future.done, timeout=5000)
        if obsolete:
            panel.attach(None, None)
        panel._poll()
        del future
        assert failures == (
            ["Completed field request"] if error_type is ValueError and not obsolete else []
        )
        assert loaded == ([True] if error_type is None and not obsolete else [])
        assert panel.pending_tasks == 0
        assert reference() is None, "GUI completion retained Future -> traceback -> GUI frame"
    finally:
        panel.attach(None, None)
        panel.shutdown()
        kernel.close()


def test_unexpected_field_completion_error_remains_visible(qtbot):
    panel = FieldHistoryPanel()
    qtbot.addWidget(panel)
    future = Future()
    future.set_exception(TypeError("Unexpected implementation error"))
    panel._future = future
    try:
        with pytest.raises(TypeError, match="Unexpected implementation error"):
            panel._poll()
        assert panel._future is None
    finally:
        panel.shutdown()
