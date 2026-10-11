import json

import pytest

from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.drakon import If
from code_visualizer.execution import run_generated, run_project
from code_visualizer.generation import generate_python, generate_python_project
from code_visualizer.generation.artifacts import ArtifactGenerationError


def test_empty_main_generates_valid_pass_and_runs_in_memory() -> None:
    session = ProjectSession.new()
    try:
        generated = generate_python(session.authority.snapshot(), include_main=False)

        assert "def main():" in generated.source
        assert "    pass" in generated.source
        result = run_project(generate_python_project(session.authority.snapshot()))
        assert result.return_code == 0
        assert result.stderr == ""
    finally:
        session.close()


def test_hello_world_saves_generates_nonempty_manifest_and_runs(tmp_path) -> None:
    session = ProjectSession.new()
    try:
        project = session.authority.snapshot()
        main = project.documents[0]
        inserted = session.client.insert_drakon_atom(
            main.id,
            "output",
            0,
            source='"Hello, world!"',
        )
        assert isinstance(inserted, CommandAccepted)

        root = tmp_path / "hello-project"
        session.save_as(root)
        result = session.generate()

        assert session.authority.snapshot().title == "hello-project"
        assert result.root == root / "generated"
        assert (result.root / "app" / "main.py").is_file()
        manifest = json.loads((result.root / "generation.json").read_text(encoding="utf-8"))
        assert manifest["status"] == "complete"
        assert manifest["files"]
        run = run_generated(result.root / "run_project.py")
        assert run.return_code == 0
        assert run.stdout == "Hello, world!\n"
        assert not tuple(result.root.rglob("__pycache__"))
    finally:
        session.close()


def test_failed_generation_preserves_previous_complete_artifacts(tmp_path) -> None:
    session = ProjectSession.new()
    try:
        project = session.authority.snapshot()
        main = project.documents[0]
        session.client.insert_drakon_atom(main.id, "output", 0, source='"good"')
        root = tmp_path / "project"
        session.save_as(root)
        session.generate()
        previous = (root / "generated" / "app" / "main.py").read_text(encoding="utf-8")
        atom = session.authority.snapshot().documents[0].body.atoms[0]
        session.client.set_drakon_text(main.id, atom.id, "expression", "invalid(")

        with pytest.raises(ArtifactGenerationError):
            session.generate()

        assert (root / "generated" / "app" / "main.py").read_text(encoding="utf-8") == previous
    finally:
        session.close()


def test_generation_write_fsync_failure_preserves_previous_complete_set(
    monkeypatch, tmp_path
) -> None:
    session = ProjectSession.new()
    try:
        diagram = session.authority.snapshot().documents[0]
        session.client.insert_drakon_atom(diagram.id, "output", 0, source='"before"')
        root = tmp_path / "generation-fsync"
        session.save_as(root)
        session.generate()
        before = (root / "generated" / "app" / "main.py").read_bytes()
        atom = session.authority.snapshot().documents[0].body.atoms[0]
        session.client.set_drakon_text(diagram.id, atom.id, "expression", '"after"')

        monkeypatch.setattr(
            "code_visualizer.generation.artifacts.os.fsync",
            lambda _descriptor: (_ for _ in ()).throw(OSError("injected artifact fsync")),
        )
        with pytest.raises(ArtifactGenerationError, match="injected artifact fsync"):
            session.generate()

        assert (root / "generated" / "app" / "main.py").read_bytes() == before
        assert not tuple(root.glob(".generated-*.tmp"))
    finally:
        session.close()


def test_failed_generation_directory_swap_rolls_back_previous_complete_set(
    monkeypatch, tmp_path
) -> None:
    session = ProjectSession.new()
    try:
        diagram = session.authority.snapshot().documents[0]
        session.client.insert_drakon_atom(diagram.id, "output", 0, source='"before"')
        root = tmp_path / "generation-swap"
        session.save_as(root)
        session.generate()
        before = (root / "generated" / "app" / "main.py").read_bytes()
        atom = session.authority.snapshot().documents[0].body.atoms[0]
        session.client.set_drakon_text(diagram.id, atom.id, "expression", '"after"')

        from code_visualizer.generation import artifacts

        original_replace = artifacts.os.replace
        failed = False

        def fail_new_set_once(source, target) -> None:
            nonlocal failed
            source_path = str(source)
            if not failed and ".generated-" in source_path and str(target).endswith("generated"):
                failed = True
                raise OSError("injected promotion swap")
            original_replace(source, target)

        monkeypatch.setattr(artifacts.os, "replace", fail_new_set_once)
        with pytest.raises(ArtifactGenerationError, match="injected promotion swap"):
            session.generate()

        assert failed
        assert (root / "generated" / "app" / "main.py").read_bytes() == before
        assert not tuple(root.glob(".generated.backup-*"))
        assert not tuple(root.glob(".generated-*.tmp"))
    finally:
        session.close()


def test_structured_if_round_trips_generates_and_runs(tmp_path) -> None:
    session = ProjectSession.new()
    try:
        diagram = session.authority.snapshot().documents[0]
        result = session.client.insert_drakon_atom(diagram.id, "if", 0)
        assert isinstance(result, CommandAccepted)
        root = tmp_path / "structured-if"
        session.save_as(root)
        generated = session.generate()
        source = (generated.root / "app" / "main.py").read_text(encoding="utf-8")
        assert "if True:\n        print('true branch action')" in source

        reopened = ProjectSession.open(root, read_only=True)
        try:
            restored = reopened.authority.snapshot().documents[0].body.atoms[0]
            assert isinstance(restored, If)
            assert restored.true_branch.atoms[0].source == "print('true branch action')"
        finally:
            reopened.close()
    finally:
        session.close()
