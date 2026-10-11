"""Preparation preserves canonical scope and admits only its latest editor request."""

from dataclasses import replace
from io import BytesIO
from threading import Event, Thread

import pytest
from fixtures.editor_worker_fixture import fixture_registry

from code_visualizer.application.authored_examples import authored_traffic_light_project
from code_visualizer.application.drakon_program_adapter import drakon_from_program
from code_visualizer.application.editor_preparation import EditorPreparation, prepare_editor
from code_visualizer.application.project_factory import create_default_project
from code_visualizer.domain.drakon import create_empty_drakon
from code_visualizer.domain.invocation_arguments import (
    EMPTY_INVOCATION_ARGUMENTS,
    parse_invocation_arguments,
)
from code_visualizer.domain.projection import DrakonViewDefinition
from code_visualizer.domain.worker import WorkerEditorPreparationRequest, WorkerEditorPrepared
from code_visualizer.execution.worker_process import WorkerChannel, read_worker_frame
from code_visualizer.generation.emitter import GeneratedProject
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.python_execution import load_python_execution_artifact
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.serialization import project_to_data
from code_visualizer.protocol.worker import worker_event_from_bytes
from code_visualizer.validation import assess_project


def _prepare(project, tmp_path, **target):
    store = ResourceStore(tmp_path)
    source = store.put(canonical_data_bytes(project_to_data(project)), "application/json")
    request = WorkerEditorPreparationRequest(
        "editor-test", source.reference, project.id, project.revision, **target
    )
    channel = WorkerChannel(BytesIO(), BytesIO())
    prepare_editor(request, fixture_registry(), store, channel)
    channel.outgoing.seek(0)
    events = []
    while True:
        try:
            events.append(worker_event_from_bytes(read_worker_frame(channel.outgoing)))
        except EOFError:
            break
    response = events[-1]
    assert isinstance(response, WorkerEditorPrepared)
    assert response.source_digest == source.content_hash
    return load_python_execution_artifact(response.execution_artifact, store)


def test_focused_worker_ignores_unrelated_invalid_configured_invocation(tmp_path):
    # Use the canonical signature fixture, preserving its required-argument defect.
    from test_invocation_binding import _function, _program, _project

    project = _project(arguments="")
    configured = project.program_model.functions[0]
    selected = _function(identifier="selected", output="'selected'")
    program = _program(configured, selected)
    diagram = create_empty_drakon(identifier="selected", diagram_id="view:selected")
    view = DrakonViewDefinition(
        diagram.id, selected.id, "Selected", diagram.header.id, diagram.end.id
    )
    diagram = drakon_from_program(selected, view, diagram, model=program)
    project = replace(
        project,
        program_model=program,
        documents=(*project.documents, diagram),
        drakon_views=(*project.drakon_views, view),
    )
    before = project_to_data(project)
    assert not assess_project(project).buildable
    artifact = _prepare(
        project, tmp_path, focus_diagram_id=diagram.id, arguments=EMPTY_INVOCATION_ARGUMENTS
    )
    assert artifact.generated.invocation.callable_id == selected.id
    assert any("print('selected')" in file.source for file in artifact.generated.files)
    assert project_to_data(project) == before
    assert project.program_model.entrypoint_callable_id == configured.id


def test_authored_domain_preparation_carries_derived_bindings_and_original_origins(tmp_path):
    project = authored_traffic_light_project()
    registry = fixture_registry()
    assert all("fsm" not in bundle.id for bundle in registry.bundles())
    before = project_to_data(project)
    artifact = _prepare(project, tmp_path, model_id=project.domain_workspace.models[0].id)
    assert artifact.generated.origins is not None
    assert {"traffic:red", "traffic:green", "traffic:yellow"} <= {
        identity for link in artifact.generated.origins.links for identity in link.source_ids
    }
    assert artifact.binding_specs
    assert all(binding.semantic_symbol_id for binding in artifact.binding_specs)
    assert project.program_model.functions == ()
    assert project_to_data(project) == before


def test_preview_mailbox_coalesces_pending_requests_and_rejects_obsolete_completion(monkeypatch):
    project = create_default_project()
    started, release, finished = Event(), Event(), Event()
    prepared = []

    def bounded_prepare(self, request):
        prepared.append(request.identity)
        if len(prepared) == 1:
            started.set()
            assert release.wait(3)
        self._publish(request, status="ready", source_digest="a" * 64)
        if len(prepared) == 2:
            finished.set()

    monkeypatch.setattr(EditorPreparation, "_prepare", bounded_prepare)
    editor = EditorPreparation()
    try:
        first = editor.submit(project)
        assert started.wait(3)
        discarded = editor.submit(replace(project, revision=1))
        current = editor.submit(replace(project, revision=2))
        assert editor.snapshot().request_id == current
        release.set()
        assert finished.wait(3)
        assert prepared == [first, current]
        assert discarded not in prepared
        assert editor.snapshot().request_id == current
        assert editor.snapshot().revision == 2
        assert editor.snapshot().status == "ready"
    finally:
        release.set()
        editor.close(wait=True)


def test_prepared_snapshot_wakes_an_already_waiting_observer(monkeypatch):
    project = create_default_project()
    preparing, release, waiting, observed = Event(), Event(), Event(), Event()

    def prepare(self, request):
        preparing.set()
        assert release.wait(3)
        self._publish(request, status="ready", source_digest="a" * 64)

    monkeypatch.setattr(EditorPreparation, "_prepare", prepare)
    editor = EditorPreparation()
    request_id = editor.submit(project)
    assert preparing.wait(3)

    def observe():
        with editor._condition:
            waiting.set()
            # A ready snapshot must signal this observer, not wait for its timeout.
            received = editor._condition.wait_for(
                lambda: editor.snapshot().status == "ready", timeout=30
            )
            if received:
                observed.set()

    observer = Thread(target=observe)
    observer.start()
    try:
        assert waiting.wait(3)
        release.set()
        assert observed.wait(3)
        assert editor.snapshot().request_id == request_id
        assert editor.snapshot().source_digest == "a" * 64
    finally:
        release.set()
        editor.close(wait=True)
        with editor._condition:
            editor._condition.notify_all()
        observer.join(timeout=3)


def test_admitted_artifact_cache_is_one_entry_with_exact_source_target_and_arguments(monkeypatch):
    project = create_default_project()
    focus = project.documents[0].id
    generated = GeneratedProject((), None, None)
    completed = Event()
    prepared = []

    def admitted(self, request):
        prepared.append(request.identity)
        self._publish(request, status="ready", source_digest="a" * 64, generated=generated)
        completed.set()

    monkeypatch.setattr(EditorPreparation, "_prepare", admitted)
    editor = EditorPreparation()
    try:
        first = editor.submit(project, focus_diagram_id=focus, arguments=EMPTY_INVOCATION_ARGUMENTS)
        assert completed.wait(3)
        admitted_view = editor.snapshot()
        second = editor.submit(
            project, focus_diagram_id=focus, arguments=EMPTY_INVOCATION_ARGUMENTS
        )
        reused = editor.snapshot()
        assert second != first
        assert reused.request_id == second
        assert reused.status == "ready"
        assert reused.generated is admitted_view.generated
        assert reused.binding_specs is admitted_view.binding_specs
        assert reused.source_digest == admitted_view.source_digest
        assert prepared == [first]

        # Equality is insufficient: a newly admitted author snapshot, target,
        # or structured invocation replaces the sole disposable cache entry.
        for source, target in (
            (
                replace(project),
                {"focus_diagram_id": focus, "arguments": EMPTY_INVOCATION_ARGUMENTS},
            ),
            (project, {"focus_diagram_id": "different-diagram"}),
            (project, {"model_id": "different-domain-model"}),
            (project, {"focus_diagram_id": focus, "arguments": parse_invocation_arguments("7")}),
            (project, {"focus_diagram_id": focus, "arguments": EMPTY_INVOCATION_ARGUMENTS}),
        ):
            completed.clear()
            request_id = editor.submit(source, **target)
            assert completed.wait(3)
            assert prepared[-1] == request_id
            assert editor.snapshot().request_id == request_id
        assert len(prepared) == 6
    finally:
        editor.close(wait=True)
    assert editor._cache is None
    with pytest.raises(RuntimeError, match="closed"):
        editor.submit(project)


def test_bound_preview_can_run_matching_arguments_but_never_replaces_defaults_or_binding(
    monkeypatch,
):
    from fixtures.editor_worker_fixture import worker_profile
    from test_invocation_binding import _project

    project = _project(arguments="7")
    before = project_to_data(project)
    focus = project.documents[0].id
    calls = []
    prepare = EditorPreparation._prepare

    def record(self, request):
        calls.append(request.identity)
        return prepare(self, request)

    monkeypatch.setattr(EditorPreparation, "_prepare", record)
    editor = EditorPreparation(profiles=(worker_profile(),))

    def wait(identity):
        with editor._condition:
            assert editor._condition.wait_for(
                lambda: (
                    editor._view is not None
                    and editor._view.request_id == identity
                    and editor._view.status in {"ready", "failed"}
                ),
                timeout=30,
            ), editor.snapshot()
        return editor.snapshot()

    try:
        preview = editor.submit(project, focus_diagram_id=focus)
        first = wait(preview)
        assert first.status == "ready", first.diagnostic
        assert first.generated.invocation.arguments == parse_invocation_arguments("7")
        explicit = editor.submit(
            project, focus_diagram_id=focus, arguments=parse_invocation_arguments("7")
        )
        reused = editor.snapshot()
        assert reused.request_id == explicit and reused.status == "ready"
        assert reused.generated is first.generated and reused.binding_specs is first.binding_specs
        assert calls == [preview]

        override = editor.submit(
            project, focus_diagram_id=focus, arguments=parse_invocation_arguments("8")
        )
        overridden = wait(override)
        assert overridden.status == "ready", overridden.diagnostic
        assert overridden.generated.invocation.arguments == parse_invocation_arguments("8")
        default = editor.submit(project, focus_diagram_id=focus)
        restored = wait(default)
        assert restored.status == "ready", restored.diagnostic
        assert restored.generated.invocation.arguments == parse_invocation_arguments("7")
        invalid = editor.submit(
            project, focus_diagram_id=focus, arguments=EMPTY_INVOCATION_ARGUMENTS
        )
        rejected = wait(invalid)
        assert rejected.status == "failed" and "INVOCATION_ARGUMENT_MISMATCH" in rejected.diagnostic
        assert calls == [preview, override, default, invalid]
        assert project_to_data(project) == before
    finally:
        editor.close(wait=True)
