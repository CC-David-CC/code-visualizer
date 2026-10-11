"""Reproduce the semantic indexed-equation proof without generated Python."""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from code_visualizer.application.authority import ProjectAuthority  # noqa: E402
from code_visualizer.application.computation import (  # noqa: E402
    execute_computation,
    export_computation_plan,
    run_computation_plan,
)
from code_visualizer.application.kernel import ProjectKernel  # noqa: E402
from code_visualizer.domain.computation import ComputationRequest  # noqa: E402
from code_visualizer.domain.evidence import ComputationOutcome  # noqa: E402
from code_visualizer.domain.notation import NotationKind  # noqa: E402
from code_visualizer.domain.values import TensorDType, TensorValue  # noqa: E402
from code_visualizer.extensions.builtin import builtin_registry  # noqa: E402
from code_visualizer.extensions.foundations.backend import BACKEND_ID  # noqa: E402
from code_visualizer.extensions.foundations.examples import matrix_product_project  # noqa: E402
from code_visualizer.persistence.computation import (  # noqa: E402
    computation_plan_from_data,
    computation_plan_to_data,
)
from code_visualizer.persistence.decoding import project_from_json  # noqa: E402
from code_visualizer.persistence.evidence_store import EvidenceStore  # noqa: E402
from code_visualizer.persistence.resource_store import ResourceStore  # noqa: E402
from code_visualizer.persistence.serialization import normalized_project_json  # noqa: E402
from code_visualizer.protocol.computation import (  # noqa: E402
    computation_plan_from_proto,
    computation_plan_to_proto,
)
from code_visualizer.protocol.evidence import evidence_from_proto, evidence_to_proto  # noqa: E402
from code_visualizer.protocol.v1 import computation_pb2, evidence_pb2  # noqa: E402


def prove(output: Path) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    project = matrix_product_project()
    canonical = normalized_project_json(project)
    assert project_from_json(canonical) == project
    project_path = output / "project.json"
    if project_path.exists() and project_path.read_text(encoding="utf-8") != canonical:
        raise ValueError("Output contains a different project; choose a fresh --output directory")
    project_path.write_text(canonical, encoding="utf-8", newline="\n")
    resources = ResourceStore(output)
    evidence_store = EvidenceStore(output)
    kernel = ProjectKernel(
        ProjectAuthority(project), resource_store=resources, evidence_store=evidence_store
    )
    try:
        request = ComputationRequest(project.id, project.revision, BACKEND_ID, "1", "matrix:model")
        evidence = execute_computation(kernel, request)
        expected = TensorValue(TensorDType.FLOAT64, (2, 2), (19.0, 22.0, 43.0, 50.0))
        assert evidence.outcome is ComputationOutcome.SUCCEEDED, evidence.diagnostics
        assert evidence.observations[0].value == expected
        assert evidence.provenance.transformations == ()
        origins = evidence.observations[0].semantic_ids
        assert {"matrix:equation", "matrix:expression:sum", "matrix:k", "matrix:C"} <= set(origins)
        assert normalized_project_json(kernel.authority.snapshot()) == canonical
        assert project.program_model.functions == ()
        output_reference = evidence.artifacts[0].resource
        assert struct.unpack("<4d", resources.read(output_reference)) == expected.elements
        assert evidence.provenance.terminal_resource is not None
        resources.read(evidence.provenance.terminal_resource)
        assert evidence_store.get(evidence.id) == evidence
        highlighted = []
        for kind in (NotationKind.GRAPH, NotationKind.TABLE, NotationKind.TREE_FORM):
            definition = next(
                item for item in kernel.notations("matrix:model") if item.kind is kind
            )
            notation = kernel.notation("matrix:model", definition.id)
            assert (
                any(row.active for row in notation.rows)
                if kind is NotationKind.TABLE
                else any(node.badges for node in notation.graph.nodes)
            )
            highlighted.append(kind.value)
        plan = export_computation_plan(kernel, request)
        plan_data = computation_plan_to_data(plan)
        (output / "plan.json").write_text(
            json.dumps(plan_data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
        plan_bytes = computation_plan_to_proto(plan).SerializeToString(deterministic=True)
        (output / "plan.pb").write_bytes(plan_bytes)
        decoded_plan = computation_plan_from_proto(
            computation_pb2.ComputationPlan.FromString(plan_bytes)
        )
        assert decoded_plan == computation_plan_from_data(json.loads(json.dumps(plan_data)))
        # The worker receives only the binary plan, explicit resource store and static registry.
        worker_evidence = run_computation_plan(
            decoded_plan,
            builtin_registry(),
            resources,
            evidence_store,
        )
        assert worker_evidence == evidence
        evidence_bytes = evidence_to_proto(evidence).SerializeToString(deterministic=True)
        (output / "evidence.pb").write_bytes(evidence_bytes)
        assert (
            evidence_from_proto(evidence_pb2.ComputationEvidence.FromString(evidence_bytes))
            == evidence
        )
        report: dict[str, object] = {
            "passed": True,
            "equation": "C[i,j] = sum(k, A[i,k] * B[k,j])",
            "expected_tensor": [[19.0, 22.0], [43.0, 50.0]],
            "canonical_unchanged": True,
            "program_functions": 0,
            "transformations": [],
            "origin_ids": list(origins),
            "highlighted_notations": highlighted,
            "evidence_id": evidence.id,
            "input_digest": evidence.provenance.input_digest,
            "output_resource": output_reference.id,
            "terminal_resource": evidence.provenance.terminal_resource.id,
            "portable_worker_equal": True,
            "protobuf_roundtrip_equal": True,
        }
        (output / "proof.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
        return report
    finally:
        kernel.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "examples/proofs/foundation-math")
    arguments = parser.parse_args()
    print(json.dumps(prove(arguments.output.resolve()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
