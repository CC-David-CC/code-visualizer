"""Computation terminals, immutable evidence, and runtime origins share one authority."""

from dataclasses import replace

import pytest
from computation_fixtures import InProcessTestKernel

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.computation import (
    execute_computation,
    export_computation_plan,
    get_evidence,
    run_computation_plan,
)
from code_visualizer.application.domain_workbench import workbench_snapshot
from code_visualizer.application.examples import example_session
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.domain.computation import (
    BackendDefinition,
    ComputationParameter,
    ComputationRequest,
)
from code_visualizer.domain.evidence import (
    ComputationOutcome,
    EvidenceArtifact,
    EvidenceObservation,
)
from code_visualizer.domain.intentional import (
    BundleReference,
    ConceptDefinition,
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
from code_visualizer.domain.program import ExpressionRole, make_program_expression
from code_visualizer.domain.project import Project
from code_visualizer.domain.transformation import (
    PROGRAM_REPRESENTATION,
    OriginLink,
    OriginMap,
    Representation,
    TransformationDefinition,
)
from code_visualizer.domain.values import ResourceReference
from code_visualizer.execution.backends import (
    BackendResult,
    PreparedComputation,
    ProducedResource,
    RegisteredBackend,
)
from code_visualizer.extensions.builtin import (
    computation_bundle,
    intentional_bundle,
    program_bundle,
)
from code_visualizer.extensions.registry import DomainExtensionBundle, DomainExtensionRegistry
from code_visualizer.generation import generate_python
from code_visualizer.generation.build import prepare_build
from code_visualizer.generation.computation import prepare_computation
from code_visualizer.generation.transformation import (
    RegisteredTransformation,
    TransformationError,
    TransformationResult,
)
from code_visualizer.persistence import ProjectStore
from code_visualizer.persistence.computation import (
    computation_plan_from_data,
    computation_plan_to_data,
    computation_request_from_data,
    computation_request_to_data,
)
from code_visualizer.persistence.evidence import evidence_from_data, evidence_to_data
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.serialization import project_to_data


def _schema(identity: str) -> DomainSchema:
    return DomainSchema(
        identity,
        identity,
        "1",
        (
            ConceptDefinition(
                identity + ":value",
                "Value",
                (
                    PropertyDefinition(
                        identity + ":amount", "Amount", ValueKind.INTEGER, required=True
                    ),
                ),
            ),
        ),
    )


def _source() -> Project:
    schema, terminal = _schema("source"), _schema("terminal")
    model = DomainModel(
        "source:model",
        schema.id,
        "1",
        ("source:node",),
        (IntentionalNode("source:node", "source:value", (PropertyValue("source:amount", 3),)),),
    )
    return Project(
        "computation-project",
        "Computation proof",
        (),
        domain_workspace=DomainWorkspace((schema, terminal), (model,)),
    )


def _transform(snapshot) -> TransformationResult:
    node = snapshot.model.nodes[0]
    terminal = DomainModel(
        "derived:model",
        "terminal",
        "1",
        ("derived:node",),
        (
            IntentionalNode(
                "derived:node",
                "terminal:value",
                (PropertyValue("terminal:amount", node.property("source:amount")),),
            ),
        ),
    )
    return TransformationResult(
        Representation("terminal"),
        terminal,
        OriginMap(
            snapshot.project.id,
            snapshot.project.revision,
            (OriginLink(terminal.id, (node.id,)), OriginLink("derived:node", (node.id,))),
        ),
    )


def _backend(snapshot: PreparedComputation) -> BackendResult:
    assert isinstance(snapshot.value, DomainModel)
    node = snapshot.value.nodes[0]
    amount = node.property("terminal:amount")
    assert isinstance(amount, int)
    return BackendResult(
        observations=(EvidenceObservation("result", (node.id,), amount * 2, "Result"),)
    )


def _registry(implementation=_backend, *, steps=None) -> DomainExtensionRegistry:
    transformation = RegisteredTransformation(
        TransformationDefinition(
            "to-terminal", "1", Representation("source"), Representation("terminal")
        ),
        _transform,
        "source",
        "1",
        "terminal",
        "1",
    )
    backend = RegisteredBackend(
        BackendDefinition(
            "test.backend", "1", "Terminal evaluator", Representation("terminal"), "terminal", "1"
        ),
        implementation,
    )
    return DomainExtensionRegistry(
        (
            computation_bundle(),
            program_bundle(),
            intentional_bundle(),
            DomainExtensionBundle(
                "test.computation",
                "1",
                transformations=(transformation,) if steps is None else steps,
                backends=(backend,),
            ),
        )
    )


def _request(project: Project) -> ComputationRequest:
    return ComputationRequest(
        project.id, project.revision, "test.backend", "1", "source:model", seed=42
    )


def test_non_python_terminal_evidence_is_deterministic_disposable_and_projected(
    tmp_path, monkeypatch
):
    project, registry = _source(), _registry()
    before = project_to_data(project)
    kernel = InProcessTestKernel(
        ProjectAuthority(project),
        extensions=registry,
        evidence_store=EvidenceStore(tmp_path),
        resource_store=ResourceStore(tmp_path),
    )
    monkeypatch.setattr(
        "code_visualizer.generation.lowering.lower_project",
        lambda *_a, **_k: pytest.fail("Direct domain backend reached programming-domain lowering"),
    )
    snapshot = prepare_computation(project, _request(project), registry)
    assert snapshot.transformations == ("to-terminal@1",)
    assert snapshot.origins.sources("derived:node") == ("source:node",)
    first = execute_computation(kernel, _request(project))
    second = execute_computation(kernel, _request(project))
    assert first == second
    assert first.observations[0].value == 6
    assert first.provenance.seed == 42
    assert evidence_from_data(evidence_to_data(first)) == first
    assert get_evidence(kernel, first.id) == first
    assert project_to_data(kernel.authority.snapshot()) == before
    assert len(kernel.authority.snapshot().domain_workspace.models) == 1
    assert kernel.runtime.active is not None
    assert "source:node" in kernel.runtime.active.active_ids
    for notation in kernel.notations("source:model"):
        projected = kernel.notation("source:model", notation.id)
        assert projected.runtime_revision == project.revision
        assert any(
            node.semantic_id == "source:node" and "active" in node.badges
            for node in projected.graph.nodes
        )
        assert any(node.node_id == "source:node" and node.active for node in projected.roots)
        if projected.rows:
            assert projected.rows[0].active
    assert kernel.selection.state.semantic_ids == kernel.runtime.active.active_ids
    store = ProjectStore(tmp_path / "saved")
    store.save(project)
    assert store.load() == project
    reopened = InProcessTestKernel(
        ProjectAuthority(project), extensions=registry, evidence_store=EvidenceStore(tmp_path)
    )
    assert get_evidence(reopened, first.id) == first


def test_non_python_admission_does_not_require_valid_python():
    session = example_session("hello_world")
    authored = session.authority.snapshot()
    function = authored.program_model.functions[0]
    output = function.body.statements[0]
    output = replace(
        output,
        expression=make_program_expression(output.id, "expression", "(", ExpressionRole.VALUE),
    )
    program = replace(
        authored.program_model,
        functions=(replace(function, body=replace(function.body, statements=(output,))),),
    )
    project = replace(authored, program_model=program, domain_workspace=_source().domain_workspace)
    kernel = InProcessTestKernel(ProjectAuthority(project), extensions=_registry())
    assert execute_computation(kernel, _request(project)).outcome is ComputationOutcome.SUCCEEDED
    with pytest.raises(Exception, match="Build blocked"):
        generate_python(project, extensions=_registry())
    session.close()


def test_python_backend_uses_existing_generation_and_trace_with_data_only_models():
    session = example_session("hello_world")
    project = replace(session.authority.snapshot(), domain_workspace=_source().domain_workspace)
    registry = _registry()
    generated = generate_python(project, extensions=registry)
    assert "Hello, world!" in generated.source
    assert prepare_build(project, registry).transformations == ()
    with pytest.raises(TransformationError) as error:
        prepare_build(project, registry, model_ids=("source:model",))
    assert error.value.code == "TRANSFORM_NO_PATH"
    kernel = InProcessTestKernel(ProjectAuthority(project), extensions=registry)
    evidence = execute_computation(
        kernel, ComputationRequest(project.id, project.revision, "code_visualizer.python", "1")
    )
    assert evidence.outcome is ComputationOutcome.SUCCEEDED
    assert (
        next(item.value for item in evidence.observations if item.id == "python:stdout")
        == "Hello, world!\n"
    )
    assert any(item.id.startswith("python:trace:") for item in evidence.observations)
    assert evidence.provenance.transformations == ()
    session.close()


@pytest.mark.parametrize("scope", (("another-schema", "1"), ("source", "2")))
def test_declared_multistage_python_route_cannot_silently_skip_unsupported_schema(scope):
    session = example_session("hello_world")
    try:
        authored = session.authority.snapshot()
        project = replace(authored, domain_workspace=_source().domain_workspace)

        def forbidden(_snapshot):
            pytest.fail("An ineligible schema must never execute a borrowed transformation")

        first = RegisteredTransformation(
            TransformationDefinition(
                "source-to-ir", "1", Representation("source"), Representation("terminal")
            ),
            forbidden,
            *scope,
            "terminal",
            "1",
        )
        second = RegisteredTransformation(
            TransformationDefinition(
                "ir-to-program",
                "1",
                Representation("terminal"),
                PROGRAM_REPRESENTATION,
                (first.definition.key,),
            ),
            forbidden,
            "terminal",
            "1",
        )
        registry = _registry(steps=(first, second))
        with pytest.raises(TransformationError) as error:
            prepare_build(project, registry)
        assert error.value.code == "TRANSFORM_NO_PATH"
        narrowed = prepare_build(project, registry, model_ids=())
        assert narrowed.project.program_model == authored.program_model
        assert narrowed.transformations == ()

        unrelated_schema = _schema("reference-only")
        unrelated_model = DomainModel(
            "reference-only:model",
            unrelated_schema.id,
            "1",
            ("reference-only:node",),
            (
                IntentionalNode(
                    "reference-only:node",
                    "reference-only:value",
                    (PropertyValue("reference-only:amount", 5),),
                ),
            ),
        )
        unrelated = replace(
            authored,
            domain_workspace=DomainWorkspace((unrelated_schema,), (unrelated_model,)),
        )
        built = prepare_build(unrelated, registry)
        assert built.project.program_model == authored.program_model
        assert built.transformations == ()
    finally:
        session.close()


def test_backend_registration_discovery_and_missing_implementation():
    project, registry = _source(), _registry()
    view = workbench_snapshot(project, registry)
    assert view.diagnostics == ()
    assert [(item.model_id, item.backend_id) for item in view.computation_routes] == [
        ("source:model", "test.backend")
    ]
    with pytest.raises(ValueError, match="Ambiguous extension"):
        DomainExtensionRegistry(
            (*registry.bundles(), replace(registry.bundles()[-1], id="other.bundle"))
        )
    with pytest.raises(TransformationError) as error:
        prepare_computation(project, replace(_request(project), backend_version="2"), registry)
    assert error.value.code == "COMPUTATION_BACKEND_MISSING"
    with pytest.raises(TransformationError) as error:
        prepare_computation(project, replace(_request(project), revision=1), registry)
    assert error.value.code == "COMPUTATION_REVISION"


def test_ambiguous_transformations_and_unknown_observation_origins_are_rejected_before_runtime():
    project = _source()
    existing = _registry().transformations()[0]
    conflicting = replace(existing, definition=replace(existing.definition, id="competing"))
    with pytest.raises(TransformationError) as error:
        prepare_computation(project, _request(project), _registry(steps=(existing, conflicting)))
    assert error.value.code == "TRANSFORM_AMBIGUOUS_PATH"
    kernel = InProcessTestKernel(
        ProjectAuthority(project),
        extensions=_registry(
            lambda _snapshot: BackendResult(
                observations=(EvidenceObservation("bad", ("absent",), 4),)
            )
        ),
    )
    with pytest.raises(TransformationError) as error:
        execute_computation(kernel, _request(project))
    assert error.value.code == "COMPUTATION_ORIGIN_UNKNOWN"
    assert kernel.runtime.sessions() == ()
    assert kernel.runtime.evidence_records() == ()


def test_missing_bundle_is_never_skipped_as_reference_only_data():
    project = _source()
    workspace = replace(
        project.domain_workspace, bundle_references=(BundleReference("missing", "1"),)
    )
    project = replace(project, domain_workspace=workspace)
    with pytest.raises(TransformationError) as error:
        prepare_build(project, _registry())
    assert error.value.code == "DOMAIN_EXTENSION_MISSING"


def test_resource_outputs_are_published_as_evidence_not_project_state(tmp_path):
    project = _source()

    def backend(snapshot):
        return replace(
            _backend(snapshot),
            produced_resources=(
                ProducedResource("file", b"six\n", "text/plain", ("derived:node",)),
            ),
        )

    kernel = InProcessTestKernel(
        ProjectAuthority(project),
        extensions=_registry(backend),
        resource_store=ResourceStore(tmp_path),
        evidence_store=EvidenceStore(tmp_path),
    )
    evidence = execute_computation(kernel, _request(project))
    artifact = evidence.artifacts[0]
    assert kernel.resource_store.read(artifact.resource) == b"six\n"
    assert evidence.provenance.origins.sources(artifact.semantic_ids[0]) == ("source:node",)
    assert kernel.authority.snapshot() == project
    without_store = InProcessTestKernel(ProjectAuthority(project), extensions=_registry(backend))
    with pytest.raises(TransformationError) as error:
        execute_computation(without_store, _request(project))
    assert error.value.code == "COMPUTATION_RESOURCE_STORE"
    assert without_store.runtime.active is None


def test_request_codecs_and_closed_immutable_evidence_values():
    request = replace(_request(_source()), configuration=(ComputationParameter("tolerance", 0.1),))
    assert computation_request_from_data(computation_request_to_data(request)) == request
    for raw in ({}, {**computation_request_to_data(request), "callback": "unsafe"}):
        with pytest.raises(ValueError):
            computation_request_from_data(raw)
    with pytest.raises(ValueError):
        ComputationParameter("payload", {"untyped": True})
    with pytest.raises(ValueError):
        EvidenceObservation("result", ["mutable"], 1)
    with pytest.raises(ValueError):
        BackendResult(observations=[])
    with pytest.raises(ValueError):
        replace(request, seed=True)


def test_portable_plan_reconstructs_terminal_without_editor_authority(tmp_path):
    project, registry = _source(), _registry()
    store = ResourceStore(tmp_path)
    kernel = InProcessTestKernel(
        ProjectAuthority(project), extensions=registry, resource_store=store
    )
    plan = export_computation_plan(kernel, _request(project))
    assert computation_plan_from_data(computation_plan_to_data(plan)) == plan
    local = execute_computation(kernel, _request(project))
    # Only the plan, content-addressed resource store, and trusted implementations
    # cross the worker boundary. No project factory or authority enters it.
    assert run_computation_plan(plan, registry, store) == local
    with pytest.raises(TransformationError) as error:
        run_computation_plan(replace(plan, input_digest="a" * 64), registry, store)
    assert error.value.code == "COMPUTATION_PLAN_MISMATCH"
    source = store.verified_path(plan.model)
    source.write_bytes(b"corrupt terminal")
    with pytest.raises(ValueError):
        run_computation_plan(plan, registry, store)
    assert kernel.authority.snapshot() == project


def test_cross_model_resource_dependencies_are_explicit_and_exclude_unrelated_data(tmp_path):
    store = ResourceStore(tmp_path)
    descriptor = store.put(b"input value", "text/plain")
    reference = ResourceReference(descriptor.id, descriptor.content_hash)
    unused = ResourceReference("resource:" + "a" * 64, "b" * 64)
    project = _source()
    source_schema = project.domain_workspace.schemas[0]
    concept = source_schema.concepts[0]
    concept = replace(
        concept,
        reference_roles=(RoleDefinition("source:input", "Input", ("dependency:value",), 1, 1),),
    )
    source_schema = replace(source_schema, concepts=(concept,))
    dependency_schema = _schema("dependency")
    dependency_concept = dependency_schema.concepts[0]
    dependency_schema = replace(
        dependency_schema,
        concepts=(
            replace(
                dependency_concept,
                properties=(
                    replace(dependency_concept.properties[0], value_kind=ValueKind.RESOURCE),
                ),
            ),
        ),
    )
    model = project.domain_workspace.models[0]
    model = replace(
        model,
        nodes=(
            replace(
                model.nodes[0], references=(RoleBinding("source:input", ("dependency:node",)),)
            ),
        ),
    )
    inputs = DomainModel(
        "dependency:model",
        "dependency",
        "1",
        ("dependency:node", "dependency:unused"),
        (
            IntentionalNode(
                "dependency:node",
                "dependency:value",
                (PropertyValue("dependency:amount", reference),),
            ),
            IntentionalNode(
                "dependency:unused",
                "dependency:value",
                (PropertyValue("dependency:amount", unused),),
            ),
        ),
    )
    project = replace(
        project,
        domain_workspace=DomainWorkspace((source_schema, dependency_schema), (model, inputs)),
    )

    def evaluate(snapshot):
        assert tuple(node.id for model in snapshot.dependency_models for node in model.nodes) == (
            "dependency:node",
        )
        assert snapshot.resources[0].data == b"input value"
        return BackendResult(
            observations=(
                EvidenceObservation(
                    "dependency-result", ("source:node", "dependency:node"), "input value"
                ),
            )
        )

    backend = RegisteredBackend(
        BackendDefinition(
            "test.backend", "1", "Reference backend", Representation("source"), "source", "1"
        ),
        evaluate,
    )
    registry = DomainExtensionRegistry(
        (
            computation_bundle(),
            intentional_bundle(),
            DomainExtensionBundle("test.dependencies", "1", backends=(backend,)),
        )
    )
    kernel = InProcessTestKernel(
        ProjectAuthority(project), extensions=registry, resource_store=store
    )
    evidence = execute_computation(kernel, _request(project))
    assert evidence.provenance.resources == (reference,)
    assert evidence.provenance.origins.sources("dependency:node") == ("dependency:node",)
    plan = export_computation_plan(kernel, _request(project))
    assert run_computation_plan(plan, registry, store) == evidence
    assert kernel.authority.snapshot() == project


def test_existing_output_resource_content_is_verified_before_recording_evidence(tmp_path):
    store = ResourceStore(tmp_path)
    descriptor = store.put(b"intact", "text/plain")
    reference = ResourceReference(descriptor.id, descriptor.content_hash)
    store.verified_path(reference).write_bytes(b"broken")

    def backend(snapshot):
        return replace(
            _backend(snapshot),
            artifacts=(EvidenceArtifact("artifact", reference, ("derived:node",)),),
        )

    project = _source()
    kernel = InProcessTestKernel(
        ProjectAuthority(project), extensions=_registry(backend), resource_store=store
    )
    with pytest.raises(ValueError):
        execute_computation(kernel, _request(project))
    assert kernel.runtime.sessions() == ()
    assert kernel.runtime.evidence_records() == ()


def test_incomplete_non_python_domain_is_diagnostic_before_backend_execution():
    project = _source()
    model = project.domain_workspace.models[0]
    model = replace(model, nodes=(replace(model.nodes[0], properties=()),))
    project = replace(project, domain_workspace=replace(project.domain_workspace, models=(model,)))
    with pytest.raises(TransformationError) as error:
        prepare_computation(project, _request(project), _registry())
    assert error.value.code == "DOMAIN_PROPERTY_REQUIRED"


def test_evidence_retains_old_revision_through_edit_undo_redo():
    from code_visualizer.application.domain_commands import SetDomainProperty
    from code_visualizer.application.messages import CommandAccepted
    from code_visualizer.sdk.client import CodeVisualizerClient

    project = _source()
    kernel = InProcessTestKernel(ProjectAuthority(project), extensions=_registry())
    client = CodeVisualizerClient(kernel.authority, actor_id="computation-test")
    evidence = execute_computation(kernel, _request(project))
    assert isinstance(
        client.submit(SetDomainProperty("source:model", "source:node", "source:amount", 5)),
        CommandAccepted,
    )
    assert kernel.runtime.active.project_revision == 0
    table = next(
        notation for notation in kernel.notations("source:model") if notation.kind.value == "table"
    )
    projection = kernel.notation("source:model", table.id)
    assert projection.revision == 1 and projection.runtime_revision == 0
    assert projection.rows[0].cells[0].value == 5
    assert get_evidence(kernel, evidence.id).observations[0].value == 6
    assert isinstance(client.undo(), CommandAccepted)
    assert (
        kernel.authority.snapshot().domain_workspace.node("source:node").property("source:amount")
        == 3
    )
    assert isinstance(client.redo(), CommandAccepted)
    latest = kernel.authority.snapshot()
    assert execute_computation(kernel, _request(latest)).observations[0].value == 10


@pytest.mark.parametrize("suffix", (".json", ".pb"))
def test_cli_compute_export_and_run_plan_use_durable_stores_without_project_for_worker(
    tmp_path, capsys, suffix
):
    import json

    from code_visualizer.cli import main

    session = example_session("hello_world")
    project = session.authority.snapshot()
    session.close()
    store = ProjectStore(tmp_path)
    store.save(project)
    original = store.project_file.read_bytes()
    assert main(["compute", str(tmp_path), "--backend", "code_visualizer.python"]) == 0
    evidence = evidence_from_data(json.loads(capsys.readouterr().out))
    assert evidence.provenance.terminal_resource is not None
    plan_file = tmp_path / ("execution.plan" + suffix)
    assert (
        main(
            [
                "export-plan",
                str(tmp_path),
                "--backend",
                "code_visualizer.python",
                "--output",
                str(plan_file),
            ]
        )
        == 0
    )
    capsys.readouterr()
    offline = tmp_path / "project.offline"
    store.project_file.rename(offline)
    try:
        assert main(["run-plan", str(plan_file), "--resources", str(tmp_path)]) == 0
        replayed = evidence_from_data(json.loads(capsys.readouterr().out))
        assert replayed == evidence
    finally:
        offline.rename(store.project_file)
    assert store.project_file.read_bytes() == original


def test_python_backend_publishes_oversized_stdout_as_typed_resource(tmp_path):
    session = example_session("hello_world")
    project = session.authority.snapshot()
    function = project.program_model.functions[0]
    output = function.body.statements[0]
    output = replace(
        output,
        expression=make_program_expression(
            output.id, "expression", "'x' * 70000", ExpressionRole.VALUE
        ),
    )
    function = replace(function, body=replace(function.body, statements=(output,)))
    project = replace(project, program_model=replace(project.program_model, functions=(function,)))
    kernel = ProjectKernel(ProjectAuthority(project), resource_store=ResourceStore(tmp_path))
    evidence = execute_computation(
        kernel, ComputationRequest(project.id, project.revision, "code_visualizer.python", "1")
    )
    assert evidence.outcome is ComputationOutcome.SUCCEEDED
    artifact = next(item for item in evidence.artifacts if item.id == "python:stdout")
    assert kernel.resource_store.read(artifact.resource) == b"x" * 70000 + b"\n"
    assert all(item.id != "python:stdout" for item in evidence.observations)
    assert evidence.provenance.terminal_resource is not None
    session.close()


def test_portable_contract_rejects_legacy_defaults_unknown_fields_and_numeric_type_drift(tmp_path):
    import copy
    import json

    from code_visualizer.domain.resources import TERMINAL_LOGICAL_TYPE
    from code_visualizer.persistence.canonical import canonical_data_bytes
    from code_visualizer.persistence.computation_terminal import TERMINAL_MEDIA_TYPE

    project, registry = _source(), _registry()
    store = ResourceStore(tmp_path)
    kernel = InProcessTestKernel(
        ProjectAuthority(project), extensions=registry, resource_store=store
    )
    request = replace(_request(project), configuration=(ComputationParameter("setting", 1),))
    plan = export_computation_plan(kernel, request)
    payload = json.loads(store.read(plan.model))
    assert [schema["id"] for schema in payload["schemas"]] == ["terminal"]
    assert payload["dependencies"] == []
    unknown = copy.deepcopy(payload)
    unknown["value"]["uninterpreted"] = "must not be dropped"
    omitted = copy.deepcopy(payload)
    omitted["schemas"][0].pop("description")
    for changed in (unknown, omitted):
        descriptor = store.put(
            canonical_data_bytes(changed),
            TERMINAL_MEDIA_TYPE,
            logical_type=TERMINAL_LOGICAL_TYPE,
        )
        with pytest.raises(TransformationError) as error:
            run_computation_plan(
                replace(plan, model=ResourceReference(descriptor.id, descriptor.content_hash)),
                registry,
                store,
            )
        assert error.value.code == "COMPUTATION_TERMINAL_FORMAT"
    changed_request = replace(plan.request, configuration=(ComputationParameter("setting", 1.0),))
    with pytest.raises(TransformationError) as error:
        run_computation_plan(replace(plan, request=changed_request), registry, store)
    assert error.value.code == "COMPUTATION_PLAN_MISMATCH"
    assert ComputationParameter("setting", 1) != ComputationParameter("setting", 1.0)
    assert EvidenceObservation("observation", (), -0.0) != EvidenceObservation(
        "observation", (), 0.0
    )
