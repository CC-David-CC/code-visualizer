"""Execute saved P7 continuum source and reuse immutable history in a fresh consumer."""

from __future__ import annotations

import argparse
import hashlib
import importlib.abc
import json
import sys
from contextlib import contextmanager
from math import comb, exp, fsum, pi, sin
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class NoExampleFactories(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith("code_visualizer.ui_qt") or (
            fullname.startswith("code_visualizer.application.")
            and (fullname.endswith("_examples") or fullname.endswith(".examples"))
        ):
            raise ImportError("Saved P7 source owns meaning: " + fullname)
        return None


@contextmanager
def host(project, path):
    from code_visualizer.application.authority import ProjectAuthority
    from code_visualizer.application.computation_service import ComputationService
    from code_visualizer.application.kernel import ProjectKernel
    from code_visualizer.persistence.evidence_store import EvidenceStore
    from code_visualizer.persistence.resource_store import ResourceStore

    service = ComputationService(max_workers=1)
    kernel = ProjectKernel(
        ProjectAuthority(project),
        computations=service,
        resource_store=ResourceStore(path),
        evidence_store=EvidenceStore(path),
    )
    try:
        yield kernel
    finally:
        kernel.close()
        service.close()


def prove(output: Path, example: Path | None = None):
    import numpy as np

    from code_visualizer.application.adaptive_artifacts import prepare_probe
    from code_visualizer.application.computation import (
        execute_computation,
        export_computation_plan,
        run_computation_plan,
    )
    from code_visualizer.application.messages import CommandAccepted
    from code_visualizer.domain.computation import ComputationParameter, ComputationRequest
    from code_visualizer.domain.evidence import ComputationOutcome
    from code_visualizer.domain.project import Project
    from code_visualizer.extensions.adaptive_diffusion.domain import BACKEND_ID
    from code_visualizer.extensions.adaptive_fields.history import (
        AdaptiveHistory,
        mixed_array,
        record,
    )
    from code_visualizer.extensions.adaptive_fields.probe import BACKEND_ID as PROBE
    from code_visualizer.extensions.adaptive_fields.records import (
        DECISION_COLUMNS,
        DECISIONS_TYPE,
        HISTORY_TYPE,
        DecisionLog,
    )
    from code_visualizer.persistence.computation_resources import resolve_computation_resource
    from code_visualizer.persistence.decoding import project_from_json
    from code_visualizer.persistence.resource_store import ResourceStore
    from code_visualizer.persistence.serialization import normalized_project_json
    from code_visualizer.protocol.computation import computation_plan_to_proto
    from code_visualizer.sdk import CodeVisualizerClient

    if output.exists():
        raise ValueError("Choose a fresh proof output directory")
    output.mkdir(parents=True)
    source = (example or ROOT / "examples/physical/adaptive-diffusion/project.json").read_bytes()
    project = project_from_json(source.decode("utf-8"))
    canonical = normalized_project_json(project)

    def history(root, store):
        return AdaptiveHistory(
            root, lambda ref: resolve_computation_resource(store, ref, file_backed=True)
        )

    def latest(evidence, store):
        return [
            a.resource
            for a in evidence.artifacts
            if store.describe(a.resource).logical_type == HISTORY_TYPE
        ][-1]

    with host(project, output / "producer") as kernel:
        evidence = execute_computation(
            kernel,
            ComputationRequest(
                project.id, project.revision, BACKEND_ID, "1", "adaptive:experiment"
            ),
        )
        assert evidence.outcome is ComputationOutcome.SUCCEEDED, evidence.diagnostics
        store, registry = kernel.resource_store, kernel.extensions
        root = latest(evidence, store)
        reader = history(root, store)
        assert reader.sample_count == 201
        errors, masses, partitions = [], [], []
        for sample_id in range(reader.sample_count):
            sample = reader.slice(sample_id)
            time = float(sample.position.time.magnitude)
            squared = []
            for a, b, value in zip(
                sample.mesh.faces[:-1], sample.mesh.faces[1:], sample.values[:, 0], strict=True
            ):
                # Independent exact Fourier cell integral for the pinned pulse.
                oracle = fsum(
                    [1.0, comb(16, 8) / 65536]
                    + [
                        comb(16, 8 - k)
                        / 32768
                        * exp(-0.001 * (2 * pi * k) ** 2 * time)
                        * (sin(2 * pi * k * (b - 0.5)) - sin(2 * pi * k * (a - 0.5)))
                        / (2 * pi * k * (b - a))
                        for k in range(1, 9)
                    ]
                )
                squared.append((b - a) * (float(value) - oracle) ** 2)
            errors.append(fsum(squared) ** 0.5)
            masses.append(float(sample.mesh.widths @ sample.values[:, 0]))
            partitions.append((sample_id, time, sample.epoch, len(sample.mesh.cells)))
        assert max(errors) <= 0.005
        np.testing.assert_allclose(masses, masses[0], rtol=1e-9, atol=0)
        assert len(reader.meshes[-1].cells) < len(reader.meshes[0].cells)
        log = record(reader.resolve, reader.series.decisions, DecisionLog, DECISIONS_TYPE)
        # Own these audit values; a live NumPy mapping would keep the producing
        # file open on Windows even after the history reader is closed.
        decisions = np.array(
            mixed_array(reader.resolve, log.values, (log.rows, len(DECISION_COLUMNS))), copy=True
        )
        assert any(row[9] for row in decisions)
        selected = reader.slice(200)
        cell = selected.mesh.cell_ids[len(selected.mesh.cells) // 2]
        expected = reader.probe(200, selected.epoch, cell, "concentration")
        checkpoint = next(a.resource for a in evidence.artifacts if a.id == "checkpoint:368640")
        assert normalized_project_json(kernel.authority.snapshot()) == canonical
        reader.close()

    consumer = Project("p7:consumer", "Exact retained cell consumer", ())
    target = ResourceStore(output / "probe")
    edit = prepare_probe(
        consumer, registry, store, target, root, 200, selected.epoch, cell, "concentration"
    )
    resumed_store = ResourceStore(output / "restart")
    for ref in registry.resource_closure((checkpoint,), store):
        resumed_store.import_reference(store, ref)
    # A filesystem move makes accidental reads from the producer location fail.
    producing = (output / "producer").resolve()
    retained = (output / "retained-producer").resolve()
    assert producing.is_relative_to(output.resolve()) and retained.is_relative_to(output.resolve())
    producing.rename(retained)
    with host(consumer, output / "probe") as kernel:
        client = CodeVisualizerClient(kernel.authority, actor_id="p7-saved-proof")
        assert isinstance(client.transaction(edit.commands), CommandAccepted)
        current = client.snapshot()
        request = ComputationRequest(current.id, current.revision, PROBE, "1", edit.model_id)
        result = execute_computation(kernel, request)
        assert result.outcome is ComputationOutcome.SUCCEEDED, result.diagnostics
        actual = next(o.value for o in result.observations if o.id == "value")
        assert actual == expected
        plan = export_computation_plan(kernel, request)
        (output / "probe-plan.pb").write_bytes(
            computation_plan_to_proto(plan).SerializeToString(deterministic=True)
        )
        replay = run_computation_plan(plan, registry, target, kernel.evidence_store)
        assert replay == result
        (output / "probe-project.json").write_text(
            normalized_project_json(current), encoding="utf-8"
        )
        client.close()
    with host(project, output / "restart") as kernel:
        resumed = execute_computation(
            kernel,
            ComputationRequest(
                project.id,
                project.revision,
                BACKEND_ID,
                "1",
                "adaptive:experiment",
                configuration=(ComputationParameter("checkpoint", checkpoint),),
            ),
        )
        assert resumed.outcome is ComputationOutcome.SUCCEEDED, resumed.diagnostics
        assert latest(resumed, kernel.resource_store) == root
    report = {
        "phase": "P7-continuum",
        "passed": True,
        "p7_complete": False,
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "history": root.content_hash,
        "sample_count": len(errors),
        "errors": errors,
        "max_l2_error": max(errors),
        "masses": masses,
        "partitions": partitions,
        "producer_location_unavailable_to_consumer": True,
        "exact_cell_consumer": True,
        "portable_consumer_replay": True,
        "complete_resume_identical": True,
        "canonical_unchanged_by_computation": True,
        "example_factory_imports_forbidden": True,
    }
    (output / "proof.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--example", type=Path)
    args = parser.parse_args()
    sys.meta_path.insert(0, NoExampleFactories())
    print(json.dumps(prove(args.output.resolve(), args.example), indent=2))


if __name__ == "__main__":
    main()
