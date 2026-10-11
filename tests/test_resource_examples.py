"""Resource-bearing examples publish complete native source off the GUI thread."""

from hashlib import sha256
from threading import Event, get_ident

import pytest
from PySide6.QtCore import QSettings

from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.examples import ExampleBuildError, example_session
from code_visualizer.application.resource_examples import source
from code_visualizer.application.session import ProjectSession
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.persistence.serialization import normalized_project_json
from code_visualizer.ui_qt.main_window import CloseDecision, MainWindow


def test_catalog_materializes_exact_declared_source_before_session_admission(tmp_path):
    project, inputs = source("hybrid_gas")
    original = {
        p.relative_to(inputs.root): sha256(p.read_bytes()).hexdigest()
        for p in inputs.root.rglob("*")
        if p.is_file()
    }
    calibration = project.domain_workspace.models[0].node("gas:gas").properties
    reference = next(p.value for p in calibration if p.property_id.endswith(":calibration"))
    with pytest.raises(ExampleBuildError, match="project folder"):
        example_session("hybrid_gas")
    destination = tmp_path / "declared-inputs"
    session = example_session("hybrid_gas", destination=destination)
    try:
        assert session.root == destination.resolve()
        assert normalized_project_json(session.authority.snapshot()) == normalized_project_json(
            project
        )
        copied = session.kernel.resource_store
        closure = builtin_registry().resource_closure((reference,), copied)
        assert len(closure) == 17
        assert len(tuple(copied.root.glob("descriptors/*.json"))) == 17
        for ref in closure:
            assert copied.verified_path(ref).read_bytes() == inputs.verified_path(ref).read_bytes()
    finally:
        session.close()
    reopened = ProjectSession.open(destination)
    try:
        assert reopened.authority.snapshot() == project
    finally:
        reopened.close()
    assert original == {
        p.relative_to(inputs.root): sha256(p.read_bytes()).hexdigest()
        for p in inputs.root.rglob("*")
        if p.is_file()
    }


def test_failed_input_copy_does_not_publish_native_project(tmp_path, monkeypatch):
    import code_visualizer.application.resource_examples as materialization

    destination = tmp_path / "failed-inputs"

    def fail(*args):
        raise OSError("retained input copy failed")

    monkeypatch.setattr(materialization, "copy_inputs", fail)
    with pytest.raises(OSError, match="input copy failed"):
        example_session("hybrid_gas", destination=destination)
    assert not (destination / "project.json").exists()
    # The normal lease was released even on failure.
    from code_visualizer.persistence.lease import ProjectLease

    lease = ProjectLease.acquire(destination, owner_id="recovery")
    lease.release()


@pytest.mark.parametrize("replace_editor", (False, True))
def test_real_menu_load_is_off_thread_bounded_and_cannot_replace_changed_editor(
    qtbot, tmp_path, monkeypatch, replace_editor
):
    import code_visualizer.application.resource_examples as materialization

    gui, entered, released = get_ident(), Event(), Event()
    original = materialization.copy_inputs

    def held(*args):
        assert get_ident() != gui
        entered.set()
        assert released.wait(15)
        return original(*args)

    monkeypatch.setattr(materialization, "copy_inputs", held)
    service = ComputationService()
    destination = tmp_path / "menu-example"
    window = MainWindow(
        settings=QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
        computations=service,
        path_chooser=lambda: destination,
        close_decision=lambda _s: CloseDecision.DISCARD,
    )
    qtbot.addWidget(window)
    window.show()
    try:
        window._open_example("hybrid_gas")
        qtbot.waitUntil(entered.is_set, timeout=10000)
        assert window._resource_examples.busy
        if replace_editor:
            window.new_project()
            current = window.session
        else:
            current = None
        # A second click must not create a second operation or replace the destination.
        window._open_example("hybrid_gas")
        released.set()
        qtbot.waitUntil(lambda: not window._resource_examples.busy, timeout=20000)
        assert (destination / "project.json").is_file()
        if replace_editor:
            assert window.session is current and window.session.root is None
            assert "remains active" in window.statusBar().currentMessage()
            saved = ProjectSession.open(destination)
            saved.close()
        else:
            assert window.session.root == destination
            assert window.domain_dock.isVisible()
            assert window.session.kernel.resource_store.inputs is None
    finally:
        released.set()
        window.close()
        service.close()
