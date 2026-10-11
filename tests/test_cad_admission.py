"""Resource/promotion failures are explicit and never replay the producing program."""

from dataclasses import replace
from importlib.metadata import PackageNotFoundError

import pytest
from test_cad_resources import header

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.cad_artifacts import prepare_consumer
from code_visualizer.application.cad_examples import spring_cad_project
from code_visualizer.application.computation import execute_computation
from code_visualizer.application.messages import CommandAccepted, CommandRejected
from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.evidence import (
    ComputationEvidence,
    ComputationOutcome,
    EvidenceArtifact,
    EvidenceProvenance,
)
from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.transformation import OriginMap
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.cad.native import encode_solid
from code_visualizer.extensions.cad.resources import BREP
from code_visualizer.persistence.evidence import evidence_content_hash
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.store import ProjectStore
from code_visualizer.sdk import CodeVisualizerClient


@pytest.fixture
def offered_geometry(tmp_path):
    from build123d import Box

    project = spring_cad_project()
    resources = ResourceStore(tmp_path / "resources")
    descriptor = resources.put(
        encode_solid(Box(50, 20, 10), header()),
        "application/vnd.codevisualizer.cad",
        logical_type=BREP,
    )
    evidence = ComputationEvidence(
        "pending",
        EvidenceProvenance(
            project.id,
            project.revision,
            None,
            "code_visualizer.python",
            "2",
            "b" * 64,
            (),
            None,
            (),
            (),
            OriginMap(project.id, project.revision),
        ),
        ComputationOutcome.SUCCEEDED,
        artifacts=(EvidenceArtifact("solid", descriptor.reference, ("cad:box",)),),
    )
    evidence = replace(evidence, id="evidence:" + evidence_content_hash(evidence))
    return project, resources, evidence


@pytest.mark.parametrize(
    "failure", ["missing", "corrupt", "dependency", "failed", "cancelled", "forged"]
)
def test_promotion_checks_selected_evidence_and_resource_before_mutation(
    offered_geometry, monkeypatch, failure
):
    from code_visualizer.extensions.cad import native

    project, resources, evidence = offered_geometry
    reference = evidence.artifacts[0].resource
    if failure in ("missing", "corrupt"):
        path = resources.verified_path(reference)
        if failure == "missing":
            path.unlink()
        else:
            path.write_bytes(b"not the sealed bytes")
    if failure == "dependency":

        def unavailable(_name):
            raise PackageNotFoundError("missing native distribution")

        monkeypatch.setattr(native, "version", unavailable)
    if failure in ("failed", "cancelled"):
        evidence = replace(evidence, outcome=ComputationOutcome(failure))
        evidence = replace(evidence, id="evidence:" + evidence_content_hash(evidence))
    if failure == "forged":
        evidence = replace(evidence, id="evidence:" + "a" * 64)
    with pytest.raises((ValueError, OSError)):
        prepare_consumer(
            project, builtin_registry(), evidence, "solid", resources, resources, "GeometryInput"
        )


def test_promotion_uses_inert_metadata_and_journal_recovers_ownership(
    offered_geometry, tmp_path, monkeypatch
):
    from code_visualizer.extensions.cad import native

    project, resources, evidence = offered_geometry

    def no_native(*args, **kwargs):
        raise AssertionError("Authoring admission must not interpret native topology")

    monkeypatch.setattr(native, "decode_solid", no_native)
    edit = prepare_consumer(
        project,
        builtin_registry(),
        evidence,
        "solid",
        resources,
        resources,
        "GeometryInput",
        model_id="new-geometry",
        node_id="imported-solid",
    )
    store = ProjectStore(tmp_path / "native")
    store.initialize(project)
    authority = ProjectAuthority(project, store=store)
    client = CodeVisualizerClient(authority, actor_id="author")
    assert isinstance(client.transaction(edit.commands, expected_revision=99), CommandRejected)
    assert client.snapshot() == project
    assert isinstance(client.transaction(edit.commands, expected_revision=0), CommandAccepted)
    assert client.snapshot().program_model == project.program_model
    recovered = ProjectAuthority(store.recover(), store=store)
    # History is intentionally scoped to the author across session replacement.
    other = CodeVisualizerClient(recovered, actor_id="author")
    assert other.snapshot().domain_workspace.model(edit.model_id) is not None
    assert isinstance(other.undo(), CommandAccepted)
    assert other.snapshot().domain_workspace.model(edit.model_id) is None
    assert isinstance(other.redo(), CommandAccepted)
    assert other.snapshot().domain_workspace.node(edit.node_id) is not None
    assert isinstance(other.transaction(edit.commands), CommandRejected)
    assert resources.verified_path(evidence.artifacts[0].resource).is_file()


@pytest.mark.parametrize("failure", ["wrong-type", "missing", "corrupt", "native-malformed"])
def test_isolated_cad_consumer_reports_bad_inputs_without_replaying_python(tmp_path, failure):
    from io import BytesIO

    from test_python_artifact_bindings import host

    from code_visualizer.extensions.cad.domain import consumer_model
    from code_visualizer.extensions.cad.native import implementation_version
    from code_visualizer.extensions.cad.resources import write_envelope

    project = spring_cad_project()
    resources = ResourceStore(tmp_path)
    stream = BytesIO()
    write_envelope(
        stream,
        replace(header(), serializer_version=implementation_version()),
        b"DBRep_DrawableShape\ninvalid native topology",
    )
    descriptor = resources.put(
        stream.getvalue(),
        "application/vnd.codevisualizer.cad",
        logical_type=(
            ResourceLogicalTypeReference("code_visualizer.python.byte_stream", "1")
            if failure == "wrong-type"
            else BREP
        ),
    )
    if failure == "missing":
        resources.verified_path(descriptor.reference).unlink()
    if failure == "corrupt":
        resources.verified_path(descriptor.reference).write_bytes(b"changed bytes")
    model = consumer_model("consumer", "measure", "Measurement", descriptor.reference)
    project = replace(
        project,
        domain_workspace=replace(
            project.domain_workspace, models=(*project.domain_workspace.models, model)
        ),
    )
    with host(project, tmp_path) as (service, kernel):
        try:
            result = execute_computation(
                kernel,
                ComputationRequest(
                    project.id, project.revision, "code_visualizer.cad.measurement", "1", model.id
                ),
            )
        except ValueError as exc:
            assert failure in ("missing", "corrupt")
            assert "resource" in str(exc).lower() or "hash" in str(exc).lower()
        else:
            assert result.outcome is ComputationOutcome.FAILED
            assert result.diagnostics
            if failure == "wrong-type":
                assert result.diagnostics[0].code == "CAD_TYPE_MISMATCH"
            if failure == "native-malformed":
                assert result.diagnostics[0].code in ("CAD_SOLID_INVALID", "CAD_BREP_INVALID")
        assert all(
            a.session.backend_id == "code_visualizer.cad.measurement" for a in service.attempts()
        )
