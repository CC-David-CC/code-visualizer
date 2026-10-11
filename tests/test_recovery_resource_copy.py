"""Recovery copies retain immutable resources and evidence without moving owners."""

from dataclasses import replace

import pytest

from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.evidence import (
    ComputationEvidence,
    ComputationOutcome,
    EvidenceObservation,
    EvidenceProvenance,
)
from code_visualizer.domain.intentional import (
    ConceptDefinition,
    DomainModel,
    DomainSchema,
    DomainWorkspace,
    IntentionalNode,
    PropertyDefinition,
    PropertyValue,
    ValueKind,
)
from code_visualizer.domain.project import Project
from code_visualizer.domain.transformation import OriginLink, OriginMap
from code_visualizer.persistence import ProjectStore
from code_visualizer.persistence.evidence import evidence_content_hash
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore


def _saved_resource_project(root):
    resources = ResourceStore(root)
    source = resources.put(b"canonical input", "application/octet-stream")
    output = resources.put(b"observed result", "text/plain")
    terminal = resources.put(b"portable terminal", "application/octet-stream")
    unrelated = resources.put(b"unrelated cache", "application/octet-stream")
    schema = DomainSchema(
        "schema",
        "proof.resources",
        "1",
        (
            ConceptDefinition(
                "concept",
                "Sample",
                (PropertyDefinition("data", "Data", ValueKind.RESOURCE, required=True),),
            ),
        ),
    )
    model = DomainModel(
        "model",
        schema.id,
        schema.version,
        ("node",),
        (IntentionalNode("node", "concept", (PropertyValue("data", source.reference),)),),
    )
    project = Project(
        "resource-copy",
        "Resource recovery",
        (),
        domain_workspace=DomainWorkspace((schema,), (model,)),
    )
    evidence = ComputationEvidence(
        "pending",
        EvidenceProvenance(
            project.id,
            project.revision,
            model.id,
            "proof.backend",
            "1",
            "0" * 64,
            (),
            None,
            (source.reference,),
            (),
            OriginMap(project.id, project.revision, (OriginLink("node", ("node",)),)),
            terminal.reference,
        ),
        ComputationOutcome.SUCCEEDED,
        (EvidenceObservation("observation", ("node",), output.reference),),
    )
    evidence = replace(evidence, id="evidence:" + evidence_content_hash(evidence))
    ProjectStore(root).initialize(project)
    EvidenceStore(root).put(evidence)
    return project, evidence, source, output, terminal, unrelated


def test_recovery_copy_retains_canonical_and_evidence_resource_closure(tmp_path):
    source_root, destination = tmp_path / "original", tmp_path / "recovered"
    project, evidence, source, output, terminal, unrelated = _saved_resource_project(source_root)
    before = (source_root / "project.json").read_bytes()
    session = ProjectSession.open(source_root)
    try:
        with pytest.raises(RuntimeError, match="explicit project move/copy"):
            session.save_as(destination)
        assert session.save_recovery_copy(destination) == destination.resolve()
        assert session.root == source_root.resolve()
        assert session.authority.snapshot() == project
        assert (source_root / "project.json").read_bytes() == before
    finally:
        session.close()
    recovered = ProjectSession.open(destination)
    try:
        assert recovered.authority.snapshot() == project
        assert recovered.kernel.evidence_store.get(evidence.id) == evidence
        for descriptor in (source, output, terminal):
            assert recovered.kernel.resource_store.describe(descriptor.reference) == descriptor
            assert recovered.kernel.resource_store.read(descriptor.reference) == ResourceStore(
                source_root
            ).read(descriptor.reference)
        with pytest.raises(FileNotFoundError):
            recovered.kernel.resource_store.describe(unrelated.reference)
        assert not ProjectStore(destination).read_journal()
    finally:
        recovered.close()


def test_corrupt_recovery_resource_never_publishes_a_dangling_snapshot(tmp_path):
    source_root, destination = tmp_path / "original", tmp_path / "recovered"
    project, evidence, source, *_ = _saved_resource_project(source_root)
    session = ProjectSession.open(source_root)
    try:
        ResourceStore(source_root).verified_path(source.reference).write_bytes(b"corrupt")
        with pytest.raises(ValueError, match="hash or byte size"):
            session.save_recovery_copy(destination)
        assert not (destination / "project.json").exists()
        assert session.authority.snapshot() == project
        assert EvidenceStore(source_root).get(evidence.id) == evidence
    finally:
        session.close()
