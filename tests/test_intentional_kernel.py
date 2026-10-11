"""Canonical domain ownership, schema rules and the existing authority history."""

from dataclasses import replace

import pytest
from python_persistence_fixtures import legacy_project_data

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.domain_commands import (
    CreateDomainNode,
    DeleteDomainBundleReference,
    DeleteDomainModel,
    DeleteDomainNode,
    DeleteDomainSchema,
    InsertDomainChild,
    MoveDomainChild,
    PutDomainModel,
    PutDomainSchema,
    RemoveDomainChild,
    RemoveDomainReference,
    SetDomainProperty,
    SetDomainReference,
)
from code_visualizer.application.messages import CommandAccepted, CommandEnvelope, CommandRejected
from code_visualizer.domain.intentional import (
    BundleReference,
    ConceptDefinition,
    ConstraintDefinition,
    ConstraintKind,
    DomainModel,
    DomainSchema,
    DomainWorkspace,
    IntentionalNode,
    PropertyDefinition,
    PropertyValue,
    RoleBinding,
    RoleDefinition,
    ValueKind,
)
from code_visualizer.domain.intentional_validation import validate_domain_workspace
from code_visualizer.domain.project import Project
from code_visualizer.extensions.registry import DomainExtensionRegistry
from code_visualizer.persistence.decoding import (
    ProjectDecodeError,
    project_from_data,
    project_from_json,
)
from code_visualizer.persistence.serialization import normalized_project_json, project_to_data
from code_visualizer.persistence.store import ProjectStore
from code_visualizer.sdk.client import CodeVisualizerClient
from code_visualizer.validation import validate_integrity, validate_project


def schema():
    return DomainSchema(
        "equipment",
        "example.equipment",
        "1",
        (
            ConceptDefinition(
                "rack",
                "Rack",
                (PropertyDefinition("rack_name", "Name"),),
                (RoleDefinition("units", "Units", ("unit",), 1, 2),),
                constraints=(
                    ConstraintDefinition(
                        "unique_name", ConstraintKind.UNIQUE_PROPERTY, "unit_name", "units"
                    ),
                ),
            ),
            ConceptDefinition(
                "unit",
                "Unit",
                (
                    PropertyDefinition("unit_name", "Name", required=True),
                    PropertyDefinition(
                        "voltage", "Voltage", ValueKind.NUMBER, default=12, minimum=0, maximum=240
                    ),
                ),
                reference_roles=(RoleDefinition("peer", "Peer", ("unit",), 0, 1),),
                constraints=(
                    ConstraintDefinition("nonempty_name", ConstraintKind.NONEMPTY, "unit_name"),
                ),
                display_property_id="unit_name",
            ),
        ),
    )


def project():
    root = IntentionalNode(
        "rack_one", "rack", children=(RoleBinding("units", ("unit_one", "unit_two")),)
    )
    first = IntentionalNode("unit_one", "unit", (PropertyValue("unit_name", "Sensor"),))
    second = IntentionalNode("unit_two", "unit", (PropertyValue("unit_name", "Actuator"),))
    model = DomainModel(
        "equipment_model", "equipment", "1", (root.id,), (root, first, second), "Equipment"
    )
    return Project(
        "project", "Domain kernel", (), domain_workspace=DomainWorkspace((schema(),), (model,))
    )


def _client(value=None, actor="human"):
    authority = ProjectAuthority(value or project())
    return authority, CodeVisualizerClient(authority, actor_id=actor)


def test_domain_schema_is_typed_and_valid_without_programming_constructs():
    value = project()
    assert value.program_model.functions == ()
    assert validate_domain_workspace(value.domain_workspace) == ()
    assert validate_integrity(value) == ()


@pytest.mark.parametrize(
    "replacement,code",
    [
        (
            PropertyDefinition("voltage", "Voltage", ValueKind.NUMBER, default="twelve"),
            "DOMAIN_PROPERTY_RULE_TYPE",
        ),
        (
            PropertyDefinition("voltage", "Voltage", ValueKind.STRING, minimum=0),
            "DOMAIN_PROPERTY_RANGE_TYPE",
        ),
        (
            PropertyDefinition("voltage", "Voltage", ValueKind.NUMBER, minimum=10, maximum=0),
            "DOMAIN_PROPERTY_RANGE",
        ),
    ],
)
def test_invalid_schema_property_rules_are_explicit(replacement, code):
    value = schema()
    concept = replace(value.concepts[1], properties=(value.concepts[1].properties[0], replacement))
    workspace = DomainWorkspace((replace(value, concepts=(value.concepts[0], concept)),))
    assert code in {item.code for item in validate_domain_workspace(workspace)}


def test_unknown_role_concepts_cardinality_and_schema_definition_identity_rejected():
    value = schema()
    root = replace(
        value.concepts[0], containment_roles=(RoleDefinition("units", "Units", ("missing",), 2, 1),)
    )
    changed = replace(value, concepts=(root, value.concepts[1], value.concepts[1]))
    codes = {item.code for item in validate_domain_workspace(DomainWorkspace((changed,)))}
    assert {"DOMAIN_DUPLICATE_ID", "DOMAIN_ROLE_CONCEPT", "DOMAIN_ROLE_CARDINALITY"} <= codes


def test_missing_required_values_are_saveable_but_block_build():
    value = project()
    model = value.domain_workspace.models[0]
    first = replace(model.nodes[1], properties=())
    model = replace(model, nodes=(model.nodes[0], first, model.nodes[2]))
    value = replace(value, domain_workspace=replace(value.domain_workspace, models=(model,)))
    assert not validate_integrity(value)
    assert project_from_json(normalized_project_json(value)) == value
    codes = {item.code for item in validate_project(value, extensions=DomainExtensionRegistry())}
    assert {"DOMAIN_PROPERTY_REQUIRED", "DOMAIN_CONSTRAINT_NONEMPTY"} <= codes


@pytest.mark.parametrize("value", [True, "12", float("inf")])
def test_declared_numeric_property_rejects_wrong_or_nonfinite_values(value):
    authority, client = _client()
    result = client.submit(SetDomainProperty("equipment_model", "unit_one", "voltage", value))
    assert isinstance(result, CommandRejected)
    assert authority.revision == 0


def test_rename_move_remove_insert_preserve_identity_and_exact_undo():
    authority, client = _client()
    original = authority.snapshot().domain_workspace
    assert isinstance(
        client.submit(SetDomainProperty("equipment_model", "unit_one", "unit_name", "Probe")),
        CommandAccepted,
    )
    assert isinstance(
        client.submit(RemoveDomainChild("equipment_model", "unit_one")), CommandAccepted
    )
    assert authority.snapshot().domain_workspace.models[0].roots == ("rack_one", "unit_one")
    assert isinstance(
        client.submit(InsertDomainChild("equipment_model", "unit_one", "rack_one", "units", 0)),
        CommandAccepted,
    )
    assert authority.snapshot().domain_workspace.node("unit_one").property("unit_name") == "Probe"
    for _ in range(3):
        assert isinstance(client.undo(), CommandAccepted)
    assert authority.snapshot().domain_workspace == original
    for _ in range(3):
        assert isinstance(client.redo(), CommandAccepted)
    assert len(authority.snapshot().domain_workspace.models[0].nodes) == 3


def test_disjoint_actor_edits_and_undo_restore_only_the_affected_node():
    authority, human = _client()
    agent = CodeVisualizerClient(authority, actor_id="agent")
    assert isinstance(
        human.submit(SetDomainProperty("equipment_model", "unit_one", "unit_name", "Probe")),
        CommandAccepted,
    )
    assert isinstance(
        agent.submit(SetDomainProperty("equipment_model", "unit_two", "unit_name", "Motor")),
        CommandAccepted,
    )
    assert isinstance(human.undo(), CommandAccepted)
    workspace = authority.snapshot().domain_workspace
    assert workspace.node("unit_one").property("unit_name") == "Sensor"
    assert workspace.node("unit_two").property("unit_name") == "Motor"


def test_containment_cycles_illegal_types_and_max_cardinality_do_not_commit():
    authority, client = _client()
    for command in (
        MoveDomainChild("equipment_model", "rack_one", "rack_one", "units"),
        CreateDomainNode("equipment_model", IntentionalNode("extra", "unit"), "rack_one", "units"),
    ):
        result = client.submit(command)
        assert isinstance(result, CommandRejected)
    assert authority.revision == 0
    model = project().domain_workspace.models[0]
    root = replace(
        model.nodes[0], children=(RoleBinding("units", ("rack_one", "unit_one", "unit_two")),)
    )
    malformed = replace(model, nodes=(root, *model.nodes[1:]))
    codes = {
        item.code for item in validate_domain_workspace(DomainWorkspace((schema(),), (malformed,)))
    }
    assert {
        "DOMAIN_CONTAINMENT_CYCLE",
        "DOMAIN_CONTAINMENT_OWNER",
        "DOMAIN_ROLE_TARGET_TYPE",
    } <= codes


def test_reference_graphs_can_cycle_but_never_dangle_and_delete_is_explicit():
    authority, client = _client()
    for source, target in (("unit_one", "unit_two"), ("unit_two", "unit_one")):
        assert isinstance(
            client.submit(SetDomainReference("equipment_model", source, "peer", (target,))),
            CommandAccepted,
        )
    assert isinstance(
        client.submit(DeleteDomainNode("equipment_model", "unit_one")), CommandRejected
    )
    assert isinstance(
        client.submit(SetDomainReference("equipment_model", "unit_one", "peer", ("missing",))),
        CommandRejected,
    )
    assert isinstance(
        client.submit(RemoveDomainReference("equipment_model", "unit_two", "peer")), CommandAccepted
    )
    assert isinstance(
        client.submit(DeleteDomainNode("equipment_model", "unit_one")), CommandAccepted
    )
    assert isinstance(client.undo(), CommandAccepted)
    assert authority.snapshot().domain_workspace.node("unit_one").reference_ids("peer") == (
        "unit_two",
    )


def test_create_defaults_atomic_transaction_and_history_recovery(tmp_path):
    empty = Project("project", "New", ())
    store = ProjectStore(tmp_path / "domains")
    store.initialize(empty)
    authority = ProjectAuthority(empty, store=store)
    client = CodeVisualizerClient(authority, actor_id="human")
    commands = (
        PutDomainSchema(schema()),
        PutDomainModel(DomainModel("equipment_model", "equipment", "1")),
        CreateDomainNode("equipment_model", IntentionalNode("root", "rack")),
        CreateDomainNode(
            "equipment_model",
            IntentionalNode("node", "unit", (PropertyValue("unit_name", "Probe"),)),
            "root",
            "units",
        ),
    )
    result = client.transaction(commands)
    assert isinstance(result, CommandAccepted)
    assert result.revision == 1
    node = authority.snapshot().domain_workspace.node("node")
    assert node.property("voltage") == 12
    recovered = ProjectAuthority(store.recover(), store=store)
    other = CodeVisualizerClient(recovered, actor_id="human")
    assert isinstance(other.undo(), CommandAccepted)
    assert recovered.snapshot().domain_workspace == DomainWorkspace()
    assert isinstance(other.redo(), CommandAccepted)
    assert recovered.snapshot().domain_workspace.node("node") == node


def test_native_roundtrip_migration_and_missing_extension_preserve_data():
    value = project()
    schema_value = replace(schema(), bundle=BundleReference("missing.domain", "7"))
    value = replace(
        value, domain_workspace=replace(value.domain_workspace, schemas=(schema_value,))
    )
    encoded = normalized_project_json(value)
    assert encoded == normalized_project_json(project_from_json(encoded))
    loaded = project_from_json(encoded)
    assert loaded == value
    diagnostics = validate_project(loaded, extensions=DomainExtensionRegistry())
    assert "DOMAIN_EXTENSION_MISSING" in {item.code for item in diagnostics}
    assert not validate_integrity(loaded)
    old = legacy_project_data(Project("old", "Revision 5", ()), 5)
    del old["domain_workspace"]
    migrated = project_from_data(old)
    assert migrated.format_revision == 11
    assert migrated.domain_workspace == DomainWorkspace()


def test_malformed_domain_codec_never_accepts_untyped_property_blob():
    data = project_to_data(project())
    data["domain_workspace"]["models"][0]["nodes"][1]["properties"][0]["value"] = {
        "callback": "arbitrary"
    }
    with pytest.raises(ProjectDecodeError, match="FORMAT_DOMAIN_INVALID"):
        project_from_data(data)


def test_shared_canonical_identity_namespace_rejects_domain_program_collision():
    value = project()
    model = value.domain_workspace.models[0]
    root = replace(model.nodes[0], id=value.id)
    model = replace(model, nodes=(root, *model.nodes[1:]), roots=(root.id,))
    value = replace(value, domain_workspace=replace(value.domain_workspace, models=(model,)))
    assert "DOMAIN_IDENTITY_COLLISION" in {item.code for item in validate_integrity(value)}


@pytest.mark.parametrize("kind", ["schema", "model", "bundle"])
def test_collection_deletion_undo_restores_original_order_and_exact_snapshot(kind):
    schema_a = DomainSchema("schema_a", "example.a", "1")
    schema_b = DomainSchema("schema_b", "example.b", "1")
    workspace = DomainWorkspace(
        schemas=(schema_a, schema_b),
        models=()
        if kind == "schema"
        else (
            DomainModel("model_a", schema_a.id, "1"),
            DomainModel("model_b", schema_b.id, "1"),
        ),
        bundle_references=(BundleReference("bundle_a", "1"), BundleReference("bundle_b", "1")),
    )
    value = Project("project", "Exact history", (), domain_workspace=workspace)
    authority, client = _client(value)
    command = {
        "schema": DeleteDomainSchema("schema_a"),
        "model": DeleteDomainModel("model_a"),
        "bundle": DeleteDomainBundleReference("bundle_a", "1"),
    }[kind]
    assert isinstance(client.submit(command), CommandAccepted)
    assert isinstance(client.undo(), CommandAccepted)
    restored = replace(authority.snapshot(), revision=value.revision)
    assert normalized_project_json(restored) == normalized_project_json(value)
    assert isinstance(client.redo(), CommandAccepted)
    assert isinstance(client.undo(), CommandAccepted)
    assert authority.snapshot().domain_workspace == workspace


def test_property_payload_must_explicitly_distinguish_unset_from_missing_value():
    authority, _client_value = _client()
    result = authority.execute(
        CommandEnvelope(
            "domain.node.set_property",
            "automation",
            "missing-value",
            "project",
            0,
            {"model_id": "equipment_model", "node_id": "unit_one", "property_id": "unit_name"},
        )
    )
    assert isinstance(result, CommandRejected)
    assert result.code == "DOMAIN_COMMAND_PAYLOAD"
    assert authority.snapshot().domain_workspace.node("unit_one").property("unit_name") == "Sensor"
