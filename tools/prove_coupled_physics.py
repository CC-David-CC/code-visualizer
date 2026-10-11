"""Run saved P6 definitions, copy exact resources and use ordinary independent consumers."""

from __future__ import annotations

import argparse
import hashlib
import importlib.abc
import json
import math
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class NoExampleFactories(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith("code_visualizer.ui_qt") or (
            fullname.startswith("code_visualizer.application.")
            and (fullname.endswith("_examples") or fullname.endswith(".examples"))
        ):
            raise ImportError("P6 execution consumes saved canonical source: " + fullname)
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


def prove(
    output: Path, *, example: Path | None = None, axial_example: Path | None = None
) -> dict[str, object]:
    import numpy as np

    from code_visualizer.application.axial_artifacts import prepare_axial
    from code_visualizer.application.channel_artifacts import prepare_probe
    from code_visualizer.application.computation import (
        execute_computation,
        export_computation_plan,
        run_computation_plan,
    )
    from code_visualizer.application.messages import CommandAccepted
    from code_visualizer.domain.computation import (
        ComputationParameter,
        ComputationRequest,
        ResourceOutput,
    )
    from code_visualizer.domain.evidence import ComputationOutcome
    from code_visualizer.domain.project import Project
    from code_visualizer.extensions.axial.presentation import prepare_result
    from code_visualizer.extensions.cad.resources import BREP
    from code_visualizer.extensions.channels.history import ChannelHistory
    from code_visualizer.extensions.channels.probe import BACKEND_ID as PROBE
    from code_visualizer.extensions.channels.records import SERIES_TYPE
    from code_visualizer.extensions.electrothermal.domain import BACKEND_ID as COUPLED
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
    source = (example or ROOT / "examples/physical/electrothermal/project.json").read_bytes()
    cad_source = (axial_example or ROOT / "examples/physical/axial-bar/project.json").read_bytes()
    project = project_from_json(source.decode("utf-8"))
    canonical = normalized_project_json(project)

    def series_data(store, root):
        history = ChannelHistory(
            root, lambda ref: resolve_computation_resource(store, ref, file_backed=True)
        )
        try:
            data = np.concatenate([a.copy() for _, a in history.iter_chunks()])
            return data, history.interpretation
        finally:
            history.close()

    with host(project, output / "coupled") as kernel:
        result = execute_computation(
            kernel,
            ComputationRequest(
                project.id, project.revision, COUPLED, "1", "electrothermal:experiment"
            ),
        )
        assert result.outcome is ComputationOutcome.SUCCEEDED, result.diagnostics
        store = kernel.resource_store
        root = [
            a.resource
            for a in result.artifacts
            if store.describe(a.resource).logical_type == SERIES_TYPE
        ][-1]
        data, meaning = series_data(store, root)
        assert tuple(data[:, 0]) == tuple(range(0, 101, 5))
        assert normalized_project_json(kernel.authority.snapshot()) == canonical
        checkpoint = next(a.resource for a in result.artifacts if a.id == "checkpoint:50")
        registry = kernel.extensions

    # Independent eliminated backward-Euler equations for the declared default.
    # No production RHS, solver, example or reference helper is imported.
    x = y = energy_in = energy_out = 0.0
    oracle = [(293.15, 293.15, energy_in, energy_out)]
    b, a = 20 + 0.2 + 0.1, 10 + 0.2 - 0.2**2 / (20 + 0.2 + 0.1)
    for step in range(1, 101):
        d = 10 * x + 0.2 * 20 * y / b
        aa, bb, cc = a * 0.004, a - d * 0.004, -d - 2.5
        x = -2 * cc / (bb + math.sqrt(bb * bb - 4 * aa * cc))
        y = (20 * y + 0.2 * x) / b
        energy_in += 2.5 / (1 + 0.004 * x)
        energy_out += 0.1 * y
        if step % 5 == 0:
            oracle.append((293.15 + x, 293.15 + y, energy_in, energy_out))
    expected = np.asarray(oracle)
    errors = np.max(np.abs(data[:, (2, 3, 11, 12)] - expected), axis=0)
    assert np.all(errors < 1e-8), errors

    consumer = Project("p6:consumer", "Exact retained channel inspection", ())
    target = ResourceStore(output / "probe")
    edit = prepare_probe(
        consumer, registry, store, target, root, len(data) - 1, meaning.channels[0].id
    )
    # Only copied declared resources are available after both producers exit.
    (output / "coupled").rename(output / "retained-coupled")
    with host(consumer, output / "probe") as kernel:
        client = CodeVisualizerClient(kernel.authority, actor_id="p6-proof")
        assert isinstance(client.transaction(edit.commands), CommandAccepted)
        current = client.snapshot()
        probe_request = ComputationRequest(current.id, current.revision, PROBE, "1", edit.model_id)
        inspected = execute_computation(kernel, probe_request)
        assert inspected.outcome is ComputationOutcome.SUCCEEDED, inspected.diagnostics
        assert inspected.observations[0].value.magnitude == data[-1, 2]
        assert not current.program_model.functions
        plan = export_computation_plan(kernel, probe_request)
        (output / "probe-plan.pb").write_bytes(
            computation_plan_to_proto(plan).SerializeToString(deterministic=True)
        )
        replay = run_computation_plan(plan, registry, target, kernel.evidence_store)
        assert replay == inspected
        (output / "probe-project.json").write_text(
            normalized_project_json(current), encoding="utf-8"
        )
        client.close()
    retained = ResourceStore(output / "retained-coupled")
    restart_store = ResourceStore(output / "restart")
    for ref in registry.resource_closure((checkpoint,), retained):
        restart_store.import_reference(retained, ref)
    with host(project, output / "restart") as kernel:
        resumed = execute_computation(
            kernel,
            ComputationRequest(
                project.id,
                project.revision,
                COUPLED,
                "1",
                "electrothermal:experiment",
                configuration=(ComputationParameter("checkpoint", checkpoint),),
            ),
        )
        assert resumed.outcome is ComputationOutcome.SUCCEEDED, resumed.diagnostics
        continued = [
            a.resource
            for a in resumed.artifacts
            if restart_store.describe(a.resource).logical_type == SERIES_TYPE
        ][-1]
        assert np.array_equal(series_data(restart_store, continued)[0], data)

    cad = project_from_json(cad_source.decode("utf-8"))
    with host(cad, output / "cad") as kernel:
        geometry = execute_computation(
            kernel,
            ComputationRequest(
                cad.id,
                cad.revision,
                "code_visualizer.python",
                "2",
                configuration=(ComputationParameter("timeout_seconds", 120),),
                outputs=(ResourceOutput("bar", BREP, ("bar:box", "bar:publish")),),
            ),
        )
        assert geometry.outcome is ComputationOutcome.SUCCEEDED, geometry.diagnostics
        solid = next(
            a
            for a in geometry.artifacts
            if kernel.resource_store.describe(a.resource).logical_type == BREP
        )
        producer = kernel.resource_store
        assert normalized_project_json(cad) == normalized_project_json(kernel.authority.snapshot())
    structural = Project("p6:axial", "Independent axial consumer", ())
    structural_store = ResourceStore(output / "axial")
    edit = prepare_axial(
        structural,
        registry,
        geometry,
        solid.id,
        producer,
        structural_store,
        young_modulus=2e11,
        force=1000,
        nodes=17,
        axis="x",
    )
    (output / "cad").rename(output / "retained-cad")
    with host(structural, output / "axial") as kernel:
        client = CodeVisualizerClient(kernel.authority, actor_id="p6-structural-proof")
        assert isinstance(client.transaction(edit.commands), CommandAccepted)
        current = client.snapshot()
        solved = execute_computation(kernel, edit.request(current))
        assert solved.outcome is ComputationOutcome.SUCCEEDED, solved.diagnostics
        view = prepare_result(
            solved.artifacts[0].resource,
            lambda ref: resolve_computation_resource(structural_store, ref),
        )
        assert math.isclose(view.displacement[-1], 5e-6, rel_tol=1e-8, abs_tol=1e-12)
        assert all(math.isclose(v, 1e7, rel_tol=1e-8) for v in view.stress)
        assert math.isclose(view.result.reaction.magnitude, -1000, rel_tol=1e-8)
        assert math.isclose(view.result.strain_energy.magnitude, 0.0025, rel_tol=1e-8)
        assert not current.program_model.functions and client.snapshot() == current
        plan = export_computation_plan(kernel, edit.request(current))
        empty = ResourceStore(output / "portable-axial")
        for ref in registry.resource_closure(
            (plan.model, *plan.request.resources), structural_store
        ):
            empty.import_reference(structural_store, ref)
        (output / "axial-project.json").write_text(
            normalized_project_json(current), encoding="utf-8"
        )
        client.close()
    again = run_computation_plan(plan, registry, empty, EvidenceStore(output / "portable-axial"))
    assert again == solved
    report = {
        "phase": "P6",
        "passed": True,
        "scope": "saved-source host/native/resource/portable proof",
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "cad_source_sha256": hashlib.sha256(cad_source).hexdigest(),
        "coupled_evidence": result.id,
        "coupled_input": result.provenance.input_digest,
        "series_hash": root.content_hash,
        "independent_discrete_errors_K_K_J_J": errors.tolist(),
        "samples": len(data),
        "probe_evidence": inspected.id,
        "resumed_evidence": resumed.id,
        "portable_consumer_replay": True,
        "complete_resume_identical": True,
        "producer_location_unavailable_to_consumer": True,
        "cad_evidence": geometry.id,
        "structural_evidence": solved.id,
        "axial_extension_m": view.displacement[-1],
        "portable_axial_identical": True,
        "source_only_producers": True,
        "canonical_unchanged_by_computation": True,
        "example_factory_imports_forbidden": True,
    }
    (output / "proof.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--example", type=Path)
    parser.add_argument("--axial-example", type=Path)
    args = parser.parse_args()
    blocker = NoExampleFactories()
    sys.meta_path.insert(0, blocker)
    try:
        report = prove(
            args.output.resolve(), example=args.example, axial_example=args.axial_example
        )
    finally:
        sys.meta_path.remove(blocker)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
