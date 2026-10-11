from dataclasses import replace

import pytest

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.domain import notation_syntax as v
from code_visualizer.domain.intentional import (
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
from code_visualizer.domain.language import AuthoredDomainLanguage
from code_visualizer.domain.language_validation import validate_authored_language
from code_visualizer.domain.notation import NotationDefinition, NotationKind
from code_visualizer.domain.notation_validation import validate_composed_notation
from code_visualizer.domain.project import Project


def workspace():
    part = ConceptDefinition(
        "part",
        "Part",
        (PropertyDefinition("name", "Name"), PropertyDefinition("x", "X", ValueKind.NUMBER)),
        reference_roles=(RoleDefinition("next", "Next", ("part",)),),
    )
    assembly = ConceptDefinition(
        "assembly", "Assembly", containment_roles=(RoleDefinition("parts", "Parts", ("part",)),)
    )
    mechanical = DomainSchema("mechanical", "example.mechanical", "1", (assembly, part))
    control = DomainSchema(
        "control",
        "example.control",
        "2",
        (
            ConceptDefinition(
                "controller", "Controller", (PropertyDefinition("gain", "Gain", ValueKind.NUMBER),)
            ),
        ),
    )
    return DomainWorkspace((mechanical, control), (DomainModel("controls", "control", "2"),))


def findings(body):
    data = workspace()
    return {item.code for item in validate_composed_notation(body, data.schemas[0], data)}


def repeated(body, query=None):
    return v.VisualRepeat("repeat", query or v.NotationObjects("objects", "part"), "p", body)


@pytest.mark.parametrize(
    "query,code",
    [
        (v.NotationObjects("objects", "typo"), "NOTATION_CONCEPT"),
        (
            v.NotationObjects("objects", schema_id="missing", schema_version="1", workspace=True),
            "NOTATION_SCHEMA",
        ),
        (v.NotationObjects("objects", model_id="missing", workspace=True), "NOTATION_MODEL"),
        (v.NotationObjects("objects", model_id="controls"), "NOTATION_MODEL"),
    ],
)
def test_query_selectors_are_checked_against_the_workspace(query, code):
    assert code in findings(repeated(v.VisualText("text"), query))


def test_fields_validate_concept_property_and_reference_paths():
    assert "NOTATION_PROPERTY" in findings(repeated(v.VisualField("field", "p", "typo")))
    assert not findings(repeated(v.VisualField("field", "p", "name", ("next",))))
    assert "NOTATION_ROLE" in findings(repeated(v.VisualField("field", "p", "name", ("parts",))))
    assembly = v.NotationObjects("objects", "assembly")
    assert "NOTATION_ROLE" in findings(
        repeated(v.VisualField("field", "p", "name", ("parts",)), assembly)
    )


def test_numeric_layout_uses_declared_numeric_properties():
    number = v.VisualNumber("x-value", property_id="name")
    body = repeated(
        v.VisualPosition("position", v.VisualText("text"), number, v.VisualNumber("y-value"))
    )
    assert "NOTATION_PROPERTY_TYPE" in findings(body)
    assert not findings(replace(body, body=replace(body.body, x=replace(number, property_id="x"))))
    # A constant has no object lookup and does not require a binding.
    assert not findings(
        v.VisualPosition(
            "position",
            v.VisualText("text"),
            v.VisualNumber("x", binding_id="unused"),
            v.VisualNumber("y"),
        )
    )


def test_semantic_relation_queries_allow_cross_schema_union_bindings():
    joined = v.VisualRepeat(
        "joined",
        v.NotationRelated("relations", "p", relation_kind="uses"),
        "target",
        v.VisualField("gain-field", "target", "gain"),
    )
    assert not findings(repeated(joined))
    assert "NOTATION_PROPERTY" in findings(
        repeated(replace(joined, body=v.VisualField("wrong-field", "target", "unknown")))
    )


def test_domain_role_queries_narrow_to_declared_target_concepts():
    nested = v.VisualRepeat(
        "children",
        v.NotationRelated("related", "p", role_id="parts"),
        "child",
        v.VisualField("field", "child", "name"),
    )
    assert not findings(repeated(nested, v.NotationObjects("objects", "assembly")))
    assert "NOTATION_ROLE" in findings(repeated(nested))


def test_comparison_and_integer_geometry_limits_are_explicit():
    condition = v.VisualConditional(
        "conditional",
        v.VisualPredicate("predicate", "p", "x", v.VisualComparison.LESS, "text"),
        v.VisualText("text"),
    )
    assert "NOTATION_PROPERTY_TYPE" in findings(repeated(condition))
    assert "NOTATION_NUMBER" in findings(v.VisualText("text", font_size=10**7))


def test_kernel_supplies_derived_semantic_relations_to_composed_notations():
    data = workspace()
    first = IntentionalNode(
        "first",
        "part",
        (PropertyValue("name", "Motor"),),
        references=(RoleBinding("next", ("second",)),),
    )
    second = IntentionalNode("second", "part", (PropertyValue("name", "Gearbox"),))
    model = DomainModel("parts-model", "mechanical", "1", (first.id, second.id), (first, second))
    body = repeated(
        v.VisualRepeat(
            "links",
            v.NotationRelated(
                "derived-query", "p", relation_kind="references", relation_label="Next"
            ),
            "target",
            v.VisualField("target-name", "target", "name"),
        )
    )
    notation = NotationDefinition(
        "linked", "Linked parts", NotationKind.COMPOSED, schema_id="mechanical", body=body
    )
    language = AuthoredDomainLanguage(
        "mechanical-language", "mechanical", "1", notations=(notation,)
    )
    project = Project(
        "joined",
        "Joined",
        (),
        domain_workspace=replace(data, models=(model,), language_definitions=(language,)),
    )
    kernel = ProjectKernel(ProjectAuthority(project))
    try:
        assert project.semantic_relations == ()
        canvas = kernel.notation(model.id, notation.id).canvas
        assert canvas is not None
        assert [(item.semantic_ids, item.text) for item in canvas.items] == [
            (("second",), "Gearbox")
        ]
    finally:
        kernel.close()


def test_schema_compilation_does_not_treat_missing_instance_context_as_empty_workspace():
    data = workspace()
    body = repeated(
        v.VisualField("gain", "p", "gain"),
        v.NotationObjects(
            "query", "controller", "control", "2", model_id="controls", workspace=True
        ),
    )
    notation = NotationDefinition(
        "explicit-model", "Controls", NotationKind.COMPOSED, schema_id="mechanical", body=body
    )
    language = AuthoredDomainLanguage("language", "mechanical", "1", notations=(notation,))
    assert not validate_authored_language(language, data.schemas[0], schemas=data.schemas)
    assert not validate_composed_notation(body, data.schemas[0], data)
    empty = replace(data, models=())
    assert "NOTATION_MODEL" in {
        issue.code for issue in validate_composed_notation(body, data.schemas[0], empty)
    }
