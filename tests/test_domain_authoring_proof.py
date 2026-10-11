"""A subprocess forbids every example-domain dependency during the from-blank proof."""

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.messages import CommandAccepted, CommandEnvelope
from code_visualizer.domain.project import Project
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.serialization import normalized_project_json

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "prove_domain_authoring.py"

_ISOLATED_PROOF = r"""
import importlib.abc
import runpy
import sys

source, script, output = sys.argv[1:]
sys.path.insert(0, source)

class NoExampleDomain(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        forbidden = (
            'code_visualizer.extensions.fsm',
            'code_visualizer.application.authored_examples',
            'code_visualizer.application.examples',
            'code_visualizer.application.project_factory',
            'code_visualizer.ui_qt',
            'PySide6',
        )
        if any(fullname == item or fullname.startswith(item + '.') for item in forbidden):
            raise AssertionError('Proof reached forbidden example/UI dependency: ' + fullname)
        return None

sys.meta_path.insert(0, NoExampleDomain())
sys.argv = [script, '--output', output]
runpy.run_path(script, run_name='__main__')
"""


@pytest.fixture(scope="module")
def proof_artifact(tmp_path_factory):
    output = tmp_path_factory.mktemp("from-blank-proof")
    result = subprocess.run(
        [sys.executable, "-I", "-c", _ISOLATED_PROOF, str(ROOT / "src"), str(SCRIPT), str(output)],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return output


def test_blank_authority_builds_and_executes_without_any_example_implementation(proof_artifact):
    report = json.loads((proof_artifact / "proof.json").read_text(encoding="utf-8"))
    assert report["passed"] and report["starts_blank"]
    assert report["host_bundles"] == ["code_visualizer.intentional", "code_visualizer.program"]
    assert report["authored_program_functions"] == 0
    assert report["derived_program_functions"] == 1
    assert report["stdout"] == "Engaged\nRest\nEngaged\n"
    assert report["deterministic_build"] and report["native_roundtrip"] and report["undo_redo"]
    highlighted = report["runtime_highlights"][0]
    assert highlighted["graph_state"] == highlighted["form_state"] == "proof:active"
    assert highlighted["graph_transition"] == highlighted["table_transition"] == "proof:activate"
    assert highlighted["generated_semantic_id"].startswith("derived:")
    assert {"proof:active", "proof:activate"} <= set(highlighted["origin_ids"])
    assert highlighted["project_revision"] == report["revision"]
    native = (proof_artifact / "project.json").read_text(encoding="utf-8")
    assert hashlib.sha256(native.encode("utf-8")).hexdigest() == report["canonical_project_sha256"]
    project = project_from_json(native)
    assert len(project.domain_workspace.models[0].nodes) == 5
    assert project.domain_workspace.schemas[0].bundle is None
    assert not project.domain_workspace.bundle_references
    assert not project.program_model.functions
    assert (proof_artifact / "generated" / "run_project.py").exists()
    assert (proof_artifact / "generated" / "project.origin-map.json").exists()


def test_recorded_normal_authority_commands_replay_to_the_exact_native_project(proof_artifact):
    commands = json.loads((proof_artifact / "commands.json").read_text(encoding="utf-8"))
    authority = ProjectAuthority(Project("proof:project", "Authority-authored toggle", ()))
    assert commands[0]["command_type"] == "domain.schema.put"
    assert commands[0]["payload"]["schema"]["concepts"] == []
    empty_model = next(item for item in commands if item["command_type"] == "domain.model.put")
    assert empty_model["payload"]["model"]["nodes"] == []
    assert sum(item["command_type"] == "domain.node.create" for item in commands) == 5
    for index, command in enumerate(commands):
        if command["command_type"] in {"undo", "redo"}:
            result = getattr(authority, command["command_type"])(
                actor_id="from-blank-proof",
                operation_id=f"replay:{index}",
                expected_revision=command["expected_revision"],
            )
        else:
            result = authority.execute(
                CommandEnvelope(
                    command["command_type"],
                    "from-blank-proof",
                    f"replay:{index}",
                    authority.snapshot().id,
                    command["expected_revision"],
                    command["payload"],
                )
            )
        assert isinstance(result, CommandAccepted), result
    native = (proof_artifact / "project.json").read_text(encoding="utf-8")
    assert normalized_project_json(authority.snapshot()) == native


def test_proof_refuses_to_overwrite_existing_files(proof_artifact):
    before = (proof_artifact / "project.json").read_bytes()
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            _ISOLATED_PROOF,
            str(ROOT / "src"),
            str(SCRIPT),
            str(proof_artifact),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode != 0 and "new or empty" in result.stderr
    assert (proof_artifact / "project.json").read_bytes() == before


def test_archive_verifier_recreates_extracted_proof_and_rejects_changed_generation(
    proof_artifact, tmp_path
):
    extracted = tmp_path / "extracted"
    shutil.copytree(ROOT / "src", extracted / "src", ignore=shutil.ignore_patterns("__pycache__"))
    tools = extracted / "tools"
    tools.mkdir()
    for name in ("verify_programmodel_archive.py", "prove_domain_authoring.py"):
        shutil.copyfile(ROOT / "tools" / name, tools / name)
    shipped = extracted / "examples" / "proofs" / "authority-authored-toggle"
    shutil.copytree(
        proof_artifact, shipped, ignore=shutil.ignore_patterns(".code-visualizer", "__pycache__")
    )
    command = [
        sys.executable,
        "-I",
        "-B",
        str(tools / "verify_programmodel_archive.py"),
        "--verify-domain-proof",
        str(extracted),
    ]
    result = subprocess.run(
        command, cwd=extracted, capture_output=True, text=True, timeout=60, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "domain_proof=passed" in result.stdout
    assert "runtime_origins=graph,table,form" in result.stdout
    launcher = shipped / "generated" / "run_project.py"
    launcher.write_text(
        launcher.read_text(encoding="utf-8") + "\nprint('corrupted artifact')\n", encoding="utf-8"
    )
    changed = subprocess.run(
        command, cwd=extracted, capture_output=True, text=True, timeout=60, check=False
    )
    assert changed.returncode != 0
    assert "Independent proof generated artifacts differ" in changed.stderr
