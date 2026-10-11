"""Production editor, CLI and automation routes retain canonical callable metadata."""

import json

import pytest
from PySide6.QtCore import Qt
from pytestqt.exceptions import TimeoutError as QtTimeoutError

from code_visualizer.application.examples import example_session
from code_visualizer.application.invocations import invocation_for_document
from code_visualizer.automation.service import (
    AccessMode,
    AutomationCapability,
    AutomationContext,
    AutomationService,
)
from code_visualizer.cli import main
from code_visualizer.domain.invocation import InvocationSpec
from code_visualizer.domain.program_kinds import CallableKind, MethodKind
from code_visualizer.execution import DebugState
from code_visualizer.persistence import ProjectStore
from code_visualizer.ui_qt.document import UnifiedDocumentWidget

EXAMPLES = (
    ("async", "async for loop action"),
    ("generators", "generator started"),
    ("classes", "Hello from a generated static method"),
)


def _wait_for_execution_button(qtbot, widget, button):
    try:
        qtbot.waitUntil(button.isEnabled, timeout=10000)
    except QtTimeoutError:
        prepared = widget._preparation._preparation.snapshot()
        pytest.fail(
            f"Editor execution did not finish: state={widget.debug_state_label.text()!r}; "
            f"preparation={prepared.status if prepared is not None else None}; "
            f"diagnostic={prepared.diagnostic if prepared is not None else ''!r}; "
            f"runner_active={widget._run_session.is_active}; "
            f"console={widget.console.toPlainText()[-2048:]!r}"
        )


@pytest.mark.parametrize(
    ("source", "spec"),
    (
        (
            "async def main():\n    print('snapshot executed')\n",
            InvocationSpec("main", CallableKind.ASYNC),
        ),
        (
            "def main():\n    print('snapshot executed')\n    yield 1\n",
            InvocationSpec("main", CallableKind.GENERATOR),
        ),
        (
            "class Worker:\n    @staticmethod\n    def run():\n"
            "        print('snapshot executed')\n",
            InvocationSpec("run", owning_class="Worker", method_kind=MethodKind.STATIC),
        ),
    ),
)
def test_source_snapshot_capability_requires_an_explicit_structured_invocation(source, spec):
    from code_visualizer.persistence.invocation import invocation_to_data

    session = example_session("async")
    try:
        descriptor = session.kernel.capabilities.get("execution.run").descriptor
        assert descriptor.input_contract["required"] == ["source", "invocation"]
        result = session.kernel.capabilities.invoke(
            "execution.run",
            {
                "source": source,
                "invocation": invocation_to_data(spec),
            },
        )
        assert result.return_code == 0
        assert result.stdout == "snapshot executed\n"
        assert "RuntimeWarning" not in result.stderr
        with pytest.raises(ValueError, match="structured"):
            session.kernel.capabilities.invoke(
                "execution.run",
                {
                    "source": source,
                    "entrypoint": spec.identifier,
                },
            )
    finally:
        session.close()


@pytest.mark.parametrize(("example_id", "expected"), EXAMPLES)
def test_editor_run_trace_and_debug_execute_the_selected_canonical_callable(
    qtbot, example_id, expected
):
    session = example_session(example_id)
    before = session.authority.snapshot()
    diagram_id = before.drakon_views[0].document_id
    invocation = invocation_for_document(before, diagram_id)
    function = before.program_model.function(before.drakon_views[0].function_id)
    assert invocation.callable_id == function.id
    assert invocation.kind == function.kind
    assert invocation.owning_class == before.program_model.class_name_for(function.id)
    widget = UnifiedDocumentWidget(session.client, diagram_id)
    qtbot.addWidget(widget)
    widget.show()
    try:
        qtbot.mouseClick(widget.run_button, Qt.MouseButton.LeftButton)
        _wait_for_execution_button(qtbot, widget, widget.run_button)
        output = widget.console.toPlainText()
        assert expected in output
        assert "exit 0" in widget.debug_state_label.text()
        assert "RuntimeWarning" not in output
        assert "<generator object" not in output
        assert "<coroutine object" not in output

        qtbot.mouseClick(widget.trace_button, Qt.MouseButton.LeftButton)
        _wait_for_execution_button(qtbot, widget, widget.trace_button)
        trace = widget.console.toPlainText()
        assert expected in trace
        assert "Process exited; exit 0" in trace
        assert "0000" in trace
        assert "<generator object" not in trace

        # Compare execution with caught-exception stops disabled; the async iterator
        # protocol itself raises completion exceptions inside an otherwise valid body.
        widget.pause_exceptions.setChecked(False)
        qtbot.mouseClick(widget.debug_button, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: widget.continue_button.isEnabled(), timeout=10000)
        assert widget._debugger.state is DebugState.PAUSED
        qtbot.mouseClick(widget.continue_button, Qt.MouseButton.LeftButton)
        try:
            qtbot.waitUntil(
                lambda: widget._debugger.state in {DebugState.FINISHED, DebugState.FAILED},
                timeout=10000,
            )
        except Exception:
            pytest.fail(
                f"{widget.debug_state_label.text()}; "
                f"exceptions={widget.pause_exceptions.isChecked()}; "
                f"breakpoints={widget._source_breakpoints}; {widget.console.toPlainText()}"
            )
        widget._poll_debugger()
        assert widget._debugger.state is DebugState.FINISHED, widget.console.toPlainText()
        assert expected in widget.console.toPlainText()
        assert session.authority.snapshot() == before
    finally:
        widget.stop_current()
        widget.close()
        session.close()


@pytest.mark.parametrize(("example_id", "expected"), EXAMPLES)
def test_cli_generated_run_and_live_trace_agree(
    example_id, expected, tmp_path, capsys, monkeypatch
):
    from code_visualizer import cli

    captured = []
    original_trace = cli.trace_project

    def traced_source(*args, **kwargs):
        result = original_trace(*args, **kwargs)
        captured.append(result)
        return result

    monkeypatch.setattr(cli, "trace_project", traced_source)
    session = example_session(example_id)
    try:
        project = session.authority.snapshot()
        root = tmp_path / example_id
        ProjectStore(root).initialize(project)
        assert main(["generate", str(root)]) == 0
        capsys.readouterr()
        assert main(["run", str(root)]) == 0
        generated = capsys.readouterr()
        assert not generated.err
        assert expected in generated.out
        assert main(["trace", str(root), project.drakon_views[0].document_id]) == 0
        traced = json.loads(capsys.readouterr().out)
        assert traced["return_code"] == 0
        assert not traced["stderr"]
        assert traced["stdout"] == generated.out
        assert traced["events"]
        assert captured[0].runtime_events
        assert all(
            event.project_revision == project.revision for event in captured[0].runtime_events
        )
        assert all(
            event.artifact_revision == project.revision for event in captured[0].runtime_events
        )
    finally:
        session.close()


@pytest.mark.parametrize(("example_id", "expected"), EXAMPLES)
def test_automation_live_run_and_trace_agree(qtbot, example_id, expected, monkeypatch):
    session = example_session(example_id)
    service = AutomationService(session.authority)
    captured = []
    original_complete = service._complete_trace

    def complete_trace(job_id, result):
        captured.append(result)
        return original_complete(job_id, result)

    monkeypatch.setattr(service, "_complete_trace", complete_trace)
    context = AutomationContext(
        "runner",
        "invocation-test",
        AccessMode.COMMIT,
        frozenset({AutomationCapability.EXECUTE, AutomationCapability.READ}),
    )
    before = session.authority.snapshot()
    outputs = []
    try:
        for method in ("test.run_diagram", "test.trace_diagram"):
            launched = service.dispatch(
                method, {"diagram_id": before.drakon_views[0].document_id}, context
            )
            params = {"job_id": launched["job_id"]}
            qtbot.waitUntil(
                lambda params=params: (
                    service.dispatch("test.status", params, context)["status"] != "running"
                ),
                timeout=10000,
            )
            result = service.dispatch("test.status", params, context)["result"]
            assert result["return_code"] == 0
            assert not result["stderr"]
            assert expected in result["stdout"]
            outputs.append(result["stdout"])
            if method == "test.trace_diagram":
                assert result["events"]
        assert outputs[0] == outputs[1]
        assert captured[0].runtime_events
        assert all(
            event.project_revision == before.revision for event in captured[0].runtime_events
        )
        assert all(
            event.artifact_revision == before.revision for event in captured[0].runtime_events
        )
        assert session.authority.snapshot() == before
    finally:
        service.close()
        session.close()
