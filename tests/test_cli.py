import json

from code_visualizer.application.headless import HeadlessService
from code_visualizer.automation.host import LocalAutomationHost
from code_visualizer.cli import main
from code_visualizer.persistence import ProjectStore


def test_cli_creates_renames_and_recovers_project(tmp_path, capsys) -> None:
    root = tmp_path / "cli-project"

    assert main(["new", str(root), "--title", "CLI Project"]) == 0
    capsys.readouterr()

    assert main(["rename", str(root), "Renamed"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "accepted"
    assert result["revision"] == 1

    assert main(["show", str(root)]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["title"] == "Renamed"
    assert ProjectStore(root).recover().title == "Renamed"


def test_cli_validates_generates_runs_and_traces_without_gui(tmp_path, capsys) -> None:
    root = tmp_path / "cli-python"
    assert main(["new", str(root), "--title", "CLI Python"]) == 0
    project = json.loads(capsys.readouterr().out)
    diagram_id = project["documents"][0]["id"]

    assert (
        main(
            [
                "insert",
                str(root),
                diagram_id,
                "output",
                "--source",
                '"Hello from CLI"',
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["validate", str(root)]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "buildability": "buildable",
        "diagnostics": [],
    }

    assert main(["generate", str(root)]) == 0
    generated = json.loads(capsys.readouterr().out)
    assert generated["status"] == "complete"
    assert "app/main.py" in generated["files"]
    assert "run_project.py" in generated["files"]
    assert "project.py" not in generated["files"]

    assert main(["run", str(root)]) == 0
    assert capsys.readouterr().out == "Hello from CLI\n"

    assert main(["trace", str(root), diagram_id]) == 0
    traced = json.loads(capsys.readouterr().out)
    assert traced["return_code"] == 0
    assert traced["stdout"] == "Hello from CLI\n"
    assert traced["events"]


def test_cli_rpc_calls_the_live_semantic_authority(tmp_path, capsys, monkeypatch) -> None:
    root = tmp_path / "live-cli"
    assert main(["new", str(root)]) == 0
    capsys.readouterr()
    headless = HeadlessService.open(root)
    monkeypatch.setattr(
        "code_visualizer.automation.websocket.secrets.token_urlsafe",
        lambda _size: "-leading-hyphen-token",
    )
    host = LocalAutomationHost(headless.authority).start()
    assert host.token == "cvi_-leading-hyphen-token"
    params = json.dumps(
        {
            "command_type": "project.rename",
            "expected_revision": 0,
            "intent": "CLI live-authority test",
            "operation_id": "cli-live-rename",
            "payload": {"title": "Live CLI Project"},
        }
    )
    try:
        assert (
            main(
                [
                    "rpc",
                    host.endpoint,
                    "command.execute",
                    "--token",
                    host.token,
                    "--params",
                    params,
                ]
            )
            == 0
        )
        result = json.loads(capsys.readouterr().out)
        assert result["status"] == "accepted"
        assert headless.authority.snapshot().title == "Live CLI Project"
    finally:
        host.stop()
        headless.close()
