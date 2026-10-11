import pytest

from code_visualizer.domain.transformation import Representation, TransformationDefinition
from code_visualizer.generation.transformation import (
    MAX_PLAN_TRANSFORMATIONS,
    RegisteredTransformation,
    TransformationError,
    declared_transformation_sources,
    plan_transformations,
)


def step(identity, source, target):
    def unexecuted(snapshot):
        raise AssertionError("Planning must never execute a transformation")

    return RegisteredTransformation(
        TransformationDefinition(identity, "1", Representation(source), Representation(target)),
        unexecuted,
    )


def test_planner_bounds_registration_iterables_before_recursion_or_sorting():
    entries = (
        step(str(index), str(index), str(index + 1))
        for index in range(MAX_PLAN_TRANSFORMATIONS + 1)
    )
    with pytest.raises(TransformationError) as result:
        plan_transformations(entries, Representation("0"), Representation("target"))
    assert result.value.code == "TRANSFORM_LIMIT"


def test_planner_diagnoses_path_explosion_instead_of_unbounded_search():
    entries = tuple(
        step(f"{index}:{variant}", str(index), str(index + 1))
        for index in range(20)
        for variant in range(2)
    )
    with pytest.raises(TransformationError) as result:
        plan_transformations(entries, Representation("0"), Representation("unreachable"))
    assert result.value.code == "TRANSFORM_LIMIT"


def test_declared_route_query_is_bounded_and_keeps_exact_representation_versions():
    entries = (step("first", "source", "ir"), step("second", "ir", "program"))
    expected = frozenset(Representation(name) for name in ("source", "ir", "program"))
    assert declared_transformation_sources(entries, Representation("program")) == expected
    assert declared_transformation_sources(reversed(entries), Representation("program")) == expected
    assert Representation("source", "2") not in expected
    oversized = (
        step(str(index), str(index), str(index + 1))
        for index in range(MAX_PLAN_TRANSFORMATIONS + 1)
    )
    with pytest.raises(TransformationError) as result:
        declared_transformation_sources(oversized, Representation("program"))
    assert result.value.code == "TRANSFORM_LIMIT"


def test_cycle_diagnostic_is_independent_of_registration_and_set_iteration_order():
    entries = (step("a", "0", "1"), step("b", "1", "0"), step("c", "0", "2"), step("d", "2", "0"))
    messages = []
    for registration in (entries, tuple(reversed(entries))):
        with pytest.raises(TransformationError) as result:
            plan_transformations(registration, Representation("0"), Representation("target"))
        assert result.value.code == "TRANSFORM_REPRESENTATION_CYCLE"
        messages.append(str(result.value))
    assert messages[0] == messages[1]
