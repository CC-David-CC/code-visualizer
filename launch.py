"""One-command source-folder bootstrap and launcher."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MINIMUM_PYTHON = (3, 12)


def _runtime_python(runtime: Path) -> Path:
    if sys.platform == "win32":
        return runtime / "Scripts" / "python.exe"
    return runtime / "bin" / "python"


def _fingerprint(requirements: Path, wheels: Path) -> str:
    digest = hashlib.sha256(requirements.read_bytes())
    if wheels.is_dir():
        for wheel in sorted(wheels.glob("*.whl")):
            digest.update(wheel.name.encode("utf-8"))
            digest.update(hashlib.sha256(wheel.read_bytes()).digest())
    return digest.hexdigest()


def _ensure_runtime(
    runtime: Path,
    *,
    online: bool,
    configured_python: Path | None,
) -> Path:
    python = configured_python
    if python is None:
        python = _runtime_python(runtime)
        if not python.is_file():
            runtime.parent.mkdir(parents=True, exist_ok=True)
            venv.EnvBuilder(with_pip=True, clear=False).create(runtime)
    if not python.is_file():
        raise SystemExit(f"Runtime Python does not exist: {python}")
    requirements = ROOT / "requirements.txt"
    wheels = ROOT / "wheels"
    stamp = runtime / ".code-visualizer-requirements"
    expected = _fingerprint(requirements, wheels)
    if (
        configured_python is None
        and stamp.is_file()
        and stamp.read_text(encoding="utf-8").strip() == expected
    ):
        return python
    command = [
        str(python),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
    ]
    if wheels.is_dir() and not online:
        command.extend(["--no-index", "--find-links", str(wheels)])
    command.extend(["-r", str(requirements)])
    subprocess.run(command, cwd=ROOT, check=True)
    if configured_python is None:
        stamp.write_text(expected + "\n", encoding="utf-8")
    return python


def _run_application(python: Path, *, cli: bool, arguments: list[str]) -> int:
    module = "code_visualizer.cli" if cli else "code_visualizer.ui_qt.app"
    bootstrap = (
        "import sys; "
        f"sys.path.insert(0, {str(ROOT / 'src')!r}); "
        f"from {module} import main; "
        "raise SystemExit(main())"
    )
    result = subprocess.run(
        [str(python), "-I", "-B", "-c", bootstrap, *arguments],
        cwd=ROOT,
        check=False,
    )
    return result.returncode


def main(arguments: list[str] | None = None) -> int:
    if sys.version_info < MINIMUM_PYTHON:
        required = ".".join(str(item) for item in MINIMUM_PYTHON)
        raise SystemExit(f"Code Visualizer requires Python {required} or newer")
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--cli", action="store_true")
    parser.add_argument("--launcher-help", action="store_true")
    parser.add_argument("--no-install", action="store_true")
    parser.add_argument("--online", action="store_true")
    development_runtime = ROOT / ".venv"
    default_runtime = (
        development_runtime if _runtime_python(development_runtime).is_file() else ROOT / ".runtime"
    )
    parser.add_argument("--runtime-dir", type=Path, default=default_runtime)
    parser.add_argument("--runtime-python", type=Path)
    options, application_arguments = parser.parse_known_args(arguments)
    if options.launcher_help:
        print(
            "Usage: python launch.py [launcher options] [application options]\n"
            "\n"
            "Launcher options:\n"
            "  --cli                 run the command-line interface\n"
            "  --online              allow dependency download instead of local wheels\n"
            "  --no-install          skip dependency setup\n"
            "  --runtime-dir PATH    choose the local environment directory\n"
            "  --runtime-python PATH use an existing interpreter\n"
            "  --launcher-help       show this help\n"
            "\n"
            "Examples:\n"
            "  python launch.py\n"
            "  python launch.py --cli --help\n"
        )
        return 0
    runtime = options.runtime_dir.resolve()
    configured = options.runtime_python.resolve() if options.runtime_python else None
    if options.no_install:
        python = configured or _runtime_python(runtime)
        if not python.is_file():
            raise SystemExit(f"Runtime Python does not exist: {python}")
    else:
        python = _ensure_runtime(runtime, online=options.online, configured_python=configured)
    if application_arguments[:1] == ["--"]:
        application_arguments.pop(0)
    return _run_application(python, cli=options.cli, arguments=application_arguments)


if __name__ == "__main__":
    raise SystemExit(main())
