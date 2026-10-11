"""Replacing an editor releases its views and preparation owners, not retained runs."""

import pytest
from shiboken6 import isValid
from test_main_window_qt import _settings

from code_visualizer.ui_qt.document import UnifiedDocumentWidget
from code_visualizer.ui_qt.main_window import CloseDecision, MainWindow


@pytest.mark.parametrize("placement", ("tabbed", "hidden", "detached"))
def test_replacing_session_disposes_retired_documents_and_their_preparation(
    qtbot, tmp_path, placement
):
    window = MainWindow(
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    for _ in range(3):
        window.action_new.trigger()
        document = window.documents.currentWidget()
        assert isinstance(document, UnifiedDocumentWidget)
        retired_session = window.session
        preparation = document._preparation._preparation
        qtbot.waitUntil(lambda p=preparation: p._thread is not None, timeout=10000)
        if placement == "hidden":
            window._close_document_tab(window.documents.indexOf(document))
            assert document in window._documents.values()
        elif placement == "detached":
            window.action_detach_document.trigger()
            assert document.diagram_id in window._detached_documents
        window.action_new.trigger()
        assert window.session is not retired_session and retired_session.closed
        assert preparation._closed, "Retirement must stop the old preparation owner immediately"
        qtbot.waitUntil(lambda d=document: not isValid(d), timeout=10000)
        qtbot.waitUntil(lambda p=preparation: not p._thread.is_alive(), timeout=10000)
        assert not window._detached_documents
        assert len(window._documents) == 1
        assert window.documents.count() == 1
        assert isinstance(window.documents.currentWidget(), UnifiedDocumentWidget)
