"""Run saved diffusion source, then probe retained history after producer exit."""

from __future__ import annotations

import argparse
import hashlib
import importlib.abc
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class NoExampleFactories(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith("code_visualizer.ui_qt") or fullname in {
            "code_visualizer.application.examples",
            "code_visualizer.application.field_examples",
            "code_visualizer.application.physical_examples",
            "code_visualizer.application.cad_examples",
        }:
            raise ImportError("Field execution must use saved canonical source: " + fullname)
        return None


def prove(output: Path, *, example: Path | None = None) -> dict[str, object]:
    from code_visualizer.application.authority import ProjectAuthority
    from code_visualizer.application.computation import (
        execute_computation,
        export_computation_plan,
        run_computation_plan,
    )
    from code_visualizer.application.computation_service import ComputationService
    from code_visualizer.application.field_artifacts import prepare_probe
    from code_visualizer.application.kernel import ProjectKernel
    from code_visualizer.application.messages import CommandAccepted
    from code_visualizer.domain.computation import ComputationParameter, ComputationRequest
    from code_visualizer.domain.evidence import ComputationOutcome
    from code_visualizer.domain.project import Project
    from code_visualizer.extensions.diffusion.domain import BACKEND_ID
    from code_visualizer.extensions.fields.history import FieldHistory
    from code_visualizer.extensions.fields.probe import BACKEND_ID as PROBE
    from code_visualizer.extensions.fields.records import SERIES_TYPE
    from code_visualizer.persistence.computation_resources import resolve_computation_resource
    from code_visualizer.persistence.decoding import project_from_json
    from code_visualizer.persistence.evidence_store import EvidenceStore
    from code_visualizer.persistence.resource_store import ResourceStore
    from code_visualizer.persistence.serialization import normalized_project_json
    from code_visualizer.protocol.computation import computation_plan_to_proto
    from code_visualizer.sdk import CodeVisualizerClient

    if output.exists():
        raise ValueError("Choose a fresh proof output directory")
    output.mkdir(parents=True)
    source = (example or ROOT / "examples/physical/diffusion-field/project.json").read_bytes()
    project = project_from_json(source.decode("utf-8"))
    canonical = normalized_project_json(project)
    resources = ResourceStore(output / "producer")
    evidence_store = EvidenceStore(output / "producer")
    service = ComputationService()
    kernel = ProjectKernel(
        ProjectAuthority(project),
        computations=service,
        resource_store=resources,
        evidence_store=evidence_store,
    )
    try:
        result = execute_computation(
            kernel,
            ComputationRequest(
                project.id, project.revision, BACKEND_ID, "1", "diffusion:experiment"
            ),
        )
        assert result.outcome is ComputationOutcome.SUCCEEDED, result.diagnostics
        assert normalized_project_json(kernel.authority.snapshot()) == canonical
        root = [
            a.resource
            for a in result.artifacts
            if resources.describe(a.resource).logical_type == SERIES_TYPE
        ][-1]
        history = FieldHistory(
            root, lambda ref: resolve_computation_resource(resources, ref, file_backed=True)
        )
        final = history.slice(history.sample_count - 1)
        sample, midpoint = final.position.sample, history.support.nodes // 2
        actual = float(final.values[midpoint])
        analytic = 10 * math.exp(-0.1 * math.pi**2)
        assert abs(actual - analytic) < 0.0008
        history.close()
    finally:
        kernel.close()
        service.close()
    # A separate canonical consumer and a fresh host receive only typed resource
    # closure. No producing Python instance or duplicate editable field is retained.
    consumer = Project("field:independent-probe", "Independent field inspection", ())
    service = ComputationService()
    target = ResourceStore(output / "consumer")
    kernel = ProjectKernel(
        ProjectAuthority(consumer),
        computations=service,
        resource_store=target,
        evidence_store=EvidenceStore(output / "consumer"),
    )
    try:
        edit = prepare_probe(consumer, kernel.extensions, resources, target, root, sample, midpoint)
        # The original producer location becomes inaccessible before consumption.
        # Only the copied closure is available to the independent probe worker.
        (output / "producer").rename(output / "retained-producer")
        client = CodeVisualizerClient(kernel.authority, actor_id="field-proof")
        accepted = client.transaction(
            edit.commands,
            expected_revision=edit.revision,
            intent="Author an exact consumer of retained field evidence",
        )
        assert isinstance(accepted, CommandAccepted), accepted
        current = kernel.authority.snapshot()
        request = ComputationRequest(current.id, current.revision, PROBE, "1", edit.model_id)
        inspected = execute_computation(kernel, request)
        assert inspected.outcome is ComputationOutcome.SUCCEEDED, inspected.diagnostics
        assert inspected.observations[0].value.magnitude == actual
        assert not current.program_model.functions
        assert all(
            n.concept_id != "foundation.fields:Field"
            for m in current.domain_workspace.models
            for n in m.nodes
        )
        plan = export_computation_plan(kernel, request)
        (output / "probe-plan.pb").write_bytes(
            computation_plan_to_proto(plan).SerializeToString(deterministic=True)
        )
        replay = run_computation_plan(plan, kernel.extensions, target, kernel.evidence_store)
        assert replay == inspected
        (output / "consumer-project.json").write_text(
            normalized_project_json(current), encoding="utf-8"
        )
    finally:
        kernel.close()
        service.close()
    # A third ordinary host restarts numerical state from retained resources.
    import numpy as np

    retained = ResourceStore(output / "retained-producer")
    restarted = ResourceStore(output / "resume")
    service = ComputationService()
    kernel = ProjectKernel(
        ProjectAuthority(project),
        computations=service,
        resource_store=restarted,
        evidence_store=EvidenceStore(output / "resume"),
    )
    try:
        checkpoint = next(a.resource for a in result.artifacts if a.id == "checkpoint:1024")
        for reference in kernel.extensions.resource_closure((checkpoint,), retained):
            restarted.import_reference(retained, reference)
        request = ComputationRequest(
            project.id,
            project.revision,
            BACKEND_ID,
            "1",
            "diffusion:experiment",
            configuration=(ComputationParameter("checkpoint", checkpoint),),
        )
        resumed = execute_computation(kernel, request)
        assert resumed.outcome is ComputationOutcome.SUCCEEDED, resumed.diagnostics
        resumed_root = [
            a.resource
            for a in resumed.artifacts
            if restarted.describe(a.resource).logical_type == SERIES_TYPE
        ][-1]
        original_history = FieldHistory(
            root, lambda ref: resolve_computation_resource(retained, ref, file_backed=True)
        )
        resumed_history = FieldHistory(
            resumed_root, lambda ref: resolve_computation_resource(restarted, ref, file_backed=True)
        )
        try:
            assert original_history.sample_count == resumed_history.sample_count
            resume_error = 0.0
            for index in range(original_history.sample_count):
                first, second = original_history.slice(index), resumed_history.slice(index)
                assert first.position == second.position
                resume_error = max(
                    resume_error, float(np.max(np.abs(first.values - second.values)))
                )
            assert resume_error <= 1e-9
        finally:
            original_history.close()
            resumed_history.close()
        resume_plan = export_computation_plan(kernel, request)
        (output / "resume-plan.pb").write_bytes(
            computation_plan_to_proto(resume_plan).SerializeToString(deterministic=True)
        )
        resumed_replay = run_computation_plan(
            resume_plan, kernel.extensions, restarted, kernel.evidence_store
        )
        assert resumed_replay.artifacts == resumed.artifacts
        assert resumed_replay.observations == resumed.observations
        assert normalized_project_json(kernel.authority.snapshot()) == canonical
    finally:
        kernel.close()
        service.close()
    report = {
        "phase": "P5",
        "passed": True,
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "producer_evidence": result.id,
        "input_digest": result.provenance.input_digest,
        "series": root.id,
        "series_hash": root.content_hash,
        "sample": sample,
        "time_seconds": final.position.time.magnitude,
        "midpoint": actual,
        "analytic_midpoint": analytic,
        "absolute_error": abs(actual - analytic),
        "consumer_evidence": inspected.id,
        "portable_consumer_replay": True,
        "producer_location_unavailable_to_consumer": True,
        "resumed_evidence": resumed.id,
        "resume_max_error": resume_error,
        "portable_restart_identical": True,
        "producer_closed_before_consumer": True,
        "canonical_unchanged": True,
    }
    (output / "proof.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--example", type=Path)
    options = parser.parse_args()
    blocker = NoExampleFactories()
    sys.meta_path.insert(0, blocker)
    try:
        result = prove(options.output.resolve(), example=options.example)
    finally:
        sys.meta_path.remove(blocker)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
