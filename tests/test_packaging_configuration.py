import importlib.util
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_frozen_release_includes_standalone_workers_for_external_interpreters(
    monkeypatch, tmp_path
):
    specification = importlib.util.spec_from_file_location(
        "release_worker_test", ROOT / "tools" / "build_release.py"
    )
    assert specification is not None and specification.loader is not None
    release = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(release)
    commands = []
    monkeypatch.setattr(
        release.subprocess, "run", lambda command, **_kwargs: commands.append(command)
    )
    release._run_pyinstaller(
        ROOT / "src" / "code_visualizer" / "__main__.py",
        "test-release",
        console=True,
        dist_root=tmp_path / "dist",
        work_root=tmp_path / "work",
    )
    command = commands[0]
    data = [
        command[index + 1] for index, argument in enumerate(command) if argument == "--add-data"
    ]
    for filename in ("debug_worker.py", "_project_imports.py"):
        source = ROOT / "src" / "code_visualizer" / "execution" / filename
        assert source.is_file()
        assert f"{source}{os.pathsep}code_visualizer/execution" in data


def test_source_folder_release_and_ci_cover_windows_and_linux() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "quality.yml").read_text(encoding="utf-8")
    assert 'code-visualizer = "code_visualizer.cli:main"' in pyproject
    assert 'code-visualizer-gui = "code_visualizer.ui_qt.app:main"' in pyproject
    assert "windows-latest" in workflow
    assert "ubuntu-latest" in workflow
    assert "python tools/build_source_release.py --skip-download" in workflow
    assert (ROOT / "launch.py").is_file()
    assert (ROOT / "requirements.txt").is_file()
    assert (ROOT / "requirements-dev.txt").is_file()
    assert (ROOT / "tools" / "build_source_release.py").is_file()
    assert (ROOT / "packaging" / "SOURCE_FOLDER_README.md").is_file()


def test_release_documentation_covers_human_factors_safety_and_cutover() -> None:
    required = {
        "ACCESSIBILITY.md",
        "ARCHITECTURE.md",
        "AUTOMATION_API.md",
        "CUTOVER.md",
        "DECISIONS.md",
        "DRAKON_LOGIC.md",
        "GENERATION_AND_ARTIFACTS.md",
        "LIVE_TEST_AND_DEBUG.md",
        "PERFORMANCE.md",
        "PROVENANCE.md",
        "QUICKSTART.md",
        "REFERENCE_AUDIT.md",
        "SECURITY.md",
        "TEST_STRATEGY.md",
    }
    assert required <= {path.name for path in (ROOT / "docs").glob("*.md")}
    quickstart = (ROOT / "docs" / "QUICKSTART.md").read_text(encoding="utf-8")
    drakon_logic = (ROOT / "docs" / "DRAKON_LOGIC.md").read_text(encoding="utf-8")
    assert "Hello, world!" in quickstart
    assert "Ctrl+Shift+P" in quickstart
    for term in ("skewer", "liana", "valence", "happy path", "metre", "Shelf"):
        assert term.casefold() in drakon_logic.casefold()
