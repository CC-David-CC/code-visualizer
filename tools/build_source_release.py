"""Build a complete source-folder release with an offline runtime wheelhouse."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from code_visualizer.generation import atomic_promote_directory

ROOT = Path(__file__).resolve().parents[1]
COPY_DIRECTORIES = (
    ".github",
    "assets",
    "docs",
    "examples",
    "packaging",
    "src",
    "tests",
    "tools",
)
COPY_FILES = (
    "launch.py",
    "pyproject.toml",
    "README.md",
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-science.txt",
    "requirements-cad.txt",
    "requirements-fields.txt",
    "requirements-fields.lock",
    "STATUS.md",
)


def _copy_source(stage: Path) -> None:
    for name in COPY_FILES:
        shutil.copy2(ROOT / name, stage / name)
    for name in COPY_DIRECTORIES:
        shutil.copytree(
            ROOT / name,
            stage / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
        )
    shutil.copy2(ROOT / "packaging" / "SOURCE_FOLDER_README.md", stage / "START_HERE.md")
    performance = stage / "artifacts" / "performance"
    performance.mkdir(parents=True)
    shutil.copy2(
        ROOT / "artifacts" / "performance" / "m9-scale-results.json",
        performance / "m9-scale-results.json",
    )


def _download_wheels(stage: Path) -> None:
    wheelhouse = stage / "wheels"
    wheelhouse.mkdir()
    for version in ("3.12", "3.13"):
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "download",
                "--disable-pip-version-check",
                "--only-binary=:all:",
                "--platform",
                "win_amd64",
                "--implementation",
                "cp",
                "--python-version",
                version,
                "--dest",
                str(wheelhouse),
                "-r",
                str(stage / "requirements-dev.txt"),
            ],
            cwd=stage,
            check=True,
        )
    built = sorted((ROOT / "artifacts" / "release" / "python").glob("code_visualizer-*.whl"))
    if len(built) != 1:
        raise RuntimeError(f"Expected one built Code Visualizer wheel, found {len(built)}")
    shutil.copy2(built[0], wheelhouse / built[0].name)


def _manifest(stage: Path) -> None:
    entries: list[dict[str, object]] = []
    for path in sorted(item for item in stage.rglob("*") if item.is_file()):
        entries.append(
            {
                "path": path.relative_to(stage).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size": path.stat().st_size,
            }
        )
    (stage / "source-release-manifest.json").write_text(
        json.dumps(
            {
                "files": entries,
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


def _smoke(release: Path, *, offline_install: bool) -> None:
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    smoke_root = ROOT / "build" / "source-folder-smoke"
    smoke_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=smoke_root) as temporary:
        if offline_install:
            common = [
                sys.executable,
                str(release / "launch.py"),
                "--runtime-dir",
                str(Path(temporary) / "runtime"),
            ]
        else:
            common = [
                sys.executable,
                str(release / "launch.py"),
                "--runtime-python",
                sys.executable,
                "--no-install",
            ]
        version = subprocess.run(
            [*common, "--cli", "--version"],
            cwd=release,
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        )
        output_lines = [line.strip() for line in version.stdout.splitlines() if line.strip()]
        if not output_lines or output_lines[-1] != "code-visualizer 0.1.0":
            raise RuntimeError(f"Source-folder CLI returned {version.stdout!r}")
        subprocess.run(
            [*common, "--offscreen", "--smoke-test"],
            cwd=release,
            check=True,
            env=environment,
            timeout=90,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts" / "release" / "source-folder",
    )
    parser.add_argument("--skip-download", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    artifact_root = (ROOT / "artifacts").resolve()
    if artifact_root not in output.parents:
        raise SystemExit(f"Release output must remain beneath {artifact_root}")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".source-folder-", dir=output.parent))
    try:
        _copy_source(stage)
        if not args.skip_download:
            _download_wheels(stage)
        _smoke(stage, offline_install=not args.skip_download)
        _manifest(stage)
        atomic_promote_directory(stage, output)
    except BaseException:
        if stage.exists():
            shutil.rmtree(stage)
        raise
    print(f"source_release={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
