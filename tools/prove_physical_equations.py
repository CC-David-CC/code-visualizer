"""Execute shipped canonical P3 inputs through the host and replay their portable plans."""

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
        if fullname in {
            "code_visualizer.application.examples",
            "code_visualizer.application.physical_examples",
            "code_visualizer.extensions.foundations.examples",
        } or fullname.startswith("code_visualizer.ui_qt"):
            raise ImportError(f"Physical execution cannot depend on factories or Qt: {fullname}")
        return None


def prove(output: Path, *, examples: Path | None = None) -> dict[str, object]:
    from code_visualizer.application.authority import ProjectAuthority
    from code_visualizer.application.computation import (
        execute_computation,
        export_computation_plan,
        run_computation_plan,
    )
    from code_visualizer.application.domain_workbench import project_notation
    from code_visualizer.application.kernel import ProjectKernel
    from code_visualizer.domain.computation import ComputationRequest
    from code_visualizer.domain.evidence import ComputationOutcome
    from code_visualizer.domain.notation import NotationKind
    from code_visualizer.domain.transformation import derived_id
    from code_visualizer.domain.values import QuantityValue
    from code_visualizer.extensions.builtin import builtin_registry
    from code_visualizer.extensions.dc import TRANSFORMATION
    from code_visualizer.extensions.foundations.equations import BACKEND_ID
    from code_visualizer.persistence.decoding import project_from_json
    from code_visualizer.persistence.evidence_store import EvidenceStore
    from code_visualizer.persistence.resource_store import ResourceStore
    from code_visualizer.persistence.serialization import normalized_project_json
    from code_visualizer.protocol.computation import (
        computation_plan_from_proto,
        computation_plan_to_proto,
    )
    from code_visualizer.protocol.evidence import evidence_from_proto, evidence_to_proto

    examples = examples or ROOT / "examples" / "physical"
    if output.exists():
        raise ValueError("Choose a fresh proof output directory")
    output.mkdir(parents=True)
    reports = []
    for name, model_id, observation_id, expected, origin in (
        (
            "dc-divider",
            "dc:network",
            derived_id(TRANSFORMATION.key, "dc:middle", "potential") + ":solution",
            2.5,
            "dc:middle",
        ),
        ("spring-equation", "spring:equations", "spring:x:solution", 0.05, "spring:x"),
    ):
        source = (examples / name / "project.json").read_bytes()
        project = project_from_json(source.decode("utf-8"))
        canonical = normalized_project_json(project)
        assert not project.program_model.functions and not project.program_model.modules
        case = output / name
        resources, evidence_store = ResourceStore(case), EvidenceStore(case)
        kernel = ProjectKernel(
            ProjectAuthority(project), resource_store=resources, evidence_store=evidence_store
        )
        try:
            request = ComputationRequest(project.id, project.revision, BACKEND_ID, "1", model_id)
            evidence = execute_computation(kernel, request)
            assert evidence.outcome is ComputationOutcome.SUCCEEDED, evidence.diagnostics
            observation = next(item for item in evidence.observations if item.id == observation_id)
            assert isinstance(observation.value, QuantityValue)
            assert math.isclose(observation.value.magnitude, expected, rel_tol=1e-10, abs_tol=1e-12)
            assert origin in evidence.provenance.origins.sources(observation.semantic_ids[0])
            highlighted = []
            history = kernel.runtime.history(kernel.runtime.active.execution_session_id)
            model = project.domain_workspace.model(model_id)
            definitions = kernel.extensions.notations_for(model.schema_id, model.schema_version)
            for kind in (NotationKind.GRAPH, NotationKind.TABLE, NotationKind.TREE_FORM):
                definition = next(item for item in definitions if item.kind is kind)
                # Each actual observation decorates its applicable objects. The last
                # observation alone need not appear in every filtered notation.
                projections = (
                    project_notation(
                        project,
                        model_id,
                        definition.id,
                        kernel.extensions,
                        active_node_ids=state.active_ids,
                        runtime_revision=state.project_revision,
                    )
                    for state in history
                )
                assert any(
                    any(row.active for row in notation.rows)
                    if kind is NotationKind.TABLE
                    else any("active" in node.badges for node in notation.graph.nodes)
                    for notation in projections
                ), (name, kind)
                highlighted.append(kind.value)
            assert normalized_project_json(kernel.authority.snapshot()) == canonical
            plan = export_computation_plan(kernel, request)
            message = computation_plan_to_proto(plan)
            (case / "plan.pb").write_bytes(message.SerializeToString(deterministic=True))
            plan = computation_plan_from_proto(message)
            evidence_message = evidence_to_proto(evidence)
            assert evidence_from_proto(evidence_message) == evidence
            (case / "evidence.pb").write_bytes(
                evidence_message.SerializeToString(deterministic=True)
            )
        finally:
            kernel.close()
        # Ordinary host execution has ended. Only the sealed plan and resources are needed.
        replay = run_computation_plan(plan, builtin_registry(), resources, evidence_store)
        assert replay == evidence
        assert evidence_store.get(evidence.id) == evidence
        report = json.loads(resources.read(evidence.artifacts[0].resource))
        assert max(abs(row["normalized"]) for row in report["residuals"]) <= 1e-10
        reports.append(
            {
                "example": name,
                "source_sha256": hashlib.sha256(source).hexdigest(),
                "input_digest": evidence.provenance.input_digest,
                "evidence_id": evidence.id,
                "resource": evidence.artifacts[0].resource.id,
                "expected": expected,
                "value": observation.value.magnitude,
                "origin": origin,
                "highlighted_notations": highlighted,
                "portable_replay_identical": True,
                "canonical_unchanged": True,
                "libraries": report["libraries"],
            }
        )
    result = {"passed": True, "physical_examples": reports, "program_lowering": False}
    (output / "proof.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--examples", type=Path)
    options = parser.parse_args()
    blocker = NoExampleFactories()
    sys.meta_path.insert(0, blocker)
    try:
        result = prove(options.output.resolve(), examples=options.examples)
    finally:
        sys.meta_path.remove(blocker)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
