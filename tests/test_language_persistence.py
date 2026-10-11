"""Persisted language data uses native history, revisions, and typed boundaries."""

from dataclasses import replace

import pytest
from python_persistence_fixtures import legacy_project_data

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.language_commands import (
    DeleteDomainLanguage,
    DeleteDomainNotation,
    DeleteDomainTransformation,
    DeleteDomainValidator,
    PutDomainLanguage,
    PutDomainNotation,
    PutDomainTransformation,
    PutDomainValidator,
)
from code_visualizer.application.messages import CommandAccepted, CommandEnvelope, CommandRejected
from code_visualizer.automation.service import (
    AccessMode,
    AutomationCapability,
    AutomationContext,
    AutomationService,
)
from code_visualizer.domain.intentional import ConceptDefinition, DomainSchema, DomainWorkspace
from code_visualizer.domain.language import (
    AuthoredDomainLanguage,
    AuthoredTransformation,
    FunctionTemplate,
    QueryHole,
    QueryLiteral,
    QueryNodes,
    RuntimeLiteral,
    TemplateOutput,
    ValidatorDefinition,
)
from code_visualizer.domain.notation import NotationDefinition, NotationKind
from code_visualizer.domain.project import Project
from code_visualizer.domain.transformation import (
    PROGRAM_REPRESENTATION,
    Representation,
    TransformationDefinition,
)
from code_visualizer.persistence.decoding import (
    ProjectDecodeError,
    project_from_data,
    project_from_json,
)
from code_visualizer.persistence.language import authored_language_to_data
from code_visualizer.persistence.serialization import normalized_project_json, project_to_data
from code_visualizer.persistence.store import ProjectStore
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.validation import validate_integrity


def _language(prefix="author"):
    return AuthoredDomainLanguage(
        f"{prefix}:language",
        "schema",
        "1",
        title="User FSM language",
        notations=(
            NotationDefinition(
                f"{prefix}:form", "State form", NotationKind.TREE_FORM, schema_id="schema"
            ),
        ),
        validators=(
            ValidatorDefinition(
                f"{prefix}:rule",
                "state",
                "state",
                QueryLiteral(f"{prefix}:true", True),
                "State rule",
            ),
        ),
        transformations=(
            AuthoredTransformation(
                TransformationDefinition(
                    f"{prefix}:transform",
                    "1",
                    Representation("user.fsm", "1"),
                    PROGRAM_REPRESENTATION,
                ),
                (
                    FunctionTemplate(
                        f"{prefix}:function",
                        QueryNodes(f"{prefix}:nodes", "state"),
                        "state",
                        body=(
                            TemplateOutput(
                                f"{prefix}:output",
                                RuntimeLiteral(
                                    f"{prefix}:runtime", QueryLiteral(f"{prefix}:text", "State")
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )


def _project(*languages):
    schema = DomainSchema("schema", "user.fsm", "1", (ConceptDefinition("state", "State"),))
    return Project(
        "project",
        "Language history",
        (),
        domain_workspace=DomainWorkspace((schema,), language_definitions=languages),
    )


def test_format_seven_persists_complete_typed_language_deterministically():
    project = _project(_language())
    encoded = normalized_project_json(project)
    restored = project_from_json(encoded)
    assert restored == project
    assert restored.format_revision == 11
    assert normalized_project_json(restored) == encoded
    assert restored.program_model.functions == ()


def test_format_six_migrates_without_inventing_language_definitions():
    data = legacy_project_data(_project(), 6)
    del data["domain_workspace"]["language_definitions"]
    restored = project_from_data(data)
    assert restored.format_revision == 11
    assert restored.domain_workspace.language_definitions == ()


@pytest.mark.parametrize(
    "corrupt",
    [
        lambda value: value.update(callback="os.system"),
        lambda value: value.update(syntax_version=True),
        lambda value: value["validators"][0].update(
            predicate={"type": "QueryLiteral", "id": "bad", "value": {"code": "print(1)"}}
        ),
        lambda value: value["transformations"][0]["functions"][0].update(
            body=[{"type": "QueryLiteral", "id": "bad", "value": 1}]
        ),
        lambda value: value["transformations"][0]["functions"][0].update(
            source={"type": "SomeImport", "module": "os"}
        ),
    ],
)
def test_decoder_rejects_unknown_code_and_mistyped_slots(corrupt):
    data = project_to_data(_project(_language()))
    corrupt(data["domain_workspace"]["language_definitions"][0])
    with pytest.raises(ProjectDecodeError, match="FORMAT_DOMAIN_INVALID"):
        project_from_data(data)


def test_incomplete_query_holes_remain_saveable_and_editable():
    language = _language()
    rule = replace(language.validators[0], predicate=QueryHole("predicate:hole"))
    project = _project(replace(language, validators=(rule,)))
    assert validate_integrity(project) == ()
    assert project_from_json(normalized_project_json(project)) == project


def test_language_history_recovers_whole_and_fine_grained_edits(tmp_path):
    project = _project()
    store = ProjectStore(tmp_path / "language")
    store.initialize(project)
    authority = ProjectAuthority(project, store=store)
    client = CodeVisualizerClient(authority, actor_id="author")
    original = _language()
    assert isinstance(client.submit(PutDomainLanguage(original)), CommandAccepted)
    updates = (
        PutDomainNotation(original.id, replace(original.notations[0], title="Custom form")),
        PutDomainValidator(
            original.id, replace(original.validators[0], message="A new validation message")
        ),
        PutDomainTransformation(original.id, replace(original.transformations[0], functions=())),
    )
    for command in updates:
        assert isinstance(client.submit(command), CommandAccepted)
    changed = authority.snapshot().domain_workspace
    recovered = ProjectAuthority(store.recover(), store=store)
    reopened = CodeVisualizerClient(recovered, actor_id="author")
    for _ in updates:
        assert isinstance(reopened.undo(), CommandAccepted)
    assert recovered.snapshot().domain_workspace.language(original.id) == original
    for _ in updates:
        assert isinstance(reopened.redo(), CommandAccepted)
    assert recovered.snapshot().domain_workspace == changed


@pytest.mark.parametrize("kind", ["language", "notation", "validator", "transformation"])
def test_definition_delete_undo_preserves_collection_order(kind):
    first, second = _language(), _language("other")
    first = replace(
        first,
        notations=(*first.notations, second.notations[0]),
        validators=(*first.validators, second.validators[0]),
        transformations=(*first.transformations, second.transformations[0]),
    )
    project = _project(first, _language("third"))
    authority = ProjectAuthority(project)
    client = CodeVisualizerClient(authority, actor_id="author")
    command = {
        "language": DeleteDomainLanguage(first.id),
        "notation": DeleteDomainNotation(first.id, first.notations[0].id),
        "validator": DeleteDomainValidator(first.id, first.validators[0].id),
        "transformation": DeleteDomainTransformation(
            first.id, first.transformations[0].definition.id
        ),
    }[kind]
    assert isinstance(client.submit(command), CommandAccepted)
    assert isinstance(client.undo(), CommandAccepted)
    assert authority.snapshot().domain_workspace == project.domain_workspace
    assert isinstance(client.redo(), CommandAccepted)
    assert isinstance(client.undo(), CommandAccepted)
    assert authority.snapshot().domain_workspace == project.domain_workspace


def test_language_ids_share_global_identity_and_revision_conflicts():
    authority = ProjectAuthority(_project())
    client = CodeVisualizerClient(authority, actor_id="author")
    language = _language()
    assert isinstance(
        client.submit(PutDomainLanguage(replace(language, id="project"))), CommandRejected
    )
    assert authority.revision == 0
    assert isinstance(
        client.submit(PutDomainLanguage(language), expected_revision=0), CommandAccepted
    )
    stale = client.submit(PutDomainLanguage(replace(language, title="Stale")), expected_revision=0)
    assert isinstance(stale, CommandRejected)
    assert stale.code == "REVISION_CONFLICT"
    duplicate = replace(language, validators=(replace(language.validators[0], id=language.id),))
    assert isinstance(client.submit(PutDomainLanguage(duplicate)), CommandRejected)
    assert authority.revision == 1


def test_automation_language_operations_use_the_same_authority():
    authority = ProjectAuthority(_project())
    service = AutomationService(authority)
    context = AutomationContext(
        "author", "author", AccessMode.COMMIT, frozenset(AutomationCapability)
    )
    try:
        result = service.dispatch(
            "domain.language.put",
            {"language": authored_language_to_data(_language()), "expected_revision": 0},
            context,
        )
        assert result["status"] == "accepted"
        assert authority.snapshot().domain_workspace.language("author:language") == _language()
        assert authority.revision == 1
        assert isinstance(
            CodeVisualizerClient(authority, actor_id="author").undo(), CommandAccepted
        )
        assert authority.snapshot().domain_workspace.language_definitions == ()
    finally:
        service.close()


def test_malformed_raw_command_is_rejected_without_mutation():
    authority = ProjectAuthority(_project())
    bad = authored_language_to_data(_language())
    bad["transformations"] = ["arbitrary Python"]
    result = authority.execute(
        CommandEnvelope("domain.language.put", "author", "invalid", "project", 0, {"language": bad})
    )
    assert isinstance(result, CommandRejected)
    assert result.code == "DOMAIN_LANGUAGE_PAYLOAD"
    assert authority.revision == 0


def test_language_codec_bounds_text_and_structure_before_accepting_data():
    from code_visualizer.persistence.language import (
        LanguageDecodeError,
        authored_language_from_data,
    )

    with pytest.raises(LanguageDecodeError, match="limits"):
        authored_language_to_data(replace(_language(), title="x" * 1_000_001))
    data = authored_language_to_data(_language())
    data["title"] = "x" * 1_000_001
    with pytest.raises(LanguageDecodeError, match="limits"):
        authored_language_from_data(data)
    deep = QueryLiteral("leaf", True)
    from code_visualizer.domain.language import QueryUnary, QueryUnaryOperator

    for index in range(130):
        deep = QueryUnary(f"not:{index}", QueryUnaryOperator.NOT, deep)
    language = _language()
    language = replace(language, validators=(replace(language.validators[0], predicate=deep),))
    with pytest.raises(LanguageDecodeError, match="limits"):
        authored_language_to_data(language)
