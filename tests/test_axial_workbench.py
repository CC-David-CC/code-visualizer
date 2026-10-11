"""Actual CAD-to-authoring UI and independent derived-result display."""

from dataclasses import replace
from threading import get_ident

import pytest
from test_diffusion_checkpoints import host

from code_visualizer.application.axial_examples import axial_cad_project, recipe_request
from code_visualizer.application.computation import execute_computation
from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.domain.project import Project
from code_visualizer.extensions.axial.domain import BACKEND_ID
from code_visualizer.extensions.axial.presentation import prepare_result
from code_visualizer.extensions.axial.records import CODEC, RESULT_TYPE, AxialResult
from code_visualizer.extensions.cad.resources import BREP
from code_visualizer.extensions.fields.arrays import array_resource, read_array
from code_visualizer.persistence.computation_resources import resolve_computation_resource
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.ui_qt.cad_artifacts import CadArtifactPanel


@pytest.fixture(scope="module")
def producer(tmp_path_factory):
    path = tmp_path_factory.mktemp("axial-ui-producer")
    project = axial_cad_project()
    with host(project, path) as kernel:
        result = execute_computation(kernel, recipe_request(project))
        assert result.outcome is ComputationOutcome.SUCCEEDED, result.diagnostics
        artifact = next(
            a
            for a in result.artifacts
            if kernel.resource_store.describe(a.resource).logical_type == BREP
        )
    return ResourceStore(path), result, artifact


def test_first_cad_producer_uses_the_existing_freeze_request(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    project = axial_cad_project()
    with host(project, tmp_path) as kernel:
        client = CodeVisualizerClient(kernel.authority, actor_id="cad-producer-ui")
        panel = CadArtifactPanel()
        qtbot.addWidget(panel)
        panel.attach(kernel, client)
        requests = []
        panel.freezeRequested.connect(requests.append)
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **kw: ("bar", True))
        try:
            assert panel.produce_button.isEnabled()
            panel.produce_button.click()
            assert len(requests) == 1
            request = requests[0]
            assert (request.backend_id, request.backend_version) == ("code_visualizer.python", "2")
            assert request.inputs == () and request.outputs[0].name == "bar"
            assert request.outputs[0].logical_type == BREP
            assert kernel.authority.snapshot() == project and kernel.computations.attempts() == ()
        finally:
            panel.attach(None, None)
            panel._executor.shutdown(wait=True)
            client.close()


def test_create_axial_analysis_in_ui_then_execute_and_inspect(
    qtbot, tmp_path, monkeypatch, producer
):
    from PySide6.QtWidgets import QInputDialog

    source, evidence, artifact = producer
    authored = Project("independent:axial", "Independent structural consumer", ())
    with host(authored, tmp_path) as kernel:
        client = CodeVisualizerClient(kernel.authority, actor_id="axial-ui")
        panel = CadArtifactPanel()
        qtbot.addWidget(panel)
        panel.attach(kernel, client)
        panel.show()
        created, worker_threads = [], []
        panel.modelCreated.connect(created.append)
        main_thread = get_ident()
        original = kernel.resource_store.import_reference

        def transfer(*args, **kwargs):
            worker_threads.append(get_ident())
            return original(*args, **kwargs)

        monkeypatch.setattr(kernel.resource_store, "import_reference", transfer)
        values = iter((200, 1000))
        monkeypatch.setattr(QInputDialog, "getDouble", lambda *a, **kw: (next(values), True))
        monkeypatch.setattr(QInputDialog, "getInt", lambda *a, **kw: (9, True))
        monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **kw: ("x", True))
        try:
            panel.inspect(evidence, artifact.id, source)
            qtbot.waitUntil(lambda: panel._inspection is not None, timeout=10000)
            assert panel.axial_button.isEnabled()
            panel.axial_button.click()
            qtbot.waitUntil(lambda: panel._future is None, timeout=10000)
            assert len(created) == 1, panel.status.text()
            assert worker_threads and all(t != main_thread for t in worker_threads)
            current = client.snapshot()
            model = current.domain_workspace.model(created[0])
            assert model is not None and len(model.nodes) == 5
            assert len(current.program_model.functions) == 0
            result = execute_computation(
                kernel, ComputationRequest(current.id, current.revision, BACKEND_ID, "1", model.id)
            )
            assert result.outcome is ComputationOutcome.SUCCEEDED, result.diagnostics
            assert client.snapshot() == current
            output = result.artifacts[0]
            panel.inspect(result, output.id, kernel.resource_store, current_source=True)
            qtbot.waitUntil(
                lambda: panel._inspection is not None and panel._inspection.axial is not None,
                timeout=10000,
            )
            view = panel._inspection.axial
            assert view.displacement[-1] == pytest.approx(5e-6, rel=1e-8)
            assert "Derived equilibrium only" in panel.status.text()
            assert panel.scene.items() and not panel.axial_button.isEnabled()
            # Undo/redo affects the authored analysis transaction, never its evidence.
            client.undo()
            assert client.snapshot().domain_workspace.model(model.id) is None
            client.redo()
            assert client.snapshot().domain_workspace.model(model.id) == model
            for ref in kernel.extensions.resource_closure(
                (output.resource,), kernel.resource_store
            ):
                kernel.resource_store.verified_path(ref)
        finally:
            panel.attach(None, None)
            panel._executor.shutdown(wait=True)
            client.close()


def test_derived_view_rejects_wrong_units_and_false_equilibrium(tmp_path, producer):
    import numpy as np

    from code_visualizer.application.axial_artifacts import prepare_axial
    from code_visualizer.application.messages import CommandAccepted
    from code_visualizer.extensions.axial.domain import quantity

    source, evidence, artifact = producer
    project = Project("axial:inspect", "Inspect derived data", ())
    with host(project, tmp_path) as kernel:
        client = CodeVisualizerClient(kernel.authority, actor_id="axial-inspect")
        edit = prepare_axial(
            project,
            kernel.extensions,
            evidence,
            artifact.id,
            source,
            kernel.resource_store,
            young_modulus=2e11,
            force=1000,
            nodes=9,
            axis="x",
        )
        assert isinstance(client.transaction(edit.commands), CommandAccepted)
        result = execute_computation(kernel, edit.request(client.snapshot()))
        assert result.outcome is ComputationOutcome.SUCCEEDED, result.diagnostics
        store = kernel.resource_store
        original = CODEC.decode(store.read(result.artifacts[0].resource), AxialResult)
        for wrong_unit in (False, True):
            data = read_array(
                resolve_computation_resource(store, original.displacement), (9,)
            ).copy()
            if not wrong_unit:
                data[4] += 1e-5
            output = array_resource(
                "altered",
                np.asarray(data),
                unit=quantity(1, "second" if wrong_unit else "meter").unit,
            )
            child = store.put(
                output.data,
                output.media_type,
                tensor=output.tensor,
                logical_type=output.logical_type,
            )
            corrupt = store.put(
                CODEC.encode(replace(original, displacement=child.reference)),
                "application/json",
                logical_type=RESULT_TYPE,
            ).reference
            with pytest.raises(
                ValueError, match="AXIAL_RESULT_UNIT" if wrong_unit else "AXIAL_RESULT_BALANCE"
            ):
                prepare_result(corrupt, lambda ref: resolve_computation_resource(store, ref))
        client.close()
