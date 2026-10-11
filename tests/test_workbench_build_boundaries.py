"""Adversarial proofs for public build and runtime identity boundaries."""

from dataclasses import replace

import pytest

from code_visualizer.application.runtime_sessions import RuntimeSessionRegistry
from code_visualizer.domain.intentional import DomainModel
from code_visualizer.domain.program import (
    ProgramModel,
    ProgramSequence,
    ProgramSymbol,
    ProgramSymbolKind,
)
from code_visualizer.domain.transformation import (
    OriginLink,
    OriginMap,
    Representation,
    TransformationDefinition,
)
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.fsm import FSM_TRANSFORMATION, lower_fsm, traffic_light_project
from code_visualizer.extensions.registry import DomainExtensionRegistry
from code_visualizer.generation.build import prepare_build, program_identities
from code_visualizer.generation.transformation import (
    RegisteredTransformation,
    TransformationError,
    TransformationInput,
    TransformationResult,
    execute_transformations,
)


def test_public_build_rejects_incomplete_source_before_domain_specific_lowering():
    project = traffic_light_project()
    model = project.domain_workspace.models[0]
    machine = model.node(model.roots[0])
    incomplete = replace(machine, references=())
    model = replace(
        model, nodes=tuple(incomplete if item.id == machine.id else item for item in model.nodes)
    )
    project = replace(project, domain_workspace=replace(project.domain_workspace, models=(model,)))
    with pytest.raises(TransformationError) as caught:
        prepare_build(project)
    assert "REQUIRED" in caught.value.code


def test_public_build_rejects_duplicate_generated_objects_inside_one_contribution():
    project = traffic_light_project()
    bundle = builtin_registry().get("org.codevisualizer.fsm", "1")
    assert bundle is not None

    def duplicate(snapshot):
        result = lower_fsm(snapshot)
        invalid = replace(
            result.value, functions=(*result.value.functions, *result.value.functions)
        )
        return replace(result, value=invalid)

    registry = DomainExtensionRegistry(
        (
            replace(
                bundle, transformations=(RegisteredTransformation(FSM_TRANSFORMATION, duplicate),)
            ),
        )
    )
    with pytest.raises(TransformationError):
        prepare_build(project, registry)


def test_execute_rejects_missing_dependencies_even_when_called_without_planner():
    project = traffic_light_project()
    model = project.domain_workspace.models[0]
    source, target = Representation("source"), Representation("target")
    definition = TransformationDefinition("step", "1", source, target, ("missing@1",))
    step = RegisteredTransformation(
        definition, lambda snapshot: TransformationResult(target, snapshot.value, snapshot.origins)
    )
    snapshot = TransformationInput(
        project, model, source, model, OriginMap(project.id, project.revision)
    )
    with pytest.raises(TransformationError):
        execute_transformations(snapshot, (step,))


@pytest.mark.parametrize("origins", [OriginLink("generated", ("",)), OriginLink("", ("source",))])
def test_origin_identity_values_cannot_be_empty(origins):
    with pytest.raises(ValueError):
        OriginMap("project", 0, (origins,))


def test_starting_existing_runtime_session_cannot_overwrite_pinned_origin_revision():
    registry = RuntimeSessionRegistry(project_id="project")
    registry.mark_starting("session", 3, 3)
    registry.register_origins(
        "session", OriginMap("project", 3, (OriginLink("generated", ("source",)),))
    )
    with pytest.raises(ValueError):
        registry.mark_starting("session", 4, 4)
    assert registry.active.project_revision == 3


def test_runtime_start_checks_pre_registered_origins_without_existing_state():
    registry = RuntimeSessionRegistry(project_id="project")
    registry.register_origins("session", OriginMap("project", 3))
    with pytest.raises(ValueError, match="pinned revisions"):
        registry.mark_starting("session", 4, 4)
    assert registry.active is None
    assert registry.mark_starting("session", 3, 3).project_revision == 3


def test_derived_sequence_identity_cannot_be_shared_by_two_functions():
    project = traffic_light_project()
    bundle = builtin_registry().get("org.codevisualizer.fsm", "1")
    assert bundle is not None

    def duplicate_containment(snapshot):
        template = lower_fsm(snapshot).value.functions[0]
        functions = tuple(
            replace(
                template,
                id=f"derived:function:{name}",
                symbol_id=f"derived:symbol:{name}",
                identifier=name,
                parameters=(),
                body=ProgramSequence("derived:shared-sequence"),
            )
            for name in ("a", "b")
        )
        symbols = tuple(
            ProgramSymbol(
                function.symbol_id,
                function.identifier,
                ProgramSymbolKind.FUNCTION,
                function.id,
                function.id,
            )
            for function in functions
        )
        model = ProgramModel(functions, symbols)
        origins = OriginMap(
            project.id,
            project.revision,
            tuple(
                OriginLink(identity, (snapshot.model.roots[0],))
                for identity in sorted(program_identities(model))
            ),
        )
        return TransformationResult(FSM_TRANSFORMATION.target, model, origins, (functions[0].id,))

    registry = DomainExtensionRegistry(
        (
            replace(
                bundle,
                transformations=(
                    RegisteredTransformation(FSM_TRANSFORMATION, duplicate_containment),
                ),
            ),
        )
    )
    with pytest.raises(TransformationError):
        prepare_build(project, registry)


def test_source_snapshot_model_cannot_claim_another_representation_than_its_plan():
    project = traffic_light_project()
    model = DomainModel("model", "schema", "1")
    first = Representation("source")
    second = Representation("target")
    step = RegisteredTransformation(
        TransformationDefinition("step", "1", first, second),
        lambda snapshot: TransformationResult(second, snapshot.value, snapshot.origins),
    )
    snapshot = TransformationInput(
        project, model, Representation("unrelated"), model, OriginMap(project.id, project.revision)
    )
    with pytest.raises(TransformationError) as caught:
        execute_transformations(snapshot, (step,))
    assert caught.value.code in {"TRANSFORM_INPUT", "TRANSFORM_NO_PATH"}
