"""The artifact panel samples background work and never aliases historical selection."""

from dataclasses import replace
from threading import Event, current_thread, main_thread

import pytest
from test_cad_resources import header
from test_python_artifact_bindings import host

from code_visualizer.application.cad_examples import spring_cad_project
from code_visualizer.application.examples import example_session
from code_visualizer.domain.evidence import (
    ComputationEvidence,
    ComputationOutcome,
    EvidenceArtifact,
    EvidenceProvenance,
)
from code_visualizer.domain.transformation import OriginMap
from code_visualizer.domain.values import ResourceReference
from code_visualizer.extensions.cad.native import encode_mesh
from code_visualizer.extensions.cad.resources import MESH, TriangleMesh
from code_visualizer.persistence.evidence import evidence_content_hash
from code_visualizer.persistence.serialization import project_to_data
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.ui_qt.cad_artifacts import CadArtifactPanel


def mesh_evidence(project, store):
    meta = replace(
        header(),
        logical_type=MESH,
        serializer="code_visualizer.cad.indexed_triangles",
        parent=ResourceReference("brep", "b" * 64),
        angular_tolerance=0.1,
        vertex_count=3,
        triangle_count=1,
    )
    mesh = TriangleMesh(
        meta, ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), ((0, 1, 2),), (42,)
    )
    resource = store.put(encode_mesh(mesh), "application/vnd.codevisualizer.cad", logical_type=MESH)
    evidence = ComputationEvidence(
        "pending",
        EvidenceProvenance(
            project.id,
            project.revision,
            None,
            "code_visualizer.cad.tessellation",
            "1",
            "a" * 64,
            (),
            None,
            (),
            (),
            OriginMap(project.id, project.revision),
        ),
        ComputationOutcome.SUCCEEDED,
        artifacts=(EvidenceArtifact("mesh", resource.reference, ("cad:box",)),),
    )
    return replace(evidence, id="evidence:" + evidence_content_hash(evidence))


def test_native_example_keeps_its_python_recipe():
    session = example_session("spring_cad")
    try:
        assert session.authority.snapshot().program_model.function("cad:recipe") is not None
    finally:
        session.close()


@pytest.mark.parametrize("current_source", [True, False])
def test_mesh_view_and_face_pick_share_only_current_semantic_selection(
    qtbot, tmp_path, current_source
):
    project = spring_cad_project()
    with host(project, tmp_path) as (_, kernel):
        client = CodeVisualizerClient(kernel.authority, actor_id="viewer")
        before = project_to_data(project)
        panel = CadArtifactPanel()
        qtbot.addWidget(panel)
        panel.attach(kernel, client)
        evidence = mesh_evidence(project, kernel.resource_store)
        panel.inspect(evidence, "mesh", kernel.resource_store, current_source=current_source)
        qtbot.waitUntil(lambda: panel._future is None, timeout=15000)
        assert len(panel.scene.items()) == 1, panel.status.text()
        picks = []
        panel.faceSelected.connect(picks.append)
        panel.scene.items()[0].setSelected(True)
        assert picks[-1].face_id == 42
        assert picks[-1].geometry.content_hash == "b" * 64
        assert kernel.selection.state.semantic_ids == (("cad:box",) if current_source else ())
        panel.orientation.setCurrentText("top")
        qtbot.waitUntil(lambda: panel._future is None, timeout=15000)
        assert project_to_data(client.snapshot()) == before


def test_background_inspection_cannot_publish_into_replacement_editor(qtbot, tmp_path, monkeypatch):
    from code_visualizer.ui_qt import cad_artifacts

    entered, release = Event(), Event()
    original = cad_artifacts.inspect_artifact

    def blocked(*args):
        assert current_thread() is not main_thread()
        entered.set()
        assert release.wait(15)
        return original(*args)

    monkeypatch.setattr(cad_artifacts, "inspect_artifact", blocked)
    project = spring_cad_project()
    with host(project, tmp_path) as (_, first), host(project, tmp_path) as (_, second):
        panel = CadArtifactPanel()
        qtbot.addWidget(panel)
        panel.attach(first, CodeVisualizerClient(first.authority, actor_id="first"))
        evidence = mesh_evidence(project, first.resource_store)
        panel.inspect(evidence, "mesh", first.resource_store, current_source=True)
        try:
            qtbot.waitUntil(entered.is_set, timeout=15000)
            panel.attach(second, CodeVisualizerClient(second.authority, actor_id="second"))
        finally:
            release.set()
        qtbot.waitUntil(lambda: panel._future is None, timeout=15000)
        assert not panel.scene.items()
        assert not second.selection.state.semantic_ids


def test_click_picks_the_visible_face_and_preserves_its_resource_identity(qtbot, tmp_path):
    from PySide6.QtCore import Qt
    from test_cad_presentation import crossing_mesh

    project = spring_cad_project()
    with host(project, tmp_path) as (_, kernel):
        panel = CadArtifactPanel()
        qtbot.addWidget(panel)
        panel.attach(kernel, CodeVisualizerClient(kernel.authority, actor_id="viewer"))
        panel.resize(900, 800)
        panel.show()
        evidence = mesh_evidence(project, kernel.resource_store)
        mesh = crossing_mesh()
        resource = kernel.resource_store.put(
            encode_mesh(mesh), "application/vnd.codevisualizer.cad", logical_type=MESH
        )
        evidence = replace(
            evidence, artifacts=(replace(evidence.artifacts[0], resource=resource.reference),)
        )
        evidence = replace(evidence, id="evidence:" + evidence_content_hash(evidence))
        panel.orientation.setCurrentText("top")
        panel.inspect(evidence, "mesh", kernel.resource_store, current_source=True)
        qtbot.waitUntil(lambda: panel._future is None, timeout=15000)
        qtbot.wait(50)
        picks = []
        panel.faceSelected.connect(picks.append)
        for x, expected in ((80, 2**32 - 1), (600, 17)):
            point = panel.view.mapFromScene(x, 80)
            qtbot.mouseClick(panel.view.viewport(), Qt.MouseButton.LeftButton, pos=point)
            assert picks[-1].face_id == expected
            assert picks[-1].geometry == mesh.header.parent
        assert kernel.selection.state.semantic_ids == ("cad:box",)
