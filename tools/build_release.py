"""Build and smoke-test cross-platform PyInstaller onedir bundles."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import platform
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]

_GUI_COMPUTATION_SMOKE = dedent(
    """\
    import json
    import sys
    from pathlib import Path

    from code_visualizer.application.authority import ProjectAuthority
    from code_visualizer.application.computation import execute_computation
    from code_visualizer.application.kernel import ProjectKernel
    from code_visualizer.domain.computation import ComputationRequest
    from code_visualizer.domain.evidence import ComputationOutcome
    from code_visualizer.persistence.decoding import project_from_data
    from code_visualizer.persistence.evidence import evidence_to_data
    from code_visualizer.persistence.evidence_store import EvidenceStore
    from code_visualizer.persistence.resource_store import ResourceStore

    root = Path(sys.argv[1])
    project = project_from_data(json.loads((root / 'project.json').read_text(encoding='utf-8')))
    kernel = ProjectKernel(
        ProjectAuthority(project),
        resource_store=ResourceStore(root),
        evidence_store=EvidenceStore(root),
    )
    try:
        evidence = execute_computation(
            kernel,
            ComputationRequest(project.id, project.revision, sys.argv[2], '1', sys.argv[3] or None),
        )
    finally:
        kernel.close()
    print(json.dumps(evidence_to_data(evidence), ensure_ascii=True, sort_keys=True, indent=2))
    raise SystemExit(0 if evidence.outcome is ComputationOutcome.SUCCEEDED else 2)
    """
)


def _run_pyinstaller(
    entry: Path,
    name: str,
    *,
    console: bool,
    dist_root: Path,
    work_root: Path,
) -> None:
    sdk = work_root / "python-sdk" / "code_visualizer"
    source_package = ROOT / "src" / "code_visualizer"
    for source in source_package.rglob("*.py"):
        target = sdk / source.relative_to(source_package)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    presentation_flags = ["--console"] if console else ["--windowed"]
    if not console and os.name == "nt":
        # Some enterprise WDAC policies reject PyInstaller's runw.exe while
        # allowing the equivalent run.exe bootloader. It can hide its own
        # console before Python starts, preserving a normal GUI experience.
        presentation_flags = ["--console", "--hide-console", "hide-early"]
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        *presentation_flags,
        "--noupx",
        "--name",
        name,
        "--paths",
        str(ROOT / "src"),
        "--collect-data",
        "code_visualizer",
        # Configured external Python also needs the typed publication SDK.
        # Internal frozen workers continue to import their bundled implementation.
        "--add-data",
        f"{sdk}{os.pathsep}code_visualizer",
        *(
            [
                "--collect-all",
                "build123d",
                "--collect-all",
                "OCP",
                "--recursive-copy-metadata",
                "build123d",
                "--copy-metadata",
                "cadquery-ocp-novtk",
            ]
            if importlib.util.find_spec("build123d") is not None
            else []
        ),
        # Configured external interpreters need the same stdlib-only workers as
        # source installs; PyInstaller's data collection excludes Python files.
        *[
            argument
            for filename in ("debug_worker.py", "_project_imports.py")
            for argument in (
                "--add-data",
                f"{ROOT / 'src' / 'code_visualizer' / 'execution' / filename}"
                f"{os.pathsep}code_visualizer/execution",
            )
        ],
        "--distpath",
        str(dist_root),
        "--workpath",
        str(work_root / name),
        "--specpath",
        str(work_root / "specs"),
        str(entry),
    ]
    subprocess.run(command, cwd=ROOT, check=True)


def _collect_cad_libraries(bundle: Path) -> None:
    """Retain libraries opened through ctypes, which static imports cannot find."""
    if importlib.util.find_spec("build123d") is None:
        return
    from PyInstaller.utils.hooks import collect_dynamic_libs

    internal = (bundle / "_internal").resolve()
    if not internal.is_relative_to((ROOT / "artifacts").resolve()):
        raise ValueError("Native runtime collection must stay inside release artifacts")
    libraries = collect_dynamic_libs("lib3mf")
    if not libraries:
        raise RuntimeError("The installed CAD dependency lib3mf has no native library")
    for filename, directory in libraries:
        source = Path(filename)
        target = (internal / directory / source.name).resolve()
        if not target.is_relative_to(internal):
            raise ValueError("A native dependency destination escaped its bundle")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        print(
            f"native_runtime_library={target} "
            f"sha256={hashlib.sha256(target.read_bytes()).hexdigest()}",
            flush=True,
        )


def _executable(bundle: Path, name: str) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return bundle / f"{name}{suffix}"


def _verify_computation_evidence(payload: str, project: Path, backend: str) -> str:
    """Reopen frozen-process output through the same versioned persistence contracts."""
    from code_visualizer.domain.evidence import ComputationOutcome
    from code_visualizer.domain.resources import ResourceLogicalTypeReference
    from code_visualizer.domain.values import QuantityValue, TensorDType, TensorValue
    from code_visualizer.execution.backends import resource_references
    from code_visualizer.persistence.evidence import evidence_from_data
    from code_visualizer.persistence.evidence_store import EvidenceStore
    from code_visualizer.persistence.resource_store import ResourceStore

    canonical = json.loads((project / "project.json").read_text(encoding="utf-8"))
    evidence = evidence_from_data(json.loads(payload))
    provenance = evidence.provenance
    if (
        evidence.outcome is not ComputationOutcome.SUCCEEDED
        or evidence.diagnostics
        or (provenance.backend_id, provenance.backend_version) != (backend, "1")
        or (provenance.project_id, provenance.revision)
        != (canonical["project_id"], canonical["revision"])
        or provenance.terminal_resource is None
    ):
        raise RuntimeError(f"Frozen computation returned invalid evidence: {evidence}")
    if EvidenceStore(project).get(evidence.id) != evidence:
        raise RuntimeError("Frozen computation receipt differs from its durable evidence")
    resources = ResourceStore(project)
    for reference in resource_references(evidence):
        resources.read(reference)  # Checks immutable descriptor and content hashes after exit.
    if backend == "code_visualizer.python":
        stdout = [item.value for item in evidence.observations if item.id == "python:stdout"]
        if stdout != ["Hello, world!\n"]:
            raise RuntimeError(f"Frozen Python computation returned stdout {stdout!r}")
    elif backend == "foundation.math.indexed_equations":
        expected = TensorValue(TensorDType.FLOAT64, (2, 2), (19.0, 22.0, 43.0, 50.0))
        if (
            len(evidence.observations) != 1
            or evidence.observations[0].value != expected
            or "matrix:equation" not in evidence.observations[0].semantic_ids
            or len(evidence.artifacts) != 1
        ):
            raise RuntimeError("Frozen math computation lost its tensor or semantic origins")
        reference = evidence.artifacts[0].resource
        descriptor = resources.describe(reference)
        if (
            descriptor.logical_type != ResourceLogicalTypeReference("foundation.math.tensor", "1")
            or descriptor.tensor is None
            or descriptor.tensor.dtype is not TensorDType.FLOAT64
            or descriptor.tensor.shape != (2, 2)
            or struct.unpack("<4d", resources.read(reference)) != expected.elements
        ):
            raise RuntimeError("Frozen math artifact differs from its typed tensor observation")
    elif backend == "foundation.math.linear_equations":
        from code_visualizer.domain.transformation import derived_id
        from code_visualizer.extensions.dc import TRANSFORMATION

        source_model = provenance.source_model_id
        observation_id, expected, origin = (
            (
                derived_id(TRANSFORMATION.key, "dc:middle", "potential") + ":solution",
                2.5,
                "dc:middle",
            )
            if source_model == "dc:network"
            else ("spring:x:solution", 0.05, "spring:x")
        )
        observation = next(item for item in evidence.observations if item.id == observation_id)
        if (
            not isinstance(observation.value, QuantityValue)
            or not isinstance(observation.value.magnitude, (int, float))
            or not math.isclose(observation.value.magnitude, expected, rel_tol=1e-10, abs_tol=1e-12)
            or origin not in provenance.origins.sources(observation.semantic_ids[0])
        ):
            raise RuntimeError("Frozen physical computation lost its value, unit or origin")
        report = json.loads(resources.read(evidence.artifacts[0].resource))
        if max(abs(item["normalized"]) for item in report["residuals"]) > 1e-10:
            raise RuntimeError("Frozen physical computation has an excessive normalized residual")
    else:
        raise ValueError(f"No release computation proof for backend {backend!r}")
    return evidence.id


def _smoke_computations(
    cli: Path,
    gui: Path,
    *,
    additional_cases: tuple[tuple[str, Path, str, str, str | None], ...] = (),
) -> None:
    """Exercise both real frozen entries, managed Python and the generic worker protocol."""
    parent = ROOT / "artifacts" / "release"
    parent.mkdir(parents=True, exist_ok=True)
    cases = (
        ("cli-python", cli, "projects/01-hello-world", "code_visualizer.python", None),
        (
            "cli-math",
            cli,
            "proofs/foundation-math",
            "foundation.math.indexed_equations",
            "matrix:model",
        ),
        (
            "gui-math",
            gui,
            "proofs/foundation-math",
            "foundation.math.indexed_equations",
            "matrix:model",
        ),
        *additional_cases,
    )
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    with TemporaryDirectory(prefix=".frozen-computation-smoke-", dir=parent) as temporary:
        for name, executable, example, backend, model in cases:
            project = Path(temporary) / name
            project.mkdir()
            canonical = (ROOT / "examples" / example / "project.json").read_bytes()
            target = project / "project.json"
            target.write_bytes(canonical)
            # No checked-in terminal, result, generated files or evidence are copied.
            arguments = ["compute", str(project), "--backend", backend]
            if model is not None:
                arguments.extend(("--model", model))
            command = [str(executable), *arguments]
            if name.startswith("gui-"):
                # The existing trusted adapter keeps sys.executable on the GUI
                # binary, so its preparation and execution children must reach
                # the GUI's fixed computation dispatch before Qt startup. Use
                # its bundled application API; the CLI is a separate frontend.
                command = [
                    str(executable),
                    "--code-visualizer-internal-python",
                    "-I",
                    "-c",
                    _GUI_COMPUTATION_SMOKE,
                    str(project),
                    backend,
                    model or "",
                ]
            try:
                result = subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    cwd=project,
                    env=environment,
                    timeout=120,
                )
                identity = _verify_computation_evidence(result.stdout, project, backend)
            except subprocess.CalledProcessError as exc:
                raise RuntimeError(
                    f"Frozen {name} failed with exit code {exc.returncode}\n"
                    f"stdout:\n{exc.stdout or ''}\nstderr:\n{exc.stderr or ''}"
                ) from exc
            finally:
                if target.read_bytes() != canonical:
                    raise RuntimeError(f"Frozen {name} mutated its canonical project input")
            print(f"frozen_computation={name} evidence={identity} resources=verified")


def _smoke_resource_proof(
    cli: Path,
    gui: Path,
    dependency: str,
    tool: str,
    phase: str,
    *,
    options: dict[str, object] | None = None,
) -> None:
    if importlib.util.find_spec(dependency) is None:
        return
    code = """import json, runpy, sys
from pathlib import Path
scope = runpy.run_path(sys.argv[1])
sys.meta_path.insert(0, scope['NoExampleFactories']())
report = scope['prove'](Path(sys.argv[2]), **json.loads(sys.argv[3]))
bundle = Path(sys._MEIPASS).resolve()
for name, module in tuple(sys.modules.items()):
    path = getattr(module, '__file__', None)
    if name.startswith('code_visualizer') and path:
        assert Path(path).resolve().is_relative_to(bundle), (name, path)
print(json.dumps(report, sort_keys=True))
"""
    for label, executable in (("cli", cli), ("gui", gui)):
        with TemporaryDirectory(prefix=f"cv-frozen-{phase.lower()}-") as directory:
            result = subprocess.run(
                [
                    str(executable),
                    "--code-visualizer-internal-python",
                    "-I",
                    "-c",
                    code,
                    str(ROOT / "tools" / tool),
                    str(Path(directory) / "proof"),
                    json.dumps(options or {}),
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=300,
            )
            if result.returncode:
                raise RuntimeError(
                    f"Frozen {phase} {label} exited {result.returncode}:\n"
                    f"{result.stdout}\n{result.stderr}"
                )
            report = json.loads(result.stdout)
            if report.get("phase") != phase or not report.get("portable_consumer_replay"):
                raise RuntimeError(f"Frozen {phase} proof was incomplete: {report}")
            print(
                f"frozen_{phase.lower()}={label} {json.dumps(report, sort_keys=True)}", flush=True
            )


def _smoke(dist_root: Path) -> None:
    cli = _executable(dist_root / "code-visualizer", "code-visualizer")
    gui = _executable(dist_root / "code-visualizer-gui", "code-visualizer-gui")
    subprocess.run([str(cli), "--version"], check=True, timeout=60)
    worker = subprocess.run(
        [
            str(cli),
            "--code-visualizer-internal-python",
            "-I",
            "-B",
            "-c",
            "print('frozen child ok')",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if worker.stdout.strip() != "frozen child ok":
        raise RuntimeError(f"Frozen child smoke returned {worker.stdout!r}")
    subprocess.run(
        [
            str(gui),
            "--code-visualizer-internal-python",
            "-I",
            "-B",
            "-c",
            "pass",
        ],
        check=True,
        timeout=60,
    )
    hello = subprocess.run(
        [str(cli), "run", str(ROOT / "examples" / "projects" / "01-hello-world")],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if hello.stdout.strip() != "Hello, world!":
        raise RuntimeError(f"Packaged Hello World returned {hello.stdout!r}")
    _smoke_computations(
        cli,
        gui,
        additional_cases=(
            (
                "cli-dc",
                cli,
                "physical/dc-divider",
                "foundation.math.linear_equations",
                "dc:network",
            ),
            (
                "gui-spring",
                gui,
                "physical/spring-equation",
                "foundation.math.linear_equations",
                "spring:equations",
            ),
        ),
    )
    _smoke_resource_proof(cli, gui, "build123d", "prove_cad_artifacts.py", "P4")
    _smoke_resource_proof(cli, gui, "scipy", "prove_field_history.py", "P5")
    _smoke_resource_proof(cli, gui, "build123d", "prove_coupled_physics.py", "P6")
    _smoke_resource_proof(cli, gui, "scipy", "prove_adaptive_physics.py", "P7-continuum")
    if sys.platform == "win32":
        _smoke_resource_proof(
            cli, gui, "scipy", "prove_hybrid_gas.py", "P7-gas", options={"smoke": True}
        )
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    subprocess.run(
        [str(gui), "--offscreen", "--smoke-test"],
        check=True,
        timeout=90,
        env=environment,
    )


def _manifest(dist_root: Path) -> Path:
    files: list[dict[str, object]] = []
    for path in sorted(item for item in dist_root.rglob("*") if item.is_file()):
        files.append(
            {
                "path": path.relative_to(dist_root).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size": path.stat().st_size,
            }
        )
    target = dist_root / "build-manifest.json"
    target.write_text(
        json.dumps(
            {
                "files": files,
                "platform": platform.platform(),
                "python": platform.python_version(),
                "schema_version": 1,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dist-root",
        type=Path,
        default=ROOT / "artifacts" / "release" / platform.system().casefold(),
    )
    parser.add_argument("--work-root", type=Path, default=ROOT / "build" / "pyinstaller")
    parser.add_argument("--no-smoke", action="store_true")
    parser.add_argument(
        "--smoke-existing",
        action="store_true",
        help="smoke and manifest an already-built/signed bundle without rebuilding it",
    )
    args = parser.parse_args()
    dist_root = args.dist_root.resolve()
    work_root = args.work_root.resolve()
    artifact_root = (ROOT / "artifacts").resolve()
    if artifact_root not in dist_root.parents:
        raise SystemExit(f"Release output must remain beneath {artifact_root}")
    unverified = dist_root / "UNVERIFIED.txt"
    if args.smoke_existing:
        if not dist_root.is_dir():
            raise SystemExit(f"No existing release bundle at {dist_root}")
        _smoke(dist_root)
        unverified.unlink(missing_ok=True)
        manifest = _manifest(dist_root)
        print(f"release={dist_root} manifest={manifest}")
        return 0
    if dist_root.exists():
        shutil.rmtree(dist_root)
    dist_root.mkdir(parents=True)
    work_root.mkdir(parents=True, exist_ok=True)
    _run_pyinstaller(
        ROOT / "packaging" / "cli_entry.py",
        "code-visualizer",
        console=True,
        dist_root=dist_root,
        work_root=work_root,
    )
    _collect_cad_libraries(dist_root / "code-visualizer")
    _run_pyinstaller(
        ROOT / "packaging" / "gui_entry.py",
        "code-visualizer-gui",
        console=False,
        dist_root=dist_root,
        work_root=work_root,
    )
    _collect_cad_libraries(dist_root / "code-visualizer-gui")
    if not args.no_smoke:
        try:
            _smoke(dist_root)
        except OSError as exc:
            if os.name != "nt" or getattr(exc, "winerror", None) != 4551:
                raise
            message = (
                "Windows Application Control blocked the unsigned native bundle "
                "(WinError 4551). No release manifest was promoted. Sign both "
                "executables with the organization's trusted code-signing credential, "
                "then run tools/build_release.py --smoke-existing."
            )
            unverified.write_text(message + "\n", encoding="utf-8")
            print(message, file=sys.stderr)
            return 3
    manifest = _manifest(dist_root)
    print(f"release={dist_root} manifest={manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
