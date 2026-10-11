"""Release checks reject stale, corrupted, or semantically wrong computation receipts."""

import builtins
import importlib.util
import json
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from code_visualizer.domain.values import TensorDType, TensorValue
from code_visualizer.persistence.evidence import (
    evidence_content_hash,
    evidence_from_data,
    evidence_to_data,
)
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def release():
    spec = importlib.util.spec_from_file_location("frozen_smoke", ROOT / "tools/build_release.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("mutates", [False, True])
def test_real_smoke_routes_both_entries_and_keeps_fresh_author_inputs(
    release, monkeypatch, tmp_path, mutates
):
    originals = {}
    for example in ("projects/01-hello-world", "proofs/foundation-math"):
        source = tmp_path / "examples" / example / "project.json"
        source.parent.mkdir(parents=True)
        source.write_text(json.dumps({"example": example}), encoding="utf-8")
        originals[source] = source.read_bytes()
    monkeypatch.setattr(release, "ROOT", tmp_path)
    commands = []
    checked = []

    def execute(command, **kwargs):
        commands.append(command)
        if command[1] == "--code-visualizer-internal-python":
            assert command[2:5] == ["-I", "-c", release._GUI_COMPUTATION_SMOKE]
            arguments = ["compute", command[5], "--backend", command[6], "--model", command[7]]
        else:
            arguments = command[1:]
        assert arguments[0] == "compute"
        project = Path(arguments[1])
        assert list(project.iterdir()) == [project / "project.json"]
        assert kwargs["cwd"] == project
        assert "PYTHONPATH" not in kwargs["env"]
        assert kwargs["check"] is True
        if mutates:
            (project / "project.json").write_text("changed", encoding="utf-8")
        return SimpleNamespace(stdout="frozen receipt")

    def verify(payload, project, backend):
        assert payload == "frozen receipt"
        checked.append((project.name, backend))
        return "evidence:checked"

    monkeypatch.setattr(release.subprocess, "run", execute)
    monkeypatch.setattr(release, "_verify_computation_evidence", verify)
    if mutates:
        with pytest.raises(RuntimeError, match="mutated its canonical"):
            release._smoke_computations(Path("cli.exe"), Path("gui.exe"))
    else:
        release._smoke_computations(Path("cli.exe"), Path("gui.exe"))
        assert [command[0] for command in commands] == ["cli.exe", "cli.exe", "gui.exe"]
        assert checked == [
            ("cli-python", "code_visualizer.python"),
            ("cli-math", "foundation.math.indexed_equations"),
            ("gui-math", "foundation.math.indexed_equations"),
        ]
    assert all(path.read_bytes() == source for path, source in originals.items())


@pytest.mark.parametrize("fails", [False, True])
def test_gui_smoke_uses_bundled_application_and_closes_its_kernel(
    release, monkeypatch, tmp_path, capsys, fails
):
    from code_visualizer.application import computation
    from code_visualizer.application.kernel import ProjectKernel
    from code_visualizer.domain.computation import ComputationRequest

    source = ROOT / "examples/proofs/foundation-math"
    canonical = (source / "project.json").read_bytes()
    (tmp_path / "project.json").write_bytes(canonical)
    identity = json.loads((source / "proof.json").read_text(encoding="utf-8"))["evidence_id"]
    evidence = EvidenceStore(source).get(identity)
    observed = []
    closed = []
    original_import = builtins.__import__
    original_close = ProjectKernel.close

    def import_bundled(name, *args, **kwargs):
        assert name != "code_visualizer.cli", "GUI smoke must not depend on the CLI frontend"
        return original_import(name, *args, **kwargs)

    def execute(kernel, request):
        project = kernel.authority.snapshot()
        assert request == ComputationRequest(
            project.id, project.revision, "foundation.math.indexed_equations", "1", "matrix:model"
        )
        assert kernel.resource_store.root == ResourceStore(tmp_path).root
        assert kernel.evidence_store.root == EvidenceStore(tmp_path).root
        observed.append(kernel)
        if fails:
            raise ValueError("computation admission failed")
        return evidence

    def close(kernel):
        closed.append(kernel)
        original_close(kernel)

    monkeypatch.setattr(builtins, "__import__", import_bundled)
    monkeypatch.setattr(computation, "execute_computation", execute)
    monkeypatch.setattr(ProjectKernel, "close", close)
    monkeypatch.setattr(
        sys,
        "argv",
        ["-c", str(tmp_path), "foundation.math.indexed_equations", "matrix:model"],
    )
    if fails:
        with pytest.raises(ValueError, match="computation admission failed"):
            exec(compile(release._GUI_COMPUTATION_SMOKE, "<frozen GUI smoke>", "exec"), {})
    else:
        with pytest.raises(SystemExit) as stopped:
            exec(compile(release._GUI_COMPUTATION_SMOKE, "<frozen GUI smoke>", "exec"), {})
        assert stopped.value.code == 0
        assert evidence_from_data(json.loads(capsys.readouterr().out)) == evidence
    assert len(observed) == 1 and closed == observed
    assert (tmp_path / "project.json").read_bytes() == canonical


def test_failed_frozen_smoke_reports_captured_stdout_and_stderr(release, monkeypatch, tmp_path):
    source = tmp_path / "examples/projects/01-hello-world/project.json"
    source.parent.mkdir(parents=True)
    source.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(release, "ROOT", tmp_path)

    def execute(command, **_kwargs):
        raise subprocess.CalledProcessError(
            1, command, output="partial frozen output", stderr="specific import failure"
        )

    monkeypatch.setattr(release.subprocess, "run", execute)
    with pytest.raises(RuntimeError, match="Frozen cli-python failed with exit code 1") as failure:
        release._smoke_computations(Path("cli.exe"), Path("gui.exe"))
    assert "partial frozen output" in str(failure.value)
    assert "specific import failure" in str(failure.value)
    assert source.read_text(encoding="utf-8") == "{}"


@pytest.mark.parametrize("damage", [None, "resource", "result"])
def test_smoke_reopens_evidence_and_checks_exact_math_and_immutable_resources(
    release, tmp_path, damage
):
    project = tmp_path / "math"
    shutil.copytree(ROOT / "examples/proofs/foundation-math", project)
    identity = json.loads((project / "proof.json").read_text(encoding="utf-8"))["evidence_id"]
    store = EvidenceStore(project)
    evidence = store.get(identity)
    if damage == "resource":
        output = ResourceStore(project).verified_path(evidence.artifacts[0].resource)
        output.write_bytes(b"x" * 32)
    elif damage == "result":
        observation = replace(
            evidence.observations[0],
            value=TensorValue(TensorDType.FLOAT64, (2, 2), (20.0, 22.0, 43.0, 50.0)),
        )
        evidence = replace(evidence, observations=(observation,))
        evidence = replace(evidence, id="evidence:" + evidence_content_hash(evidence))
        store.put(evidence)
    payload = json.dumps(evidence_to_data(evidence))
    assert evidence_from_data(json.loads(payload)) == evidence
    if damage is None:
        assert (
            release._verify_computation_evidence(
                payload, project, "foundation.math.indexed_equations"
            )
            == evidence.id
        )
    else:
        with pytest.raises((RuntimeError, ValueError), match=r"content|hash|tensor"):
            release._verify_computation_evidence(
                payload, project, "foundation.math.indexed_equations"
            )
