import hashlib
import json

import pytest

from code_visualizer.application.examples import python_modules_session
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.python_pipeline import (
    DebouncedPythonPipeline,
    PipelineState,
)
from code_visualizer.application.session import ProjectSession
from code_visualizer.execution import run_generated, trace_project
from code_visualizer.generation import (
    generate_python_project,
    inspect_generation,
)
from code_visualizer.generation.artifacts import StaleGenerationError, generate_to_disk
from code_visualizer.generation.ir import FunctionIR
from code_visualizer.generation.lowering import lower_project
from code_visualizer.validation import Severity, validate_project


class _FakeCall:
    def __init__(self, callback) -> None:
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class _FakeScheduler:
    def __init__(self) -> None:
        self.calls: list[_FakeCall] = []

    def call_later(self, _delay_ms: int, callback) -> _FakeCall:
        call = _FakeCall(callback)
        self.calls.append(call)
        return call

    def run_pending(self) -> int:
        pending, self.calls = self.calls, []
        executed = 0
        for call in pending:
            if not call.cancelled:
                call.callback()
                executed += 1
        return executed


def test_generation_ir_uses_semantic_identity_with_optional_presentation() -> None:
    session = ProjectSession.new()
    try:
        assert isinstance(
            session.client.create_program_function(
                "headless_helper",
                function_id="function_headless_helper",
                symbol_id="symbol_headless_helper",
                body_sequence_id="sequence_headless_helper",
            ),
            CommandAccepted,
        )
        assert isinstance(
            session.client.insert_program_statement(
                "function_headless_helper",
                "sequence_headless_helper",
                0,
                "output",
                statement_id="output_headless_helper",
                expression='"canonical only"',
            ),
            CommandAccepted,
        )
        project = session.authority.snapshot()
        ir = lower_project(project)
        functions = {
            item.callable_id: item
            for module in ir.modules
            for item in module.body
            if isinstance(item, FunctionIR)
        }
        viewed_id = project.drakon_views[0].function_id
        viewed = functions[viewed_id]
        headless = functions["function_headless_helper"]

        assert viewed.signature_origin.semantic_id == viewed.callable_id
        assert viewed.presentation_id == project.drakon_views[0].document_id
        assert viewed.signature_origin.presentation_id == viewed.presentation_id
        assert headless.signature_origin.semantic_id == headless.callable_id
        assert headless.presentation_id is None
        assert headless.signature_origin.presentation_id is None

        generated = generate_python_project(project)
        signature = next(
            span
            for span in generated.spans
            if span.semantic_id == headless.callable_id and span.field == "signature"
        )
        output = next(
            span for span in generated.spans if span.semantic_id == "output_headless_helper"
        )
        assert signature.presentation_id is None
        assert output.presentation_id is None
    finally:
        session.close()


def test_typed_ir_emits_runs_and_maps_a_two_function_package(tmp_path) -> None:
    session = python_modules_session()
    try:
        project = session.authority.snapshot()
        assert not [item for item in validate_project(project) if item.severity is Severity.ERROR]
        first = generate_python_project(project)
        second = generate_python_project(project)
        assert first == second

        root = tmp_path / "module-project"
        session.save_as(root)
        result = session.generate()
        expected = {
            "studio_demo/__init__.py",
            "studio_demo/main.py",
            "studio_demo/helpers.py",
            "run_project.py",
            "project.source-map.json",
            "generation-report.json",
            "run-config.json",
            "generation.json",
        }
        relative = {path.relative_to(result.root).as_posix() for path in result.files}
        assert expected <= relative
        assert "project.py" not in relative

        manifest = json.loads(result.manifest.read_text(encoding="utf-8"))
        assert manifest["revision"] == session.authority.revision
        assert manifest["status"] == "complete"
        for path, digest in manifest["files"].items():
            assert hashlib.sha256((result.root / path).read_bytes()).hexdigest() == digest

        run = run_generated(result.root / "run_project.py")
        assert run.return_code == 0
        assert run.stdout == "Hello from two modules!\n"

        source_map = json.loads(
            (result.root / "project.source-map.json").read_text(encoding="utf-8")
        )
        assert source_map["version"] == 3
        map_ids = [item["map_id"] for item in source_map["spans"]]
        assert len(map_ids) == len(set(map_ids))
        main_atom = project.documents[0].body.atoms[0]
        owned = [item for item in source_map["spans"] if item["semantic_id"] == main_atom.id]
        assert owned
        for span in owned:
            assert span["presentation_id"] == project.documents[0].id
            assert "object_id" not in span
            assert "diagram_id" not in span
            source = (result.root / span["file_path"]).read_text(encoding="utf-8")
            lines = source.splitlines()
            assert span["start_line"] <= len(lines)
            assert "print" in "\n".join(lines[span["start_line"] - 1 : span["end_line"]])

        isolated = generate_python_project(
            project,
            focus_diagram_id=project.documents[0].id,
        )
        trace = trace_project(isolated)
        assert trace.run.return_code == 0
        assert trace.run.stdout == "Hello from two modules!\n"
        traced_locations = {(event.file_path, event.line) for event in trace.events}
        assert any(
            span.semantic_id == main_atom.id
            and any(
                span.file_path == path and span.start_line <= line <= span.end_line
                for path, line in traced_locations
            )
            for span in isolated.spans
        )
    finally:
        session.close()


def test_invalid_python_commits_as_diagnostic_and_blocks_generation(tmp_path) -> None:
    session = ProjectSession.new()
    try:
        main = session.authority.snapshot().documents[0]
        inserted = session.client.insert_drakon_atom(main.id, "output", 0, source='"valid"')
        assert isinstance(inserted, CommandAccepted)
        root = tmp_path / "editable-invalid"
        session.save_as(root)
        first = session.generate()
        previous = (first.root / "app/main.py").read_bytes()

        atom = session.authority.snapshot().documents[0].body.atoms[0]
        edited = session.client.set_drakon_text(main.id, atom.id, "expression", "broken(")
        assert isinstance(edited, CommandAccepted)
        diagnostics = validate_project(session.authority.snapshot())
        assert any(item.code == "PY_INVALID_EXPRESSION" for item in diagnostics)
        with pytest.raises(Exception, match="PROGRAM_INCOMPLETE_EXPRESSION"):
            session.generate()
        assert (first.root / "app/main.py").read_bytes() == previous
    finally:
        session.close()


def test_debounce_cancels_stale_jobs_and_preserves_prior_output_when_blocked(tmp_path) -> None:
    session = ProjectSession.new()
    statuses = []
    scheduler = _FakeScheduler()
    pipeline = DebouncedPythonPipeline(scheduler, listener=statuses.append)
    try:
        root = tmp_path / "debounced"
        session.save_as(root)
        pipeline.attach(session)
        main = session.authority.snapshot().documents[0]
        session.client.insert_drakon_atom(main.id, "output", 0, source='"first"')
        pipeline.project_changed()
        atom = session.authority.snapshot().documents[0].body.atoms[0]
        session.client.set_drakon_text(main.id, atom.id, "expression", '"latest"')
        pipeline.project_changed()

        assert not (root / "generated").exists()
        assert scheduler.run_pending() == 1
        manifest = json.loads((root / "generated" / "generation.json").read_text(encoding="utf-8"))
        latest_revision = session.authority.revision
        assert manifest["revision"] == latest_revision
        assert statuses[-1].state is PipelineState.UP_TO_DATE

        session.client.set_drakon_text(main.id, atom.id, "expression", "invalid(")
        pipeline.project_changed()
        assert scheduler.run_pending() == 1
        assert statuses[-1].state is PipelineState.BLOCKED
        preserved = json.loads((root / "generated" / "generation.json").read_text(encoding="utf-8"))
        assert preserved["revision"] == latest_revision
    finally:
        pipeline.cancel()
        session.close()


def test_stale_revision_cannot_promote_artifacts(tmp_path) -> None:
    session = ProjectSession.new()
    try:
        root = tmp_path / "stale"
        session.save_as(root)
        project = session.authority.snapshot()
        with pytest.raises(StaleGenerationError):
            generate_to_disk(
                project,
                root,
                current_revision=lambda: project.revision + 1,
            )
        assert not (root / "generated").exists()
    finally:
        session.close()


def test_external_artifact_changes_pause_debounce_until_explicit_generation(tmp_path) -> None:
    session = ProjectSession.new()
    statuses = []
    scheduler = _FakeScheduler()
    pipeline = DebouncedPythonPipeline(scheduler, listener=statuses.append)
    try:
        root = tmp_path / "external-change"
        session.save_as(root)
        pipeline.attach(session)
        assert pipeline.generate_now() is not None
        generated_file = root / "generated" / "app/main.py"
        generated_file.write_text("# external edit\n", encoding="utf-8")
        (root / "generated" / "notes.txt").write_text("keep me", encoding="utf-8")
        inspection = inspect_generation(root, current_revision=session.authority.revision)
        assert inspection.modified == ("app/main.py",)
        assert inspection.unexpected == ("notes.txt",)

        diagram = session.authority.snapshot().documents[0]
        session.client.insert_drakon_atom(diagram.id, "output", 0, source='"new revision"')
        pipeline.project_changed()
        assert scheduler.run_pending() == 1
        assert statuses[-1].state is PipelineState.STALE_OUTPUT
        assert generated_file.read_text(encoding="utf-8") == "# external edit\n"
        assert (root / "generated" / "notes.txt").is_file()

        assert pipeline.generate_now() is not None
        assert "external edit" not in generated_file.read_text(encoding="utf-8")
        assert not (root / "generated" / "notes.txt").exists()
        assert inspect_generation(root, current_revision=session.authority.revision).clean
    finally:
        pipeline.cancel()
        session.close()
