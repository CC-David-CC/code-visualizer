"""Domain intentions use the mature generator and return through its runtime plane."""

from dataclasses import replace

import pytest

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.domain_execution import debug_project, trace_project
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.runtime_sessions import (
    RuntimeSessionRegistry,
    RuntimeSessionStatus,
)
from code_visualizer.domain.intentional import PropertyValue
from code_visualizer.domain.program import ProgramModel, program_statements
from code_visualizer.domain.transformation import (
    OriginLink,
    OriginMap,
    Representation,
    TransformationDefinition,
    derived_id,
)
from code_visualizer.execution import DebugEvent, DebugState, run_generated
from code_visualizer.extensions.builtin import builtin_registry, computation_bundle, program_bundle
from code_visualizer.extensions.fsm import (
    FSM_REPRESENTATION,
    FSM_TRANSFORMATION,
    traffic_light_project,
)
from code_visualizer.extensions.registry import (
    DomainExtensionRegistry,
    GeneratorInput,
)
from code_visualizer.generation import generate_python, generate_python_project, generate_to_disk
from code_visualizer.generation.build import prepare_build, program_identities
from code_visualizer.generation.transformation import (
    RegisteredTransformation,
    TransformationError,
    TransformationResult,
    plan_transformations,
)
from code_visualizer.persistence import ProjectStore
from code_visualizer.persistence.serialization import project_to_data
from code_visualizer.validation import assess_project


def _step(
    identity: str, source: str, target: str, depends: tuple[str, ...] = ()
) -> RegisteredTransformation:
    definition = TransformationDefinition(
        identity, "1", Representation(source), Representation(target), depends
    )
    return RegisteredTransformation(
        definition,
        lambda snapshot: TransformationResult(definition.target, snapshot.value, snapshot.origins),
    )


def test_transformations_follow_representation_dependencies_independent_of_registration_order() -> (
    None
):
    first = _step("first", "domain", "normalized")
    second = _step("second", "normalized", "program", ("first@1",))
    for registrations in ((first, second), (second, first)):
        plan = plan_transformations(
            registrations, Representation("domain"), Representation("program")
        )
        assert plan == (first, second)


@pytest.mark.parametrize(
    ("steps", "code"),
    (
        ((_step("one", "a", "b"), _step("two", "a", "b")), "TRANSFORM_AMBIGUOUS_PATH"),
        ((_step("one", "a", "b"), _step("two", "b", "a")), "TRANSFORM_REPRESENTATION_CYCLE"),
        (
            (_step("one", "a", "b", ("two@1",)), _step("two", "b", "c", ("one@1",))),
            "TRANSFORM_DEPENDENCY_CYCLE",
        ),
        ((_step("one", "a", "b", ("absent@1",)),), "TRANSFORM_MISSING_DEPENDENCY"),
        ((_step("one", "a", "b"), _step("one", "a", "b")), "TRANSFORM_DUPLICATE"),
        ((_step("one", "a", "c"),), "TRANSFORM_NO_PATH"),
    ),
)
def test_invalid_transformation_graphs_fail_explicitly(steps, code: str) -> None:
    with pytest.raises(TransformationError) as caught:
        plan_transformations(steps, Representation("a"), Representation("b"))
    assert caught.value.code == code


def test_origin_composition_keeps_all_high_level_causes_and_revision() -> None:
    previous = OriginMap("project", 3, (OriginLink("middle", ("state", "transition")),))
    current = OriginMap("project", 3, (OriginLink("operation", ("middle", "action")),))
    assert current.composed_with(previous).sources("operation") == ("action", "state", "transition")
    with pytest.raises(ValueError, match="same project revision"):
        current.composed_with(replace(previous, revision=4))
    with pytest.raises(ValueError, match="duplicate"):
        OriginMap("project", 3, (OriginLink("same", ("a",)), OriginLink("same", ("b",))))
    assert derived_id("extension@1", "object", "role") == derived_id(
        "extension@1", "object", "role"
    )
    assert derived_id("extension@1", "object", "role") != derived_id("other@1", "object", "role")


def test_fsm_build_is_deterministic_complete_and_disposable() -> None:
    project = traffic_light_project()
    canonical_data = project_to_data(project)
    first = prepare_build(project)
    assert first == prepare_build(project)
    assert first.transformations == (FSM_TRANSFORMATION.key,)
    assert project.program_model == ProgramModel()
    assert first.project.program_model.functions
    assert first.project.domain_workspace is project.domain_workspace
    assert first.project.program_model.entrypoint_callable_id is not None
    assert project.program_model.entrypoint_callable_id is None
    assert program_identities(first.project.program_model) == {
        link.generated_id for link in first.origins.links
    }
    assert all(
        set(link.source_ids) <= {node.id for node in project.domain_workspace.models[0].nodes}
        for link in first.origins.links
    )
    assert assess_project(first.project).buildable
    assert project_to_data(project) == canonical_data


def test_rename_changes_generated_labels_without_replacing_intention_or_derived_ids() -> None:
    project = traffic_light_project()
    model = project.domain_workspace.models[0]
    yellow = model.node("traffic:yellow")
    assert yellow is not None
    amber = replace(yellow, properties=(PropertyValue("fsm:state:name", "Amber"),))
    renamed = replace(
        project,
        domain_workspace=replace(
            project.domain_workspace,
            models=(
                replace(
                    model,
                    nodes=tuple(amber if item.id == amber.id else item for item in model.nodes),
                ),
            ),
        ),
    )
    before = prepare_build(project)
    after = prepare_build(renamed)
    assert program_identities(before.project.program_model) == program_identities(
        after.project.program_model
    )
    assert before.origins == after.origins
    source = generate_python(renamed, include_main=False).source
    assert "Green --timer--> Amber" in source
    assert "Yellow" not in source
    assert renamed.domain_workspace.node("traffic:yellow") is amber


def test_fsm_uses_registered_program_generator_and_existing_disk_execution(tmp_path) -> None:
    project = traffic_light_project()
    build = prepare_build(project)
    generator = next(item for item in builtin_registry().generators() if item.id == "python")
    assert generator.generate(
        GeneratorInput(build.project, build.origins)
    ) == generate_python_project(project)
    store = ProjectStore(tmp_path / "traffic")
    store.initialize(project)
    result = generate_to_disk(project, store.root)
    assert (result.root / "project.origin-map.json").is_file()
    run = run_generated(result.root / "run_project.py")
    assert run.return_code == 0, run.stderr
    assert "Green --timer--> Yellow" in run.stdout
    reloaded = store.recover(promote=False)
    assert reloaded.program_model == ProgramModel()
    assert reloaded.domain_workspace == project.domain_workspace
    assert prepare_build(reloaded) == build


def test_authored_program_and_domain_outputs_compose_only_in_derived_build() -> None:
    from code_visualizer.application.project_factory import create_default_project

    authored = create_default_project()
    project = replace(authored, domain_workspace=traffic_light_project().domain_workspace)
    build = prepare_build(project)
    assert build.project.program_model.functions[0] is project.program_model.functions[0]
    assert len(build.project.program_model.functions) == 2
    assert len(project.program_model.functions) == 1
    assert (
        build.project.program_model.entrypoint_callable_id
        == authored.program_model.entrypoint_callable_id
    )
    assert generate_python_project(project).files


def test_derived_identity_collisions_are_rejected() -> None:
    project = traffic_light_project()
    first = prepare_build(project)
    duplicate = replace(project, program_model=first.project.program_model)
    with pytest.raises(TransformationError) as caught:
        prepare_build(duplicate)
    assert caught.value.code == "TRANSFORM_ID_COLLISION"


@pytest.mark.parametrize("canonical_id", ("traffic:yellow", "fsm:state", "project_traffic_light"))
def test_transform_cannot_reuse_an_existing_domain_or_project_identity(canonical_id: str) -> None:
    project = traffic_light_project()
    bundle = builtin_registry().get("org.codevisualizer.fsm", "1")
    assert bundle is not None
    registered = bundle.transformations[0]

    def collide(snapshot):
        result = registered.transform(snapshot)
        function = result.value.functions[0]
        return replace(
            result,
            value=replace(result.value, functions=(replace(function, id=canonical_id),)),
            origins=replace(
                result.origins,
                links=tuple(
                    replace(link, generated_id=canonical_id)
                    if link.generated_id == function.id
                    else link
                    for link in result.origins.links
                ),
            ),
        )

    extensions = DomainExtensionRegistry(
        (
            computation_bundle(),
            program_bundle(),
            replace(bundle, transformations=(replace(registered, transform=collide),)),
        )
    )
    with pytest.raises(TransformationError) as caught:
        prepare_build(project, extensions)
    assert caught.value.code == "TRANSFORM_ID_COLLISION"


def test_multiple_models_require_an_explicit_derived_entrypoint_selection() -> None:
    project = traffic_light_project()
    original = project.domain_workspace.models[0]
    remapped = {node.id: node.id.replace("traffic:", "other:") for node in original.nodes}
    second = replace(
        original,
        id="other:model",
        roots=tuple(remapped[item] for item in original.roots),
        nodes=tuple(
            replace(
                node,
                id=remapped[node.id],
                children=tuple(
                    replace(role, node_ids=tuple(remapped[item] for item in role.node_ids))
                    for role in node.children
                ),
                references=tuple(
                    replace(role, node_ids=tuple(remapped[item] for item in role.node_ids))
                    for role in node.references
                ),
            )
            for node in original.nodes
        ),
    )
    project = replace(
        project, domain_workspace=replace(project.domain_workspace, models=(second, original))
    )
    with pytest.raises(TransformationError) as caught:
        prepare_build(project)
    assert caught.value.code == "TRANSFORM_ENTRYPOINT_AMBIGUOUS"
    chosen = prepare_build(project, entrypoint_model_id="traffic:model")
    assert len(chosen.project.program_model.functions) == 2
    function_id = chosen.project.program_model.entrypoint_callable_id
    assert function_id is not None
    assert chosen.origins.sources(function_id) == ("traffic:machine",)
    assert generate_python_project(project, entrypoint_model_id="traffic:model").files
    kernel = ProjectKernel(ProjectAuthority(project))
    try:
        result = trace_project(kernel, model_id="traffic:model")
        assert result.run.return_code == 0
        assert any("traffic:green-yellow" in item.origin_ids for item in kernel.runtime.history())
        assert not any("other:green-yellow" in item.origin_ids for item in kernel.runtime.history())
    finally:
        kernel.close()


def test_missing_transform_is_explicit_and_keeps_canonical_data() -> None:
    project = traffic_light_project()
    bundle = builtin_registry().get("org.codevisualizer.fsm", "1")
    assert bundle is not None
    registry = DomainExtensionRegistry(
        (computation_bundle(), program_bundle(), replace(bundle, transformations=()))
    )
    with pytest.raises(TransformationError) as caught:
        prepare_build(project, registry)
    assert caught.value.code == "TRANSFORM_NO_PATH"
    assert project.domain_workspace.models[0].node("traffic:yellow") is not None
    assert project.program_model == ProgramModel()


def test_two_registered_transforms_preserve_origins_to_original_domain_nodes() -> None:
    project = traffic_light_project()
    bundle = builtin_registry().get("org.codevisualizer.fsm", "1")
    assert bundle is not None
    original = bundle.transformations[0]
    intermediate = Representation("org.codevisualizer.fsm.normalized.program")
    first_definition = TransformationDefinition(
        "org.codevisualizer.fsm.normalize", "1", FSM_REPRESENTATION, intermediate
    )
    second_definition = TransformationDefinition(
        "org.codevisualizer.fsm.finalize",
        "1",
        intermediate,
        FSM_TRANSFORMATION.target,
        (first_definition.key,),
    )

    def normalize(snapshot):
        return replace(original.transform(snapshot), representation=intermediate)

    def finalize(snapshot):
        return TransformationResult(
            second_definition.target,
            snapshot.value,
            OriginMap(
                project.id,
                project.revision,
                tuple(
                    OriginLink(identity, (identity,))
                    for identity in sorted(program_identities(snapshot.value))
                ),
            ),
            tuple(function.id for function in snapshot.value.functions),
        )

    extensions = DomainExtensionRegistry(
        (
            computation_bundle(),
            program_bundle(),
            replace(
                bundle,
                transformations=(
                    RegisteredTransformation(second_definition, finalize),
                    RegisteredTransformation(first_definition, normalize),
                ),
            ),
        )
    )
    chained = prepare_build(project, extensions)
    direct = prepare_build(project)
    assert chained.project.program_model == direct.project.program_model
    assert chained.origins == direct.origins
    assert chained.transformations == (first_definition.key, second_definition.key)


def test_trace_returns_generated_operation_and_domain_origins_to_one_runtime_plane() -> None:
    project = traffic_light_project()
    kernel = ProjectKernel(ProjectAuthority(project))
    try:
        trace = trace_project(kernel, model_id="traffic:model")
        assert trace.run.return_code == 0, trace.run.stderr
        history = kernel.runtime.history()
        selected = [
            state
            for state in history
            if {"traffic:green-yellow", "traffic:yellow", "traffic:signal"} <= set(state.origin_ids)
        ]
        assert selected
        assert all(
            state.semantic_id and state.semantic_id.startswith("derived:") for state in selected
        )
        assert all(set(state.origin_ids) <= set(state.active_ids) for state in selected)
        assert kernel.runtime.active is not None
        assert kernel.runtime.active.status is RuntimeSessionStatus.FINISHED
        assert kernel.authority.snapshot() == project
        assert kernel.selection.state.execution_session_id == selected[0].execution_session_id
    finally:
        kernel.close()


def test_existing_debugger_steps_domain_operations_with_pinned_origins() -> None:
    kernel = ProjectKernel(ProjectAuthority(traffic_light_project()))
    debug = debug_project(kernel, model_id="traffic:model")
    operations = {
        statement.id
        for function in debug.snapshot.build.project.program_model.functions
        for statement in program_statements(function.body)
    }
    try:
        active = None
        for _ in range(60):
            event = debug.wait_event()
            if event.event == "paused":
                active = kernel.runtime.active
                if active is not None and "traffic:signal" in active.origin_ids:
                    break
                if active is not None and active.semantic_id in operations:
                    debug.step_over()
                else:
                    debug.step_into()
            if event.event in {"finished", "exception"}:
                pytest.fail(f"Debugger ended before reaching the signal action: {event.detail}")
        assert active is not None
        assert {"traffic:red-green", "traffic:green", "traffic:signal"} <= set(active.origin_ids)
        assert active.project_revision == kernel.revision
        debug.continue_execution()
        while debug.wait_event().event != "finished":
            pass
    finally:
        debug.stop()
        kernel.close()


def test_runtime_origins_cannot_change_project_or_artifact_revision() -> None:
    registry = RuntimeSessionRegistry(project_id="project")
    origins = OriginMap("project", 4, (OriginLink("generated", ("intention",)),))
    registry.register_origins("session", origins)
    event = DebugEvent(
        1,
        "trace",
        DebugState.RUNNING,
        execution_session_id="session",
        project_revision=4,
        artifact_revision=4,
    )
    assert registry.record(event, "generated").origin_ids == ("intention",)
    with pytest.raises(ValueError, match="pinned revisions"):
        registry.record(replace(event, artifact_revision=5), "generated")
    with pytest.raises(ValueError, match="another project"):
        registry.register_origins("other", replace(origins, project_id="other"))
    with pytest.raises(ValueError, match="replace"):
        registry.register_origins("session", replace(origins, links=()))
