"""Runtime naming and package ownership have one current native representation."""

import json
from copy import deepcopy
from dataclasses import replace

import pytest

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.project_factory import create_default_project
from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.program import ProgramModel, ProgramModule
from code_visualizer.domain.program_kinds import ProgramModuleKind
from code_visualizer.domain.project import (
    EnvironmentVariable,
    Project,
    PythonRuntimeSettings,
    RunProfile,
)
from code_visualizer.domain.python_declarations import parse_python_declarations
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.generation.computation import prepare_computation
from code_visualizer.generation.transformation import TransformationError
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.computation_terminal import load_terminal, publish_terminal
from code_visualizer.persistence.decoding import (
    ProjectDecodeError,
    program_module_from_data,
    project_from_data,
    project_from_json,
    runtime_settings_from_data,
)
from code_visualizer.persistence.program_migration import migrate_legacy_module_kind_operation
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.serialization import (
    normalized_project_json,
    program_model_to_data,
    program_module_to_data,
    project_to_data,
    runtime_settings_to_data,
)
from code_visualizer.persistence.store import JournalRecord, ProjectStore
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.validation import assess_project


def _project():
    return Project(
        "project:runtime",
        "Runtime settings",
        (),
        runtime_settings=PythonRuntimeSettings(
            (
                RunProfile(environment=(EnvironmentVariable("MODE", "proof"),)),
                RunProfile("Other", arguments="--flag"),
            ),
            "Other",
        ),
        program_model=ProgramModel(modules=(ProgramModule("module:main", "main"),)),
    )


def _native_ten(project):
    raw = project_to_data(project)
    raw["format_revision"] = 10
    raw["module_setup"] = raw.pop("runtime_settings")
    for module in raw["program_model"]["modules"]:
        assert module.pop("kind") == "module"
    return raw


def test_current_runtime_settings_have_one_name_and_strict_native_shape():
    project = _project()
    raw = project_to_data(project)
    assert raw["format_revision"] == 11
    assert "runtime_settings" in raw and "module_setup" not in raw
    assert not hasattr(project, "module_setup")
    assert runtime_settings_from_data(raw["runtime_settings"]) == project.runtime_settings
    assert project_from_json(normalized_project_json(project)) == project
    assert normalized_project_json(project) == normalized_project_json(project_from_data(raw))
    with pytest.raises(ProjectDecodeError, match="FORMAT_DUPLICATE_EXECUTABLE_STATE"):
        runtime_settings_from_data({**raw["runtime_settings"], "modules": []})


@pytest.mark.parametrize("revision", (10, 11))
def test_native_snapshots_reject_two_runtime_settings_fields(revision):
    raw = project_to_data(_project())
    raw["format_revision"] = revision
    raw["module_setup"] = deepcopy(raw["runtime_settings"])
    with pytest.raises(ProjectDecodeError, match="FORMAT_DUPLICATE_RUNTIME_SETTINGS"):
        project_from_data(raw)


def test_current_snapshot_rejects_legacy_runtime_name_and_missing_module_kind():
    raw = project_to_data(_project())
    raw["module_setup"] = raw.pop("runtime_settings")
    with pytest.raises(ProjectDecodeError, match="FORMAT_LEGACY_RUNTIME_SETTINGS"):
        project_from_data(raw)
    module = program_module_to_data(_project().program_model.modules[0])
    module.pop("kind")
    with pytest.raises(ProjectDecodeError, match="FORMAT_MISSING_FIELD"):
        program_module_from_data(module)


def test_native_ten_migration_preserves_runtime_values_and_module_identity():
    project = _project()
    raw = _native_ten(project)
    original = deepcopy(raw)
    recovered = project_from_data(raw)
    assert recovered == project
    assert raw == original
    assert recovered.program_model.modules[0].id == "module:main"
    assert recovered.program_model.modules[0].kind is ProgramModuleKind.MODULE
    assert project_to_data(recovered)["format_revision"] == 11
    assert "module_setup" not in project_to_data(recovered)


def test_native_package_initializers_roundtrip_with_explicit_kind_and_stable_ids():
    model = ProgramModel(
        modules=(
            ProgramModule("package:root", "", kind=ProgramModuleKind.PACKAGE),
            ProgramModule("package:nested", "tools", kind=ProgramModuleKind.PACKAGE),
            ProgramModule("module:worker", "tools.worker"),
        )
    )
    project = replace(_project(), program_model=model)
    restored = project_from_json(normalized_project_json(project))
    assert restored.program_model == model
    assert [(item.id, item.kind, item.path) for item in restored.program_model.modules] == [
        ("package:root", ProgramModuleKind.PACKAGE, ""),
        ("package:nested", ProgramModuleKind.PACKAGE, "tools"),
        ("module:worker", ProgramModuleKind.MODULE, "tools.worker"),
    ]


def test_native_package_initializer_kind_and_body_survive_durable_undo_redo(tmp_path):
    before = _project()
    module = before.program_model.modules[0]
    package = replace(
        module,
        kind=ProgramModuleKind.PACKAGE,
        body=parse_python_declarations(
            module.id, "VALUE = 7", identity_namespace="package-history"
        ),
    )
    store = ProjectStore(tmp_path)
    store.initialize(before)
    client = CodeVisualizerClient(ProjectAuthority(before, store=store), actor_id="editor")
    try:
        assert isinstance(client.put_program_module(package), CommandAccepted)
    finally:
        client.close()
    recovered = store.recover(promote=False)
    assert recovered.program_model.modules == (package,)
    assert recovered.format_revision == 11
    client = CodeVisualizerClient(ProjectAuthority(recovered, store=store), actor_id="editor")
    try:
        for operation, expected in ((client.undo, module), (client.redo, package)):
            assert isinstance(operation(), CommandAccepted)
            current = client.snapshot()
            assert current.program_model.modules == (expected,)
            assert current.runtime_settings == before.runtime_settings
            assert current.program_model.modules[0].id == module.id
    finally:
        client.close()


def test_root_package_callable_signature_edit_keeps_drakon_history_and_native_identity(tmp_path):
    project = create_default_project()
    module = project.program_model.modules[0]
    root = replace(module, path="", kind=ProgramModuleKind.PACKAGE)
    store = ProjectStore(tmp_path)
    store.initialize(project)
    client = CodeVisualizerClient(ProjectAuthority(project, store=store), actor_id="editor")
    try:
        assert isinstance(client.put_program_module(root), CommandAccepted)
        before = client.snapshot()
        diagram = before.documents[0]
        function = before.program_model.functions[0]
        assert diagram.header.function.module == ""
        assert assess_project(before).diagnostics == ()
        assert isinstance(
            client.replace_function_spec(
                diagram.id, replace(diagram.header.function, identifier="initialize")
            ),
            CommandAccepted,
        )
        edited = client.snapshot()
        assert edited.program_model.function(function.id).identifier == "initialize"
        assert edited.documents[0].header.function.identifier == "initialize"
        store.save(edited)
        restored = store.load()
        assert restored == edited
        assert restored.program_model.module_for(function.id) == root
        assert restored.documents[0].header.function.module == ""
        assert restored.drakon_views == before.drakon_views
        assert assess_project(restored).diagnostics == ()
        invalid = replace(
            restored,
            program_model=replace(
                restored.program_model,
                modules=(replace(root, kind=ProgramModuleKind.MODULE),),
            ),
        )
        assert "PY_INVALID_MODULE_PATH" in {
            item.code for item in assess_project(invalid).diagnostics
        }
    finally:
        client.close()
    client = CodeVisualizerClient(
        ProjectAuthority(store.recover(promote=False), store=store), actor_id="editor"
    )
    try:
        for command, expected in ((client.undo, before), (client.redo, edited)):
            assert isinstance(command(), CommandAccepted)
            current = client.snapshot()
            assert current.program_model == expected.program_model
            assert current.documents == expected.documents
            assert current.drakon_views == expected.drakon_views
            assert current.program_model.module_for(function.id) == root
            assert assess_project(current).diagnostics == ()
    finally:
        client.close()


def test_terminal_two_preserves_explicit_authored_package_initializers(tmp_path):
    initializer = ProgramModule(
        "package:root",
        "",
        parse_python_declarations(
            "package:root", "VALUE = 7", identity_namespace="package-terminal"
        ),
        kind=ProgramModuleKind.PACKAGE,
    )
    project = replace(_project(), program_model=ProgramModel(modules=(initializer,)))
    registry = builtin_registry()
    prepared = prepare_computation(
        project,
        ComputationRequest(project.id, project.revision, "code_visualizer.python", "1"),
        registry,
    )
    store = ResourceStore(tmp_path)
    plan = publish_terminal(prepared, store)
    original = store.read(plan.model)
    loaded = load_terminal(plan, store, registry)
    assert loaded.value == project.program_model
    assert loaded.value.modules[0] == initializer
    assert json.loads(original)["value"]["modules"][0]["kind"] == "package"
    assert store.read(plan.model) == original


@pytest.mark.parametrize("nested", (False, True))
@pytest.mark.parametrize(
    "command", ("python.configure_runtime", "program.module.put", "program.configure")
)
def test_native_ten_history_upgrades_runtime_and_module_payloads_for_undo_redo(
    tmp_path, command, nested
):
    before = _project()
    if command == "python.configure_runtime":
        after = replace(
            before, runtime_settings=replace(before.runtime_settings, active_run_profile="Default")
        )
        forward = runtime_settings_to_data(after.runtime_settings)
        inverse = runtime_settings_to_data(before.runtime_settings)
    else:
        after = replace(
            before,
            program_model=replace(
                before.program_model,
                modules=(replace(before.program_model.modules[0], path="renamed"),),
            ),
        )
        if command == "program.module.put":
            forward = {"module": program_module_to_data(after.program_model.modules[0])}
            inverse = {"module": program_module_to_data(before.program_model.modules[0])}
            forward["module"].pop("kind")
            inverse["module"].pop("kind")
        else:
            forward = {
                key: value
                for key, value in program_model_to_data(after.program_model).items()
                if key in {"package", "modules", "entrypoint"}
            }
            inverse = {
                key: value
                for key, value in program_model_to_data(before.program_model).items()
                if key in {"package", "modules", "entrypoint"}
            }
            forward["modules"][0].pop("kind")
            inverse["modules"][0].pop("kind")
    after = replace(after, revision=1)
    if nested:
        forward = {"operations": [{"command_type": command, "payload": forward}]}
        inverse = {"operations": [{"command_type": command, "payload": inverse}]}
        command = "transaction"
    record = {
        "revision": 1,
        "actor_id": "editor",
        "operation_id": "legacy-ten",
        "command_type": command,
        "project": _native_ten(after),
        "history_action": "commit",
        "occurred_at": "",
        "affected_ids": [after.id, "module:main"],
        "forward_type": command,
        "forward_payload": forward,
        "inverse_type": command,
        "inverse_payload": inverse,
    }
    upgraded = JournalRecord.from_data(record)
    assert upgraded.project == after
    store = ProjectStore(tmp_path)
    store.initialize(after)
    store.journal_file.write_text(json.dumps(record) + "\n", encoding="utf-8")
    client = CodeVisualizerClient(
        ProjectAuthority(store.recover(promote=False), store=store), actor_id="editor"
    )
    try:
        for operation, expected in ((client.undo, before), (client.redo, after)):
            assert isinstance(operation(), CommandAccepted)
            current = client.snapshot()
            assert current.runtime_settings == expected.runtime_settings
            assert current.program_model == expected.program_model
            assert current.format_revision == 11
    finally:
        client.close()


def test_legacy_function_restore_header_receives_explicit_module_kinds():
    raw = _native_ten(_project())["program_model"]
    header = {
        key: value for key, value in raw.items() if key in {"package", "modules", "entrypoint"}
    }
    payload = {"function": {"id": "unrelated"}, "program_header": header}
    original = deepcopy(payload)
    kind, converted = migrate_legacy_module_kind_operation("program.function.restore", payload)
    assert kind == "program.function.restore"
    assert converted["program_header"]["modules"][0]["kind"] == "module"
    assert converted["function"] == payload["function"]
    assert payload == original


@pytest.mark.parametrize("unknown_field", (False, True))
def test_terminal_two_defaults_old_module_kinds_without_changing_immutable_bytes(
    tmp_path, unknown_field
):
    project = _project()
    registry = builtin_registry()
    prepared = prepare_computation(
        project,
        ComputationRequest(project.id, project.revision, "code_visualizer.python", "1"),
        registry,
    )
    store = ResourceStore(tmp_path)
    plan = publish_terminal(prepared, store)
    descriptor = store.describe(plan.model)
    payload = json.loads(store.read(plan.model))
    for module in payload["value"]["modules"]:
        module.pop("kind")
    if unknown_field:
        payload["value"]["modules"][0]["unrecognized_meaning"] = "retain or reject"
    original = canonical_data_bytes(payload)
    historical = store.put(original, descriptor.media_type, logical_type=descriptor.logical_type)
    legacy_plan = replace(plan, model=historical.reference)
    if unknown_field:
        with pytest.raises((ProjectDecodeError, TransformationError)):
            load_terminal(legacy_plan, store, registry)
    else:
        loaded = load_terminal(legacy_plan, store, registry)
        assert loaded.value == project.program_model
        assert loaded.input_digest == plan.input_digest
    assert store.read(historical.reference) == original
    assert store.describe(historical.reference) == historical
