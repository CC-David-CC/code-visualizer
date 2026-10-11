"""Executable wire contracts preserve typed values and reuse authority semantics."""

import ast
import asyncio
import hashlib
import json
import math
from dataclasses import replace
from pathlib import Path

import pytest
from websockets.asyncio.client import connect

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.commands import RenameProject
from code_visualizer.application.domain_commands import (
    CreateDomainNode,
    DeleteDomainBundleReference,
    DeleteDomainConcept,
    DeleteDomainModel,
    DeleteDomainNode,
    DeleteDomainSchema,
    InsertDomainChild,
    MoveDomainChild,
    PromoteEvidenceObservation,
    PutDomainBundleReference,
    PutDomainConcept,
    PutDomainModel,
    PutDomainPropertyDefinition,
    PutDomainRoleDefinition,
    PutDomainSchema,
    RemoveDomainChild,
    RemoveDomainReference,
    SetDomainProperty,
    SetDomainReference,
)
from code_visualizer.application.messages import CommandEnvelope
from code_visualizer.automation.protobuf import dispatch_protobuf
from code_visualizer.automation.protocol import RpcError, command_from_params
from code_visualizer.automation.service import (
    AccessMode,
    AutomationCapability,
    AutomationContext,
    AutomationService,
)
from code_visualizer.automation.websocket import AutomationWebSocketServer
from code_visualizer.domain.computation import (
    BackendDefinition,
    CancelRequest,
    ComputationParameter,
    ComputationPlan,
    ComputationRequest,
    ComputationSession,
    ComputationStatus,
    ProgressEvent,
)
from code_visualizer.domain.evidence import (
    ComputationEvidence,
    ComputationOutcome,
    EvidenceArtifact,
    EvidenceDiagnostic,
    EvidenceObservation,
    EvidenceProvenance,
    ObservationEvent,
)
from code_visualizer.domain.intentional import (
    BundleReference,
    ConceptDefinition,
    DomainModel,
    DomainSchema,
    IntentionalNode,
    PropertyDefinition,
    PropertyValue,
    ValueKind,
)
from code_visualizer.domain.resources import (
    DataResource,
    ResourceAxis,
    ResourceLogicalTypeReference,
    TensorDescriptor,
)
from code_visualizer.domain.transformation import OriginLink, OriginMap, Representation
from code_visualizer.domain.values import (
    ComplexValue,
    Dimension,
    DimensionPower,
    QuantityValue,
    ResourceReference,
    TensorDType,
    TensorValue,
    UnitReference,
    ValueConstraints,
)
from code_visualizer.extensions.fsm import traffic_light_project
from code_visualizer.protocol.commands import command_from_proto, command_to_proto
from code_visualizer.protocol.computation import (
    backend_from_proto,
    backend_to_proto,
    cancel_from_proto,
    cancel_to_proto,
    computation_plan_from_proto,
    computation_plan_to_proto,
    computation_request_from_proto,
    computation_request_to_proto,
    progress_from_proto,
    progress_to_proto,
    session_from_proto,
    session_to_proto,
)
from code_visualizer.protocol.domain import (
    model_from_proto,
    model_to_proto,
    schema_from_proto,
    schema_to_proto,
)
from code_visualizer.protocol.evidence import (
    evidence_from_proto,
    evidence_to_proto,
    observation_event_from_proto,
    observation_event_to_proto,
)
from code_visualizer.protocol.resources import resource_from_proto, resource_to_proto
from code_visualizer.protocol.v1 import command_pb2, value_pb2
from code_visualizer.protocol.validation import ProtocolBoundaryError, parse_message
from code_visualizer.protocol.values import (
    canonical_value_from_proto,
    canonical_value_to_proto,
    constraints_from_proto,
    constraints_to_proto,
)

HASH = hashlib.sha256(b"portable resource").hexdigest()
UNIT = UnitReference("si:metre", "1", Dimension((DimensionPower("length", 1),)))
VALUES = (
    "",
    "measurement \u03b1",
    False,
    True,
    0,
    -1,
    1 << 63,
    -(1 << 100),
    (1 << 4096) - 1,
    0.0,
    -0.0,
    1.25,
    ComplexValue(-0.0, 2.0),
    QuantityValue(1 << 80, UNIT),
    QuantityValue(ComplexValue(2.0, -3.0), UNIT),
    TensorValue(TensorDType.BOOL, (2,), (False, True)),
    TensorValue(TensorDType.INT8, (2,), (-128, 127)),
    TensorValue(TensorDType.UINT64, (2,), (0, (1 << 64) - 1)),
    TensorValue(TensorDType.FLOAT32, (2,), (0.5, -0.0)),
    TensorValue(TensorDType.COMPLEX128, (1,), (ComplexValue(1.5, -2.0),)),
    TensorValue(TensorDType.FLOAT64, (0, 3), ()),
    ResourceReference("resource:field", HASH),
)


@pytest.mark.parametrize("value", VALUES)
def test_canonical_value_roundtrip_preserves_exact_types_and_components(value):
    message = canonical_value_to_proto(value)
    restored = canonical_value_from_proto(
        parse_message(message.SerializeToString(), value_pb2.CanonicalValue)
    )
    assert type(restored) is type(value)
    assert restored == value
    if isinstance(value, float):
        assert math.copysign(1, restored) == math.copysign(1, value)
    if isinstance(value, ComplexValue):
        assert math.copysign(1, restored.real) == math.copysign(1, value.real)


@pytest.mark.parametrize(
    ("value", "hexadecimal"),
    (
        (False, "08015800"),
        (True, "08015801"),
        ("", "08015200"),
        (0, "080162020800"),
        (-1, "080162020801"),
        (0.0, "0801690000000000000000"),
        (-0.0, "0801690000000000000080"),
    ),
)
def test_version_one_golden_value_wire_tags_are_stable(value, hexadecimal):
    assert canonical_value_to_proto(value).SerializeToString().hex() == hexadecimal
    assert (
        canonical_value_from_proto(
            parse_message(bytes.fromhex(hexadecimal), value_pb2.CanonicalValue)
        )
        == value
    )


def test_unknown_version_and_nested_fields_are_rejected_without_silent_loss():
    value = canonical_value_to_proto(4)
    value.schema_version = 2
    with pytest.raises(ProtocolBoundaryError, match="version"):
        canonical_value_from_proto(value)
    # Unknown field 100 with varint 1, including inside a known nested message.
    value = canonical_value_to_proto(4)
    value.integer.ParseFromString(value.integer.SerializeToString() + b"\xa0\x06\x01")
    with pytest.raises(ProtocolBoundaryError, match="fields"):
        canonical_value_from_proto(value)
    with pytest.raises(ProtocolBoundaryError, match="variant"):
        canonical_value_from_proto(value_pb2.CanonicalValue(schema_version=1))
    with pytest.raises(ProtocolBoundaryError, match="Malformed"):
        parse_message(b"\x80", value_pb2.CanonicalValue)


@pytest.mark.parametrize(
    "message",
    (
        value_pb2.CanonicalValue(schema_version=1, floating=float("nan")),
        value_pb2.CanonicalValue(schema_version=1, integer=value_pb2.IntegerValue(decimal="01")),
        value_pb2.CanonicalValue(schema_version=1, integer=value_pb2.IntegerValue(decimal="-0")),
        value_pb2.CanonicalValue(schema_version=1, integer=value_pb2.IntegerValue(decimal="1")),
        value_pb2.CanonicalValue(
            schema_version=1, tensor=value_pb2.TensorValue(dtype=100, shape=(0,))
        ),
        value_pb2.CanonicalValue(
            schema_version=1,
            tensor=value_pb2.TensorValue(
                dtype=value_pb2.TENSOR_INT8,
                shape=(1,),
                elements=(value_pb2.TensorElement(integer=value_pb2.IntegerValue(small=128)),),
            ),
        ),
    ),
)
def test_invalid_or_ambiguous_value_representations_reject(message):
    with pytest.raises(ValueError):
        canonical_value_from_proto(message)


def test_schema_model_and_constraint_roundtrip_keep_presence_and_order():
    project = traffic_light_project()
    schema = project.domain_workspace.schemas[0]
    model = project.domain_workspace.models[0]
    assert schema_from_proto(schema_to_proto(schema)) == schema
    assert model_from_proto(model_to_proto(model)) == model
    for constraints in (
        ValueConstraints(),
        ValueConstraints(Dimension()),
        ValueConstraints(UNIT.dimension, TensorDType.FLOAT64, (None, 0, 3)),
        ValueConstraints(tensor_shape=()),
    ):
        assert constraints_from_proto(constraints_to_proto(constraints)) == constraints


def test_rich_schema_defaults_choices_and_constraints_roundtrip_through_binary():
    tensor = TensorValue(TensorDType.FLOAT64, (2,), (0.0, -0.0))
    schema = DomainSchema(
        "measurements",
        "example.measurements",
        "1",
        (
            ConceptDefinition(
                "measurement",
                "Measurement",
                (
                    PropertyDefinition(
                        "quantity",
                        "Quantity",
                        ValueKind.QUANTITY,
                        True,
                        QuantityValue(0.0, UNIT),
                        (QuantityValue(0.0, UNIT),),
                        value_constraints=ValueConstraints(dimension=UNIT.dimension),
                    ),
                    PropertyDefinition(
                        "tensor",
                        "Tensor",
                        ValueKind.TENSOR,
                        False,
                        tensor,
                        value_constraints=ValueConstraints(
                            tensor_dtype=TensorDType.FLOAT64, tensor_shape=(None,)
                        ),
                    ),
                    PropertyDefinition("flag", "Flag", ValueKind.BOOLEAN, default=False),
                ),
            ),
        ),
    )
    model = DomainModel(
        "model",
        schema.id,
        schema.version,
        ("node",),
        (
            IntentionalNode(
                "node",
                "measurement",
                (
                    PropertyValue("quantity", QuantityValue(0.0, UNIT)),
                    PropertyValue("tensor", tensor),
                    PropertyValue("flag", False),
                ),
            ),
        ),
    )
    encoded_schema = schema_to_proto(schema)
    encoded_model = model_to_proto(model)
    assert (
        schema_from_proto(type(encoded_schema).FromString(encoded_schema.SerializeToString()))
        == schema
    )
    assert (
        model_from_proto(type(encoded_model).FromString(encoded_model.SerializeToString())) == model
    )


def test_resource_computation_and_evidence_preserve_pinned_provenance():
    resource = DataResource(
        "resource:field",
        HASH,
        16,
        "application/octet-stream",
        TensorDescriptor(TensorDType.FLOAT64, (2,), (ResourceAxis("x", "axis:x"),), UNIT),
        ResourceLogicalTypeReference("org.example.field", "1"),
    )
    assert resource_from_proto(resource_to_proto(resource)) == resource
    backend = BackendDefinition(
        "backend", "2", "Backend", Representation("schema", "3"), "schema", "3"
    )
    assert backend_from_proto(backend_to_proto(backend)) == backend
    configuration = (ComputationParameter("timestep", QuantityValue(0.5, UNIT)),)
    request = ComputationRequest(
        "project", 2, "backend", "2", "model", configuration, (1 << 63) - 1, (resource.reference,)
    )
    assert computation_request_from_proto(computation_request_to_proto(request)) == request
    provenance = EvidenceProvenance(
        "project",
        2,
        "model",
        "backend",
        "2",
        HASH,
        configuration,
        request.seed,
        request.resources,
        ("lower@1",),
        OriginMap("project", 2, (OriginLink("out", ("source",)),)),
    )
    evidence = ComputationEvidence(
        "evidence",
        provenance,
        ComputationOutcome.SUCCEEDED,
        (EvidenceObservation("observed", ("source",), VALUES[-3], "Amplitude", 0),),
        (EvidenceArtifact("artifact", resource.reference, ("source",), "Field"),),
        (EvidenceDiagnostic("INFO", "Completed", ("source",)),),
    )
    assert evidence_from_proto(evidence_to_proto(evidence)) == evidence
    portable = replace(
        evidence, provenance=replace(provenance, terminal_resource=resource.reference)
    )
    assert evidence_to_proto(portable).provenance.HasField("terminal_resource")
    assert not evidence_to_proto(evidence).provenance.HasField("terminal_resource")
    assert evidence_from_proto(evidence_to_proto(portable)) == portable
    promotion = PromoteEvidenceObservation("model", "node", "property", evidence, "observed")
    encoded = command_to_proto(
        promotion,
        actor_id="actor",
        operation_id="promote",
        project_id="project",
        expected_revision=2,
    )
    assert encoded.WhichOneof("command") == "promote_evidence"
    assert command_from_proto(encoded).payload == promotion.to_operation().payload


def test_unknown_version_rejects_across_all_public_root_contracts():
    schema = schema_to_proto(traffic_light_project().domain_workspace.schemas[0])
    schema.schema_version = 99
    with pytest.raises(ProtocolBoundaryError, match="version"):
        schema_from_proto(schema)
    resource = resource_to_proto(DataResource("resource", HASH, 0, "application/octet-stream"))
    resource.schema_version = 99
    with pytest.raises(ProtocolBoundaryError, match="version"):
        resource_from_proto(resource)
    request = computation_request_to_proto(ComputationRequest("project", 0, "backend", "1"))
    request.schema_version = 99
    with pytest.raises(ProtocolBoundaryError, match="version"):
        computation_request_from_proto(request)
    with pytest.raises(ProtocolBoundaryError, match="2 MiB"):
        parse_message(b"0" * (2 * 1024 * 1024 + 1), value_pb2.CanonicalValue)


def test_plan_session_events_and_cancel_contracts_roundtrip():
    request = ComputationRequest("project", 2, "backend", "1", "model")
    origins = OriginMap("project", 2, (OriginLink("out", ("source",)),))
    plan = ComputationPlan(
        request,
        Representation("terminal", "3"),
        ResourceReference("model-resource", HASH),
        ("transform@1",),
        origins,
        HASH,
    )
    encoded = computation_plan_to_proto(plan)
    assert (
        computation_plan_from_proto(type(encoded).FromString(encoded.SerializeToString())) == plan
    )
    for status in ComputationStatus:
        session = ComputationSession(
            "session",
            "project",
            2,
            "backend",
            "1",
            status,
            False,
            "evidence" if status is ComputationStatus.SUCCEEDED else None,
        )
        assert session_from_proto(session_to_proto(session)) == session
    for progress in (
        ProgressEvent("session", 0, 0.0),
        ProgressEvent("session", 1, 0.5, 1.0, "Working"),
    ):
        assert progress_from_proto(progress_to_proto(progress)) == progress
    cancellation = CancelRequest("session", "User request")
    assert cancel_from_proto(cancel_to_proto(cancellation)) == cancellation
    observed = ObservationEvent(
        "session", EvidenceObservation("sample", ("source",), QuantityValue(2.0, UNIT))
    )
    assert observation_event_from_proto(observation_event_to_proto(observed)) == observed


def _commands():
    project = traffic_light_project()
    schema, model = project.domain_workspace.schemas[0], project.domain_workspace.models[0]
    concept = schema.concepts[0]
    return (
        PutDomainSchema(schema),
        DeleteDomainSchema(schema.id),
        PutDomainModel(model),
        DeleteDomainModel(model.id),
        PutDomainConcept(schema.id, concept),
        DeleteDomainConcept(schema.id, concept.id),
        PutDomainPropertyDefinition(schema.id, concept.id, concept.properties[0]),
        PutDomainRoleDefinition(schema.id, concept.id, concept.containment_roles[0], False),
        CreateDomainNode(model.id, model.nodes[0]),
        CreateDomainNode(model.id, model.nodes[0], "parent", "role", 0),
        DeleteDomainNode(model.id, model.nodes[0].id),
        SetDomainProperty(model.id, "node", "prop", None),
        *(SetDomainProperty(model.id, "node", "prop", value) for value in VALUES),
        MoveDomainChild(model.id, "node", None, None),
        InsertDomainChild(model.id, "node", "parent", "role", 3),
        RemoveDomainChild(model.id, "node"),
        SetDomainReference(model.id, "node", "role", ("a", "b")),
        RemoveDomainReference(model.id, "node", "role"),
        RemoveDomainReference(model.id, "node", "role", "a"),
        PutDomainBundleReference(BundleReference("bundle", "1")),
        DeleteDomainBundleReference("bundle", "1"),
    )


@pytest.mark.parametrize("command", _commands())
def test_typed_commands_preserve_authority_operations(command):
    wire = command_to_proto(
        command,
        actor_id="actor",
        operation_id="operation",
        project_id="project",
        expected_revision=0,
        transaction_id="transaction",
        intent="Human intent",
    )
    restored = command_from_proto(
        parse_message(wire.SerializeToString(), command_pb2.CommandEnvelope)
    )
    operation = command.to_operation()
    assert restored == CommandEnvelope(
        operation.command_type,
        "actor",
        "operation",
        "project",
        0,
        operation.payload,
        transaction_id="transaction",
        intent="Human intent",
    )


def test_all_authority_entry_paths_reject_unknown_envelope_versions():
    project = traffic_light_project()
    authority = ProjectAuthority(project)
    operation = RenameProject("Changed").to_operation()
    command = CommandEnvelope(
        operation.command_type, "actor", "op", project.id, 0, operation.payload, schema_version=2
    )
    assert authority.execute(command).code == "COMMAND_VERSION_UNSUPPORTED"
    result = authority.execute_transaction(
        (command,), actor_id="actor", operation_id="tx", expected_revision=0
    )
    assert result.code == "COMMAND_VERSION_UNSUPPORTED"
    assert authority.snapshot() == project
    with pytest.raises(RpcError, match="version"):
        command_from_params(
            {"command_type": operation.command_type, "operation_id": "op", "schema_version": 2},
            actor_id="actor",
            project_id=project.id,
        )


def test_binary_dispatch_reuses_grants_revisions_undo_and_identity():
    project = traffic_light_project()
    service = AutomationService(ProjectAuthority(project))
    context = AutomationContext(
        "actor", "session", AccessMode.COMMIT, frozenset(AutomationCapability)
    )
    wire = command_to_proto(
        SetDomainProperty("traffic:model", "traffic:green", "fsm:state:name", "Emerald"),
        actor_id="actor",
        operation_id="rename",
        project_id=project.id,
        expected_revision=0,
    )
    try:
        denied = dispatch_protobuf(
            service,
            wire.SerializeToString(),
            replace(context, capabilities=frozenset({AutomationCapability.READ})),
        )
        assert command_pb2.CommandResponse.FromString(denied).WhichOneof("result") == "error"
        spoofed = dispatch_protobuf(
            service, wire.SerializeToString(), replace(context, actor_id="other")
        )
        assert command_pb2.CommandResponse.FromString(spoofed).WhichOneof("result") == "error"
        accepted = command_pb2.CommandResponse.FromString(
            dispatch_protobuf(service, wire.SerializeToString(), context)
        )
        assert accepted.WhichOneof("result") == "accepted"
        assert accepted.accepted.revision == 1
        assert (
            service.authority.snapshot()
            .domain_workspace.node("traffic:green")
            .property("fsm:state:name")
            == "Emerald"
        )
        duplicate = command_pb2.CommandResponse.FromString(
            dispatch_protobuf(service, wire.SerializeToString(), context)
        )
        assert duplicate == accepted
        wire.operation_id = "stale"
        stale = command_pb2.CommandResponse.FromString(
            dispatch_protobuf(service, wire.SerializeToString(), context)
        )
        assert stale.rejected.code == "REVISION_CONFLICT"
        undo = command_pb2.CommandEnvelope(
            schema_version=1,
            actor_id="actor",
            operation_id="undo",
            project_id=project.id,
            expected_revision=1,
            undo=command_pb2.HistoryCommand(),
        )
        response = command_pb2.CommandResponse.FromString(
            dispatch_protobuf(service, undo.SerializeToString(), context)
        )
        assert response.accepted.revision == 2
        assert service.authority.snapshot().domain_workspace == project.domain_workspace
    finally:
        service.close()


def test_authenticated_websocket_negotiates_binary_on_existing_endpoint():
    project = traffic_light_project()
    service = AutomationService(ProjectAuthority(project))
    server = AutomationWebSocketServer(service)

    async def scenario():
        await server.start()
        try:
            async with connect(
                server.endpoint, additional_headers={"Authorization": "Bearer " + server.token}
            ) as connection:
                await connection.send(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "service.initialize",
                            "params": {"actor_id": "actor", "binary_protocol": "protobuf.v1"},
                        }
                    )
                )
                initialized = json.loads(await connection.recv())
                assert initialized["result"]["binary_protocol"] == "protobuf.v1"
                command = command_to_proto(
                    SetDomainProperty(
                        "traffic:model", "traffic:green", "fsm:state:name", "Emerald"
                    ),
                    actor_id="actor",
                    operation_id="binary",
                    project_id=project.id,
                    expected_revision=0,
                )
                await connection.send(command.SerializeToString())
                raw = await connection.recv()
                assert isinstance(raw, bytes)
                assert command_pb2.CommandResponse.FromString(raw).accepted.revision == 1
        finally:
            await server.stop()

    try:
        asyncio.run(scenario())
    finally:
        service.close()


def test_canonical_domain_does_not_depend_on_protobuf_or_external_contracts():
    source = Path(__file__).resolve().parents[1] / "src" / "code_visualizer" / "domain"
    for path in source.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            assert not any(
                name.startswith(("google.protobuf", "code_visualizer.protocol")) for name in modules
            ), path


def test_contracts_have_no_untyped_struct_or_any_payloads():
    from code_visualizer.protocol.v1 import (
        computation_pb2,
        domain_pb2,
        evidence_pb2,
        identity_pb2,
        resource_pb2,
    )

    for module in (
        value_pb2,
        command_pb2,
        computation_pb2,
        domain_pb2,
        evidence_pb2,
        identity_pb2,
        resource_pb2,
    ):
        for message in module.DESCRIPTOR.message_types_by_name.values():
            for field in message.fields:
                if field.message_type is not None:
                    assert field.message_type.full_name not in {
                        "google.protobuf.Any",
                        "google.protobuf.Struct",
                    }
