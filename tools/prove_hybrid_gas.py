"""Run saved gas source, consume retained cells and reconstruct a native checkpoint.

The default executes the shipped horizon. --smoke authors an explicit short
schedule through the ordinary authority; it is a distribution check, not the
separately frozen ensemble's scientific qualification.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.abc
import json
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
            raise ImportError("Saved P7 gas source owns meaning: " + fullname)
        return None


@contextmanager
def host(project, path, *, authority=None):
    from code_visualizer.application.authority import ProjectAuthority
    from code_visualizer.application.computation_service import ComputationService
    from code_visualizer.application.kernel import ProjectKernel
    from code_visualizer.persistence.evidence_store import EvidenceStore
    from code_visualizer.persistence.resource_store import ResourceStore

    service = ComputationService(max_workers=1)
    kernel = ProjectKernel(
        authority or ProjectAuthority(project),
        computations=service,
        resource_store=ResourceStore(path),
        evidence_store=EvidenceStore(path),
    )
    try:
        yield kernel
    finally:
        kernel.close()
        service.close()


def prove(output: Path, *, example: Path | None = None, smoke: bool = False):
    import numpy as np

    from code_visualizer.application.authority import ProjectAuthority
    from code_visualizer.application.computation import (
        execute_computation,
        export_computation_plan,
        run_computation_plan,
    )
    from code_visualizer.application.domain_commands import SetDomainProperty
    from code_visualizer.application.gas_artifacts import prepare_probe
    from code_visualizer.application.messages import CommandAccepted
    from code_visualizer.domain.computation import ComputationParameter, ComputationRequest
    from code_visualizer.domain.evidence import ComputationOutcome
    from code_visualizer.domain.project import Project
    from code_visualizer.extensions.builtin import builtin_registry
    from code_visualizer.extensions.gas_observation.domain import BACKEND_ID as PROBE
    from code_visualizer.extensions.gas_observation.reader import cell_ids, probe
    from code_visualizer.extensions.hybrid_gas.checkpoint import method_digest
    from code_visualizer.extensions.hybrid_gas.domain import BACKEND_ID, identity
    from code_visualizer.extensions.hybrid_gas.history import GasHistory
    from code_visualizer.extensions.hybrid_gas.native_api import installation
    from code_visualizer.extensions.hybrid_gas.problem import derive_problem
    from code_visualizer.extensions.hybrid_gas.records import (
        CHECKPOINT_TYPE,
        CODEC,
        HISTORY_TYPE,
        GasCheckpoint,
    )
    from code_visualizer.persistence.computation_resources import resolve_computation_resource
    from code_visualizer.persistence.decoding import project_from_json
    from code_visualizer.persistence.project_resources import copy_project_resources
    from code_visualizer.persistence.resource_store import ResourceStore
    from code_visualizer.persistence.serialization import normalized_project_json
    from code_visualizer.persistence.store import ProjectStore
    from code_visualizer.protocol.computation import computation_plan_to_proto
    from code_visualizer.sdk import CodeVisualizerClient

    output = output.resolve()
    if output.exists():
        raise ValueError("Choose a fresh proof output directory")
    output.mkdir(parents=True)
    example = (example or ROOT / "examples/physical/hybrid-gas/project.json").resolve()
    source = example.read_bytes()
    (output / "received-source.json").write_bytes(source)
    project = project_from_json(source.decode("utf-8"))
    source_store = ProjectStore(output / "authored-source")
    source_store.initialize(project)
    authority = ProjectAuthority(project, store=source_store)
    client = CodeVisualizerClient(authority, actor_id="p7-gas-distribution")
    try:
        if smoke:
            commands = tuple(
                SetDomainProperty("gas:experiment", "gas:policy", identity("Policy", key), value)
                for key, value in (
                    ("final_tick", 1000),
                    ("sample_ticks", 500),
                    ("checkpoint_ticks", 500),
                    ("statistics_ticks", 500),
                    ("block_ticks", 500),
                    ("warmup_ticks", 0),
                    ("preview_windows", 100),
                )
            )
            assert isinstance(client.transaction(commands), CommandAccepted)
        project = client.snapshot()
        source_store.save(project)
        assert source_store.recover(promote=False) == project
    finally:
        client.close()
    canonical = normalized_project_json(project)
    registry = builtin_registry()
    inputs = ResourceStore(example.parent)
    copy_project_resources(
        project,
        inputs,
        None,
        source_store.root,
        resolve_closure=lambda refs: registry.resource_closure(refs, inputs),
    )
    copy_project_resources(
        project,
        inputs,
        None,
        output / "producer",
        resolve_closure=lambda refs: registry.resource_closure(refs, inputs),
    )
    problem = derive_problem(project, project.domain_workspace.model("gas:experiment"))

    def request(checkpoint=None):
        return ComputationRequest(
            project.id,
            project.revision,
            BACKEND_ID,
            "1",
            "gas:experiment",
            configuration=(ComputationParameter("checkpoint", checkpoint),) if checkpoint else (),
        )

    def history(root, store):
        return GasHistory(
            root, lambda ref: resolve_computation_resource(store, ref, file_backed=True)
        )

    def latest(evidence, store, kind):
        return [
            a.resource
            for a in evidence.artifacts
            if store.describe(a.resource).logical_type == kind
        ][-1]

    with host(project, output / "producer") as kernel:
        evidence = execute_computation(kernel, request())
        assert evidence.outcome is ComputationOutcome.SUCCEEDED, evidence.diagnostics
        store = kernel.resource_store
        root = latest(evidence, store, HISTORY_TYPE)
        viewed = history(root, store)
        try:
            assert (
                viewed.sample_count == problem.policy.final_tick // problem.policy.sample_ticks + 1
            )
            expected_samples = tuple(
                viewed.gas_slice(i).conserved.copy() for i in range(viewed.sample_count)
            )
            expected_positions = tuple(
                viewed.gas_slice(i).position for i in range(viewed.sample_count)
            )
            expected_modes = tuple(viewed.gas_slice(i).particle for i in range(viewed.sample_count))
            selected = viewed.gas_slice(viewed.sample_count - 1)
            cell = cell_ids(viewed)[len(cell_ids(viewed)) // 2]
            component = viewed.interpretation.field_ids[1]
            expected = probe(
                viewed,
                selected.position.sample,
                cell,
                component,
                viewed.interpretation.frame_id,
                selected.position.time,
            )
        finally:
            viewed.close()
        checkpoints = [
            a.resource
            for a in evidence.artifacts
            if store.describe(a.resource).logical_type == CHECKPOINT_TYPE
        ]
        checkpoint = checkpoints[1]
        state = CODEC.decode(store.read(checkpoints[-1]), GasCheckpoint)
        assert state.tick == problem.policy.final_tick
        with store.verified_path(state.accumulators).open("rb") as stream:
            accounting = np.load(stream, allow_pickle=False)
        residual = tuple(float(v) for v in accounting[10:15])
        assert len(residual) == 5 and max(residual) <= 1e-10, residual
        origins = {identity for a in evidence.artifacts for identity in a.semantic_ids}
        assert set(problem.origins) <= origins
        assert normalized_project_json(kernel.authority.snapshot()) == canonical

    consumer = Project("p7:gas-consumer", "Exact retained gas cell", ())
    target = ResourceStore(output / "probe")
    edit = prepare_probe(
        consumer, registry, store, target, root, selected.position.sample, 0, cell, component
    )
    restart_store = ResourceStore(output / "restart")
    copy_project_resources(
        project,
        inputs,
        None,
        output / "restart",
        resolve_closure=lambda refs: registry.resource_closure(refs, inputs),
    )
    for ref in registry.resource_closure((checkpoint,), store):
        restart_store.import_reference(store, ref)
    producing, retained = (output / "producer").resolve(), (output / "retained-producer").resolve()
    assert producing.is_relative_to(output) and retained.is_relative_to(output)
    producing.rename(retained)
    assert not producing.exists()
    consumer_store = ProjectStore(output / "probe")
    consumer_store.initialize(consumer)
    with host(
        consumer, output / "probe", authority=ProjectAuthority(consumer, store=consumer_store)
    ) as kernel:
        client = CodeVisualizerClient(kernel.authority, actor_id="p7-retained-consumer")
        try:
            assert isinstance(client.transaction(edit.commands), CommandAccepted)
            current = client.snapshot()
            consumer_store.save(current)
            consumer_request = ComputationRequest(
                current.id, current.revision, PROBE, "1", edit.model_id
            )
            result = execute_computation(kernel, consumer_request)
            assert result.outcome is ComputationOutcome.SUCCEEDED, result.diagnostics
            assert len(result.observations) == 1
            observation = result.observations[0]
            assert observation.value == expected
            assert observation.semantic_ids == current.domain_workspace.model(edit.model_id).roots
            plan = export_computation_plan(kernel, consumer_request)
            (output / "probe-plan.pb").write_bytes(
                computation_plan_to_proto(plan).SerializeToString(deterministic=True)
            )
            replay = run_computation_plan(plan, registry, target, kernel.evidence_store)
            assert replay == result
        finally:
            client.close()
    with host(project, output / "restart") as kernel:
        resumed = execute_computation(kernel, request(checkpoint))
        assert resumed.outcome is ComputationOutcome.SUCCEEDED, resumed.diagnostics
        actual_root = latest(resumed, kernel.resource_store, HISTORY_TYPE)
        assert actual_root == root
        viewed = history(actual_root, kernel.resource_store)
        try:
            for index, values in enumerate(expected_samples):
                actual = viewed.gas_slice(index)
                assert actual.position == expected_positions[index]
                assert actual.particle == expected_modes[index]
                np.testing.assert_array_equal(actual.conserved, values)
        finally:
            viewed.close()
    native = installation()
    report = {
        "phase": "P7-gas",
        "passed": True,
        "p7_complete": False,
        "smoke": smoke,
        "scientific_ensemble_qualification": False,
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "executed_source_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "method_digest": method_digest(),
        "source_revision": project.revision,
        "history": root.content_hash,
        "sample_count": len(expected_samples),
        "final_tick": problem.policy.final_tick,
        "maximum_balance_residuals": residual,
        "particle_modes": expected_modes,
        "origin_ids": sorted(origins),
        "native_path": str(native.binary),
        "native_sha256": hashlib.sha256(native.binary.read_bytes()).hexdigest(),
        "producer_location_unavailable_to_consumer": True,
        "exact_cell_consumer": True,
        "portable_consumer_replay": True,
        "complete_resume_identical": True,
        "canonical_unchanged_by_computation": True,
        "example_factory_imports_forbidden": True,
    }
    assert example.read_bytes() == source
    assert source_store.project_file.read_text(encoding="utf-8") == canonical
    (output / "proof.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--example", type=Path)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    sys.meta_path.insert(0, NoExampleFactories())
    print(json.dumps(prove(args.output, example=args.example, smoke=args.smoke), indent=2))


if __name__ == "__main__":
    main()
