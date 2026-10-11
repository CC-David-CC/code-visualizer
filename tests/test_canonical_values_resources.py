"""Universal value/resource boundaries, authority admission and durable evidence."""

from dataclasses import replace
from hashlib import sha256

import pytest

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.domain_commands import (
    PromoteEvidenceObservation,
    SetDomainProperty,
)
from code_visualizer.application.messages import CommandAccepted, CommandRejected
from code_visualizer.domain.evidence import (
    ComputationEvidence,
    ComputationOutcome,
    EvidenceObservation,
    EvidenceProvenance,
)
from code_visualizer.domain.intentional import (
    ConceptDefinition,
    DomainModel,
    DomainSchema,
    DomainWorkspace,
    IntentionalNode,
    PropertyDefinition,
    PropertyValue,
    ValueKind,
)
from code_visualizer.domain.intentional_validation import validate_domain_workspace
from code_visualizer.domain.project import Project
from code_visualizer.domain.resources import ResourceAxis, TensorDescriptor
from code_visualizer.domain.transformation import OriginMap
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
    validate_canonical_value,
)
from code_visualizer.generation.transformation import value_identities
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.evidence import (
    evidence_content_hash,
    evidence_from_data,
    evidence_to_data,
)
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.serialization import normalized_project_json
from code_visualizer.persistence.store import ProjectStore
from code_visualizer.persistence.values import canonical_value_from_data, canonical_value_to_data
from code_visualizer.sdk.client import CodeVisualizerClient

DIMENSION = Dimension((DimensionPower("example:length", 1),))
UNIT = UnitReference("example:metre", "1", DIMENSION)
TENSOR = TensorValue(TensorDType.FLOAT64, (2, 2), (1.0, 2.0, 3.0, 4.0))


def value_project(kind=ValueKind.TENSOR, value=TENSOR, constraints=None):
    schema = DomainSchema(
        "schema",
        "example.values",
        "1",
        (
            ConceptDefinition(
                "concept",
                "Sample",
                (
                    PropertyDefinition(
                        "value", "Value", kind, value_constraints=constraints or ValueConstraints()
                    ),
                ),
            ),
        ),
    )
    model = DomainModel(
        "model",
        schema.id,
        schema.version,
        ("sample",),
        (IntentionalNode("sample", "concept", (PropertyValue("value", value),)),),
    )
    return Project(
        "project:values", "Values", (), domain_workspace=DomainWorkspace((schema,), (model,))
    )


@pytest.mark.parametrize(
    "value",
    [
        "",
        "λ\n",
        False,
        0,
        1 << 2048,
        -0.0,
        1.5,
        ComplexValue(1.0, -2.0),
        QuantityValue(2, UNIT),
        QuantityValue(ComplexValue(0.0, 1.0), UNIT),
        TENSOR,
        TensorValue(TensorDType.UINT64, (1,), ((1 << 64) - 1,)),
        TensorValue(TensorDType.BOOL, (0, 5), ()),
        ResourceReference("result", "a" * 64),
    ],
)
def test_closed_value_round_trip_preserves_variant_and_deterministic_bytes(value):
    data = canonical_value_to_data(value)
    restored = canonical_value_from_data(data)
    assert restored == value
    assert type(restored) is type(value)
    assert canonical_data_bytes(data) == canonical_data_bytes(canonical_value_to_data(restored))
    if type(value) is float:
        assert restored.hex() == value.hex()


@pytest.mark.parametrize(
    "value",
    [None, [], {}, b"data", complex(1, 2), float("inf"), float("nan"), "x" * 65537, 1 << 4096],
    ids=[
        "none",
        "list",
        "dict",
        "bytes",
        "python-complex",
        "infinity",
        "nan",
        "large-text",
        "large-integer",
    ],
)
def test_canonical_admission_rejects_untyped_nonfinite_and_oversized_values(value):
    with pytest.raises(ValueError):
        validate_canonical_value(value)
    with pytest.raises(ValueError):
        canonical_value_from_data(value)


@pytest.mark.parametrize(
    "dtype,shape,elements",
    [
        (TensorDType.INT8, (1,), (128,)),
        (TensorDType.UINT8, (1,), (-1,)),
        (TensorDType.INT32, (1,), (True,)),
        (TensorDType.FLOAT64, (1,), (1,)),
        (TensorDType.FLOAT32, (1,), (0.1,)),
        (TensorDType.FLOAT64, (1,), (float("nan"),)),
        (TensorDType.FLOAT64, (2,), (1.0,)),
        (TensorDType.FLOAT64, (-1,), ()),
        (TensorDType.FLOAT64, (1025,), (0.0,) * 1025),
        (TensorDType.BOOL, (1,) * 17, (True,)),
        (TensorDType.BOOL, [1], (True,)),
        (TensorDType.BOOL, (1,), [True]),
    ],
)
def test_tensor_contract_rejects_invalid_shape_dtype_size_and_mutability(dtype, shape, elements):
    with pytest.raises(ValueError):
        TensorValue(dtype, shape, elements)


def test_rich_value_versions_and_unknown_fields_fail_explicitly():
    data = canonical_value_to_data(TENSOR)
    with pytest.raises(ValueError, match="version"):
        canonical_value_from_data({**data, "version": 2})
    with pytest.raises(ValueError, match="Unknown fields"):
        canonical_value_from_data({**data, "units": "invented"})
    with pytest.raises(ValueError, match="magnitude"):
        QuantityValue(TENSOR, UNIT)
    with pytest.raises(ValueError, match="sorted"):
        Dimension((DimensionPower("z", 1), DimensionPower("a", 1)))


def test_quantity_dimension_and_tensor_contracts_are_generic_schema_rules():
    project = value_project(
        ValueKind.QUANTITY, QuantityValue(2, UNIT), ValueConstraints(dimension=DIMENSION)
    )
    assert validate_domain_workspace(project.domain_workspace) == ()
    bad = value_project(
        ValueKind.QUANTITY, QuantityValue(2, UNIT), ValueConstraints(dimension=Dimension())
    )
    assert {issue.code for issue in validate_domain_workspace(bad.domain_workspace)} == {
        "DOMAIN_PROPERTY_TYPE"
    }
    for constraints in (
        ValueConstraints(tensor_shape=(3, 3)),
        ValueConstraints(tensor_dtype=TensorDType.INT64),
    ):
        assert {
            issue.code
            for issue in validate_domain_workspace(
                value_project(constraints=constraints).domain_workspace
            )
        } == {"DOMAIN_PROPERTY_TYPE"}
    assert not validate_domain_workspace(
        value_project(constraints=ValueConstraints(tensor_shape=(None, 2))).domain_workspace
    )


def test_rich_value_authority_undo_redo_and_persistence(tmp_path):
    project = value_project()
    store = ProjectStore(tmp_path)
    store.initialize(project)
    authority = ProjectAuthority(project, store=store)
    client = CodeVisualizerClient(authority, actor_id="author")
    changed = replace(TENSOR, elements=(9.0, 2.0, 3.0, 4.0))
    assert isinstance(
        client.submit(SetDomainProperty("model", "sample", "value", changed)), CommandAccepted
    )
    assert authority.snapshot().domain_workspace.node("sample").property("value") == changed
    assert isinstance(client.undo(), CommandAccepted)
    assert authority.snapshot().domain_workspace.node("sample").property("value") == TENSOR
    assert isinstance(client.redo(), CommandAccepted)
    serialized = normalized_project_json(authority.snapshot())
    assert normalized_project_json(project_from_json(serialized)) == serialized
    assert "resource:" not in value_identities(
        value_project(ValueKind.RESOURCE, ResourceReference("resource:", "a" * 64))
    )


def test_resource_store_streaming_deduplication_descriptors_and_integrity(tmp_path):
    store = ResourceStore(tmp_path)
    payload = b"opaque tensor file" * 10000
    descriptor = store.put(
        payload,
        "application/octet-stream",
        tensor=TensorDescriptor(
            TensorDType.FLOAT64, (2, 2), (ResourceAxis("row"), ResourceAxis("column"))
        ),
    )
    assert descriptor.content_hash == sha256(payload).hexdigest()
    assert store.put(payload, descriptor.media_type, tensor=descriptor.tensor) == descriptor
    different = store.put(
        payload, descriptor.media_type, tensor=TensorDescriptor(TensorDType.FLOAT64, (4,))
    )
    assert different.content_hash == descriptor.content_hash
    assert different.id != descriptor.id
    path = tmp_path / "input.bin"
    path.write_bytes(payload)
    assert store.import_file(path, descriptor.media_type, tensor=descriptor.tensor) == descriptor
    assert store.read(descriptor.reference) == payload
    with pytest.raises(ValueError, match="managed descriptor"):
        store.read(ResourceReference("../../escape", descriptor.content_hash))
    store.verified_path(descriptor.reference).write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="hash"):
        store.read(descriptor.reference)


def evidence(project, value=TENSOR):
    record = ComputationEvidence(
        "pending",
        EvidenceProvenance(
            project.id,
            project.revision,
            "model",
            "backend:test",
            "1",
            "a" * 64,
            (),
            42,
            (),
            (),
            OriginMap(project.id, project.revision),
        ),
        ComputationOutcome.SUCCEEDED,
        (EvidenceObservation("observation", ("sample",), value),),
    )
    return replace(record, id="evidence:" + evidence_content_hash(record))


def test_evidence_is_immutable_and_explicit_promotion_uses_the_same_authority(tmp_path):
    project = value_project()
    changed = replace(TENSOR, elements=(9.0, 2.0, 3.0, 4.0))
    record = evidence(project, changed)
    store = EvidenceStore(tmp_path)
    path = store.put(record)
    assert store.put(record) == path
    assert store.get(record.id) == evidence_from_data(evidence_to_data(record)) == record
    authority = ProjectAuthority(project)
    client = CodeVisualizerClient(authority, actor_id="author")
    assert authority.snapshot() == project
    result = client.submit(
        PromoteEvidenceObservation("model", "sample", "value", record, "observation")
    )
    assert isinstance(result, CommandAccepted)
    assert result.events[0].payload["evidence_id"] == record.id
    assert authority.snapshot().domain_workspace.node("sample").property("value") == changed
    assert record.id not in normalized_project_json(authority.snapshot())
    assert isinstance(client.undo(), CommandAccepted)
    assert authority.snapshot().domain_workspace.node("sample").property("value") == TENSOR
    assert isinstance(client.redo(), CommandAccepted)
    assert authority.snapshot().domain_workspace.node("sample").property("value") == changed
    forged = replace(record, observations=(replace(record.observations[0], value=TENSOR),))
    result = client.submit(
        PromoteEvidenceObservation("model", "sample", "value", forged, "observation")
    )
    assert isinstance(result, CommandRejected)
    assert result.code == "EVIDENCE_CONTENT_HASH"
    with pytest.raises(ValueError, match="hash"):
        store.put(forged)


def test_queries_traverse_explicit_cross_model_inputs_without_copying_values():
    from code_visualizer.domain import language as lang
    from code_visualizer.domain.intentional import RoleBinding, RoleDefinition
    from code_visualizer.domain.language_validation import LanguageTypeChecker, QueryType
    from code_visualizer.generation.language import LanguageEvaluationError, evaluate_query

    project = value_project()
    source_schema = DomainSchema(
        "request-schema",
        "example.request",
        "1",
        (
            ConceptDefinition(
                "request-concept",
                "Request",
                reference_roles=(RoleDefinition("input", "Input", ("concept",), 1, 1),),
            ),
        ),
    )
    source = IntentionalNode(
        "request", "request-concept", references=(RoleBinding("input", ("sample",)),)
    )
    source_model = DomainModel("requests", source_schema.id, "1", (source.id,), (source,))
    workspace = replace(
        project.domain_workspace,
        schemas=(*project.domain_workspace.schemas, source_schema),
        models=(*project.domain_workspace.models, source_model),
    )
    query = lang.QueryProperty(
        "q-property",
        lang.QueryUnary(
            "q-first",
            lang.QueryUnaryOperator.FIRST,
            lang.QueryRole("q-input", lang.QueryVariable("q-source", "source"), "input"),
        ),
        "value",
    )
    checker = LanguageTypeChecker(source_schema, workspace.schemas)
    assert (
        checker.query(query, {"source": QueryType("node", ("request-concept",))}).kind == "tensor"
    )
    assert not checker.issues
    assert (
        evaluate_query(query, source_schema, source_model, {"source": source}, workspace=workspace)
        is TENSOR
    )
    assert (
        evaluate_query(
            lang.QueryNodes("q-local", "concept"), source_schema, source_model, workspace=workspace
        )
        == ()
    )
    with pytest.raises(LanguageEvaluationError, match="supplied input workspace"):
        evaluate_query(query, source_schema, source_model, {"source": source})
    assert len(workspace.models[0].nodes) == len(source_model.nodes) == 1


def test_authored_intermediate_template_preserves_tensor_and_origin():
    from code_visualizer.domain import language as lang
    from code_visualizer.domain.transformation import Representation, TransformationDefinition
    from code_visualizer.generation.language import compile_authored_transformation
    from code_visualizer.generation.transformation import TransformationInput

    project = value_project()
    source = project.domain_workspace.schemas[0]
    target = DomainSchema(
        "target-schema",
        "example.tensor-ir",
        "1",
        (
            ConceptDefinition(
                "target-concept",
                "Tensor operand",
                (PropertyDefinition("target-value", "Value", ValueKind.TENSOR),),
            ),
        ),
    )
    recipe = lang.AuthoredTransformation(
        TransformationDefinition(
            "copy-tensor",
            "1",
            Representation(source.namespace, "1"),
            Representation(target.namespace, "1"),
        ),
        domain=lang.DomainTemplate(
            "template",
            target.id,
            target.version,
            (
                lang.DomainNodeTemplate(
                    "emit",
                    lang.QueryNodes("select", "concept"),
                    "source",
                    "target-concept",
                    (
                        lang.DomainPropertyTemplate(
                            "emit-value",
                            "target-value",
                            lang.QueryProperty(
                                "property", lang.QueryVariable("bound", "source"), "value"
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    language = lang.AuthoredDomainLanguage(
        "language", source.id, source.version, transformations=(recipe,)
    )
    project = replace(
        project,
        domain_workspace=replace(
            project.domain_workspace, schemas=(source, target), language_definitions=(language,)
        ),
    )
    transform = compile_authored_transformation(
        language, source, recipe, schemas=project.domain_workspace.schemas
    )
    model = project.domain_workspace.models[0]
    snapshot = TransformationInput(
        project, model, recipe.definition.source, model, OriginMap(project.id, project.revision)
    )
    result = transform.transform(snapshot)
    assert result == transform.transform(snapshot)
    assert result.value.nodes[0].property("target-value") == TENSOR
    assert result.origins.sources(result.value.nodes[0].id) == ("sample",)
    assert project.domain_workspace.models == (model,)


def test_automation_preserves_compound_value_tags_and_attaches_saved_stores(tmp_path):
    # Generic dataclass capability results must not erase a nested value's tag.
    from dataclasses import make_dataclass

    from code_visualizer.automation.service import AutomationService, _capability_json_value

    result_type = make_dataclass("CapabilityResult", [("value", object)], frozen=True)
    encoded = _capability_json_value(result_type(TENSOR))
    assert canonical_value_from_data(encoded["value"]) == TENSOR
    service = AutomationService(ProjectAuthority(value_project()), project_root=lambda: tmp_path)
    assert service.kernel.resource_store.root == tmp_path.resolve() / "resources"
    assert service.kernel.evidence_store.root == tmp_path.resolve() / "evidence"
    service.close()
