"""Execute the shipped native CAD source, then consume its artifacts in fresh hosts."""

from __future__ import annotations

import argparse
import hashlib
import importlib.abc
import json
import math
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class NoExampleFactories(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {
            "code_visualizer.application.examples",
            "code_visualizer.application.cad_examples",
            "code_visualizer.application.physical_examples",
        } or fullname.startswith("code_visualizer.ui_qt"):
            raise ImportError("CAD execution must use saved native source: " + fullname)
        return None


def prove(output: Path, *, example: Path | None = None) -> dict[str, object]:
    from code_visualizer.application.cad_artifacts import prepare_consumer
    from code_visualizer.application.computation import (
        execute_computation,
        export_computation_plan,
        run_computation_plan,
    )
    from code_visualizer.application.computation_service import ComputationService
    from code_visualizer.application.domain_commands import SetDomainProperty
    from code_visualizer.application.messages import CommandAccepted
    from code_visualizer.application.session import ProjectSession
    from code_visualizer.domain.computation import (
        ComputationParameter,
        ComputationRequest,
        ResourceInput,
        ResourceOutput,
    )
    from code_visualizer.domain.evidence import ComputationOutcome
    from code_visualizer.domain.program import program_statements
    from code_visualizer.domain.resources import ResourceLogicalTypeReference
    from code_visualizer.extensions.cad.domain import identity, quantity
    from code_visualizer.extensions.cad.native import decode_mesh, decode_solid
    from code_visualizer.extensions.cad.resources import BREP, MESH
    from code_visualizer.persistence.decoding import project_from_json
    from code_visualizer.persistence.store import ProjectStore
    from code_visualizer.protocol.computation import (
        computation_plan_from_proto,
        computation_plan_to_proto,
    )

    if output.exists():
        raise ValueError("Choose a fresh proof output directory")
    source = (example or ROOT / "examples/physical/spring-cad/project.json").read_bytes()
    project = project_from_json(source.decode("utf-8"))
    ProjectStore(output).initialize(project)
    reports = []

    def run(request):
        # A new service is closed after every producer/consumer. No live Python
        # object or earlier process is available to the next step.
        with closing(ComputationService()) as service:
            session = ProjectSession.open(output, computations=service)
            try:
                evidence = execute_computation(session.kernel, request)
                assert evidence.outcome is ComputationOutcome.SUCCEEDED, evidence.diagnostics
                reports.append(
                    {
                        "backend": request.backend_id,
                        "evidence": evidence.id,
                        "input_digest": evidence.provenance.input_digest,
                        "resources": [a.resource.content_hash for a in evidence.artifacts],
                    }
                )
                return evidence
            finally:
                session.close()

    solved = run(
        ComputationRequest(
            project.id,
            project.revision,
            "foundation.math.linear_equations",
            "1",
            "spring:equations",
        )
    )
    solution = solved.artifacts[0].resource
    generated = run(
        ComputationRequest(
            project.id,
            project.revision,
            "code_visualizer.python",
            "2",
            configuration=(ComputationParameter("timeout_seconds", 120),),
            inputs=(
                ResourceInput(
                    "solution",
                    solution,
                    ResourceLogicalTypeReference("foundation.math.equation_solution", "1"),
                ),
            ),
            outputs=(
                ResourceOutput(
                    "solid", BREP, tuple(s.id for s in program_statements(project.program_model))
                ),
            ),
        )
    )
    geometry = generated.artifacts[0]
    measured = None
    mesh_error = None
    for concept in ("Measurement", "Tessellation", "RegionSelection", "GeometryInput"):
        with closing(ComputationService()) as service:
            session = ProjectSession.open(output, computations=service)
            try:
                kernel = session.kernel
                edit = prepare_consumer(
                    session.authority.snapshot(),
                    kernel.extensions,
                    generated,
                    geometry.id,
                    kernel.resource_store,
                    kernel.resource_store,
                    concept,
                )
                assert isinstance(
                    session.client.transaction(edit.commands, expected_revision=edit.revision),
                    CommandAccepted,
                )
                if concept == "GeometryInput":
                    assert isinstance(
                        session.client.submit(
                            SetDomainProperty(
                                edit.model_id,
                                edit.node_id,
                                identity(concept, "translate_x"),
                                quantity(0.01),
                            )
                        ),
                        CommandAccepted,
                    )
                request = edit.request(session.authority.snapshot())
                assert session.authority.snapshot().program_model == project.program_model
            finally:
                session.close()
        result = run(request)
        with closing(ComputationService()) as service:
            session = ProjectSession.open(output, computations=service)
            try:
                store = session.kernel.resource_store
                if concept == "Measurement":
                    measured = {o.label: o.value.magnitude for o in result.observations}
                    assert math.isclose(measured["extent_x"], 0.05, abs_tol=1e-8)
                    assert math.isclose(
                        measured["volume"],
                        0.05 * 0.02 * 0.01 - math.pi * 0.002**2 * 0.01,
                        abs_tol=1e-12,
                    )
                elif concept == "Tessellation":
                    mesh_ref = result.artifacts[0].resource
                    assert store.describe(mesh_ref).logical_type == MESH
                    mesh = decode_mesh(store.read(mesh_ref))
                    assert mesh.header.parent == geometry.resource
                    assert mesh.header.frame.unit.id == "foundation.units.si:millimeter"
                    # An independent analytic chord check, separate from exact BREP
                    # volume and the image: sample edges on the radius-2-mm wall.
                    errors = []
                    for indices in mesh.triangles:
                        points = [mesh.vertices[i] for i in indices]
                        if max(p[2] for p in points) - min(p[2] for p in points) < 1e-8:
                            continue
                        if all(abs(math.hypot(p[0] - 25, p[1] - 10) - 2) < 1e-8 for p in points):
                            for a, b in zip(points, points[1:] + points[:1], strict=True):
                                errors.append(
                                    abs(
                                        math.hypot((a[0] + b[0]) / 2 - 25, (a[1] + b[1]) / 2 - 10)
                                        - 2
                                    )
                                )
                    assert errors and max(errors) <= 0.05
                    assert mesh.header.tolerance == 0.05
                    mesh_error = {
                        "maximum_chord_error_mm": max(errors),
                        "declared_tolerance_mm": 0.05,
                        "samples": len(errors),
                    }
                elif concept == "GeometryInput":
                    meta, shape = decode_solid(store.read(result.artifacts[0].resource))
                    assert meta.parent == geometry.resource
                    assert math.isclose(shape.bounding_box().min.X, 10, abs_tol=1e-5)
                # The disposable terminal is portable; replay does not read project.json.
                plan = export_computation_plan(session.kernel, request)
                plan = computation_plan_from_proto(computation_plan_to_proto(plan))
                replay = run_computation_plan(plan, session.kernel.extensions, store)
                assert replay.outcome is ComputationOutcome.SUCCEEDED, replay.diagnostics
                assert store.verified_path(geometry.resource).is_file()
            finally:
                session.close()
    report = {
        "phase": "P4",
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "measurements_si": measured,
        "mesh_error": mesh_error,
        "steps": reports,
        "producer_replay": False,
        "native_source_factories": False,
        "portable_consumer_replay": True,
    }
    (output / "cad-proof.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--example", type=Path)
    options = parser.parse_args()
    sys.meta_path.insert(0, NoExampleFactories())
    print(json.dumps(prove(options.output.resolve(), example=options.example), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
