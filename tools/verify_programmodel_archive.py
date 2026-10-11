"""Verify a local source archive, its extracted launch, and every shipped example."""

from __future__ import annotations

import argparse
import hashlib
import importlib.abc
import importlib.util
import json
import os
import stat
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path, PurePosixPath
from uuid import uuid4
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {
    "__pycache__",
    ".code-visualizer",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    ".runtime",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _relative_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    _require(
        bool(name)
        and not path.is_absolute()
        and path.as_posix() == name
        and all(part not in {".", ".."} for part in path.parts)
        and "\\" not in name
        and ":" not in name,
        f"Unsafe or noncanonical archive path: {name!r}",
    )
    return path


def _workspace_payload() -> dict[str, bytes]:
    """Use the same explicit source selection as the archive builder."""

    specification = importlib.util.spec_from_file_location(
        "programmodel_archive_builder", ROOT / "tools" / "build_programmodel_archive.py"
    )
    _require(specification is not None and specification.loader is not None, "Builder is missing")
    assert specification is not None and specification.loader is not None
    builder = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(builder)
    payload = {
        path.relative_to(ROOT).as_posix(): path.read_bytes() for path in builder.source_files()
    }
    payload["START_HERE.md"] = builder.START_HERE.encode("utf-8")
    return payload


def verify_and_extract(
    archive_path: Path,
    extract_parent: Path,
    supplementary_archives: tuple[Path, ...] = (),
) -> Path:
    """Validate every entry before extracting into a newly created local directory."""

    workspace = _workspace_payload()
    with ExitStack() as stack:
        archives = tuple(
            stack.enter_context(ZipFile(path)) for path in (archive_path, *supplementary_archives)
        )
        infos = tuple((archive, item) for archive in archives for item in archive.infolist())
        names = [item.filename for _archive, item in infos]
        _require(len(names) == len(set(names)), "Archive contains duplicate entry names")
        _require(
            len(names) == len({name.casefold() for name in names}),
            "Archive paths collide on Windows",
        )
        payload: dict[str, bytes] = {}
        for archive, item in infos:
            path = _relative_path(item.filename)
            _require(
                path.parts[0] == "programmodel" and len(path.parts) > 1, "Unexpected archive root"
            )
            _require(not item.is_dir(), "The source archive should contain file entries only")
            _require(not stat.S_ISLNK(item.external_attr >> 16), "Archive contains a symbolic link")
            relative = PurePosixPath(*path.parts[1:])
            _require(
                not EXCLUDED_PARTS.intersection(relative.parts),
                f"Runtime state in archive: {relative}",
            )
            _require(
                not any(
                    part.startswith(".test-") or part.endswith(".egg-info")
                    for part in relative.parts
                ),
                f"Scratch files in archive: {relative}",
            )
            _require(
                relative.parts[:2] != ("artifacts", "release"),
                "Historical release copied into archive",
            )
            payload[relative.as_posix()] = archive.read(item)
        _require(all(archive.testzip() is None for archive in archives), "Archive CRC check failed")

    manifest_bytes = payload.pop("source-manifest.json", None)
    _require(manifest_bytes is not None, "Source manifest is missing")
    assert manifest_bytes is not None
    manifest = json.loads(manifest_bytes)
    _require(
        isinstance(manifest, dict) and manifest.get("schema_version") == 1,
        "Unknown source manifest",
    )
    records = manifest.get("files")
    _require(isinstance(records, list), "Manifest file records are missing")
    seen: set[str] = set()
    for record in records:
        _require(isinstance(record, dict), "Malformed manifest record")
        name = record.get("path")
        _require(isinstance(name, str), "Manifest path must be text")
        _relative_path(name)
        _require(
            name not in seen and name in payload, f"Duplicate or missing manifest entry: {name}"
        )
        seen.add(name)
        content = payload[name]
        _require(
            type(record.get("size")) is int and record["size"] == len(content),
            f"Size mismatch: {name}",
        )
        _require(
            record.get("sha256") == hashlib.sha256(content).hexdigest(), f"SHA-256 mismatch: {name}"
        )
    _require(seen == set(payload), "Manifest does not cover every delivered file")
    _require(
        set(payload) == set(workspace), "Archive file set differs from current workspace delivery"
    )
    for name, content in payload.items():
        _require(content == workspace[name], f"Archive is stale relative to the workspace: {name}")

    destination = extract_parent.resolve() / f".test-archive-{uuid4().hex}"
    destination.mkdir(parents=True, exist_ok=False)
    extracted = destination / "programmodel"
    extracted.mkdir()
    payload["source-manifest.json"] = manifest_bytes
    for name, content in payload.items():
        target = extracted.joinpath(*PurePosixPath(name).parts).resolve()
        _require(target.is_relative_to(extracted), f"Extraction escaped its directory: {name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    print(f"manifest=passed files={len(payload)}", flush=True)
    print(f"extracted={extracted}", flush=True)
    return extracted


def _run(
    command: list[str], *, cwd: Path, timeout: float = 60.0
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {command!r}\n{result.stdout}\n{result.stderr}"
        )
    return result


def verify_launch(extracted: Path, runtime_python: Path) -> None:
    command = [
        str(runtime_python),
        str(extracted / "launch.py"),
        "--runtime-python",
        str(runtime_python),
        "--no-install",
    ]
    result = _run([*command, "--cli", "--version"], cwd=extracted)
    _require(
        result.stdout.strip() == "code-visualizer 0.1.0", "Extracted CLI version did not match"
    )
    print("launch_cli=passed", flush=True)
    _run([*command, "--offscreen", "--smoke-test"], cwd=extracted)
    print("launch_gui=passed", flush=True)


def _check_source_imports(source_root: Path) -> None:
    for name, module in tuple(sys.modules.items()):
        filename = getattr(module, "__file__", None)
        if name.startswith("code_visualizer.") and filename:
            _require(
                Path(filename).resolve().is_relative_to(source_root),
                f"Package import escaped extracted source: {name}",
            )


def verify_domain_proof(extracted: Path) -> None:
    """Re-create the shipped proof in a fresh process with example imports forbidden."""

    source_root = (extracted / "src").resolve()
    _require(
        not any(
            name == "code_visualizer" or name.startswith("code_visualizer.") for name in sys.modules
        ),
        "Independent proof requires a fresh interpreter",
    )

    class RejectExampleImports(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname: str, path: object = None, target: object = None) -> None:
            forbidden = (
                "code_visualizer.extensions.fsm",
                "code_visualizer.application.examples",
                "code_visualizer.application.authored_examples",
                "code_visualizer.application.project_factory",
                "code_visualizer.ui_qt",
                "PySide6",
            )
            if any(fullname == item or fullname.startswith(item + ".") for item in forbidden):
                raise ValueError(f"Independent proof imported an example or editor: {fullname}")
            return None

    blocker = RejectExampleImports()
    sys.meta_path.insert(0, blocker)
    sys.path.insert(0, str(source_root))
    try:
        script = extracted / "tools" / "prove_domain_authoring.py"
        specification = importlib.util.spec_from_file_location(
            "archive_domain_authoring_proof", script
        )
        _require(
            specification is not None and specification.loader is not None,
            "Proof script is missing",
        )
        assert specification is not None and specification.loader is not None
        proof = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(proof)
        reproduced = extracted / f".test-domain-proof-{uuid4().hex}"
        report = proof.run_proof(reproduced)
        shipped = extracted / "examples" / "proofs" / "authority-authored-toggle"
        # The fresh run performs typed edits, undo/redo, native round trips, generation,
        # actual execution, and simultaneous graph/table/form runtime-origin checks.
        _require(report.get("passed") is True, "Re-created authoring proof did not pass")
        _require(
            report.get("host_bundles")
            == ["code_visualizer.intentional", "code_visualizer.program"],
            "Independent proof used a domain implementation supplied by the host",
        )
        _require(bool(report.get("runtime_highlights")), "The proof has no runtime origin evidence")
        for name in ("project.json", "commands.json", "proof.json"):
            _require(
                (shipped / name).read_text(encoding="utf-8")
                == (reproduced / name).read_text(encoding="utf-8"),
                f"Independent proof re-creation mismatch: {name}",
            )

        def generated_payload(root: Path) -> dict[str, bytes]:
            return {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
                and "__pycache__" not in path.parts
                and path.suffix not in {".pyc", ".pyo"}
            }

        expected = generated_payload(reproduced / "generated")
        actual = generated_payload(shipped / "generated")
        _require(
            bool(expected) and actual == expected, "Independent proof generated artifacts differ"
        )
        _check_source_imports(source_root)
        print(
            "domain_proof=passed blank_authority=verified commands=reproduced "
            "example_imports=forbidden generation=matched execution=passed "
            "runtime_origins=graph,table,form",
            flush=True,
        )
    finally:
        sys.meta_path.remove(blocker)


def verify_foundation_proof(extracted: Path) -> None:
    """Reproduce binary worker plans, content resources and evidence from extracted code."""

    source_root = (extracted / "src").resolve()
    _require(
        not any(
            name == "code_visualizer" or name.startswith("code_visualizer.") for name in sys.modules
        ),
        "Foundation proof requires a fresh interpreter",
    )
    sys.path.insert(0, str(source_root))
    specification = importlib.util.spec_from_file_location(
        "archive_foundation_math_proof", extracted / "tools" / "prove_foundation_math.py"
    )
    _require(
        specification is not None and specification.loader is not None,
        "Foundation proof script is missing",
    )
    assert specification is not None and specification.loader is not None
    proof = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(proof)
    reproduced = extracted / f".test-foundation-proof-{uuid4().hex}"
    report = proof.prove(reproduced)
    _require(
        report.get("passed") is True
        and report.get("canonical_unchanged") is True
        and report.get("portable_worker_equal") is True
        and report.get("protobuf_roundtrip_equal") is True,
        "Foundation proof did not preserve canonical state and portable evidence",
    )
    _require(report.get("program_functions") == 0, "Foundation proof generated a program")
    _require(bool(report.get("origin_ids")), "Foundation proof lost intentional origins")
    _require(
        set(report.get("highlighted_notations", ())) == {"graph", "table", "tree_form"},
        "Foundation evidence did not decorate every notation",
    )
    shipped = extracted / "examples" / "proofs" / "foundation-math"
    reproduced_files = {
        path.relative_to(reproduced).as_posix(): path.read_bytes()
        for path in reproduced.rglob("*")
        if path.is_file() and not EXCLUDED_PARTS.intersection(path.relative_to(reproduced).parts)
    }
    _require(
        {"project.json", "plan.json", "plan.pb", "evidence.pb", "proof.json"}
        <= reproduced_files.keys(),
        "Foundation proof has incomplete interchange artifacts",
    )
    for name, content in reproduced_files.items():
        target = shipped / name
        _require(
            target.is_file() and target.read_bytes() == content,
            f"Foundation proof re-creation mismatch: {name}",
        )
    for directory in ("resources", "evidence"):
        actual = {
            path.relative_to(shipped).as_posix()
            for path in (shipped / directory).rglob("*")
            if path.is_file()
        }
        expected = {name for name in reproduced_files if name.startswith(directory + "/")}
        _require(actual == expected, f"Foundation {directory} artifact set differs")
    _check_source_imports(source_root)
    print(
        "foundation_proof=passed computation=python-adapter "
        "program_model=unused protobuf=round-trip "
        "worker_evidence=identical resources=matched runtime_origins=graph,table,form",
        flush=True,
    )


def verify_examples(extracted: Path, expected_examples: int) -> None:
    """Run only inside the isolated child whose import root is this extracted source."""

    source_root = extracted / "src"
    sys.path.insert(0, str(source_root))
    import code_visualizer.domain.program as program_module
    from code_visualizer.application.examples import EXAMPLE_CATALOG
    from code_visualizer.generation import expected_artifact_contents, generate_python_project
    from code_visualizer.persistence import ProjectStore
    from code_visualizer.validation import assess_project

    _require(
        Path(program_module.__file__).resolve().is_relative_to(source_root),
        "An installed or workspace package leaked into archive verification",
    )
    _require(
        len(EXAMPLE_CATALOG) == expected_examples,
        f"Expected {expected_examples} examples, found {len(EXAMPLE_CATALOG)}",
    )
    examples_root = extracted / "examples" / "projects"
    expected_directories = tuple(
        f"{index:02d}-{definition.id.replace('_', '-')}"
        for index, definition in enumerate(EXAMPLE_CATALOG, 1)
    )
    actual_directories = tuple(
        path.name
        for path in sorted(examples_root.iterdir())
        if path.is_dir() and (path / "project.json").is_file()
    )
    _require(
        actual_directories == expected_directories,
        "Shipped projects differ from the application catalog",
    )

    from dataclasses import replace

    for directory in expected_directories:
        project_root = examples_root / directory
        project = ProjectStore(project_root).recover(promote=False)
        assessment = assess_project(project)
        _require(
            not assessment.diagnostics,
            f"Example diagnostics: {directory}: {assessment.diagnostics!r}",
        )
        generated = generate_python_project(project)
        viewless = generate_python_project(replace(project, documents=(), drakon_views=()))
        _require(
            {item.path: item.source for item in generated.files}
            == {item.path: item.source for item in viewless.files},
            f"Views changed generated Python: {directory}",
        )
        expected = expected_artifact_contents(project, project_root=project_root)
        generated_root = project_root / "generated"
        actual_files = {
            path.relative_to(generated_root).as_posix()
            for path in generated_root.rglob("*")
            if path.is_file()
        }
        _require(actual_files == set(expected), f"Artifact file set mismatch: {directory}")
        for name, content in expected.items():
            _require(
                (generated_root / name).read_text(encoding="utf-8") == content,
                f"Regeneration mismatch: {directory}/{name}",
            )
        run_root = extracted / ".test-archive-runs" / directory
        run_root.mkdir(parents=True, exist_ok=False)
        for item in generated.files:
            target = run_root / item.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(item.source, encoding="utf-8", newline="\n")
        # Generated packages need the script directory in sys.path; -B avoids caches.
        _run([sys.executable, "-B", str(run_root / "run_project.py")], cwd=run_root, timeout=30)
        print(
            f"example={directory} validation=clean regeneration=matched "
            "viewless=matched execution=passed",
            flush=True,
        )
    _check_source_imports(source_root)
    print(f"examples=passed count={len(expected_directories)}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ROOT.parent / "programmodel.zip")
    parser.add_argument("--supplement", type=Path, action="append", default=[])
    parser.add_argument("--runtime-python", type=Path, default=Path(sys.executable))
    parser.add_argument("--extract-parent", type=Path, default=ROOT)
    parser.add_argument("--expected-examples", type=int, default=17)
    parser.add_argument("--verify-extracted", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--verify-domain-proof", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--verify-foundation-proof", type=Path, help=argparse.SUPPRESS)
    options = parser.parse_args()
    if options.verify_foundation_proof is not None:
        verify_foundation_proof(options.verify_foundation_proof.resolve())
        return 0
    if options.verify_domain_proof is not None:
        verify_domain_proof(options.verify_domain_proof.resolve())
        return 0
    if options.verify_extracted is not None:
        verify_examples(options.verify_extracted.resolve(), options.expected_examples)
        return 0
    archive = options.archive.resolve()
    runtime = options.runtime_python.resolve()
    extracted = verify_and_extract(archive, options.extract_parent, tuple(options.supplement))
    verify_launch(extracted, runtime)
    proof_result = _run(
        [
            str(runtime),
            "-I",
            "-B",
            str(extracted / "tools" / "verify_programmodel_archive.py"),
            "--verify-domain-proof",
            str(extracted),
        ],
        cwd=extracted,
        timeout=60,
    )
    print(proof_result.stdout, end="", flush=True)
    foundation_result = _run(
        [
            str(runtime),
            "-I",
            "-B",
            str(extracted / "tools" / "verify_programmodel_archive.py"),
            "--verify-foundation-proof",
            str(extracted),
        ],
        cwd=extracted,
        timeout=60,
    )
    print(foundation_result.stdout, end="", flush=True)
    physical_result = _run(
        [
            str(runtime),
            "-I",
            "-B",
            str(extracted / "tools" / "prove_physical_equations.py"),
            "--output",
            str(extracted / f".test-physical-proof-{uuid4().hex}"),
        ],
        cwd=extracted,
        timeout=120,
    )
    print(physical_result.stdout, end="", flush=True)
    cad_result = _run(
        [
            str(runtime),
            "-I",
            "-B",
            str(extracted / "tools" / "prove_cad_artifacts.py"),
            "--output",
            str(extracted / f".test-cad-proof-{uuid4().hex}"),
        ],
        cwd=extracted,
        timeout=300,
    )
    print(cad_result.stdout, end="", flush=True)
    field_result = _run(
        [
            str(runtime),
            "-I",
            "-B",
            str(extracted / "tools" / "prove_field_history.py"),
            "--output",
            str(extracted / f".test-field-proof-{uuid4().hex}"),
        ],
        cwd=extracted,
        timeout=120,
    )
    print(field_result.stdout, end="", flush=True)
    coupled_result = _run(
        [
            str(runtime),
            "-I",
            "-B",
            str(extracted / "tools" / "prove_coupled_physics.py"),
            "--output",
            str(extracted / f".test-coupled-proof-{uuid4().hex}"),
        ],
        cwd=extracted,
        timeout=300,
    )
    print(coupled_result.stdout, end="", flush=True)
    adaptive_result = _run(
        [
            str(runtime),
            "-I",
            "-B",
            str(extracted / "tools" / "prove_adaptive_physics.py"),
            "--output",
            str(extracted / f".test-adaptive-proof-{uuid4().hex}"),
        ],
        cwd=extracted,
        timeout=300,
    )
    print(adaptive_result.stdout, end="", flush=True)
    # This is the full saved gas horizon, distinct from the explicitly authored
    # short variant used by installation smoke checks. Throughput has a separate
    # budget; none of the GUI response-time gates is changed.
    gas_result = _run(
        [
            str(runtime),
            "-I",
            "-B",
            str(extracted / "tools" / "prove_hybrid_gas.py"),
            "--output",
            str(extracted / f".test-gas-proof-{uuid4().hex}"),
        ],
        cwd=extracted,
        timeout=10800,
    )
    print(gas_result.stdout, end="", flush=True)
    result = _run(
        [
            str(runtime),
            "-I",
            "-B",
            str(extracted / "tools" / "verify_programmodel_archive.py"),
            "--verify-extracted",
            str(extracted),
            "--expected-examples",
            str(options.expected_examples),
        ],
        cwd=extracted,
        timeout=60,
    )
    print(result.stdout, end="", flush=True)
    print(
        f"archive={archive}\nsha256={hashlib.sha256(archive.read_bytes()).hexdigest()}", flush=True
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
