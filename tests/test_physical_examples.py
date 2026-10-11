"""P3 authored examples persist and execute through ordinary application boundaries."""

import pytest

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.computation import execute_computation
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.physical_examples import (
    dc_divider_project,
    spring_equation_project,
)
from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.domain.transformation import derived_id
from code_visualizer.extensions.dc import TRANSFORMATION
from code_visualizer.extensions.foundations.equations import BACKEND_ID
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.serialization import normalized_project_json
from code_visualizer.persistence.store import ProjectStore


@pytest.mark.parametrize(
    ("factory", "model_id", "observation_id", "expected"),
    (
        (
            dc_divider_project,
            "dc:network",
            derived_id(TRANSFORMATION.key, "dc:middle", "potential") + ":solution",
            2.5,
        ),
        (spring_equation_project, "spring:equations", "spring:x:solution", 0.05),
    ),
)
def test_native_physical_example_round_trip_and_real_worker(
    factory, model_id, observation_id, expected, tmp_path
):
    pytest.importorskip("pint")
    pytest.importorskip("sympy")
    pytest.importorskip("numpy")
    project = factory()
    source = normalized_project_json(project)
    store = ProjectStore(tmp_path)
    store.initialize(project)
    reloaded = store.load()
    assert normalized_project_json(reloaded) == source
    kernel = ProjectKernel(
        ProjectAuthority(reloaded, store=store),
        resource_store=ResourceStore(tmp_path),
        evidence_store=EvidenceStore(tmp_path),
    )
    try:
        evidence = execute_computation(
            kernel, ComputationRequest(reloaded.id, reloaded.revision, BACKEND_ID, "1", model_id)
        )
        assert evidence.outcome is ComputationOutcome.SUCCEEDED, evidence.diagnostics
        value = next(item.value for item in evidence.observations if item.id == observation_id)
        assert value.magnitude == pytest.approx(expected)
        assert evidence.provenance.terminal_resource is not None
        assert len(evidence.artifacts) == 1
        assert normalized_project_json(kernel.authority.snapshot()) == source
    finally:
        kernel.close()
    assert EvidenceStore(tmp_path).get(evidence.id) == evidence
    assert ResourceStore(tmp_path).verified_path(evidence.artifacts[0].resource).is_file()


def test_declared_unit_picker_is_an_unaccepted_buffer_until_authority_edit(qtbot):
    from code_visualizer.application.domain_workbench import catalog_unit_choices
    from code_visualizer.extensions.dc import identity
    from code_visualizer.sdk import CodeVisualizerClient
    from code_visualizer.ui_qt.features.domain_workbench.value_editors import QuantityValueEditor
    from code_visualizer.ui_qt.features.domain_workbench.widget import DomainWorkbenchWidget

    project = dc_divider_project()
    authority = ProjectAuthority(project)
    kernel = ProjectKernel(authority)
    client = CodeVisualizerClient(authority, actor_id="physical-author")
    widget = DomainWorkbenchWidget()
    qtbot.addWidget(widget)
    try:
        widget.attach(kernel, client)
        widget.reveal("dc:upper")
        control = widget._properties[identity("Resistor", "resistance")].control
        assert isinstance(control, QuantityValueEditor)
        wanted = next(
            unit for _label, unit in catalog_unit_choices(project) if unit.id.endswith(":kiloohm")
        )
        index = next(
            index
            for index in range(control.unit_choice.count())
            if control.unit_choice.itemData(index) == wanted
        )
        control.unit_choice.setCurrentIndex(index)
        control.real.setText("1")
        assert authority.snapshot() == project
        widget.apply_fields()
        assert kernel.revision == 1
        value = (
            authority.snapshot()
            .domain_workspace.node("dc:upper")
            .property(identity("Resistor", "resistance"))
        )
        assert value.unit == wanted and value.magnitude == 1
        client.undo()
        assert authority.snapshot().domain_workspace == project.domain_workspace
        client.redo()
        assert (
            authority.snapshot()
            .domain_workspace.node("dc:upper")
            .property(identity("Resistor", "resistance"))
            == value
        )
    finally:
        widget.attach(None)
        kernel.close()
