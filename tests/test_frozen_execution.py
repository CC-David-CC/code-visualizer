from __future__ import annotations

import sys
from pathlib import Path

import pytest

from code_visualizer.execution.child_process import (
    COMPUTATION_WORKER,
    DEBUG_WORKER,
    INTERNAL_PYTHON_WORKER,
    PROJECT_WORKER,
    computation_worker_command,
    debug_worker_command,
    dispatch_internal_worker,
    python_child_command,
)


def test_source_install_uses_active_python() -> None:
    assert python_child_command(["-I", "-c", "pass"]) == [
        sys.executable,
        "-I",
        "-c",
        "pass",
    ]


def test_frozen_install_routes_python_and_debug_through_private_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "studio.exe")

    assert python_child_command(["-I", "-B", "-c", "pass"]) == [
        "studio.exe",
        INTERNAL_PYTHON_WORKER,
        "-I",
        "-B",
        "-c",
        "pass",
    ]
    assert debug_worker_command(Path("debug_worker.py")) == [
        "studio.exe",
        INTERNAL_PYTHON_WORKER,
        DEBUG_WORKER,
    ]
    assert python_child_command(["-c", "pass"], interpreter=" custom-python ") == [
        "custom-python",
        "-c",
        "pass",
    ]


def test_internal_python_worker_executes_isolated_code(capsys: pytest.CaptureFixture[str]) -> None:
    result = dispatch_internal_worker(
        [INTERNAL_PYTHON_WORKER, "-I", "-B", "-c", "print('worker reached')"]
    )

    assert result == 0
    assert capsys.readouterr().out == "worker reached\n"


def test_internal_worker_ignores_normal_application_arguments() -> None:
    assert dispatch_internal_worker(["--version"]) is None


def test_computation_worker_uses_fixed_source_and_frozen_entries(monkeypatch):
    source = Path("trusted/computation_worker.py")
    assert computation_worker_command(source) == [sys.executable, "-I", str(source)]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "studio.exe")
    assert computation_worker_command(source) == [
        "studio.exe",
        INTERNAL_PYTHON_WORKER,
        COMPUTATION_WORKER,
    ]
    calls = []

    def trusted_entry():
        calls.append("trusted")
        return 17

    assert (
        dispatch_internal_worker(
            [INTERNAL_PYTHON_WORKER, COMPUTATION_WORKER], computation_worker=trusted_entry
        )
        == 17
    )
    assert calls == ["trusted"]
    with pytest.raises(SystemExit, match="No trusted computation worker"):
        dispatch_internal_worker([INTERNAL_PYTHON_WORKER, COMPUTATION_WORKER])


@pytest.mark.parametrize("entry", ["cli_entry.py", "gui_entry.py"])
def test_packaged_computation_entry_uses_trusted_composition_before_ui(entry, monkeypatch):
    import runpy

    from code_visualizer.application import computation_worker

    monkeypatch.setattr(computation_worker, "main", lambda: 23)
    monkeypatch.setattr(sys, "argv", ["studio.exe", INTERNAL_PYTHON_WORKER, COMPUTATION_WORKER])
    entrypoint = Path(__file__).resolve().parents[1] / "packaging" / entry
    with pytest.raises(SystemExit) as ended:
        runpy.run_path(str(entrypoint), run_name="__main__")
    assert ended.value.code == 23


def test_frozen_project_dispatch_hides_internal_arguments_and_restores_caller_argv(
    tmp_path, monkeypatch, capsys
):
    launcher = tmp_path / "run_project.py"
    launcher.write_text(
        "import sys\nfrom pathlib import Path\n"
        "print(sys.argv[1:])\nprint(Path(sys.argv[0]).name)\n",
        encoding="utf-8",
    )
    private_arguments = [INTERNAL_PYTHON_WORKER, PROJECT_WORKER, str(tmp_path), str(launcher)]
    original_argv = ["studio.exe", *private_arguments]
    monkeypatch.setattr(sys, "argv", original_argv)
    assert dispatch_internal_worker(private_arguments) == 0
    assert capsys.readouterr().out == "[]\nrun_project.py\n"
    assert sys.argv == original_argv
