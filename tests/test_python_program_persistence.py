"""Python ownership is canonical across format migration and durable history."""

from copy import deepcopy
from dataclasses import replace

import pytest

from code_visualizer.domain.expression import UnparsedPythonExpression
from code_visualizer.domain.program import (
    ExpressionRole,
    ProgramAction,
    ProgramAssignment,
    ProgramClass,
    ProgramEntryPoint,
    ProgramFunction,
    ProgramFunctionReference,
    ProgramImport,
    ProgramModel,
    ProgramModule,
    ProgramSequence,
    ProgramSymbol,
    ProgramSymbolKind,
    ProgramTypeAlias,
    make_program_expression,
    program_expressions,
)
from code_visualizer.domain.program_kinds import CallableKind, MethodKind
from code_visualizer.domain.project import Project
from code_visualizer.domain.python_declarations import parse_python_declarations
from code_visualizer.persistence.decoding import (
    ProjectDecodeError,
    program_declaration_from_data,
    program_function_from_data,
    program_model_from_data,
    project_from_data,
    project_from_json,
    runtime_settings_from_data,
)
from code_visualizer.persistence.program_migration import migrate_legacy_program_data
from code_visualizer.persistence.serialization import (
    normalized_project_json,
    program_function_to_data,
    program_model_to_data,
    project_to_data,
)
from code_visualizer.persistence.store import JournalRecord


def _function(identifier="main", *, class_method=False):
    return ProgramFunction(
        "function:" + identifier,
        "symbol:" + identifier,
        identifier,
        identifier,
        CallableKind.SYNC,
        (),
        None,
        (),
        None,
        MethodKind.STATIC if class_method else None,
        ProgramSequence(
            "body:" + identifier,
            (
                ProgramAction(
                    "action:" + identifier,
                    make_program_expression(
                        "action:" + identifier,
                        "source",
                        "print('ok')",
                        ExpressionRole.STATEMENTS,
                        identity_namespace="fixed",
                    ),
                ),
            ),
        ),
    )


def _legacy(revision=9):
    function = _function()
    symbol = ProgramSymbol(
        function.symbol_id,
        function.identifier,
        ProgramSymbolKind.FUNCTION,
        function.id,
        function.id,
    )
    project = Project("project:legacy", "Legacy", (), program_model=ProgramModel())
    raw = project_to_data(project)
    raw.pop("runtime_settings")
    raw["format_revision"] = revision
    raw["program_model"] = {
        "functions": [
            {**program_function_to_data(function), "module": "main", "owning_class": None}
        ],
        "symbols": program_model_to_data(ProgramModel(symbols=(symbol,)))["symbols"],
    }
    raw["program_model"]["functions"][0].pop("type_parameters")
    raw["module_setup"] = {
        "package": "app",
        "entrypoint_callable_id": function.id,
        "entrypoint_arguments": ""
        if revision < 8
        else {"kind": "literal", "positional": [], "keywords": []},
        "post_source": "print('startup')",
        "active_run_profile": "Default",
        "run_profiles": [
            {
                "name": "Default",
                "interpreter": "",
                "working_directory": ".",
                "arguments": "",
                "environment": [],
            }
        ],
        "modules": [
            {
                "path": "main",
                "docstring": "Original module",
                "imports": [{"module": "math", "name": "pi", "alias": "PI"}],
                "constants": [{"name": "VALUE", "expression": "7", "annotation": "int"}],
                "type_aliases": [{"name": "Numbers", "expression": "list[int]"}],
                "declarations": "class Helper:\n    value = 1",
                "before_functions": "before = VALUE + 1",
                "after_functions": "after = before + 1",
            }
        ],
    }
    return raw


@pytest.mark.parametrize("revision", [4, 5, 6, 7, 8, 9])
def test_legacy_python_ownership_promotes_once_with_existing_identities(revision):
    raw = _legacy(revision)
    original = deepcopy(raw)
    first = project_from_data(raw)
    assert raw == original
    assert first == project_from_data(raw)
    assert first.format_revision == 11
    model = first.program_model
    assert model.functions[0].id == "function:main"
    assert model.functions[0].body.id == "body:main"
    assert model.functions[0].symbol_id == "symbol:main"
    assert model.module_path_for("function:main") == "main"
    body = model.modules[0].body
    assert [type(item) for item in body] == [
        ProgramImport,
        ProgramAssignment,
        ProgramTypeAlias,
        ProgramClass,
        ProgramAssignment,
        ProgramFunctionReference,
        ProgramAssignment,
    ]
    assert body[3].identifier == "Helper"
    assert model.entrypoint.callable_id == "function:main"
    assert model.entrypoint.startup
    encoded = project_to_data(first)
    assert set(encoded["runtime_settings"]) == {"run_profiles", "active_run_profile"}
    assert not {"module", "owning_class"} & encoded["program_model"]["functions"][0].keys()
    assert project_from_json(normalized_project_json(first)) == first


def test_legacy_class_groups_keep_the_original_emission_order_and_method_ids():
    raw = _legacy()
    raw["program_model"]["functions"] = [
        {
            **program_function_to_data(_function(name, class_method=owner is not None)),
            "module": "main",
            "owning_class": owner,
        }
        for name, owner in (("first", "Worker"), ("main", None), ("last", "Worker"))
    ]
    converted = program_model_from_data(
        migrate_legacy_program_data(
            raw["program_model"],
            raw["module_setup"],
            project_id="project:legacy",
        )
    )
    owner = converted.class_for("function:first")
    assert owner == converted.class_for("function:last")
    assert [item.function_id for item in owner.body] == ["function:first", "function:last"]
    assert converted.modules[0].body[-3] == ProgramFunctionReference("function:main")
    assert converted.modules[0].body[-2] == owner


def test_unconfigured_legacy_scope_preserves_the_existing_lowering_default_module():
    raw = _legacy()
    raw["program_model"]["functions"][0]["module"] = "helpers.worker"
    converted = migrate_legacy_program_data(
        raw["program_model"], raw["module_setup"], project_id="p"
    )
    model = program_model_from_data(converted)
    assert [module.path for module in model.modules] == ["main", "helpers.worker"]
    assert model.module_for("function:main").body == (ProgramFunctionReference("function:main"),)


def test_incomplete_legacy_source_is_preserved_explicitly_without_a_parsed_shadow():
    raw = _legacy()
    raw["module_setup"]["modules"][0]["declarations"] = "class Broken("
    model = program_model_from_data(
        migrate_legacy_program_data(raw["program_model"], raw["module_setup"], project_id="p")
    )
    incomplete = [
        expression.tree
        for expression in program_expressions(model.modules)
        if isinstance(expression.tree, UnparsedPythonExpression)
    ]
    assert len(incomplete) == 1
    assert incomplete[0].source == "class Broken("
    assert program_model_from_data(program_model_to_data(model)) == model


def test_module_only_program_and_nested_class_headers_round_trip_without_drakon():
    declarations = parse_python_declarations(
        "module:test",
        """@decorate
class Box[T](Base, metaclass=Meta):
    \"\"\"A generic container.\"\"\"
    class Nested:
        count = 1
""",
        identity_namespace="stable",
    )
    model = ProgramModel(modules=(ProgramModule("module:test", "main", declarations),))
    project = Project("p", "Module only", (), program_model=model)
    assert project_from_json(normalized_project_json(project)) == project
    owner = model.modules[0].body[0]
    assert isinstance(owner, ProgramClass)
    assert owner.arguments is not None and owner.decorators and owner.type_parameters
    assert isinstance(owner.body[0], ProgramClass)


def test_current_codecs_reject_displaced_executable_state():
    with pytest.raises(ProjectDecodeError, match="FORMAT_DUPLICATE_EXECUTABLE_STATE"):
        runtime_settings_from_data(_legacy()["module_setup"])
    with pytest.raises(ProjectDecodeError, match="FORMAT_DUPLICATE_EXECUTABLE_STATE"):
        program_function_from_data(_legacy()["program_model"]["functions"][0])
    with pytest.raises(ProjectDecodeError, match="FORMAT_PROGRAM_OWNERSHIP"):
        program_declaration_from_data(
            {"kind": "function_reference", "function_id": "f", "id": "copy"}
        )


@pytest.mark.parametrize("nested", [False, True])
def test_legacy_journal_translates_both_setup_operations_into_current_typed_commands(nested):
    raw = _legacy(7)
    forward = deepcopy(raw["module_setup"])
    inverse = {**forward, "entrypoint_arguments": "7"}
    kind = "python.replace_module_setup"
    if nested:
        forward = {"operations": [{"command_type": kind, "payload": forward}]}
        inverse = {"operations": [{"command_type": kind, "payload": inverse}]}
        kind = "transaction"
    record = JournalRecord.from_data(
        {
            "revision": 1,
            "actor_id": "editor",
            "operation_id": "legacy-edit",
            "command_type": kind,
            "project": raw,
            "history_action": "commit",
            "occurred_at": "",
            "forward_type": kind,
            "forward_payload": forward,
            "inverse_type": kind,
            "inverse_payload": inverse,
        }
    )
    for payload in (record.forward_payload, record.inverse_payload):
        operations = payload["operations"]
        assert [item["command_type"] for item in operations] == [
            "program.configure",
            "python.configure_runtime",
        ]
        assert set(operations[1]["payload"]) == {"run_profiles", "active_run_profile"}
        assert "modules" in operations[0]["payload"]
    assert record.project.format_revision == 11


def test_empty_program_has_no_fabricated_entrypoint_identity():
    model = ProgramModel()
    assert program_model_to_data(model)["entrypoint"] is None
    assert program_model_from_data(program_model_to_data(model)) == model
    configured = replace(model, entrypoint=ProgramEntryPoint("entrypoint:actual"))
    assert program_model_from_data(program_model_to_data(configured)) == configured


def test_legacy_terminal_bundle_cutover_preserves_unrelated_extension_references():
    raw = _legacy()
    raw["domain_workspace"]["bundle_references"] = [
        {"id": "code_visualizer.computation", "version": "1"},
        {"id": "org.example.custom", "version": "1"},
    ]
    project = project_from_data(raw)
    assert {(item.id, item.version) for item in project.domain_workspace.bundle_references} == {
        ("code_visualizer.computation", "2"),
        ("org.example.custom", "1"),
    }


@pytest.mark.parametrize("field", ["bases", "source", "module_setup"])
def test_current_declarations_reject_unknown_meaning_instead_of_dropping_it(field):
    from code_visualizer.persistence.decoding import program_class_from_data
    from code_visualizer.persistence.serialization import program_class_to_data

    raw = program_class_to_data(ProgramClass("class:c", "C"))
    raw[field] = "shadow"
    with pytest.raises(ProjectDecodeError, match="FORMAT_UNKNOWN_PROGRAM_FIELD"):
        program_class_from_data(raw)


def test_legacy_method_move_history_restores_class_ownership_and_undo_redo(tmp_path):
    import json

    from code_visualizer.application.authority import ProjectAuthority
    from code_visualizer.application.messages import CommandAccepted
    from code_visualizer.persistence import ProjectStore
    from code_visualizer.sdk import CodeVisualizerClient

    raw = _legacy()
    function = raw["program_model"]["functions"][0]
    function.update(module="other", owning_class="Worker", method_kind="static")
    raw["module_setup"]["modules"].append({"path": "other"})
    raw["revision"] = 1
    record = {
        "revision": 1,
        "actor_id": "editor",
        "operation_id": "old-move",
        "command_type": "program.function.set_module",
        "project": raw,
        "history_action": "commit",
        "occurred_at": "",
        "affected_ids": ["function:main"],
        "forward_type": "program.function.set_module",
        "forward_payload": {"function_id": "function:main", "module": "other"},
        "inverse_type": "program.function.set_module",
        "inverse_payload": {"function_id": "function:main", "module": "main"},
    }
    migrated = JournalRecord.from_data(record)
    assert "project:legacy" in migrated.affected_ids
    assert migrated.forward_type == migrated.inverse_type == "program.configure"
    store = ProjectStore(tmp_path)
    store.initialize(project_from_data(raw))
    store.journal_file.write_text(json.dumps(record) + "\n", encoding="utf-8")
    authority = ProjectAuthority(store.recover(promote=False), store=store)
    client = CodeVisualizerClient(authority, actor_id="editor")
    try:
        for operation, path in ((client.undo, "main"), (client.redo, "other")):
            assert isinstance(operation(), CommandAccepted)
            model = client.snapshot().program_model
            assert model.module_path_for("function:main") == path
            assert model.class_name_for("function:main") == "Worker"
            assert (
                len(
                    [
                        item
                        for module in model.modules
                        for item in module.body
                        if isinstance(item, ProgramClass) and item.identifier == "Worker"
                    ]
                )
                == 1
            )
    finally:
        client.close()


def test_legacy_module_and_class_anchors_survive_promotion_rename_and_reload():
    from code_visualizer.application.authority import ProjectAuthority
    from code_visualizer.application.messages import CommandAccepted
    from code_visualizer.application.semantic_index import build_semantic_program
    from code_visualizer.domain.authoring import SemanticConcept
    from code_visualizer.domain.freeform import FreeformDiagram, Rect, ShapeKind, ShapeObject
    from code_visualizer.domain.mindmap import MindMapDiagram, Topic
    from code_visualizer.domain.projection import ProjectionDefinition
    from code_visualizer.domain.semantic import SemanticObjectKind
    from code_visualizer.persistence.serialization import document_to_data
    from code_visualizer.sdk import CodeVisualizerClient

    # These are the exact IDs emitted by the revision-9 semantic index.
    module_id = "module:app.main"
    class_id = "class:module:app.main:Worker"
    raw = _legacy()
    raw["program_model"]["functions"][0].update(owning_class="Worker", method_kind="static")
    canvas = FreeformDiagram(
        "canvas:anchors",
        "Anchors",
        (
            ShapeObject(
                "shape:module", ShapeKind.RECTANGLE, Rect(0, 0, 100, 60), semantic_id=module_id
            ),
            ShapeObject(
                "shape:class", ShapeKind.RECTANGLE, Rect(150, 0, 100, 60), semantic_id=class_id
            ),
        ),
    )
    hierarchy = MindMapDiagram(
        "tree:anchors",
        "Hierarchy",
        Topic(
            "topic:module",
            "Module",
            (Topic("topic:class", "Class", semantic_id=class_id),),
            semantic_id=module_id,
        ),
    )
    authored = Project(
        "annotations",
        "Annotations",
        (),
        concepts=(SemanticConcept("concept:owners", "Owners", member_ids=(module_id, class_id)),),
        projection_definitions=(
            ProjectionDefinition("lens:module", "Module", scope_id=module_id),
            ProjectionDefinition("lens:class", "Class", scope_id=class_id),
        ),
    )
    authored_data = project_to_data(authored)
    raw.update(
        documents=[document_to_data(canvas), document_to_data(hierarchy)],
        concepts=authored_data["concepts"],
        projection_definitions=authored_data["projection_definitions"],
    )
    project = project_from_data(raw)
    assert project.program_model.module(module_id) is not None
    assert project.program_model.class_(class_id) is not None
    assert project.concepts[0].member_ids == (module_id, class_id)
    assert {item.scope_id for item in project.projection_definitions} == {module_id, class_id}
    assert project.documents == (canvas, hierarchy)
    index = {item.id: item for item in build_semantic_program(project).objects}
    assert index[module_id].kind is SemanticObjectKind.MODULE
    assert index[class_id].kind is SemanticObjectKind.CLASS

    authority = ProjectAuthority(project)
    client = CodeVisualizerClient(authority, actor_id="editor")
    try:
        owner = client.snapshot().program_model.class_(class_id)
        assert isinstance(
            client.put_program_class(module_id, replace(owner, identifier="RenamedWorker")),
            CommandAccepted,
        )
        module = client.snapshot().program_model.module(module_id)
        assert isinstance(
            client.put_program_module(replace(module, path="renamed")), CommandAccepted
        )
        renamed = project_from_json(normalized_project_json(client.snapshot()))
        index = {item.id: item for item in build_semantic_program(renamed).objects}
        assert index[module_id].label == "renamed"
        assert index[class_id].label == "RenamedWorker"
        assert renamed.concepts == project.concepts
        assert renamed.projection_definitions == project.projection_definitions
        assert renamed.documents == project.documents
        assert renamed.program_model.module_for("function:main").id == module_id
        assert renamed.program_model.class_for("function:main").id == class_id
    finally:
        client.close()


def test_legacy_semantic_module_identity_collision_fails_explicitly():
    raw = _legacy()
    module_id = "module:app.main"
    raw["program_model"]["functions"][0]["id"] = module_id
    raw["program_model"]["symbols"][0].update(owner_id=module_id, declaration_id=module_id)
    raw["module_setup"]["entrypoint_callable_id"] = module_id
    with pytest.raises(ProjectDecodeError, match="DUPLICATE"):
        project_from_data(raw)
